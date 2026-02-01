# 引き継ぎ: Step 3 (F2: 情報収集・配信) 完了

## 完了済み作業

- **PR #12** (Merged): 設定管理・DBスキーマ (#2, #3)
- **PR #13** (Merged): LLM抽象化層・Slack Bot連携・チャットサービス (#4, #5, #6)
- **PR #14** (Merged): RSS情報収集・記事要約・自動配信スケジューラ (#7, #8)
  - `src/services/feed_collector.py` — RSS取得、一括重複排除、asyncio.to_threadでノンブロッキング化
  - `src/services/summarizer.py` — ローカルLLMによる記事要約（失敗時はtitleフォールバック）
  - `src/scheduler/jobs.py` — APScheduler cronジョブ、カテゴリ別Slackフォーマット、エラーハンドリング
  - Copilotレビュー指摘14件対応済み

## 未着手・作業中

- **Issue #9**: ユーザー情報自動抽出の実装
  - 仕様: `docs/specs/` を確認（user_profiler関連）
  - `src/services/user_profiler.py` を作成予定
  - ローカルLLM使用（会話からユーザー情報を抽出する定型タスク）
- **Issue #10**: 学習トピック提案の実装
  - `src/services/topic_recommender.py` を作成予定
  - オンラインLLM使用（推論力が必要なタスク）

## 注意事項・判断メモ

- Summarizerは現在タイトル+URLのみでLLMに要約を依頼している。RSSエントリのdescription/summaryフィールドを活用する改善は別Issue向き
- feedsテーブルのURL検証（SSRF対策）は管理者のみが登録する前提でスキップ。公開APIにする場合は要対応
- `datetime` は全てUTC統一に修正済み。`format_daily_digest` のみ表示用に `ZoneInfo("Asia/Tokyo")` を使用
- テストは全34件通過中
- `/fix-copilot-reviews` スキルを `.claude/skills/` に追加済み（PR後のCopilotレビュー対応を自動化）
