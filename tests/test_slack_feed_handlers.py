"""Slack feedコマンドハンドラのテスト (Issue #22)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.feed_collector import FeedCollector
from src.slack.handlers import (
    _handle_feed_add,
    _handle_feed_delete,
    _handle_feed_disable,
    _handle_feed_enable,
    _handle_feed_list,
    _parse_feed_command,
)


def test_parse_feed_command_add_single_url() -> None:
    """feedコマンド解析: add 単一URL + カテゴリ."""
    subcommand, urls, category = _parse_feed_command("feed add https://example.com/rss Python")
    assert subcommand == "add"
    assert urls == ["https://example.com/rss"]
    assert category == "Python"


def test_parse_feed_command_add_multiple_urls() -> None:
    """feedコマンド解析: add 複数URL + カテゴリ."""
    subcommand, urls, category = _parse_feed_command(
        "feed add https://example.com/rss https://another.com/feed Python ML"
    )
    assert subcommand == "add"
    assert urls == ["https://example.com/rss", "https://another.com/feed"]
    assert category == "Python ML"


def test_parse_feed_command_add_no_category() -> None:
    """feedコマンド解析: add カテゴリ省略時はデフォルト「一般」."""
    subcommand, urls, category = _parse_feed_command("feed add https://example.com/rss")
    assert subcommand == "add"
    assert urls == ["https://example.com/rss"]
    assert category == "一般"


def test_parse_feed_command_list() -> None:
    """feedコマンド解析: list."""
    subcommand, urls, category = _parse_feed_command("feed list")
    assert subcommand == "list"
    assert urls == []
    assert category == "一般"


def test_parse_feed_command_delete() -> None:
    """feedコマンド解析: delete 複数URL."""
    subcommand, urls, category = _parse_feed_command(
        "feed delete https://example.com/rss https://another.com/feed"
    )
    assert subcommand == "delete"
    assert urls == ["https://example.com/rss", "https://another.com/feed"]


def test_parse_feed_command_enable() -> None:
    """feedコマンド解析: enable."""
    subcommand, urls, category = _parse_feed_command("feed enable https://example.com/rss")
    assert subcommand == "enable"
    assert urls == ["https://example.com/rss"]


def test_parse_feed_command_disable() -> None:
    """feedコマンド解析: disable."""
    subcommand, urls, category = _parse_feed_command("feed disable https://example.com/rss")
    assert subcommand == "disable"
    assert urls == ["https://example.com/rss"]


def test_parse_feed_command_case_insensitive() -> None:
    """feedコマンド解析: サブコマンドは大文字小文字不問."""
    subcommand, _, _ = _parse_feed_command("feed ADD https://example.com/rss")
    assert subcommand == "add"


def test_parse_feed_command_invalid() -> None:
    """feedコマンド解析: 不正コマンド."""
    subcommand, urls, category = _parse_feed_command("feed")
    assert subcommand == ""
    assert urls == []
    assert category == ""


def test_parse_feed_command_invalid_url_no_domain() -> None:
    """feedコマンド解析: ドメインなしURLはURLとして認識されない."""
    subcommand, urls, category = _parse_feed_command("feed add https://")
    assert subcommand == "add"
    assert urls == []


def test_parse_feed_command_slack_url_format() -> None:
    """feedコマンド解析: Slack形式の<URL>を正しく解析する."""
    subcommand, urls, category = _parse_feed_command(
        "feed add <https://example.com/rss> Python"
    )
    assert subcommand == "add"
    assert urls == ["https://example.com/rss"]
    assert category == "Python"


def test_parse_feed_command_slack_url_with_label() -> None:
    """feedコマンド解析: Slack形式の<URL|label>を正しく解析する."""
    subcommand, urls, category = _parse_feed_command(
        "feed add <https://example.com/rss|example.com/rss>"
    )
    assert subcommand == "add"
    assert urls == ["https://example.com/rss"]
    assert category == "一般"


@pytest.mark.asyncio
async def test_handle_feed_add_success() -> None:
    """feedハンドラ: add成功."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock()
    mock_feed.url = "https://example.com/rss"
    mock_feed.category = "Python"
    collector.add_feed.return_value = mock_feed

    result = await _handle_feed_add(collector, ["https://example.com/rss"], "Python")

    collector.add_feed.assert_called_once_with("https://example.com/rss", "https://example.com/rss", "Python")
    assert "✅" in result
    assert "https://example.com/rss" in result


@pytest.mark.asyncio
async def test_handle_feed_add_duplicate_error() -> None:
    """feedハンドラ: add重複エラー."""
    collector = AsyncMock(spec=FeedCollector)
    collector.add_feed.side_effect = ValueError("既に登録されています")

    result = await _handle_feed_add(collector, ["https://example.com/rss"], "Python")

    assert "❌" in result
    assert "既に登録されています" in result


@pytest.mark.asyncio
async def test_handle_feed_add_multiple() -> None:
    """feedハンドラ: 複数add."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed1 = MagicMock(url="https://feed1.com/rss", category="Python")
    mock_feed2 = MagicMock(url="https://feed2.com/rss", category="Python")
    collector.add_feed.side_effect = [mock_feed1, mock_feed2]

    result = await _handle_feed_add(
        collector, ["https://feed1.com/rss", "https://feed2.com/rss"], "Python"
    )

    assert collector.add_feed.call_count == 2
    assert result.count("✅") == 2


@pytest.mark.asyncio
async def test_handle_feed_add_no_url() -> None:
    """feedハンドラ: add URLなしエラー."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_add(collector, [], "Python")
    assert "エラー" in result


@pytest.mark.asyncio
async def test_handle_feed_list() -> None:
    """feedハンドラ: list."""
    collector = AsyncMock(spec=FeedCollector)
    enabled_feed = MagicMock(url="https://enabled.com/rss", category="Python")
    disabled_feed = MagicMock(url="https://disabled.com/rss", category="Other")
    collector.list_feeds.return_value = ([enabled_feed], [disabled_feed])

    result = await _handle_feed_list(collector)

    assert "有効なフィード" in result
    assert "https://enabled.com/rss" in result
    assert "無効なフィード" in result
    assert "https://disabled.com/rss" in result


@pytest.mark.asyncio
async def test_handle_feed_list_empty() -> None:
    """feedハンドラ: list空."""
    collector = AsyncMock(spec=FeedCollector)
    collector.list_feeds.return_value = ([], [])

    result = await _handle_feed_list(collector)

    assert "フィードが登録されていません" in result


@pytest.mark.asyncio
async def test_handle_feed_delete_success() -> None:
    """feedハンドラ: delete成功."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_delete(collector, ["https://example.com/rss"])

    collector.delete_feed.assert_called_once_with("https://example.com/rss")
    assert "✅" in result


@pytest.mark.asyncio
async def test_handle_feed_delete_not_found() -> None:
    """feedハンドラ: delete存在しないURL."""
    collector = AsyncMock(spec=FeedCollector)
    collector.delete_feed.side_effect = ValueError("登録されていません")

    result = await _handle_feed_delete(collector, ["https://nonexistent.com/rss"])

    assert "❌" in result
    assert "登録されていません" in result


@pytest.mark.asyncio
async def test_handle_feed_delete_no_url() -> None:
    """feedハンドラ: delete URLなしエラー."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_delete(collector, [])
    assert "エラー" in result


@pytest.mark.asyncio
async def test_handle_feed_enable_success() -> None:
    """feedハンドラ: enable成功."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_enable(collector, ["https://example.com/rss"])

    collector.enable_feed.assert_called_once_with("https://example.com/rss")
    assert "✅" in result


@pytest.mark.asyncio
async def test_handle_feed_enable_no_url() -> None:
    """feedハンドラ: enable URLなしエラー."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_enable(collector, [])
    assert "エラー" in result


@pytest.mark.asyncio
async def test_handle_feed_disable_success() -> None:
    """feedハンドラ: disable成功."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_disable(collector, ["https://example.com/rss"])

    collector.disable_feed.assert_called_once_with("https://example.com/rss")
    assert "✅" in result


@pytest.mark.asyncio
async def test_handle_feed_disable_no_url() -> None:
    """feedハンドラ: disable URLなしエラー."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_disable(collector, [])
    assert "エラー" in result
