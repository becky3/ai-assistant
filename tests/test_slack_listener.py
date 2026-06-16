"""SlackListener のテスト (Issue #851)."""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock

from src.messaging.slack_listener import SlackListener
from src.process_guard import BOT_READY_SIGNAL


def _make_app() -> tuple[AsyncMock, dict[str, Any]]:
    """app.event デコレータを捕捉する mock app を作る."""
    app = AsyncMock()
    handlers: dict[str, Any] = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    return app, handlers


def test_slack_listener_registers_handlers() -> None:
    """構築時に app_mention / message ハンドラを登録し、bot_user_id を公開する."""
    app, handlers = _make_app()
    router = AsyncMock()

    listener = SlackListener(app=app, router=router, bot_user_id="UBOT")

    assert "app_mention" in handlers
    assert "message" in handlers
    assert listener.bot_user_id == "UBOT"


async def test_slack_listener_run_starts_socket(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """run() が socket handler を起動し READY シグナルを出力する."""
    app, _ = _make_app()
    router = AsyncMock()
    listener = SlackListener(app=app, router=router, bot_user_id="UBOT")

    handler = AsyncMock()

    @contextlib.asynccontextmanager
    async def fake_socket(_app):  # type: ignore[no-untyped-def]
        yield handler

    monkeypatch.setattr(
        "src.messaging.slack_listener.socket_mode_handler", fake_socket
    )

    await listener.run()

    handler.start_async.assert_awaited_once()
    captured = capsys.readouterr()
    assert BOT_READY_SIGNAL in captured.out
