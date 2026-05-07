"""プロセスガードのテスト (Issue #136).

仕様: docs/specs/infrastructure/bot-process-guard.md
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.process_guard import (
    check_already_running,
    cleanup_children,
    is_process_alive,
    read_pid_file,
    remove_pid_file,
    write_pid_file,
)


# ---------------------------------------------------------------------------
# PIDファイル管理テスト
# ---------------------------------------------------------------------------


class TestPidFile:
    """PIDファイルの読み書き・削除."""

    def test_write_pid_file_creates_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bot起動時にPIDファイルが作成される."""
        pid_file = tmp_path / "bot.pid"
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        write_pid_file()

        assert pid_file.exists()
        assert pid_file.read_text(encoding="utf-8") == str(os.getpid())

    def test_remove_pid_file_deletes_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bot終了時にPIDファイルが削除される."""
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
# プロセス生存確認テスト
# ---------------------------------------------------------------------------


class TestIsProcessAlive:
    """プロセス生存確認."""

    def test_alive_process_returns_true(self) -> None:
        """psutil.pid_exists が True を返す場合は True."""
        with patch("src.process_guard.psutil.pid_exists", return_value=True):
            assert is_process_alive(12345) is True

    def test_dead_process_returns_false(self) -> None:
        """psutil.pid_exists が False を返す場合は False."""
        with patch("src.process_guard.psutil.pid_exists", return_value=False):
            assert is_process_alive(12345) is False


# ---------------------------------------------------------------------------
# 重複起動チェックテスト
# ---------------------------------------------------------------------------


class TestCheckAlreadyRunning:
    """重複起動チェック."""

    def test_exits_when_process_alive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """既にBotが起動中の場合、sys.exit(1) で終了する."""
        pid_file = tmp_path / "bot.pid"
        pid_file.write_text("12345", encoding="utf-8")
        monkeypatch.setattr("src.process_guard.PID_FILE", pid_file)

        with (
            patch("src.process_guard.is_process_alive", return_value=True),
            pytest.raises(SystemExit, match="1"),
        ):
            check_already_running()

    def test_continues_with_stale_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """stale PIDの場合、PIDファイルを削除して正常通過."""
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
    """子プロセスクリーンアップ."""

    @staticmethod
    def _make_child(pid: int) -> MagicMock:
        child = MagicMock()
        child.pid = pid
        return child

    def test_terminates_all_children(self) -> None:
        """子プロセスすべてに terminate() が送信される."""
        child_a = self._make_child(111)
        child_b = self._make_child(222)
        mock_parent = MagicMock()
        mock_parent.children.return_value = [child_a, child_b]

        with patch("src.process_guard.psutil.Process", return_value=mock_parent):
            cleanup_children()

        mock_parent.children.assert_called_once_with(recursive=False)
        child_a.terminate.assert_called_once()
        child_b.terminate.assert_called_once()

    def test_no_children_is_noop(self) -> None:
        """子プロセスがない場合は何もしない."""
        mock_parent = MagicMock()
        mock_parent.children.return_value = []

        with patch("src.process_guard.psutil.Process", return_value=mock_parent):
            cleanup_children()  # 例外が発生しないこと

    def test_no_such_process_is_silent(self) -> None:
        """対象プロセスが存在しない場合は静かにスキップする."""

        with patch(
            "src.process_guard.psutil.Process",
            side_effect=psutil.NoSuchProcess(pid=12345),
        ):
            cleanup_children()  # 例外が発生しないこと

    def test_access_denied_is_silent(self) -> None:
        """親プロセスの情報取得で権限エラーが起きた場合も例外を伝播しない."""

        with patch(
            "src.process_guard.psutil.Process",
            side_effect=psutil.AccessDenied(pid=12345),
        ):
            cleanup_children()  # 例外が発生しないこと

    def test_child_already_gone_is_silent(self) -> None:
        """terminate 中に子プロセスが消えても例外を伝播しない."""

        child = self._make_child(111)
        child.terminate.side_effect = psutil.NoSuchProcess(pid=111)
        mock_parent = MagicMock()
        mock_parent.children.return_value = [child]

        with patch("src.process_guard.psutil.Process", return_value=mock_parent):
            cleanup_children()  # 例外が発生しないこと

    def test_child_access_denied_is_silent(self) -> None:
        """terminate で権限エラーが起きても例外を伝播せず次の子に進む."""

        child_a = self._make_child(111)
        child_a.terminate.side_effect = psutil.AccessDenied(pid=111)
        child_b = self._make_child(222)
        mock_parent = MagicMock()
        mock_parent.children.return_value = [child_a, child_b]

        with patch("src.process_guard.psutil.Process", return_value=mock_parent):
            cleanup_children()

        child_b.terminate.assert_called_once()  # 後続の子は処理される

    def test_excludes_protected_pids(self) -> None:
        """exclude_pids に含まれる子プロセスは terminate されない."""
        child_a = self._make_child(111)
        child_b = self._make_child(222)
        child_c = self._make_child(333)
        mock_parent = MagicMock()
        mock_parent.children.return_value = [child_a, child_b, child_c]

        with patch("src.process_guard.psutil.Process", return_value=mock_parent):
            cleanup_children(exclude_pids={222})

        child_a.terminate.assert_called_once()
        child_b.terminate.assert_not_called()
        child_c.terminate.assert_called_once()
