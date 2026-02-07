#!/usr/bin/env bash
# Bot起動スクリプト（重複起動防止付き）
# 仕様: docs/specs/bot-process-guard.md
#
# 使い方:
#   bash scripts/bot_start.sh
#
# 既存プロセスの停止を bot_stop.sh に委譲し、
# 新しいBotを起動する。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- メイン処理 ---

echo "=== Bot起動スクリプト ==="
echo "プロジェクトルート: $PROJECT_ROOT"

# 既存プロセスの停止（bot_stop.sh に委譲）
bash "$SCRIPT_DIR/bot_stop.sh"

# Bot起動
echo "Botを起動します..."
cd "$PROJECT_ROOT"

# uv run で起動（バックグラウンドではなくフォアグラウンド）
# PIDファイルの管理は Python 側の process_guard.py が担当
exec uv run python -m src.main
