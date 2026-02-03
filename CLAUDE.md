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
  handover/          # 引き継ぎドキュメント
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

### 作業開始時の手順
1. **Issue・Milestoneの確認**: 作業前に必ず現状を把握する
   ```bash
   gh milestone list                  # Milestone一覧と進捗確認
   gh issue list --milestone "Step N: ..."  # 該当Stepのissue一覧
   gh issue list --state open         # 未着手Issue一覧
   gh issue view <番号>               # Issue詳細の確認
   ```
2. **対象Issueの仕様書を読む**: Issueに記載された仕様書パスを確認し、`docs/specs/` の該当ファイルを読む
3. **引き継ぎドキュメントを確認**: `docs/handover/` の最新ファイル（日付が最も新しいもの）を1つ読めばよい
4. **ブランチ作成→実装→PR** の流れで進める

### Git運用
- ブランチ: `feature/f{N}-{機能名}-#{Issue番号}`
- コミット: `feat(f{N}): 説明 (#{Issue番号})`
- PR作成時に `Closes #{Issue番号}` で紐付け
- GitHub Milestones で Step 単位の進捗管理
- `gh` コマンドで Issue/PR を操作

### レビュー指摘対応
PRに対するレビュー指摘（Copilot、人間問わず）を修正した場合、以下を確認すること:
1. **コード修正**: 指摘に対する修正を実施し、テストが全件パスすることを確認
2. **ドキュメント整合性チェック**: 修正内容が以下のドキュメントに影響しないか確認し、必要なら更新する
   - `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
   - `docs/handover/` — 注意事項・判断メモに記載済みの内容が変わる場合（例: 手動手順が自動化された等）
   - `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合
3. **コミット**: `fix: Copilotレビュー指摘対応 (PR #番号)` の形式でコミット

### レトロスペクティブ
- 各機能の実装完了時に `docs/retro/f{N}-{機能名}.md` に振り返りを記録
- テンプレート・運用ルール自体の改善も行う

### 引き継ぎドキュメント (`docs/handover/`)
作業を中断・交代する際に、次の作業者へ状況を伝えるためのドキュメントを残す。

**ファイル命名**: `YYYY-MM-DD-{内容}.md`（例: `2026-02-01-step1-complete.md`）

**構成ルール** — 以下のセクションを含めること:
```markdown
# 引き継ぎ: {タイトル}
## 完了済み作業
- 何を実装/作成したか（Issue番号を含める）
## 未着手・作業中
- 次にやるべきIssue番号と概要
- 着手中のものがあればブランチ名と状況
## 注意事項・判断メモ
- 実装中に気づいた点、設計判断の理由、ハマりポイントなど
## 環境メモ（必要に応じて）
- 特殊な環境設定やローカル固有の情報
```

## Claude Code Hooks

プロジェクトには Claude Code の hooks 機能を使った通知システムが設定されています。

### 設定ファイル

- **`.claude/hooks.json`**: イベント駆動の通知設定
- **`.claude/scripts/notify.sh`**: クロスプラットフォーム対応の通知スクリプト

### 対応イベント

1. **`user-prompt-submit`**: ユーザーの確認が必要な時（最優先）
2. **`task-completed`**: タスク完了時
3. **`tool-call-approved`**: ツール実行承認時

### 通知方式

- **macOS**: `osascript` によるネイティブ通知 + サウンド
- **Linux**: `notify-send` (libnotify) + オプションでサウンド
- **Windows**: PowerShell によるバルーン通知
- **フォールバック**: コンソールへのテキスト出力

### カスタマイズ方法

`.claude/hooks.json` を編集してイベントや通知内容を変更できます:

```json
{
  "hooks": {
    "user-prompt-submit": {
      "command": ".claude/scripts/notify.sh",
      "args": ["カスタムタイトル", "カスタムメッセージ"]
    }
  }
}
```

### 参考資料

- [Zenn記事: Claude Codeのhooks機能について](https://zenn.dev/is0383kk/articles/5d66a34b0a89be)
- Issue #35: Hooks使って、確認時に音を鳴らす
