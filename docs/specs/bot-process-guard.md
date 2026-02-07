# Bot プロセスガード（重複起動検知）

## 概要

Bot起動時にPIDファイルを使って既存プロセスの重複起動を検知し、警告メッセージを表示して終了する。また、シャットダウン時に子プロセス（MCPサーバー等）をクリーンアップする。

## ユーザーストーリー

- 開発者として、Botが二重起動していることに気づかず問題が発生するのを防ぐために、重複起動を検知して警告を受けたい
- 運用者として、Bot停止後に残存する子プロセスをクリーンアップするために、シャットダウン時に子プロセスを自動停止したい

## 背景

- Bot停止時に子プロセス（MCPサーバー等）が残存し、次回起動時にSlackに二重セッションが発生する問題があった
- PR #137 で `os.kill(pid, 0)` ベースの実装をしたが、Windowsでは `SystemError` が発生しリバート済み
- 今回は `tasklist`（Windows）/ `os.kill`（Unix）のプラットフォーム分岐で再実装する

## 受け入れ条件

- [ ] AC1: Bot起動時にPIDファイル（`bot.pid`）が作成される
- [ ] AC2: Bot終了時にPIDファイルが削除される
- [ ] AC3: 既にBotが起動中の場合、重複起動を検知して警告メッセージを表示し `sys.exit(1)` で終了する
- [ ] AC4: PIDファイルが残っているが対応プロセスが存在しない場合（stale PID）、正常に起動できる
- [ ] AC5: Windowsで `tasklist` コマンドによるプロセス生存確認が正しく動作する
- [ ] AC6: Unix系OSで `os.kill(pid, 0)` によるプロセス生存確認が正しく動作する
- [ ] AC7: Bot終了時に子プロセス（MCPサーバー等）がクリーンアップされる
- [ ] AC8: クリーンアップ処理の失敗がBot終了を妨げない（例外をキャッチしてログ出力）
- [ ] AC9: `bot.pid` が `.gitignore` に含まれている

## 技術設計

### PIDファイル管理

PIDファイルのパスはプロジェクトルート直下の `bot.pid`。

```python
PID_FILE = Path("bot.pid")
```

#### `write_pid_file() -> None`
- 現在のプロセスIDを `bot.pid` に書き込む

#### `read_pid_file() -> int | None`
- PIDファイルを読み取り、整数値として返す
- ファイルが存在しない、または内容が不正な場合は `None` を返す

#### `remove_pid_file() -> None`
- PIDファイルを削除する
- ファイルが存在しない場合は何もしない
- 削除に失敗した場合はログ警告を出力して続行する

### プロセス生存確認

#### `is_process_alive(pid: int) -> bool`
- `sys.platform == "win32"` で判定し、Windows用 / Unix用の内部関数にディスパッチする

#### `_is_process_alive_unix(pid: int) -> bool`
- `os.kill(pid, 0)` でプロセスの存在を確認
- `ProcessLookupError` → `False`（プロセスなし）
- `PermissionError` → `True`（プロセスあり、権限なし）

#### `_is_process_alive_windows(pid: int) -> bool`
- `subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], ...)` を実行
- 標準出力にPID文字列が含まれていれば `True`
- `"INFO:"` で始まるか、PID文字列が見つからなければ `False`
- `FileNotFoundError`（tasklist未検出）→ `False`
- `subprocess.TimeoutExpired`（タイムアウト）→ `False`

### 重複起動チェック

#### `check_already_running() -> None`
1. `read_pid_file()` でPIDを取得
2. PIDが取得できなければ正常通過
3. `is_process_alive(pid)` でプロセス生存確認
4. 生存していればエラーメッセージをログ出力し `sys.exit(1)`
5. stale PIDの場合はPIDファイルを削除して正常通過

### 子プロセスクリーンアップ

#### `cleanup_children() -> None`
- 現在のプロセスの子プロセスを停止する
- **Unix**: `pgrep -P {pid}` で子プロセスを取得し `os.kill(child_pid, signal.SIGTERM)` で停止
- **Windows**: `wmic process where (ParentProcessId={pid}) get ProcessId` で子プロセスを取得し `taskkill /PID {child_pid} /F` で停止
- 子プロセスが存在しない場合は何もしない
- `pgrep`/`wmic` コマンドが見つからない場合やタイムアウト時はスキップしてログ出力
- 個々の子プロセス停止失敗（`taskkill` 未検出、タイムアウト等）はログ出力して継続

## `src/main.py` への統合

```python
from src.process_guard import (
    check_already_running,
    cleanup_children,
    remove_pid_file,
    write_pid_file,
)

async def main() -> None:
    check_already_running()
    write_pid_file()

    # ... 既存の初期化処理 ...

    try:
        await start_socket_mode(app, settings)
    finally:
        if mcp_manager:
            try:
                await mcp_manager.cleanup()
            except Exception:
                logger.warning("MCPクリーンアップ失敗", exc_info=True)
        try:
            cleanup_children()
        except Exception:
            logger.warning("子プロセスクリーンアップ失敗", exc_info=True)
        remove_pid_file()
```

## やらないこと

- **自動kill**: 既存プロセスを自動的に停止しない。ユーザーが手動で停止する
- **プロセス名検証**: PIDファイルのプロセスがBotかどうかの検証は行わない（killしないため誤kill問題がない）
- **起動・停止スクリプト**: シェルスクリプトは不要

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/process_guard.py` | PIDファイル管理・重複検知・子プロセスクリーンアップ |
| `src/main.py` | プロセスガード統合 |
| `tests/test_process_guard.py` | プロセスガードのテスト |
| `.gitignore` | `bot.pid` の除外設定 |

## テスト方針

- PIDファイルの読み書き・削除
- Unix向けプロセス生存確認（`os.kill` モック）
- Windows向けプロセス生存確認（`tasklist` 出力モック）
- 重複起動チェック（生存プロセスあり→SystemExit / stale PID→正常通過）
- 子プロセスクリーンアップ（Unix: pgrep+SIGTERM / Windows: wmic+taskkill）
- テスト名は `test_ac{N}_...` 形式で受け入れ条件と対応

## 関連Issue

- #136: Bot重複起動防止の仕組みを導入する
- #137: 初回実装（Windowsで SystemError 発生のためリバート）
- #139: PR #137 のリバート
