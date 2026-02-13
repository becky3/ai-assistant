---
name: test-run
description: pytest・ruff・mypy・markdownlint・shellcheck によるコード品質チェックの実行・分析・修正提案
user-invocable: true
allowed-tools: Bash, Read, Grep, Glob, Edit
argument-hint: "[diff|full]"
---

## タスク

pytest による自動テスト実行、ruff によるリント、mypy による型チェック、markdownlint による Markdown チェック、shellcheck によるシェルスクリプトチェックを実行し、結果を分析して修正提案を行う。

## 引数

`$ARGUMENTS` の形式:

- `diff`: 変更に関連するテストのみ実行（差分テスト）
- `full`: 全テスト実行（デフォルト）
- 未指定: `full` モードで実行

## 実行対象

- `tests/*.py` の pytest テストファイル
- `src/` および `tests/` のリントチェック（ruff）
- `src/` の型チェック（mypy）
- `docs/**/*.md`, `*.md`, `.claude/**/*.md` の Markdown チェック（markdownlint）
- `.github/scripts/**/*.sh` のシェルスクリプトチェック（shellcheck）
- プロジェクトは `uv` によるパッケージ管理を使用

## 実行コマンド

- テスト: `uv run pytest`
- リント: `uv run ruff check src/ tests/`
- 型チェック: `uv run mypy src/`
- Markdown チェック: `npx markdownlint-cli2@0.20.0`
- Markdown 自動修正: `npx markdownlint-cli2@0.20.0 --fix`
- シェルスクリプトチェック: `uv run shellcheck .github/scripts/auto-fix/*.sh .github/scripts/post-merge/*.sh`

## 処理手順

### 1. 実行モードの判定

- `$ARGUMENTS` に `diff` が含まれる → `diff` モード
- `$ARGUMENTS` に `full` が含まれる、または未指定 → `full` モード

### 2. テスト対象の特定

#### diff モードの場合

変更ファイルの取得（以下の優先順位で試行）:

1. 作業ツリーの変更（未ステージ・ステージング両方）: `git diff --name-only`
2. ベースブランチとの比較: `base=$(git merge-base HEAD origin/develop) && git diff --name-only "$base" HEAD`
3. ステージング済みの変更のみ: `git diff --cached --name-only`
4. 直近コミットの差分（フォールバック）: `git show --name-only --format="" HEAD`
5. すべて失敗した場合 → `full` モードにフォールバック

変更ファイルから対応テストを推定（下記マッピングルール参照）。

**特殊ケース**:

- 変更ファイル 0 件で指定もなし → `full` モードにフォールバック
- Markdown ファイル（`*.md`）のみの変更 → pytest・ruff・mypy・shellcheck はスキップ、markdownlint のみ実行
- シェルスクリプト（`*.sh`）のみの変更 → pytest・ruff・mypy・markdownlint はスキップ、shellcheck のみ実行
- `pyproject.toml`, `conftest.py` の変更 → `full` モードにフォールバック

#### full モードの場合

- 引数でファイルパスやテスト名が指定されていればそれを実行
- `-k` オプションによるパターンマッチも対応
- カバレッジ測定が要求されていれば `--cov` オプションを付与
- 未指定なら全テストを実行

### 3. テスト実行

```bash
uv run pytest
```

必要に応じて `-v` や `-vv` で詳細出力を有効化。

### 4. リント (ruff) 実行

```bash
uv run ruff check src/ tests/
```

diff モードでは変更された `*.py` ファイルのみを対象にする。

### 5. 型チェック (mypy) 実行

```bash
uv run mypy src/
```

diff モードでは変更された `src/**/*.py` ファイルのみを対象にする。

### 6. Markdown チェック (markdownlint) 実行

```bash
npx markdownlint-cli2@0.20.0
```

diff モードでは変更された Markdown ファイルのみを対象にする。

### 7. シェルスクリプトチェック (shellcheck) 実行

```bash
uv run shellcheck .github/scripts/auto-fix/*.sh .github/scripts/post-merge/*.sh
```

diff モードでは変更された `*.sh` ファイルのみを対象にする。
シェルスクリプト（`*.sh`）が存在しない場合や変更がない場合はスキップする。

**重要**: pytest・ruff・mypy・markdownlint・shellcheck のいずれかが失敗してもプロセスを中断せず、すべてのチェックを実行して統合レポートを生成する。

### 8. 結果の解析

- **pytest 成功時**: 実行件数、実行時間、カバレッジ率（要求された場合）
- **pytest 失敗時**: 成功/失敗件数、各失敗テストのエラーメッセージ、スタックトレース
- **ruff 違反あり時**: 違反ファイル、ルールコード、行番号、違反内容
- **mypy エラーあり時**: エラーファイル、エラー種別、行番号、エラー内容
- **markdownlint 違反あり時**: 違反ファイル、ルールコード、行番号、違反内容、自動修正可能かどうか
- **shellcheck 違反あり時**: 違反ファイル、エラーコード（SC????）、行番号、違反内容、重大度（error/warning/info）

### 9. 失敗時の詳細調査

- 失敗したテストファイルを Read で読み込み
- テスト対象のソースコードを Read で読み込み
- エラーの種類を特定（AssertionError, TypeError, AttributeError 等）
- 根本原因を分析（テストコードの問題、ソースコードの問題、依存関係の問題）
- リント違反・型エラー・Markdown 違反・shellcheck 違反時も該当箇所のコードを Read で確認

### 10. 修正案の生成

各失敗テスト・リント違反・型エラー・Markdown 違反・shellcheck 違反に対して:

- エラー内容の要約
- 原因の説明
- 具体的な修正案（ファイルパス、行番号、修正コード）
- 修正の優先度（Critical/Warning/Suggestion）

### 11. 修正適用と再実行（オプション）

- ユーザーが承認した場合、Edit ツールで修正を適用
- markdownlint の場合は `--fix` オプションで自動修正を適用
- 修正後に再度テスト・リント・型チェック・Markdown チェック・shellcheck を実行して確認

## 出力フォーマット

### 全て成功時

```markdown
### コード品質チェック結果 ✅

#### pytest
- **実行件数**: {N} passed
- **実行時間**: {X.XX}s

#### ruff (lint)
- **違反**: なし

#### mypy (型チェック)
- **型エラー**: なし

#### markdownlint
- **違反**: なし

#### shellcheck
- **違反**: なし

すべてのチェックが成功しました。
```

### 失敗時

```markdown
### コード品質チェック結果 ❌

#### pytest
- **成功**: {N} passed
- **失敗**: {M} failed
- **実行時間**: {X.XX}s

##### 失敗したテスト

**{番号}. {テストファイル}::{テストケース名}**

**エラー内容:**
{エラーメッセージ}

**原因:**
- {原因の説明}

**修正案:**
{ファイルパス}:{行番号} の修正コード

---

#### ruff (lint)
- **違反**: {N}件（または「なし」）

#### mypy (型チェック)
- **型エラー**: {N}件（または「なし」）

#### markdownlint
- **違反**: {N}件（または「なし」）

#### shellcheck
- **違反**: {N}件（または「なし」）

---

#### 次のステップ
上記の修正を適用しますか？修正後に再度テストを実行します。
```

## 差分テストのマッピングルール

| ソースファイルパターン | 対応テストファイル |
|----------------------|-------------------|
| `src/services/{name}.py` | `tests/test_{name}.py` または `tests/test_{name}_service.py` |
| `src/rag/*.py` | `tests/test_rag_*.py` + RAG 精度テスト判定 |
| `src/embedding/*.py` | `tests/test_embedding.py` + RAG 精度テスト判定 |
| `src/llm/*.py` | `tests/test_llm.py` |
| `src/config/*.py` | `tests/test_config.py` |
| `src/db/*.py` | `tests/test_db.py` |
| `src/slack/*.py` | `tests/test_slack_handlers.py`, `tests/test_slack_feed_handlers.py` |
| `src/scheduler/*.py` | `tests/test_scheduler.py` |
| `src/mcp_bridge/*.py` | `tests/test_mcp_client_manager.py` |
| `src/process_guard.py` | `tests/test_process_guard.py` |
| `tests/*.py` | そのまま実行対象に追加 |

### フォールバック条件

以下の場合は全テスト実行にフォールバック:

- `pyproject.toml` が変更された場合
- `conftest.py` が変更された場合
- マッピングで対応テストが見つからなかった場合
- `src/__init__.py` など共通モジュールが変更された場合

## RAG 精度テスト

RAG 関連ファイル（`src/rag/**`, `src/embedding/**`, `src/services/rag_knowledge.py`）が変更された場合、通常のテストに加えて RAG 精度テストの実行を検討する。

### 必要性の判定

| 変更内容 | 精度テストの必要性 |
|----------|-------------------|
| チャンキングロジック（`chunker.py`, `heading_chunker.py`, `table_chunker.py`） | **必須** |
| ベクトル検索ロジック（`vector_store.py`, `hybrid_search.py`, `bm25_index.py`） | **必須** |
| Embedding プロバイダー（`src/embedding/**`） | **必須** |
| 類似度閾値・検索パラメータ | **必須** |
| RAG サービスの統合ロジック（`rag_knowledge.py`） | 推奨 |
| CLI・評価ロジック（`cli.py`, `evaluation.py`） | 不要（ユニットテストで十分） |

### 実行フロー

RAG 精度テストが必要と判断した場合、確認なしで自動実行する:

1. テスト用 ChromaDB を初期化:

   ```bash
   python -m src.rag.cli init-test-db \
     --persist-dir ./test_chroma_db \
     --fixture tests/fixtures/rag_test_documents.json
   ```

2. 精度評価を実行:

   ```bash
   python -m src.rag.cli evaluate \
     --persist-dir ./test_chroma_db \
     --output-dir reports/rag-evaluation
   ```

3. 結果を報告: レポート（`reports/rag-evaluation/report.md`）の内容を表示

## テスト名規約

このプロジェクトではテスト名が受け入れ条件（AC）と対応している:

```python
def test_ac1_rss_feed_is_fetched_and_parsed():  # AC1に対応
def test_ac2_duplicate_articles_skipped():  # AC2に対応
```

失敗したテストの AC 番号から、該当する仕様書（`docs/specs/`）の受け入れ条件を参照することで、テストの意図をより深く理解できる。

## 注意事項

- `uv` コマンドが利用できない環境では適切にエラーを報告する
- `npx` コマンドが利用できない環境では markdownlint をスキップし、他のチェックは続行する
- `shellcheck` コマンドが利用できない環境（`uv run shellcheck --version` が失敗する場合）では shellcheck をスキップし、他のチェックは続行する
- テスト失敗時は必ず失敗したテストのソースコードを読んでから分析する
- リント違反・型エラー・Markdown 違反時は該当箇所のコードを読んでから分析する
- 修正案は具体的で、ファイルパス・行番号を含める
- 修正を適用する場合は、必ずユーザーの承認を得る
- markdownlint の `--fix` オプションで自動修正可能な違反は、ユーザー承認後に一括修正できる
