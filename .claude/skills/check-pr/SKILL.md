---
name: check-pr
description: PRの内容確認・レビュー指摘対応・実装継続を行う
user-invocable: true
allowed-tools: Bash, Read, Edit, Write, Grep, Glob, Task
argument-hint: [pr-number]
---

## タスク

PRの内容を確認し、未解決のレビュー指摘があれば対応した上で、必要な実装を行う。

## 手順

1. PR番号の決定と変数設定
   - `$ARGUMENTS` が指定されていればその番号を使う
   - 未指定なら `gh pr view --json number -q .number` で現在ブランチのPRを検出
   - 以降の手順では決定したPR番号を `$PR_NUMBER` として参照する

2. PRブランチへのチェックアウト
   - 現在のブランチがPRのブランチでない場合:

     ```bash
     gh pr checkout $PR_NUMBER
     ```

   - 未コミットの変更がある場合はチェックアウトが失敗する。その場合は変更を stash するか、先にコミットしてから再実行する

3. PR情報の確認と表示

   ```bash
   # PR基本情報の取得
   gh pr view $PR_NUMBER --json title,body,headRefName,baseRefName

   # 変更ファイル一覧の取得
   gh pr view $PR_NUMBER --json files --jq '.files[].path'

   # 差分の確認
   gh pr diff $PR_NUMBER
   ```

   以下の形式でサマリーを表示:

   ```text
   ## PR #番号 の概要

   ### タイトル
   PRのタイトル

   ### 説明
   PRの説明（なければ「なし」）

   ### 変更ファイル
   - file1.py
   - file2.py
   ```

4. 未解決コメントの取得
   - owner/repo は `gh repo view --json owner,name` で取得
   - 以下の GraphQL で未解決スレッドのみ抽出（`{owner}`, `{repo}`, `$PR_NUMBER` を実際の値に置換して実行）:

   ```bash
   gh api graphql -f query='
   {
     repository(owner: "{owner}", name: "{repo}") {
       pullRequest(number: $PR_NUMBER) {
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

5. 指摘の一覧表示（ある場合）:

   ```text
   ### 未解決レビューコメント

   #### [N] ファイル:行番号 (@レビュアー)
   指摘内容の要約
   ```

   - `[N]` は指摘の通し番号（1から開始）
   - 指摘がない場合は「未解決の指摘はありません」と表示

6. 関連する仕様書の確認
   - PRの目的に対応する `docs/specs/` の仕様書を特定して読む
   - 仕様書の受け入れ条件（AC）を把握する

7. 実装方針の検討と実施
   - PRの目的と変更内容を踏まえ、必要な実装を検討
   - 未解決の指摘がある場合:
     - 指摘対象のファイル・行を読み、コンテキストを理解する
     - 妥当な指摘かどうかを判断する
     - 妥当でない場合はスキップ理由を述べる
     - 妥当な指摘に対して修正を実施
   - 指摘がない場合も、PRの目的を達成するために必要な実装があれば継続

8. 修正後に **test-runner サブエージェント** で差分テストを実行:
   - `test-runnerサブエージェントで差分テストを実行してください` と呼び出す
   - 直接 `uv run pytest` を実行せず、必ずサブエージェントに委譲すること

9. ドキュメント整合性チェック:
   修正内容が以下のドキュメントの記述と矛盾しないか確認し、必要なら更新する:
   - `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
   - `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合

10. `docs/specs/` に変更がある場合、**doc-reviewer サブエージェント** で変更した仕様書の品質レビューを実施:
    - `doc-reviewerサブエージェントを使用して docs/specs/対象ファイル.md をレビューしてください` と呼び出す
    - Critical/Warning の指摘があれば修正し、再度 test-runner でテスト通過を確認

11. PRに対応コメントを投稿（`gh pr comment`）:
    - 各指摘に対して「対応済み ✅」「別Issue化 ⏸️」「対応不要（理由）❌」を明記
    - 対応内容の簡潔な説明を含める
    - レビュアーが再確認しやすいよう、変更箇所や判断理由を記載
    - 例:

      ```text
      ## レビュー指摘への対応

      ### [1] 指摘タイトル ✅
      対応内容の説明

      ### [2] 指摘タイトル ⏸️
      別Issueとして対応する理由
      ```

12. 対応済みレビュースレッドの resolve:
    - owner/repo は `gh repo view --json owner,name` で取得
    - 以下の GraphQL で対応済みの未解決スレッドを取得（`{owner}`, `{repo}`, `$PR_NUMBER` を実際の値に置換して実行）:

      ```bash
      gh api graphql -f query='
      {
        repository(owner: "{owner}", name: "{repo}") {
          pullRequest(number: $PR_NUMBER) {
            reviewThreads(first: 100) {
              nodes {
                id
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
      }'
      ```

    - GraphQL query が失敗した場合はエラーメッセージをログに出力し、resolve 処理をスキップする（致命的ではないため処理を継続）:

      ```bash
      if ! THREADS=$(gh api graphql -f query='...' --jq '...' 2>&1); then
        echo "Warning: Failed to query review threads: $THREADS"
        echo "Skipping thread resolution due to API error"
        # resolve をスキップして次のステップに進む
      fi
      ```

    - レビュースレッドが0件の場合は「対応済みスレッドなし」とログ出力してスキップ
    - ステップ7で「対応済み」と判断したスレッドのみを `resolveReviewThread` mutation で resolve する。未対応の指摘は resolve しない（`$THREAD_ID` を実際のスレッドIDに置換）:

      ```bash
      gh api graphql -f query='
      mutation($threadId: ID!) {
        resolveReviewThread(input: { threadId: $threadId }) {
          thread { isResolved }
        }
      }' -f threadId="$THREAD_ID"
      ```

    - 個別スレッドの resolve 失敗はエラー詳細をログして次のスレッドに継続（1件の失敗で全体を止めない）
    - 全スレッドの resolve 失敗時もエラーとはしない（再レビューで再検出されるため）

13. 修正をコミット & push:
    - コミットメッセージ:
      - 指摘対応のみ: `fix: レビュー指摘対応 (PR #番号)`
      - 実装継続: `feat: 実装内容の説明 (PR #番号)`
    - 変更内容を箇条書きでコミットメッセージに含める
    - ドキュメント更新がある場合はコミットメッセージにその旨も含める

14. 対応結果のサマリーを表示
