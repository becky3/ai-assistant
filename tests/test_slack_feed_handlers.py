"""Slack feedコマンドハンドラのテスト (Issue #22)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.services.feed_collector import FeedCollector
from src.slack.handlers import (
    _handle_feed_add,
    _handle_feed_collect_skip_summary,
    _handle_feed_delete,
    _handle_feed_disable,
    _handle_feed_enable,
    _handle_feed_export,
    _handle_feed_import,
    _handle_feed_list,
    _handle_feed_replace,
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


def test_parse_feed_command_test() -> None:
    """feedコマンド解析: test."""
    subcommand, urls, category = _parse_feed_command("feed test")
    assert subcommand == "test"
    assert urls == []
    assert category == "一般"


def test_parse_feed_command_invalid() -> None:
    """feedコマンド解析: 不正コマンド."""
    subcommand, urls, category = _parse_feed_command("feed")
    assert subcommand == ""
    assert urls == []
    assert category == ""


def test_parse_feed_command_invalid_url_no_domain() -> None:
    """feedコマンド解析: ドメインなしURLはURLとしてもカテゴリとしても認識されない."""
    subcommand, urls, category = _parse_feed_command("feed add https://")
    assert subcommand == "add"
    assert urls == []
    assert category == "一般"


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


# --- feed import テスト (AC13) ---


@pytest.mark.asyncio
async def test_ac13_5_handle_feed_import_no_files() -> None:
    """feedハンドラ: import ファイルなしエラー (AC13.5)."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_import(collector, None, "xoxb-token")
    assert "エラー" in result
    assert "CSVファイルを添付" in result


@pytest.mark.asyncio
async def test_ac13_6_handle_feed_import_non_csv_file() -> None:
    """feedハンドラ: import CSV以外のファイルエラー (AC13.6)."""
    collector = AsyncMock(spec=FeedCollector)
    files = [{"name": "image.png", "mimetype": "image/png", "url_private": "https://files.slack.com/test.png"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")
    assert "エラー" in result
    assert "CSVファイルが見つかりません" in result


@pytest.mark.asyncio
async def test_ac13_1_handle_feed_import_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: import 成功 (AC13.1)."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock()
    mock_feed.url = "https://example.com/rss"
    mock_feed.name = "Example Feed"
    mock_feed.category = "Tech"
    collector.add_feed.return_value = mock_feed

    csv_content = "url,name,category\nhttps://example.com/rss,Example Feed,Tech"

    # httpx.AsyncClient をモック
    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")

    assert "成功: 1件" in result
    collector.add_feed.assert_called_once_with("https://example.com/rss", "Example Feed", "Tech")


@pytest.mark.asyncio
async def test_ac13_3_handle_feed_import_default_category(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: import カテゴリ省略時は「一般」(AC13.3)."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock()
    mock_feed.url = "https://example.com/rss"
    mock_feed.name = "Example Feed"
    mock_feed.category = "一般"
    collector.add_feed.return_value = mock_feed

    csv_content = "url,name,category\nhttps://example.com/rss,Example Feed,"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")

    collector.add_feed.assert_called_once_with("https://example.com/rss", "Example Feed", "一般")
    assert "成功: 1件" in result


@pytest.mark.asyncio
async def test_ac13_4_handle_feed_import_duplicate_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: import 重複スキップ (AC13.4)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.add_feed.side_effect = ValueError("既に登録されています")

    csv_content = "url,name,category\nhttps://duplicate.com/rss,Dup Feed,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")

    assert "成功: 0件" in result
    assert "失敗: 1件" in result
    assert "行2:" in result
    assert "既に登録されています" in result


@pytest.mark.asyncio
async def test_ac13_2_handle_feed_import_invalid_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: import 不正ヘッダーエラー (AC13.2)."""
    collector = AsyncMock(spec=FeedCollector)

    csv_content = "wrong,header,format\nhttps://example.com/rss,Example,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")

    assert "エラー" in result
    assert "CSVヘッダーが不正" in result


@pytest.mark.asyncio
async def test_ac13_7_handle_feed_import_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: import サマリー表示 (AC13.7)."""
    collector = AsyncMock(spec=FeedCollector)

    # 1件目成功、2件目失敗
    mock_feed = MagicMock(url="https://ok.com/rss", name="OK Feed", category="Tech")
    collector.add_feed.side_effect = [mock_feed, ValueError("重複")]

    csv_content = "url,name,category\nhttps://ok.com/rss,OK Feed,Tech\nhttps://dup.com/rss,Dup Feed,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_import(collector, files, "xoxb-token")

    assert "フィードインポート完了" in result
    assert "成功: 1件" in result
    assert "失敗: 1件" in result
    assert "行3:" in result  # 3行目（ヘッダー=1, 1件目=2, 2件目=3）
    assert "重複" in result


# --- feed replace テスト (AC16) ---


def test_parse_feed_command_replace() -> None:
    """feedコマンド解析: replace."""
    subcommand, urls, category = _parse_feed_command("feed replace")
    assert subcommand == "replace"
    assert urls == []
    assert category == "一般"


def test_parse_feed_command_export() -> None:
    """feedコマンド解析: export."""
    subcommand, urls, category = _parse_feed_command("feed export")
    assert subcommand == "export"
    assert urls == []
    assert category == "一般"


@pytest.mark.asyncio
async def test_ac16_4_handle_feed_replace_no_files() -> None:
    """feedハンドラ: replace ファイルなしエラー (AC16.4)."""
    collector = AsyncMock(spec=FeedCollector)
    result = await _handle_feed_replace(collector, None, "xoxb-token")
    assert "エラー" in result
    assert "CSVファイルを添付" in result


@pytest.mark.asyncio
async def test_ac16_5_handle_feed_replace_non_csv_file() -> None:
    """feedハンドラ: replace CSV以外のファイルエラー (AC16.5)."""
    collector = AsyncMock(spec=FeedCollector)
    files: list[dict[str, object]] = [{"name": "image.png", "mimetype": "image/png", "url_private": "https://files.slack.com/test.png"}]
    result = await _handle_feed_replace(collector, files, "xoxb-token")
    assert "エラー" in result
    assert "CSVファイルが見つかりません" in result


@pytest.mark.asyncio
async def test_ac16_1_handle_feed_replace_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: replace 正常系（全削除→再登録）(AC16.1)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.delete_all_feeds.return_value = 3
    mock_feed = MagicMock()
    mock_feed.url = "https://new.com/rss"
    mock_feed.name = "New Feed"
    mock_feed.category = "Tech"
    collector.add_feed.return_value = mock_feed

    csv_content = "url,name,category\nhttps://new.com/rss,New Feed,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files: list[dict[str, object]] = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_replace(collector, files, "xoxb-token")

    assert "フィード置換完了" in result
    assert "削除: 3件" in result
    assert "登録成功: 1件" in result
    assert "登録失敗: 0件" in result
    collector.delete_all_feeds.assert_called_once()
    collector.add_feed.assert_called_once_with("https://new.com/rss", "New Feed", "Tech")


@pytest.mark.asyncio
async def test_ac16_3_handle_feed_replace_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: replace サマリー表示 (AC16.3)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.delete_all_feeds.return_value = 5

    mock_feed = MagicMock(url="https://ok.com/rss", name="OK Feed", category="Tech")
    collector.add_feed.side_effect = [mock_feed, ValueError("重複")]

    csv_content = "url,name,category\nhttps://ok.com/rss,OK Feed,Tech\nhttps://dup.com/rss,Dup Feed,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files: list[dict[str, object]] = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_replace(collector, files, "xoxb-token")

    assert "フィード置換完了" in result
    assert "削除: 5件" in result
    assert "登録成功: 1件" in result
    assert "登録失敗: 1件" in result
    assert "行3:" in result
    assert "重複" in result


@pytest.mark.asyncio
async def test_ac16_6_handle_feed_replace_import_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """feedハンドラ: replace 一部登録失敗（削除は取り消されない）(AC16.6)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.delete_all_feeds.return_value = 2
    # 全件失敗
    collector.add_feed.side_effect = ValueError("追加エラー")

    csv_content = "url,name,category\nhttps://fail.com/rss,Fail Feed,Tech"

    mock_response = MagicMock()
    mock_response.text = csv_content
    mock_response.raise_for_status = MagicMock()

    async def mock_get(*args: object, **kwargs: object) -> MagicMock:
        return mock_response

    mock_client = MagicMock()
    mock_client.get = mock_get
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: mock_client)

    files: list[dict[str, object]] = [{"name": "feeds.csv", "mimetype": "text/csv", "url_private": "https://files.slack.com/feeds.csv"}]
    result = await _handle_feed_replace(collector, files, "xoxb-token")

    # 削除は実行されている（取り消されない）
    collector.delete_all_feeds.assert_called_once()
    assert "削除: 2件" in result
    assert "登録成功: 0件" in result
    assert "登録失敗: 1件" in result


# --- feed export テスト (AC17) ---


@pytest.mark.asyncio
async def test_ac17_5_handle_feed_export_no_feeds() -> None:
    """feedハンドラ: export フィード0件 (AC17.5)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.get_all_feeds.return_value = []

    slack_client = AsyncMock()

    result = await _handle_feed_export(collector, slack_client, "C123", "1234.5678")

    assert "エクスポートするフィードがありません" in result
    slack_client.files_upload_v2.assert_not_called()


@pytest.mark.asyncio
async def test_ac17_1_handle_feed_export_success() -> None:
    """feedハンドラ: export 正常系 (AC17.1)."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock()
    mock_feed.url = "https://example.com/rss"
    mock_feed.name = "Example Feed"
    mock_feed.category = "Tech"
    collector.get_all_feeds.return_value = [mock_feed]

    slack_client = AsyncMock()

    result = await _handle_feed_export(collector, slack_client, "C123", "1234.5678")

    assert result == ""
    slack_client.files_upload_v2.assert_called_once()
    call_kwargs = slack_client.files_upload_v2.call_args[1]
    assert call_kwargs["channel"] == "C123"
    assert call_kwargs["thread_ts"] == "1234.5678"
    assert call_kwargs["filename"] == "feeds.csv"
    assert "1件" in call_kwargs["initial_comment"]


@pytest.mark.asyncio
async def test_ac17_4_handle_feed_export_all_feeds() -> None:
    """feedハンドラ: export 有効・無効の両方が含まれる (AC17.4)."""
    collector = AsyncMock(spec=FeedCollector)
    enabled_feed = MagicMock(url="https://enabled.com/rss", name="Enabled", category="Tech")
    disabled_feed = MagicMock(url="https://disabled.com/rss", name="Disabled", category="Other")
    collector.get_all_feeds.return_value = [enabled_feed, disabled_feed]

    slack_client = AsyncMock()

    result = await _handle_feed_export(collector, slack_client, "C123", "1234.5678")

    assert result == ""
    call_kwargs = slack_client.files_upload_v2.call_args[1]
    csv_content = call_kwargs["content"]
    assert "https://enabled.com/rss" in csv_content
    assert "https://disabled.com/rss" in csv_content
    assert "2件" in call_kwargs["initial_comment"]


@pytest.mark.asyncio
async def test_ac17_2_handle_feed_export_csv_format() -> None:
    """feedハンドラ: export CSV形式の検証 (AC17.2)."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock(url="https://example.com/rss", category="Tech")
    mock_feed.name = "Example Feed"
    collector.get_all_feeds.return_value = [mock_feed]

    slack_client = AsyncMock()

    await _handle_feed_export(collector, slack_client, "C123", "1234.5678")

    call_kwargs = slack_client.files_upload_v2.call_args[1]
    csv_content = call_kwargs["content"]
    lines = csv_content.strip().splitlines()
    assert lines[0] == "url,name,category"
    assert lines[1] == "https://example.com/rss,Example Feed,Tech"


@pytest.mark.asyncio
async def test_ac17_6_handle_feed_export_permission_error() -> None:
    """feedハンドラ: export 権限不足エラー (AC17.6)."""
    collector = AsyncMock(spec=FeedCollector)
    mock_feed = MagicMock(url="https://example.com/rss", name="Example Feed", category="Tech")
    collector.get_all_feeds.return_value = [mock_feed]

    slack_client = AsyncMock()
    slack_client.files_upload_v2.side_effect = Exception("missing_scope: files:write")

    result = await _handle_feed_export(collector, slack_client, "C123", "1234.5678")

    assert "エラー" in result
    assert "files:write" in result


# --- feed collect --skip-summary テスト (AC18) ---


def test_parse_feed_command_collect() -> None:
    """feedコマンド解析: collect."""
    subcommand, urls, category = _parse_feed_command("feed collect --skip-summary")
    assert subcommand == "collect"
    assert urls == []


@pytest.mark.asyncio
async def test_ac18_1_handle_feed_collect_skip_summary_success() -> None:
    """feedハンドラ: collect --skip-summary 成功 (AC18.1)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.collect_all_skip_summary.return_value = (3, 45)

    result = await _handle_feed_collect_skip_summary(collector)

    collector.collect_all_skip_summary.assert_called_once()
    assert "要約スキップ収集完了" in result
    assert "収集フィード数: 3" in result
    assert "収集記事数: 45" in result


@pytest.mark.asyncio
async def test_ac18_6_handle_feed_collect_skip_summary_summary_format() -> None:
    """feedハンドラ: collect --skip-summary サマリー形式 (AC18.6)."""
    collector = AsyncMock(spec=FeedCollector)
    collector.collect_all_skip_summary.return_value = (0, 0)

    result = await _handle_feed_collect_skip_summary(collector)

    assert "収集フィード数: 0" in result
    assert "収集記事数: 0" in result


@pytest.mark.asyncio
async def test_ac18_handle_feed_collect_skip_summary_error() -> None:
    """feedハンドラ: collect --skip-summary エラー時."""
    collector = AsyncMock(spec=FeedCollector)
    collector.collect_all_skip_summary.side_effect = Exception("Unexpected error")

    result = await _handle_feed_collect_skip_summary(collector)

    assert "エラーが発生しました" in result
