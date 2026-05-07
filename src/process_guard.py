"""Bot プロセスガード — 重複起動検知・子プロセスクリーンアップ
仕様: docs/specs/infrastructure/bot-process-guard.md
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

PID_FILE = Path("bot.pid")
BOT_READY_SIGNAL = "BOT_READY"


# ---------------------------------------------------------------------------
# PIDファイル管理
# ---------------------------------------------------------------------------


def write_pid_file() -> None:
    """現在のプロセスIDをPIDファイルに書き込む（排他作成）."""
    pid = os.getpid()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(str(PID_FILE), flags, 0o644)
    except FileExistsError:
        # 同時起動の競合: PIDファイルが既に存在する
        existing_pid = read_pid_file()
        if existing_pid is not None and is_process_alive(existing_pid):
            logger.error(
                "既に別プロセスが起動中です: %s (PID=%d)", PID_FILE, existing_pid,
            )
            sys.exit(1)
        # stale PIDファイルを削除して再試行
        try:
            PID_FILE.unlink()
        except OSError:
            logger.error(
                "stale PIDファイルを削除できませんでした: %s", PID_FILE, exc_info=True,
            )
            sys.exit(1)
        try:
            fd = os.open(str(PID_FILE), flags, 0o644)
        except FileExistsError:
            logger.error("PIDファイルの排他確保に失敗しました: %s", PID_FILE)
            sys.exit(1)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(str(pid))
    logger.info("PIDファイルを作成しました: %s (PID=%d)", PID_FILE, pid)


def read_pid_file() -> int | None:
    """PIDファイルを読み取り、整数値として返す.

    ファイルが存在しない、または内容が不正な場合は None を返す。
    """
    if not PID_FILE.exists():
        return None
    try:
        text = PID_FILE.read_text(encoding="utf-8").strip()
        pid = int(text)
        if pid <= 0:
            return None
        return pid
    except (ValueError, OSError):
        return None


def remove_pid_file() -> None:
    """PIDファイルを削除する. 存在しない場合は何もしない."""
    existed = PID_FILE.exists()
    try:
        PID_FILE.unlink(missing_ok=True)
        if existed:
            logger.info("PIDファイルを削除しました: %s", PID_FILE)
        else:
            logger.debug("PIDファイルは存在しませんでした（削除対象なし）: %s", PID_FILE)
    except OSError:
        logger.warning("PIDファイルの削除に失敗しました: %s", PID_FILE, exc_info=True)


# ---------------------------------------------------------------------------
# プロセス生存確認
# ---------------------------------------------------------------------------


def is_process_alive(pid: int) -> bool:
    """プロセスが生存しているか確認する.

    `psutil.pid_exists` は権限がない場合でも True を返すため、
    旧 Unix 実装（`os.kill(pid, 0)` の `PermissionError` を alive=True とみなす）と
    意味的に等価である。テスト時の patch ポイントを集約するため薄いラッパーとして残す。
    """
    return psutil.pid_exists(pid)


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


def cleanup_children(exclude_pids: Iterable[int] = ()) -> None:
    """現在のプロセスの子プロセスをクリーンアップする.

    `exclude_pids` に含まれる PID は kill 対象から除外する。bot 終了時にも
    存続させたい子プロセス（例: Slack 経由で起動した remote-control）を保護するために使う。

    Windows では TerminateProcess、Unix では SIGTERM が送信される。
    """
    excluded = frozenset(exclude_pids)
    pid = os.getpid()
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=False)
    except psutil.NoSuchProcess:
        logger.debug("プロセスが見つかりません: PID=%d", pid)
        return
    except psutil.AccessDenied:
        logger.warning("プロセス情報のアクセス権限がありません: PID=%d", pid)
        return

    for child in children:
        if child.pid in excluded:
            logger.info("保護対象の子プロセスのため停止しません: PID=%d", child.pid)
            continue
        try:
            child.terminate()
            logger.info("子プロセスを停止しました: PID=%d", child.pid)
        except psutil.NoSuchProcess:
            logger.debug("子プロセスが既に存在しません: PID=%d", child.pid)
        except psutil.AccessDenied:
            logger.warning("子プロセスの停止権限がありません: PID=%d", child.pid)
