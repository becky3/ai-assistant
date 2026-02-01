# 引き継ぎ: 全機能 (F1〜F4) 実装完了

## 完了済み作業

- **PR #12** (Merged): 設定管理・DBスキーマ (#2, #3)
- **PR #13** (Merged): LLM抽象化層・Slack Bot連携・チャットサービス (#4, #5, #6)
- **PR #14** (Merged): RSS情報収集・記事要約・自動配信スケジューラ (#7, #8)
- **PR #16** (Merged): ユーザー情報自動抽出 (#9)
  - `src/services/user_profiler.py` — 会話からinterests/skills/goalsをLLMで抽出、既存プロファイルとマージ
  - ローカルLLM使用（フォールバックあり）
- **PR #19** (Merged): 学習トピック提案 (#10)
  - `src/services/topic_recommender.py` — ユーザープロファイル＋直近記事を基にオンラインLLMでトピック提案
  - プロファイル未登録時は一般的なおすすめを返す
  - Copilotレビュー指摘3件対応済み

## 未着手・作業中

- **Issue #20**: 実環境での動作確認
  - `.env` を作成しトークン・APIキーを設定
  - Slackアプリの設定（Socket Mode、app_mentionイベント）
  - 全機能の結合テスト

## 注意事項・判断メモ

- テストは全51件通過中（`uv run pytest`）
- mypy strict エラーなし（`uv run mypy src/`）
- `.env` は `.gitignore` に含まれておりコミットされない。`.env.example` をコピーして使う
- LM Studioを使わない場合、ローカルLLMタスク（要約・プロファイル抽出）はオンラインLLMにフォールバックする
- トピック提案のキーワード検出は「おすすめ」「トピック」「何を学ぶ」「何学ぶ」「学習提案」「recommend」
- feedsテーブルへのRSS URL登録は現状DB直接操作が必要（管理UIは未実装）

## 環境メモ

- Python 3.10+、パッケージ管理は uv
- 起動: `uv run python -m src.main`
- DB: SQLite（デフォルトで `./learning_companion.db` に作成される）
