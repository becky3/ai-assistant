"""RAG評価CLIテスト

仕様: docs/specs/f9-rag-auto-evaluation.md
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.rag.cli import (
    RegressionInfo,
    detect_regression,
    load_baseline,
    write_json_report,
    write_markdown_report,
)
from src.rag.evaluation import EvaluationReport, QueryEvaluationResult


class TestDetectRegression:
    """リグレッション検出関数のテスト."""

    def test_no_regression_when_f1_improved(self) -> None:
        """F1スコアが改善した場合、リグレッションなし."""
        result = detect_regression(
            baseline_f1=0.5,
            current_f1=0.6,
            threshold=0.1,
        )
        assert result["detected"] is False
        assert result["baseline_f1"] == 0.5
        assert result["current_f1"] == 0.6
        assert result["delta"] == pytest.approx(0.1)

    def test_no_regression_when_f1_slightly_decreased(self) -> None:
        """F1スコアの低下が閾値以内なら、リグレッションなし."""
        result = detect_regression(
            baseline_f1=0.6,
            current_f1=0.55,
            threshold=0.1,
        )
        assert result["detected"] is False
        assert result["delta"] == pytest.approx(-0.05)

    def test_regression_detected_when_f1_decreased_beyond_threshold(self) -> None:
        """F1スコアの低下が閾値を超えたら、リグレッション検出."""
        result = detect_regression(
            baseline_f1=0.7,
            current_f1=0.5,
            threshold=0.1,
        )
        assert result["detected"] is True
        assert result["delta"] == pytest.approx(-0.2)


class TestLoadBaseline:
    """ベースライン読み込みテスト."""

    def test_load_baseline_success(self, tmp_path: Path) -> None:
        """正常なベースラインファイルの読み込み."""
        baseline_data = {
            "summary": {
                "average_f1": 0.65,
                "average_precision": 0.7,
                "average_recall": 0.6,
            }
        }
        baseline_file = tmp_path / "baseline.json"
        baseline_file.write_text(json.dumps(baseline_data), encoding="utf-8")

        result = load_baseline(str(baseline_file))
        summary = result.get("summary", {})
        assert isinstance(summary, dict)
        assert summary.get("average_f1") == 0.65


class TestWriteJsonReport:
    """JSONレポート出力テスト."""

    def test_ac6_json_report_format(self, tmp_path: Path) -> None:
        """AC6: JSON形式のレポートが出力されること."""
        report = EvaluationReport(
            queries_evaluated=2,
            average_precision=0.75,
            average_recall=0.8,
            average_f1=0.77,
            negative_source_violations=[],
            query_results=[
                QueryEvaluationResult(
                    query_id="q1",
                    query="テストクエリ1",
                    precision=0.8,
                    recall=0.9,
                    f1=0.85,
                    retrieved_sources=["https://example.com/a"],
                    expected_sources=["https://example.com/a"],
                    negative_violations=[],
                ),
                QueryEvaluationResult(
                    query_id="q2",
                    query="テストクエリ2",
                    precision=0.7,
                    recall=0.7,
                    f1=0.7,
                    retrieved_sources=["https://example.com/b"],
                    expected_sources=["https://example.com/b"],
                    negative_violations=[],
                ),
            ],
        )

        output_path = tmp_path / "report.json"
        write_json_report(report, None, output_path, "test_dataset.json")

        assert output_path.exists()
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)

        # 必須フィールドの存在確認
        assert "timestamp" in data
        assert "dataset" in data
        assert "summary" in data
        assert "query_results" in data

        # サマリーの値確認
        summary = data["summary"]
        assert summary["queries_evaluated"] == 2
        assert summary["average_precision"] == 0.75
        assert summary["average_recall"] == 0.8
        assert summary["average_f1"] == 0.77
        assert summary["negative_source_violations"] == 0

        # クエリ結果の確認
        assert len(data["query_results"]) == 2
        assert data["query_results"][0]["query_id"] == "q1"


class TestWriteMarkdownReport:
    """Markdownレポート出力テスト."""

    def test_ac7_markdown_report_format(self, tmp_path: Path) -> None:
        """AC7: Markdown形式のレポートが出力されること."""
        report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.8,
            average_recall=0.9,
            average_f1=0.85,
            negative_source_violations=[],
            query_results=[
                QueryEvaluationResult(
                    query_id="q1",
                    query="テストクエリ",
                    precision=0.8,
                    recall=0.9,
                    f1=0.85,
                    retrieved_sources=["https://example.com/a"],
                    expected_sources=["https://example.com/a"],
                    negative_violations=[],
                ),
            ],
        )

        output_path = tmp_path / "report.md"
        write_markdown_report(report, None, output_path, "test_dataset.json")

        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")

        # 必須セクションの存在確認
        assert "# RAG評価レポート" in content
        assert "## サマリー" in content
        assert "## クエリ別詳細" in content
        assert "評価クエリ数 | 1" in content
        assert "平均F1 | 0.850" in content


class TestRegressionInfo:
    """リグレッション情報付きレポートのテスト."""

    def test_ac10_regression_detection(self, tmp_path: Path) -> None:
        """AC10: F1スコアの低下がしきい値を超えたらリグレッション判定すること."""
        report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.5,
            average_recall=0.5,
            average_f1=0.5,
            negative_source_violations=[],
            query_results=[],
        )

        regression_info = RegressionInfo(
            detected=True,
            baseline_f1=0.7,
            current_f1=0.5,
            delta=-0.2,
        )

        json_path = tmp_path / "report.json"
        write_json_report(report, regression_info, json_path, "test_dataset.json")

        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        assert data["regression"] is not None
        assert data["regression"]["detected"] is True
        assert data["regression"]["baseline_f1"] == 0.7
        assert data["regression"]["current_f1"] == 0.5

        md_path = tmp_path / "report.md"
        write_markdown_report(report, regression_info, md_path, "test_dataset.json")

        content = md_path.read_text(encoding="utf-8")
        assert "## リグレッション検出" in content
        assert "リグレッション検出" in content


class TestSaveBaseline:
    """ベースライン保存テスト."""

    def test_ac12_save_baseline(self, tmp_path: Path) -> None:
        """AC12: --save-baseline指定時に現在の結果をベースラインとして保存すること."""
        report = EvaluationReport(
            queries_evaluated=2,
            average_precision=0.75,
            average_recall=0.8,
            average_f1=0.77,
            negative_source_violations=[],
            query_results=[],
        )

        baseline_path = tmp_path / "baseline.json"
        write_json_report(report, None, baseline_path, "test_dataset.json")

        assert baseline_path.exists()
        with open(baseline_path, encoding="utf-8") as f:
            data = json.load(f)

        # ベースラインとして利用可能か確認
        assert data["summary"]["average_f1"] == 0.77
        # リグレッション情報はNone（ベースライン用）
        assert data["regression"] is None


class TestCLIEvaluate:
    """CLI evaluateコマンドのテスト."""

    @pytest.mark.asyncio
    async def test_ac1_evaluate_command_runs(self, tmp_path: Path) -> None:
        """AC1: python -m src.rag.cli evaluate で評価が実行できること."""
        from src.rag.cli import run_evaluation
        from argparse import Namespace

        # モック用の評価レポート
        mock_report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.8,
            average_recall=0.9,
            average_f1=0.85,
            negative_source_violations=[],
            query_results=[
                QueryEvaluationResult(
                    query_id="q1",
                    query="テスト",
                    precision=0.8,
                    recall=0.9,
                    f1=0.85,
                    retrieved_sources=["https://example.com/a"],
                    expected_sources=["https://example.com/a"],
                    negative_violations=[],
                ),
            ],
        )

        # テスト用データセット作成
        dataset_path = tmp_path / "test_dataset.json"
        dataset_data = {
            "queries": [
                {
                    "id": "q1",
                    "query": "テスト",
                    "expected_sources": ["https://example.com/a"],
                    "negative_sources": [],
                }
            ]
        }
        dataset_path.write_text(json.dumps(dataset_data), encoding="utf-8")

        output_dir = tmp_path / "output"

        args = Namespace(
            dataset=str(dataset_path),
            output_dir=str(output_dir),
            baseline_file=None,
            n_results=5,
            threshold=None,
            fail_on_regression=False,
            regression_threshold=0.1,
            save_baseline=False,
        )

        with patch("src.rag.cli.create_rag_service") as mock_create_service:
            with patch("src.rag.cli.evaluate_retrieval", return_value=mock_report):
                mock_service = AsyncMock()
                mock_create_service.return_value = mock_service

                await run_evaluation(args)

        # レポートが出力されたか確認
        assert (output_dir / "report.json").exists()
        assert (output_dir / "report.md").exists()

    @pytest.mark.asyncio
    async def test_ac2_dataset_option(self, tmp_path: Path) -> None:
        """AC2: --dataset オプションでデータセットパスを指定できること."""
        from src.rag.cli import run_evaluation
        from argparse import Namespace

        mock_report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.8,
            average_recall=0.9,
            average_f1=0.85,
            negative_source_violations=[],
            query_results=[],
        )

        # カスタムデータセットパス
        custom_dataset = tmp_path / "custom_dataset.json"
        custom_dataset.write_text(json.dumps({"queries": []}), encoding="utf-8")

        output_dir = tmp_path / "output"

        args = Namespace(
            dataset=str(custom_dataset),
            output_dir=str(output_dir),
            baseline_file=None,
            n_results=5,
            threshold=None,
            fail_on_regression=False,
            regression_threshold=0.1,
            save_baseline=False,
        )

        with patch("src.rag.cli.create_rag_service") as mock_create_service:
            with patch("src.rag.cli.evaluate_retrieval", return_value=mock_report) as mock_eval:
                mock_service = AsyncMock()
                mock_create_service.return_value = mock_service

                await run_evaluation(args)

                # カスタムデータセットパスが使用されたか確認
                mock_eval.assert_called_once()
                call_kwargs = mock_eval.call_args
                assert call_kwargs[1]["dataset_path"] == str(custom_dataset)

    @pytest.mark.asyncio
    async def test_ac3_output_dir_option(self, tmp_path: Path) -> None:
        """AC3: --output-dir オプションでレポート出力先を指定できること."""
        from src.rag.cli import run_evaluation
        from argparse import Namespace

        mock_report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.8,
            average_recall=0.9,
            average_f1=0.85,
            negative_source_violations=[],
            query_results=[],
        )

        dataset = tmp_path / "dataset.json"
        dataset.write_text(json.dumps({"queries": []}), encoding="utf-8")

        # カスタム出力ディレクトリ
        custom_output = tmp_path / "custom_output" / "reports"

        args = Namespace(
            dataset=str(dataset),
            output_dir=str(custom_output),
            baseline_file=None,
            n_results=5,
            threshold=None,
            fail_on_regression=False,
            regression_threshold=0.1,
            save_baseline=False,
        )

        with patch("src.rag.cli.create_rag_service") as mock_create_service:
            with patch("src.rag.cli.evaluate_retrieval", return_value=mock_report):
                mock_service = AsyncMock()
                mock_create_service.return_value = mock_service

                await run_evaluation(args)

        # カスタム出力ディレクトリにレポートが出力されたか確認
        assert custom_output.exists()
        assert (custom_output / "report.json").exists()
        assert (custom_output / "report.md").exists()

    @pytest.mark.asyncio
    async def test_ac11_fail_on_regression_exit_code(self, tmp_path: Path) -> None:
        """AC11: --fail-on-regression指定時、リグレッション検出でexit code 1になること."""
        from src.rag.cli import run_evaluation
        from argparse import Namespace

        mock_report = EvaluationReport(
            queries_evaluated=1,
            average_precision=0.3,
            average_recall=0.4,
            average_f1=0.35,  # ベースラインより大幅に低い
            negative_source_violations=[],
            query_results=[],
        )

        dataset = tmp_path / "dataset.json"
        dataset.write_text(json.dumps({"queries": []}), encoding="utf-8")

        # ベースラインファイル作成（F1=0.7）
        baseline_file = tmp_path / "baseline.json"
        baseline_data = {
            "summary": {"average_f1": 0.7},
        }
        baseline_file.write_text(json.dumps(baseline_data), encoding="utf-8")

        output_dir = tmp_path / "output"

        args = Namespace(
            dataset=str(dataset),
            output_dir=str(output_dir),
            baseline_file=str(baseline_file),
            n_results=5,
            threshold=None,
            fail_on_regression=True,
            regression_threshold=0.1,
            save_baseline=False,
        )

        with patch("src.rag.cli.create_rag_service") as mock_create_service:
            with patch("src.rag.cli.evaluate_retrieval", return_value=mock_report):
                mock_service = AsyncMock()
                mock_create_service.return_value = mock_service

                with pytest.raises(SystemExit) as exc_info:
                    await run_evaluation(args)

                assert exc_info.value.code == 1


class TestCLIInitTestDb:
    """CLI init-test-dbコマンドのテスト."""

    @pytest.mark.asyncio
    async def test_init_test_db_creates_chromadb(self, tmp_path: Path) -> None:
        """init-test-dbコマンドでChromaDBが初期化されること."""
        from src.rag.cli import init_test_db
        from argparse import Namespace

        # テスト用フィクスチャ作成
        fixture_path = tmp_path / "fixture.json"
        fixture_data = {
            "documents": [
                {
                    "source_url": "https://example.com/test.html",
                    "title": "テストドキュメント",
                    "content": "これはテスト用のコンテンツです。",
                }
            ]
        }
        fixture_path.write_text(json.dumps(fixture_data), encoding="utf-8")

        persist_dir = tmp_path / "test_chroma"

        args = Namespace(
            persist_dir=str(persist_dir),
            fixture=str(fixture_path),
        )

        with patch("src.config.settings.get_settings") as mock_settings:
            with patch("src.embedding.factory.get_embedding_provider") as mock_provider:
                with patch("src.rag.vector_store.VectorStore") as mock_vector_store:
                    mock_settings.return_value = MagicMock(embedding_provider="local")
                    mock_provider.return_value = MagicMock()

                    mock_store_instance = MagicMock()
                    mock_store_instance.add_documents = AsyncMock(return_value=1)
                    mock_vector_store.return_value = mock_store_instance

                    await init_test_db(args)

                    # VectorStoreが正しいパスで初期化されたか確認
                    mock_vector_store.assert_called_once()
                    call_kwargs = mock_vector_store.call_args[1]
                    assert call_kwargs["persist_directory"] == str(persist_dir)

                    # add_documentsが呼ばれたか確認
                    mock_store_instance.add_documents.assert_called_once()
