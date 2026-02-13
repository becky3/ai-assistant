# auto-fix: レビュー指摘対応プロンプト

<!-- markdownlint-disable MD014 MD031 -->

PR #{{PR_NUMBER}} のレビュー指摘に対応してください。
以下の手順を順番に全て実行すること。途中で停止しないこと。

## ステップ 1/9: PR情報の確認

```bash
gh pr view {{PR_NUMBER}} --json title,body,headRefName,baseRefName
gh pr view {{PR_NUMBER}} --json files --jq '.files[].path'
gh pr diff {{PR_NUMBER}}
```

## ステップ 2/9: 未解決レビューコメントの取得

まず owner/repo を取得する:

```bash
OWNER=$(gh repo view --json owner --jq '.owner.login')
REPO=$(gh repo view --json name --jq '.name')
echo "Owner: $OWNER, Repo: $REPO"
```

取得した OWNER, REPO を使って GraphQL で未解決スレッドを抽出:

```bash
gh api graphql -f query="
{
  repository(owner: \"$OWNER\", name: \"$REPO\") {
    pullRequest(number: {{PR_NUMBER}}) {
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
" --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .comments.nodes[0] | {author: .author.login, path, line, body}'
```

未解決の指摘がない場合は「未解決の指摘はありません」と表示して終了。

## ステップ 3/9: 関連仕様書の確認と修正実施

- PRの目的に対応する `docs/specs/` の仕様書を特定して読む
- 各指摘について:
  - 指摘対象のファイル・行を読み、コンテキストを理解する
  - 妥当な指摘かどうかを判断する
  - 妥当な指摘に対して修正を実施する
  - 妥当でない場合はスキップ理由を記録する

## ステップ 4/9: テスト実行

`/test-run` スキルを実行してテスト・リント・型チェック・Markdownチェックを一括実行する。

失敗があれば修正して再実行。全て通過してから次へ進む。

Skill が利用できない場合は以下を直接実行する:

```bash
uv run pytest && uv run ruff check src/ tests/ && uv run mypy src/
npx markdownlint-cli2@0.20.0 "CLAUDE.md" "docs/**/*.md" "*.md" ".claude/**/*.md"
```

Markdown のみの変更の場合、pytest / ruff / mypy はスキップ可（markdownlint のみ実行）。

## ステップ 5/9: コードレビュー

`/code-review` スキルを実行して変更コードのセルフレビューを実施する。
Critical/Warning の指摘があれば修正する。

Skill が利用できない場合は `git diff` で変更差分を確認し、以下の観点でセルフレビューする:

- テスト名と実装の整合性
- エラーハンドリング（except pass の有無）
- バリデーション漏れ（境界値: 0, 負数, 空文字列）
- セキュリティ（コマンドインジェクション、XSS等）

## ステップ 6/9: ドキュメント整合性チェック

`docs/` や `CLAUDE.md` に変更がある場合、`/doc-review` スキルを実行してドキュメントレビューを実施する。
ドキュメント変更がなければスキップ可。

Skill が利用できない場合は、修正内容が以下のドキュメントの記述と矛盾しないか手動で確認し、必要なら更新する:

- `docs/specs/` — 仕様・受け入れ条件に影響する変更の場合
- `CLAUDE.md` — 開発ルール・プロジェクト構造に影響する場合

## ステップ 7/9: PRに対応コメント投稿

`gh pr comment {{PR_NUMBER}}` で対応状況を投稿:

- 各指摘に対して「対応済み ✅」「別Issue化 ⏸️」「対応不要（理由）❌」を明記

## ステップ 8/9: 対応済みスレッドの resolve

対応済みと判断したスレッドのみ resolveReviewThread mutation で resolve する。
以下のエラーハンドリング方針に従うこと:

- owner/repo 取得失敗 → エラーログを出力して resolve をスキップ
- 認証エラー（401/403） → エラーログを出力して即停止
- 一時的API障害（個別resolve失敗） → warning でログし次のスレッドに継続
- 全件resolve失敗 → 認証/権限エラーの可能性があるためエラーログを出力

```bash
PR_NUMBER={{PR_NUMBER}}

# owner/repo の取得と検証（環境情報付きエラーログ）
if ! OWNER=$(gh repo view --json owner --jq '.owner.login' 2>&1); then
  echo "::error::Failed to get repository owner: $OWNER (GH_REPO=${GH_REPO:-unset}, GH_TOKEN length=${#GH_TOKEN})"
  exit 1
fi
if ! REPO=$(gh repo view --json name --jq '.name' 2>&1); then
  echo "::error::Failed to get repository name: $REPO (GH_REPO=${GH_REPO:-unset}, OWNER=$OWNER)"
  exit 1
fi

# 未解決スレッドIDの取得
THREADS=""
QUERY_SUCCESS=true
if ! THREADS=$(gh api graphql -f query="
{
  repository(owner: \"$OWNER\", name: \"$REPO\") {
    pullRequest(number: $PR_NUMBER) {
      reviewThreads(first: 100) {
        nodes {
          id
          isResolved
        }
      }
    }
  }
}" --jq '.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved == false) | .id' 2>&1); then
  QUERY_SUCCESS=false
  # GraphQLエラー形式を確認してからフォールバック
  if echo "$THREADS" | jq -e '.errors' > /dev/null 2>&1; then
    ERROR_TYPE=$(echo "$THREADS" | jq -r '.errors[0].type // "UNKNOWN"')
    ERROR_MSG=$(echo "$THREADS" | jq -r '.errors[0].message // "No message"')
    if [ "$ERROR_TYPE" = "FORBIDDEN" ] || [ "$ERROR_TYPE" = "UNAUTHORIZED" ]; then
      echo "::error::GraphQL auth error (type=$ERROR_TYPE): $ERROR_MSG"
      exit 1
    fi
    echo "::warning::GraphQL error (type=$ERROR_TYPE): $ERROR_MSG"
  elif echo "$THREADS" | grep -qE '401|403|authentication|forbidden'; then
    echo "::error::Authentication/permission error: $THREADS"
    exit 1
  else
    echo "::warning::Failed to query review threads: $THREADS"
  fi
  THREADS=""
fi

# スレッドの resolve（失敗カウンター付き、エラー種別分類）
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
    if ! ERROR=$(gh api graphql -f query='
    mutation($threadId: ID!) {
      resolveReviewThread(input: { threadId: $threadId }) {
        thread { isResolved }
      }
    }' -f threadId="$THREAD_ID" 2>&1); then
      FAILED=$((FAILED + 1))
      # エラー種別の推定と分類
      if echo "$ERROR" | jq -e '.errors' > /dev/null 2>&1; then
        ERR_TYPE=$(echo "$ERROR" | jq -r '.errors[0].type // "UNKNOWN"')
        ERR_MSG=$(echo "$ERROR" | jq -r '.errors[0].message // "No message"')
        echo "::warning::Failed to resolve thread $THREAD_ID: [GraphQL $ERR_TYPE] $ERR_MSG"
      elif echo "$ERROR" | grep -qE '401|403|authentication|forbidden'; then
        echo "::warning::Failed to resolve thread $THREAD_ID: [AUTH] $ERROR"
      elif echo "$ERROR" | grep -qE 'not found|NOT_FOUND|Could not resolve'; then
        echo "::warning::Failed to resolve thread $THREAD_ID: [NOT_FOUND] $ERROR"
      else
        echo "::warning::Failed to resolve thread $THREAD_ID: [API_ERROR] $ERROR"
      fi
    else
      RESOLVED=$((RESOLVED + 1))
    fi
  done <<< "$THREADS"

  echo "Resolved: $RESOLVED, Failed: $FAILED"
  if [ "$RESOLVED" -eq 0 ] && [ "$FAILED" -gt 0 ]; then
    echo "::error::All thread resolutions failed ($FAILED threads). Possible auth/permission issue."
    exit 1
  fi
fi
```

## ステップ 9/9: コミット & push

```bash
git add -A
if [ -n "$(git status --porcelain)" ]; then
  git diff --cached --stat
  git commit -m "fix: レビュー指摘対応 (PR #{{PR_NUMBER}})"
  git push origin HEAD
else
  echo "No changes to commit. Skipping."
fi
```
