"""WebCrawler テスト

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import asyncio
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

    def __init__(
        self, status: int = 200, text: str = "", headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self._text = text
        self.headers: dict[str, str] = headers or {}

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

    def __init__(
        self, status: int, text: str, headers: dict[str, str] | None = None
    ) -> None:
        self._status = status
        self._text = text
        self._headers = headers

    async def __aenter__(self) -> MockResponse:
        return MockResponse(self._status, self._text, self._headers)

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

    def test_ac31_non_http_scheme_rejected(self) -> None:
        """AC31: http/https 以外のスキームが拒否されること."""
        crawler = WebCrawler()

        with pytest.raises(ValueError, match="許可されていないスキーム"):
            crawler.validate_url("file:///etc/passwd")

        with pytest.raises(ValueError, match="許可されていないスキーム"):
            crawler.validate_url("ftp://example.com/file")

    def test_valid_url_passes(self) -> None:
        """有効なURLが検証を通過すること."""
        crawler = WebCrawler()
        result = crawler.validate_url("https://example.com/page")
        assert result == "https://example.com/page"

    def test_http_scheme_allowed(self) -> None:
        """http スキームも許可されること."""
        crawler = WebCrawler()
        result = crawler.validate_url("http://example.com/page")
        assert result == "http://example.com/page"

    def test_any_domain_allowed(self) -> None:
        """任意のドメインが許可されること."""
        crawler = WebCrawler()
        result = crawler.validate_url("https://any-domain.com/page")
        assert result == "https://any-domain.com/page"

    def test_localhost_rejected(self) -> None:
        """SSRF対策: localhostへのアクセスが拒否されること."""
        crawler = WebCrawler()

        with pytest.raises(ValueError, match="localhost"):
            crawler.validate_url("http://localhost/admin")

        with pytest.raises(ValueError, match="localhost"):
            crawler.validate_url("https://localhost:8080/api")

    def test_loopback_ip_rejected(self) -> None:
        """SSRF対策: ループバックIP (127.0.0.1) へのアクセスが拒否されること."""
        crawler = WebCrawler()

        with pytest.raises(ValueError, match="ループバックアドレス"):
            crawler.validate_url("http://127.0.0.1/admin")

        with pytest.raises(ValueError, match="ループバックアドレス"):
            crawler.validate_url("http://127.0.0.2/admin")

    def test_private_ip_rejected(self) -> None:
        """SSRF対策: プライベートIP (RFC1918) へのアクセスが拒否されること."""
        crawler = WebCrawler()

        # 10.0.0.0/8
        with pytest.raises(ValueError, match="プライベートIPアドレス"):
            crawler.validate_url("http://10.0.0.1/internal")

        # 172.16.0.0/12
        with pytest.raises(ValueError, match="プライベートIPアドレス"):
            crawler.validate_url("http://172.16.0.1/internal")

        # 192.168.0.0/16
        with pytest.raises(ValueError, match="プライベートIPアドレス"):
            crawler.validate_url("http://192.168.1.1/internal")

    def test_link_local_ip_rejected(self) -> None:
        """SSRF対策: リンクローカルIP (169.254.0.0/16) へのアクセスが拒否されること."""
        crawler = WebCrawler()

        # AWS metadata endpoint
        with pytest.raises(ValueError, match="リンクローカルアドレス"):
            crawler.validate_url("http://169.254.169.254/latest/meta-data/")


class TestWebCrawlerTextExtraction:
    """WebCrawler テキスト抽出のテスト."""

    def test_extract_text_from_article(self) -> None:
        """<article> タグから本文を抽出すること."""
        crawler = WebCrawler()
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
        crawler = WebCrawler()
        title, text = crawler._extract_text(SAMPLE_HTML_WITH_MAIN)

        assert title == "メインコンテンツ"
        assert "メインエリアのテキスト" in text
        assert "ナビ" not in text

    def test_extract_text_from_body(self) -> None:
        """<body> から本文を抽出すること（<article>, <main> がない場合）."""
        crawler = WebCrawler()
        title, text = crawler._extract_text(SAMPLE_HTML_BODY_ONLY)

        assert title == "ボディのみ"
        assert "ボディ内のテキスト" in text


class TestWebCrawlerCrawlIndexPage:
    """WebCrawler.crawl_index_page のテスト."""

    @pytest.mark.asyncio
    async def test_ac12_crawl_index_page_extracts_urls(self) -> None:
        """AC12: リンク集ページからURLリストを抽出できること."""
        crawler = WebCrawler()

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        # SAMPLE_INDEX_HTML には6つのリンクがある
        # 期待されるURLを厳密に検証
        expected_urls = {
            "https://example.com/article/1",
            "https://example.com/article/2",
            "https://example.com/article/3",
            "https://other-domain.com/page",
            "https://example.com/doc/guide.html",
            "https://example.com/doc/faq.html",
        }
        assert set(urls) == expected_urls
        assert len(urls) == 6

    @pytest.mark.asyncio
    async def test_ac13_url_pattern_filtering(self) -> None:
        """AC13: URLパターン（正規表現）によるフィルタリングが機能すること."""
        crawler = WebCrawler()

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
    async def test_ac34_max_crawl_pages_limit(self) -> None:
        """AC34: 1回のクロールで取得するページ数が max_pages で制限されること."""
        crawler = WebCrawler(max_pages=2)

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_INDEX_HTML),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        assert len(urls) <= 2


class TestWebCrawlerCrawlPage:
    """WebCrawler.crawl_page のテスト."""

    @pytest.mark.asyncio
    async def test_ac14_crawl_page_extracts_text(self) -> None:
        """AC14: 単一ページの本文テキストを取得できること."""
        crawler = WebCrawler()

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
        crawler = WebCrawler()

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(404, "Not Found"),
        ):
            page = await crawler.crawl_page("https://example.com/not-found")

        assert page is None

    @pytest.mark.asyncio
    async def test_crawl_page_returns_none_on_scheme_validation_failure(self) -> None:
        """スキーム検証失敗時に None を返すこと."""
        crawler = WebCrawler()

        page = await crawler.crawl_page("file:///etc/passwd")

        assert page is None

    @pytest.mark.asyncio
    async def test_crawl_page_rejects_redirect(self) -> None:
        """SSRF対策: リダイレクト応答を拒否すること."""
        crawler = WebCrawler()

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(302, ""),
        ):
            page = await crawler.crawl_page("https://example.com/redirect")

        assert page is None


class TestWebCrawlerCrawlIndexPageRedirect:
    """WebCrawler.crawl_index_page のリダイレクト対策テスト."""

    @pytest.mark.asyncio
    async def test_crawl_index_page_rejects_redirect(self) -> None:
        """SSRF対策: インデックスページのリダイレクト応答を拒否すること."""
        crawler = WebCrawler()

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(301, ""),
        ):
            urls = await crawler.crawl_index_page("https://example.com/articles")

        assert urls == []


class TestWebCrawlerCrawlPages:
    """WebCrawler.crawl_pages のテスト."""

    @pytest.mark.asyncio
    async def test_ac15_crawl_pages_isolates_errors(self) -> None:
        """AC15: 複数ページを並行クロールし、ページ単位のエラーを隔離すること."""
        crawler = WebCrawler(crawl_delay=0)

        # 特定のURLを失敗させる（並行実行でも順序非依存）
        fail_url = "https://example.com/article/2"

        class MockClientSessionWithErrors:
            """エラーをシミュレートするモックセッション."""

            async def __aenter__(self) -> "MockClientSessionWithErrors":
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

            def get(self, url: str, **kwargs: object) -> "MockContextManagerWithErrors":  # noqa: ARG002
                # URLに応じて成功/失敗を決定（順序非依存）
                if url == fail_url:
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
                fail_url,  # これは失敗
                "https://example.com/article/3",
            ]
            pages = await crawler.crawl_pages(urls)

        # fail_url が失敗しても、他のページは成功している
        assert len(pages) == 2
        page_urls = [p.url for p in pages]
        assert "https://example.com/article/1" in page_urls
        assert "https://example.com/article/3" in page_urls
        assert fail_url not in page_urls

    @pytest.mark.asyncio
    async def test_ac35_crawl_delay_between_requests(self) -> None:
        """AC35: 同一ドメインへの連続リクエスト間に crawl_delay の待機が挿入されること."""
        crawler = WebCrawler(crawl_delay=0.1)

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSession(200, SAMPLE_HTML_WITH_ARTICLE),
        ):
            with patch(
                "src.services.web_crawler.asyncio.sleep", new_callable=AsyncMock
            ) as mock_sleep:
                # 同一ドメインへの複数リクエスト + 異なるドメインへのリクエスト
                urls = [
                    "https://example.com/article/1",
                    "https://example.com/article/2",  # 同一ドメイン（遅延あり）
                    "https://other.com/page",  # 異なるドメイン（遅延なし）
                ]
                await crawler.crawl_pages(urls)

                # sleep が呼ばれたことを確認（同一ドメインへの遅延）
                # 並行実行のため、厳密な回数は実行順序に依存するが、少なくとも1回は呼ばれる
                assert mock_sleep.call_count >= 1

    @pytest.mark.asyncio
    async def test_crawl_pages_empty_list(self) -> None:
        """空のURLリストに対して空のリストを返すこと."""
        crawler = WebCrawler()
        pages = await crawler.crawl_pages([])
        assert pages == []


class TestWebCrawlerConcurrency:
    """WebCrawler 並行制御のテスト."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_requests(self) -> None:
        """Semaphore により同時接続数が制限されること."""
        max_concurrent = 2
        crawler = WebCrawler(
            max_concurrent=max_concurrent,
            crawl_delay=0,
        )

        # 同時実行数を追跡
        current_concurrent = 0
        max_observed_concurrent = 0
        lock = asyncio.Lock()

        class MockClientSessionWithConcurrencyTracking:
            """同時実行数を追跡するモックセッション."""

            async def __aenter__(self) -> "MockClientSessionWithConcurrencyTracking":
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

            def get(self, url: str, **kwargs: object) -> "MockContextManagerWithDelay":  # noqa: ARG002
                return MockContextManagerWithDelay()

        class MockContextManagerWithDelay:
            """遅延を入れて同時実行をシミュレートするコンテキストマネージャ."""

            async def __aenter__(self) -> MockResponse:
                nonlocal current_concurrent, max_observed_concurrent
                async with lock:
                    current_concurrent += 1
                    max_observed_concurrent = max(max_observed_concurrent, current_concurrent)
                # 少し待機して同時実行をシミュレート
                await asyncio.sleep(0.05)
                return MockResponse(200, SAMPLE_HTML_WITH_ARTICLE)

            async def __aexit__(self, *args: object) -> None:
                nonlocal current_concurrent
                async with lock:
                    current_concurrent -= 1

        with patch(
            "src.services.web_crawler.aiohttp.ClientSession",
            return_value=MockClientSessionWithConcurrencyTracking(),
        ):
            urls = [f"https://example.com/article/{i}" for i in range(5)]
            await crawler.crawl_pages(urls)

        # 同時実行数が max_concurrent を超えていないことを確認
        assert max_observed_concurrent <= max_concurrent
