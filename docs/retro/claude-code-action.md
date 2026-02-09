# claude-code-action 設定のレトロスペクティブ

## 概要

GitHub Actions で `anthropics/claude-code-action` を使用した自動化ワークフローの設定に関する知見。

## 関連Issue/PR

- Issue #153: タスク完了時のIssue通知コメント追加
- PR #170: prompt パラメータ追加（問題発生）
- PR #178: prompt パラメータ修正
- PR #180: AskUserQuestion 制約の明示
- PR #181: claude-code-action バージョン更新
- PR #182: コミットSHA修正
- PR #183: prompt 削除・Slack通知追加（根本原因対応）

---

## 2026-02-09: prompt パラメータによるトリガーコメント上書き問題

### 発生した問題

`prompt` パラメータを設定したところ、Claude が「何をすべきか」を判断できず質問して終了するようになった。

### 原因

`prompt` パラメータを設定すると、対話型モード（`@claude` メンション）の元のトリガーコメント内容が**上書きされてしまう**。

claude-code-action には2つのモードがある：

1. **対話型モード**: `@claude` メンションで起動。コメント内容が自動的に渡される
2. **オートメーションモード**: `prompt` パラメータで明示的にタスクを指定

`prompt` を設定すると、対話型モードでもオートメーションモードのように動作し、元のコメント内容が渡されなくなる。

### 解決策

`prompt` パラメータ内で GitHub Actions の変数を使い、元のコメント内容を明示的に含める：

```yaml
prompt: |
  【ユーザーからの指示】
  ${{ github.event.comment.body || github.event.issue.body || github.event.review.body }}

  【追加ルール】
  CLAUDE.md のルールに従って作業を進めてください。

  【重要】タスク完了時の必須アクション:
  PRを作成したら、必ず対応したIssueに「新規コメント」として完了報告を投稿すること。
```

### うまくいったこと

- ログファイルから問題の原因（prompt のみが渡されている）を迅速に特定できた
- GitHub Actions の変数展開（`${{ }}`）を使った柔軟な対応ができた
- 複数イベントタイプへの対応を OR 演算子で簡潔に実装できた

### 学び

1. **prompt パラメータは上書き動作**: 追加ではなく上書きになるため、元のコメント内容を含める必要がある
2. **イベントタイプごとに変数が異なる**:
   - `issue_comment`, `pull_request_review_comment`: `github.event.comment.body`
   - `issues`: `github.event.issue.body`
   - `pull_request_review`: `github.event.review.body`
3. **OR演算子で複数イベント対応**: `${{ A || B || C }}` で最初に存在する値を取得できる

---

## 2026-02-09: AskUserQuestion 拒否による処理中断問題

### 発生した問題

トリガーコメント内容は正しく渡されるようになったが、Claude が `AskUserQuestion` ツールで質問しようとして `permission_denials` で拒否され、処理が中断するようになった。

### 原因

GitHub Actions 環境では対話ができないため、`AskUserQuestion` ツールは使用不可。しかし Claude はこの制約を認識しておらず、曖昧な指示に対して質問しようとする。

ログの該当部分：

```json
"permission_denials": [{
  "tool_name": "AskUserQuestion",
  "tool_input": {
    "questions": [{"question": "「Claude導入に必要な手続き」とは何を指していますか？"...}]
  }
}]
```

### 解決策

`prompt` パラメータに GitHub Actions 環境の制約を明示：

```yaml
【GitHub Actions環境の制約】
この環境では対話ができない。AskUserQuestionツールは使用不可。
不明点があっても質問せずに、自分で判断して進めること。
```

### 学び

1. **GitHub Actions では対話不可**: `AskUserQuestion` は `permission_denials` で拒否される
2. **制約の明示が必要**: Claude に環境の制約を明示的に伝えないと、使えないツールを使おうとする
3. **曖昧な指示への対応**: 質問できない環境では「自分で判断して進める」よう指示する

---

## 2026-02-09: コメント投稿されない問題（バージョン起因）

### 発生した問題

AskUserQuestion 問題を解決後も、Claude の処理結果が GitHub コメントとして投稿されなかった。

### 原因

`anthropics/claude-code-action@v1` は **2025年8月のバージョン**で、コメント投稿機能にバグがある可能性があった。最新は `v1.0.46`（2026年2月7日）。

参考: [Issue #548](https://github.com/anthropics/claude-code-action/issues/548)

### 解決策

バージョンを `@v1` から `@v1.0.46` に更新。さらにセキュリティのため、コミットSHAでピン留め。

```yaml
- uses: anthropics/claude-code-action@5994afaaa7f44611addc97a696a135acff5fd218 # v1.0.46
```

### 学び

1. **メジャーバージョンタグ（@v1）は古い可能性がある**: 定期的に最新バージョンを確認する
2. **リリース一覧で最新を確認**: `gh release list --repo anthropics/claude-code-action`

---

## 2026-02-09: Copilot のコミットSHA提案が間違っていた問題

### 発生した問題

Copilot が「タグではなくコミットSHAでピン留めすべき」と正しく指摘したが、提案されたSHAが**存在しなかった**。

```
Error: An action could not be found at the URI '...tarball/3e2f3e0c3b9f90c71f6b16e0ef5c975c3ac3e072'
```

### 原因

Copilot が提案したコミットSHA `3e2f3e0c3b9f90c71f6b16e0ef5c975c3ac3e072` は実在しなかった。

### 解決策

GitHub API で正しいSHAを取得：

```bash
gh api repos/anthropics/claude-code-action/git/refs/tags/v1.0.46 --jq '.object.sha'
# → 5994afaaa7f44611addc97a696a135acff5fd218
```

### 学び

1. **Copilot の提案を鵜呑みにしない**: 特にコミットSHA等の具体的な値は必ず検証する
2. **SHA の取得方法を知っておく**: `gh api repos/{owner}/{repo}/git/refs/tags/{tag}` で取得可能
3. **エラーが出たらすぐ修正**: GitHub Actions のエラーログを確認し、原因を特定する

---

## 2026-02-09: Agent Mode ではコメントが投稿されない問題（根本原因）

### 発生した問題

AskUserQuestion 制約の追加、バージョン更新、コミットSHA修正を行っても、Claude の処理結果が GitHub コメントとして投稿されなかった。

### 原因（根本原因）

`prompt` パラメータを設定すると **Agent Mode** が有効になり、**コメント投稿機能が設計上無効化される**。

claude-code-action のソースコード調査により判明：

- **Tag Mode**（`@claude` メンション、`prompt` なし）: `commentId` を追跡し、コメントを投稿・更新する
- **Agent Mode**（`prompt` あり）: `commentId: undefined` を返し、コメント投稿をスキップする

これは**バグではなく仕様**。Agent Mode は CI/CD パイプライン等での自動処理を想定しており、対話的なコメント投稿は想定されていない。

### 解決策

1. **`prompt` パラメータを削除**: Tag Mode に戻し、コメント投稿機能を復活させる
2. **Slack 通知を追加**: ワークフロー完了時に Slack で通知を受け取る
3. **制約を CLAUDE.md に移動**: GitHub Actions 環境の制約は CLAUDE.md に記載し、Tag Mode でも読み込まれるようにする

```yaml
# prompt パラメータを削除（Tag Mode に戻す）
- uses: anthropics/claude-code-action@5994afaaa7f44611addc97a696a135acff5fd218 # v1.0.46
  with:
    claude_code_oauth_token: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
    # prompt パラメータなし → Tag Mode

# Slack 通知を追加
- name: Slack notification
  if: always()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    fields: repo,message,commit,author,action,eventName,ref,workflow
  env:
    SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
```

### 学び

1. **Tag Mode と Agent Mode の違いを理解する**: `prompt` パラメータの有無でモードが切り替わる
2. **Agent Mode はコメント投稿しない**: これは仕様であり、バグではない
3. **通知が必要なら別の手段を使う**: Slack 通知、メール通知等を併用する
4. **制約は永続的な場所に書く**: prompt ではなく CLAUDE.md に書けば、どのモードでも読み込まれる

---

## 次に活かすこと

### claude-code-action の設定

- **Tag Mode と Agent Mode の違いを理解する**: `prompt` パラメータの有無でモードが切り替わり、挙動が大きく異なる
- **Agent Mode はコメント投稿しない**: コメント通知が必要なら Tag Mode を使うか、Slack 等の別手段を併用する
- **制約は CLAUDE.md に書く**: prompt に書くと Agent Mode になってしまう。CLAUDE.md なら Tag Mode でも読み込まれる
- GitHub Actions のワークフロー変更後は、実際にトリガーして動作確認する（ログを確認）

### GitHub Actions 環境

- **非対話環境の制約を CLAUDE.md に明示する**: `AskUserQuestion` が使えないことを記載する
- **ログの `permission_denials` を確認**: ツール拒否が発生していないかチェックする

### バージョン管理

- **定期的にバージョンを更新する**: `@v1` 等のメジャータグは古い可能性がある
- **Copilot の提案は検証する**: 特にコミットSHA等の具体的な値は `gh api` で確認してから適用する
- **SHA の取得方法**: `gh api repos/{owner}/{repo}/git/refs/tags/{tag} --jq '.object.sha'`
