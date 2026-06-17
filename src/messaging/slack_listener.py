"""Slack 用 MessagingListener 実装.

仕様: docs/specs/features/cli-adapter.md

Slack Bolt App + Socket Mode + イベントハンドラ登録を束ね、受信側の
抽象 `MessagingListener` を満たす。受信正規化ロジックは
`src/slack/handlers.py`（`register_handlers`）に温存し、本クラスは
ライフサイクル（接続・起動・graceful 停止）を担う。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.messaging.listener import MessagingListener
from src.process_guard import BOT_READY_SIGNAL
from src.slack.app import socket_mode_handler
from src.slack.handlers import register_handlers

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp

    from src.messaging.router import MessageRouter

logger = logging.getLogger(__name__)


class SlackListener(MessagingListener):
    """Slack Bolt + Socket Mode を束ねる受信リスナー.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(
        self,
        app: AsyncApp,
        router: MessageRouter,
        bot_user_id: str,
        auto_reply_channels: list[str] | None = None,
    ) -> None:
        self._app = app
        self._router = router
        self._bot_user_id = bot_user_id
        register_handlers(app, router, auto_reply_channels=auto_reply_channels)

    @property
    def bot_user_id(self) -> str:
        """解決済みの bot ユーザー ID（Slack auth_test で解決済みの値）."""
        return self._bot_user_id

    async def run(self) -> None:
        """Socket Mode で接続し、シャットダウンまでイベントを dispatch する."""
        async with socket_mode_handler(self._app) as handler:
            print(BOT_READY_SIGNAL, flush=True)
            try:
                await handler.start_async()  # type: ignore[no-untyped-call]
            except asyncio.CancelledError:
                logger.info("シャットダウンシグナルを受信しました")
