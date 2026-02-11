# F9: RAG自動評価パイプライン（Phase 3）— レトロスペクティブ

## 概要

RAG検索精度の自動評価パイプラインを構築した。CLIツールによる評価実行、JSON/Markdownレポート出力、ベースライン比較によるリグレッション検出を実装。test-runnerサブエージェントがRAG関連コード変更時に自動実行する仕組みを整備した。

## 実装範囲

| Issue | タイトル | 状態 |
|-------|---------|------|
| #177 | RAG評価・可視化 Phase 3: 自動評価パイプライン | PR #219 で完了 |

関連PR: #219

### 主な成果物

| ファイル | 内容 |
|----------|------|
| `src/rag/cli.py` | RAG評価CLI（evaluate, init-test-db サブコマンド） |
| `tests/test_rag_cli.py` | CLIテスト 13件 |
| `tests/fixtures/rag_test_documents.json` | テスト用ドキュメントフィクスチャ |
| `.claude/agents/test-runner.md` | RAG精度テスト自動実行ルールを追記 |
| `docs/specs/f9-rag-auto-evaluation.md` | Phase 3 仕様書 |

### CLI機能

```bash
# RAG検索精度評価
python -m src.rag.cli evaluate \
  --dataset tests/fixtures/rag_evaluation_dataset.json \
  --output-dir reports/rag-evaluation \
  --baseline-file reports/rag-evaluation/baseline.json \
  --fail-on-regression

# テスト用ChromaDB初期化
python -m src.rag.cli init-test-db \
  --persist-dir ./test_chroma_db \
  --fixture tests/fixtures/rag_test_documents.json
```

## うまくいったこと

### 1. チーム開発による並行作業

エージェントチーム（3名構成）で効率的に作業を分担:

| 役割 | 担当 | 成果 |
|------|------|------|
| メンバーA | テストドキュメント | タスク完了 |
| メンバーB | CLI実装、CLIテスト | 2タスク完了 |
| リーダー | 全体統括、品質レビュー | レビュー完了 |

並行作業により、依存関係のないタスクを同時進行できた。

### 2. 既存コードの活用

Phase 2 で作成した `src/rag/evaluation.py` の評価関数群をそのまま活用:

- `evaluate_retrieval()` — メイン評価ロジック
- `EvaluationReport` — 評価結果データクラス
- `calculate_precision_recall()` — Precision/Recall計算

新規で追加したのはCLIラッパーとレポート出力のみで、評価ロジック自体の再実装は不要だった。

### 3. 著作権問題の迅速な対応

テストデータに実在のゲーム情報（ドラゴンクエスト等）を含めてしまったが、ユーザー指摘後すぐに修正:

- 架空のRPG「勇者の冒険」に完全置き換え
- 全てのキャラクター名、アイテム名、ダンジョン名を架空に
- 構造とテスト意図は維持

### 4. 品質チェックの徹底

test-runner、code-reviewer、doc-reviewer サブエージェントを活用:

- pytest: 566件パス
- ruff/mypy/markdownlint: 問題なし
- コードレビュー: Critical 0件
- ドキュメントレビュー: 整合性良好

## 改善点・ハマったこと

### 1. 著作権問題に最初から気づかなかった

**問題**: テストデータ作成時に、実在のゲーム（ドラゴンクエスト3、ファイナルファンタジー1）の情報をそのまま使用してしまった。

**経緯**:

1. 既存の評価データセット（`rag_evaluation_dataset.json`）がドラクエ3の攻略情報で作成されていた
2. テストドキュメント作成時にそのまま踏襲
3. ユーザー指摘で著作権問題に気づく

**対応**: 両ファイルを架空のRPG「勇者の冒険」に置き換え。

**教訓**: テストデータは最初から架空のコンテンツで作成すべき。実在の著作物を使用しない。

### 2. 環境変数の副作用

**問題**: `create_rag_service()` 関数で `os.environ["RAG_SIMILARITY_THRESHOLD"]` を直接上書きしている。これは他のテストやプロセスに影響を与える可能性がある。

**対応**: code-reviewer の Warning として検出。今後の改善として、設定オブジェクトへの直接代入や関数スコープ内でのみ有効な方法を検討。

### 3. GitHub Actions ワークフローの不要性

**問題**: 当初、GitHub ActionsでRAG精度テストを自動実行するワークフローを設計していたが、実行にはOpenAI APIキー等の設定が必要で、かつRAG精度テストはコード変更時のみ必要なため、CIワークフローとしては過剰だった。

**経緯**:

1. 仕様書に GitHub Actions ワークフローを含めてしまった
2. ワークフロー実装後、401エラー（OpenAI APIキー未設定）が発生
3. ユーザー指摘でワークフローの必要性を再検討

**対応**: ワークフローを削除し、test-runnerサブエージェントがRAG関連コード変更時に自動で精度テストを実行する方式に変更。

**教訓**: CIワークフローを設計する前に、その機能が本当にCI/CD自動化として必要か、ローカル実行で十分かを検討する。

## 今後の課題

| 課題 | 説明 | 優先度 |
|------|------|--------|
| ベースラインの初期作成 | 初回評価でベースラインを生成・コミット | 高 |
| 環境変数副作用の解消 | `create_rag_service()` の設計見直し | 中 |
| AC4/AC5のテスト追加 | `--n-results`, `--threshold` オプションの直接テスト | 低 |

## 次に活かすこと

1. **テストデータに実在の著作物を使用しない** — 最初から架空のコンテンツで作成する習慣をつける

2. **環境変数の上書きは避ける** — テスト時の設定変更は `monkeypatch` やテスト用設定オブジェクトを使用する

3. **チーム開発時の依存関係を明確に** — タスク間の依存関係をTaskListで管理し、並行可能なタスクを最大限活用する

4. **既存コードの活用を優先** — 新規実装より既存の評価関数の再利用を検討する

## 参考

- 仕様書: [docs/specs/f9-rag-auto-evaluation.md](../specs/f9-rag-auto-evaluation.md)
- 関連レトロ: [f9-rag-knowledge.md](./f9-rag-knowledge.md)（RAGナレッジ機能）
- 関連レトロ: [f9-rag-chunking-hybrid.md](./f9-rag-chunking-hybrid.md)（チャンキング・ハイブリッド検索）
