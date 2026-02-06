"""ThreadHistoryService のテスト (Issue #97).

仕様: docs/specs/f8-thread-support.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.thread_history import ThreadHistoryService

BOT_USER_ID = "U_BOT"


@pytest.fixture
def slack_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(slack_client: AsyncMock) -> ThreadHistoryService:
    return ThreadHistoryService(
        slack_client=slack_client,
        bot_user_id=BOT_USER_ID,
        limit=20,
    )


async def test_ac1_fetch_thread_messages_from_slack_api(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """AC1: Slack API からスレッドメッセージを取得できる."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "hello", "ts": "1000.0"},
            {"user": "U2", "text": "world", "ts": "1001.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 2
    assert result[0].role == "user"
    assert "<@U1>:" in result[0].content
    assert "hello" in result[0].content
    slack_client.conversations_replies.assert_called_once_with(
        channel="C1", ts="1000.0", limit=20
    )


async def test_ac2_thread_history_respects_limit(
    slack_client: AsyncMock,
) -> None:
    """AC2: limit 設定に従って件数が制限される."""
    service = ThreadHistoryService(
        slack_client=slack_client,
        bot_user_id=BOT_USER_ID,
        limit=2,
    )
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "msg1", "ts": "1000.0"},
            {"user": "U1", "text": "msg2", "ts": "1001.0"},
            {"user": "U1", "text": "msg3", "ts": "1002.0"},
            {"user": "U1", "text": "msg4", "ts": "1003.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    # 4メッセージ中、limit=2 なので最新2件
    assert len(result) == 2
    assert "msg3" in result[0].content
    assert "msg4" in result[1].content


async def test_ac3_bot_messages_mapped_to_assistant_role(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """AC3: ボットのメッセージは assistant ロール、他は user ロール."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "質問", "ts": "1000.0"},
            {"user": BOT_USER_ID, "text": "回答", "ts": "1001.0"},
            {"user": "U2", "text": "追加質問", "ts": "1002.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 3
    assert result[0].role == "user"
    assert result[1].role == "assistant"
    assert result[1].content == "回答"  # assistant はユーザーID付与なし
    assert result[2].role == "user"
    assert "<@U2>:" in result[2].content


async def test_ac5_returns_none_on_api_failure(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """AC5: Slack API 失敗時に None を返す（フォールバック用）."""
    slack_client.conversations_replies.side_effect = Exception("API error")

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is None


async def test_subtype_messages_are_skipped(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """サブタイプ付きメッセージはスキップされる."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "normal", "ts": "1000.0"},
            {"user": "U1", "text": "edited", "ts": "1001.0", "subtype": "message_changed"},
            {"user": "U1", "text": "", "ts": "1002.0"},  # テキストなし
            {"user": "U1", "text": "valid", "ts": "1003.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 2
    assert "normal" in result[0].content
    assert "valid" in result[1].content


async def test_current_message_excluded(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """トリガーメッセージが current_ts で正しく除外される."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "past msg", "ts": "1000.0"},
            {"user": "U1", "text": "trigger msg", "ts": "1001.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="1001.0"
    )

    assert result is not None
    assert len(result) == 1
    assert "past msg" in result[0].content


async def test_empty_messages_returns_empty_list(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """メッセージが空の場合は空リストを返す."""
    slack_client.conversations_replies.return_value = {"messages": []}

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert result == []


async def test_user_id_included_in_user_messages(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """user ロールのメッセージにはユーザーIDが付与される."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U_ABC", "text": "hello", "ts": "1000.0"},
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 1
    assert result[0].content == "<@U_ABC>: hello"
    assert result[0].role == "user"
