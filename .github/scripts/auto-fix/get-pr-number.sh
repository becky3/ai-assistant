#!/usr/bin/env bash
# get-pr-number.sh — イベントからPR番号を特定
#
# 入力:
#   PR_NUMBER_FROM_EVENT — pull_request(labeled) トリガー時のPR番号（設定されていれば優先使用）
#   PULL_REQUESTS_JSON — workflow_run トリガー時の pull_requests 配列
#   HEAD_BRANCH — workflow_run トリガー時のフォールバック用ブランチ名（必須ではない）
# 出力: $GITHUB_OUTPUT に number, skip を書き出し
# エラー方針: PR未発見 → skip=true、API失敗/不正値 → exit 1

set -euo pipefail
source "$(dirname "$0")/_common.sh"

require_env GITHUB_OUTPUT

# pull_request(labeled) トリガー: イベントから直接PR番号を取得
if [ -n "${PR_NUMBER_FROM_EVENT:-}" ]; then
  if ! validate_pr_number "$PR_NUMBER_FROM_EVENT" "PR_NUMBER_FROM_EVENT"; then
    exit 1
  fi
  output "number" "$PR_NUMBER_FROM_EVENT"
  output "skip" "false"
  echo "PR number (from event): $PR_NUMBER_FROM_EVENT"
  exit 0
fi

# workflow_run トリガー: pull_requests 配列からPR番号を取得
require_env PULL_REQUESTS_JSON

# workflow_run.pull_requests 配列からPR番号を取得
PR_NUMBER=$(echo "$PULL_REQUESTS_JSON" | jq -r '.[0].number // empty')

# pull_requests が空の場合、ブランチ名から検索
if [ -z "$PR_NUMBER" ]; then
  if [ -z "${HEAD_BRANCH:-}" ]; then
    echo "::warning::PR not found in pull_requests and HEAD_BRANCH is empty. Skipping."
    output "skip" "true"
    exit 0
  fi
  if ! PR_NUMBER=$(gh pr list --head "$HEAD_BRANCH" --json number --jq '.[0].number // empty'); then
    echo "::error::Failed to search PR by branch name: $HEAD_BRANCH"
    exit 1
  fi
fi

if [ -z "$PR_NUMBER" ]; then
  echo "::notice::No PR found for this workflow run. Skipping."
  output "skip" "true"
  exit 0
fi

# 数値バリデーション
if ! validate_pr_number "$PR_NUMBER"; then
  exit 1
fi

output "number" "$PR_NUMBER"
output "skip" "false"
echo "PR number: $PR_NUMBER"
