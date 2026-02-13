#!/usr/bin/env bash
# Handle errors — エラー時の auto:failed ラベル付与 + PRコメント（フォールバック付き）
#
# 入力（環境変数）:
#   PR_NUMBER           — 対象PR番号
#   ACTIONS_URL         — Actions ログへのURL
#   COMMON_SCRIPT_PATH  — _common.sh のフルパス
#   GH_TOKEN            — GitHub トークン（env経由で gh CLI が自動参照）
#   GH_REPO             — 対象リポジトリ（owner/repo）
#
# 出力: ラベル付与 + PRコメント（副作用、ベストエフォート）
#
# エラー方針: 全処理がベストエフォート（エラーハンドラ自体は失敗しない）
#
# 注意: このスクリプトはYAML側のファイル存在チェックで呼ばれる。
#   checkout失敗時はスクリプト自体が存在しないため、YAML側フォールバックが実行される。

set -euo pipefail

# _common.sh の source（ベストエフォート）
COMMON_SCRIPT="${COMMON_SCRIPT_PATH:-}"
SOURCED=false
# COMMON_SCRIPT is dynamically resolved at runtime
# shellcheck disable=SC1090
if [ -n "$COMMON_SCRIPT" ] && [ -f "$COMMON_SCRIPT" ]; then
  if ! SYNTAX_ERR=$(bash -n "$COMMON_SCRIPT" 2>&1); then
    echo "::error::Syntax error in $COMMON_SCRIPT: $SYNTAX_ERR — falling back"
  elif ! source "$COMMON_SCRIPT"; then
    echo "::error::Failed to source $COMMON_SCRIPT — falling back"
  else
    SOURCED=true
  fi
fi

if [ -z "${PR_NUMBER:-}" ]; then
  echo "::warning::PR_NUMBER is not set; skipping error handling"
  exit 0
fi
if [ -z "${ACTIONS_URL:-}" ]; then
  echo "::warning::ACTIONS_URL is not set; skipping error handling"
  exit 0
fi

ERROR_COMMENT="## auto-fix: エラー発生

自動修正処理中にエラーが発生しました。\`auto:failed\` ラベルを付与して自動処理を停止します。

**次のアクション**: [Actions ログ]($ACTIONS_URL) を確認し、問題を解消してください。
対応完了後、\`auto:failed\` を除去して \`/review\` コメントを投稿すると再開できます。"

if [ "$SOURCED" = true ]; then
  gh_best_effort gh issue edit "$PR_NUMBER" --add-label "auto:failed" || true
  gh_comment "$PR_NUMBER" "$ERROR_COMMENT" || true
else
  # フォールバック: 共通関数なしでベストエフォート
  if ! LABEL_ERR=$(gh issue edit "$PR_NUMBER" --add-label "auto:failed" 2>&1); then
    echo "::error::Failed to add auto:failed label: $LABEL_ERR"
  fi
  if ! COMMENT_ERR=$(gh pr comment "$PR_NUMBER" --body "$ERROR_COMMENT" 2>&1); then
    echo "::error::Failed to post error comment: $COMMENT_ERR"
  fi
fi
