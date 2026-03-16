# AI Assistant

Slack上で動作するAI学習支援アシスタント。
RSS記事の自動収集・要約配信、チャットでの質問応答、ユーザーの興味に基づく学習トピック提案を行う。

コスト最適化のため、タスクの性質に応じてローカルLLM（LM Studio）とオンラインLLM（OpenAI / Anthropic）を使い分ける。

## 主な機能

| 機能 | 概要 |
|------|------|
| **チャット応答** | Slackでボットにメンションすると、会話履歴を踏まえて文脈に沿った回答を返す |
| **情報収集・配信** | RSSフィードから記事を自動収集・LLMで要約し、毎朝Slackチャンネルに配信する。管理コマンドでフィードの追加・削除も可能 |
| **ユーザー情報抽出** | ユーザーとの会話から興味・スキル・学習目標を自動抽出し、プロファイルとして蓄積する |
| **トピック提案** | ユーザープロファイルと最新の収集記事を組み合わせて、パーソナライズされた学習トピックを提案する |
| **特定チャンネル自動返信** | 指定したチャンネルではメンション不要で、全メッセージに自動応答する |
| **外部ツール連携（MCP）** | Model Context Protocolにより、LLMが外部ツールを動的に発見・呼び出しできるエージェント的な動作を実現する |
| **RAGナレッジ** | 外部リポジトリ（rag-knowledge）のMCPサーバーと連携し、ベクトルDBの知識を活用してチャット応答品質を向上させる |
| **スレッド対応** | Slackスレッド内でメンションされた際にスレッド履歴を取得し、文脈を踏まえた応答を行う |
| **Slack mrkdwn形式対応** | LLMの返信をSlack mrkdwn形式でフォーマットし、太字・リスト等が正しく表示されるようにする |
| **CLIアダプター** | Slack接続なしでCLIからボット動作を確認できるPort/Adapterパターンを提供する（REPLモード・ワンショットモード対応） |
| **ボットステータス** | 稼働環境・ホスト名・稼働時間を表示し、どのサーバーでボットが動作しているかを確認できる |
| **Botプロセスガード** | PIDファイルによるプロセス管理で、多重起動の防止・グレースフルシャットダウン・子プロセスのクリーンアップを行う |

全機能の一覧と仕様書リンクは [全体仕様概要](docs/specs/overview.md) を参照。

## 動作環境

- **OS**: Windows 11（主要開発・運用環境）
- **ランタイム**: Python 3.11+
- **パッケージ管理**: uv

## 技術スタック

Python 3.11+ / uv / slack-bolt / OpenAI SDK / Anthropic SDK / SQLite + SQLAlchemy / feedparser / MCP SDK

詳細は [全体仕様概要](docs/specs/overview.md) を参照。

## セットアップ

```bash
uv sync
cp .env.example .env  # 環境依存値を編集
```

API キー・トークンは py-common-lib の `get_secret` で OS セキュアストレージから取得する（サービス名: `ai-assistant`）。
登録方法は [py-common-lib の仕様書](https://github.com/becky3/py-common-lib/blob/main/docs/specs/infrastructure/secret-store.md) を参照。

詳細は `.env.example` および [設定管理仕様](docs/specs/infrastructure/config-management.md) を参照。

## 起動

```bash
# フォアグラウンドで直接起動
uv run python -m src.main

# バックグラウンドで起動（管理コマンド）
uv run python -m src.main --start

# 停止 / 再起動 / 状態確認
uv run python -m src.main --stop
uv run python -m src.main --restart
uv run python -m src.main --status
```

## プロジェクト構造

プロジェクトのディレクトリ構成・モジュール責務・仕様書との対応は [ARCHITECTURE.md](ARCHITECTURE.md) を参照。

## 開発ガイドライン

**開発を始める前に必ず [CLAUDE.md](CLAUDE.md) を読んでください。**

CLAUDE.mdには以下の重要な情報が含まれています：

- 仕様駆動開発のルール
- コーディング規約
- Git運用フロー
- LLM使い分けルール
- Claude Code 拡張機能（Hooks、エージェントチーム）

### 開発フロー概要（git-flow）

本プロジェクトは git-flow ベースのブランチ戦略を採用。詳細は git-flow 仕様（`~/.claude/docs/specs/workflows/git-flow.md`）を参照。

1. Issue・Milestoneの確認 (`gh milestone list`, `gh issue list`)
2. 対象Issueの仕様書を読む (`docs/specs/`)
3. `develop` からブランチ作成 (`feature/{機能名}-#{Issue番号}`)
4. 実装・テスト
5. コミット (`type(scope): 説明 (#Issue番号)`)
6. `develop` に向けてPR作成 (`gh pr create --base develop`)

### テストと lint

```bash
# テスト実行
uv run pytest

# lint
uv run ruff check .

# 型チェック
uv run mypy src
```

## ドキュメント

### 全体仕様

- [全体仕様概要](docs/specs/overview.md)

### 機能仕様（features）

- [チャット応答](docs/specs/features/chat-response.md)
- [情報収集・配信](docs/specs/features/feed-management.md)
- [ユーザー情報抽出](docs/specs/features/user-profiling.md)
- [トピック提案](docs/specs/features/topic-recommend.md)
- [特定チャンネル自動返信](docs/specs/features/auto-reply.md)
- [ボットステータス](docs/specs/features/bot-status.md)
- [スレッドサポート](docs/specs/features/thread-support.md)
- [Slack mrkdwn形式対応](docs/specs/features/slack-formatting.md)
- [CLIアダプター](docs/specs/features/cli-adapter.md)

### 基盤仕様（infrastructure）

- [MCP統合](docs/specs/infrastructure/mcp-integration.md)
- [RAGナレッジ](docs/specs/infrastructure/rag-knowledge.md)
- [Bot プロセスガード](docs/specs/infrastructure/bot-process-guard.md)
- [設定管理](docs/specs/infrastructure/config-management.md)

### ワークフロー（workflows）

shared-workflows リポジトリで管理。仕様書は [shared-workflows/docs/specs/](https://github.com/becky3/shared-workflows/tree/main/docs/specs) を参照。

- 自動進行管理（auto-progress）
- Copilot 自動修正ワークフロー（copilot-auto-fix）
- Claude Code Actions（claude-code-actions）

### Claude Code 拡張（agentic）

**プロジェクト固有エージェント:**

- [Test Runner エージェント](docs/specs/agentic/agents/test-runner-agent.md)

**プロジェクト固有スキル:**

- [Check Review Batch スキル](docs/specs/agentic/skills/check-review-batch-skill.md)
- [Topic スキル](docs/specs/agentic/skills/topic-skill.md)
