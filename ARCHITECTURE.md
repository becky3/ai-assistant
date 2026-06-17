# アーキテクチャガイド

本ドキュメントはプロジェクトのディレクトリ構成とモジュール責務をフォルダ単位で記述する。ファイル単位の詳細は意図的に省略しており、各モジュールの役割と関係性の把握を目的とする。

## トップレベル構造

| ディレクトリ | 説明 |
|---|---|
| `src/` | アプリケーション本体 |
| `config/` | アシスタント設定・MCP サーバー接続設定 |
| `docs/` | 仕様書・テンプレート |
| `tests/` | テストコード・フィクスチャ |
| `scripts/` | 運用・開発用スクリプト |
| `.claude/` | Claude Code プロジェクト設定 |
| `.github/` | GitHub Actions ワークフロー・PR テンプレート・Copilot 設定 |

## src/ モジュール構成

### サブディレクトリ

| ディレクトリ | 責務 |
|---|---|
| `src/config/` | pydantic-settings による環境変数・設定管理 |
| `src/db/` | SQLAlchemy モデル定義・DB セッション管理 |
| `src/llm/` | LLM プロバイダー抽象化（ローカル / OpenAI / Anthropic）とファクトリ |
| `src/services/` | ビジネスロジック（チャット応答、RSS 収集、要約等） |
| `src/slack/` | Slack Bolt アプリ初期化・イベントハンドラ（SlackListener から利用される Slack 受信実装の内部） |
| `src/messaging/` | メッセージング抽象化（受信 `MessagingListener` Port + 送信 `MessagingPort`/Adapter。Slack/Discord/CLI 実装、中立モデル `IncomingFile`/`ArticleCard`/`ThreadRef`、プラットフォーム選択 `runtime.py`、Discord 整形 `discord_format.py`）。`MessageRouter` はプラットフォーム非依存 |
| `src/scheduler/` | 配信ジョブ（`jobs.py`、`MessagingPort` 経由）と定時実行スケジューラ（`daily_scheduler.py` / `schedule_config.py`、`config/schedule.toml` を毎日定時に実行） |
| `src/mcp_bridge/` | MCP サーバーへの接続管理（クライアント側ブリッジ） |

### ルートレベルファイル

| ファイル | 責務 |
|---|---|
| `src/main.py` | エントリーポイント（Bot 起動・管理コマンド振り分け） |
| `src/cli.py` | CLI アダプター起動エントリーポイント |
| `src/bot_manager.py` | Bot 管理コマンド（start / stop / restart / status） |
| `src/process_guard.py` | Bot 重複起動防止・PID ファイル管理 |
| `src/compat.py` | プラットフォーム互換ユーティリティ |

## 補助ディレクトリ

| ディレクトリ | 説明 |
|---|---|
| `config/` | `assistant.yaml`（アシスタント性格設定・MCP プロンプト）、`config.toml`（共通設定値） |
| `docs/specs/` | 機能仕様書・基盤仕様書・エージェント定義（実装の根拠） |
| `tests/` | pytest テストコード・フィクスチャ |
| `scripts/` | 運用・開発用シェルスクリプト |
| `.claude/` | Claude Code プロジェクト設定 |
| `.github/` | GitHub Actions ワークフロー・PR テンプレート・Copilot 設定 |

## 仕様書 — 実装モジュール対応表

### features/

| 仕様書 | 実装モジュール |
|---|---|
| `features/chat-response.md` | `src/services/`, `src/llm/` |
| `features/feed-management.md` | `src/services/`, `src/scheduler/` |
| `features/auto-reply.md` | `src/slack/`, `src/messaging/` |
| `features/bot-status.md` | `src/slack/` |
| `features/thread-support.md` | `src/slack/`, `src/services/` |
| `features/slack-formatting.md` | `src/services/` |
| `features/cli-adapter.md` | `src/messaging/` |

### infrastructure/

| 仕様書 | 実装モジュール |
|---|---|
| `infrastructure/mcp-integration.md` | `src/mcp_bridge/` |
| `infrastructure/rag-knowledge.md` | 外部リポジトリ（rag-knowledge） |
| `infrastructure/bot-process-guard.md` | `src/process_guard.py`, `src/bot_manager.py` |
| `infrastructure/discord-setup.md` | `src/messaging/` (`runtime.py`, `discord_adapter.py`, `discord_listener.py`, `discord_format.py`) |
| `infrastructure/scheduled-tasks.md` | `src/scheduler/` (`daily_scheduler.py`, `schedule_config.py`) |

### workflows/

ワークフロー仕様書は [shared-workflows リポジトリの docs/specs/](https://github.com/becky3/shared-workflows/tree/main/docs/specs) に移動済み。

| 仕様書（shared-workflows） | 対象 |
|---|---|
| `auto-progress.md` | `.github/workflows/` |
| `copilot-auto-fix.md` | `.github/workflows/` |
| `claude-code-actions.md` | `.github/workflows/` |

### agentic/

プロジェクト固有のスキル仕様:

| 仕様書 | 対象 |
|---|---|
| `agentic/skills/check-review-batch-skill.md` | 自動マージ Issue の PR バッチチェック |

## 関連ドキュメント

- [全体仕様概要](docs/specs/overview.md) — 機能一覧・技術スタック・DB 設計
- 仕様書スタイルガイド（`~/.claude/docs/specs/style-guide.md`）— 仕様書の分類・命名規則・記述ルール
- [CLAUDE.md](CLAUDE.md) — 開発ガイドライン
