#!/bin/bash
# Claude Code 通知スクリプト
# 使用法: notify.sh <タイトル> <メッセージ>

TITLE="${1:-通知}"
MESSAGE="${2:-通知}"

# macOS
if command -v osascript &> /dev/null; then
    osascript \
      -e 'on run argv' \
      -e 'display notification (item 2 of argv) with title (item 1 of argv) sound name "Glass"' \
      -e 'end run' \
      -- "$TITLE" "$MESSAGE" || echo "Warning: macOS notification failed" >&2
    exit 0
fi

# Linux
if command -v notify-send &> /dev/null; then
    notify-send -- "$TITLE" "$MESSAGE" --urgency=normal --icon=dialog-information || echo "Warning: Linux notification failed" >&2

    # オプション: 音も鳴らす
    if [ -f /usr/share/sounds/freedesktop/stereo/complete.oga ] && command -v paplay &> /dev/null; then
        paplay /usr/share/sounds/freedesktop/stereo/complete.oga &
    fi
    exit 0
fi

# Windows
if command -v powershell.exe &> /dev/null; then
    # Base64エンコードで引数を安全に渡す（インジェクション対策）
    TITLE_B64=$(echo -n "$TITLE" | base64)
    MESSAGE_B64=$(echo -n "$MESSAGE" | base64)

    powershell.exe -Command "
        \$title = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('$TITLE_B64'))
        \$message = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('$MESSAGE_B64'))
        Add-Type -AssemblyName System.Windows.Forms
        \$notification = New-Object System.Windows.Forms.NotifyIcon
        \$notification.Icon = [System.Drawing.SystemIcons]::Information
        \$notification.BalloonTipTitle = \$title
        \$notification.BalloonTipText = \$message
        \$notification.Visible = \$true
        \$notification.ShowBalloonTip(3000)
        Start-Sleep -Seconds 3
        \$notification.Dispose()
    " || echo "Warning: Windows notification failed" >&2
    exit 0
fi

# フォールバック
echo "[$TITLE] $MESSAGE" >&2
