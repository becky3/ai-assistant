"""Bot プロセスガード — 重複起動検知・子プロセスクリーンアップ
仕様: docs/specs/bot-process-guard.md
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PID_FILE = Path("bot.pid")


# ---------------------------------------------------------------------------
# PIDファイル管理
# ---------------------------------------------------------------------------


def write_pid_file() -> None:
    """現在のプロセスIDをPIDファイルに書き込む."""
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    logger.info("PIDファイルを作成しました: %s (PID=%d)", PID_FILE, os.getpid())


def read_pid_file() -> int | None:
    """PIDファイルを読み取り、整数値として返す.

    ファイルが存在しない、または内容が不正な場合は None を返す。
    """
    if not PID_FILE.exists():
        return None
    try:
        text = PID_FILE.read_text(encoding="utf-8").strip()
        return int(text)
    except (ValueError, OSError):
        return None


def remove_pid_file() -> None:
    """PIDファイルを削除する. 存在しない場合は何もしない."""
    try:
        PID_FILE.unlink(missing_ok=True)
        logger.info("PIDファイルを削除しました: %s", PID_FILE)
    except OSError:
        logger.warning("PIDファイルの削除に失敗しました: %s", PID_FILE, exc_info=True)


# ---------------------------------------------------------------------------
# プロセス生存確認
# ---------------------------------------------------------------------------


def _is_process_alive_unix(pid: int) -> bool:
    """Unix系OSでプロセスの生存を確認する."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_process_alive_windows(pid: int) -> bool:
    """Windowsでtasklistコマンドを使ってプロセスの生存を確認する."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        # tasklist は該当プロセスがない場合 "INFO: No tasks ..." を返す
        if output.startswith("INFO:"):
            return False
        return str(pid) in output
    except FileNotFoundError:
        logger.warning("tasklist コマンドが見つかりません")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("tasklist コマンドがタイムアウトしました")
        return False


def is_process_alive(pid: int) -> bool:
    """プロセスが生存しているか確認する（プラットフォーム分岐）."""
    if sys.platform == "win32":
        return _is_process_alive_windows(pid)
    return _is_process_alive_unix(pid)


# ---------------------------------------------------------------------------
# 重複起動チェック
# ---------------------------------------------------------------------------


def check_already_running() -> None:
    """既にBotが起動中かチェックし、起動中なら警告して終了する."""
    pid = read_pid_file()
    if pid is None:
        return

    if is_process_alive(pid):
        logger.error(
            "Bot は既に起動中です (PID=%d)。"
            "停止するには手動でプロセスを終了してください。",
            pid,
        )
        sys.exit(1)

    # stale PID: プロセスが存在しないのでPIDファイルを削除
    logger.info("stale PIDファイルを検出しました (PID=%d)。削除して続行します。", pid)
    remove_pid_file()


# ---------------------------------------------------------------------------
# 子プロセスクリーンアップ
# ---------------------------------------------------------------------------


def _cleanup_children_unix() -> None:
    """Unix系OSで子プロセスをSIGTERMで停止する."""
    pid = os.getpid()
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        logger.debug("pgrep コマンドが見つかりません。子プロセスクリーンアップをスキップします。")
        return
    except subprocess.TimeoutExpired:
        logger.warning("pgrep コマンドがタイムアウトしました")
        return

    child_pids = result.stdout.strip().splitlines()
    for child_pid_str in child_pids:
        child_pid_str = child_pid_str.strip()
        if not child_pid_str:
            continue
        try:
            child_pid = int(child_pid_str)
            os.kill(child_pid, signal.SIGTERM)
            logger.info("子プロセスを停止しました: PID=%d", child_pid)
        except (ValueError, ProcessLookupError):
            pass
        except PermissionError:
            logger.warning("子プロセスの停止権限がありません: PID=%s", child_pid_str)


def _cleanup_children_windows() -> None:
    """Windowsでwmic/taskkillを使って子プロセスを停止する."""
    pid = os.getpid()
    try:
        result = subprocess.run(
            ["wmic", "process", "where", f"(ParentProcessId={pid})", "get", "ProcessId"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        logger.debug("wmic コマンドが見つかりません。子プロセスクリーンアップをスキップします。")
        return
    except subprocess.TimeoutExpired:
        logger.warning("wmic コマンドがタイムアウトしました")
        return

    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or not line.isdigit():
            continue
        child_pid = int(line)
        try:
            subprocess.run(
                ["taskkill", "/PID", str(child_pid), "/F"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            logger.info("子プロセスを停止しました: PID=%d", child_pid)
        except FileNotFoundError:
            logger.warning("taskkill コマンドが見つかりません")
        except subprocess.TimeoutExpired:
            logger.warning("taskkill がタイムアウトしました: PID=%d", child_pid)


def cleanup_children() -> None:
    """現在のプロセスの子プロセスをクリーンアップする（プラットフォーム分岐）."""
    if sys.platform == "win32":
        _cleanup_children_windows()
    else:
        _cleanup_children_unix()
