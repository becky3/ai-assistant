#!/usr/bin/env bash
# check-review-result.sh — GraphQL APIでunresolvedレビュースレッド数を取得（最大5回リトライ）
#
# 入力: 環境変数 PR_NUMBER, GITHUB_REPOSITORY
# 出力: $GITHUB_OUTPUT に has_issues を書き出し
# エラー方針: 全リトライ失敗 → exit 1

set -euo pipefail
source "$(dirname "$0")/_common.sh"

require_env PR_NUMBER GITHUB_REPOSITORY GITHUB_OUTPUT

REPO_OWNER="${GITHUB_REPOSITORY%%/*}"
REPO_NAME="${GITHUB_REPOSITORY#*/}"

# GraphQL で unresolved レビュースレッドを検索（最大5回、10秒間隔）
UNRESOLVED_COUNT=""
FIRST_ERROR=""
LAST_ERROR=""
for i in $(seq 1 5); do
  if UNRESOLVED_COUNT=$(gh api graphql -f query='
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes {
              isResolved
            }
          }
        }
      }
    }
  ' -f owner="${REPO_OWNER}" -f name="${REPO_NAME}" -F number="$PR_NUMBER" \
    --jq '
      .data.repository.pullRequest as $pr |
      if $pr == null then
        error("PR not found")
      else
        [$pr.reviewThreads.nodes[] | select(.isResolved == false)] | length
      end
    ' 2>&1); then
    # 数値バリデーション（リトライループ内で実行）
    if ! validate_numeric "$UNRESOLVED_COUNT" "unresolved count"; then
      echo "::warning::Invalid response format (attempt $i/5): '$UNRESOLVED_COUNT'. Retrying..."
      if [ -z "$FIRST_ERROR" ]; then
        FIRST_ERROR="$UNRESOLVED_COUNT"
      fi
      LAST_ERROR="$UNRESOLVED_COUNT"
      UNRESOLVED_COUNT=""
      if [ "$i" -lt 5 ]; then
        sleep 10
        continue
      else
        echo "::error::Failed to get valid response after 5 attempts."
        echo "::error::First error: $FIRST_ERROR"
        echo "::error::Last error: $LAST_ERROR"
        exit 1
      fi
    fi
    # 成功 - エラー記録をクリア
    FIRST_ERROR=""
    LAST_ERROR=""
    break
  fi
  echo "::warning::Failed to query review threads (attempt $i/5): $UNRESOLVED_COUNT"
  if [ -z "$FIRST_ERROR" ]; then
    FIRST_ERROR="$UNRESOLVED_COUNT"
  fi
  LAST_ERROR="$UNRESOLVED_COUNT"
  if [ "$i" -lt 5 ]; then sleep 10; fi
done

# リトライループ内でバリデーション済み。この時点で UNRESOLVED_COUNT は必ず有効な数値

echo "Unresolved review threads: $UNRESOLVED_COUNT"

if [ "$UNRESOLVED_COUNT" -gt 0 ]; then
  output "has_issues" "true"
  echo "Review result: $UNRESOLVED_COUNT unresolved thread(s) found"
else
  output "has_issues" "false"
  echo "Review result: No unresolved threads"
fi
