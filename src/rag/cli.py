"""RAG評価CLIモジュール

仕様: docs/specs/f9-rag-auto-evaluation.md
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

from src.rag.evaluation import (
    EvaluationReport,
    evaluate_retrieval,
)

if TYPE_CHECKING:
    from src.services.rag_knowledge import RAGKnowledgeService


class RegressionInfo(TypedDict):
    """リグレッション検出結果の型定義."""

    detected: bool
    baseline_f1: float
    current_f1: float
    delta: float

logger = logging.getLogger(__name__)


def main() -> None:
    """CLIエントリポイント."""
    parser = argparse.ArgumentParser(description="RAG評価CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # evaluate サブコマンド
    eval_parser = subparsers.add_parser("evaluate", help="RAG検索精度を評価")
    eval_parser.add_argument(
        "--dataset",
        default="tests/fixtures/rag_evaluation_dataset.json",
        help="評価データセットのパス",
    )
    eval_parser.add_argument(
        "--output-dir",
        default="reports/rag-evaluation",
        help="レポート出力ディレクトリ",
    )
    eval_parser.add_argument(
        "--baseline-file",
        help="ベースラインJSONファイルのパス",
    )
    eval_parser.add_argument(
        "--n-results",
        type=int,
        default=5,
        help="各クエリで取得する結果数",
    )
    eval_parser.add_argument(
        "--threshold",
        type=float,
        help="類似度閾値",
    )
    eval_parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="リグレッション検出時に exit code 1 で終了",
    )
    eval_parser.add_argument(
        "--regression-threshold",
        type=float,
        default=0.1,
        help="リグレッション判定閾値（F1スコアの低下量）",
    )
    eval_parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="現在の結果をベースラインとして保存",
    )

    # init-test-db サブコマンド
    init_parser = subparsers.add_parser("init-test-db", help="テスト用ChromaDB初期化")
    init_parser.add_argument(
        "--persist-dir",
        default="./test_chroma_db",
        help="ChromaDB永続化ディレクトリ",
    )
    init_parser.add_argument(
        "--fixture",
        default="tests/fixtures/rag_test_documents.json",
        help="テストドキュメントフィクスチャ",
    )

    args = parser.parse_args()

    if args.command == "evaluate":
        asyncio.run(run_evaluation(args))
    elif args.command == "init-test-db":
        asyncio.run(init_test_db(args))


async def create_rag_service(
    threshold: float | None = None,
    persist_dir: str | None = None,
) -> "RAGKnowledgeService":
    """RAGKnowledgeServiceを生成する.

    Args:
        threshold: 類似度閾値（指定時は環境変数を上書き）
        persist_dir: ChromaDB永続化ディレクトリ（指定時は環境変数を上書き）

    Returns:
        RAGKnowledgeServiceインスタンス
    """
    import os

    from src.config.settings import get_settings
    from src.embedding.factory import get_embedding_provider
    from src.rag.vector_store import VectorStore
    from src.services.rag_knowledge import RAGKnowledgeService
    from src.services.web_crawler import WebCrawler

    # 閾値を環境変数で上書き（一時的）
    if threshold is not None:
        os.environ["RAG_SIMILARITY_THRESHOLD"] = str(threshold)

    settings = get_settings()
    embedding_provider = get_embedding_provider(settings, settings.embedding_provider)

    # persist_dirが指定されている場合はそれを使用
    chroma_persist_dir = persist_dir or settings.chromadb_persist_dir
    vector_store = VectorStore(
        embedding_provider=embedding_provider,
        persist_directory=chroma_persist_dir,
    )

    # WebCrawlerはダミー（評価時は使用しない）
    web_crawler = WebCrawler()

    return RAGKnowledgeService(
        vector_store=vector_store,
        web_crawler=web_crawler,
    )


async def run_evaluation(args: argparse.Namespace) -> None:
    """評価を実行しレポートを出力する."""
    logger.info("Starting RAG evaluation...")
    logger.info("Dataset: %s", args.dataset)
    logger.info("Output directory: %s", args.output_dir)

    # データセットファイルの存在確認
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        logger.error("Dataset file not found: %s", args.dataset)
        sys.exit(1)

    # RAGサービス初期化
    rag_service = await create_rag_service(threshold=args.threshold)

    # 評価実行
    report = await evaluate_retrieval(
        rag_service=rag_service,
        dataset_path=args.dataset,
        n_results=args.n_results,
    )

    logger.info(
        "Evaluation complete: %d queries, avg_f1=%.3f",
        report.queries_evaluated,
        report.average_f1,
    )

    # ベースライン比較
    regression_info: RegressionInfo | None = None
    if args.baseline_file and Path(args.baseline_file).exists():
        baseline = load_baseline(args.baseline_file)
        summary = baseline.get("summary", {})
        baseline_f1 = float(summary.get("average_f1", 0.0)) if isinstance(summary, dict) else 0.0
        regression_info = detect_regression(
            baseline_f1=baseline_f1,
            current_f1=report.average_f1,
            threshold=args.regression_threshold,
        )
        if regression_info["detected"]:
            logger.warning(
                "Regression detected! Baseline F1: %.3f -> Current F1: %.3f (delta: %.3f)",
                regression_info["baseline_f1"],
                regression_info["current_f1"],
                regression_info["delta"],
            )
        else:
            logger.info(
                "No regression. Baseline F1: %.3f -> Current F1: %.3f (delta: %+.3f)",
                regression_info["baseline_f1"],
                regression_info["current_f1"],
                regression_info["delta"],
            )

    # レポート出力
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"

    write_json_report(report, regression_info, json_path, args.dataset)
    write_markdown_report(report, regression_info, md_path, args.dataset)

    logger.info("Reports written to: %s", output_dir)

    if args.save_baseline:
        baseline_path = output_dir / "baseline.json"
        write_json_report(report, None, baseline_path, args.dataset)
        logger.info("Baseline saved to: %s", baseline_path)

    # リグレッション時の終了コード
    if args.fail_on_regression and regression_info and regression_info["detected"]:
        logger.error("Exiting with code 1 due to regression")
        sys.exit(1)


def load_baseline(baseline_path: str) -> dict[str, object]:
    """ベースラインJSONを読み込む.

    Args:
        baseline_path: ベースラインファイルのパス

    Returns:
        ベースラインデータ
    """
    with open(baseline_path, encoding="utf-8") as f:
        data: dict[str, object] = json.load(f)
        return data


def detect_regression(
    baseline_f1: float,
    current_f1: float,
    threshold: float,
) -> RegressionInfo:
    """リグレッションを検出する.

    Args:
        baseline_f1: ベースラインのF1スコア
        current_f1: 現在のF1スコア
        threshold: リグレッション判定閾値

    Returns:
        リグレッション情報
    """
    delta = current_f1 - baseline_f1
    detected = delta < -threshold
    return RegressionInfo(
        detected=detected,
        baseline_f1=baseline_f1,
        current_f1=current_f1,
        delta=delta,
    )


def write_json_report(
    report: EvaluationReport,
    regression: RegressionInfo | None,
    output_path: Path,
    dataset_path: str,
) -> None:
    """JSONレポートを出力する.

    Args:
        report: 評価レポート
        regression: リグレッション情報（オプション）
        output_path: 出力パス
        dataset_path: 評価データセットのパス
    """
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset_path,
        "summary": {
            "queries_evaluated": report.queries_evaluated,
            "average_precision": report.average_precision,
            "average_recall": report.average_recall,
            "average_f1": report.average_f1,
            "negative_source_violations": len(report.negative_source_violations),
        },
        "regression": regression,
        "query_results": [
            {
                "query_id": qr.query_id,
                "query": qr.query,
                "precision": qr.precision,
                "recall": qr.recall,
                "f1": qr.f1,
                "retrieved_sources": qr.retrieved_sources,
                "expected_sources": qr.expected_sources,
                "negative_violations": qr.negative_violations,
            }
            for qr in report.query_results
        ],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_markdown_report(
    report: EvaluationReport,
    regression: RegressionInfo | None,
    output_path: Path,
    dataset_path: str,
) -> None:
    """Markdownレポートを出力する.

    Args:
        report: 評価レポート
        regression: リグレッション情報（オプション）
        output_path: 出力パス
        dataset_path: 評価データセットのパス
    """
    lines = [
        "# RAG評価レポート",
        "",
        f"**実行日時**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        f"**データセット**: {dataset_path}",
        "",
        "## サマリー",
        "",
        "| 指標 | 値 |",
        "|------|-----|",
        f"| 評価クエリ数 | {report.queries_evaluated} |",
        f"| 平均Precision | {report.average_precision:.3f} |",
        f"| 平均Recall | {report.average_recall:.3f} |",
        f"| 平均F1 | {report.average_f1:.3f} |",
        f"| 禁止ソース違反 | {len(report.negative_source_violations)} |",
        "",
    ]

    if regression:
        lines.extend([
            "## リグレッション検出",
            "",
        ])
        if regression["detected"]:
            lines.append(
                f"**リグレッション検出** "
                f"(ベースラインF1: {regression['baseline_f1']:.3f} -> "
                f"現在F1: {regression['current_f1']:.3f}, "
                f"変化: {regression['delta']:+.3f})"
            )
        else:
            lines.append(
                f"リグレッションなし "
                f"(ベースラインF1: {regression['baseline_f1']:.3f} -> "
                f"現在F1: {regression['current_f1']:.3f}, "
                f"変化: {regression['delta']:+.3f})"
            )
        lines.append("")

    lines.extend([
        "## クエリ別詳細",
        "",
    ])

    for qr in report.query_results:
        status = "PASS" if qr.f1 >= 0.5 else "FAIL"
        lines.extend([
            f"### [{status}] {qr.query_id}: {qr.query}",
            "",
            f"- Precision: {qr.precision:.3f}",
            f"- Recall: {qr.recall:.3f}",
            f"- F1: {qr.f1:.3f}",
            f"- 取得ソース: {len(qr.retrieved_sources)}件",
            f"- 期待ソース: {len(qr.expected_sources)}件",
        ])
        if qr.negative_violations:
            lines.append(f"- **禁止ソース違反**: {qr.negative_violations}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


async def init_test_db(args: argparse.Namespace) -> None:
    """テスト用ChromaDBを初期化する.

    Args:
        args: コマンドライン引数
    """
    logger.info("Initializing test ChromaDB...")
    logger.info("Persist directory: %s", args.persist_dir)
    logger.info("Fixture file: %s", args.fixture)

    # フィクスチャファイルの存在確認
    fixture_path = Path(args.fixture)
    if not fixture_path.exists():
        logger.error("Fixture file not found: %s", args.fixture)
        sys.exit(1)

    # フィクスチャ読み込み
    with open(fixture_path, encoding="utf-8") as f:
        fixture_data = json.load(f)

    documents = fixture_data.get("documents", [])
    if not documents:
        logger.warning("No documents found in fixture")
        return

    # VectorStoreを初期化
    from src.config.settings import get_settings
    from src.embedding.factory import get_embedding_provider
    from src.rag.vector_store import DocumentChunk, VectorStore

    settings = get_settings()
    embedding_provider = get_embedding_provider(settings, settings.embedding_provider)

    vector_store = VectorStore(
        embedding_provider=embedding_provider,
        persist_directory=args.persist_dir,
    )

    # ドキュメントをチャンクに変換して追加
    chunks: list[DocumentChunk] = []
    for doc in documents:
        source_url = doc.get("source_url", "")
        title = doc.get("title", "")
        content = doc.get("content", "")

        if not source_url or not content:
            logger.warning("Skipping document with missing source_url or content")
            continue

        # URLハッシュでIDを生成
        url_hash = hashlib.sha256(source_url.encode()).hexdigest()[:16]
        chunk_id = f"{url_hash}_0"

        chunk = DocumentChunk(
            id=chunk_id,
            text=content,
            metadata={
                "source_url": source_url,
                "title": title,
                "chunk_index": 0,
                "crawled_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        chunks.append(chunk)

    # ベクトルストアに追加
    count = await vector_store.add_documents(chunks)
    logger.info("Added %d documents to test ChromaDB at %s", count, args.persist_dir)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    main()
