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
  bot_stop.sh         # 停止スクリプト（プロセス検証付き）
src/
  process_guard.py     # Pythonプロセスガード（PID管理・子プロセスクリーンアップ）
```

### 停止スクリプト (`scripts/bot_stop.sh`)

PIDファイルベースでBotを停止するシェルスクリプト。プロセス検証により、PID再利用時に無関係プロセスを誤killしない。

**処理フロー**:
1. PIDファイル（`bot.pid`）が存在しない → 「Botは起動していません」、exit 0
2. PID読み取り → 不正な値なら PIDファイル削除、exit 1
3. `is_process_alive` → 死んでいれば PIDファイル削除、exit 0
4. `is_bot_process` → Bot以外なら「PID再利用検出」警告、PIDファイル削除、exit 0（killしない）
5. `kill_process_tree` でプロセスツリーごと停止
6. PIDファイル削除、「Botを停止しました」表示

**プロセス検証（`is_bot_process`）**:
- コマンドライン文字列に識別キーワード `src.main` が含まれるかで判定
- Windows: `wmic process where "ProcessId=PID" get CommandLine`
- Unix: `ps -p PID -o args=`
- コマンド実行失敗時は安全側に倒し、Bot以外と判定（killしない）

**ヘルパー関数**:
- `detect_os`, `is_process_alive`, `kill_process_tree` — `bot_stop.sh` 内で定義（`bot_start.sh` は `bot_stop.sh` を呼び出すため間接的に使用）
- `is_bot_process` — プロセスがBotかどうか検証

**クロスプラットフォーム対応**:
- Linux/macOS: `kill`, `ps`, `pkill` コマンドを使用
- Windows (Git Bash): `taskkill`, `tasklist`, `wmic` コマンドを使用
- プラットフォーム判定: `uname -s` の結果で分岐

### 起動スクリプト (`scripts/bot_start.sh`)

既存プロセスの停止を `bot_stop.sh` に委譲し、新しいBotを起動するシェルスクリプト。

**処理フロー**:
1. `bot_stop.sh` を呼び出して既存プロセスを停止
2. `exec uv run python -m src.main` を実行（新しいPIDファイルの作成および終了時の削除は、Python側の `write_pid_file()` とクリーンアップ処理に委譲）

### Pythonプロセスガード (`src/process_guard.py`)

アプリケーション内でのPID管理と子プロセスクリーンアップを担当する。

**機能**:
1. PIDファイルの書き込み・読み取り・削除
2. 既存プロセスの検出・停止（`os.kill` でシグナル送信、プロセスツリー停止時に `pgrep`（Unix）/ `taskkill`（Windows）を使用）
3. プロセス検証（コマンドライン文字列から `src.main` の存在を確認し、Bot以外のkillを防止）
4. シャットダウン時の子プロセスクリーンアップ（`main.py` の `finally` ブロックから呼び出し）

**PIDファイル**:
- パス: プロジェクトルートの `bot.pid`
- 内容: メインプロセスのPID（整数値のみ）
- 作成タイミング: アプリケーション起動時
- 削除タイミング: アプリケーション正常終了時

### main.py との統合

`src/main.py` の `main()` 関数にプロセスガードを組み込む:

1. 起動時: `kill_existing_process()` → `write_pid_file()`
2. `try` ブロック内: 既存の初期化処理・ソケットモード開始
3. `finally` ブロック: 各クリーンアップ処理（`mcp_manager.cleanup()`、`cleanup_children()`、`remove_pid_file()`）は例外安全に実装し、一つの処理が失敗しても残りの処理が確実に実行されるようにする

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
- [ ] AC10: `scripts/bot_stop.sh` を単独実行し、PIDファイルに記録されたBotプロセスをプロセスツリーごと停止し、PIDファイルを削除できること
- [ ] AC11: PIDファイルのプロセスがBotかコマンドライン文字列で検証し、Bot以外をkillしないこと
- [ ] AC12: `bot_start.sh` が内部で `bot_stop.sh` を呼び出して既存プロセスを停止すること

## 設定

### PIDファイルパス

PIDファイルはプロジェクトルートの `bot.pid` に固定する（環境変数による設定は不要）。

## 使用LLMプロバイダー

**不要** — プロセス管理のみのためLLM処理は不使用

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `src/process_guard.py` | プロセスガードモジュール（PID管理・子プロセスクリーンアップ） |
| `scripts/bot_start.sh` | Bot起動スクリプト（停止処理を `bot_stop.sh` に委譲） |
| `scripts/bot_stop.sh` | Bot停止スクリプト（プロセス検証付き） |
| `src/main.py` | エントリーポイント（プロセスガード統合） |
| `.gitignore` | `bot.pid` を除外対象に追加 |
| `CLAUDE.md` | Bot起動手順の更新 |
| `README.md` | 起動セクションの更新 |
| `tests/test_process_guard.py` | プロセスガードのテスト |

## テスト方針

- 単体テスト: PIDファイルの読み書き・削除、stale PID検出
- 単体テスト: 子プロセスクリーンアップのモック検証
- 単体テスト: プロセス検証（`is_bot_process`）のモック検証
- 結合テスト（手動）: `bot_stop.sh` の単独実行でBotが停止されること（AC10）
- 結合テスト（手動）: `bot_start.sh` 実行時に `bot_stop.sh` が呼び出され、既存プロセスが停止されてから新しいBotが起動すること（AC12）
- テスト名は `test_ac{N}_...` 形式で受け入れ条件と対応

## 考慮事項

### Windows（Git Bash）環境
- シェルスクリプトはLF改行コードで保存
- `kill` コマンドの代わりに `taskkill` を使用するケースを考慮
- Python側は `sys.platform` で判定し、Windows では `taskkill` / `wmic` コマンドを使用

### プロセス停止失敗時の挙動
- **Python側**（`kill_existing_process()`）: 停止後にプロセス生存確認を行い、停止失敗時はPIDファイルを残して `RuntimeError` を発生させる（AC9）
- **シェルスクリプト側**（`bot_stop.sh`）: 簡易実装として停止コマンドの結果に関わらずPIDファイルを削除する。確実な停止保証はPython側が担当する

### セキュリティ
- PIDファイルには数値のみを書き込み（インジェクション防止）
- PIDファイル読み込み時に数値バリデーションを実施

### 将来拡張
- ロックファイル（`flock`）によるより厳密な排他制御
- ヘルスチェックエンドポイントの追加
