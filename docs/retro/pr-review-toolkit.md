# PR Review Toolkit 導入のレトロスペクティブ

## 概要

Anthropic 公式の PR Review Toolkit プラグインを導入し、PR 作成時の自動レビュー機能を実装した。

## 関連Issue/PR

- Issue #130: PR Review Toolkit 導入検討
- PR #223: PR Review Toolkit 導入

---

## 2026-02-11: 導入作業

### 何を実装したか

**Phase 1: プラグイン導入**

- 6つの専門レビューエージェント（`prt-*` プレフィックス）を追加
  - `prt-code-reviewer`: CLAUDE.md 準拠・バグ検出（信頼度スコア付き）
  - `prt-test-analyzer`: テストカバレッジ品質分析
  - `prt-silent-failure-hunter`: サイレント障害検出
  - `prt-type-design-analyzer`: 型設計・不変条件評価
  - `prt-comment-analyzer`: コメント正確性分析
  - `prt-code-simplifier`: コード簡素化
- `/review-pr` 統合コマンドを追加
- CLAUDE.md に使用方法を追記

**Phase 2: GitHub Actions 自動レビュー**

- `pull_request` トリガー（`types: [opened]`）を追加
- `pr-review` ジョブを新設
  - `claude-sonnet-4-5` モデルを使用（コスト効率）
  - PR Review Toolkit エージェントを活用するプロンプト設計
- 既存の `@claude` メンションとの共存（イベント種別で分岐）

### うまくいったこと

1. **Anthropic 公式プラグインの調査が効率的だった**
   - GitHub リポジトリから直接プラグイン構造を調査
   - 各エージェントの仕様を正確に把握

2. **既存サブエージェントとの役割分担を明確化**
   - `prt-` プレフィックスで命名の衝突を回避
   - 既存の `code-reviewer` / `doc-reviewer` との使い分けを CLAUDE.md に記載

3. **GitHub Actions の共存設計**
   - `github.event_name` でイベントを分岐
   - 既存の `@claude` メンションワークフローを維持しつつ新機能を追加

4. **段階的な導入設計**
   - Issue #130 のコメントで事前に Phase 1/2 の設計を議論済み
   - 設計に従った実装でスムーズに進行

### 改善点

1. **markdownlint エラーが32件発生**
   - 新規作成したエージェント定義ファイルにエラーが多数あった
   - 品質レビューフェーズで検出・修正

2. **`.gitignore` で `.claude` が無視されていた**
   - `git add -f` で強制追加が必要だった
   - 今後の Claude Code 関連ファイル追加時は注意が必要

### 技術的な判断

1. **モデル選択: `claude-sonnet-4-5-20250929` を使用**
   - 自動レビューはコスト効率を重視
   - `@claude` メンションによる実装支援は引き続き `claude-opus-4-5` を使用

2. **Slack 通知: 自動レビューは失敗時のみ**
   - 成功時の通知は冗長と判断
   - 既存の `@claude` ジョブは引き続き `always()` で通知

3. **セキュリティガード: `becky3` ユーザーのみ**
   - 既存の `@claude` ジョブと同様の制限を適用

---

## 次に活かすこと

### PR Review Toolkit の活用

- **`/review-pr` コマンド**: PR 作成前に包括的なレビューを実行できる
- **信頼度スコア**: `prt-code-reviewer` は 80 以上の問題のみ報告し、ノイズを削減
- **専門エージェント**: 型設計やサイレント障害など、汎用レビューでは見落としやすい問題を検出

### GitHub Actions 設計

- **イベント分岐**: `github.event_name` で複数のワークフローを共存させる
- **モデル使い分け**: 自動処理には `sonnet`、対話的作業には `opus` を使用してコスト最適化
- **fetch-depth: 0**: 正確な差分取得のため履歴全体を取得

### プラグイン導入時の注意

- **`.gitignore` の確認**: `.claude` ディレクトリが無視されている場合は `git add -f` が必要
- **命名規則**: 既存の定義との衝突を避けるためプレフィックスを付ける
- **markdownlint**: 新規 Markdown ファイルは作成後に必ず lint を実行
