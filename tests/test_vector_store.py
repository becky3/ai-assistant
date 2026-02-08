"""ベクトルストアのテスト (Issue #116).

仕様: docs/specs/f9-rag-knowledge.md — AC8〜AC11
"""

from __future__ import annotations

import uuid

import pytest

from src.embedding.base import EmbeddingProvider
from src.rag.vector_store import DocumentChunk, RetrievalResult, VectorStore


class MockEmbeddingProvider(EmbeddingProvider):
    """テスト用のモックEmbeddingプロバイダー."""

    def __init__(self, dimension: int = 3) -> None:
        self._dimension = dimension
        self._call_count = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """テキストを固定次元のベクトルに変換する."""
        self._call_count += 1
        # 各テキストを単純なベクトルに変換（テスト用）
        return [[float(i + len(text)) for i in range(self._dimension)] for text in texts]

    async def is_available(self) -> bool:
        """常にTrueを返す."""
        return True


@pytest.fixture
def mock_embedding() -> MockEmbeddingProvider:
    """モックEmbeddingプロバイダーを返すフィクスチャ."""
    return MockEmbeddingProvider(dimension=3)


@pytest.fixture
def ephemeral_store(mock_embedding: MockEmbeddingProvider) -> VectorStore:
    """インメモリのVectorStoreを返すフィクスチャ.

    各テストで独立したコレクションを使用するためにUUIDをコレクション名に含める。
    """
    unique_collection = f"test_collection_{uuid.uuid4().hex[:8]}"
    return VectorStore.create_ephemeral(mock_embedding, collection_name=unique_collection)


class TestAC8AddDocuments:
    """AC8: VectorStore.add_documents() でチャンクをEmbedding→ChromaDBに保存できること."""

    @pytest.mark.asyncio
    async def test_add_single_document(self, ephemeral_store: VectorStore) -> None:
        """単一のドキュメントを追加できる."""
        chunk = DocumentChunk(
            id="doc1_0",
            text="これはテストテキストです。",
            metadata={"source_url": "https://example.com/doc1", "chunk_index": 0},
        )
        count = await ephemeral_store.add_documents([chunk])
        assert count == 1

    @pytest.mark.asyncio
    async def test_add_multiple_documents(self, ephemeral_store: VectorStore) -> None:
        """複数のドキュメントを追加できる."""
        chunks = [
            DocumentChunk(
                id=f"doc_{i}",
                text=f"テキスト{i}",
                metadata={"source_url": "https://example.com", "chunk_index": i},
            )
            for i in range(5)
        ]
        count = await ephemeral_store.add_documents(chunks)
        assert count == 5

    @pytest.mark.asyncio
    async def test_add_empty_list(self, ephemeral_store: VectorStore) -> None:
        """空のリストを渡すと0を返す."""
        count = await ephemeral_store.add_documents([])
        assert count == 0

    @pytest.mark.asyncio
    async def test_embedding_is_called(
        self,
        mock_embedding: MockEmbeddingProvider,
        ephemeral_store: VectorStore,
    ) -> None:
        """Embeddingプロバイダーが呼び出される."""
        chunk = DocumentChunk(
            id="doc1_0",
            text="テスト",
            metadata={"source_url": "https://example.com", "chunk_index": 0},
        )
        await ephemeral_store.add_documents([chunk])
        assert mock_embedding._call_count == 1


class TestAC9SearchSimilarChunks:
    """AC9: VectorStore.search() でクエリに類似するチャンクを検索できること."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self, ephemeral_store: VectorStore) -> None:
        """検索結果が返される."""
        # ドキュメントを追加
        chunks = [
            DocumentChunk(
                id=f"doc_{i}",
                text=f"テキスト{i}",
                metadata={"source_url": "https://example.com", "chunk_index": i},
            )
            for i in range(3)
        ]
        await ephemeral_store.add_documents(chunks)

        # 検索
        results = await ephemeral_store.search("テキスト", n_results=2)
        assert len(results) == 2
        assert all(isinstance(r, RetrievalResult) for r in results)

    @pytest.mark.asyncio
    async def test_search_returns_text_and_metadata(
        self,
        ephemeral_store: VectorStore,
    ) -> None:
        """検索結果にテキストとメタデータが含まれる."""
        chunk = DocumentChunk(
            id="doc1_0",
            text="テストテキスト",
            metadata={"source_url": "https://example.com/test", "chunk_index": 0},
        )
        await ephemeral_store.add_documents([chunk])

        results = await ephemeral_store.search("テスト", n_results=1)
        assert len(results) == 1
        assert results[0].text == "テストテキスト"
        assert results[0].metadata["source_url"] == "https://example.com/test"

    @pytest.mark.asyncio
    async def test_search_returns_distance(self, ephemeral_store: VectorStore) -> None:
        """検索結果にdistanceが含まれる."""
        chunk = DocumentChunk(
            id="doc1_0",
            text="テスト",
            metadata={"source_url": "https://example.com", "chunk_index": 0},
        )
        await ephemeral_store.add_documents([chunk])

        results = await ephemeral_store.search("テスト", n_results=1)
        assert len(results) == 1
        assert isinstance(results[0].distance, float)

    @pytest.mark.asyncio
    async def test_search_empty_store(self, ephemeral_store: VectorStore) -> None:
        """空のストアを検索すると空のリストを返す."""
        results = await ephemeral_store.search("テスト", n_results=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_search_respects_n_results(self, ephemeral_store: VectorStore) -> None:
        """n_resultsで返却数を制限できる."""
        chunks = [
            DocumentChunk(
                id=f"doc_{i}",
                text=f"テキスト{i}",
                metadata={"source_url": "https://example.com", "chunk_index": i},
            )
            for i in range(10)
        ]
        await ephemeral_store.add_documents(chunks)

        results = await ephemeral_store.search("テキスト", n_results=3)
        assert len(results) == 3


class TestAC10DeleteBySource:
    """AC10: VectorStore.delete_by_source() でソースURL指定のチャンクを削除できること."""

    @pytest.mark.asyncio
    async def test_delete_by_source_url(self, ephemeral_store: VectorStore) -> None:
        """ソースURL指定で削除できる."""
        # 2つの異なるソースからドキュメントを追加
        chunks = [
            DocumentChunk(
                id="doc1_0",
                text="テキスト1",
                metadata={"source_url": "https://example.com/page1", "chunk_index": 0},
            ),
            DocumentChunk(
                id="doc1_1",
                text="テキスト2",
                metadata={"source_url": "https://example.com/page1", "chunk_index": 1},
            ),
            DocumentChunk(
                id="doc2_0",
                text="テキスト3",
                metadata={"source_url": "https://example.com/page2", "chunk_index": 0},
            ),
        ]
        await ephemeral_store.add_documents(chunks)

        # page1のドキュメントを削除
        deleted_count = await ephemeral_store.delete_by_source("https://example.com/page1")
        assert deleted_count == 2

        # page2のドキュメントは残っている
        stats = ephemeral_store.get_stats()
        assert stats["total_chunks"] == 1

    @pytest.mark.asyncio
    async def test_delete_nonexistent_source(self, ephemeral_store: VectorStore) -> None:
        """存在しないソースURLを指定すると0を返す."""
        chunk = DocumentChunk(
            id="doc1_0",
            text="テスト",
            metadata={"source_url": "https://example.com/page1", "chunk_index": 0},
        )
        await ephemeral_store.add_documents([chunk])

        deleted_count = await ephemeral_store.delete_by_source("https://example.com/nonexistent")
        assert deleted_count == 0


class TestAC11GetStats:
    """AC11: VectorStore.get_stats() でナレッジベースの統計情報を取得できること."""

    def test_get_stats_empty_store(self, ephemeral_store: VectorStore) -> None:
        """空のストアの統計."""
        stats = ephemeral_store.get_stats()
        assert stats["total_chunks"] == 0
        assert stats["source_count"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_with_documents(self, ephemeral_store: VectorStore) -> None:
        """ドキュメントがある場合の統計."""
        chunks = [
            DocumentChunk(
                id="doc1_0",
                text="テキスト1",
                metadata={"source_url": "https://example.com/page1", "chunk_index": 0},
            ),
            DocumentChunk(
                id="doc1_1",
                text="テキスト2",
                metadata={"source_url": "https://example.com/page1", "chunk_index": 1},
            ),
            DocumentChunk(
                id="doc2_0",
                text="テキスト3",
                metadata={"source_url": "https://example.com/page2", "chunk_index": 0},
            ),
        ]
        await ephemeral_store.add_documents(chunks)

        stats = ephemeral_store.get_stats()
        assert stats["total_chunks"] == 3
        assert stats["source_count"] == 2


class TestVectorStoreDataClasses:
    """データクラスのテスト."""

    def test_document_chunk_creation(self) -> None:
        """DocumentChunkが正しく作成できる."""
        chunk = DocumentChunk(
            id="test_id",
            text="テストテキスト",
            metadata={"source_url": "https://example.com", "chunk_index": 0},
        )
        assert chunk.id == "test_id"
        assert chunk.text == "テストテキスト"
        assert chunk.metadata["source_url"] == "https://example.com"

    def test_retrieval_result_creation(self) -> None:
        """RetrievalResultが正しく作成できる."""
        result = RetrievalResult(
            text="テストテキスト",
            metadata={"source_url": "https://example.com"},
            distance=0.5,
        )
        assert result.text == "テストテキスト"
        assert result.metadata["source_url"] == "https://example.com"
        assert result.distance == 0.5


class TestVectorStoreFactory:
    """VectorStoreのファクトリメソッドのテスト."""

    def test_create_ephemeral(self, mock_embedding: MockEmbeddingProvider) -> None:
        """create_ephemeral()でインメモリストアを作成できる."""
        store = VectorStore.create_ephemeral(mock_embedding, collection_name="test")
        assert store._persist_directory == ""
        assert store._collection_name == "test"

    def test_create_ephemeral_default_collection(
        self,
        mock_embedding: MockEmbeddingProvider,
    ) -> None:
        """create_ephemeral()のデフォルトコレクション名."""
        store = VectorStore.create_ephemeral(mock_embedding)
        assert store._collection_name == "knowledge"
