"""ハイブリッド検索のテスト

仕様: docs/specs/f9-rag.md
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.rag.bm25_index import BM25Result
from src.rag.hybrid_search import (
    HybridSearchEngine,
    HybridSearchResult,
    reciprocal_rank_fusion,
)
from src.rag.vector_store import RetrievalResult


class TestReciprocalRankFusion:
    """reciprocal_rank_fusion関数のテスト."""

    def test_ac8_single_ranking(self) -> None:
        """単一のランキングでRRFスコアが計算される."""
        rankings = [["doc1", "doc2", "doc3"]]
        scores = reciprocal_rank_fusion(rankings, k=60)

        # 順位が高いほどスコアが高い
        assert scores["doc1"] > scores["doc2"]
        assert scores["doc2"] > scores["doc3"]

    def test_ac8_multiple_rankings_merged(self) -> None:
        """複数のランキングがマージされる."""
        rankings = [
            ["doc1", "doc2", "doc3"],  # ランキング1
            ["doc2", "doc1", "doc3"],  # ランキング2
        ]
        scores = reciprocal_rank_fusion(rankings, k=60)

        # doc1とdoc2は両方で上位なので高スコア
        assert scores["doc1"] > scores["doc3"]
        assert scores["doc2"] > scores["doc3"]

    def test_ac8_document_in_one_ranking_only(self) -> None:
        """片方のランキングにのみ存在するドキュメント."""
        rankings = [
            ["doc1", "doc2"],
            ["doc3", "doc4"],
        ]
        scores = reciprocal_rank_fusion(rankings, k=60)

        # すべてのドキュメントがスコアを持つ
        assert "doc1" in scores
        assert "doc3" in scores

    def test_ac8_rrf_k_parameter_affects_scores(self) -> None:
        """AC8: kパラメータがスコアに影響する."""
        rankings = [["doc1", "doc2"]]

        scores_k60 = reciprocal_rank_fusion(rankings, k=60)
        scores_k10 = reciprocal_rank_fusion(rankings, k=10)

        # kが小さいほどスコアの差が大きくなる
        diff_k60 = scores_k60["doc1"] - scores_k60["doc2"]
        diff_k10 = scores_k10["doc1"] - scores_k10["doc2"]
        assert diff_k10 > diff_k60


class TestHybridSearchResult:
    """HybridSearchResultクラスのテスト."""

    def test_ac14_result_with_both_scores(self) -> None:
        """AC14: 両方のスコアを持つ結果."""
        result = HybridSearchResult(
            doc_id="doc1",
            text="テスト",
            metadata={"source_url": "http://example.com"},
            vector_distance=0.3,
            bm25_score=5.0,
            rrf_score=0.1,
        )

        assert result.vector_distance == 0.3
        assert result.bm25_score == 5.0
        assert result.rrf_score == 0.1

    def test_ac14_result_with_vector_only(self) -> None:
        """AC14: ベクトル検索のみの結果."""
        result = HybridSearchResult(
            doc_id="doc1",
            text="テスト",
            metadata={},
            vector_distance=0.3,
            bm25_score=None,
            rrf_score=0.05,
        )

        assert result.vector_distance == 0.3
        assert result.bm25_score is None

    def test_ac14_result_with_bm25_only(self) -> None:
        """AC14: BM25検索のみの結果."""
        result = HybridSearchResult(
            doc_id="doc1",
            text="テスト",
            metadata={},
            vector_distance=None,
            bm25_score=5.0,
            rrf_score=0.05,
        )

        assert result.vector_distance is None
        assert result.bm25_score == 5.0


class TestHybridSearchEngine:
    """HybridSearchEngineクラスのテスト（モックを使用）."""

    @pytest.fixture
    def mock_vector_store(self) -> MagicMock:
        """VectorStoreのモック."""
        store = MagicMock()
        store.search = AsyncMock(return_value=[])
        return store

    @pytest.fixture
    def mock_bm25_index(self) -> MagicMock:
        """BM25Indexのモック."""
        index = MagicMock()
        index.search = MagicMock(return_value=[])
        return index

    @pytest.fixture
    def engine(
        self, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> HybridSearchEngine:
        """HybridSearchEngineインスタンス."""
        return HybridSearchEngine(
            vector_store=mock_vector_store,
            bm25_index=mock_bm25_index,
            vector_weight=0.5,
            rrf_k=60,
        )

    @pytest.mark.asyncio
    async def test_ac8_search_merges_vector_and_bm25_results(
        self, engine: HybridSearchEngine, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """ベクトル検索とBM25検索の結果がRRFでマージされる."""
        # VectorStoreの結果を設定
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="ドキュメント1の内容",
                metadata={"source_url": "http://example.com/1", "chunk_index": 0},
                distance=0.2,
            ),
            RetrievalResult(
                text="ドキュメント2の内容",
                metadata={"source_url": "http://example.com/2", "chunk_index": 0},
                distance=0.3,
            ),
        ]

        # BM25Indexの結果を設定（doc_idはVectorStoreと同じ形式で生成）
        import hashlib

        url1_hash = hashlib.sha256(b"http://example.com/1").hexdigest()[:16]
        url2_hash = hashlib.sha256(b"http://example.com/2").hexdigest()[:16]
        mock_bm25_index.search.return_value = [
            BM25Result(doc_id=f"{url2_hash}_0", score=5.0, text="ドキュメント2の内容"),
            BM25Result(doc_id=f"{url1_hash}_0", score=3.0, text="ドキュメント1の内容"),
        ]

        results = await engine.search("テストクエリ", n_results=5)

        # 両方の検索が呼ばれたことを確認
        mock_vector_store.search.assert_called_once()
        mock_bm25_index.search.assert_called_once()

        # 結果が返されることを確認
        assert len(results) == 2

        # RRFスコアが計算されていることを確認
        for result in results:
            assert result.rrf_score > 0

    @pytest.mark.asyncio
    async def test_ac8_search_returns_empty_when_no_results(
        self, engine: HybridSearchEngine, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """AC8: 両方の検索結果が空の場合、空リストを返す."""
        mock_vector_store.search.return_value = []
        mock_bm25_index.search.return_value = []

        results = await engine.search("存在しないクエリ", n_results=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_ac14_search_with_vector_only_results(
        self, engine: HybridSearchEngine, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """AC14: ベクトル検索のみ結果がある場合."""
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="ベクトル検索でのみヒット",
                metadata={"source_url": "http://example.com/vec", "chunk_index": 0},
                distance=0.25,
            ),
        ]
        mock_bm25_index.search.return_value = []

        results = await engine.search("ベクトルクエリ", n_results=5)

        assert len(results) == 1
        assert results[0].vector_distance == 0.25
        assert results[0].bm25_score is None

    @pytest.mark.asyncio
    async def test_ac14_search_with_bm25_only_results(
        self, engine: HybridSearchEngine, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """AC14: BM25検索のみ結果がある場合."""
        mock_vector_store.search.return_value = []
        mock_bm25_index.search.return_value = [
            BM25Result(doc_id="bm25_doc_1", score=8.5, text="BM25でのみヒット"),
        ]

        results = await engine.search("キーワードクエリ", n_results=5)

        assert len(results) == 1
        assert results[0].vector_distance is None
        assert results[0].bm25_score == 8.5

    @pytest.mark.asyncio
    async def test_ac10_vector_weight_affects_rrf_scores(
        self, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """vector_weightパラメータがRRFスコアに影響する."""
        # VectorStoreの結果
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text="テスト",
                metadata={"source_url": "http://example.com/test", "chunk_index": 0},
                distance=0.2,
            ),
        ]
        mock_bm25_index.search.return_value = []

        # vector_weight=0.8 の場合
        engine_high = HybridSearchEngine(
            vector_store=mock_vector_store,
            bm25_index=mock_bm25_index,
            vector_weight=0.8,
            rrf_k=60,
        )
        results_high = await engine_high.search("テスト", n_results=5)

        # vector_weight=0.2 の場合
        engine_low = HybridSearchEngine(
            vector_store=mock_vector_store,
            bm25_index=mock_bm25_index,
            vector_weight=0.2,
            rrf_k=60,
        )
        results_low = await engine_low.search("テスト", n_results=5)

        # 高い重みの方がRRFスコアが高い
        assert results_high[0].rrf_score > results_low[0].rrf_score

    @pytest.mark.asyncio
    async def test_ac8_search_respects_n_results_limit(
        self, engine: HybridSearchEngine, mock_vector_store: MagicMock, mock_bm25_index: MagicMock
    ) -> None:
        """AC8: n_resultsパラメータで結果数が制限される."""
        # 多くの結果を返すように設定
        mock_vector_store.search.return_value = [
            RetrievalResult(
                text=f"ドキュメント{i}",
                metadata={"source_url": f"http://example.com/{i}", "chunk_index": 0},
                distance=0.1 + i * 0.05,
            )
            for i in range(10)
        ]
        mock_bm25_index.search.return_value = []

        results = await engine.search("テスト", n_results=3)

        assert len(results) == 3
