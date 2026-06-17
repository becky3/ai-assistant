"""毎日定時実行スケジューラ.

仕様: docs/specs/infrastructure/scheduled-tasks.md

各ジョブを毎日指定時刻に `MessageRouter.process_message` 経由で実行する。
APScheduler 等の外部依存は使わず、asyncio タスクで「次回時刻まで待機 → 実行 →
翌日まで再待機」を繰り返す軽量実装。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from src.messaging.port import IncomingMessage

if TYPE_CHECKING:
    from src.messaging.port import MessagingPort
    from src.messaging.router import MessageRouter
    from src.scheduler.schedule_config import ScheduledJob

logger = logging.getLogger(__name__)


def seconds_until_next(now: datetime, hour: int, minute: int) -> float:
    """now から次回の hour:minute までの秒数を返す（同日が過ぎていれば翌日）."""
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class DailyScheduler:
    """ジョブを毎日指定時刻に実行するスケジューラ.

    仕様: docs/specs/infrastructure/scheduled-tasks.md
    """

    def __init__(
        self,
        jobs: list[ScheduledJob],
        router: MessageRouter,
        messaging: MessagingPort,
        *,
        default_channel: str,
        timezone: str,
    ) -> None:
        self._jobs = jobs
        self._router = router
        self._messaging = messaging
        self._default_channel = default_channel
        self._tz = ZoneInfo(timezone)
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        """全ジョブの実行タスクを起動する."""
        for job in self._jobs:
            self._tasks.append(asyncio.create_task(self._run_job(job)))
        if self._jobs:
            logger.info("定時実行スケジューラを開始しました: %d 件", len(self._jobs))

    async def stop(self) -> None:
        """全ジョブタスクをキャンセルする."""
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _run_job(self, job: ScheduledJob) -> None:
        """1 ジョブを毎日実行し続ける."""
        while True:
            delay = seconds_until_next(datetime.now(tz=self._tz), job.hour, job.minute)
            logger.info(
                "scheduled job 待機: command=%r, %02d:%02d, in %.0fs",
                job.command, job.hour, job.minute, delay,
            )
            await asyncio.sleep(delay)
            await self._fire(job)

    async def _fire(self, job: ScheduledJob) -> None:
        """発火を告知し、スレッド内でジョブのコマンドを実行する."""
        channel = job.channel or self._default_channel
        if not channel:
            logger.warning(
                "scheduled job の channel 未設定のためスキップ: command=%r", job.command,
            )
            return
        logger.info(
            "scheduled job 実行: command=%r, channel=%s", job.command, channel,
        )

        # 発火を可視化する告知を投稿し、応答をまとめるスレッドを開く。
        # スレッド作成に失敗した場合はチャンネル直下にフォールバックする。
        title = f"🕒 定時実行: {job.command}"
        try:
            thread = await self._messaging.open_thread(channel, title)
            target_channel, target_thread = thread.channel, thread.thread_key
        except Exception:
            logger.exception(
                "scheduled job の告知スレッド作成に失敗（チャンネル直下に投稿）: command=%r",
                job.command,
            )
            target_channel, target_thread = channel, channel

        msg = IncomingMessage(
            user_id=job.user_id,
            text=job.command,
            thread_id=target_thread,
            channel=target_channel,
            is_in_thread=False,
            message_id=f"scheduled-{job.hour:02d}{job.minute:02d}",
        )
        try:
            await self._router.process_message(msg)
        except Exception:
            logger.exception("scheduled job 実行に失敗: command=%r", job.command)
