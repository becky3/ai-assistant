#!/bin/bash
# Leader Guard - チーム運用中のリーダーによる Edit/Write 使用をブロックするフック
# PreToolUse フックとして実行される
# stdin から JSON を読み取り、permission_mode でリーダー/メンバーを判別する
# 仕様: docs/specs/agent-teams.md（リーダー管理専任ルール）

# stdin から JSON を読み取る
INPUT=$(cat)

# permission_mode を抽出（jq があれば使う、なければ grep/sed）
if command -v jq > /dev/null 2>&1; then
    PERMISSION_MODE=$(echo "$INPUT" | jq -r '.permission_mode // empty')
else
    PERMISSION_MODE=$(echo "$INPUT" | grep -o '"permission_mode"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"permission_mode"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
fi

# メンバー（bypassPermissions）なら何もしない
if [ "$PERMISSION_MODE" = "bypassPermissions" ]; then
    exit 0
fi

# チームディレクトリの確認
TEAMS_DIR="$HOME/.claude/teams"

if [ ! -d "$TEAMS_DIR" ]; then
    exit 0
fi

# サブディレクトリが1つでもあるか確認
has_teams=false
for entry in "$TEAMS_DIR"/*/; do
    if [ -d "$entry" ]; then
        has_teams=true
        break
    fi
done

if [ "$has_teams" = false ]; then
    exit 0
fi

# リーダー + チーム稼働中 → ブロック
echo '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "⚠️ チーム運用中: リーダー管理専任ルールにより、Edit/Write の使用は原則禁止です。メンバーに委譲してください。"}}'

exit 0
