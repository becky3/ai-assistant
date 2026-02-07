"""Bot重複起動防止（プロセスガード）
仕様: docs/specs/bot-process-guard.md

PIDファイルによるプロセス管理と、シャットダウン時の子プロセスクリーンアップを提供する。
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# PIDファイルのデフォルトパス（プロジェクトルート）
DEFAULT_PID_FILE = Path(__file__).resolve().parent.parent / "bot.pid"


def write_pid_file(pid_path: Path = DEFAULT_PID_FILE) -> None:
    """現在のプロセスPIDをファイルに書き込む."""
    pid = os.getpid()
    pid_path.write_text(str(pid), encoding="utf-8")
    logger.info("PIDファイルを作成しました: %s (PID=%d)", pid_path, pid)


def remove_pid_file(pid_path: Path = DEFAULT_PID_FILE) -> None:
    """PIDファイルを削除する."""
    try:
        pid_path.unlink(missing_ok=True)
        logger.info("PIDファイルを削除しました: %s", pid_path)
    except OSError:
        logger.warning("PIDファイルの削除に失敗しました: %s", pid_path, exc_info=True)


def read_pid_file(pid_path: Path = DEFAULT_PID_FILE) -> int | None:
    """PIDファイルからPIDを読み取る.

    Returns:
        PID（整数）。ファイルが存在しない・不正な場合は None。
    """
    if not pid_path.exists():
        return None

    try:
        content = pid_path.read_text(encoding="utf-8").strip()
        pid = int(content)
        if pid <= 0:
            logger.warning("PIDファイルに不正な値が含まれています: %s", content)
            return None
        return pid
    except (ValueError, OSError):
        logger.warning("PIDファイルの読み取りに失敗しました: %s", pid_path, exc_info=True)
        return None


def is_process_alive(pid: int) -> bool:
    """指定PIDのプロセスが生存しているか確認する."""
    try:
        os.kill(pid, 0)  # シグナル0: 生存確認のみ
    except ProcessLookupError:
        return False
    except PermissionError:
        # プロセスは存在するがアクセス権がない
        return True
    except (OSError, SystemError):
        # Windows環境で不正なPID・終了済みプロセスの場合など
        return False
    else:
        return True


def _kill_process_tree(pid: int) -> None:
    """プロセスとその子プロセスを停止する.

    Windows と Unix で異なる方法を使用する。
    """
    if sys.platform == "win32":
        _kill_process_tree_windows(pid)
    else:
        _kill_process_tree_unix(pid)


def _kill_process_tree_unix(pid: int) -> None:
    """Unix系OSでプロセスツリーを停止する.

    子プロセスを列挙して停止した後、親プロセスに SIGTERM → SIGKILL を送信する。
    """
    import subprocess

    # まず子プロセスを停止
    try:
        result = subprocess.run(  # noqa: S603
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip().isdigit():
                child_pid = int(line.strip())
                try:
                    os.kill(child_pid, signal.SIGTERM)
                    logger.info("子プロセス PID=%d に SIGTERM を送信しました", child_pid)
                except (ProcessLookupError, PermissionError):
                    pass
    except FileNotFoundError:
        logger.debug("pgrep コマンドが見つかりません。子プロセスの停止をスキップします。")

    # 親プロセスに SIGTERM で graceful に停止を試みる
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("プロセス PID=%d に SIGTERM を送信しました", pid)
    except ProcessLookupError:
        logger.info("プロセス PID=%d は既に終了しています", pid)
        return
    except PermissionError:
        logger.warning("プロセス PID=%d への SIGTERM 送信に失敗しました（権限不足）", pid)
        return

    # 少し待ってからまだ生きているか確認
    time.sleep(1)

    if is_process_alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)  # type: ignore[attr-defined]
            logger.info("プロセス PID=%d に SIGKILL を送信しました", pid)
        except ProcessLookupError:
            # SIGKILL 送信前にプロセスが終了していた場合は正常
            pass
        except PermissionError:
            logger.warning("プロセス PID=%d への SIGKILL 送信に失敗しました（権限不足）", pid)


def _kill_process_tree_windows(pid: int) -> None:
    """WindowsでプロセスとBotの子プロセスを停止する."""
    import subprocess

    try:
        subprocess.run(  # noqa: S603
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        logger.info("プロセスツリー PID=%d を停止しました (taskkill)", pid)
    except FileNotFoundError:
        logger.warning("taskkill コマンドが見つかりません。手動でプロセスを停止してください。")


def kill_existing_process(pid_path: Path = DEFAULT_PID_FILE) -> None:
    """PIDファイルに記録された既存プロセスを停止する.

    - PIDファイルが存在しない場合は何もしない
    - PIDファイルのプロセスが既に終了している場合（stale PID）はPIDファイルを削除
    - PIDファイルのプロセスが生存している場合はプロセスツリーごと停止
    """
    pid = read_pid_file(pid_path)
    if pid is None:
        return

    if not is_process_alive(pid):
        logger.info("PIDファイルのプロセス PID=%d は既に終了しています（stale PID）。PIDファイルを削除します。", pid)
        remove_pid_file(pid_path)
        return

    # 自分自身のPIDの場合は停止しない
    if pid == os.getpid():
        logger.info("PIDファイルのプロセスは自分自身です。スキップします。")
        return

    logger.info("既存プロセス PID=%d を停止します...", pid)
    _kill_process_tree(pid)

    # kill後に生存確認し、停止できていなければPIDファイルを残してエラーにする
    time.sleep(1)
    if is_process_alive(pid):
        msg = f"プロセス PID={pid} の停止に失敗しました。手動で停止してください。"
        logger.error(msg)
        raise RuntimeError(msg)

    remove_pid_file(pid_path)
    logger.info("既存プロセスの停止が完了しました。")


def cleanup_children() -> None:
    """現在のプロセスの子プロセスをクリーンアップする.

    シャットダウン時に呼び出して、残存する子プロセスを停止する。
    """
    current_pid = os.getpid()

    if sys.platform == "win32":
        _cleanup_children_windows(current_pid)
    else:
        _cleanup_children_unix(current_pid)


def _cleanup_children_unix(parent_pid: int) -> None:
    """Unix系OSで子プロセスをクリーンアップする."""
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603
            ["pgrep", "-P", str(parent_pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        child_pids_raw = result.stdout.strip()
        if not child_pids_raw:
            logger.debug("子プロセスはありません。")
            return

        child_pids = [int(p) for p in child_pids_raw.split("\n") if p.strip().isdigit()]
        for child_pid in child_pids:
            try:
                os.kill(child_pid, signal.SIGTERM)
                logger.info("子プロセス PID=%d に SIGTERM を送信しました", child_pid)
            except ProcessLookupError:
                # 子プロセスが既に終了していた場合は正常
                pass
            except PermissionError:
                logger.warning("子プロセス PID=%d への SIGTERM 送信に失敗しました", child_pid)

    except FileNotFoundError:
        logger.debug("pgrep コマンドが見つかりません。子プロセスのクリーンアップをスキップします。")


def _cleanup_children_windows(parent_pid: int) -> None:
    """Windowsで子プロセスをクリーンアップする."""
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603
            [
                "wmic",
                "process",
                "where",
                f"ParentProcessId={parent_pid}",
                "get",
                "ProcessId",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                child_pid = int(line)
                try:
                    subprocess.run(  # noqa: S603
                        ["taskkill", "/F", "/PID", str(child_pid)],
                        capture_output=True,
                        check=False,
                    )
                    logger.info("子プロセス PID=%d を停止しました", child_pid)
                except FileNotFoundError:
                    # taskkill コマンドが見つからない場合は停止をスキップ
                    pass
    except FileNotFoundError:
        logger.debug("wmic コマンドが見つかりません。子プロセスのクリーンアップをスキップします。")
