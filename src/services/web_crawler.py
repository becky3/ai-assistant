"""Webページクローラー

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# User-Agent for crawler identification
USER_AGENT = "AI-Assistant-Crawler/1.0"


@dataclass
class CrawledPage:
    """クロール結果."""

    url: str
    title: str
    text: str  # 抽出済みプレーンテキスト
    crawled_at: str  # ISO 8601 タイムスタンプ


class WebCrawler:
    """Webページクローラー.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        timeout: float = 30.0,
        allowed_domains: list[str] | None = None,
        max_pages: int = 50,
        crawl_delay: float = 1.0,
        max_concurrent: int = 5,
    ) -> None:
        """WebCrawlerを初期化する.

        Args:
            timeout: HTTPリクエストのタイムアウト秒数
            allowed_domains: クロールを許可するドメインのリスト（SSRF対策）
            max_pages: 1回のクロールで取得する最大ページ数
            crawl_delay: 同一ドメインへの連続リクエスト間の待機秒数
            max_concurrent: 同時接続数の上限
        """
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._allowed_domains = set(allowed_domains or [])
        self._max_pages = max_pages
        self._crawl_delay = crawl_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _validate_url(self, url: str) -> str:
        """SSRF対策のURL検証. 問題なければ正規化済みURLを返す.

        検証内容:
        - スキームが http または https であること
        - ホスト名が allowed_domains に含まれること
        - 検証失敗時は ValueError を送出

        Args:
            url: 検証するURL

        Returns:
            正規化済みURL

        Raises:
            ValueError: URL検証に失敗した場合
        """
        parsed = urlparse(url)

        # スキーム検証
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"許可されていないスキームです: {parsed.scheme}. http または https のみ許可されます。"
            )

        # ホスト名検証
        hostname = parsed.hostname or ""
        if not hostname:
            raise ValueError("URLにホスト名が含まれていません。")

        # allowed_domains が空の場合は全てのドメインを拒否
        if not self._allowed_domains:
            raise ValueError(
                "クロールが許可されたドメインが設定されていません。"
                "RAG_ALLOWED_DOMAINS を設定してください。"
            )

        # ドメイン検証（サブドメインも許可）
        domain_allowed = False
        for allowed in self._allowed_domains:
            if hostname == allowed or hostname.endswith("." + allowed):
                domain_allowed = True
                break

        if not domain_allowed:
            raise ValueError(
                f"ドメイン '{hostname}' はクロールが許可されていません。"
                f"許可ドメイン: {', '.join(sorted(self._allowed_domains))}"
            )

        return url

    def _extract_text(self, html: str) -> tuple[str, str]:
        """HTMLから本文テキストを抽出する.

        抽出ロジック:
        1. <script>, <style>, <nav>, <header>, <footer> タグを除去
        2. <article> → <main> → <body> の優先順で本文領域を特定
        3. テキストを抽出してクリーンアップ

        Args:
            html: HTML文字列

        Returns:
            (title, text) のタプル
        """
        soup = BeautifulSoup(html, "html.parser")

        # タイトル抽出
        title = ""
        title_tag = soup.find("title")
        if title_tag and title_tag.string:
            title = title_tag.string.strip()

        # 不要なタグを除去
        for tag_name in ("script", "style", "nav", "header", "footer", "aside", "noscript"):
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 本文領域を特定（優先順: article → main → body）
        content_element = soup.find("article")
        if content_element is None:
            content_element = soup.find("main")
        if content_element is None:
            content_element = soup.find("body")
        if content_element is None:
            content_element = soup

        # テキスト抽出とクリーンアップ
        text = content_element.get_text(separator="\n", strip=True)
        # 連続する空白行を1つにまとめる
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 連続するスペースを1つにまとめる
        text = re.sub(r"[ \t]+", " ", text)

        return title, text.strip()

    async def crawl_index_page(
        self,
        index_url: str,
        url_pattern: str = "",
    ) -> list[str]:
        """リンク集ページ内の <a> タグからURLリストを抽出する（深度1のみ、再帰クロールは行わない）.

        - index_url および抽出したリンクURLを _validate_url() で検証
        - 抽出URL数が max_pages を超える場合は先頭 max_pages 件に制限

        Args:
            index_url: リンク集ページのURL
            url_pattern: 正規表現パターンでリンクをフィルタリング（任意）

        Returns:
            抽出されたURLのリスト

        Raises:
            ValueError: URL検証に失敗した場合
        """
        # インデックスページのURL検証
        validated_url = self._validate_url(index_url)

        # パターンのコンパイル
        pattern = re.compile(url_pattern) if url_pattern else None

        # ページ取得
        async with aiohttp.ClientSession(
            timeout=self._timeout,
            headers={"User-Agent": USER_AGENT},
        ) as session:
            async with session.get(validated_url) as resp:
                if resp.status != 200:
                    logger.warning("Failed to fetch index page: %s (status=%d)", index_url, resp.status)
                    return []
                html = await resp.text(errors="replace")

        # リンク抽出
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        seen: set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag.get("href")
            if not isinstance(href, str):
                continue
            # 相対URLを絶対URLに変換
            absolute_url = urljoin(index_url, href)

            # 重複スキップ
            if absolute_url in seen:
                continue

            # パターンフィルタリング
            if pattern and not pattern.search(absolute_url):
                continue

            # URL検証（許可されていないドメインはスキップ）
            try:
                self._validate_url(absolute_url)
            except ValueError:
                continue

            seen.add(absolute_url)
            urls.append(absolute_url)

            # max_pages に達したら終了
            if len(urls) >= self._max_pages:
                break

        return urls

    async def crawl_page(self, url: str) -> CrawledPage | None:
        """単一ページの本文テキストを取得する. 失敗時は None.

        - _validate_url() でURL検証後にHTTPアクセスを行う

        Args:
            url: クロールするURL

        Returns:
            CrawledPage オブジェクト、または失敗時は None
        """
        try:
            validated_url = self._validate_url(url)
        except ValueError as e:
            logger.warning("URL validation failed: %s - %s", url, e)
            return None

        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(
                    timeout=self._timeout,
                    headers={"User-Agent": USER_AGENT},
                ) as session:
                    async with session.get(validated_url) as resp:
                        if resp.status != 200:
                            logger.warning("Failed to fetch page: %s (status=%d)", url, resp.status)
                            return None
                        html = await resp.text(errors="replace")

            title, text = self._extract_text(html)
            crawled_at = datetime.now(tz=timezone.utc).isoformat()

            return CrawledPage(
                url=url,
                title=title,
                text=text,
                crawled_at=crawled_at,
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout while fetching page: %s", url)
            return None
        except aiohttp.ClientError as e:
            logger.warning("HTTP error while fetching page: %s - %s", url, e)
            return None
        except Exception:
            logger.exception("Unexpected error while fetching page: %s", url)
            return None

    async def crawl_pages(self, urls: list[str]) -> list[CrawledPage]:
        """複数ページを並行クロールする.

        - 各リクエスト間に crawl_delay 秒の待機を挿入（同一ドメインへの負荷軽減）
        - ページ単位でエラーを隔離し、他のページの処理は継続

        Args:
            urls: クロールするURLのリスト

        Returns:
            クロールに成功したページのリスト
        """
        results: list[CrawledPage] = []

        for i, url in enumerate(urls):
            # 最初のリクエスト以外は遅延を挿入
            if i > 0 and self._crawl_delay > 0:
                await asyncio.sleep(self._crawl_delay)

            page = await self.crawl_page(url)
            if page is not None:
                results.append(page)

        return results
