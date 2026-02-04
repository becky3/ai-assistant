# Claude Code Hooks による通知機能

## 概要

Claude Code の hooks 機能を使用して、ツール実行時やタスク完了時にデスクトップ通知や音で知らせる機能を実装。長時間かかるタスクの完了通知や、重要な確認時のアラートを提供する。

## 背景

- 参考記事: https://zenn.dev/is0383kk/articles/5d66a34b0a89be
- Claude Code は hooks 機能により、特定のイベント発生時にカスタムスクリプトを実行可能
- 長時間かかるタスクの完了通知や、重要な確認時のアラートに有用

## ユーザーストーリー

- 開発者として、Claude Code がユーザー確認を待っているときにデスクトップ通知を受け取りたい
- 開発者として、長時間タスクが完了したときに音やデスクトップ通知で知らせてほしい
- 開発者として、通知内容や対象イベントをカスタマイズしたい

## 技術仕様

### 設定ファイル

**ファイル: `.claude/settings.json`**

```json
{
  "hooks": {
    "Notification": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "./.claude/scripts/notify.sh 入力待ち 確認が必要です"
          }
        ]
      }
    ],
    "PermissionRequest": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "./.claude/scripts/notify.sh 確認が必要です 承認を待っています"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "./.claude/scripts/notify.sh タスク完了 完了しました"
          }
        ]
      }
    ]
  }
}
```

**対応イベント（PascalCase）:**
- `Notification`: ユーザー入力待ち時（選択肢提示、許可ダイアログ、アイドル状態など）
- `PermissionRequest`: ツール実行の許可ダイアログ表示時のみ
- `Stop`: Claude がタスク完了時
- その他のイベント: `SessionStart`, `SessionEnd`, `PreToolUse`, `PostToolUse` など

**注意**: 選択肢提示（AskUserQuestion）は `Notification` イベントで捕捉する。`PermissionRequest` はツール実行許可のみ。

**設定形式のポイント:**
- イベント名は PascalCase（例: `Stop`, `Notification`）
- 各イベントは配列で、`matcher` と `hooks` を含むオブジェクトを持つ
- `hooks` 配列内で `type: "command"` と `command` を指定
- パスは相対パス `./.claude/scripts/...` を使用

**Notification イベントの matcher 値:**
- `*`: 全ての通知タイプをキャッチ
- `permission_prompt`: ツール許可ダイアログ表示時
- `idle_prompt`: アイドル状態で入力待機時
- `elicitation_dialog`: 選択肢提示（AskUserQuestion）時
- `auth_success`: 認証成功時

### 通知スクリプト

**ファイル: `.claude/scripts/notify.sh`**

クロスプラットフォーム対応の bash スクリプト:

- **macOS**: `osascript` によるネイティブ通知 + サウンド
- **Linux**: `notify-send` (libnotify) + オプションでサウンド
- **Windows**: PowerShell によるバルーン通知
- **フォールバック**: 通知コマンドがない環境では `stderr` にテキスト出力

**セキュリティ対策:**
- シェルインジェクション対策（変数の適切なエスケープ）
- エラー発生時の明示的なメッセージ表示

### 使用方法

`.claude/settings.json` を編集してイベントや通知内容をカスタマイズ:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "./.claude/scripts/notify.sh カスタムタイトル カスタムメッセージ"
          }
        ]
      }
    ]
  }
}
```

## 受け入れ条件

- [x] AC1: `.claude/settings.json` に hooks が設定されている
- [x] AC2: `.claude/scripts/notify.sh` が実装され、実行可能権限がある（クローン後に `chmod +x` が必要な場合あり）
- [x] AC3: macOS環境でデスクトップ通知が表示される
- [x] AC4: Linux環境で `notify-send` 通知が表示される
- [x] AC5: Windows環境で PowerShell 通知が表示される
- [x] AC6: 通知が表示されない環境でもエラーなく動作する

## 技術的な注意点

- **セキュリティ**: フックスクリプトは任意コマンド実行可能なため、信頼できるスクリプトのみ設定
- **パフォーマンス**: 通知は非同期実行、Claude Code の動作を阻害しない
- **環境依存**: 各環境での通知コマンド存在確認とフォールバック処理が必須
- **設定の配置**: プロジェクト固有は `.claude/settings.json`、グローバルは `~/.claude/settings.json`
- **Windows環境**: シェルスクリプトは LF 改行コードで保存すること（CRLF だとエラー）
- **実行権限**: クローン後に `chmod +x .claude/scripts/notify.sh` が必要な場合がある（特にLinux/macOS）

## 実装の優先順位

**Phase 1 (MVP)** — 完了:
- macOS + Linux のデスクトップ通知
- `PermissionRequest` イベント対応（確認・承認待ち通知）
- 基本的な通知スクリプト
- セキュリティ対策

**Phase 2 (拡張)** — 完了:
- Windows対応
- `Stop` イベント対応
- 音による通知追加

**Phase 3 (最適化)** — 未実装:
- 通知のカスタマイズ設定
- 通知頻度制御
- 通知音選択機能

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `.claude/settings.json` | hooks 設定（イベント駆動の通知設定を含む） |
| `.claude/scripts/notify.sh` | クロスプラットフォーム対応の通知スクリプト |

## 参考資料

- [Claude Code Hooks 公式ドキュメント](https://code.claude.com/docs/en/hooks)
- [Zenn記事: Claude Codeのhooks機能について](https://zenn.dev/is0383kk/articles/5d66a34b0a89be)
- Issue #35: Hooks使って、確認時に音を鳴らす
- PR #45: 実装プルリクエスト
