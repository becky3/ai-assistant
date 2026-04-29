"""Remote Control 起動サービス
仕様: docs/specs/features/remote-control-launch.md

claude remote-control をデタッチ起動し、ログから接続 URL を抽出する。
"""

from __future__ import annotations

import asyncio
import logging
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

    def get_repositories(self) -> dict[str, str]:
        """登録済み repo allowlist を返す."""
        return dict(self._repositories)

    async def launch(self, repo_key: str) -> RemoteControlLaunchResult:
        """指定 repo-key で claude remote-control を起動し、接続 URL を返す."""
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

        session_name = f"slack-{repo_key}-{int(time.time())}"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._log_dir / f"{session_name}.log"

        # log_file の Python 側バッファリング指定は子プロセスの書き込みには無関係
        # （fd 経由で直接 OS に書き込まれるため）。テキストモードは UTF-8 受け取りの意図表明のみ
        log_file = log_path.open("w", encoding="utf-8")
        try:
            if sys.platform == "win32":
                creationflags = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
                ) | getattr(subprocess, "DETACHED_PROCESS", 0)
                proc = await asyncio.create_subprocess_exec(
                    claude_bin, "remote-control", "--name", session_name,
                    cwd=str(repo_path),
                    stdout=log_file.fileno(),
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    claude_bin, "remote-control", "--name", session_name,
                    cwd=str(repo_path),
                    stdout=log_file.fileno(),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except Exception:
            # 起動自体が失敗した場合、空のログファイルを残さない
            log_path.unlink(missing_ok=True)
            raise
        finally:
            log_file.close()

        logger.info(
            "remote-control launched: pid=%s, repo_key=%s, session=%s, log=%s",
            proc.pid, repo_key, session_name, log_path,
        )

        url = await self._extract_url(log_path, proc)
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
                msg = (
                    f"接続 URL の抽出がタイムアウトしました（{self._url_timeout}秒）。"
                    f"ログファイルを直接確認してください: {log_path}"
                )
                raise RemoteControlURLTimeoutError(msg)

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

