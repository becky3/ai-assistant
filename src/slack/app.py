"""Slack Bolt AsyncApp 初期化
仕様: docs/specs/features/chat-response.md
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from py_common_lib.secrets import get_secret
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.config.settings import SERVICE_NAME


def create_app() -> AsyncApp:
    """Slack Bolt AsyncApp を生成する."""
    app = AsyncApp(
        token=get_secret(key="SLACK_BOT_TOKEN", service=SERVICE_NAME),
        signing_secret=get_secret(key="SLACK_SIGNING_SECRET", service=SERVICE_NAME),
    )
    return app


async def start_socket_mode(app: AsyncApp) -> None:
    """Socket Mode でアプリを起動する."""
    handler = AsyncSocketModeHandler(
        app, get_secret(key="SLACK_APP_TOKEN", service=SERVICE_NAME),
    )
    await handler.start_async()  # type: ignore[no-untyped-call]


@asynccontextmanager
async def socket_mode_handler(app: AsyncApp) -> AsyncIterator[AsyncSocketModeHandler]:
    """Socket Mode ハンドラーのコンテキストマネージャー."""
    handler = AsyncSocketModeHandler(
        app, get_secret(key="SLACK_APP_TOKEN", service=SERVICE_NAME),
    )
    try:
        yield handler
    finally:
        await handler.close_async()  # type: ignore[no-untyped-call]
