"""Bot 管理コマンド — start / restart / stop / status
仕様: docs/specs/infrastructure/bot-process-guard.md
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

import psutil

from src.process_guard import (
    BOT_READY_SIGNAL,
    is_process_alive,
    read_pid_file,
    remove_pid_file,
)

logger = logging.getLogger(__name__)
READY_TIMEOUT_SECONDS = 60
LOG_DIR = Path(".tmp")
LOG_FILE = LOG_DIR / "bot.log"


# ---------------------------------------------------------------------------
# プロセスツリー停止
# ---------------------------------------------------------------------------


def _kill_pid(pid: int) -> None:
    """指定PIDのプロセスを停止する.

    Unix では SIGTERM を送り、子プロセスにグレースフル停止の機会を与える。
    Windows では psutil.terminate() が TerminateProcess を呼ぶため強制終了となる
    （Windows API にグレースフル停止に相当する仕組みがないため）。
    実装は psutil の `Process.terminate()` に委譲する。
    """
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        logger.info("プロセスを停止しました: PID=%d", pid)
    except psutil.NoSuchProcess:
        logger.debug("プロセスが既に存在しません: PID=%d", pid)
    except psutil.AccessDenied:
        logger.warning("プロセスの停止権限がありません: PID=%d", pid)


def _kill_process_tree(pid: int) -> None:
    """指定PIDのプロセスツリー（子プロセス→本体の順）を外部から停止する.

    内部では psutil.Process オブジェクトを直接使い、PID → Process の再ルックアップを
    避けることで PID 再利用レースの窓を縮小する。
    親プロセスが既に消失している場合は kill 不要のため早期 return する。
    子プロセスの列挙に失敗した場合でも、本体プロセスの停止は試行する。
    """
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        logger.debug("プロセスが既に存在しません: PID=%d", pid)
        return

    children: list[psutil.Process] = []
    try:
        children = parent.children(recursive=False)
    except psutil.NoSuchProcess:
        logger.debug("プロセスが既に存在しません: PID=%d", pid)
        return
    except psutil.AccessDenied:
        logger.warning(
            "子プロセス列挙の権限がありません。本体のみ停止を試みます: PID=%d", pid,
        )

    for child in children:
        try:
            child.terminate()
            logger.info("プロセスを停止しました: PID=%d", child.pid)
        except psutil.NoSuchProcess:
            logger.debug("プロセスが既に存在しません: PID=%d", child.pid)
        except psutil.AccessDenied:
            logger.warning("プロセスの停止権限がありません: PID=%d", child.pid)

    _kill_pid(pid)


# ---------------------------------------------------------------------------
# 管理コマンド
# ---------------------------------------------------------------------------


def _stop_bot() -> bool:
    """起動中のBotを停止する. 停止した場合True, 未起動の場合Falseを返す."""
    pid = read_pid_file()
    if pid is None or not is_process_alive(pid):
        # PIDファイルがあるがプロセスがない場合（stale）もクリーンアップ
        if pid is not None:
            remove_pid_file()
        return False

    _kill_process_tree(pid)
    remove_pid_file()
    return True


def _start_bot() -> int:
    """Botを子プロセスとして起動し、BOT_READY を待つ. BotのPIDを返す."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOG_FILE, "a", encoding="utf-8")  # noqa: SIM115

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.main"],
            stdout=subprocess.PIPE,
            stderr=log_file,
        )
    except Exception:
        log_file.close()
        raise

    try:
        _wait_for_ready(proc)
    except BaseException:
        # BOT_READY 待ちに失敗した場合、子プロセスを停止する
        # SystemExit (sys.exit) も捕捉するため BaseException を使用
        _kill_process_tree(proc.pid)
        if proc.stdout is not None:
            proc.stdout.close()
        remove_pid_file()
        raise
    finally:
        log_file.close()

    # BOT_READY 受信後、Bot が write_pid_file() で記録した実際の PID を返す。
    # Popen.pid はランチャー等の中間プロセスの場合があるため PID ファイルを参照する。
    bot_pid = read_pid_file()
    if bot_pid is None:
        bot_pid = proc.pid
    return bot_pid


def _wait_for_ready(proc: subprocess.Popen[bytes]) -> None:
    """子プロセスの stdout から BOT_READY を待つ."""
    assert proc.stdout is not None  # noqa: S101

    timeout = READY_TIMEOUT_SECONDS
    # Windows では select が pipe に使えないため、スレッドで readline する
    if sys.platform == "win32":
        _wait_for_ready_windows(proc, timeout)
    else:
        _wait_for_ready_unix(proc, timeout)


def _wait_for_ready_windows(proc: subprocess.Popen[bytes], timeout: float) -> None:
    """Windows向け: daemon スレッドで stdout.readline() を行い、全体デッドラインで待つ."""
    import queue
    import threading
    import time

    assert proc.stdout is not None  # noqa: S101

    line_queue: queue.Queue[str] = queue.Queue()

    def _reader() -> None:
        for raw in iter(proc.stdout.readline, b""):  # type: ignore[union-attr]
            line_queue.put(raw.decode("utf-8", errors="replace").strip())
        line_queue.put("")  # EOF

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(f"Error: Bot startup timed out ({timeout}s)", file=sys.stderr)
            sys.exit(1)

        try:
            line = line_queue.get(timeout=remaining)
        except queue.Empty:
            print(f"Error: Bot startup timed out ({timeout}s)", file=sys.stderr)
            sys.exit(1)

        if not line:
            # パイプが閉じた（子プロセスが異常終了した）
            returncode = proc.poll()
            print(
                f"Error: Bot process exited unexpectedly (exit code: {returncode}). "
                f"Check log: {LOG_FILE}",
                file=sys.stderr,
            )
            sys.exit(1)

        if line == BOT_READY_SIGNAL:
            return


def _wait_for_ready_unix(proc: subprocess.Popen[bytes], timeout: float) -> None:
    """Unix向け: select で stdout をタイムアウト付きで待つ."""
    import select as select_mod

    assert proc.stdout is not None  # noqa: S101
    fd = proc.stdout.fileno()

    remaining = timeout
    import time

    while True:
        if remaining <= 0:
            print(f"Error: Bot startup timed out ({timeout}s)", file=sys.stderr)
            sys.exit(1)

        start = time.monotonic()
        ready, _, _ = select_mod.select([fd], [], [], remaining)
        elapsed = time.monotonic() - start
        remaining -= elapsed

        if not ready:
            print(f"Error: Bot startup timed out ({timeout}s)", file=sys.stderr)
            sys.exit(1)

        line = proc.stdout.readline().decode("utf-8", errors="replace").strip()
        if not line:
            returncode = proc.poll()
            print(
                f"Error: Bot process exited unexpectedly (exit code: {returncode}). "
                f"Check log: {LOG_FILE}",
                file=sys.stderr,
            )
            sys.exit(1)

        if line == BOT_READY_SIGNAL:
            return


def cmd_start() -> None:
    """--start: Botを起動する."""
    pid = read_pid_file()
    if pid is not None and is_process_alive(pid):
        print(f"Already running (PID={pid})")
        sys.exit(1)

    # stale PID ファイルがあれば削除
    if pid is not None:
        remove_pid_file()

    child_pid = _start_bot()
    print(f"Running (PID={child_pid})")


def cmd_stop() -> None:
    """--stop: Botを停止する."""
    stopped = _stop_bot()
    if stopped:
        print("Stopped")
    else:
        print("Not running")


def cmd_restart() -> None:
    """--restart: Botを停止→起動する."""
    stopped = _stop_bot()
    if stopped:
        print("Stopped")

    child_pid = _start_bot()
    print(f"Running (PID={child_pid})")


def cmd_status() -> None:
    """--status: Botの状態を表示する."""
    pid = read_pid_file()
    if pid is not None and is_process_alive(pid):
        print(f"Running (PID={pid})")
        if LOG_FILE.exists():
            print(f"Log: {LOG_FILE}")
        sys.exit(0)
    else:
        print("Not running")
        sys.exit(1)


def handle_command(args: argparse.Namespace) -> None:
    """管理コマンドを実行する."""
    from src.compat import configure_stdio_encoding

    configure_stdio_encoding()
    logging.basicConfig(level=logging.INFO)

    if args.start:
        cmd_start()
    elif args.restart:
        cmd_restart()
    elif args.stop:
        cmd_stop()
    elif args.status:
        cmd_status()
