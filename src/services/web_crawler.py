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
        max_pages: int = 50,
        crawl_delay: float = 1.0,
        max_concurrent: int = 5,
    ) -> None:
        """WebCrawlerを初期化する.

        Args:
            timeout: HTTPリクエストのタイムアウト秒数
            max_pages: 1回のクロールで取得する最大ページ数
            crawl_delay: 同一ドメインへの連続リクエスト間の待機秒数
            max_concurrent: 同時接続数の上限
        """
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._max_pages = max_pages
        self._crawl_delay = crawl_delay
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def validate_url(self, url: str) -> str:
        """URL検証. 問題なければ検証済みURLを返す.

        検証内容:
        - スキームが http または https であること
        - 検証失敗時は ValueError を送出

        Args:
            url: 検証するURL

        Returns:
            検証済みURL（現時点では入力URLをそのまま返す）

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

        - index_url および抽出したリンクURLを validate_url() で検証
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
        validated_url = self.validate_url(index_url)

        # パターンのコンパイル
        pattern = re.compile(url_pattern) if url_pattern else None

        # ページ取得（SSRF対策: リダイレクト追従を無効化）
        async with aiohttp.ClientSession(
            timeout=self._timeout,
        ) as session:
            async with session.get(validated_url, allow_redirects=False) as resp:
                # リダイレクト応答の場合はログを出して空リストを返す
                if resp.status in (301, 302, 303, 307, 308):
                    logger.warning(
                        "Redirect detected (SSRF protection): %s -> %s",
                        index_url,
                        resp.headers.get("Location", "unknown"),
                    )
                    return []
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

            # スキーム検証（http/https以外は除外）
            # 将来のURL安全性チェック機能（Issue #159）に備えて検証を維持
            try:
                self.validate_url(absolute_url)
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

        - validate_url() でURL検証後にHTTPアクセスを行う

        Args:
            url: クロールするURL

        Returns:
            CrawledPage オブジェクト、または失敗時は None
        """
        try:
            validated_url = self.validate_url(url)
        except ValueError as e:
            logger.warning("URL validation failed: %s - %s", url, e)
            return None

        try:
            async with self._semaphore:
                async with aiohttp.ClientSession(
                    timeout=self._timeout,
                ) as session:
                    # SSRF対策: リダイレクト追従を無効化
                    async with session.get(validated_url, allow_redirects=False) as resp:
                        # リダイレクト応答の場合はログを出して None を返す
                        if resp.status in (301, 302, 303, 307, 308):
                            logger.warning(
                                "Redirect detected (SSRF protection): %s -> %s",
                                url,
                                resp.headers.get("Location", "unknown"),
                            )
                            return None
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

        - Semaphore により同時接続数を max_concurrent に制限
        - 同一ドメインへの連続リクエスト間に crawl_delay 秒の待機を挿入（負荷軽減）
        - ページ単位でエラーを隔離し、他のページの処理は継続

        Args:
            urls: クロールするURLのリスト

        Returns:
            クロールに成功したページのリスト
        """
        if not urls:
            return []

        # ホストごとの最終リクエスト時刻を管理するロック付き辞書
        last_request_time: dict[str, float] = {}
        time_lock = asyncio.Lock()

        async def crawl_with_delay(url: str) -> CrawledPage | None:
            """同一ドメインへの遅延を挿入してクロールする."""
            hostname = urlparse(url).hostname

            if hostname and self._crawl_delay > 0:
                async with time_lock:
                    previous = last_request_time.get(hostname)
                    if previous is not None:
                        now = asyncio.get_event_loop().time()
                        elapsed = now - previous
                        if elapsed < self._crawl_delay:
                            await asyncio.sleep(self._crawl_delay - elapsed)
                    # リクエスト前に時刻を更新（他のタスクが同じホストに同時アクセスしないようにする）
                    last_request_time[hostname] = asyncio.get_event_loop().time()

            page = await self.crawl_page(url)

            # リクエスト後に実際の完了時刻を更新
            if hostname:
                async with time_lock:
                    last_request_time[hostname] = asyncio.get_event_loop().time()

            return page

        # 並行実行（Semaphore は crawl_page 内で適用される）
        tasks = [crawl_with_delay(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 成功したページのみを収集（例外はログ済みなのでスキップ）
        pages: list[CrawledPage] = []
        for result in results:
            if isinstance(result, CrawledPage):
                pages.append(result)

        return pages
