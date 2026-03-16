"""Slack Bolt AsyncApp 初期化
仕様: docs/specs/features/chat-response.md
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.config.settings import resolve_secret


def create_app() -> AsyncApp:
    """Slack Bolt AsyncApp を生成する."""
    app = AsyncApp(
        token=resolve_secret("SLACK_BOT_TOKEN"),
        signing_secret=resolve_secret("SLACK_SIGNING_SECRET"),
    )
    return app


async def start_socket_mode(app: AsyncApp) -> None:
    """Socket Mode でアプリを起動する."""
    handler = AsyncSocketModeHandler(app, resolve_secret("SLACK_APP_TOKEN"))
    await handler.start_async()  # type: ignore[no-untyped-call]


@asynccontextmanager
async def socket_mode_handler(app: AsyncApp) -> AsyncIterator[AsyncSocketModeHandler]:
    """Socket Mode ハンドラーのコンテキストマネージャー."""
    handler = AsyncSocketModeHandler(app, resolve_secret("SLACK_APP_TOKEN"))
    try:
        yield handler
    finally:
        await handler.close_async()  # type: ignore[no-untyped-call]
