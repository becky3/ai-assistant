"""Slack Bolt AsyncApp 初期化
仕様: docs/specs/f1-chat.md
"""

from __future__ import annotations

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.config.settings import Settings


def create_app(settings: Settings) -> AsyncApp:
    """Slack Bolt AsyncApp を生成する."""
    app = AsyncApp(
        token=settings.slack_bot_token,
        signing_secret=settings.slack_signing_secret,
    )
    return app


async def start_socket_mode(app: AsyncApp, settings: Settings) -> None:
    """Socket Mode でアプリを起動する."""
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    await handler.start_async()  # type: ignore[no-untyped-call]
