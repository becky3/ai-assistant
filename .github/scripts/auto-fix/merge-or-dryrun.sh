#!/usr/bin/env bash
# Merge or dry-run — AUTO_MERGE_ENABLED に応じてマージ実行 or ドライラン通知
#
# 入力（環境変数）:
#   PR_NUMBER           — 対象PR番号
#   AUTO_MERGE_ENABLED  — "true" で実マージ、それ以外でドライラン
#   ACTIONS_URL         — Actions ログへのURL
#   GH_TOKEN            — GitHub トークン（REPO_OWNER_PAT）
#   GH_REPO             — 対象リポジトリ（owner/repo）
#
# 出力: PRコメント投稿（副作用のみ）
#
# エラー方針: マージ失敗 → auto:failed 付与 + exit 1

set -euo pipefail
source "$(dirname "$0")/_common.sh"

require_env PR_NUMBER ACTIONS_URL

if [ -z "$GH_TOKEN" ]; then
  echo "::error::REPO_OWNER_PAT is not set"
  exit 1
fi

AUTO_MERGE_RAW="${AUTO_MERGE_ENABLED:-}"
AUTO_MERGE_LOWER=$(echo "$AUTO_MERGE_RAW" | tr '[:upper:]' '[:lower:]')

# 想定される値: "true", "false", "" (未設定)
if [ -n "$AUTO_MERGE_LOWER" ] && [ "$AUTO_MERGE_LOWER" != "true" ] && [ "$AUTO_MERGE_LOWER" != "false" ]; then
  echo "::warning::Unexpected AUTO_MERGE_ENABLED value: '$AUTO_MERGE_RAW'. Falling back to dry-run mode."
  AUTO_MERGE_LOWER="false"
fi

if [ "$AUTO_MERGE_LOWER" = "true" ]; then
  echo "AUTO_MERGE_ENABLED=true: Executing merge"
  if ! MERGE_ERR=$(gh pr merge "$PR_NUMBER" --merge 2>&1); then
    echo "::error::Merge failed: $MERGE_ERR"
    # マージ失敗時: auto:failed ラベル付与 + PRコメント（事後処理はベストエフォート）
    gh_best_effort gh issue edit "$PR_NUMBER" --add-label "auto:failed" || true
    gh_comment "$PR_NUMBER" "## auto-fix: 自動マージ失敗

マージ条件は全て満たしていましたが、マージコマンドの実行に失敗しました:

\`\`\`
$MERGE_ERR
\`\`\`

**次のアクション**: エラー内容を確認し、手動でマージしてください。

[Actions ログ]($ACTIONS_URL)" || true
    exit 1
  fi

  # マージ成功後のコメント投稿（非クリティカル）
  gh_comment "$PR_NUMBER" "## auto-fix: 自動マージ完了

全てのマージ条件を満たしたため、自動マージを実行しました:
- ✅ レビュー指摘ゼロ
- ✅ CI全チェック通過
- ✅ コンフリクトなし
- ✅ auto:failed ラベルなし

[Actions ログ]($ACTIONS_URL)" || true
else
  echo "AUTO_MERGE_ENABLED=${AUTO_MERGE_RAW:-<unset>}: Dry-run mode"
  # ドライラン時のコメント投稿（非クリティカル）
  gh_comment "$PR_NUMBER" "## auto-fix: マージ判定結果（ドライラン）

全てのマージ条件を満たしています:
- ✅ レビュー指摘ゼロ
- ✅ CI全チェック通過
- ✅ コンフリクトなし
- ✅ auto:failed ラベルなし

**ドライランモード**: \`AUTO_MERGE_ENABLED\` が有効でないため、判定結果の通知のみです。実際のマージは管理者が手動で行ってください。

\`\`\`bash
gh pr merge $PR_NUMBER --merge
\`\`\`

[Actions ログ]($ACTIONS_URL)" || true
fi
