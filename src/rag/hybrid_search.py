"""ハイブリッド検索モジュール

仕様: docs/specs/f9-rag.md
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.bm25_index import BM25Index, BM25Result
    from src.rag.vector_store import RetrievalResult, VectorStore

logger = logging.getLogger(__name__)


def _generate_doc_id(source_url: str, chunk_index: int) -> str:
    """ドキュメントIDを生成する.

    VectorStoreと同じ形式（url_hash + "_" + chunk_index）で生成する。
    """
    url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
    return f"{url_hash}_{chunk_index}"


@dataclass
class HybridSearchResult:
    """ハイブリッド検索結果.

    ベクトル検索とBM25検索の結果を統合したもの。
    """

    doc_id: str
    text: str
    metadata: dict[str, str | int]
    vector_distance: float | None  # ベクトル検索での距離（Noneの場合はBM25のみでヒット）
    bm25_score: float | None  # BM25スコア（Noneの場合はベクトル検索のみでヒット）
    rrf_score: float  # RRFで統合されたスコア


class HybridSearchEngine:
    """ベクトル検索とBM25を組み合わせたハイブリッド検索.

    仕様: docs/specs/f9-rag.md
    """

    def __init__(
        self,
        vector_store: VectorStore,
        bm25_index: BM25Index,
        vector_weight: float = 0.5,
        rrf_k: int = 60,
    ) -> None:
        """HybridSearchEngineを初期化する.

        Args:
            vector_store: ベクトルストア
            bm25_index: BM25インデックス
            vector_weight: ベクトル検索の重み（0.0〜1.0）
            rrf_k: RRFの定数（デフォルト: 60、論文推奨値）
        """
        self._vector_store = vector_store
        self._bm25_index = bm25_index
        self._vector_weight = max(0.0, min(1.0, vector_weight))
        self._rrf_k = rrf_k

    async def search(
        self,
        query: str,
        n_results: int = 5,
        similarity_threshold: float | None = None,
    ) -> list[HybridSearchResult]:
        """ハイブリッド検索を実行する.

        仕様: docs/specs/f9-rag.md

        1. ベクトル検索で候補を取得
        2. BM25検索で候補を取得
        3. RRF（Reciprocal Rank Fusion）でスコアを統合
        4. 統合スコアでソート

        Args:
            query: 検索クエリ
            n_results: 返却する結果の最大数
            similarity_threshold: ベクトル検索の類似度閾値

        Returns:
            HybridSearchResultのリスト（RRFスコア降順）
        """
        # 多めに取得してからRRFで統合
        fetch_count = max(n_results * 3, 20)

        # ベクトル検索
        # 閾値フィルタリングは最終段階で行うため、ここでは適用しない
        vector_results = await self._vector_store.search(
            query,
            n_results=fetch_count,
            similarity_threshold=None,
        )

        # BM25検索
        bm25_results = self._bm25_index.search(query, n_results=fetch_count)

        # 検索結果が両方とも空の場合
        if not vector_results and not bm25_results:
            return []

        # ベクトル検索のみの場合
        if not bm25_results:
            return self._convert_vector_only_results(
                vector_results, n_results, similarity_threshold
            )

        # BM25のみの場合
        if not vector_results:
            return self._convert_bm25_only_results(bm25_results, n_results)

        # 両方の結果がある場合はRRFで統合
        return self._merge_with_rrf(
            vector_results, bm25_results, n_results, similarity_threshold
        )

    def _convert_vector_only_results(
        self,
        vector_results: list[RetrievalResult],
        n_results: int,
        similarity_threshold: float | None,
    ) -> list[HybridSearchResult]:
        """ベクトル検索結果のみを変換する."""
        results: list[HybridSearchResult] = []
        rank = 0  # 閾値を満たすもののみでランク計算

        for i, vr in enumerate(vector_results):
            # 閾値フィルタリング（先にフィルタしてからn_results件を取得）
            if similarity_threshold is not None and vr.distance > similarity_threshold:
                continue

            # 必要件数に達したら終了
            if len(results) >= n_results:
                break

            # RRFスコアを計算（閾値を満たすもののランクで計算）
            rrf_score = self._vector_weight / (self._rrf_k + rank + 1)
            rank += 1

            # VectorStoreと同じ形式でdoc_idを生成
            source_url = str(vr.metadata.get("source_url", ""))
            chunk_index = int(vr.metadata.get("chunk_index", i))
            doc_id = _generate_doc_id(source_url, chunk_index)

            results.append(
                HybridSearchResult(
                    doc_id=doc_id,
                    text=vr.text,
                    metadata=vr.metadata,
                    vector_distance=vr.distance,
                    bm25_score=None,
                    rrf_score=rrf_score,
                )
            )

        return results

    def _convert_bm25_only_results(
        self,
        bm25_results: list["BM25Result"],
        n_results: int,
    ) -> list[HybridSearchResult]:
        """BM25検索結果のみを変換する."""
        results: list[HybridSearchResult] = []
        bm25_weight = 1.0 - self._vector_weight

        for i, br in enumerate(bm25_results[:n_results]):
            # RRFスコアを計算（BM25のランクのみ）
            rrf_score = bm25_weight / (self._rrf_k + i + 1)

            # BM25Indexからsource_urlを取得
            source_url = self._bm25_index.get_source_url(br.doc_id)
            metadata: dict[str, str | int] = {}
            if source_url:
                metadata["source_url"] = source_url

            results.append(
                HybridSearchResult(
                    doc_id=br.doc_id,
                    text=br.text,
                    metadata=metadata,
                    vector_distance=None,
                    bm25_score=br.score,
                    rrf_score=rrf_score,
                )
            )

        return results

    def _merge_with_rrf(
        self,
        vector_results: list["RetrievalResult"],
        bm25_results: list["BM25Result"],
        n_results: int,
        similarity_threshold: float | None,
    ) -> list[HybridSearchResult]:
        """RRFで検索結果を統合する."""
        bm25_weight = 1.0 - self._vector_weight

        # ドキュメントIDでマッピング
        doc_map: dict[str, dict[str, float | None | dict[str, str | int] | str]] = {}

        # ベクトル検索結果を処理
        # 閾値を満たした結果だけでランクを進める（_convert_vector_only_resultsと一貫性を保つ）
        vector_rank = 0
        for i, vr in enumerate(vector_results):
            # VectorStoreと同じ形式でdoc_idを生成
            source_url = str(vr.metadata.get("source_url", ""))
            chunk_index = int(vr.metadata.get("chunk_index", i))
            doc_id = _generate_doc_id(source_url, chunk_index)

            # 閾値チェック（フィルタリングではなく、スコア計算に影響）
            if similarity_threshold is not None and vr.distance > similarity_threshold:
                # 閾値を超えている場合はベクトル検索のRRFスコアを0に
                vector_rank_bonus = 0.0
            else:
                # 閾値を満たした結果のみでランクを計算
                vector_rank_bonus = self._vector_weight / (self._rrf_k + vector_rank + 1)
                vector_rank += 1

            doc_map[doc_id] = {
                "text": vr.text,
                "metadata": vr.metadata,
                "vector_distance": vr.distance,
                "bm25_score": None,
                "vector_rrf": vector_rank_bonus,
                "bm25_rrf": 0.0,
            }

        # BM25結果を処理
        for i, br in enumerate(bm25_results):
            bm25_rank_bonus = bm25_weight / (self._rrf_k + i + 1)

            if br.doc_id in doc_map:
                # 既存のエントリを更新
                doc_map[br.doc_id]["bm25_score"] = br.score
                doc_map[br.doc_id]["bm25_rrf"] = bm25_rank_bonus
            else:
                # 新規エントリを追加（BM25のみヒット）
                # BM25Indexからsource_urlを取得
                bm25_source_url: str | None = self._bm25_index.get_source_url(br.doc_id)
                bm25_metadata: dict[str, str | int] = {}
                if bm25_source_url:
                    bm25_metadata["source_url"] = bm25_source_url

                doc_map[br.doc_id] = {
                    "text": br.text,
                    "metadata": bm25_metadata,
                    "vector_distance": None,
                    "bm25_score": br.score,
                    "vector_rrf": 0.0,
                    "bm25_rrf": bm25_rank_bonus,
                }

        # RRFスコアを計算してソート
        results: list[HybridSearchResult] = []
        for doc_id, data in doc_map.items():
            # 型安全なキャスト（dictが含まれる可能性があるためisinstanceでガード）
            raw_vector_rrf = data.get("vector_rrf", 0.0)
            raw_bm25_rrf = data.get("bm25_rrf", 0.0)
            vector_rrf = (
                float(raw_vector_rrf)
                if isinstance(raw_vector_rrf, (int, float))
                else 0.0
            )
            bm25_rrf = (
                float(raw_bm25_rrf)
                if isinstance(raw_bm25_rrf, (int, float))
                else 0.0
            )
            rrf_score = vector_rrf + bm25_rrf

            # 閾値超過かつBM25ヒットなしのドキュメントを除外
            # vector_rrf == 0 は閾値超過を意味し、bm25_rrf == 0 はBM25ヒットなし
            # 両方0の場合（両方でヒットしなかった）は結果に含めない
            if vector_rrf == 0.0 and bm25_rrf == 0.0:
                continue

            # 型安全なキャスト
            raw_vector_distance = data.get("vector_distance")
            raw_bm25_score = data.get("bm25_score")
            vector_distance: float | None = (
                float(raw_vector_distance)
                if isinstance(raw_vector_distance, (int, float))
                else None
            )
            bm25_score: float | None = (
                float(raw_bm25_score)
                if isinstance(raw_bm25_score, (int, float))
                else None
            )

            results.append(
                HybridSearchResult(
                    doc_id=doc_id,
                    text=str(data["text"]),
                    metadata=data["metadata"] if isinstance(data["metadata"], dict) else {},
                    vector_distance=vector_distance,
                    bm25_score=bm25_score,
                    rrf_score=rrf_score,
                )
            )

        # RRFスコアでソート
        results.sort(key=lambda x: x.rrf_score, reverse=True)

        return results[:n_results]


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
) -> dict[str, float]:
    """RRFでスコアを統合する.

    RRF_score(d) = Σ 1 / (k + rank(d))

    Args:
        rankings: 各検索手法のランキング結果（ドキュメントIDのリスト）
        k: 定数（デフォルト: 60、論文推奨値）

    Returns:
        ドキュメントID → 統合スコアのマッピング
    """
    scores: dict[str, float] = {}

    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            if doc_id not in scores:
                scores[doc_id] = 0.0
            scores[doc_id] += 1.0 / (k + rank)

    return scores
