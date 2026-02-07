"""プロセスガードのテスト (Issue #136).

仕様: docs/specs/bot-process-guard.md
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.process_guard import (
    _is_process_alive_unix,
    _is_process_alive_windows,
    check_already_running,
    cleanup_children,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)


# ---------------------------------------------------------------------------
# PIDファイル管理テスト
# ---------------------------------------------------------------------------


class TestPidFile:
    """AC1, AC2: PIDファイルの読み書き・削除."""

    def test_ac1_write_pid_file_creates_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC1: Bot起動時にPIDファイルが作成される."""
        pid_file = tmp_path / "bot.pid"
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        write_pid_file()

        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == str(os.getpid())

    def test_ac2_remove_pid_file_deletes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC2: Bot終了時にPIDファイルが削除される."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        remove_pid_file()

        assert not pid_file.exists()

    def test_remove_pid_file_missing_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PIDファイルが存在しない場合、remove_pid_fileは何もしない."""
        pid_file = tmp_path / "bot.pid"
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        remove_pid_file()  # 例外が発生しないこと

    def test_read_pid_file_returns_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PIDファイルからPIDを正しく読み取る."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        assert read_pid_file() == 12345

    def test_read_pid_file_returns_none_when_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PIDファイルが存在しない場合はNoneを返す."""
        pid_file = tmp_path / "bot.pid"
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        assert read_pid_file() is None

    def test_read_pid_file_returns_none_for_invalid_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PIDファイルの内容が不正な場合はNoneを返す."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("not-a-number", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        assert read_pid_file() is None

    def test_read_pid_file_returns_none_for_zero_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PID=0 は不正値としてNoneを返す."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("0", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        assert read_pid_file() is None

    def test_read_pid_file_returns_none_for_negative_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """負のPIDは不正値としてNoneを返す."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("-1", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        assert read_pid_file() is None

    def test_write_pid_file_exclusive_exits_when_alive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """排他作成: PIDファイルが既に存在し生存プロセスなら exit(1)."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        with (
            patch("src.process_guard.is_process_alive", return_value=True),
            pytest.raises(SystemExit, match="1"),
        ):
            write_pid_file()

    def test_write_pid_file_exclusive_recovers_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """排他作成: stale PIDファイルがあれば削除して再作成する."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("99999", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        with patch("src.process_guard.is_process_alive", return_value=False):
            write_pid_file()

        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == str(os.getpid())


# ---------------------------------------------------------------------------
# プロセス生存確認テスト (Unix)
# ---------------------------------------------------------------------------


class TestIsProcessAliveUnix:
    """AC6: Unix系OSでのプロセス生存確認."""

    def test_ac6_alive_process_returns_true(self) -> None:
        """os.kill(pid, 0) が成功した場合はTrue."""
        with patch("src.process_guard.os.kill") as mock_kill:
            mock_kill.return_value = None
            assert _is_process_alive_unix(12345) is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_ac6_dead_process_returns_false(self) -> None:
        """ProcessLookupError が発生した場合はFalse."""
        with patch("src.process_guard.os.kill") as mock_kill:
            mock_kill.side_effect = ProcessLookupError()
            assert _is_process_alive_unix(12345) is False

    def test_ac6_permission_error_returns_true(self) -> None:
        """PermissionError が発生した場合はTrue（プロセスは存在する）."""
        with patch("src.process_guard.os.kill") as mock_kill:
            mock_kill.side_effect = PermissionError()
            assert _is_process_alive_unix(12345) is True


# ---------------------------------------------------------------------------
# プロセス生存確認テスト (Windows)
# ---------------------------------------------------------------------------


class TestIsProcessAliveWindows:
    """AC5: Windowsでのプロセス生存確認."""

    def test_ac5_alive_process_returns_true(self) -> None:
        """tasklist出力にPIDが含まれている場合はTrue."""
        mock_result = MagicMock()
        mock_result.stdout = "python.exe                   12345 Console  1    50,000 K\n"
        with patch("src.process_guard.subprocess.run", return_value=mock_result):
            assert _is_process_alive_windows(12345) is True

    def test_ac5_dead_process_returns_false(self) -> None:
        """tasklist が "INFO: No tasks" を返す場合はFalse."""
        mock_result = MagicMock()
        mock_result.stdout = "INFO: No tasks are running which match the specified criteria.\n"
        with patch("src.process_guard.subprocess.run", return_value=mock_result):
            assert _is_process_alive_windows(12345) is False

    def test_ac5_tasklist_not_found_returns_false(self) -> None:
        """tasklistコマンドが見つからない場合はFalse."""
        with patch(
            "src.process_guard.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            assert _is_process_alive_windows(12345) is False

    def test_ac5_tasklist_timeout_returns_false(self) -> None:
        """tasklistがタイムアウトした場合はFalse."""
        with patch(
            "src.process_guard.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="tasklist", timeout=5),
        ):
            assert _is_process_alive_windows(12345) is False

    def test_ac5_pid_not_in_output_returns_false(self) -> None:
        """tasklist出力にPIDが含まれていない場合はFalse."""
        mock_result = MagicMock()
        mock_result.stdout = "python.exe                   99999 Console  1    50,000 K\n"
        with patch("src.process_guard.subprocess.run", return_value=mock_result):
            assert _is_process_alive_windows(12345) is False

    def test_ac5_partial_pid_match_returns_false(self) -> None:
        """PIDが別PIDの部分文字列として含まれる場合はFalse（誤判定防止）."""
        mock_result = MagicMock()
        # PID=123 を検索するが、出力には 12345 しかない
        mock_result.stdout = "python.exe                   12345 Console  1    50,000 K\n"
        with patch("src.process_guard.subprocess.run", return_value=mock_result):
            assert _is_process_alive_windows(123) is False


# ---------------------------------------------------------------------------
# 重複起動チェックテスト
# ---------------------------------------------------------------------------


class TestCheckAlreadyRunning:
    """AC3, AC4: 重複起動チェック."""

    def test_ac3_exits_when_process_alive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC3: 既にBotが起動中の場合、sys.exit(1) で終了する."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        with (
            patch("src.process_guard.is_process_alive", return_value=True),
            pytest.raises(SystemExit, match="1"),
        ):
            check_already_running()

    def test_ac4_continues_with_stale_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC4: stale PIDの場合、PIDファイルを削除して正常通過."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        with patch("src.process_guard.is_process_alive", return_value=False):
            check_already_running()  # 例外が発生しないこと

        assert not pid_file.exists()  # stale PIDファイルが削除されている

    def test_continues_when_no_pid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PIDファイルがない場合は正常通過."""
        pid_file = tmp_path / "bot.pid"
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        check_already_running()  # 例外が発生しないこと


# ---------------------------------------------------------------------------
# 子プロセスクリーンアップテスト
# ---------------------------------------------------------------------------


class TestCleanupChildren:
    """AC7, AC8: 子プロセスクリーンアップ."""

    def test_ac7_unix_cleanup_sends_sigterm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC7 (Unix): 子プロセスにSIGTERMを送信する."""
        import signal as sig

        mock_result = MagicMock()
        mock_result.stdout = "111\n222\n"
        monkeypatch.setattr("sys.platform", "linux")

        with (
            patch("src.process_guard.subprocess.run", return_value=mock_result),
            patch("src.process_guard.os.kill") as mock_kill,
        ):
            cleanup_children()
            assert mock_kill.call_count == 2
            mock_kill.assert_any_call(111, sig.SIGTERM)
            mock_kill.assert_any_call(222, sig.SIGTERM)

    def test_ac7_windows_cleanup_uses_taskkill(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC7 (Windows): wmic + taskkill で子プロセスを停止する."""
        wmic_result = MagicMock()
        wmic_result.stdout = "ProcessId\n111\n222\n\n"
        taskkill_result = MagicMock()
        monkeypatch.setattr("sys.platform", "win32")

        with patch("src.process_guard.subprocess.run") as mock_run:
            mock_run.side_effect = [wmic_result, taskkill_result, taskkill_result]
            cleanup_children()

            # wmic 1回 + taskkill 2回 = 3回
            assert mock_run.call_count == 3

    def test_ac8_cleanup_failure_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC8: クリーンアップ失敗時に例外を送出しない."""
        monkeypatch.setattr("sys.platform", "linux")

        with patch(
            "src.process_guard.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            cleanup_children()  # 例外が発生しないこと

    def test_unix_no_children(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """子プロセスがない場合は何もしない."""
        mock_result = MagicMock()
        mock_result.stdout = ""
        monkeypatch.setattr("sys.platform", "linux")

        with (
            patch("src.process_guard.subprocess.run", return_value=mock_result),
            patch("src.process_guard.os.kill") as mock_kill,
        ):
            cleanup_children()
            mock_kill.assert_not_called()

    def test_windows_wmic_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Windows: wmicが見つからない場合はスキップ."""
        monkeypatch.setattr("sys.platform", "win32")

        with patch(
            "src.process_guard.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            cleanup_children()  # 例外が発生しないこと
