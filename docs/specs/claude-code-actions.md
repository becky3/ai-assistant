# Claude Code Actions

## 概要

GitHub PRやIssueで `@claude` メンションすることでClaude Codeを呼び出し、コードレビュー、実装、質問応答などを自動化する。

## ユーザーストーリー

- 開発者として、PRで `@claude` メンションしてコードレビューを依頼したい
- 開発者として、Issueで `@claude` メンションして実装を依頼したい
- 開発者として、PRコメントで `@claude` に質問して回答を得たい

## 入出力仕様

### トリガー
- `issue_comment`: Issue/PRへのコメント
- `pull_request_review_comment`: PRレビューコメント
- `issues`: Issue作成・アサイン
- `pull_request_review`: PRレビュー投稿

### 入力
- `@claude` を含むコメント本文
- 対象のIssue/PRのコンテキスト

### 出力
- Issue/PRへのコメントとして回答
- 必要に応じてコード変更のコミット・プッシュ

### 具体例

```
入力: "@claude このリポジトリの概要を教えて"
出力: (Issueコメントとしてリポジトリの概要を回答)
```

```
入力: "@claude このPRのコードをレビューして"
出力: (PRコメントとしてコードレビュー結果を投稿)
```

## 受け入れ条件

- [x] AC1: `@claude` メンションでClaude Codeが起動する
- [x] AC2: becky3ユーザーのみ実行可能（セキュリティガード）
- [x] AC3: OAuth認証でAPIアクセスする
- [x] AC4: `--max-turns 30` でターン数を制限する
- [x] AC5: ワークフローファイルが `.github/workflows/claude.yml` に配置される

## 認証方式

**OAuth認証**（`CLAUDE_CODE_OAUTH_TOKEN`）

### セットアップ手順
1. [Claude GitHub App](https://github.com/apps/claude) をリポジトリにインストール
2. `claude setup-token` でOAuthトークンを取得
3. **リポジトリシークレット**に `CLAUDE_CODE_OAUTH_TOKEN` を登録
   - Settings → Secrets and variables → Actions → **Repository secrets**
   - ⚠️ Environment secrets ではなく Repository secrets に設定すること

## セキュリティガード

| ガード | 説明 |
|--------|------|
| ユーザー制限 | `github.actor == 'becky3'` で許可ユーザーを限定 |
| イベントフィルタリング | `@claude` メンションがある場合のみ実行 |
| トークン保護 | シークレット経由で参照（ハードコードしない） |
| ターン制限 | `--max-turns 30` で無限ループ防止 |

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `.github/workflows/claude.yml` | GitHub Actionsワークフロー定義 |
| `CLAUDE.md` | プロジェクト固有のガイドライン（Claudeが参照） |

## テスト方針

- デプロイ後、テスト用Issueを作成して `@claude このリポジトリの概要を教えて` とコメント
- Claudeがコメントで応答することを確認
- GitHub Actions のログでワークフロー実行を確認
- 許可されていないユーザー（becky3以外）からのメンションでワークフローがスキップされることを確認

## 参考資料

- [Claude Code GitHub Actions 公式ドキュメント](https://code.claude.com/docs/en/github-actions)
- [anthropics/claude-code-action リポジトリ](https://github.com/anthropics/claude-code-action)
