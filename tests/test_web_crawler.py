"""WebCrawler テスト

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.services.web_crawler import CrawledPage, WebCrawler


# テスト用HTMLサンプル
SAMPLE_HTML_WITH_ARTICLE = """
<!DOCTYPE html>
<html>
<head>
    <title>テスト記事</title>
    <script>console.log('test');</script>
    <style>body { color: red; }</style>
</head>
<body>
    <nav>ナビゲーション</nav>
    <header>ヘッダー</header>
    <article>
        <h1>記事タイトル</h1>
        <p>これは記事の本文です。</p>
        <p>2つ目の段落です。</p>
    </article>
    <footer>フッター</footer>
</body>
</html>
"""

SAMPLE_HTML_WITH_MAIN = """
<!DOCTYPE html>
<html>
<head><title>メインコンテンツ</title></head>
<body>
    <nav>ナビ</nav>
    <main>
        <p>メインエリアのテキスト</p>
    </main>
</body>
</html>
"""

SAMPLE_HTML_BODY_ONLY = """
<!DOCTYPE html>
<html>
<head><title>ボディのみ</title></head>
<body>
    <p>ボディ内のテキスト</p>
</body>
</html>
"""

SAMPLE_INDEX_HTML = """
<!DOCTYPE html>
<html>
<head><title>リンク集</title></head>
<body>
    <h1>記事一覧</h1>
    <ul>
        <li><a href="/article/1">記事1</a></li>
        <li><a href="/article/2">記事2</a></li>
        <li><a href="https://example.com/article/3">記事3</a></li>
        <li><a href="https://other-domain.com/page">外部リンク</a></li>
        <li><a href="/doc/guide.html">ガイド</a></li>
        <li><a href="/doc/faq.html">FAQ</a></li>
    </ul>
</body>
</html>
"""


class MockResponse:
    """モックHTTPレスポンス."""

    def __init__(self, status: int = 200, text: str = "") -> None:
        self.status = status
        self._text = text

    async def text(self, errors: str = "strict") -> str:  # noqa: ARG002
        return self._text


class MockClientSession:
    """モックaiohttpクライアントセッション."""

    def __init__(self, status: int = 200, text: str = "") -> None:
        self._status = status
        self._text = text

    async def __aenter__(self) -> "MockClientSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def get(self, url: str, **kwargs: object) -> "MockContextManager":  # noqa: ARG002
        return MockContextManager(self._status, self._text)


class MockContextManager:
    """モックコンテキストマネージャ（session.get()の戻り値）."""

    def __init__(self, status: int, text: str) -> None:
        self._status = status
        self._text = text

    async def __aenter__(self) -> MockResponse:
        return MockResponse(self._status, self._text)

    async def __aexit__(self, *args: object) -> None:
        pass


class TestCrawledPage:
    """CrawledPage データクラスのテスト."""

    def test_crawled_page_creation(self) -> None:
        """CrawledPage が正しく作成されること."""
        page = CrawledPage(
            url="https://example.com/test",
            title="テストタイトル",
            text="テスト本文",
            crawled_at="2024-01-01T00:00:00+00:00",
        )
        assert page.url == "https://example.com/test"
        assert page.title == "テストタイトル"
        assert page.text == "テスト本文"
        assert page.crawled_at == "2024-01-01T00:00:00+00:00"


class TestWebCrawlerValidation:
    """WebCrawler URL検証のテスト."""

    def test_ac30_disallowed_domain_rejected(self) -> None:
        """AC30: allowed_domains に含まれないドメインのURLがクロール拒否されること."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        with pytest.raises(ValueError, match="クロールが許可されていません"):
            crawler._validate_url("https://other-domain.com/page")

    def test_ac31_non_http_scheme_rejected(self) -> None:
        """AC31: http/https 以外のスキームが拒否されること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with pytest.raises(ValueError, match="許可されていないスキーム"):
            crawler._validate_url("file:///etc/passwd")

        with pytest.raises(ValueError, match="許可されていないスキーム"):
            crawler._validate_url("ftp://example.com/file")

    def test_ac33_empty_allowlist_rejects_all(self) -> None:
        """AC33: allowed_domains が未設定の場合、全てのURLが拒否されること."""
        crawler = WebCrawler(allowed_domains=[])
        with pytest.raises(ValueError, match="クロールが許可されたドメインが設定されていません"):
            crawler._validate_url("https://example.com/page")

    def test_ac33_none_allowlist_rejects_all(self) -> None:
        """AC33: allowed_domains が None の場合、全てのURLが拒否されること."""
        crawler = WebCrawler(allowed_domains=None)
        with pytest.raises(ValueError, match="クロールが許可されたドメインが設定されていません"):
            crawler._validate_url("https://example.com/page")

    def test_valid_url_passes(self) -> None:
        """許可されたドメインのURLが検証を通過すること."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        result = crawler._validate_url("https://example.com/page")
        assert result == "https://example.com/page"

    def test_subdomain_allowed(self) -> None:
        """サブドメインも許可されること."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        result = crawler._validate_url("https://sub.example.com/page")
        assert result == "https://sub.example.com/page"

    def test_http_scheme_allowed(self) -> None:
        """http スキームも許可されること."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        result = crawler._validate_url("http://example.com/page")
        assert result == "http://example.com/page"


class TestWebCrawlerTextExtraction:
    """WebCrawler テキスト抽出のテスト."""

    def test_extract_text_from_article(self) -> None:
        """<article> タグから本文を抽出すること."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        title, text = crawler._extract_text(SAMPLE_HTML_WITH_ARTICLE)

        assert title == "テスト記事"
        assert "記事タイトル" in text
        assert "これは記事の本文です" in text
        assert "2つ目の段落です" in text
        # 除去されるべき要素
        assert "ナビゲーション" not in text
        assert "ヘッダー" not in text
        assert "フッター" not in text
        assert "console.log" not in text

    def test_extract_text_from_main(self) -> None:
        """<main> タグから本文を抽出すること（<article> がない場合）."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        title, text = crawler._extract_text(SAMPLE_HTML_WITH_MAIN)

        assert title == "メインコンテンツ"
        assert "メインエリアのテキスト" in text
        assert "ナビ" not in text

    def test_extract_text_from_body(self) -> None:
        """<body> から本文を抽出すること（<article>, <main> がない場合）."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        title, text = crawler._extract_text(SAMPLE_HTML_BODY_ONLY)

        assert title == "ボディのみ"
        assert "ボディ内のテキスト" in text


class TestWebCrawlerCrawlIndexPage:
    """WebCrawler.crawl_index_page のテスト."""

    @pytest.mark.asyncio
    async def test_ac12_crawl_index_page_extracts_urls(self) -> None:
        """AC12: リンク集ページからURLリストを抽出できること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        # example.com ドメインのリンクのみ抽出される
        assert len(urls) >= 3
        assert "https://example.com/article/1" in urls
        assert "https://example.com/article/2" in urls
        assert "https://example.com/article/3" in urls
        # 許可されていないドメインは含まれない
        assert "https://other-domain.com/page" not in urls

    @pytest.mark.asyncio
    async def test_ac13_url_pattern_filtering(self) -> None:
        """AC13: URLパターン（正規表現）によるフィルタリングが機能すること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            # .html で終わるURLのみ抽出
            urls = await crawler.crawl_index_page(
                "https://example.com/articles",
                url_pattern=r"\.html$",
            )

        assert len(urls) == 2
        assert all(url.endswith(".html") for url in urls)

    @pytest.mark.asyncio
    async def test_ac32_extracted_links_validated(self) -> None:
        """AC32: 抽出したリンクURLもドメインホワイトリストで検証されること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        # 許可されていないドメインのURLは含まれない
        for url in urls:
            assert "other-domain.com" not in url

    @pytest.mark.asyncio
    async def test_ac34_max_crawl_pages_limit(self) -> None:
        """AC34: 1回のクロールで取得するページ数が max_pages で制限されること."""
        crawler = WebCrawler(allowed_domains=["example.com"], max_pages=2)

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        assert len(urls) <= 2

    @pytest.mark.asyncio
    async def test_index_page_validation_failure(self) -> None:
        """インデックスページのURL検証に失敗した場合、ValueError を送出すること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with pytest.raises(ValueError, match="クロールが許可されていません"):
            await crawler.crawl_index_page("https://malicious.com/articles")


class TestWebCrawlerCrawlPage:
    """WebCrawler.crawl_page のテスト."""

    @pytest.mark.asyncio
    async def test_ac14_crawl_page_extracts_text(self) -> None:
        """AC14: 単一ページの本文テキストを取得できること."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_HTML_WITH_ARTICLE),
        ):
            page = await crawler.crawl_page("https://example.com/article/1")

        assert page is not None
        assert page.url == "https://example.com/article/1"
        assert page.title == "テスト記事"
        assert "これは記事の本文です" in page.text
        assert page.crawled_at  # ISO 8601 形式のタイムスタンプ

    @pytest.mark.asyncio
    async def test_crawl_page_returns_none_on_http_error(self) -> None:
        """HTTPエラー時に None を返すこと."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(404, "Not Found"),
        ):
            page = await crawler.crawl_page("https://example.com/not-found")

        assert page is None

    @pytest.mark.asyncio
    async def test_crawl_page_returns_none_on_validation_failure(self) -> None:
        """URL検証失敗時に None を返すこと."""
        crawler = WebCrawler(allowed_domains=["example.com"])

        page = await crawler.crawl_page("https://malicious.com/page")

        assert page is None


class TestWebCrawlerCrawlPages:
    """WebCrawler.crawl_pages のテスト."""

    @pytest.mark.asyncio
    async def test_ac15_crawl_pages_isolates_errors(self) -> None:
        """AC15: 複数ページを並行クロールし、ページ単位のエラーを隔離すること."""
        crawler = WebCrawler(allowed_domains=["example.com"], crawl_delay=0)

        call_count = 0

        class MockClientSessionWithErrors:
            """エラーをシミュレートするモックセッション."""

            async def __aenter__(self) -> "MockClientSessionWithErrors":
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

            def get(self, url: str, **kwargs: object) -> "MockContextManagerWithErrors":  # noqa: ARG002
                nonlocal call_count
                call_count += 1
                if call_count == 2:  # 2番目のリクエストは失敗
                    return MockContextManagerWithErrors(500, "Server Error")
                return MockContextManagerWithErrors(200, SAMPLE_HTML_WITH_ARTICLE)

        class MockContextManagerWithErrors:
            """エラーをシミュレートするモックコンテキストマネージャ."""

            def __init__(self, status: int, text: str) -> None:
                self._status = status
                self._text = text

            async def __aenter__(self) -> MockResponse:
                return MockResponse(self._status, self._text)

            async def __aexit__(self, *args: object) -> None:
                pass

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSessionWithErrors(),
        ):
            urls = [
                "https://example.com/article/1",
                "https://example.com/article/2",  # これは失敗
                "https://example.com/article/3",
            ]
            pages = await crawler.crawl_pages(urls)

        # 2番目が失敗しても、1番目と3番目は成功している
        assert len(pages) == 2

    @pytest.mark.asyncio
    async def test_ac35_crawl_delay_between_requests(self) -> None:
        """AC35: 同一ドメインへの連続リクエスト間に crawl_delay の待機が挿入されること."""
        crawler = WebCrawler(allowed_domains=["example.com"], crawl_delay=0.1)

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_HTML_WITH_ARTICLE),
        ):
            with patch(
                "src.services.web_crawler.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                urls = [
                    "https://example.com/article/1",
                    "https://example.com/article/2",
                    "https://example.com/article/3",
                ]
                await crawler.crawl_pages(urls)

                # 最初のリクエスト以外で sleep が呼ばれる（2回）
                assert mock_sleep.call_count == 2
                mock_sleep.assert_called_with(0.1)

    @pytest.mark.asyncio
    async def test_crawl_pages_empty_list(self) -> None:
        """空のURLリストに対して空のリストを返すこと."""
        crawler = WebCrawler(allowed_domains=["example.com"])
        pages = await crawler.crawl_pages([])
        assert pages == []


class TestWebCrawlerConcurrency:
    """WebCrawler 並行制御のテスト."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self) -> None:
        """Semaphore により同時接続数が制限されること."""
        crawler = WebCrawler(
            allowed_domains=["example.com"],
            max_concurrent=2,
            crawl_delay=0,
        )

        # Semaphoreの初期値を確認
        assert crawler._semaphore._value == 2
