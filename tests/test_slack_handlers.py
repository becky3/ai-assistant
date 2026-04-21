"""Slack Bot連携のテスト (Issue #5, #496)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from src.messaging.port import IncomingMessage
from src.slack.handlers import strip_mention


def test_strip_mention_removes_bot_id() -> None:
    """メンション部分を除去してからLLMに送信する."""
    assert strip_mention("<@U1234ABC> hello") == "hello"
    assert strip_mention("<@U999> foo bar") == "foo bar"
    assert strip_mention("no mention") == "no mention"
    assert strip_mention("<@U1234ABC>") == ""


def test_strip_mention_with_display_name() -> None:
    """表示名付きメンション (<@U...|name>) を除去する."""
    assert strip_mention("<@U0AC49HLCUB|daisy> rag update.") == "rag update."
    assert strip_mention("Reminder: <@U0AC49HLCUB|daisy> rag update.") == "Reminder: rag update."


def test_strip_mention_multiple() -> None:
    """複数メンションがあっても全て除去する."""
    assert strip_mention("<@U111> <@U222> test") == "test"


async def test_handle_mention_replies_in_thread() -> None:
    """メンションに対してスレッド内で応答する."""
    from src.slack.handlers import register_handlers

    router = AsyncMock()
    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, router)

    assert "app_mention" in handlers

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> こんにちは", "ts": "123.456"}
    await handlers["app_mention"](event=event, say=say)

    router.process_message.assert_called_once()
    msg: IncomingMessage = router.process_message.call_args[0][0]
    assert msg.user_id == "U123"
    assert msg.text == "こんにちは"
    assert msg.thread_id == "123.456"
    assert msg.is_in_thread is False
    assert msg.message_id == "123.456"


async def test_handle_mention_in_thread() -> None:
    """スレッド内メンションでは is_in_thread=True が設定される."""
    from src.slack.handlers import register_handlers

    router = AsyncMock()
    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, router)

    say = AsyncMock()
    event = {
        "user": "U123", "text": "<@UBOT> hello",
        "ts": "200.0", "thread_ts": "100.0",
    }
    await handlers["app_mention"](event=event, say=say)

    msg: IncomingMessage = router.process_message.call_args[0][0]
    assert msg.thread_id == "100.0"
    assert msg.is_in_thread is True
    assert msg.message_id == "200.0"


async def test_handle_mention_empty_text_ignored() -> None:
    """メンションのみ（テキストなし）は無視される."""
    from src.slack.handlers import register_handlers

    router = AsyncMock()
    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, router)

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT>", "ts": "123.456"}
    await handlers["app_mention"](event=event, say=say)

    router.process_message.assert_not_called()


# F6: message イベントハンドラのテスト
def _setup_handlers_with_auto_reply(
    router: AsyncMock,
    auto_reply_channels: list[str],
) -> dict:
    """auto_reply_channels 付きでハンドラを登録するヘルパー."""
    from src.slack.handlers import register_handlers

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, router, auto_reply_channels=auto_reply_channels)
    return handlers


async def test_auto_reply_in_configured_channel() -> None:
    """設定されたチャンネルの全メッセージに自動返信する."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_called_once()
    msg: IncomingMessage = router.process_message.call_args[0][0]
    assert msg.user_id == "U123"
    assert msg.text == "hello"
    assert msg.channel == "C_AUTO"


async def test_auto_reply_ignores_bot_messages() -> None:
    """Bot自身の投稿には反応しない."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456", "bot_id": "B123"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_subtype_messages() -> None:
    """サブタイプ付きメッセージには反応しない."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456", "subtype": "message_changed"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_when_no_channels_configured() -> None:
    """auto_reply_channels が未設定の場合は無効."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, [])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_ANY", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_mention_messages() -> None:
    """メンション付きメッセージは app_mention で処理されるためスキップ."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_mention_with_display_name() -> None:
    """表示名付きメンション (<@U...|name>) も app_mention 扱いでスキップ."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT|botname> hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_non_configured_channel() -> None:
    """対象外チャンネルへの投稿には反応しない."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_OTHER", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_empty_user_id() -> None:
    """user_id が空のメッセージは無視する（システムメッセージなど）."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "", "text": "hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()


async def test_auto_reply_ignores_empty_text() -> None:
    """空テキストのメッセージは無視する."""
    router = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(router, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "   ", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    router.process_message.assert_not_called()
