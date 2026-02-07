"""プロセスガードのテスト
仕様: docs/specs/bot-process-guard.md
"""

from __future__ import annotations

import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.process_guard import (
    is_process_alive,
    kill_existing_process,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)


@pytest.fixture
def pid_file(tmp_path: Path) -> Path:
    """テスト用PIDファイルパス."""
    return tmp_path / "test_bot.pid"


class TestWritePidFile:
    """AC1: 起動時にPIDファイルが作成されること."""

    def test_ac1_pid_file_is_created(self, pid_file: Path) -> None:
        write_pid_file(pid_file)

        assert pid_file.exists()
        content = pid_file.read_text(encoding="utf-8").strip()
        assert content == str(os.getpid())

    def test_ac1_pid_file_contains_valid_pid(self, pid_file: Path) -> None:
        write_pid_file(pid_file)

        pid = int(pid_file.read_text(encoding="utf-8").strip())
        assert pid > 0


class TestRemovePidFile:
    """AC2: 正常終了時にPIDファイルが削除されること."""

    def test_ac2_pid_file_is_removed(self, pid_file: Path) -> None:
        write_pid_file(pid_file)
        assert pid_file.exists()

        remove_pid_file(pid_file)
        assert not pid_file.exists()

    def test_ac2_remove_nonexistent_pid_file(self, pid_file: Path) -> None:
        """存在しないPIDファイルの削除でエラーにならないこと."""
        remove_pid_file(pid_file)
        assert not pid_file.exists()


class TestReadPidFile:
    """PIDファイルの読み取りテスト."""

    def test_read_valid_pid(self, pid_file: Path) -> None:
        pid_file.write_text("12345", encoding="utf-8")

        result = read_pid_file(pid_file)
        assert result == 12345

    def test_read_nonexistent_file(self, pid_file: Path) -> None:
        result = read_pid_file(pid_file)
        assert result is None

    def test_read_invalid_content(self, pid_file: Path) -> None:
        pid_file.write_text("not_a_number", encoding="utf-8")

        result = read_pid_file(pid_file)
        assert result is None

    def test_read_negative_pid(self, pid_file: Path) -> None:
        pid_file.write_text("-1", encoding="utf-8")

        result = read_pid_file(pid_file)
        assert result is None

    def test_read_zero_pid(self, pid_file: Path) -> None:
        pid_file.write_text("0", encoding="utf-8")

        result = read_pid_file(pid_file)
        assert result is None

    def test_read_pid_with_whitespace(self, pid_file: Path) -> None:
        pid_file.write_text("  12345  \n", encoding="utf-8")

        result = read_pid_file(pid_file)
        assert result == 12345


class TestIsProcessAlive:
    """プロセス生存確認テスト."""

    def test_current_process_is_alive(self) -> None:
        assert is_process_alive(os.getpid()) is True

    def test_nonexistent_process(self) -> None:
        # PID 99999999 は通常存在しない
        assert is_process_alive(99999999) is False


class TestKillExistingProcess:
    """AC3, AC4: 既存プロセスの検出・停止テスト."""

    def test_ac3_kills_existing_process(self, pid_file: Path) -> None:
        """生存プロセスが記録されている場合、停止が試みられること."""
        pid_file.write_text("99999", encoding="utf-8")

        # 最初の呼び出し(生存確認)はTrue、kill後の確認はFalse
        with (
            patch("src.process_guard.is_process_alive", side_effect=[True, False]),
            patch("src.process_guard._kill_process_tree") as mock_kill,
            patch("src.process_guard.time"),
        ):
            kill_existing_process(pid_file)

        mock_kill.assert_called_once_with(99999)
        assert not pid_file.exists()

    def test_ac3_kill_failure_keeps_pid_file(self, pid_file: Path) -> None:
        """kill失敗時にPIDファイルが残りRuntimeErrorが発生すること."""
        pid_file.write_text("99999", encoding="utf-8")

        # kill後もプロセスが生存している場合
        with (
            patch("src.process_guard.is_process_alive", return_value=True),
            patch("src.process_guard._kill_process_tree"),
            patch("src.process_guard.time"),
            pytest.raises(RuntimeError, match="停止に失敗しました"),
        ):
            kill_existing_process(pid_file)

        # PIDファイルは削除されていないこと
        assert pid_file.exists()

    def test_ac4_stale_pid_file(self, pid_file: Path) -> None:
        """stale PIDファイル（プロセスが存在しない）の場合、PIDファイルのみ削除すること."""
        pid_file.write_text("99999999", encoding="utf-8")

        kill_existing_process(pid_file)

        assert not pid_file.exists()

    def test_no_pid_file(self, pid_file: Path) -> None:
        """PIDファイルが存在しない場合、何もしないこと."""
        kill_existing_process(pid_file)
        # エラーが発生しないことを確認

    def test_skip_own_pid(self, pid_file: Path) -> None:
        """自分自身のPIDが記録されている場合、停止しないこと."""
        pid_file.write_text(str(os.getpid()), encoding="utf-8")

        with patch("src.process_guard._kill_process_tree") as mock_kill:
            kill_existing_process(pid_file)

        mock_kill.assert_not_called()


class TestCleanupChildrenUnix:
    """AC5: 子プロセスクリーンアップ（Unix）のテスト."""

    def test_ac5_unix_children_are_killed(self) -> None:
        """子PIDが列挙され、SIGTERMが送信されること."""
        mock_result = MagicMock()
        mock_result.stdout = "1001\n1002\n"

        with (
            patch("src.process_guard.sys") as mock_sys,
            patch("subprocess.run", return_value=mock_result) as mock_run,
            patch("os.kill") as mock_kill,
        ):
            mock_sys.platform = "linux"
            from src.process_guard import _cleanup_children_unix

            _cleanup_children_unix(12345)

        mock_run.assert_called_once()
        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(1001, signal.SIGTERM)
        mock_kill.assert_any_call(1002, signal.SIGTERM)

    def test_ac5_unix_no_children(self) -> None:
        """子プロセスがない場合に正常に終了すること."""
        mock_result = MagicMock()
        mock_result.stdout = ""

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("os.kill") as mock_kill,
        ):
            from src.process_guard import _cleanup_children_unix

            _cleanup_children_unix(12345)

        mock_kill.assert_not_called()

    def test_ac5_unix_pgrep_not_found(self) -> None:
        """pgrepが存在しない場合にエラーにならないこと."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            from src.process_guard import _cleanup_children_unix

            _cleanup_children_unix(12345)  # 例外が発生しないこと

    def test_ac5_unix_child_already_dead(self) -> None:
        """子プロセスが既に終了している場合にエラーにならないこと."""
        mock_result = MagicMock()
        mock_result.stdout = "1001\n"

        with (
            patch("subprocess.run", return_value=mock_result),
            patch("os.kill", side_effect=ProcessLookupError),
        ):
            from src.process_guard import _cleanup_children_unix

            _cleanup_children_unix(12345)  # 例外が発生しないこと


class TestCleanupChildrenWindows:
    """AC5: 子プロセスクリーンアップ（Windows）のテスト."""

    def test_ac5_windows_children_are_killed(self) -> None:
        """子PIDが列挙され、taskkillで停止されること."""
        wmic_result = MagicMock()
        wmic_result.stdout = "ProcessId\n2001\n2002\n"

        taskkill_result = MagicMock()

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            if cmd[0] == "wmic":
                return wmic_result
            return taskkill_result

        with patch("subprocess.run", side_effect=mock_run) as mock_subprocess:
            from src.process_guard import _cleanup_children_windows

            _cleanup_children_windows(12345)

        # wmic 1回 + taskkill 2回 = 3回
        assert mock_subprocess.call_count == 3

    def test_ac5_windows_wmic_not_found(self) -> None:
        """wmicが存在しない場合にエラーにならないこと."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            from src.process_guard import _cleanup_children_windows

            _cleanup_children_windows(12345)  # 例外が発生しないこと

    def test_ac5_windows_taskkill_not_found(self) -> None:
        """taskkillが存在しない場合にエラーにならないこと."""
        wmic_result = MagicMock()
        wmic_result.stdout = "ProcessId\n2001\n"

        call_count = 0

        def mock_run(cmd: list[str], **kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if cmd[0] == "wmic":
                return wmic_result
            raise FileNotFoundError

        with patch("subprocess.run", side_effect=mock_run):
            from src.process_guard import _cleanup_children_windows

            _cleanup_children_windows(12345)  # 例外が発生しないこと
