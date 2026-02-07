# Bot重複起動防止（Process Guard）

## 概要

`uv run python -m src.main` でBotを起動する際、既存プロセス（子プロセス含む）が残存していた場合に自動で停止してから起動する仕組みを導入する。PIDファイルによるプロセス管理と、シャットダウン時の子プロセスクリーンアップを組み合わせる。

## 背景

- Bot停止時に子プロセス（MCP weatherサーバー等）が残存し、次回起動時に重複インスタンスが立ち上がる問題が発生
- Slackメッセージが二重に処理されたり、古いセッションが残るなどの影響がある
- 手動で `kill` / `Stop-Process` 等を使わないと解消できない

## ユーザーストーリー

- 開発者として、Bot起動時に既存プロセスが自動で停止されることで、重複起動を気にせず開発を進めたい
- 運用者として、シャットダウン時に子プロセスもクリーンアップされることで、ゾンビプロセスが残らない状態にしたい

## 技術仕様

### 全体構成

```
scripts/
  bot_start.sh        # 起動スクリプト（PID管理・重複防止）
src/
  process_guard.py     # Pythonプロセスガード（PID管理・子プロセスクリーンアップ）
```

### 起動スクリプト (`scripts/bot_start.sh`)

PIDファイルベースで既存プロセスを検出・停止してからBotを起動するシェルスクリプト。

**処理フロー**:
1. PIDファイル（`bot.pid`）の存在を確認
2. PIDファイルがある場合、該当プロセスが生存しているか確認
3. 生存している場合、プロセスツリーごと停止（子プロセス含む）
4. 既存のPIDファイル（`bot.pid`）があれば削除
5. `exec uv run python -m src.main` を実行（新しいPIDファイルの作成および終了時の削除は、Python側の `write_pid_file()` とクリーンアップ処理に委譲）

**クロスプラットフォーム対応**:
- Linux/macOS: `kill`, `ps` コマンドを使用
- Windows (Git Bash): `taskkill` コマンドを使用
- プラットフォーム判定: `uname -s` の結果で分岐

### Pythonプロセスガード (`src/process_guard.py`)

アプリケーション内でのPID管理と子プロセスクリーンアップを担当する。

**機能**:
1. PIDファイルの書き込み・読み取り・削除
2. 既存プロセスの検出・停止（`os.kill` / `pgrep`（Unix）、`taskkill` / `wmic`（Windows））
3. シャットダウン時の子プロセスクリーンアップ（`main.py` の `finally` ブロックから呼び出し）

**PIDファイル**:
- パス: プロジェクトルートの `bot.pid`
- 内容: メインプロセスのPID（整数値のみ）
- 作成タイミング: アプリケーション起動時
- 削除タイミング: アプリケーション正常終了時

### main.py との統合

`src/main.py` の `main()` 関数にプロセスガードを組み込む:

```python
from src.process_guard import write_pid_file, remove_pid_file, kill_existing_process, cleanup_children

async def main() -> None:
    # 既存プロセスの停止
    kill_existing_process()
    # PIDファイル書き込み
    write_pid_file()
    try:
        # ... 既存の初期化処理 ...
        await start_socket_mode(app, settings)
    finally:
        if mcp_manager:
            await mcp_manager.cleanup()
        cleanup_children()
        remove_pid_file()
```

## 受け入れ条件

- [ ] AC1: 起動時にPIDファイル（`bot.pid`）が作成されること
- [ ] AC2: 正常終了時にPIDファイルが削除されること
- [ ] AC3: PIDファイルに記録されたプロセスが生存している場合、起動時に自動停止されること
- [ ] AC4: PIDファイルが存在するが該当プロセスが存在しない場合（stale PID）、正常に起動できること
- [ ] AC5: シャットダウン時に子プロセス（MCP サーバー等）もクリーンアップされること
- [ ] AC6: 起動スクリプト（`scripts/bot_start.sh`）がLinux/macOS/Windows(Git Bash)で動作すること
- [ ] AC7: `uv run python -m src.main` での直接起動でもプロセスガードが機能すること
- [ ] AC8: PIDファイルが `.gitignore` に追加されていること
- [ ] AC9: 既存プロセスの停止に失敗した場合、PIDファイルを残してエラーとなること

## 設定

### PIDファイルパス

PIDファイルはプロジェクトルートの `bot.pid` に固定する（環境変数による設定は不要）。

## 使用LLMプロバイダー

**不要** — プロセス管理のみのためLLM処理は不使用

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/process_guard.py` | プロセスガードモジュール（PID管理・子プロセスクリーンアップ） |
| `scripts/bot_start.sh` | Bot起動スクリプト（PIDベース重複防止） |
| `src/main.py` | エントリーポイント（プロセスガード統合） |
| `.gitignore` | `bot.pid` を除外対象に追加 |
| `CLAUDE.md` | Bot起動手順の更新 |
| `README.md` | 起動セクションの更新 |
| `tests/test_process_guard.py` | プロセスガードのテスト |

## テスト方針

- 単体テスト: PIDファイルの読み書き・削除、stale PID検出
- 単体テスト: 子プロセスクリーンアップのモック検証
- テスト名は `test_ac{N}_...` 形式で受け入れ条件と対応

## 考慮事項

### Windows（Git Bash）環境
- シェルスクリプトはLF改行コードで保存
- `kill` コマンドの代わりに `taskkill` を使用するケースを考慮
- Python側は `sys.platform` で判定し、Windows では `taskkill` / `wmic` コマンドを使用

### セキュリティ
- PIDファイルには数値のみを書き込み（インジェクション防止）
- PIDファイル読み込み時に数値バリデーションを実施

### 将来拡張
- ロックファイル（`flock`）によるより厳密な排他制御
- ヘルスチェックエンドポイントの追加
