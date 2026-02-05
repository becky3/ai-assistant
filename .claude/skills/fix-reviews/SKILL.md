---
name: fix-reviews
description: PRの未解決レビュー指摘を確認し、妥当な指摘には修正対応する
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob
argument-hint: [pr-number]
---

## タスク

PRの未解決レビュー指摘を確認し、妥当な指摘に対応する。

## 手順

1. PR番号の決定
   - `$ARGUMENTS` が指定されていればその番号を使う
   - 未指定なら `gh pr view --json number -q .number` で現在ブランチのPRを検出

2. 未解決コメントの取得
   - owner/repo は `gh repo view --json owner,name` で取得
   - 以下の GraphQL で未解決スレッドのみ抽出:

```bash
gh api graphql -f query='
{
  repository(owner: "{owner}", name: "{repo}") {
    pullRequest(number: {pr_number}) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 10) {
            nodes {
              author { login }
              body
              path
              line
            }
          }
        }
      }
    }
  }
}' --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .comments.nodes[0] | {author: .author.login, path, line, body}'
```

3. 指摘がない場合は「未解決の指摘はありません」と表示して終了

4. 指摘がある場合は一覧表示:
   ```
   ## 未解決レビューコメント (PR #番号)

   ### [N] ファイル:行番号 (@レビュアー)
   指摘内容の要約
   ```

5. 各指摘について正当性を検討:
   - 指摘対象のファイル・行を読み、コンテキストを理解する
   - 妥当な指摘かどうかを判断する
   - 妥当でない場合はスキップ理由を述べる

6. 妥当な指摘に対して修正を実施

7. 修正後に **test-runner サブエージェント** でテストを実行して全テスト通過を確認:
   - `test-runnerサブエージェントで全テストを実行してください` と呼び出す
   - 直接 `uv run pytest` を実行せず、必ずサブエージェントに委譲すること

8. ドキュメント整合性チェック:
   修正内容が以下のドキュメントの記述と矛盾しないか確認し、必要なら更新する:
   - `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
   - `docs/handover/` — 注意事項・判断メモに記載済みの内容が変わる場合（例: 手動手順が自動化された等）
   - `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合

9. `docs/specs/` に変更がある場合、**doc-reviewer サブエージェント** で変更した仕様書の品質レビューを実施:
   - `doc-reviewerサブエージェントを使用して docs/specs/対象ファイル.md をレビューしてください` と呼び出す
   - Critical/Warning の指摘があれば修正し、再度 test-runner でテスト通過を確認

10. 修正をコミット & push:
   - コミットメッセージ: `fix: レビュー指摘対応 (PR #番号)`
   - 変更内容を箇条書きでコミットメッセージに含める
   - ドキュメント更新がある場合はコミットメッセージにその旨も含める

11. 対応結果のサマリーを表示
