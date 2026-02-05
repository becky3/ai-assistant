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


async def test_deliver_keyword_triggers_manual_delivery() -> None:
    """配信テストキーワードで手動配信が実行される."""
    from unittest.mock import patch

    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()
    collector = AsyncMock()
    session_factory = AsyncMock()
    slack_client = AsyncMock()
    channel_id = "C_TEST"

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(
        app, chat_service,
        collector=collector,
        session_factory=session_factory,
        slack_client=slack_client,
        channel_id=channel_id,
    )

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> deliver", "ts": "123.456"}

    mock_deliver = AsyncMock()
    with patch("src.scheduler.jobs.daily_collect_and_deliver", mock_deliver):
        await handlers["app_mention"](event=event, say=say)

    mock_deliver.assert_called_once_with(
        collector, session_factory, slack_client, channel_id,
        max_articles_per_category=10,
        layout="horizontal",
    )
    # First call: "配信を開始します...", second: "配信が完了しました"
    assert say.call_count == 2
    assert "開始" in say.call_args_list[0][1]["text"]
    assert "完了" in say.call_args_list[1][1]["text"]


async def test_deliver_keyword_error_handling() -> None:
    """配信テスト中のエラーがメッセージとして返される."""
    from unittest.mock import patch

    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(
        app, chat_service,
        collector=AsyncMock(),
        session_factory=AsyncMock(),
        slack_client=AsyncMock(),
        channel_id="C_TEST",
    )

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> deliver", "ts": "111.222"}

    mock_deliver = AsyncMock(side_effect=RuntimeError("fail"))
    with patch("src.scheduler.jobs.daily_collect_and_deliver", mock_deliver):
        await handlers["app_mention"](event=event, say=say)

    # First: "配信を開始します...", second: error message
    assert say.call_count == 2
    assert "エラー" in say.call_args_list[1][1]["text"]


# F6: message イベントハンドラのテスト
def _setup_handlers_with_auto_reply(
    chat_service: AsyncMock,
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
    register_handlers(app, chat_service, auto_reply_channels=auto_reply_channels)
    return handlers


async def test_f6_ac1_auto_reply_in_configured_channel() -> None:
    """F6-AC1: 設定されたチャンネルの全メッセージに自動返信する."""
    chat_service = AsyncMock()
    chat_service.respond.return_value = "自動返信"

    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_called_once_with(
        user_id="U123", text="hello", thread_ts="123.456"
    )
    say.assert_called_once_with(text="自動返信", thread_ts="123.456")


async def test_f6_ac2_ignores_bot_messages() -> None:
    """F6-AC2: Bot自身の投稿には反応しない."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456", "bot_id": "B123"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ac3_ignores_subtype_messages() -> None:
    """F6-AC3: サブタイプ付きメッセージには反応しない."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_AUTO", "ts": "123.456", "subtype": "message_changed"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ac6_ignores_when_no_auto_reply_channels() -> None:
    """F6-AC6: auto_reply_channels が未設定の場合は無効."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, [])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_ANY", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ac7_ignores_mention_messages() -> None:
    """F6-AC7: メンション付きメッセージは app_mention で処理されるためスキップ."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ignores_non_auto_reply_channel() -> None:
    """F6: 対象外チャンネルへの投稿には反応しない."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "hello", "channel": "C_OTHER", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ignores_empty_user_id() -> None:
    """F6: user_id が空のメッセージは無視する（システムメッセージなど）."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "", "text": "hello", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()


async def test_f6_ignores_empty_text() -> None:
    """F6: 空テキストのメッセージは無視する."""
    chat_service = AsyncMock()
    handlers = _setup_handlers_with_auto_reply(chat_service, ["C_AUTO"])

    say = AsyncMock()
    event = {"user": "U123", "text": "   ", "channel": "C_AUTO", "ts": "123.456"}
    await handlers["message"](event=event, say=say)

    chat_service.respond.assert_not_called()
    say.assert_not_called()
