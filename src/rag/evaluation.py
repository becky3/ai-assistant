"""RAG評価メトリクス計算モジュール

仕様: docs/specs/f9-rag.md (Phase 2評価機能)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.services.rag_knowledge import RAGKnowledgeService

logger = logging.getLogger(__name__)


@dataclass
class PrecisionRecallResult:
    """Precision/Recall計算結果."""

    precision: float
    recall: float
    f1: float
    true_positives: int
    false_positives: int
    false_negatives: int


def calculate_precision_recall(
    retrieved_sources: list[str],
    expected_sources: list[str],
) -> PrecisionRecallResult:
    """Precision/Recall を計算する.

    Args:
        retrieved_sources: RAG検索で取得されたソースURLリスト
        expected_sources: 期待されるソースURLリスト（正解データ）

    Returns:
        PrecisionRecallResult: 計算結果（precision, recall, f1, 各カウント）

    Note:
        - Precision = TP / (TP + FP) = 取得結果のうち正解の割合
        - Recall = TP / (TP + FN) = 正解のうち取得できた割合
        - F1 = 2 * (Precision * Recall) / (Precision + Recall)
        - 空リストの場合は適切にハンドリング（ゼロ除算回避）
    """
    retrieved_set = set(retrieved_sources)
    expected_set = set(expected_sources)

    # True Positives: 期待され、かつ取得された
    true_positives = len(retrieved_set & expected_set)
    # False Positives: 取得されたが、期待されていない
    false_positives = len(retrieved_set - expected_set)
    # False Negatives: 期待されたが、取得されなかった
    false_negatives = len(expected_set - retrieved_set)

    # Precision: 取得結果のうち正解の割合
    if len(retrieved_set) > 0:
        precision = true_positives / len(retrieved_set)
    else:
        # 何も取得されなかった場合
        # 期待するものがなければ完璧、あれば0
        precision = 1.0 if len(expected_set) == 0 else 0.0

    # Recall: 正解のうち取得できた割合
    if len(expected_set) > 0:
        recall = true_positives / len(expected_set)
    else:
        # 期待するものがない場合
        # 何も取得しなければ完璧、取得してしまったら0
        recall = 1.0 if len(retrieved_set) == 0 else 0.0

    # F1スコア: PrecisionとRecallの調和平均
    if precision + recall > 0:
        f1 = 2 * (precision * recall) / (precision + recall)
    else:
        f1 = 0.0

    return PrecisionRecallResult(
        precision=precision,
        recall=recall,
        f1=f1,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def check_negative_sources(
    retrieved_sources: list[str],
    negative_sources: list[str],
) -> list[str]:
    """取得結果に含まれてはいけないソースが含まれていないかチェックする.

    Args:
        retrieved_sources: RAG検索で取得されたソースURLリスト
        negative_sources: 含まれてはいけないソースURLリスト

    Returns:
        含まれていた禁止ソースのリスト（空なら問題なし）
    """
    retrieved_set = set(retrieved_sources)
    negative_set = set(negative_sources)
    return list(retrieved_set & negative_set)


@dataclass
class QueryEvaluationResult:
    """個別クエリの評価結果."""

    query_id: str
    query: str
    precision: float
    recall: float
    f1: float
    retrieved_sources: list[str]
    expected_sources: list[str]
    negative_violations: list[str]  # 検出された禁止ソース


@dataclass
class EvaluationReport:
    """RAG評価レポート."""

    queries_evaluated: int
    average_precision: float
    average_recall: float
    average_f1: float
    negative_source_violations: list[str]  # 違反があったクエリIDリスト
    query_results: list[QueryEvaluationResult] = field(default_factory=list)


@dataclass
class EvaluationDatasetQuery:
    """評価データセットのクエリ."""

    id: str
    query: str
    expected_sources: list[str]
    negative_sources: list[str] = field(default_factory=list)
    expected_keywords: list[str] = field(default_factory=list)
    description: str = ""
    notes: str = ""


def load_evaluation_dataset(dataset_path: str) -> list[EvaluationDatasetQuery]:
    """評価用データセットをJSONファイルから読み込む.

    Args:
        dataset_path: データセットファイルのパス

    Returns:
        クエリリスト

    Raises:
        FileNotFoundError: ファイルが見つからない場合
        json.JSONDecodeError: JSONパースに失敗した場合
    """
    with open(dataset_path, encoding="utf-8") as f:
        data = json.load(f)

    queries: list[EvaluationDatasetQuery] = []
    for q in data.get("queries", []):
        queries.append(
            EvaluationDatasetQuery(
                id=q.get("id", ""),
                query=q.get("query", ""),
                expected_sources=q.get("expected_sources", []),
                negative_sources=q.get("negative_sources", []),
                expected_keywords=q.get("expected_keywords", []),
                description=q.get("description", ""),
                notes=q.get("notes", ""),
            )
        )
    return queries


async def evaluate_retrieval(
    rag_service: RAGKnowledgeService,
    dataset_path: str,
    n_results: int = 5,
) -> EvaluationReport:
    """データセットを使ってRAG検索の精度を評価する.

    Args:
        rag_service: RAGKnowledgeServiceインスタンス
        dataset_path: 評価データセットファイルのパス
        n_results: 各クエリで取得する結果数

    Returns:
        EvaluationReport: 評価レポート
    """
    # データセット読み込み
    queries = load_evaluation_dataset(dataset_path)

    if not queries:
        logger.warning("No queries found in dataset: %s", dataset_path)
        return EvaluationReport(
            queries_evaluated=0,
            average_precision=0.0,
            average_recall=0.0,
            average_f1=0.0,
            negative_source_violations=[],
            query_results=[],
        )

    query_results: list[QueryEvaluationResult] = []
    total_precision = 0.0
    total_recall = 0.0
    total_f1 = 0.0
    negative_violations: list[str] = []

    for dataset_query in queries:
        # RAG検索実行
        try:
            result = await rag_service.retrieve(dataset_query.query, n_results=n_results)
            retrieved_sources = result.sources
        except Exception:
            logger.exception("Failed to evaluate query: %s", dataset_query.id)
            # エラー時は空の結果として処理を継続
            retrieved_sources = []

        # Precision/Recall計算
        pr_result = calculate_precision_recall(
            retrieved_sources=retrieved_sources,
            expected_sources=dataset_query.expected_sources,
        )

        # 禁止ソースチェック
        violations = check_negative_sources(
            retrieved_sources=retrieved_sources,
            negative_sources=dataset_query.negative_sources,
        )

        if violations:
            negative_violations.append(dataset_query.id)
            logger.warning(
                "Query %s has negative source violations: %s",
                dataset_query.id,
                violations,
            )

        # 結果を記録
        query_result = QueryEvaluationResult(
            query_id=dataset_query.id,
            query=dataset_query.query,
            precision=pr_result.precision,
            recall=pr_result.recall,
            f1=pr_result.f1,
            retrieved_sources=retrieved_sources,
            expected_sources=dataset_query.expected_sources,
            negative_violations=violations,
        )
        query_results.append(query_result)

        total_precision += pr_result.precision
        total_recall += pr_result.recall
        total_f1 += pr_result.f1

        logger.debug(
            "Query %s: precision=%.3f, recall=%.3f, f1=%.3f",
            dataset_query.id,
            pr_result.precision,
            pr_result.recall,
            pr_result.f1,
        )

    # 平均計算
    num_queries = len(queries)
    avg_precision = total_precision / num_queries
    avg_recall = total_recall / num_queries
    avg_f1 = total_f1 / num_queries

    logger.info(
        "Evaluation complete: %d queries, avg_precision=%.3f, avg_recall=%.3f, avg_f1=%.3f",
        num_queries,
        avg_precision,
        avg_recall,
        avg_f1,
    )

    return EvaluationReport(
        queries_evaluated=num_queries,
        average_precision=avg_precision,
        average_recall=avg_recall,
        average_f1=avg_f1,
        negative_source_violations=negative_violations,
        query_results=query_results,
    )
