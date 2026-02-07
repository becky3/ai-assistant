#!/usr/bin/env bash
# Bot起動スクリプト（重複起動防止付き）
# 仕様: docs/specs/bot-process-guard.md
#
# 使い方:
#   bash scripts/bot_start.sh
#
# PIDファイル（bot.pid）で既存プロセスを検出し、
# 生存していれば停止してから新しいBotを起動する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/bot.pid"

# --- ヘルパー関数 ---

detect_os() {
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*)
            echo "windows"
            ;;
        Darwin*)
            echo "macos"
            ;;
        *)
            echo "linux"
            ;;
    esac
}

is_process_alive() {
    local pid=$1
    local os_type
    os_type=$(detect_os)

    if [ "$os_type" = "windows" ]; then
        tasklist //FI "PID eq $pid" 2>/dev/null | grep -wq "$pid"
    else
        kill -0 "$pid" 2>/dev/null
    fi
}

kill_process_tree() {
    local pid=$1
    local os_type
    os_type=$(detect_os)

    if [ "$os_type" = "windows" ]; then
        taskkill //F //T //PID "$pid" > /dev/null 2>&1 || true
    else
        # まず SIGTERM で graceful に停止
        kill "$pid" 2>/dev/null || true
        sleep 1
        # まだ生きていれば SIGKILL
        if is_process_alive "$pid"; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
}

# --- メイン処理 ---

echo "=== Bot起動スクリプト ==="
echo "プロジェクトルート: $PROJECT_ROOT"

# 既存プロセスの確認・停止
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")

    # PIDが有効な数値か確認
    if [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
        if is_process_alive "$OLD_PID"; then
            echo "既存プロセス (PID=$OLD_PID) を停止します..."
            kill_process_tree "$OLD_PID"
            echo "既存プロセスを停止しました。"
        else
            echo "PIDファイルのプロセス (PID=$OLD_PID) は既に終了しています。"
        fi
    else
        echo "PIDファイルに不正な値が含まれています: '$OLD_PID'"
    fi

    rm -f "$PID_FILE"
fi

# Bot起動
echo "Botを起動します..."
cd "$PROJECT_ROOT"

# uv run で起動（バックグラウンドではなくフォアグラウンド）
# PIDファイルの管理は Python 側の process_guard.py が担当
exec uv run python -m src.main
