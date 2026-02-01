# Learning Companion

Slack上で動作するAI学習支援アシスタント。ローカルLLMとオンラインLLMをタスクに応じて使い分け、コストを最適化する。

## 技術スタック

- Python 3.10+ / uv (パッケージ管理)
- slack-bolt (AsyncApp, Socket Mode)
- OpenAI SDK (OpenAI + LM Studio), Anthropic SDK
- SQLite + SQLAlchemy (async: aiosqlite)
- APScheduler, feedparser, pydantic-settings

## セットアップ

```bash
uv sync
cp .env.example .env  # 編集して各種トークン・APIキーを設定
```

## 起動

```bash
uv run python -m src.main
```

## テスト

```bash
uv run pytest
```

## プロジェクト構造

```
src/
  main.py           # エントリーポイント
  config/settings.py # pydantic-settings による環境変数管理
  db/models.py       # SQLAlchemy モデル (feeds, articles, user_profiles, conversations)
  db/session.py      # DB接続・セッション管理
  slack/app.py       # Slack Bolt AsyncApp 初期化
  slack/handlers.py  # イベントハンドラ
  llm/base.py        # LLMProvider ABC (全プロバイダーの共通インターフェース)
  llm/openai_provider.py
  llm/anthropic_provider.py
  llm/lmstudio_provider.py  # OpenAI SDK で base_url を localhost:1234 に向ける
  llm/factory.py     # プロバイダー生成ファクトリ
  services/chat.py           # チャット応答 (オンラインLLM)
  services/feed_collector.py # RSS収集
  services/summarizer.py     # 記事要約 (ローカルLLM)
  services/user_profiler.py  # 会話からユーザー情報抽出 (ローカルLLM)
  services/topic_recommender.py # 学習トピック提案 (オンラインLLM)
  scheduler/jobs.py  # APScheduler 毎朝の収集・配信ジョブ
config/
  assistant.yaml     # アシスタントの名前・性格・口調 (システムプロンプトに反映)
docs/
  specs/             # 機能仕様書 (実装の根拠)
  retro/             # レトロスペクティブ記録
```

## LLM使い分けルール

- **ローカル (LM Studio)**: 記事要約、ユーザー情報抽出 — 単純・定型タスク
- **オンライン (OpenAI/Claude)**: チャット応答、情報源探索、トピック提案 — 推論力が必要なタスク
- ローカル不可時はオンラインにフォールバック

## 開発ルール

### 仕様駆動開発
- **実装前に必ず `docs/specs/` の仕様書を読むこと**。仕様書が実装の根拠。
- 仕様書にない機能追加・リファクタリングは別Issueに切り出す。
- 仕様変更が必要な場合は、先に仕様書を更新してから実装する。

### コーディング規約
- 各サービスクラスのdocstringに対応する仕様書パスを記載する:
  ```python
  class FeedCollector:
      """RSS/Webからの情報収集サービス
      仕様: docs/specs/f2-feed-collection.md
      """
  ```
- テスト名は仕様書の受け入れ条件(AC)番号と対応させる:
  ```python
  def test_ac1_rss_feed_is_fetched_and_parsed():
  def test_ac2_articles_are_summarized_by_local_llm():
  ```
- ruff でリント、mypy (strict) で型チェック

### Git運用
- ブランチ: `feature/f{N}-{機能名}-#{Issue番号}`
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- GitHub Milestones で Step 単位の進捗管理
- `gh` コマンドで Issue/PR を操作

### レトロスペクティブ
- 各機能の実装完了時に `docs/retro/f{N}-{機能名}.md` に振り返りを記録
- テンプレート・運用ルール自体の改善も行う
