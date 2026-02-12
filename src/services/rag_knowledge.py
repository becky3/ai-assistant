"""RAGナレッジ管理サービス

仕様: docs/specs/f9-rag.md
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urldefrag

from src.rag.chunker import chunk_text
from src.rag.content_detector import ContentType, detect_content_type
from src.rag.heading_chunker import chunk_by_headings
from src.rag.table_chunker import chunk_table_data
from src.rag.vector_store import DocumentChunk, VectorStore

if TYPE_CHECKING:
    from src.config.settings import Settings
    from src.rag.bm25_index import BM25Index
    from src.rag.hybrid_search import HybridSearchEngine
    from src.services.safe_browsing import SafeBrowsingClient
    from src.services.web_crawler import CrawledPage, WebCrawler

logger = logging.getLogger(__name__)


@dataclass
class RAGRetrievalResult:
    """RAG検索結果.

    仕様: docs/specs/f9-rag.md

    Attributes:
        context: フォーマット済みテキスト（システムプロンプト注入用）
        sources: ユニークなソースURLリスト（表示用）
    """

    context: str
    sources: list[str]


class RAGKnowledgeService:
    """RAGナレッジ管理サービス.

    仕様: docs/specs/f9-rag.md
    """

    def __init__(
        self,
        vector_store: VectorStore,
        web_crawler: WebCrawler,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        safe_browsing_client: SafeBrowsingClient | None = None,
        bm25_index: BM25Index | None = None,
        hybrid_search_enabled: bool = False,
    ) -> None:
        """RAGKnowledgeServiceを初期化する.

        Args:
            vector_store: ベクトルストア
            web_crawler: Webクローラー
            chunk_size: チャンクの最大文字数
            chunk_overlap: チャンク間のオーバーラップ文字数
            safe_browsing_client: Safe Browsing クライアント（オプション）
            bm25_index: BM25インデックス（オプション、ハイブリッド検索用）
            hybrid_search_enabled: ハイブリッド検索の有効/無効
        """
        self._vector_store = vector_store
        self._web_crawler = web_crawler
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._safe_browsing_client = safe_browsing_client
        self._bm25_index = bm25_index
        self._hybrid_search_enabled = hybrid_search_enabled
        self._hybrid_search_engine: HybridSearchEngine | None = None

        # ハイブリッド検索エンジンの初期化
        if hybrid_search_enabled and bm25_index is not None:
            from src.config.settings import get_settings
            from src.rag.hybrid_search import HybridSearchEngine

            settings = get_settings()
            self._hybrid_search_engine = HybridSearchEngine(
                vector_store=vector_store,
                bm25_index=bm25_index,
                vector_weight=settings.rag_vector_weight,
                rrf_k=settings.rag_rrf_k,
            )
            logger.info("Hybrid search engine initialized")

    async def ingest_from_index(
        self,
        index_url: str,
        url_pattern: str = "",
        progress_callback: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict[str, int]:
        """リンク集ページから一括取り込み.

        Args:
            index_url: リンク集ページのURL
            url_pattern: 正規表現パターンでリンクをフィルタリング（任意）
            progress_callback: 進捗コールバック関数（オプション）
                引数: (crawled: int, total: int)
                crawled: クロール完了ページ数
                total: 総ページ数

        Returns:
            {"pages_crawled": N, "chunks_stored": M, "errors": E, "unsafe_urls": U}

        Raises:
            SafetyCheckError: Safe Browsing APIでfail_open=False設定時、
                API障害が発生した場合に送出される
        """
        # リンク集ページからURLリストを抽出
        urls = await self._web_crawler.crawl_index_page(index_url, url_pattern)
        if not urls:
            logger.warning("No URLs found in index page: %s", index_url)
            return {"pages_crawled": 0, "chunks_stored": 0, "errors": 0, "unsafe_urls": 0}

        # Safe Browsing チェック（有効な場合のみ）
        safe_urls = urls
        unsafe_count = 0
        if self._safe_browsing_client:
            check_results = await self._safe_browsing_client.check_urls(urls)
            safe_urls = []
            for url in urls:
                result = check_results.get(url)
                if result and not result.is_safe:
                    threat_types = [t.threat_type.value for t in result.threats]
                    logger.warning(
                        "Unsafe URL skipped: %s (threats: %s)", url, threat_types
                    )
                    unsafe_count += 1
                else:
                    safe_urls.append(url)
            if unsafe_count > 0:
                logger.info(
                    "Safe Browsing: %d URLs skipped as unsafe out of %d",
                    unsafe_count,
                    len(urls),
                )

        if not safe_urls:
            logger.warning("No safe URLs to crawl after Safe Browsing check")
            return {"pages_crawled": 0, "chunks_stored": 0, "errors": 0, "unsafe_urls": unsafe_count}

        # 複数ページを並行クロール（進捗報告付き）
        # WebCrawler.crawl_page() は内部でセマフォ制御と遅延を行う
        total_urls = len(safe_urls)
        tasks = [
            asyncio.create_task(self._web_crawler.crawl_page(url))
            for url in safe_urls
        ]

        pages: list[CrawledPage] = []
        completed_count = 0
        for coro in asyncio.as_completed(tasks):
            page = await coro
            completed_count += 1
            if page is not None:
                pages.append(page)

            # 進捗コールバック呼び出し（エラーを隔離）
            if progress_callback:
                try:
                    await progress_callback(completed_count, total_urls)
                except Exception:
                    logger.debug("Progress callback failed", exc_info=True)

        # 各ページをチャンキングして保存
        total_chunks = 0
        # errorsはクロール失敗数（safe_urlsの数からpagesの数を引く）
        errors = len(safe_urls) - len(pages)

        for page in pages:
            try:
                chunks_stored = await self._ingest_crawled_page(page)
                total_chunks += chunks_stored
            except Exception:
                logger.exception("Failed to ingest page: %s", page.url)
                errors += 1

        logger.info(
            "Ingested from index: pages=%d, chunks=%d, errors=%d, unsafe=%d",
            len(pages),
            total_chunks,
            errors,
            unsafe_count,
        )

        return {
            "pages_crawled": len(pages),
            "chunks_stored": total_chunks,
            "errors": errors,
            "unsafe_urls": unsafe_count,
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
            ValueError: URL検証に失敗した場合、またはURLが危険と判定された場合
        """
        # URL検証を先に行い、失敗時は例外を投げる（ユーザーにエラー理由を伝えるため）
        # 戻り値（正規化済みURL）を以降の処理で使用
        validated_url = self._web_crawler.validate_url(url)

        # Safe Browsing チェック（有効な場合のみ）
        if self._safe_browsing_client:
            result = await self._safe_browsing_client.check_url(validated_url)
            if not result.is_safe:
                threat_types = [t.threat_type.value for t in result.threats]
                logger.warning(
                    "Unsafe URL rejected: %s (threats: %s)", validated_url, threat_types
                )
                raise ValueError(
                    f"URLが安全ではありません: {validated_url} "
                    f"(検出された脅威: {', '.join(threat_types)})"
                )

        page = await self._web_crawler.crawl_page(validated_url)
        if page is None:
            logger.warning("Failed to crawl page: %s", validated_url)
            return 0

        return await self._ingest_crawled_page(page)

    def _smart_chunk(self, text: str) -> list[str]:
        """コンテンツタイプに応じた適切なチャンキング手法を選択する.

        仕様: docs/specs/f9-rag.md

        - TABLE: テーブルデータとして行単位でチャンキング
        - HEADING/MIXED: 見出し単位でチャンキング
        - PROSE: 従来の段落ベースチャンキング

        Args:
            text: チャンキング対象のテキスト

        Returns:
            チャンクのリスト
        """
        if not text or not text.strip():
            return []

        content_type = detect_content_type(text)
        logger.debug("Detected content type: %s", content_type.value)

        if content_type == ContentType.TABLE:
            # テーブルデータ: 行単位でチャンキング
            table_chunks = chunk_table_data(text)
            if table_chunks:
                return [chunk.formatted_text for chunk in table_chunks]
            # テーブルチャンキングに失敗した場合はフォールバック
            logger.debug("Table chunking returned no results, falling back to prose")

        if content_type in (ContentType.HEADING, ContentType.MIXED):
            # 見出しあり: 見出し単位でチャンキング
            heading_chunks = chunk_by_headings(
                text,
                max_chunk_size=self._chunk_size,
            )
            if heading_chunks:
                return [chunk.formatted_text for chunk in heading_chunks]
            # 見出しチャンキングに失敗した場合はフォールバック
            logger.debug("Heading chunking returned no results, falling back to prose")

        # 通常テキスト: 従来のチャンキング
        return chunk_text(
            text,
            chunk_size=self._chunk_size,
            chunk_overlap=self._chunk_overlap,
        )

    async def _ingest_crawled_page(self, page: CrawledPage) -> int:
        """クロール済みページをチャンキングして保存する.

        Args:
            page: クロール済みページ

        Returns:
            保存されたチャンク数
        """
        # テキストをスマートチャンキング（コンテンツタイプに応じた手法を選択）
        chunks = self._smart_chunk(page.text)

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

        # BM25インデックスにも追加（ハイブリッド検索用）
        # 注: BM25は補助的機能のため、失敗してもVectorStoreの結果は維持する
        if self._bm25_index is not None:
            bm25_docs = [
                (chunk.id, chunk.text, normalized_url)
                for chunk in document_chunks
            ]
            try:
                self._bm25_index.add_documents(bm25_docs)
                logger.debug("Added %d documents to BM25 index", len(bm25_docs))
            except Exception:
                logger.warning(
                    "Failed to add documents to BM25 index for %s", normalized_url,
                    exc_info=True,
                )

        logger.info("Ingested page %s: %d chunks", normalized_url, count)
        return count

    async def retrieve(self, query: str, n_results: int = 5) -> RAGRetrievalResult:
        """関連知識を検索し、結果を返す.

        ChatService から呼ばれる。結果なしの場合は空のRAGRetrievalResult。

        仕様: docs/specs/f9-rag.md

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数

        Returns:
            RAGRetrievalResult: コンテキストとソース情報
        """
        from src.config.settings import get_settings

        settings = get_settings()

        # ハイブリッド検索が有効な場合
        if self._hybrid_search_enabled and self._hybrid_search_engine is not None:
            return await self._retrieve_hybrid(query, n_results, settings)

        # 従来のベクトル検索のみ
        return await self._retrieve_vector_only(query, n_results, settings)

    async def _retrieve_vector_only(
        self,
        query: str,
        n_results: int,
        settings: "Settings",
    ) -> RAGRetrievalResult:
        """ベクトル検索のみで検索を実行する（従来の動作）.

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数
            settings: 設定オブジェクト

        Returns:
            RAGRetrievalResult: コンテキストとソース情報
        """
        results = await self._vector_store.search(
            query,
            n_results=n_results,
            similarity_threshold=settings.rag_similarity_threshold,
        )

        if not results:
            return RAGRetrievalResult(context="", sources=[])

        # デバッグログ出力
        if settings.rag_debug_log_enabled:
            logger.info("RAG retrieve (vector only): query=%r", query)
            for i, result in enumerate(results, start=1):
                source_url = result.metadata.get("source_url", "不明")
                logger.info(
                    "RAG result %d: distance=%.3f source=%r",
                    i,
                    result.distance,
                    source_url,
                )
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

    async def _retrieve_hybrid(
        self,
        query: str,
        n_results: int,
        settings: "Settings",
    ) -> RAGRetrievalResult:
        """ハイブリッド検索（ベクトル＋BM25）で検索を実行する.

        仕様: docs/specs/f9-rag.md

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数
            settings: 設定オブジェクト

        Returns:
            RAGRetrievalResult: コンテキストとソース情報
        """
        assert self._hybrid_search_engine is not None

        results = await self._hybrid_search_engine.search(
            query,
            n_results=n_results,
            similarity_threshold=settings.rag_similarity_threshold,
        )

        if not results:
            return RAGRetrievalResult(context="", sources=[])

        # デバッグログ出力
        if settings.rag_debug_log_enabled:
            logger.info("RAG retrieve (hybrid): query=%r", query)
            for i, result in enumerate(results, start=1):
                source_url = result.metadata.get("source_url", "不明")
                logger.info(
                    "RAG result %d: rrf_score=%.4f vector_dist=%s bm25_score=%s source=%r",
                    i,
                    result.rrf_score,
                    f"{result.vector_distance:.3f}" if result.vector_distance is not None else "N/A",
                    f"{result.bm25_score:.3f}" if result.bm25_score is not None else "N/A",
                    source_url,
                )
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

        # 正規化後のURLに紐づくチャンクを削除（ベクトルストア）
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

        # BM25インデックスからも削除（ハイブリッド検索用）
        # 注: BM25は補助的機能のため、失敗してもVectorStoreの結果は維持する
        if self._bm25_index is not None:
            try:
                bm25_deleted = self._bm25_index.delete_by_source(normalized_url)
                if fragment:
                    bm25_deleted += self._bm25_index.delete_by_source(source_url)
                logger.debug("Deleted %d documents from BM25 index", bm25_deleted)
            except Exception:
                logger.warning(
                    "Failed to delete from BM25 index for %s", normalized_url,
                    exc_info=True,
                )

        return total_deleted

    async def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計.

        Returns:
            統計情報の辞書
        """
        # VectorStore.get_stats()は同期APIを呼ぶため、to_threadでラップ
        return await asyncio.to_thread(self._vector_store.get_stats)
