# Learning Companion

Slack上で動作するAI学習支援アシスタント。
RSS記事の自動収集・要約配信、チャットでの質問応答、ユーザーの興味に基づく学習トピック提案を行う。

コスト最適化のため、タスクの性質に応じてローカルLLM（LM Studio）とオンラインLLM（OpenAI / Anthropic）を使い分ける。

## 主な機能

- **チャット応答** — @メンションで質問に回答（オンラインLLM）
- **情報収集・配信** — RSSフィードから記事を収集・要約し、毎朝Slackに自動配信（要約はローカルLLM）
- **ユーザープロファイリング** — 会話から興味・スキル・目標を自動抽出（ローカルLLM）
- **学習トピック提案** — プロファイルと最新記事をもとにおすすめトピックを提案（オンラインLLM）

## 技術スタック

Python 3.10+ / uv / slack-bolt / OpenAI SDK / Anthropic SDK / SQLite + SQLAlchemy / APScheduler / feedparser

## セットアップ

```bash
uv sync
cp .env.example .env  # 各種トークン・APIキーを設定
```

## 起動

```bash
uv run python -m src.main
```

## ドキュメント

- [全体仕様概要](docs/specs/overview.md)
- [F1: チャット応答](docs/specs/f1-chat.md)
- [F2: 情報収集・配信](docs/specs/f2-feed-collection.md)
- [F3: ユーザー情報抽出](docs/specs/f3-user-profiling.md)
- [F4: トピック提案](docs/specs/f4-topic-recommend.md)
