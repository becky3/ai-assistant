#!/usr/bin/env bash
# Post Merge — 次Issue候補ピックアップスクリプト
#
# Open かつ auto:failed なし、auto-implement なしの Issue を検索し、
# 候補をPRコメントとして投稿する。ラベルの自動付与はしない。
#
# 必須環境変数:
#   PR_NUMBER       — マージされたPR番号
#   GH_TOKEN        — GitHub トークン
#   GH_REPO         — リポジトリ (owner/repo)
#
# エラー方針: 全処理ベストエフォート

# _common.sh を auto-fix/ から相対パスで source
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../auto-fix/_common.sh"

require_env PR_NUMBER
validate_pr_number "$PR_NUMBER"

# --- Milestone付きIssueを優先的に検索 ---
# 1. auto:failed / auto-implement ラベルなしの Open Issue を取得
# 2. Milestone付きを優先、番号昇順で最大3件

# まず全候補を取得（auto:failed / auto-implement を除外）
ALL_ISSUES=""
if ! ALL_ISSUES=$(gh issue list \
  --state open \
  --json number,title,labels,milestone \
  --jq '[.[] | select(
    (.labels | map(.name) | index("auto:failed") | not) and
    (.labels | map(.name) | index("auto-implement") | not)
  )] | sort_by(.number)' 2>&1); then
  echo "::warning::Failed to search for candidate issues: $ALL_ISSUES"
  exit 0
fi

if [ "$ALL_ISSUES" = "[]" ] || [ -z "$ALL_ISSUES" ]; then
  echo "No candidate issues found."
  gh_best_effort gh pr comment "$PR_NUMBER" --body "## post-merge: 次Issue候補

候補となるIssueはありません。"
  exit 0
fi

# Milestone付きを優先して最大3件を選定
# jq で milestone ありを先頭に、なしを後ろに並べて先頭3件を取得
CANDIDATES=""
if ! CANDIDATES=$(echo "$ALL_ISSUES" | jq -r '
  [
    (.[] | select(.milestone != null)),
    (.[] | select(.milestone == null))
  ] | .[0:3] | .[] |
  "- #\(.number) \(.title)\(if .milestone then " (Milestone: \(.milestone.title))" else "" end)"
' 2>&1); then
  echo "::warning::Failed to format candidate issues: $CANDIDATES"
  exit 0
fi

if [ -z "$CANDIDATES" ]; then
  echo "No candidate issues after filtering."
  gh_best_effort gh pr comment "$PR_NUMBER" --body "## post-merge: 次Issue候補

候補となるIssueはありません。"
  exit 0
fi

echo "Next issue candidates:"
echo "$CANDIDATES"

# PRコメントに候補一覧を投稿（ラベル付与はしない）
COMMENT_BODY="## post-merge: 次Issue候補

以下のIssueが自動実装の候補です。\`auto-implement\` ラベルを付与すると自動実装が開始されます。

${CANDIDATES}

> このリストは自動生成されたものです。ラベルの付与は管理者が判断してください。"

gh_best_effort gh pr comment "$PR_NUMBER" --body "$COMMENT_BODY"
