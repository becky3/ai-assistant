"""ChromaDBベクトルストアモジュール

仕様: docs/specs/f9-rag-knowledge.md
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import cast

import chromadb
from chromadb.api.types import Embeddings, IncludeEnum

from src.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """ベクトルストアに格納するチャンク."""

    id: str  # ユニークID（URLハッシュ + chunk_index）
    text: str  # チャンク本文
    metadata: dict[str, str | int]  # source_url, title, chunk_index, crawled_at


@dataclass
class RetrievalResult:
    """検索結果."""

    text: str
    metadata: dict[str, str | int]
    distance: float  # 小さいほど類似度が高い


class VectorStore:
    """ChromaDBベースのベクトルストア.

    仕様: docs/specs/f9-rag-knowledge.md
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        persist_directory: str = "./chroma_db",
        collection_name: str = "knowledge",
    ) -> None:
        """VectorStoreを初期化する.

        Args:
            embedding_provider: Embedding生成プロバイダー
            persist_directory: ChromaDBの永続化ディレクトリ
            collection_name: コレクション名
        """
        self._embedding = embedding_provider
        self._persist_directory = persist_directory
        self._collection_name = collection_name
        self._client = chromadb.PersistentClient(path=persist_directory)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @classmethod
    def create_ephemeral(
        cls,
        embedding_provider: EmbeddingProvider,
        collection_name: str = "knowledge",
    ) -> "VectorStore":
        """テスト用のインメモリVectorStoreを作成する.

        Args:
            embedding_provider: Embedding生成プロバイダー
            collection_name: コレクション名

        Returns:
            インメモリのVectorStoreインスタンス
        """
        instance = cls.__new__(cls)
        instance._embedding = embedding_provider
        instance._persist_directory = ""
        instance._collection_name = collection_name
        instance._client = chromadb.EphemeralClient()
        instance._collection = instance._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return instance

    async def add_documents(self, chunks: list[DocumentChunk]) -> int:
        """チャンクをEmbedding→ベクトルストアに追加.

        Args:
            chunks: 追加するチャンクのリスト

        Returns:
            追加件数
        """
        if not chunks:
            return 0

        # テキストをEmbeddingに変換
        texts = [chunk.text for chunk in chunks]
        raw_embeddings = await self._embedding.embed(texts)
        embeddings: Embeddings = cast(Embeddings, raw_embeddings)

        # ChromaDBに追加（同期APIなのでto_threadでラップ）
        ids = [chunk.id for chunk in chunks]
        metadatas = [chunk.metadata for chunk in chunks]

        await asyncio.to_thread(
            self._collection.add,
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,  # type: ignore[arg-type]
        )

        logger.info("Added %d documents to vector store", len(chunks))
        return len(chunks)

    async def search(
        self,
        query: str,
        n_results: int = 5,
    ) -> list[RetrievalResult]:
        """クエリに類似するチャンクを検索する.

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数

        Returns:
            検索結果のリスト（類似度の高い順）
        """
        # クエリをEmbeddingに変換
        raw_query_embedding = await self._embedding.embed([query])
        query_embeddings: Embeddings = cast(Embeddings, raw_query_embedding)

        # ChromaDBで検索（同期APIなのでto_threadでラップ）
        results = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=query_embeddings,
            n_results=n_results,
            include=[IncludeEnum.documents, IncludeEnum.metadatas, IncludeEnum.distances],
        )

        # 結果を変換
        retrieval_results: list[RetrievalResult] = []
        if results["documents"] and results["documents"][0]:
            documents = results["documents"][0]
            metadatas = results["metadatas"][0] if results["metadatas"] else [{}] * len(documents)
            distances = results["distances"][0] if results["distances"] else [0.0] * len(documents)

            for doc, meta, dist in zip(documents, metadatas, distances):
                retrieval_results.append(
                    RetrievalResult(
                        text=doc,
                        metadata=meta or {},  # type: ignore[arg-type]
                        distance=dist,
                    )
                )

        return retrieval_results

    async def delete_by_source(self, source_url: str) -> int:
        """ソースURL指定でチャンクを削除.

        Args:
            source_url: 削除するソースURL

        Returns:
            削除件数
        """
        # まず該当するドキュメントを検索
        results = await asyncio.to_thread(
            self._collection.get,
            where={"source_url": source_url},
            include=[IncludeEnum.metadatas],
        )

        if not results["ids"]:
            return 0

        ids_to_delete = results["ids"]
        count = len(ids_to_delete)

        # 削除実行
        await asyncio.to_thread(
            self._collection.delete,
            ids=ids_to_delete,
        )

        logger.info("Deleted %d documents from vector store (source: %s)", count, source_url)
        return count

    def get_stats(self) -> dict[str, int]:
        """ナレッジベース統計（総チャンク数等）を返す.

        Returns:
            統計情報の辞書
        """
        count = self._collection.count()

        # ユニークなソースURL数を取得
        all_docs = self._collection.get(include=[IncludeEnum.metadatas])
        source_urls: set[str] = set()
        if all_docs["metadatas"]:
            for meta in all_docs["metadatas"]:
                if meta and "source_url" in meta:
                    source_urls.add(str(meta["source_url"]))

        return {
            "total_chunks": count,
            "source_count": len(source_urls),
        }
