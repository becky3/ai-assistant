"""定時実行スケジュールの設定ローダー.

仕様: docs/specs/infrastructure/scheduled-tasks.md

`config/schedule.toml`（git 管理外）から毎日実行のジョブ定義を読み込む。
ファイルが存在しない場合は空リストを返す（スケジューラ無効）。
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE_PATH = Path("config/schedule.toml")


@dataclass
class ScheduledJob:
    """毎日指定時刻に実行する 1 ジョブ."""

    hour: int
    minute: int
    command: str
    channel: str | None = None
    user_id: str = ""


def load_schedule(path: Path = DEFAULT_SCHEDULE_PATH) -> list[ScheduledJob]:
    """スケジュール設定ファイルを読み込みジョブ定義を返す.

    ファイル不在時は空リスト（スケジューラ無効）。不正なジョブは警告のうえスキップする。
    """
    if not path.exists():
        logger.info("スケジュール設定なし（スケジューラ無効）: %s", path)
        return []

    with open(path, "rb") as f:
        data = tomllib.load(f)

    jobs_raw = data.get("jobs", [])
    if not isinstance(jobs_raw, list):
        logger.warning("スケジュール設定の jobs が配列ではないため無効化します: %s", path)
        return []

    jobs: list[ScheduledJob] = []
    for i, entry in enumerate(jobs_raw):
        if not isinstance(entry, dict):
            logger.warning("スケジュール job[%d]: テーブルではないためスキップ", i)
            continue
        time_str = str(entry.get("time", "")).strip()
        command = str(entry.get("command", "")).strip()
        if not time_str or not command:
            logger.warning("スケジュール job[%d]: time/command 必須のためスキップ", i)
            continue

        parts = time_str.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            logger.warning("スケジュール job[%d]: time 形式が不正のためスキップ: %r", i, time_str)
            continue
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            logger.warning("スケジュール job[%d]: time 範囲が不正のためスキップ: %r", i, time_str)
            continue

        channel_raw = entry.get("channel")
        channel = str(channel_raw).strip() if channel_raw not in (None, "") else None
        user_id = str(entry.get("user_id", "")).strip()

        jobs.append(
            ScheduledJob(
                hour=hour,
                minute=minute,
                command=command,
                channel=channel,
                user_id=user_id,
            )
        )

    logger.info("スケジュール %d 件を読み込みました: %s", len(jobs), path)
    return jobs
