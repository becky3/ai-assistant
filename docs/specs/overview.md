# AI Assistant — 全体仕様概要

## 1. プロダクト概要

AI Assistantは、Slack上で動作するAIアシスタントである。
ユーザーとの会話、情報の自動収集・要約配信、ユーザープロファイリング、学習トピック提案を通じて、継続的な学習をサポートする。

## 2. 機能一覧

| # | 機能名 | 概要 | 仕様書 |
|---|--------|------|--------|
| 1 | チャット応答 | @メンションによる質問応答 | [chat-response.md](features/chat-response.md) |
| 2 | 情報収集・配信 | RSS収集→要約→毎朝自動配信 | [feed-management.md](features/feed-management.md) |
| 3 | ユーザー情報抽出 | 会話から興味・スキル・目標を抽出 | [user-profiling.md](features/user-profiling.md) |
| 4 | トピック提案 | 収集情報+プロファイルから学習提案 | [topic-recommend.md](features/topic-recommend.md) |
| 5 | MCP統合 | LLMが外部ツールを動的に呼び出すプロトコル統合 | [mcp-integration.md](infrastructure/mcp-integration.md) |
| 6 | 特定チャンネル自動返信 | 指定チャンネルでメンションなしでも自動応答 | [auto-reply.md](features/auto-reply.md) |
| 7 | ボットステータスコマンド | 稼働環境・ホスト名・稼働時間の表示 | [bot-status.md](features/bot-status.md) |
| 8 | ボットのスレッド対応 | Slackスレッド履歴取得によるコンテキスト補完 | [thread-support.md](features/thread-support.md) |
| 9 | RAGナレッジ | 外部リポジトリ（rag-knowledge）の MCP サーバーとして動作。ベクトル DB に知識を蓄積しチャット応答に活用 | [rag-knowledge.md](infrastructure/rag-knowledge.md) |
| 10 | Slack mrkdwn形式対応 | LLM返信をSlack mrkdwn形式で出力 | [slack-formatting.md](features/slack-formatting.md) |
| 11 | CLIアダプター | Slack非依存でCLIからボット動作を確認するPort/Adapterパターン | [cli-adapter.md](features/cli-adapter.md) |
| 12 | Botプロセスガード | PIDファイルによるプロセス管理で多重起動防止・管理コマンドを提供 | [bot-process-guard.md](infrastructure/bot-process-guard.md) |

## 3. 技術スタック

| カテゴリ | 技術 |
|---------|------|
| 言語 | Python 3.11+ |
| パッケージ管理 | uv |
| Slack SDK | slack-bolt (AsyncApp, Socket Mode) |
| オンラインLLM | OpenAI (openai SDK) / Anthropic (anthropic SDK) |
| ローカルLLM | LM Studio (OpenAI互換API) |
| DB | SQLite + SQLAlchemy (ORM経由で将来DB切替可能) |
| スケジューラ | APScheduler |
| RSS | feedparser |
| 設定管理 | pydantic-settings (.env) + YAML (アシスタント性格) |

## 4. LLM使い分けルール

全サービスでローカルLLM（LM Studio）をデフォルトで使用する。
各サービスごとに `.env` ファイルで使用するLLMを変更可能。

### サービスごとのLLM設定

| 環境変数 | 対象サービス | デフォルト | 説明 |
|----------|-------------|-----------|------|
| `CHAT_LLM_PROVIDER` | ChatService | local | チャット応答 |
| `PROFILER_LLM_PROVIDER` | UserProfiler | local | ユーザー情報抽出 |
| `TOPIC_LLM_PROVIDER` | TopicRecommender | local | トピック提案 |
| `SUMMARIZER_LLM_PROVIDER` | Summarizer | local | 記事要約 |

各設定には `"local"` または `"online"` を指定する。
`"online"` の場合、`ONLINE_LLM_PROVIDER` の設定（`"openai"` or `"anthropic"`）が使用される。

### 設定例

```env
# 全てローカル（デフォルト）
CHAT_LLM_PROVIDER=local
PROFILER_LLM_PROVIDER=local
TOPIC_LLM_PROVIDER=local
SUMMARIZER_LLM_PROVIDER=local

# チャットとトピック提案のみオンライン
CHAT_LLM_PROVIDER=online
TOPIC_LLM_PROVIDER=online
ONLINE_LLM_PROVIDER=openai
```

## 5. DB設計

### テーブル一覧

| テーブル名 | 用途 | 主要カラム |
|-----------|------|-----------|
| feeds | RSSフィード管理 | url, name, category, enabled, created_at |
| articles | 収集済み記事 | feed_id(FK), title, url, summary, published_at, collected_at |
| user_profiles | ユーザー情報 | slack_user_id, interests, skills, goals, updated_at |
| conversations | 会話履歴 | slack_user_id, thread_ts, role, content, created_at |

## 6. アシスタント設定

`config/assistant.yaml` で以下を定義:

- 名前・表示名
- 性格・口調（システムプロンプトに反映）
- アイコンURL
- ステータス絵文字

## 7. 開発方針

### 仕様駆動開発

1. GitHub Issueで機能・タスクを管理
2. 各機能の仕様書を先に作成・承認
3. 仕様書に基づいて実装・テスト
4. 機能完了時にジャーナルに記録し、運用ルールを改善

### 仕様書スタイルガイド

仕様書の分類・命名規則・記述ルールは仕様書スタイルガイド（`~/.claude/docs/specs/style-guide.md`）を参照。

本プロジェクト固有の仕様書カテゴリ:

| カテゴリ | 配置先 | 判断基準 |
|---------|--------|---------|
| ユーザー向け機能 | `features/` | ユーザーが直接触る・意識するプロダクト機能 |
| 基盤・ツール | `infrastructure/` | ユーザーが直接意識しない裏側の仕組み、開発ツール |

### ワークフロー仕様書

GitHub Actions ワークフローの仕様書（auto-progress, copilot-auto-fix, claude-code-actions）は shared-workflows リポジトリの `docs/specs/` で管理する。

### 仕様書テンプレート

共通テンプレートは agent-commons（`~/.claude/docs/templates/`）で管理。一覧は `~/.claude/docs/overview.md` を参照。

### Git運用（git-flow）

git-flow ベースのブランチ戦略を採用。詳細は `~/.claude/docs/specs/workflows/git-flow.md` を参照。

- **常設ブランチ**: `main`（安定版）/ `develop`（開発統合）
- **作業ブランチ**:
  - `feature/{機能名}-#{Issue番号}` — 新機能（`develop` → `develop`）
  - `bugfix/{修正内容}-#{Issue番号}` — バグ修正（`develop` → `develop` / `release/*` → `release/*`）
  - `release/v{X.Y.Z}` — リリース準備（`develop` → `main` squash マージ）
  - `hotfix/{修正内容}-#{Issue番号}` — 緊急修正（`main` → `main` + `develop`）
  - `sync/main-to-develop-v{X.Y.Z}` — リリース後の main → develop 同期（`develop` → `develop`）
- コミット: `type(scope): 説明 (#Issue番号)` ※scope は仕様書ファイル名（拡張子なし）
- PR作成時に `Closes #{Issue番号}` でIssueを紐付け（feature/bugfix: base `develop`, release/hotfix: base `main`）
- リリース後は sync ブランチ経由で `main` → `develop` に差分反映（詳細は `~/.claude/docs/specs/workflows/git-flow.md` 参照）
- マイルストーンでStep単位の進捗管理
