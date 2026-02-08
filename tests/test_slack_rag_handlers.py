"""Slack ragコマンドハンドラのテスト."""

from __future__ import annotations

from src.slack.handlers import _parse_rag_command


class TestParseRagCommand:
    """_parse_rag_command関数のテスト."""

    def test_crawl_with_url(self) -> None:
        """ragコマンド解析: crawl URL."""
        subcommand, url, pattern = _parse_rag_command("rag crawl https://example.com/docs")
        assert subcommand == "crawl"
        assert url == "https://example.com/docs"
        assert pattern == ""

    def test_crawl_with_url_and_pattern(self) -> None:
        """ragコマンド解析: crawl URL パターン."""
        subcommand, url, pattern = _parse_rag_command(
            "rag crawl https://example.com/docs /api/"
        )
        assert subcommand == "crawl"
        assert url == "https://example.com/docs"
        assert pattern == "/api/"

    def test_crawl_with_url_and_pattern_with_spaces(self) -> None:
        """ragコマンド解析: crawl URL 複数トークンのパターン."""
        subcommand, url, pattern = _parse_rag_command(
            "rag crawl https://example.com/docs /docs/.*/guide"
        )
        assert subcommand == "crawl"
        assert url == "https://example.com/docs"
        assert pattern == "/docs/.*/guide"

    def test_crawl_with_slack_url_format(self) -> None:
        """ragコマンド解析: SlackのURL形式 <https://...|label>."""
        subcommand, url, pattern = _parse_rag_command(
            "rag crawl <https://example.com/docs|example.com>"
        )
        assert subcommand == "crawl"
        assert url == "https://example.com/docs"
        assert pattern == ""

    def test_crawl_with_slack_url_format_no_label(self) -> None:
        """ragコマンド解析: SlackのURL形式 <https://...> (ラベルなし)."""
        subcommand, url, pattern = _parse_rag_command(
            "rag crawl <https://example.com/docs>"
        )
        assert subcommand == "crawl"
        assert url == "https://example.com/docs"
        assert pattern == ""

    def test_add_with_url(self) -> None:
        """ragコマンド解析: add URL."""
        subcommand, url, pattern = _parse_rag_command("rag add https://example.com/page")
        assert subcommand == "add"
        assert url == "https://example.com/page"
        assert pattern == ""

    def test_status(self) -> None:
        """ragコマンド解析: status."""
        subcommand, url, pattern = _parse_rag_command("rag status")
        assert subcommand == "status"
        assert url == ""
        assert pattern == ""

    def test_delete_with_url(self) -> None:
        """ragコマンド解析: delete URL."""
        subcommand, url, pattern = _parse_rag_command(
            "rag delete https://example.com/page"
        )
        assert subcommand == "delete"
        assert url == "https://example.com/page"
        assert pattern == ""

    def test_subcommand_case_insensitive(self) -> None:
        """ragコマンド解析: サブコマンドは小文字に正規化."""
        subcommand, url, pattern = _parse_rag_command("rag CRAWL https://example.com/docs")
        assert subcommand == "crawl"

    def test_empty_command(self) -> None:
        """ragコマンド解析: 空コマンド."""
        subcommand, url, pattern = _parse_rag_command("rag")
        assert subcommand == ""
        assert url == ""
        assert pattern == ""

    def test_invalid_url_scheme(self) -> None:
        """ragコマンド解析: 無効なURLスキームは無視."""
        subcommand, url, pattern = _parse_rag_command("rag crawl ftp://example.com/docs")
        assert subcommand == "crawl"
        assert url == ""  # http/https以外は無視
        assert pattern == ""

    def test_http_url(self) -> None:
        """ragコマンド解析: http:// URLも受け付ける."""
        subcommand, url, pattern = _parse_rag_command("rag add http://example.com/page")
        assert subcommand == "add"
        assert url == "http://example.com/page"
        assert pattern == ""
