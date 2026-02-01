# Learning Companion — 全体仕様概要

## 1. プロダクト概要

Learning Companionは、Slack上で動作するAI学習支援アシスタントである。
ユーザーとの会話、情報の自動収集・要約配信、ユーザープロファイリング、学習トピック提案を通じて、継続的な学習をサポートする。

## 2. 機能一覧

| ID | 機能名 | 概要 | 仕様書 |
|----|--------|------|--------|
| F1 | チャット応答 | @メンションによる質問応答 | [f1-chat.md](f1-chat.md) |
| F2 | 情報収集・配信 | RSS収集→要約→毎朝自動配信 | [f2-feed-collection.md](f2-feed-collection.md) |
| F3 | ユーザー情報抽出 | 会話から興味・スキル・目標を抽出 | [f3-user-profiling.md](f3-user-profiling.md) |
| F4 | トピック提案 | 収集情報+プロファイルから学習提案 | [f4-topic-recommend.md](f4-topic-recommend.md) |

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

## 4. LLM使い分けルール（タスクベース）

コスト最適化のため、タスクの性質に応じてLLMを使い分ける。

| タスク | プロバイダー | 理由 |
|--------|-------------|------|
| 記事要約 | ローカル (LM Studio) | 単純作業・大量処理向き |
| ユーザー情報抽出 | ローカル | 定型的な抽出タスク |
| 質問への回答 | オンライン (OpenAI/Claude) | 高品質な応答が必要 |
| 情報源探索・提案 | オンライン | 推論力が必要 |
| 学習トピック提案 | オンライン | パーソナライズに推論力が必要 |

**フォールバック**: ローカルLLMが利用不可の場合、オンラインLLMにフォールバックする。

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
## ユーザーストーリー
## 入出力仕様（具体例付き）
## 受け入れ条件（チェックリスト形式）
## 使用LLMプロバイダー
## 関連ファイル（実装対象）
## テスト方針
```

### Git運用
- ブランチ: `feature/f{N}-{機能名}-#{Issue番号}`
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- マイルストーンでStep単位の進捗管理
