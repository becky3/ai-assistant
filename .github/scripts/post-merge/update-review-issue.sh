#!/usr/bin/env bash
# Post Merge — レビューIssue更新スクリプト
#
# auto:review-batch ラベルの Open Issue を検索し、
# 既存あり → Issue body に追記、なし → 新規作成 + ピン留め
#
# 必須環境変数:
#   PR_NUMBER       — マージされたPR番号
#   PR_TITLE        — PRタイトル
#   RUNTIME_FILES   — 実行テスト対象ファイル一覧 (multiline)
#   GH_TOKEN        — GitHub トークン
#   GH_REPO         — リポジトリ (owner/repo)
#
# エラー方針: Issue操作失敗 → warning で続行

# _common.sh を auto-fix/ から相対パスで source
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../auto-fix/_common.sh"

require_env PR_NUMBER PR_TITLE RUNTIME_FILES
validate_pr_number "$PR_NUMBER"

# --- チェックリスト生成 ---
# ファイルパターンからテンプレート生成（仕様書ACの自動抽出は複雑すぎるため行わない）
generate_checklist() {
  local files="$1"
  local checklist=""
  local has_src=false
  local has_config=false
  local has_mcp=false
  local has_pyproject=false

  while IFS= read -r file; do
    case "$file" in
      src/*)       has_src=true ;;
      config/*)    has_config=true ;;
      mcp-servers/*) has_mcp=true ;;
      pyproject.toml) has_pyproject=true ;;
    esac
  done <<< "$files"

  if [ "$has_src" = true ]; then
    checklist+=$'- [ ] Bot起動確認（`uv run python -m src.main`）\n- [ ] エラーログに異常がないこと\n'
  fi

  if [ "$has_config" = true ]; then
    checklist+=$'- [ ] 設定変更の動作確認\n'
  fi

  if [ "$has_mcp" = true ]; then
    checklist+=$'- [ ] MCPサーバー起動確認\n'
  fi

  if [ "$has_pyproject" = true ]; then
    checklist+=$'- [ ] 依存パッケージの動作確認（`uv sync`）\n'
  fi

  echo "$checklist"
}

# 今日の日付（失敗時はフォールバック）
DATE=$(date -u +"%Y-%m-%d") || DATE="unknown-date"

# チェックリスト生成（コマンド置換内のエラーは伝播しないためフォールバック）
CHECKLIST=$(generate_checklist "$RUNTIME_FILES") || CHECKLIST=""

# ファイル一覧を整形
FILE_LIST=""
while IFS= read -r file; do
  if [ -n "$file" ]; then
    FILE_LIST="${FILE_LIST}\`${file}\`, "
  fi
done <<< "$RUNTIME_FILES"
# 末尾のカンマとスペースを除去
FILE_LIST="${FILE_LIST%, }"

# 追記するセクション
NEW_SECTION="## PR #${PR_NUMBER}: ${PR_TITLE} (${DATE})

- 変更: ${FILE_LIST}
${CHECKLIST}"

# --- 既存 review-batch Issue を検索 ---
EXISTING_ISSUE=""
if ! EXISTING_ISSUE=$(gh issue list --label "auto:review-batch" --state open --json number --jq '.[0].number // empty' 2>&1); then
  echo "::warning::Failed to search for review-batch issue: $EXISTING_ISSUE"
  EXISTING_ISSUE=""
fi

# 数値バリデーション（APIレスポンス異常時の防御）
if [ -n "$EXISTING_ISSUE" ] && ! validate_numeric "$EXISTING_ISSUE" "EXISTING_ISSUE"; then
  echo "::warning::Unexpected issue number format: '$EXISTING_ISSUE'"
  EXISTING_ISSUE=""
fi

if [ -n "$EXISTING_ISSUE" ]; then
  # --- 既存Issueに追記 ---
  echo "Found existing review-batch issue: #$EXISTING_ISSUE"

  CURRENT_BODY=""
  if ! CURRENT_BODY=$(gh issue view "$EXISTING_ISSUE" --json body --jq '.body' 2>&1); then
    echo "::warning::Failed to get issue body: $CURRENT_BODY. Trying comment fallback."
    # フォールバック: Issue body を取得できない場合はコメントで追記
    if ! gh_safe_warning gh issue comment "$EXISTING_ISSUE" --body "$NEW_SECTION"; then
      echo "::warning::Comment fallback also failed. Please manually update review-batch issue #$EXISTING_ISSUE with PR #$PR_NUMBER changes."
    fi
    exit 0
  fi

  UPDATED_BODY="${CURRENT_BODY}

---

${NEW_SECTION}"

  if ! gh_safe_warning gh issue edit "$EXISTING_ISSUE" --body "$UPDATED_BODY"; then
    echo "::warning::Failed to update issue body. Trying comment fallback."
    if gh_safe_warning gh issue comment "$EXISTING_ISSUE" --body "$NEW_SECTION"; then
      echo "Added comment to review-batch issue #$EXISTING_ISSUE (body update failed, used comment fallback)"
    else
      echo "::warning::Comment fallback also failed. Please manually update review-batch issue #$EXISTING_ISSUE with PR #$PR_NUMBER changes."
    fi
  else
    echo "Updated review-batch issue #$EXISTING_ISSUE"
  fi
else
  # --- 新規Issue作成 + ピン留め ---
  echo "No existing review-batch issue found. Creating new one."

  ISSUE_BODY="# 自動マージレビュー

自動マージされたPRのうち、実行テストが必要なものの一覧です。
確認完了後、このIssueをクローズしてください。

---

${NEW_SECTION}"

  NEW_ISSUE_URL=""
  if ! NEW_ISSUE_URL=$(gh issue create \
    --title "自動マージレビュー" \
    --body "$ISSUE_BODY" \
    --label "auto:review-batch" 2>&1); then
    echo "::warning::Failed to create review-batch issue: $NEW_ISSUE_URL"
    exit 0
  fi

  # URL形式バリデーション（stderr混入やエラーメッセージの防御）
  if [[ "$NEW_ISSUE_URL" != https://github.com/* ]]; then
    echo "::warning::Unexpected issue URL format: $NEW_ISSUE_URL"
    exit 0
  fi

  # Issue番号を抽出（URLの末尾の数字）
  NEW_ISSUE_NUM="${NEW_ISSUE_URL##*/}"

  # 数値バリデーション（stderr混入時の防御）
  if ! validate_numeric "$NEW_ISSUE_NUM" "NEW_ISSUE_NUM"; then
    echo "::warning::Could not extract issue number from: $NEW_ISSUE_URL"
    exit 0
  fi

  echo "Created review-batch issue: #$NEW_ISSUE_NUM ($NEW_ISSUE_URL)"

  # ピン留め（ベストエフォート）
  if ! gh_safe_warning gh issue pin "$NEW_ISSUE_NUM"; then
    echo "::warning::Failed to pin issue #$NEW_ISSUE_NUM (non-critical)"
  else
    echo "Pinned review-batch issue #$NEW_ISSUE_NUM"
  fi
fi
