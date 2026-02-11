# F9: RAG自動評価パイプライン (Phase 3)

## 概要

RAG検索精度の自動評価パイプラインを構築し、CI/CDでの定期的な精度テスト、リグレッション検出、評価レポートの自動生成を実現する。

## 背景

Phase 2でPrecision/Recall評価関数とテストデータセットを整備した。Phase 3では、これらを活用して継続的な品質監視を自動化する。

### 親Issue

- #173 (RAG検索精度の評価・検証の仕組みを導入)

### 関連Issue

- #176 (Phase 2: 閾値フィルタリング) — PR #192 で完了
- #195 (チャンキング改善・ハイブリッド検索) — 未着手

### Phase 2完了時点の成果

| 成果物 | 説明 |
|--------|------|
| `src/rag/evaluation.py` | Precision/Recall計算、データセット読み込み、評価レポート生成 |
| `tests/fixtures/rag_evaluation_dataset.json` | 8クエリの評価用テストデータセット |
| `RAG_SIMILARITY_THRESHOLD` | 類似度閾値フィルタリング機能 |

### Phase 2で判明した課題

チャンキング戦略の問題（数値テーブルデータ中心のチャンク）により、キーワード検索的なクエリの精度が低い。Issue #195 の対応が必要だが、Phase 3の自動評価パイプラインは**現状の精度を記録・監視するため**にも先に構築する価値がある。

## ユーザーストーリー

- 開発者として、RAG検索精度をCI/CDで自動テストし、リグレッションを早期発見したい
- 開発者として、コードベースの変更が検索精度に影響したかを把握したい
- 開発者として、評価結果をMarkdown/JSONレポートとして確認したい
- 開発者として、ベースラインと比較してリグレッションを検出したい

## 機能仕様

### 1. 評価CLIコマンド

RAG評価をコマンドラインから実行できるようにする。

#### コマンド形式

```bash
# 基本実行
python -m src.rag.cli evaluate

# オプション指定
python -m src.rag.cli evaluate \
  --dataset tests/fixtures/rag_evaluation_dataset.json \
  --output-dir reports/rag-evaluation \
  --baseline-file reports/rag-evaluation/baseline.json \
  --n-results 5 \
  --threshold 0.5 \
  --fail-on-regression
```

#### オプション

| オプション | 型 | デフォルト | 説明 |
|-----------|---|----------|------|
| `--dataset` | str | `tests/fixtures/rag_evaluation_dataset.json` | 評価データセットのパス |
| `--output-dir` | str | `reports/rag-evaluation` | レポート出力ディレクトリ |
| `--baseline-file` | str \| None | `None` | ベースラインJSONファイルのパス |
| `--n-results` | int | `5` | 各クエリで取得する結果数 |
| `--threshold` | float \| None | `None` | 類似度閾値（`RAG_SIMILARITY_THRESHOLD` を上書き） |
| `--fail-on-regression` | bool | `False` | リグレッション検出時に exit code 1 で終了 |
| `--regression-threshold` | float | `0.1` | F1スコアの低下がこの値を超えたらリグレッション判定 |

#### 出力ファイル

- `{output-dir}/report.json` — 構造化された評価結果
- `{output-dir}/report.md` — 人間可読なMarkdownレポート
- `{output-dir}/baseline.json` — ベースラインとして保存用（`--save-baseline` 指定時）

### 2. リグレッション検出

ベースラインと比較して、精度の低下（リグレッション）を検出する。

#### リグレッション判定基準

```python
# デフォルト: F1スコアが10%以上低下したらリグレッション
regression_detected = (baseline_f1 - current_f1) > regression_threshold
```

#### ベースラインの更新

- 意図的な変更（チャンキング改善など）後は、新しい結果をベースラインとして保存
- コマンド: `python -m src.rag.cli evaluate --save-baseline`
- ベースラインファイルはリポジトリにコミット管理

### 3. 評価レポート

#### JSONレポート形式

```json
{
  "timestamp": "2026-02-09T12:00:00Z",
  "dataset": "tests/fixtures/rag_evaluation_dataset.json",
  "config": {
    "n_results": 5,
    "similarity_threshold": 0.5
  },
  "summary": {
    "queries_evaluated": 8,
    "average_precision": 0.625,
    "average_recall": 0.75,
    "average_f1": 0.68,
    "negative_source_violations": 0
  },
  "regression": {
    "detected": false,
    "baseline_f1": 0.65,
    "current_f1": 0.68,
    "delta": 0.03
  },
  "query_results": [
    {
      "query_id": "q1",
      "query": "まもりのマント 入手場所",
      "precision": 0.5,
      "recall": 1.0,
      "f1": 0.67,
      "retrieved_sources": ["https://..."],
      "expected_sources": ["https://..."],
      "negative_violations": []
    }
  ]
}
```

#### Markdownレポート形式

```markdown
# RAG評価レポート

**実行日時**: 2026-02-09 12:00:00
**データセット**: tests/fixtures/rag_evaluation_dataset.json

## サマリー

| 指標 | 値 |
|------|-----|
| 評価クエリ数 | 8 |
| 平均Precision | 0.625 |
| 平均Recall | 0.75 |
| 平均F1 | 0.68 |
| 禁止ソース違反 | 0 |

## リグレッション検出

✅ リグレッションなし（ベースラインF1: 0.65 → 現在F1: 0.68）

## クエリ別詳細

### q1: まもりのマント 入手場所

- Precision: 0.5
- Recall: 1.0
- F1: 0.67
- 取得ソース: 2件
- 期待ソース: 2件
- 禁止ソース違反: なし

...
```

### 4. GitHub Actions ワークフロー

#### ワークフロー設計

```mermaid
flowchart TB
    subgraph Trigger["トリガー"]
        SCHEDULE["スケジュール<br/>(週1回)"]
        MANUAL["手動実行<br/>(workflow_dispatch)"]
        PR["PR作成/更新<br/>(特定パス変更時)"]
    end

    subgraph Setup["セットアップ"]
        CHECKOUT["checkout"]
        DEPS["依存関係<br/>インストール"]
        CHROMA["ChromaDB<br/>セットアップ"]
    end

    subgraph Evaluate["評価実行"]
        CLI["python -m src.rag.cli evaluate"]
        REPORT["レポート生成"]
        REGRESSION["リグレッション検出"]
    end

    subgraph Output["出力"]
        ARTIFACT["Artifacts<br/>アップロード"]
        COMMENT["PR/Issueコメント<br/>(オプション)"]
        FAIL["失敗時: exit 1"]
    end

    Trigger --> Setup --> Evaluate --> Output
```

#### ワークフローファイル (`.github/workflows/rag-evaluation.yml`)

```yaml
name: RAG Evaluation

on:
  schedule:
    - cron: '0 9 * * 1'  # 毎週月曜 9:00 UTC
  workflow_dispatch:
    inputs:
      save_baseline:
        description: 'Save current results as new baseline'
        type: boolean
        default: false
  pull_request:
    paths:
      - 'src/rag/**'
      - 'src/embedding/**'
      - 'src/services/rag_knowledge.py'
      - 'tests/fixtures/rag_evaluation_dataset.json'

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Setup test ChromaDB
        run: |
          # テスト用のChromaDBを初期化
          python -m src.rag.cli init-test-db

      - name: Run RAG evaluation
        id: evaluate
        run: |
          python -m src.rag.cli evaluate \
            --output-dir reports/rag-evaluation \
            --baseline-file reports/rag-evaluation/baseline.json \
            ${{ github.event.inputs.save_baseline == 'true' && '--save-baseline' || '' }} \
            ${{ github.event_name == 'pull_request' && '--fail-on-regression' || '' }}

      - name: Upload evaluation report
        uses: actions/upload-artifact@v4
        with:
          name: rag-evaluation-report
          path: reports/rag-evaluation/

      - name: Comment on PR
        if: github.event_name == 'pull_request'
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const report = fs.readFileSync('reports/rag-evaluation/report.md', 'utf8');
            github.rest.issues.createComment({
              issue_number: context.issue.number,
              owner: context.repo.owner,
              repo: context.repo.repo,
              body: report
            });
```

### 5. テスト用ChromaDB初期化

評価を実行するには、テストデータが投入されたChromaDBが必要。

#### init-test-dbコマンド

```bash
python -m src.rag.cli init-test-db \
  --persist-dir ./test_chroma_db \
  --fixture tests/fixtures/rag_test_documents.json
```

テスト用ドキュメントフィクスチャ (`tests/fixtures/rag_test_documents.json`):

```json
{
  "documents": [
    {
      "source_url": "https://example.com/dq3/item/mamorinomanto.html",
      "title": "まもりのマント",
      "content": "まもりのマントは、ふゆうじょう、かこのカオスしんでんで入手できます..."
    }
  ]
}
```

## 技術仕様

### CLI モジュール (`src/rag/cli.py`)

```python
"""RAG評価CLIモジュール

仕様: docs/specs/f9-rag-auto-evaluation.md
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.rag.evaluation import (
    EvaluationReport,
    evaluate_retrieval,
)


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


async def run_evaluation(args: argparse.Namespace) -> None:
    """評価を実行しレポートを出力する."""
    # RAGサービス初期化
    rag_service = await create_rag_service(threshold=args.threshold)

    # 評価実行
    report = await evaluate_retrieval(
        rag_service=rag_service,
        dataset_path=args.dataset,
        n_results=args.n_results,
    )

    # ベースライン比較
    regression_info = None
    if args.baseline_file and Path(args.baseline_file).exists():
        baseline = load_baseline(args.baseline_file)
        regression_info = detect_regression(
            baseline_f1=baseline["summary"]["average_f1"],
            current_f1=report.average_f1,
            threshold=args.regression_threshold,
        )

    # レポート出力
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json_report(report, regression_info, output_dir / "report.json")
    write_markdown_report(report, regression_info, output_dir / "report.md")

    if args.save_baseline:
        write_json_report(report, None, output_dir / "baseline.json")

    # リグレッション時の終了コード
    if args.fail_on_regression and regression_info and regression_info["detected"]:
        sys.exit(1)


def detect_regression(
    baseline_f1: float,
    current_f1: float,
    threshold: float,
) -> dict:
    """リグレッションを検出する."""
    delta = current_f1 - baseline_f1
    detected = delta < -threshold
    return {
        "detected": detected,
        "baseline_f1": baseline_f1,
        "current_f1": current_f1,
        "delta": delta,
    }
```

### レポート生成関数

```python
def write_json_report(
    report: EvaluationReport,
    regression: dict | None,
    output_path: Path,
) -> None:
    """JSONレポートを出力する."""
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
    regression: dict | None,
    output_path: Path,
) -> None:
    """Markdownレポートを出力する."""
    lines = [
        "# RAG評価レポート",
        "",
        f"**実行日時**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
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
                f"⚠️ **リグレッション検出** "
                f"(ベースラインF1: {regression['baseline_f1']:.3f} → "
                f"現在F1: {regression['current_f1']:.3f}, "
                f"変化: {regression['delta']:+.3f})"
            )
        else:
            lines.append(
                f"✅ リグレッションなし "
                f"(ベースラインF1: {regression['baseline_f1']:.3f} → "
                f"現在F1: {regression['current_f1']:.3f}, "
                f"変化: {regression['delta']:+.3f})"
            )
        lines.append("")

    lines.extend([
        "## クエリ別詳細",
        "",
    ])

    for qr in report.query_results:
        status = "✅" if qr.f1 >= 0.5 else "⚠️"
        lines.extend([
            f"### {status} {qr.query_id}: {qr.query}",
            "",
            f"- Precision: {qr.precision:.3f}",
            f"- Recall: {qr.recall:.3f}",
            f"- F1: {qr.f1:.3f}",
            f"- 取得ソース: {len(qr.retrieved_sources)}件",
            f"- 期待ソース: {len(qr.expected_sources)}件",
        ])
        if qr.negative_violations:
            lines.append(f"- ⚠️ 禁止ソース違反: {qr.negative_violations}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
```

### ディレクトリ構成

```
ai-assistant/
├── src/
│   └── rag/
│       ├── evaluation.py      # 既存: Precision/Recall計算
│       └── cli.py             # 新規: CLIエントリポイント
├── tests/
│   └── fixtures/
│       ├── rag_evaluation_dataset.json  # 既存: 評価クエリ
│       └── rag_test_documents.json      # 新規: テスト用ドキュメント
├── reports/
│   └── rag-evaluation/
│       ├── baseline.json      # ベースライン（リポジトリ管理）
│       ├── report.json        # 最新評価結果
│       └── report.md          # Markdownレポート
└── .github/
    └── workflows/
        └── rag-evaluation.yml # 新規: 評価ワークフロー
```

## 受け入れ条件

### CLI

- [ ] **AC1**: `python -m src.rag.cli evaluate` で評価が実行できること
- [ ] **AC2**: `--dataset` オプションでデータセットパスを指定できること
- [ ] **AC3**: `--output-dir` オプションでレポート出力先を指定できること
- [ ] **AC4**: `--n-results` オプションで取得結果数を指定できること
- [ ] **AC5**: `--threshold` オプションで類似度閾値を指定できること

### レポート生成

- [ ] **AC6**: JSON形式のレポートが出力されること
- [ ] **AC7**: Markdown形式のレポートが出力されること
- [ ] **AC8**: レポートにタイムスタンプ、サマリー、クエリ別詳細が含まれること

### リグレッション検出

- [ ] **AC9**: `--baseline-file` 指定時にベースラインと比較すること
- [ ] **AC10**: F1スコアの低下がしきい値を超えたらリグレッション判定すること
- [ ] **AC11**: `--fail-on-regression` 指定時、リグレッション検出で exit code 1 になること
- [ ] **AC12**: `--save-baseline` 指定時に現在の結果をベースラインとして保存すること

### GitHub Actions

- [ ] **AC13**: 週次スケジュールで評価が自動実行されること
- [ ] **AC14**: `workflow_dispatch` で手動実行できること
- [ ] **AC15**: RAG関連ファイル変更時にPRでトリガーされること
- [ ] **AC16**: 評価レポートがArtifactsとしてアップロードされること
- [ ] **AC17**: PR時にレポートがコメントとして投稿されること（オプション）

### テスト用DB

- [ ] **AC18**: `init-test-db` コマンドでテスト用ChromaDBを初期化できること
- [ ] **AC19**: テストドキュメントフィクスチャを読み込みベクトル化できること

## テスト方針

### ユニットテスト

| テストファイル | テスト | 対応AC |
|--------------|--------|--------|
| `tests/test_rag_cli.py` | `test_ac1_evaluate_command_runs` | AC1 |
| `tests/test_rag_cli.py` | `test_ac2_dataset_option` | AC2 |
| `tests/test_rag_cli.py` | `test_ac3_output_dir_option` | AC3 |
| `tests/test_rag_cli.py` | `test_ac6_json_report_format` | AC6 |
| `tests/test_rag_cli.py` | `test_ac7_markdown_report_format` | AC7 |
| `tests/test_rag_cli.py` | `test_ac10_regression_detection` | AC10 |
| `tests/test_rag_cli.py` | `test_ac11_fail_on_regression_exit_code` | AC11 |
| `tests/test_rag_cli.py` | `test_ac12_save_baseline` | AC12 |

### 統合テスト

- GitHub Actions ワークフローのテストは手動確認
- CI環境でのChromaDB初期化をテスト

## 関連ファイル

### 新規ファイル

| ファイル | 用途 |
|---------|------|
| `src/rag/cli.py` | CLIエントリポイント |
| `tests/fixtures/rag_test_documents.json` | テスト用ドキュメントフィクスチャ |
| `tests/test_rag_cli.py` | CLIテスト |
| `.github/workflows/rag-evaluation.yml` | 評価ワークフロー |
| `reports/rag-evaluation/baseline.json` | ベースライン（リポジトリ管理） |

### 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `src/rag/__init__.py` | cliモジュールのエクスポート |
| `.gitignore` | `reports/rag-evaluation/*.json` の除外（baseline.json以外） |

### 参照ファイル

| ファイル | 参照理由 |
|---------|---------|
| `src/rag/evaluation.py` | 評価関数の利用 |
| `tests/fixtures/rag_evaluation_dataset.json` | 評価データセットの形式確認 |
| `docs/specs/f9-rag-knowledge.md` | RAG機能の基盤仕様 |
| `docs/specs/f9-rag-evaluation.md` | Phase 1仕様 |

## 注意事項

1. **ChromaDBの状態依存**: 評価を実行するには、適切なテストデータが投入されたChromaDBが必要。`init-test-db` コマンドで初期化する。

2. **CI環境でのEmbedding**: GitHub ActionsではLM Studioが利用できないため、オンラインEmbedding（OpenAI）を使用するか、事前計算済みのベクトルを使用する設計が必要。

3. **現状の精度問題**: Phase 2で判明した通り、現状のチャンキング戦略では期待通りの精度が出ない可能性がある。これは Issue #195 で対応予定。自動評価パイプラインは現状の精度を記録・監視するために構築する。

4. **ベースライン管理**: ベースラインファイルはリポジトリにコミットし、チーム全体で共有する。意図的な変更後は明示的に更新する。

5. **レポートの除外**: 生成されたレポート（`report.json`, `report.md`）は `.gitignore` で除外し、Artifactsのみで管理する。ベースライン（`baseline.json`）のみコミット対象。

## 変更履歴

| 日付 | 内容 |
|------|------|
| 2026-02-09 | 初版作成 (Phase 3設計) |
