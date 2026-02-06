# AI Assistant — 全体仕様概要

## 1. プロダクト概要

AI Assistantは、Slack上で動作するAIアシスタントである。
ユーザーとの会話、情報の自動収集・要約配信、ユーザープロファイリング、学習トピック提案を通じて、継続的な学習をサポートする。

## 2. 機能一覧

| ID | 機能名 | 概要 | 仕様書 |
|----|--------|------|--------|
| F1 | チャット応答 | @メンションによる質問応答 | [f1-chat.md](f1-chat.md) |
| F2 | 情報収集・配信 | RSS収集→要約→毎朝自動配信 | [f2-feed-collection.md](f2-feed-collection.md) |
| F3 | ユーザー情報抽出 | 会話から興味・スキル・目標を抽出 | [f3-user-profiling.md](f3-user-profiling.md) |
| F4 | トピック提案 | 収集情報+プロファイルから学習提案 | [f4-topic-recommend.md](f4-topic-recommend.md) |
| F5 | MCP統合 | LLMが外部ツールを動的に呼び出すプロトコル統合 | [f5-mcp-integration.md](f5-mcp-integration.md) |
| F6 | 特定チャンネル自動返信 | 指定チャンネルでメンションなしでも自動応答 | [f6-auto-reply.md](f6-auto-reply.md) |
| F7 | ボットステータスコマンド | 稼働環境・ホスト名・稼働時間の表示 | [f7-bot-status.md](f7-bot-status.md) |
| F8 | ボットのスレッド対応 | Slackスレッド履歴取得によるコンテキスト補完 | [f8-thread-support.md](f8-thread-support.md) |
| F9 | RAGナレッジ | 外部Webページの知識をベクトルDBに蓄積しチャット応答に活用 | [f9-rag-knowledge.md](f9-rag-knowledge.md) |

## 3. 技術スタック

| カテゴリ | 技術 |
|---------|------|
| 言語 | Python 3.10+ |
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
4. 機能完了時にレトロスペクティブを実施し、運用ルールを改善

### 仕様書テンプレート
```
# F{N}: 機能名
## 概要
## 背景（必要に応じて）
## ユーザーストーリー
## 入出力仕様（具体例付き）
## 受け入れ条件（チェックリスト形式）
## 使用LLMプロバイダー（該当する場合）
## 関連ファイル（実装対象）
## テスト方針
```

### Git運用
- ブランチ: `feature/f{N}-{機能名}-#{Issue番号}`
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- マイルストーンでStep単位の進捗管理
