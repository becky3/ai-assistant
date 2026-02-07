# Git Worktree 導入検討レポート

> Issue: #134
> 作成日: 2026-02-07
> ステータス: 検討結果（導入推奨）

## 1. 概要

Git Worktree は、単一のGitリポジトリから複数の作業ディレクトリ（ワークツリー）を作成し、異なるブランチを同時にチェックアウトできるGit標準機能（Git 2.5以降）である。本レポートでは、ai-assistant プロジェクトへの導入価値を検討する。

### 公式ドキュメント

- [git-worktree Documentation](https://git-scm.com/docs/git-worktree)
- [Claude Code Common Workflows - Git Worktrees](https://code.claude.com/docs/en/common-workflows)

## 2. Git Worktree の基本

### 仕組み

```
ai-assistant/          ← メインワークツリー（main ブランチ）
ai-assistant-feature-a/ ← リンクワークツリー（feature/f10-xxx ブランチ）
ai-assistant-bugfix/    ← リンクワークツリー（fix/yyy ブランチ）
```

- 各ワークツリーは独立した作業ディレクトリを持つ
- `.git` オブジェクトデータベースは共有（ディスク効率が良い）
- `HEAD`、インデックス、ワーキングツリーは各ディレクトリで独立
- 同一ブランチを複数ワークツリーで同時チェックアウトすることはできない

### 基本コマンド

```bash
# ワークツリーの作成（新規ブランチ）
git worktree add ../ai-assistant-feature-a -b feature/f10-new-feature

# ワークツリーの作成（既存ブランチ）
git worktree add ../ai-assistant-bugfix fix/some-bug

# 一覧表示
git worktree list

# 削除（必ずこのコマンドで行う。手動でフォルダ削除しない）
git worktree remove ../ai-assistant-feature-a

# メタデータのクリーンアップ
git worktree prune
```

## 3. 導入事例の調査

### 3.1 Anthropic公式推奨

Anthropic社は [Claude Code の公式ドキュメント](https://code.claude.com/docs/en/common-workflows) で Git Worktree を用いた並列開発ワークフローを推奨している。

> "Git worktrees allow you to check out multiple branches from the same repository into separate directories. Each worktree has its own working directory with isolated files, while sharing the same Git history."

ポイント：
- 各ワークツリーで独立した Claude Code セッションを実行可能
- ワークツリー間で変更が干渉しないため、並列作業に最適
- `/resume` で同一リポジトリのワークツリー間のセッションを一覧・復帰できる

### 3.2 incident.io の事例

[incident.io のブログ記事](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees)では、Git Worktree + Claude Code の組み合わせで大幅な開発速度向上を報告している。

- 4〜5個の Claude Code エージェントを同時並列実行
- JavaScript エディタを推定2時間 → 10分で構築
- API生成ツールの18%改善を$8の投資で実現
- bash関数 `w` でワークツリー作成・管理を自動化

### 3.3 日本国内の導入事例

- [シナプス技術者ブログ](https://tech.synapse.jp/entry/2026/01/15/113000): 実務での導入体験レポート
- [Zenn: Git Worktree完全ガイド 2026年版](https://zenn.dev/goyle0/articles/git-worktree-guide-2026): AI駆動開発時代の並列作業術として詳細解説
- [Zenn: AI駆動開発でも活用できる並列開発](https://zenn.dev/tmasuyama1114/articles/git_worktree_beginner): 初心者向け解説
- [Zenn: モバイル開発でのレビュー効率化](https://zenn.dev/yagijin/articles/1a0f3530cc9389): iOS開発でのレビュー効率化事例
- [Qiita: git worktreeの使い方](https://qiita.com/syukan3/items/dab71e88ce91bca44432): 実践的な使い方解説

### 3.4 その他の注目事例

- [Nx Blog](https://nx.dev/blog/git-worktrees-ai-agents): 大規模モノレポでのAIエージェントワークフロー改善
- [CodeRabbit git-worktree-runner](https://github.com/coderabbitai/git-worktree-runner): AI開発向けワークツリー管理ツール（OSSツール）
- [gwq](https://github.com/d-kuro/gwq): ファジーファインダー付きGitワークツリーマネージャー

## 4. ai-assistant プロジェクトへの適合性分析

### 4.1 プロジェクト特性

| 項目 | 現状 | Worktree適合性 |
|------|------|---------------|
| 言語 | Python 3.10 | **高** — venv/uvは各ワークツリーで独立セットアップ可能 |
| パッケージ管理 | uv + pyproject.toml | **高** — `uv sync` で各ワークツリーに環境構築可能 |
| データベース | SQLite（ローカルファイル） | **高** — 各ワークツリーで独立DBファイルを使用可能 |
| Docker | なし | **高** — コンテナ競合の心配なし |
| 環境設定 | `.env`（git管理外） | **中** — 手動コピーが必要 |
| テスト | pytest | **高** — 各ワークツリーで独立実行可能 |
| CI/CD | GitHub Actions (Claude Code) | **高** — ブランチ単位で動作 |
| 仕様書管理 | `docs/specs/` | **高** — 仕様駆動開発と相性が良い |

### 4.2 現在の開発フロー

```
Issue確認 → 仕様書読解 → ブランチ作成 → 実装 → テスト → PR作成
```

**現在の課題**:
- Claude Code（GitHub Actions経由）は1つのIssueに対して1つのブランチで逐次処理
- 複数の独立したIssueを並列に進めたい場合、現行フローでは待ちが発生
- ローカル開発でもブランチ切り替え時に `stash` や WIP コミットが必要

### 4.3 Worktree導入後の想定フロー

```
                    ┌─ worktree A: feature/f10-xxx → Claude Code セッション A
メインワークツリー ──┼─ worktree B: feature/f11-yyy → Claude Code セッション B
     (main)        └─ worktree C: fix/zzz        → Claude Code セッション C
```

- 各ワークツリーで独立した Claude Code セッションを並列実行
- メインワークツリーは `main` ブランチを維持し、レビュー・マージのハブとして機能
- 完了したワークツリーは `git worktree remove` で削除

## 5. メリット・デメリット分析

### 5.1 メリット

#### コンテキストスイッチの排除
- ブランチ切り替え不要で、作業中のファイル状態を保持
- `stash` / WIPコミットが不要に
- エディタの状態（開いているファイル、カーソル位置）が維持される

#### 並列開発の実現
- 複数のClaude Codeインスタンスを同時実行可能
- 独立したIssueを並行して進められる
- 緊急のバグ修正にも作業を中断せず対応可能

#### リソース効率
- リポジトリの完全クローンと比べて `.git` オブジェクトを共有するためディスク効率が良い
- Git履歴やリモート接続も共有

#### AI駆動開発との高い親和性
- Anthropic公式推奨のワークフロー
- Claude Code の `/resume` がワークツリー間のセッション管理をサポート
- 各エージェントが独立した作業空間で動作し、相互干渉なし

#### レビュー効率の向上
- PRレビュー時に別ワークツリーでコード確認可能
- 自分の作業を中断せずにレビューに対応

### 5.2 デメリット・リスク

#### 環境ファイルの手動管理
- `.env` などgit管理外のファイルは各ワークツリーに手動コピーが必要
- **対策**: セットアップスクリプトで自動コピーする仕組みを用意

#### 削除手順の厳守が必要
- フォルダを直接削除すると Git 内部の管理情報と不整合が発生
- 必ず `git worktree remove` を使用する必要がある
- **対策**: CLAUDE.md にルールを明記、ヘルパースクリプトの提供

#### ワークツリーの配置場所に注意
- プロジェクトフォルダ内にワークツリーを作ると、検索結果やgit管理に混乱が生じる
- **対策**: 兄弟ディレクトリ配置を標準ルールとする

#### 同一ブランチの制約
- 1つのブランチは1つのワークツリーでのみチェックアウト可能
- **影響**: 本プロジェクトでは各Issueに専用ブランチを作成するため、実質的な制約にならない

#### 管理の複雑化
- ワークツリーが増えすぎると管理が煩雑になる
- **対策**: 同時ワークツリー数の目安を設定（推奨: 3〜5個以内）、完了後は速やかに削除

## 6. 導入計画案

### Phase 1: ローカル開発での試験導入

1. **ディレクトリ構成ルールの策定**
   ```
   ~/projects/
   ├── ai-assistant/              ← メインワークツリー (main)
   ├── ai-assistant-feature-xxx/  ← 機能開発用
   ├── ai-assistant-fix-yyy/      ← バグ修正用
   └── ai-assistant-review-zzz/   ← レビュー用
   ```

2. **セットアップスクリプトの作成**
   ```bash
   # scripts/new-worktree.sh（案）
   # - ワークツリー作成
   # - .env ファイルのコピー
   # - uv sync の実行
   # - DB初期化
   ```

3. **CLAUDE.md への運用ルール追記**
   - ワークツリーの命名規則
   - 作成・削除のフロー
   - 同時ワークツリー数の推奨上限

### Phase 2: Claude Code 並列実行

1. 複数のターミナルで各ワークツリーに対して `claude` を実行
2. 独立したIssueを並列で処理
3. セッション管理に `/resume` と `/rename` を活用

### Phase 3: 自動化の強化（オプション）

1. ワークツリー管理のヘルパーコマンドの整備
2. 完了済みワークツリーの自動クリーンアップ
3. GitHub Actions との連携（CI上でのワークツリー活用）

## 7. 結論・推奨事項

### 導入推奨度: **高**

以下の理由から、ai-assistant プロジェクトへの Git Worktree 導入を推奨する。

1. **Anthropic公式推奨**: Claude Code のドキュメントで Git Worktree を用いた並列開発が正式に推奨されている
2. **プロジェクト適合性が高い**: Python + uv + SQLite の構成はワークツリー間の独立性を確保しやすく、Docker不使用のため競合リスクも低い
3. **実績のある手法**: incident.io をはじめ、多くの開発チームが実際に成果を上げている
4. **低リスク**: Git標準機能であり、導入コストが低い。既存のワークフローに大きな変更を加える必要がない
5. **仕様駆動開発との相性**: 各Issueが独立した仕様書を持つ本プロジェクトの開発スタイルでは、Issue単位でワークツリーを分離することが自然

### 次のアクション

1. セットアップスクリプト（`scripts/new-worktree.sh`）の実装
2. CLAUDE.md への Git Worktree 運用ルールの追記
3. `.gitignore` へのワークツリー関連パスの追加（必要に応じて）
4. 実際に2〜3個のIssueで試験運用し、効果を検証

## 8. 参考資料

### 公式ドキュメント
- [git-worktree Documentation](https://git-scm.com/docs/git-worktree)
- [Claude Code Common Workflows](https://code.claude.com/docs/en/common-workflows)

### 導入事例・解説記事
- [incident.io: How we're shipping faster with Claude Code and Git Worktrees](https://incident.io/blog/shipping-faster-with-claude-code-and-git-worktrees)
- [Nx Blog: How Git Worktrees Changed My AI Agent Workflow](https://nx.dev/blog/git-worktrees-ai-agents)
- [Zenn: Git Worktree 完全ガイド 2026年版](https://zenn.dev/goyle0/articles/git-worktree-guide-2026)
- [Zenn: Git Worktreeをわかりやすく解説](https://zenn.dev/hiraoku/articles/56f4f9ffc6d186)
- [Zenn: AI駆動開発でも活用できる並列開発の方法](https://zenn.dev/tmasuyama1114/articles/git_worktree_beginner)
- [Zenn: モバイル開発でのレビューはgit worktreeと相性が良い](https://zenn.dev/yagijin/articles/1a0f3530cc9389)
- [Qiita: git worktree の使い方](https://qiita.com/syukan3/items/dab71e88ce91bca44432)
- [シナプス技術者ブログ: Git worktreeを使ってみた](https://tech.synapse.jp/entry/2026/01/15/113000)
- [CloudBuilders: Git Worktreeを導入してみた](https://www.cloudbuilders.jp/articles/6132/)

### ツール
- [CodeRabbit git-worktree-runner](https://github.com/coderabbitai/git-worktree-runner) — AI開発向けワークツリー管理ツール
- [gwq](https://github.com/d-kuro/gwq) — ファジーファインダー付きGitワークツリーマネージャー

### コミュニティ
- [GitHub: Field notes - git worktree pattern (anthropics/claude-code#1052)](https://github.com/anthropics/claude-code/issues/1052)
- [GitHub: Parallel Multi-Agent Workflows Feature Request (anthropics/claude-code#10599)](https://github.com/anthropics/claude-code/issues/10599)
