#!/usr/bin/env bash
# Post Merge — 変更ファイル分類スクリプト
#
# PRの変更ファイル一覧を取得し、実行テストが必要かどうかを判定する。
#
# 必須環境変数:
#   PR_NUMBER       — PR番号
#   GH_TOKEN        — GitHub トークン
#   GH_REPO         — リポジトリ (owner/repo)
#   GITHUB_OUTPUT   — GitHub Actions 出力ファイル
#
# 出力:
#   needs_runtime_test — true/false
#   runtime_files      — 実行テスト対象ファイル一覧 (multiline)
#
# エラー方針: 取得失敗時は needs_runtime_test=false（安全側に倒す）

# _common.sh を auto-fix/ から相対パスで source
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../auto-fix/_common.sh"

require_env PR_NUMBER GITHUB_OUTPUT
validate_pr_number "$PR_NUMBER"

# PR の変更ファイル一覧を取得
FILES=""
if ! FILES=$(gh pr view "$PR_NUMBER" --json files --jq '.files[].path' 2>&1); then
  echo "::warning::Failed to get PR files: $FILES. Assuming no runtime test needed."
  output "needs_runtime_test" "false"
  output "runtime_files" ""
  exit 0
fi

if [ -z "$FILES" ]; then
  echo "::notice::No files changed in PR #$PR_NUMBER"
  output "needs_runtime_test" "false"
  output "runtime_files" ""
  exit 0
fi

echo "Changed files:"
echo "$FILES"

# 実行テスト対象パターンにマッチするファイルを抽出
RUNTIME_FILES=""
while IFS= read -r file; do
  case "$file" in
    src/*|config/*|mcp-servers/*|pyproject.toml)
      if [ -n "$RUNTIME_FILES" ]; then
        RUNTIME_FILES="$RUNTIME_FILES"$'\n'"$file"
      else
        RUNTIME_FILES="$file"
      fi
      ;;
  esac
done <<< "$FILES"

if [ -n "$RUNTIME_FILES" ]; then
  echo ""
  echo "Runtime test required for:"
  echo "$RUNTIME_FILES"
  output "needs_runtime_test" "true"

  # multiline output
  {
    echo "runtime_files<<RUNTIME_FILES_EOF"
    echo "$RUNTIME_FILES"
    echo "RUNTIME_FILES_EOF"
  } >> "$GITHUB_OUTPUT"
else
  echo ""
  echo "No runtime-affecting files changed. Runtime test not required."
  output "needs_runtime_test" "false"
  output "runtime_files" ""
fi
