#!/usr/bin/env bash
# check-loop-count.sh — PR内のループマーカーコメント数をカウント
#
# 入力: 環境変数 PR_NUMBER, GH_REPO
# 出力: $GITHUB_OUTPUT に loop_count, limit_reached を書き出し
# エラー方針: API失敗/不正値 → デフォルト0で続行

set -euo pipefail
source "$(dirname "$0")/_common.sh"

require_env PR_NUMBER GH_REPO GITHUB_OUTPUT

# auto-fix ループのマーカーコメント数をカウント
# auto-fix.yml が /check-pr 実行前に投稿する「auto-fix: レビュー指摘への自動対応」コメントを対象
if ! LOOP_COUNT=$(gh api "repos/${GH_REPO}/issues/${PR_NUMBER}/comments" \
  --paginate --jq '[.[] | select(.user.login == "github-actions[bot]" and (.body | contains("auto-fix: レビュー指摘への自動対応")))] | length' 2>&1); then
  echo "::warning::Failed to get loop count: $LOOP_COUNT. Defaulting to 0."
  LOOP_COUNT=0
fi

# 数値バリデーション（API応答が不正な場合はデフォルト0で継続）
if ! validate_numeric "$LOOP_COUNT" "loop count"; then
  LOOP_COUNT=0
fi

output "loop_count" "$LOOP_COUNT"
echo "Loop count: $LOOP_COUNT"

if [ "$LOOP_COUNT" -ge 3 ]; then
  output "limit_reached" "true"
  echo "::warning::Loop limit reached ($LOOP_COUNT >= 3)"
else
  output "limit_reached" "false"
fi
