# 引き継ぎ: 初期セットアップ完了

## 完了済み作業
- プロジェクト基盤ファイル作成・マージ済み (PR #1)
  - 仕様書: `docs/specs/overview.md`, `f1-chat.md`, `f2-feed-collection.md`, `f3-user-profiling.md`, `f4-topic-recommend.md`
  - 設定: `pyproject.toml`, `.gitignore`, `.env.example`, `config/assistant.yaml`
  - `CLAUDE.md`, `README.md`
- GitHub Milestones (Step 1〜5) 作成済み
- GitHub Issues (#2〜#10) 作成済み、各Milestoneに紐付け済み
- ラベル作成済み: `feature`, `spec`, `infrastructure`

## 未着手・作業中
- Step 1 の残り:
  - #2 設定管理(pydantic-settings)の実装
  - #3 DBスキーマ・セッション管理の実装
- Step 2 以降は Step 1 完了後に着手

## 注意事項・判断メモ
- 仕様駆動開発: 実装前に必ず `docs/specs/` の仕様書を読むこと
- LLM使い分けはタスクベース（単純作業→ローカル、推論→オンライン）
- `uv` をパッケージマネージャとして使用
- `.claude/` ディレクトリは `.gitignore` でコミット対象外

## 環境メモ
- ローカルLLMは LM Studio (localhost:1234) を想定
- Slack Bot はSocket Mode（開発用）で動作させる想定
