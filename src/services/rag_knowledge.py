"""RAGナレッジ管理サービス

仕様: docs/specs/f9-rag-knowledge.md, docs/specs/f9-rag-evaluation.md
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urldefrag

from src.rag.chunker import chunk_text
from src.rag.vector_store import DocumentChunk, VectorStore

if TYPE_CHECKING:
    from src.services.web_crawler import CrawledPage, WebCrawler

logger = logging.getLogger(__name__)


@dataclass
class RAGRetrievalResult:
    """RAG検索結果.

    仕様: docs/specs/f9-rag-evaluation.md

    Attributes:
        context: フォーマット済みテキスト（システムプロンプト注入用）
        sources: ユニークなソースURLリスト（表示用）
    """

    context: str
    sources: list[str]


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

        同一URLの再取り込み時は、まず add_documents() による upsert を行い、
        その後 delete_stale_chunks() で不要になったチャンクを削除する。

        Args:
            url: 取り込むページのURL

        Returns:
            チャンク数

        Raises:
            ValueError: URL検証に失敗した場合
        """
        # URL検証を先に行い、失敗時は例外を投げる（ユーザーにエラー理由を伝えるため）
        # 戻り値（正規化済みURL）を以降の処理で使用
        validated_url = self._web_crawler.validate_url(url)

        page = await self._web_crawler.crawl_page(validated_url)
        if page is None:
            logger.warning("Failed to crawl page: %s", validated_url)
            return 0

        return await self._ingest_crawled_page(page)

    async def _ingest_crawled_page(self, page: CrawledPage) -> int:
        """クロール済みページをチャンキングして保存する.

        Args:
            page: クロール済みページ

        Returns:
            保存されたチャンク数
        """
        # テキストをチャンキング
        chunks = chunk_text(
            page.text,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

        if not chunks:
            # チャンク生成失敗時は既存ナレッジを削除しない（データ喪失防止）
            logger.info("No chunks generated for page: %s", page.url)
            return 0

        # URLからフラグメントを除去して正規化（上流で除去済みだが防御的に再適用）
        normalized_url, _ = urldefrag(page.url)

        # DocumentChunkに変換
        # SHA256の先頭16文字を使用（衝突確率が十分に低い）
        url_hash = hashlib.sha256(normalized_url.encode()).hexdigest()[:16]
        document_chunks = [
            DocumentChunk(
                id=f"{url_hash}_{i}",
                text=chunk,
                metadata={
                    "source_url": normalized_url,
                    "title": page.title,
                    "chunk_index": i,
                    "crawled_at": page.crawled_at,
                },
            )
            for i, chunk in enumerate(chunks)
        ]
        new_ids = {chunk.id for chunk in document_chunks}

        # ベクトルストアにupsert（失敗時もデータロスを防ぐため、先に追加）
        count = await self._vector_store.add_documents(document_chunks)

        # upsert成功後、古いチャンクを削除（チャンク数が減った場合）
        await self._vector_store.delete_stale_chunks(normalized_url, new_ids)

        logger.info("Ingested page %s: %d chunks", normalized_url, count)
        return count

    async def retrieve(self, query: str, n_results: int = 5) -> RAGRetrievalResult:
        """関連知識を検索し、結果を返す.

        ChatService から呼ばれる。結果なしの場合は空のRAGRetrievalResult。

        仕様: docs/specs/f9-rag-evaluation.md

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数

        Returns:
            RAGRetrievalResult: コンテキストとソース情報
        """
        from src.config.settings import get_settings

        settings = get_settings()
        results = await self._vector_store.search(query, n_results=n_results)

        if not results:
            return RAGRetrievalResult(context="", sources=[])

        # デバッグログ出力
        if settings.rag_debug_log_enabled:
            logger.info("RAG retrieve: query=%r", query)
            for i, result in enumerate(results, start=1):
                source_url = result.metadata.get("source_url", "不明")
                # INFOレベルではdistance・sourceのみ出力（PII漏洩リスク軽減）
                logger.info(
                    "RAG result %d: distance=%.3f source=%r",
                    i,
                    result.distance,
                    source_url,
                )
                # テキストプレビューはDEBUGレベルに限定
                text_preview = (
                    result.text[:100] + "..." if len(result.text) > 100 else result.text
                )
                logger.debug("RAG result %d text: %r", i, text_preview)
                logger.debug("RAG result %d full text: %r", i, result.text)

        # フォーマット済みテキストを構築
        formatted_parts: list[str] = []
        sources: list[str] = []
        for i, result in enumerate(results, start=1):
            source_url = str(result.metadata.get("source_url", "不明"))
            formatted_parts.append(
                f"--- 参考情報 {i} ---\n出典: {source_url}\n{result.text}"
            )
            if source_url != "不明" and source_url not in sources:
                sources.append(source_url)

        return RAGRetrievalResult(
            context="\n\n".join(formatted_parts),
            sources=sources,
        )

    async def delete_source(self, source_url: str) -> int:
        """ソースURL指定で知識を削除.

        Args:
            source_url: 削除するソースURL

        Returns:
            削除チャンク数
        """
        # フラグメントを除去して正規化
        normalized_url, fragment = urldefrag(source_url)

        # 正規化後のURLに紐づくチャンクを削除
        total_deleted = await self._vector_store.delete_by_source(normalized_url)

        # 後方互換: 以前はフラグメント付きURLで保存していた可能性があるため、
        # 元のURL（フラグメント付き）でも削除を試みる
        if fragment:
            legacy_deleted = await self._vector_store.delete_by_source(source_url)
            total_deleted += legacy_deleted
            logger.info(
                "Deleted %d chunks from sources: %s (normalized), %s (with fragment)",
                total_deleted,
                normalized_url,
                source_url,
            )
        else:
            logger.info("Deleted %d chunks from source: %s", total_deleted, normalized_url)

        return total_deleted

    async def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計.

        Returns:
            統計情報の辞書
        """
        # VectorStore.get_stats()は同期APIを呼ぶため、to_threadでラップ
        return await asyncio.to_thread(self._vector_store.get_stats)
