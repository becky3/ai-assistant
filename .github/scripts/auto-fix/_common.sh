#!/usr/bin/env bash
# Auto Fix — 共通エラーハンドリング関数
#
# 使い方 (ローカル実行時):
#   source "$(dirname "$0")/_common.sh"
# 使い方 (GitHub Actions ワークフロー内):
#   source "$GITHUB_WORKSPACE/.github/scripts/auto-fix/_common.sh"
#
# エラーハンドリング方針（auto-fix.yml 冒頭と対応）:
#   gh_safe          → 失敗時 ::error:: + exit 1（認証/権限/必須データ取得）
#   gh_safe_warning  → 失敗時 ::warning::（一時的API障害、非クリティカル）
#   gh_best_effort   → 失敗時 ::error:: のみ（エラーハンドラ内、ベストエフォート）

set -euo pipefail

# gh_safe: コマンド実行し、失敗時は ::error:: + exit 1
# 用途: 認証/権限エラー、必須データの取得失敗
# 使用例: RESULT=$(gh_safe gh pr view "$PR_NUMBER" --json body --jq '.body // ""')
gh_safe() {
  local output
  local exit_code=0
  output=$("$@" 2>&1) || exit_code=$?
  if [ "$exit_code" -ne 0 ]; then
    echo "::error::Command failed (exit $exit_code): $* — $output"
    exit 1
  fi
  echo "$output"
}

# gh_safe_warning: コマンド実行し、失敗時は ::warning:: + return 1
# 用途: 一時的API障害で続行可能なケース、非クリティカルな操作
# 使用例: if ! RESULT=$(gh_safe_warning gh issue edit "$NUM" --remove-label "label"); then ...
gh_safe_warning() {
  local output
  if ! output=$("$@" 2>&1); then
    echo "::warning::Command failed (non-critical): $* — $output" >&2
    return 1
  fi
  echo "$output"
}

# gh_best_effort: コマンド実行し、失敗時は ::error:: のみ（exit しない）
# 用途: エラーハンドラ内のベストエフォート処理（ラベル付与、コメント投稿等）
# 使用例: gh_best_effort gh issue edit "$NUM" --add-label "auto:failed"
gh_best_effort() {
  local output
  if ! output=$("$@" 2>&1); then
    echo "::error::Command failed (best-effort): $* — $output — manual intervention may be required" >&2
    return 1
  fi
  echo "$output"
}

# gh_comment: PRコメント投稿のラッパー（非クリティカル: 失敗してもワークフローは続行）
# 用途: 成功/失敗/ドライラン等のPRコメント投稿
# 使用例: gh_comment "$PR_NUMBER" "## auto-fix: 自動マージ完了 ..."
# 引数: $1 = PR番号, $2 = コメント本文
gh_comment() {
  local pr_number="$1"
  local body="$2"

  if [ -z "$pr_number" ] || [ -z "$body" ]; then
    echo "::error::gh_comment: Missing required arguments (pr_number='$pr_number')" >&2
    return 1
  fi

  local output
  if ! output=$(gh pr comment "$pr_number" --body "$body" 2>&1); then
    echo "::warning::Failed to post PR comment to #$pr_number: $output" >&2
    return 1
  fi
}

# require_env: 必須環境変数の存在を検証
# 用途: スクリプト冒頭で必須パラメータを検証
# 使用例: require_env PR_NUMBER GITHUB_OUTPUT
require_env() {
  local missing=()
  for var in "$@"; do
    if ! declare -p "$var" >/dev/null 2>&1; then
      missing+=("$var")
    elif [ -z "${!var}" ]; then
      missing+=("$var (defined but empty)")
    fi
  done
  if [ ${#missing[@]} -gt 0 ]; then
    echo "::error::Missing or empty required environment variables: ${missing[*]}" >&2
    exit 1
  fi
}

# output: $GITHUB_OUTPUT にキー=値を書き出し
# 用途: ステップ出力の設定
# 使用例: output "number" "$PR_NUMBER"
output() {
  local key="$1"
  local value="$2"
  echo "$key=$value" >> "$GITHUB_OUTPUT"
}

# validate_pr_number: PR番号が正の整数かどうかを検証
# 用途: PR番号の入力バリデーション（0や負数を拒否）
# 使用例: if ! validate_pr_number "$PR_NUMBER" "PR_NUMBER_FROM_EVENT"; then exit 1; fi
# 引数: $1 = 値, $2 = 変数名（ログ用、省略可）
validate_pr_number() {
  local value="$1"
  local name="${2:-PR number}"
  if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "::error::Invalid $name: '$value'" >&2
    return 1
  fi
}

# validate_numeric: 値が数値かどうかを検証
# 用途: API応答の数値バリデーション
# 使用例: if ! validate_numeric "$COUNT" "loop count"; then COUNT=0; fi
# 引数: $1 = 値, $2 = 変数名（ログ用）
validate_numeric() {
  local value="$1"
  local name="${2:-value}"
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "::warning::Invalid $name: '$value' (expected numeric)" >&2
    return 1
  fi
}
