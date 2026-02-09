# F9: RAGナレッジ機能 — レトロスペクティブ

## 概要

外部Webページから収集した知識をベクトルDBに蓄積し、ユーザーの質問に関連する情報を自動検索してチャット応答に活用するRAG（Retrieval-Augmented Generation）機能を実装した。

## 実装範囲

| Issue | タイトル | 状態 |
|-------|---------|------|
| #119 | F9: RAGナレッジ機能の実装（親Issue） | 完了 |
| #114 | 仕様書作成 | 完了 |
| #115 | Embeddingプロバイダーの実装 | 完了 |
| #116 | RAGインフラの実装（チャンキング・ベクトルストア） | 完了 |
| #117 | Webクローラーの実装 | 完了 |
| #118 | RAGナレッジサービスの実装と既存コード統合 | 完了 |
| #161 | アンカー違いの重複取り込み防止 | 完了 |

関連PR: #120, #121, #151, #152, #154, #155, #156, #187

## 主なコンポーネント

```
src/embedding/           — Embeddingプロバイダー（LM Studio/OpenAI切替）
src/rag/                 — チャンキング、ChromaDBベクトルストア
src/services/web_crawler.py    — SSRF対策付きWebクローラー
src/services/rag_knowledge.py  — オーケストレーションサービス
```

**Slackコマンド:**

- `@bot rag crawl <URL> [パターン]` — リンク集から一括取り込み
- `@bot rag add <URL>` — 単一ページ取り込み
- `@bot rag status` — 統計表示
- `@bot rag delete <URL>` — 削除

## うまくいったこと

### 1. 仕様駆動開発の徹底

- 先に詳細な仕様書（f9-rag-knowledge.md）を作成してから実装に入った
- 35個の受け入れ条件（AC）を定義し、テスト名と対応づけ
- 実装中に仕様変更が必要になった場合も、先に仕様書を更新してから実装

### 2. 既存パターンの再利用

| パターン | 参照元 | 適用先 |
|---------|--------|--------|
| 抽象基底クラス | `LLMProvider` | `EmbeddingProvider` |
| ファクトリ関数 | `get_provider_for_service()` | `get_embedding_provider()` |
| 同期APIラップ | `feed_collector.py` | ChromaDB操作 |
| オプショナル注入 | `ThreadHistoryService` | `RAGKnowledgeService` |
| コマンドルーティング | `feed` コマンド | `rag` コマンド |

### 3. セキュリティ対策の事前設計

SSRF対策を仕様書段階で明確化：

- ドメインホワイトリスト（必須）
- スキーム制限（http/httpsのみ）
- リダイレクト追従無効化
- クロール遅延・ページ数制限

### 4. テスト設計

- `chromadb.EphemeralClient()` でファイルシステム副作用なしにテスト
- AC番号ベースのテスト命名でトレーサビリティ確保
- Slackコマンドの統合テストは `pytest.skip()` で明示的にスキップ

## 改善点・ハマったこと

### 1. ChromaDBテレメトリのエラー

**問題**: ChromaDBがデフォルトでテレメトリを送信しようとし、失敗時にエラーログが出力された。

**対応**:

- `ChromaSettings(anonymized_telemetry=False)` でテレメトリ無効化
- ロガーレベルをCRITICALに設定してエラー抑制

**教訓**: 外部ライブラリのデフォルト動作（テレメトリ、ログ出力等）を事前に確認する

### 2. Pythonバージョン変更の波及

**問題**: sentence-transformers（onnxruntime）がPython 3.11以上を要求。テスト実行時にエラー発生。

**対応**: `.python-version`, `pyproject.toml`, `README.md` など複数ファイルを更新。

**教訓**:

- 依存パッケージ追加時はPythonバージョン要件を事前確認
- ML系ライブラリは特にバージョン制約が厳しい

### 3. アンカー違いの重複取り込み

**問題**: `rag crawl` で同一ページのアンカー違い（`#m`, `#movie`等）が別ページとして取り込まれた。

**対応**: PR #187 で解決。`validate_url()` に `urldefrag()` によるフラグメント除去を追加し、`crawl_index_page()` での重複排除、`_ingest_crawled_page()` と `delete_source()` での防御的正規化を実装。

**実装のポイント**:

- 正規化を `validate_url()` に集約することで、下流の全処理で一貫したURLが使用される設計
- `rag_knowledge.py` 側にも防御的に `urldefrag()` を適用（外部入力の安全性確保）
- AC36/AC37として受け入れ条件を追加し、8件のテストでカバー

**教訓**: クローラーのURL正規化は早期に実装すべき。今回の修正は小規模だったが、正規化が遅れるとDB内に重複データが蓄積され、後からのクリーンアップが困難になる

### 4. Settings()の毎回インスタンス化

**問題**: `ChatService.respond()` 内で毎回 `Settings()` をインスタンス化していた。

**対応**: `get_settings()` （キャッシュ済み）を使用するよう修正。

**教訓**: 設定値の取得は初期化時またはキャッシュ経由で行う

### 5. crawl中のフィードバック不足

**問題**: クロール処理中、完了までSlackで反応がなく状況がわからない。

**対応**: Issue #158 として課題化。進捗表示の改善を予定。

**教訓**: 長時間処理には進捗フィードバックが必要

## 今後の課題（Issue化済み）

| Issue | 内容 |
|-------|------|
| #157 | ドメイン許可リストをSlackから動的管理 |
| #158 | crawl進捗フィードバック追加 |
| #159 | URL安全性チェック（Google Safe Browsing API） |
| #160 | robots.txt の解析・遵守 |
| ~~#161~~ | ~~アンカー違いの重複取り込み防止~~ | PR #187 で対応済み |

## 次に活かすこと

1. **外部ライブラリのデフォルト動作を確認する** — テレメトリ、ログレベル、ネットワーク接続等

2. **URL正規化は早期に実装する** — フラグメント除去、末尾スラッシュ統一など

3. **長時間処理には進捗フィードバックを設計に含める** — クローラー、バッチ処理など

4. **設定値の取得はキャッシュ経由で** — `get_settings()` パターンを使用

5. **仕様書のコード例は実装と整合させる** — 型の違い（`list[str]` vs `str`）など細部も確認

## 参考

- 仕様書: [docs/specs/f9-rag-knowledge.md](../specs/f9-rag-knowledge.md)
- 関連レトロ: [f9-rag-infrastructure.md](./f9-rag-infrastructure.md)（チャンキング・ベクトルストア詳細）
