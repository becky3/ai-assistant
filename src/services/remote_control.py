"""Remote Control 起動サービス
仕様: docs/specs/features/remote-control-launch.md

claude remote-control をデタッチ起動し、ログから接続 URL を抽出する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# claude remote-control が stdout に出力する接続 URL のパターン
_URL_PATTERN = re.compile(r"https://claude\.ai/code\?environment=env_[A-Za-z0-9]+")

# URL 抽出のポーリング間隔（秒）。短すぎると CPU を浪費、長すぎると応答遅延
_POLL_INTERVAL_SECONDS = 0.5


class RemoteControlError(Exception):
    """Remote Control 起動の共通エラー."""


class RemoteControlBinaryNotFoundError(RemoteControlError):
    """claude 実行ファイルが PATH 上に存在しない."""


class RemoteControlRepositoryNotFoundError(RemoteControlError):
    """指定された絶対パスがディレクトリとして存在しない."""


class RemoteControlURLTimeoutError(RemoteControlError):
    """ログから接続 URL を抽出する前にタイムアウトした.

    起動した子プロセスは kill しない（接続自体は遅延後に成立する可能性があるため）。
    エラーメッセージにログファイルパスを含めることで、ユーザーが手動で URL を確認できる。
    """


class RemoteControlProcessExitedError(RemoteControlError):
    """URL 抽出前に子プロセスが終了した（claude のエラー等）."""


@dataclass(frozen=True)
class RemoteControlLaunchResult:
    """起動成功時の結果."""

    session_name: str
    connect_url: str
    log_path: Path


class RemoteControlLauncher:
    """claude remote-control プロセスをデタッチ起動するサービス.

    仕様: docs/specs/features/remote-control-launch.md
    """

    def __init__(
        self,
        repositories: dict[str, str],
        log_dir: Path,
        url_timeout: int,
    ) -> None:
        self._repositories = repositories
        self._log_dir = log_dir
        self._url_timeout = url_timeout
        # 起動中の remote-control プロセス PID。cleanup_children() の除外対象として参照される
        self._active_pids: set[int] = set()

    def get_repositories(self) -> dict[str, str]:
        """登録済み repo allowlist を返す."""
        return dict(self._repositories)

    def get_active_pids(self) -> set[int]:
        """起動中の remote-control プロセス PID 集合を返す.

        bot 終了時の cleanup_children() で「道連れ kill」を回避する除外リストに使う。
        """
        return set(self._active_pids)

    async def launch(self, repo_key: str) -> RemoteControlLaunchResult:
        """指定 repo-key で claude remote-control を起動し、接続 URL を返す."""
        logger.info("remote_control launch start: repo_key=%s", repo_key)
        if repo_key not in self._repositories:
            registered = ", ".join(sorted(self._repositories.keys())) or "(なし)"
            msg = f"未登録のリポジトリキーです: {repo_key}\n登録済み: {registered}"
            raise RemoteControlError(msg)

        repo_path = Path(self._repositories[repo_key])
        if not repo_path.is_dir():
            msg = f"リポジトリパスが存在しません: repo_key={repo_key}"
            raise RemoteControlRepositoryNotFoundError(msg)

        claude_bin = shutil.which("claude")
        if claude_bin is None:
            msg = "claude コマンドが PATH 上に見つかりません。Claude Code CLI をインストールしてください。"
            raise RemoteControlBinaryNotFoundError(msg)

        # defense in depth: 設定層 (_parse_remote_control_repositories) で文字種制限済みだが、
        # サービス層単独で使われる場合（テスト等）にもパストラバーサルを防ぐため再度サニタイズする
        safe_repo_key = re.sub(r"[^A-Za-z0-9._-]", "_", repo_key) or "repo"
        session_name = f"slack-{safe_repo_key}-{int(time.time())}"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{session_name}.log"

        # log_file の Python 側バッファリング指定は子プロセスの書き込みには無関係
        # （fd 経由で直接 OS に書き込まれるため）。テキストモードは UTF-8 受け取りの意図表明のみ
        # Slack 経由のリモートセッションでは「ドキュメント確認依頼時の自動オープン」
        # （~/.claude/rules/invariants.md）が機能しないため、Claude 側が確認動線を
        # 切替えるためのマーカーを bot 環境継承時に追加する。同名キーがあれば本値で確定する
        child_env = {**os.environ, "REMOTE_SLACK_SESSION": "1"}
        # bypassPermissions: Slack 起動のセッションは Yes/No 確認に応答できないため許可確認を回避する
        launch_args: tuple[str, ...] = (
            claude_bin, "remote-control",
            "--name", session_name,
            "--permission-mode", "bypassPermissions",
        )
        log_file = log_path.open("w", encoding="utf-8")
        launch_failed = False
        try:
            if sys.platform == "win32":
                creationflags = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
                ) | getattr(subprocess, "DETACHED_PROCESS", 0)
                proc = await asyncio.create_subprocess_exec(
                    *launch_args,
                    cwd=str(repo_path),
                    stdout=log_file.fileno(),
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                    env=child_env,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *launch_args,
                    cwd=str(repo_path),
                    stdout=log_file.fileno(),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=child_env,
                )
        except Exception:
            launch_failed = True
            raise
        finally:
            log_file.close()
            # close 後に削除する（Windows ではオープン中のファイルは削除できないため、
            # 順序を逆にすると元の起動失敗例外が unlink エラーでマスクされる）
            if launch_failed:
                try:
                    log_path.unlink(missing_ok=True)
                except OSError:
                    # 削除失敗は元の起動失敗例外より重要ではないため握りつぶす
                    pass

        logger.info(
            "remote_control subprocess complete: pid=%s, repo_key=%s, session=%s, log=%s",
            proc.pid, repo_key, session_name, log_path,
        )

        url = await self._extract_url(log_path, proc)
        # POSIX で子プロセスが後に終了した際の zombie 化を防ぐため、
        # 終了は監視しないが回収だけ非同期で受け取る（kill はしない）
        self._active_pids.add(proc.pid)
        wait_task = asyncio.create_task(proc.wait())
        wait_task.add_done_callback(
            lambda _t: self._active_pids.discard(proc.pid),
        )
        logger.info(
            "remote_control launch complete: repo_key=%s, session=%s, pid=%s",
            repo_key, session_name, proc.pid,
        )
        return RemoteControlLaunchResult(
            session_name=session_name,
            connect_url=url,
            log_path=log_path,
        )

    async def _extract_url(
        self,
        log_path: Path,
        proc: asyncio.subprocess.Process,
    ) -> str:
        """ログファイルをポーリングし接続 URL を抽出する."""
        deadline = time.monotonic() + self._url_timeout
        while True:
            if log_path.exists():
                try:
                    content = log_path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
                match = _URL_PATTERN.search(content)
                if match:
                    return match.group(0)

            if proc.returncode is not None:
                msg = (
                    "claude remote-control プロセスが URL 出力前に終了しました。"
                    f"終了コード: {proc.returncode}"
                )
                raise RemoteControlProcessExitedError(msg)

            if time.monotonic() >= deadline:
                # 公開チャンネルでの実行を想定し、Slack 向け応答にホストの絶対パスを
                # 露出させない。詳細な絶対パスは管理者向けにサーバーログに残す
                logger.warning(
                    "remote-control URL extraction timed out: timeout=%ss, log_path=%s",
                    self._url_timeout, log_path,
                )
                msg = (
                    f"接続 URL の抽出がタイムアウトしました（{self._url_timeout}秒）。"
                    f"ログファイル名: {log_path.name}"
                )
                raise RemoteControlURLTimeoutError(msg)

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

