"""RemoteControlLauncher のテスト (Issue #831)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_get_active_pids_initially_empty() -> None:
    """起動前の get_active_pids は空集合."""
    launcher = _make_launcher(repositories={"foo": "/repo"})
    assert launcher.get_active_pids() == set()


def test_get_active_pids_returns_copy() -> None:
    """get_active_pids が返す集合への変更は内部状態に影響しない."""
    launcher = _make_launcher(repositories={"foo": "/repo"})
    out = launcher.get_active_pids()
    out.add(12345)
    assert launcher.get_active_pids() == set()


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
    """ログに URL が現れない場合、タイムアウトする.

    Slack 向けメッセージにはファイル名のみ含まれ、絶対パスは含まれない（情報露出防止）。
    """
    log_path = tmp_path / "session.log"
    log_path.write_text("no url here\n", encoding="utf-8")
    launcher = _make_launcher(url_timeout=1)
    proc = _FakeProc(returncode=None)

    from src.services.remote_control import RemoteControlURLTimeoutError

    with pytest.raises(RemoteControlURLTimeoutError) as exc_info:
        await launcher._extract_url(log_path, proc)  # type: ignore[arg-type]
    msg = str(exc_info.value)
    assert log_path.name in msg
    assert str(tmp_path) not in msg


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


# --- 起動引数・環境変数の検証 (Issue #839) ---


@pytest.mark.parametrize("platform", ["win32", "linux"])
async def test_launch_passes_bypass_permissions_and_marker_env(
    tmp_path: Path, platform: str,
) -> None:
    """Win/POSIX 両分岐で起動引数に --permission-mode bypassPermissions が含まれ、
    子プロセス env に REMOTE_SLACK_SESSION=1 が注入され、親環境の PATH が継承される.
    """
    launcher = _make_launcher(
        repositories={"foo": str(tmp_path)},
        log_dir=tmp_path / "logs",
    )

    fake_proc = MagicMock()
    fake_proc.pid = 12345
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.returncode = None

    with patch(
        "src.services.remote_control.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=fake_proc),
    ) as mock_exec, patch(
        "src.services.remote_control.shutil.which",
        return_value="/usr/bin/claude",
    ), patch(
        "src.services.remote_control.sys.platform", platform,
    ), patch.object(
        launcher,
        "_extract_url",
        new=AsyncMock(return_value="https://claude.ai/code?environment=env_01TEST"),
    ), patch.dict(
        "src.services.remote_control.os.environ",
        {"PATH": "/usr/bin"},
        clear=False,
    ):
        await launcher.launch("foo")

    args, kwargs = mock_exec.call_args
    assert "--permission-mode" in args
    perm_idx = args.index("--permission-mode")
    assert args[perm_idx + 1] == "bypassPermissions"
    assert "--name" in args  # 既存仕様: セッション名指定は維持
    env = kwargs["env"]
    assert env["REMOTE_SLACK_SESSION"] == "1"
    assert env["PATH"] == "/usr/bin"  # 親環境の継承を確認
