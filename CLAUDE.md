# AI Assistant — 開発ガイドライン

## プロジェクト基盤情報

@README.md
@docs/specs/overview.md

## 設定管理（3層分離）

設定値は3層に分離して管理する。詳細は `docs/specs/infrastructure/config-management.md` を参照。

- **シークレット**: keyring（`resolve_secret()` で取得、サービス名: `ai-assistant`）
- **環境依存値**: `.env`（`_EnvLoader` で読み込み）
- **共通設定値**: `config/config.toml`（git 管理、`_load_toml_config()` で読み込み）
- 新しい設定値は分類基準に従い適切な層に配置すること
- 外部 HTTP リクエストは py-common-lib の `ConstrainedClient` 経由で実行すること

## LLM使い分けルール

- **デフォルト**: 全サービスでローカルLLM（LM Studio）を使用
- **設定変更**: `config/config.toml` の `[llm]` セクションで各サービスごとにLLMを変更可能
- `MCP_ENABLED` — MCP機能の有効/無効（`.env` で設定、デフォルト: `false`）
- RAG機能は rag-knowledge リポジトリに移行済み。MCP サーバーとして `config/mcp_servers.json` で接続設定する

## 自動進行ルール（auto-progress）

自動実装の詳細ルール・品質チェック手順・GA環境の制約は `.claude/CLAUDE-auto-progress.md` を参照。

## Claude Code 拡張機能

### 自律呼び出しルール（プロジェクト固有）

以下はプロジェクト固有のルール:

| ユーザー表現 | 呼び出し先 | 種別 |
|-------------|-----------|------|
| 「テスト実行して」「テスト通して」 | test-runner | エージェント |
| 「自動マージレビューチェックして」 | `/check-review-batch` | スキル |
