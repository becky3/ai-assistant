"""RAGナレッジ管理サービス

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING

from src.rag.chunker import chunk_text
from src.rag.vector_store import DocumentChunk, VectorStore

if TYPE_CHECKING:
    from src.services.web_crawler import CrawledPage, WebCrawler

logger = logging.getLogger(__name__)


class RAGKnowledgeService:
    """RAGナレッジ管理サービス.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        vector_store: VectorStore,
        web_crawler: WebCrawler,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> None:
        """RAGKnowledgeServiceを初期化する.

        Args:
            vector_store: ベクトルストア
            web_crawler: Webクローラー
            chunk_size: チャンクの最大文字数
            chunk_overlap: チャンク間のオーバーラップ文字数
        """
        self._vector_store = vector_store
        self._web_crawler = web_crawler
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    async def ingest_from_index(
        self,
        index_url: str,
        url_pattern: str = "",
    ) -> dict[str, int]:
        """リンク集ページから一括取り込み.

        Args:
            index_url: リンク集ページのURL
            url_pattern: 正規表現パターンでリンクをフィルタリング（任意）

        Returns:
            {"pages_crawled": N, "chunks_stored": M, "errors": E}
        """
        # リンク集ページからURLリストを抽出
        urls = await self._web_crawler.crawl_index_page(index_url, url_pattern)
        if not urls:
            logger.warning("No URLs found in index page: %s", index_url)
            return {"pages_crawled": 0, "chunks_stored": 0, "errors": 0}

        # 複数ページを並行クロール
        pages = await self._web_crawler.crawl_pages(urls)

        # 各ページをチャンキングして保存
        total_chunks = 0
        errors = len(urls) - len(pages)

        for page in pages:
            try:
                chunks_stored = await self._ingest_crawled_page(page)
                total_chunks += chunks_stored
            except Exception:
                logger.exception("Failed to ingest page: %s", page.url)
                errors += 1

        logger.info(
            "Ingested from index: pages=%d, chunks=%d, errors=%d",
            len(pages),
            total_chunks,
            errors,
        )

        return {
            "pages_crawled": len(pages),
            "chunks_stored": total_chunks,
            "errors": errors,
        }

    async def ingest_page(self, url: str) -> int:
        """単一ページ取り込み.

        同一URLの再取り込み時は、既存チャンクを delete_by_source() で
        削除してから新規追加する（upsert動作）。

        Args:
            url: 取り込むページのURL

        Returns:
            チャンク数
        """
        page = await self._web_crawler.crawl_page(url)
        if page is None:
            logger.warning("Failed to crawl page: %s", url)
            return 0

        return await self._ingest_crawled_page(page)

    async def _ingest_crawled_page(self, page: CrawledPage) -> int:
        """クロール済みページをチャンキングして保存する.

        Args:
            page: クロール済みページ

        Returns:
            保存されたチャンク数
        """
        # 既存チャンクを削除（upsert動作）
        await self._vector_store.delete_by_source(page.url)

        # テキストをチャンキング
        chunks = chunk_text(
            page.text,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        if not chunks:
            logger.info("No chunks generated for page: %s", page.url)
            return 0

        # DocumentChunkに変換
        url_hash = hashlib.md5(page.url.encode()).hexdigest()[:8]
        document_chunks = [
            DocumentChunk(
                id=f"{url_hash}_{i}",
                text=chunk,
                metadata={
                    "source_url": page.url,
                    "title": page.title,
                    "chunk_index": i,
                    "crawled_at": page.crawled_at,
                },
            )
            for i, chunk in enumerate(chunks)
        ]

        # ベクトルストアに保存
        count = await self._vector_store.add_documents(document_chunks)
        logger.info("Ingested page %s: %d chunks", page.url, count)
        return count

    async def retrieve(self, query: str, n_results: int = 5) -> str:
        """関連知識を検索し、フォーマット済みテキストとして返す.

        ChatService から呼ばれる。結果なしの場合は空文字列。

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数

        Returns:
            フォーマット済みの関連知識テキスト。結果がない場合は空文字列。
        """
        results = await self._vector_store.search(query, n_results=n_results)

        if not results:
            return ""

        # フォーマット済みテキストを構築
        formatted_parts: list[str] = []
        for i, result in enumerate(results, start=1):
            source_url = result.metadata.get("source_url", "不明")
            formatted_parts.append(
                f"--- 参考情報 {i} ---\n出典: {source_url}\n{result.text}"
            )

        return "\n\n".join(formatted_parts)

    async def delete_source(self, source_url: str) -> int:
        """ソースURL指定で知識を削除.

        Args:
            source_url: 削除するソースURL

        Returns:
            削除チャンク数
        """
        count = await self._vector_store.delete_by_source(source_url)
        logger.info("Deleted %d chunks from source: %s", count, source_url)
        return count

    async def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計.

        Returns:
            統計情報の辞書
        """
        return self._vector_store.get_stats()
