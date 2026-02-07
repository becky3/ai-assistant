#!/usr/bin/env bash
# Bot停止スクリプト（プロセス検証付き）
# 仕様: docs/specs/bot-process-guard.md
#
# 使い方:
#   bash scripts/bot_stop.sh
#
# PIDファイル（bot.pid）からプロセスを特定し、
# Botプロセスであることを検証してから停止する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PID_FILE="$PROJECT_ROOT/bot.pid"

# Bot識別キーワード
BOT_KEYWORD="src.main"

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

is_bot_process() {
    local pid=$1
    local os_type
    os_type=$(detect_os)

    if [ "$os_type" = "windows" ]; then
        # Windows: wmic でコマンドラインを取得
        local cmdline
        cmdline=$(wmic process where "ProcessId=$pid" get CommandLine 2>/dev/null || echo "")
        if echo "$cmdline" | grep -q "$BOT_KEYWORD"; then
            return 0
        fi
    else
        # Unix: ps でコマンドラインを取得
        local cmdline
        cmdline=$(ps -p "$pid" -o args= 2>/dev/null || echo "")
        if echo "$cmdline" | grep -q "$BOT_KEYWORD"; then
            return 0
        fi
    fi

    return 1
}

kill_process_tree() {
    local pid=$1
    local os_type
    os_type=$(detect_os)

    if [ "$os_type" = "windows" ]; then
        taskkill //F //T //PID "$pid" > /dev/null 2>&1 || true
    else
        # まず子プロセスを停止
        pkill -P "$pid" 2>/dev/null || true
        # 親プロセスに SIGTERM で graceful に停止
        kill "$pid" 2>/dev/null || true
        sleep 1
        # まだ生きていれば SIGKILL
        if is_process_alive "$pid"; then
            pkill -9 -P "$pid" 2>/dev/null || true
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
}

# --- メイン処理 ---

echo "=== Bot停止スクリプト ==="

# 1. PIDファイルの存在確認
if [ ! -f "$PID_FILE" ]; then
    echo "Botは起動していません（PIDファイルなし）。"
    exit 0
fi

# 2. PID読み取り
OLD_PID=$(cat "$PID_FILE" 2>/dev/null || echo "")

if ! [[ "$OLD_PID" =~ ^[0-9]+$ ]]; then
    echo "PIDファイルに不正な値が含まれています: '$OLD_PID'"
    rm -f "$PID_FILE"
    exit 1
fi

echo "PIDファイルのプロセス: PID=$OLD_PID"

# 3. プロセス生存確認
if ! is_process_alive "$OLD_PID"; then
    echo "プロセス (PID=$OLD_PID) は既に終了しています。PIDファイルを削除します。"
    rm -f "$PID_FILE"
    exit 0
fi

# 4. プロセス検証（Bot以外をkillしない）
if ! is_bot_process "$OLD_PID"; then
    echo "警告: PID=$OLD_PID はBotプロセスではありません（PID再利用検出）。killをスキップします。"
    rm -f "$PID_FILE"
    exit 0
fi

# 5. プロセスツリーごと停止
echo "Botプロセス (PID=$OLD_PID) を停止します..."
kill_process_tree "$OLD_PID"

# 6. PIDファイル削除・完了報告
rm -f "$PID_FILE"
echo "Botを停止しました。"
