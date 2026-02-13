#!/usr/bin/env bash
# remove-label.sh — PR本文からリンクIssueを抽出し、auto-implement ラベルを除去
#
# 入力: 環境変数 PR_NUMBER
# 出力: なし（副作用のみ）
# エラー方針: ラベル未存在 → notice で続行、API失敗 → warning で続行

set -euo pipefail
source "$(dirname "$0")/_common.sh"

require_env PR_NUMBER

# PRのbodyから "Closes #N" パターンでIssue番号を抽出
if ! PR_BODY=$(gh pr view "$PR_NUMBER" --json body --jq '.body // ""' 2>&1); then
  echo "::error::Failed to fetch PR body: $PR_BODY"
  exit 1
fi

# 複数のCloses/Fixes/Resolves パターンに対応（大文字小文字不問）
# grep -P（PCRE）は ubuntu-latest で未対応の場合があるため -E（ERE）を使用
ISSUE_NUMBERS=$(echo "$PR_BODY" | grep -ioE '(closes|fixes|resolves)\s+#[0-9]+' | grep -oE '[0-9]+') || GREP_EXIT=$?
GREP_EXIT=${GREP_EXIT:-0}
if [ "$GREP_EXIT" -eq 1 ]; then
  # grep終了コード1 = マッチなし（正常）
  ISSUE_NUMBERS=""
elif [ "$GREP_EXIT" -ge 2 ]; then
  echo "::error::grep failed with exit code $GREP_EXIT while parsing PR body"
  exit 1
fi

if [ -z "$ISSUE_NUMBERS" ]; then
  echo "::notice::No linked issue found in PR body. Skipping label removal."
else
  while IFS= read -r ISSUE_NUMBER; do
    [ -z "$ISSUE_NUMBER" ] && continue
    echo "Removing auto-implement label from Issue #$ISSUE_NUMBER"
    # ラベル除去を試行し、エラー種別を区別（冪等性）
    if ! LABEL_ERR=$(gh issue edit "$ISSUE_NUMBER" --remove-label "auto-implement" 2>&1); then
      if echo "$LABEL_ERR" | grep -qi "not found\|does not have"; then
        echo "::notice::Label 'auto-implement' not found on Issue #$ISSUE_NUMBER or already removed. Skipping."
      else
        echo "::warning::Failed to remove label from Issue #$ISSUE_NUMBER: $LABEL_ERR"
      fi
    fi
  done <<< "$ISSUE_NUMBERS"
fi
