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

12. レビュースレッドの resolve:

    **前提条件**: ステップ4で取得した全ての未解決スレッドに対し、ステップ7・11で判断が完了していること。
    未検討のスレッドがある場合はステップ7に戻ること。

    全スレッドの判断完了後、以下の全ステータスのスレッドを resolve する:
    - ✅ 対応済み: 修正を実施した指摘
    - ❌ 対応不要: 判断理由付きで対応しないと決定した指摘
    - ⏸️ 別Issue化: 別Issueを作成して追跡可能にした指摘

    エラーハンドリング方針（auto-fix.yml と統一）:

    | エラー種別 | 対応 |
    |-----------|------|
    | 認証/権限エラー（owner/repo取得失敗、全件resolve失敗） | exit 1 で即停止 |
    | 一時的API障害（個別resolve失敗、スレッド取得失敗） | `::warning::` でログし続行 |
    | データ不存在（PR番号不正、スレッド0件） | ログ出力しスキップ |
    | 取得失敗（非クリティカル） | デフォルト値で続行 |

    - owner/repo の取得とバリデーション（失敗時は認証/権限エラーの可能性 → exit 1）:

      ```bash
      # owner/repo の取得と検証（認証/権限エラー → exit 1）
      if ! OWNER=$(gh repo view --json owner --jq '.owner.login' 2>&1); then
        echo "::error::Failed to get repository owner: $OWNER"
        exit 1
      fi
      if ! REPO=$(gh repo view --json name --jq '.name' 2>&1); then
        echo "::error::Failed to get repository name: $REPO"
        exit 1
      fi

      # PR番号の数値バリデーション（データ不存在 → スキップ）
      if ! [[ "$PR_NUMBER" =~ ^[1-9][0-9]*$ ]]; then
        echo "::warning::Invalid PR number: '$PR_NUMBER'. Skipping thread resolution."
        exit 1
      fi
      ```

    - 未解決スレッドの取得（失敗時は一時的API障害の可能性 → warning で続行）:

      ```bash
      THREADS=""
      QUERY_SUCCESS=true
      if ! THREADS=$(gh api graphql -f query="
      {
        repository(owner: \"$OWNER\", name: \"$REPO\") {
          pullRequest(number: $PR_NUMBER) {
            reviewThreads(first: 100) {
              # 注意: 100スレッドを超える場合はページネーション未対応
              nodes {
                id
                isResolved
              }
            }
          }
        }
      }" --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id' 2>&1); then
        QUERY_SUCCESS=false
        # 認証エラー（401/403）→ 即停止
        if echo "$THREADS" | grep -qE '401|403|authentication|forbidden'; then
          echo "::error::Authentication/permission error: $THREADS"
          exit 1
        fi
        # 一時的障害 → warning でスキップ
        echo "::warning::Failed to query review threads: $THREADS"
        echo "Skipping thread resolution due to API error"
        THREADS=""
      fi
      ```

    - 失敗カウンターで全件失敗を検知（全件失敗は認証エラーの可能性 → exit 1）:

      ```bash
      if [ -z "$THREADS" ]; then
        if [ "$QUERY_SUCCESS" = true ]; then
          echo "No unresolved threads to resolve. Skipping."
        else
          echo "::warning::Skipping resolve due to query failure."
        fi
      else
        RESOLVED=0
        FAILED=0
        while IFS= read -r THREAD_ID; do
          [ -z "$THREAD_ID" ] && continue
          # THREAD_ID のフォーマット検証（GitHub thread IDは英数字・_・-のみ）
          if ! [[ "$THREAD_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
            echo "::warning::Invalid thread ID format: $THREAD_ID"
            FAILED=$((FAILED + 1))
            continue
          fi
          # 個別失敗は一時的障害の可能性 → warning で続行
          # Windows Git Bash では GraphQL変数($threadId)が正しく渡らないため、
          # IDをmutationクエリに直接埋め込む
          if ! ERROR=$(gh api graphql -f query="
          mutation {
            resolveReviewThread(input: { threadId: \"$THREAD_ID\" }) {
              thread { isResolved }
            }
          }" 2>&1); then
            FAILED=$((FAILED + 1))
            echo "::warning::Failed to resolve thread $THREAD_ID: $ERROR"
          else
            RESOLVED=$((RESOLVED + 1))
          fi
        done <<< "$THREADS"

        echo "Resolved: $RESOLVED, Failed: $FAILED"
        # 全件失敗は認証/権限エラーの可能性 → exit 1
        if [ "$RESOLVED" -eq 0 ] && [ "$FAILED" -gt 0 ]; then
          echo "::error::All thread resolutions failed. Possible causes:"
          echo "::error::- Insufficient token permissions"
          echo "::error::- API rate limit exceeded"
          echo "::error::- GraphQL query syntax error"
          exit 1
        fi
      fi
      ```

13. prt レビュー評価（Issue #265 への記録）:

    レビュー指摘に prt（PR Review Toolkit）の自動レビューコメントが含まれる場合、
    指摘の精度を評価し、**明らかに間違っている指摘や精度に問題がある指摘**があれば
    Issue #265 にコメントとして記録する。

    **評価観点**:
    - 技術的な分析が正確か（例: `set -e` との相互作用の見落とし等）
    - 指摘の文脈理解が適切か（例: CI/CD ワークフローのテスト戦略）
    - 信頼度スコアと実際の妥当性が一致しているか
    - 改善提案が実用的か

    **コメント形式**:
    ```text
    ## PR #番号 レビュー評価メモ

    ### エージェント名（件数）
    **問題の種類**: 具体的な説明
    - 問題のある記述の引用
    - 正しい分析・判断の説明
    **評価**: 総合コメント
    ```

    **注意**:
    - 全て妥当な指摘だった場合はコメント不要（問題がある場合のみ記録）
    - copilot の指摘も含めて評価し、ツール間の精度比較情報を含める

14. 修正をコミット & push:
    - コミットメッセージ:
      - 指摘対応のみ: `fix: レビュー指摘対応 (PR #番号)`
      - 実装継続: `feat: 実装内容の説明 (PR #番号)`
    - 変更内容を箇条書きでコミットメッセージに含める
    - ドキュメント更新がある場合はコミットメッセージにその旨も含める

15. 対応結果のサマリーを表示（prt 評価を Issue #265 に投稿した場合はその旨も報告）
