"""ThreadHistoryService のテスト (Issue #97).

仕様: docs/specs/features/thread-support.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.services.thread_history import ThreadHistoryService, extract_text_from_blocks

BOT_USER_ID = "U_BOT"


@pytest.fixture
def slack_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def service(slack_client: AsyncMock) -> ThreadHistoryService:
    return ThreadHistoryService(
        slack_client=slack_client,
        bot_user_id=BOT_USER_ID,
        bot_id="B_BOT",
        limit=20,
    )


async def test_fetch_thread_messages_from_slack_api(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """Slack API からスレッドメッセージを取得できる."""
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


async def test_thread_history_respects_limit(
    slack_client: AsyncMock,
) -> None:
    """limit 設定に従って件数が制限される."""
    service = ThreadHistoryService(
        slack_client=slack_client,
        bot_user_id=BOT_USER_ID,
        bot_id="B_BOT",
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


async def test_bot_messages_mapped_to_assistant_role(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """ボットのメッセージは assistant ロール、他は user ロール."""
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


async def test_returns_none_on_api_failure(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """Slack API 失敗時に None を返す（フォールバック用）."""
    slack_client.conversations_replies.side_effect = Exception("API error")

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is None


async def test_subtype_messages_are_skipped(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """bot_message 以外のサブタイプ付きメッセージはスキップされる."""
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


class TestExtractTextFromBlocks:
    """extract_text_from_blocks のテスト."""

    def test_section_block_mrkdwn(self) -> None:
        """section ブロックの mrkdwn テキストを抽出する."""
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": ":newspaper: *<https://example.com|Sample Article>*\n2026-04-21\n\nArticle summary here"},
            },
        ]
        result = extract_text_from_blocks(blocks)
        assert "Sample Article" in result
        assert "Article summary here" in result

    def test_multiple_section_blocks(self) -> None:
        """複数の section ブロックからテキストを結合する."""
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Title line"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Summary line"}},
        ]
        result = extract_text_from_blocks(blocks)
        assert "Title line" in result
        assert "Summary line" in result

    def test_non_section_blocks_ignored(self) -> None:
        """divider 等の非テキストブロックは無視する."""
        blocks = [
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "content"}},
        ]
        result = extract_text_from_blocks(blocks)
        assert result == "content"

    def test_empty_blocks(self) -> None:
        """空のブロックリストは空文字を返す."""
        assert extract_text_from_blocks([]) == ""

    def test_image_block_with_section(self) -> None:
        """image ブロックは無視し、section のみ抽出する."""
        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": "Article title"}},
            {"type": "image", "image_url": "https://example.com/img.png", "alt_text": "alt"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Summary"}},
        ]
        result = extract_text_from_blocks(blocks)
        assert "Article title" in result
        assert "Summary" in result
        assert "img.png" not in result

    def test_rich_text_block(self) -> None:
        """rich_text ブロックからテキストを抽出する."""
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Hello from rich text"},
                        ],
                    },
                ],
            },
        ]
        result = extract_text_from_blocks(blocks)
        assert result == "Hello from rich text"

    def test_rich_text_link_element(self) -> None:
        """rich_text ブロック内の link タイプからテキストを抽出する."""
        blocks = [
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_section",
                        "elements": [
                            {"type": "text", "text": "Check out "},
                            {"type": "link", "url": "https://example.com", "text": "this link"},
                        ],
                    },
                ],
            },
        ]
        result = extract_text_from_blocks(blocks)
        assert "Check out" in result
        assert "this link" in result


async def test_blockkit_message_text_extracted_from_blocks(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """Block Kit メッセージの blocks からテキストを抽出する."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {
                "user": BOT_USER_ID,
                "text": "記事",
                "ts": "1000.0",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": ":newspaper: *<https://example.com|Sample Article>*\n2026-04-21\n\nThis is the article summary",
                        },
                    },
                ],
            },
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 1
    assert result[0].role == "assistant"
    assert "Sample Article" in result[0].content
    assert "This is the article summary" in result[0].content


async def test_bot_message_subtype_not_skipped(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """bot_message subtype のメッセージはスキップされない."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {
                "bot_id": "B_BOT",
                "text": "Bot notification",
                "ts": "1000.0",
                "subtype": "bot_message",
            },
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 1
    assert result[0].role == "assistant"
    assert "Bot notification" in result[0].content


async def test_bot_id_detected_as_assistant(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """自ボットの bot_id を持つメッセージは assistant ロールになる."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {
                "bot_id": "B_BOT",
                "text": "配信メッセージ",
                "ts": "1000.0",
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": ":file_folder: *Tech News*"}},
                ],
            },
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 1
    assert result[0].role == "assistant"
    assert "Tech News" in result[0].content


async def test_other_bot_not_mapped_to_assistant(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """他ボットの bot_id を持つメッセージは user ロールになる."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {
                "bot_id": "B_OTHER",
                "text": "External bot message",
                "ts": "1000.0",
            },
        ],
    }

    result = await service.fetch_thread_messages(
        channel="C1", thread_ts="1000.0", current_ts="9999.0"
    )

    assert result is not None
    assert len(result) == 1
    assert result[0].role == "user"
    assert "External bot message" in result[0].content


async def test_non_bot_subtype_still_skipped(
    service: ThreadHistoryService, slack_client: AsyncMock
) -> None:
    """bot_message 以外のサブタイプは引き続きスキップされる."""
    slack_client.conversations_replies.return_value = {
        "messages": [
            {"user": "U1", "text": "normal", "ts": "1000.0"},
            {"user": "U1", "text": "edited", "ts": "1001.0", "subtype": "message_changed"},
            {"user": "U1", "text": "deleted", "ts": "1002.0", "subtype": "message_deleted"},
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
