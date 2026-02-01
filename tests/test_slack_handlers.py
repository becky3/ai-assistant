"""Slack Bot連携のテスト (Issue #5)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.slack.handlers import strip_mention


def test_ac4_strip_mention_removes_bot_id() -> None:
    """AC4: メンション部分を除去してからLLMに送信する."""
    assert strip_mention("<@U1234ABC> hello") == "hello"
    assert strip_mention("<@U999> foo bar") == "foo bar"
    assert strip_mention("no mention") == "no mention"
    assert strip_mention("<@U1234ABC>") == ""


def test_ac4_strip_mention_multiple() -> None:
    """AC4: 複数メンションがあっても全て除去する."""
    assert strip_mention("<@U111> <@U222> test") == "test"


async def test_ac1_handle_mention_replies_in_thread() -> None:
    """AC1: @bot メンションに対してスレッド内で応答する."""
    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()
    chat_service.respond.return_value = "テスト応答"

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, chat_service)

    assert "app_mention" in handlers

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> こんにちは", "ts": "123.456"}
    await handlers["app_mention"](event=event, say=say)

    chat_service.respond.assert_called_once_with(
        user_id="U123", text="こんにちは", thread_ts="123.456"
    )
    say.assert_called_once_with(text="テスト応答", thread_ts="123.456")


async def test_ac7_error_message_on_llm_failure() -> None:
    """AC7: LLM API呼び出し失敗時にエラーメッセージを返す."""
    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()
    chat_service.respond.side_effect = RuntimeError("API error")

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, chat_service)

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> test", "ts": "111.222"}
    await handlers["app_mention"](event=event, say=say)

    say.assert_called_once()
    assert "エラー" in say.call_args[1]["text"]
