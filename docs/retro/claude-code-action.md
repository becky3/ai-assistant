# claude-code-action 設定のレトロスペクティブ

## 概要

GitHub Actions で `anthropics/claude-code-action` を使用した自動化ワークフローの設定に関する知見。

## 関連Issue/PR

- Issue #153: タスク完了時のIssue通知コメント追加
- PR #170: prompt パラメータ追加（問題発生）
- PR #178: prompt パラメータ修正

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

## 次に活かすこと

- claude-code-action の設定変更時は、**対話型/オートメーションの両モードの挙動**を確認する
- `prompt` パラメータを使う場合は、元のトリガー内容を含めることを忘れない
- GitHub Actions のワークフロー変更後は、実際にトリガーして動作確認する（ログを確認）
