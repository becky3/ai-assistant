#!/bin/bash
# Claude Code 通知スクリプト
# 使用法: notify.sh <タイトル> <メッセージ>

TITLE="${1:-通知}"
MESSAGE="${2:-通知}"

# macOS
if command -v osascript &> /dev/null; then
    osascript -e "display notification \"$MESSAGE\" with title \"$TITLE\" sound name \"Glass\""
    exit 0
fi

# Linux
if command -v notify-send &> /dev/null; then
    notify-send "$TITLE" "$MESSAGE" --urgency=normal --icon=dialog-information

    # オプション: 音も鳴らす
    if [ -f /usr/share/sounds/freedesktop/stereo/complete.oga ] && command -v paplay &> /dev/null; then
        paplay /usr/share/sounds/freedesktop/stereo/complete.oga &
    fi
    exit 0
fi

# Windows
if command -v powershell.exe &> /dev/null; then
    powershell.exe -Command "
        Add-Type -AssemblyName System.Windows.Forms
        \$notification = New-Object System.Windows.Forms.NotifyIcon
        \$notification.Icon = [System.Drawing.SystemIcons]::Information
        \$notification.BalloonTipTitle = '$TITLE'
        \$notification.BalloonTipText = '$MESSAGE'
        \$notification.Visible = \$true
        \$notification.ShowBalloonTip(3000)
        Start-Sleep -Seconds 3
        \$notification.Dispose()
    " 2>/dev/null
    exit 0
fi

# フォールバック
echo "🔔 [$TITLE] $MESSAGE" >&2
