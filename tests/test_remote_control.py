"""RemoteControlLauncher のテスト (Issue #831)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.services.remote_control import (
    RemoteControlBinaryNotFoundError,
    RemoteControlError,
    RemoteControlLauncher,
    RemoteControlRepositoryNotFoundError,
)


def _make_launcher(
    repositories: dict[str, str] | None = None,
    log_dir: Path | None = None,
    url_timeout: int = 5,
) -> RemoteControlLauncher:
    return RemoteControlLauncher(
        repositories=repositories or {},
        log_dir=log_dir or Path(".tmp/remote-control-test"),
        url_timeout=url_timeout,
    )


async def test_launch_unknown_repo_key_raises() -> None:
    """未登録 repo-key を指定すると RemoteControlError が発生."""
    launcher = _make_launcher(repositories={"foo": "/repo"})
    with pytest.raises(RemoteControlError) as exc_info:
        await launcher.launch("bar")
    assert "未登録のリポジトリキー" in str(exc_info.value)
    assert "foo" in str(exc_info.value)  # 登録済みリストに含まれる


async def test_launch_nonexistent_path_raises(tmp_path: Path) -> None:
    """allowlist の絶対パスが存在しない場合に RepositoryNotFoundError が発生."""
    launcher = _make_launcher(
        repositories={"foo": str(tmp_path / "does-not-exist")},
    )
    with pytest.raises(RemoteControlRepositoryNotFoundError):
        await launcher.launch("foo")


async def test_launch_claude_binary_missing(tmp_path: Path) -> None:
    """claude が PATH 上に無い場合に BinaryNotFoundError が発生."""
    launcher = _make_launcher(repositories={"foo": str(tmp_path)})
    with patch("src.services.remote_control.shutil.which", return_value=None):
        with pytest.raises(RemoteControlBinaryNotFoundError):
            await launcher.launch("foo")


def test_get_repositories_returns_copy() -> None:
    """get_repositories は内部 dict のコピーを返す（呼び出し側変更で内部が壊れない）."""
    launcher = _make_launcher(repositories={"foo": "/repo"})
    out = launcher.get_repositories()
    out["bar"] = "/another"
    assert "bar" not in launcher.get_repositories()


# --- _extract_url の単体テスト ---


class _FakeProc:
    """asyncio.subprocess.Process のテスト用ダミー."""

    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode


async def test_extract_url_finds_existing_url(tmp_path: Path) -> None:
    """ログに URL が既に書き込まれていれば即座に抽出できる."""
    log_path = tmp_path / "session.log"
    log_path.write_text(
        "Connecting...\n"
        "Continue coding in https://claude.ai/code?environment=env_01ABC123XYZ\n"
        "more output\n",
        encoding="utf-8",
    )
    launcher = _make_launcher(url_timeout=2)
    proc = _FakeProc(returncode=None)

    url = await launcher._extract_url(log_path, proc)  # type: ignore[arg-type]

    assert url == "https://claude.ai/code?environment=env_01ABC123XYZ"


async def test_extract_url_timeout(tmp_path: Path) -> None:
    """ログに URL が現れない場合、タイムアウトする."""
    log_path = tmp_path / "session.log"
    log_path.write_text("no url here\n", encoding="utf-8")
    launcher = _make_launcher(url_timeout=1)
    proc = _FakeProc(returncode=None)

    from src.services.remote_control import RemoteControlURLTimeoutError

    with pytest.raises(RemoteControlURLTimeoutError) as exc_info:
        await launcher._extract_url(log_path, proc)  # type: ignore[arg-type]
    assert str(log_path) in str(exc_info.value)


async def test_extract_url_process_exited_before_url(tmp_path: Path) -> None:
    """子プロセスが URL 出力前に終了した場合、ProcessExitedError が発生."""
    log_path = tmp_path / "session.log"
    log_path.write_text("startup error\n", encoding="utf-8")
    launcher = _make_launcher(url_timeout=10)
    proc = _FakeProc(returncode=1)

    from src.services.remote_control import RemoteControlProcessExitedError

    with pytest.raises(RemoteControlProcessExitedError) as exc_info:
        await launcher._extract_url(log_path, proc)  # type: ignore[arg-type]
    assert "終了コード: 1" in str(exc_info.value)


async def test_extract_url_handles_missing_log_file_initially(tmp_path: Path) -> None:
    """ログファイルが未作成でも、後から作成されれば抽出される."""
    import asyncio

    log_path = tmp_path / "session.log"
    launcher = _make_launcher(url_timeout=3)
    proc = _FakeProc(returncode=None)

    async def write_url_after_delay() -> None:
        await asyncio.sleep(0.6)
        log_path.write_text(
            "https://claude.ai/code?environment=env_01XYZ789\n",
            encoding="utf-8",
        )

    write_task = asyncio.create_task(write_url_after_delay())
    url = await launcher._extract_url(log_path, proc)  # type: ignore[arg-type]
    await write_task

    assert url == "https://claude.ai/code?environment=env_01XYZ789"
