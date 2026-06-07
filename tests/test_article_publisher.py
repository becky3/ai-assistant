"""ArticleWriterPublisher のテスト (#841).

テスト方針:
- claude -p のプロセス呼び出しを subprocess モックで検証する
- レスポンスファイル（`.tmp/auto-publish-diary/result.json`）の読み取り成功/失敗、
  終了コード判定、タイムアウト、引数構成を検証する
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.article_publisher import (
    RESULT_FILE_RELATIVE,
    ArticlePublishBinaryNotFoundError,
    ArticlePublishFailure,
    ArticlePublishRepositoryNotFoundError,
    ArticlePublishResponseFileError,
    ArticlePublishResult,
    ArticlePublishTimeoutError,
    ArticleWriterPublisher,
)


def _make_publisher(
    repo_path: Path,
    timeout: int = 60,
) -> ArticleWriterPublisher:
    return ArticleWriterPublisher(repo_path=repo_path, timeout=timeout)


def _stub_proc(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _make_subprocess_mock_writing_result(
    repo_path: Path,
    payload_text: str | None,
    returncode: int = 0,
    stdout: bytes = b"",
) -> AsyncMock:
    """create_subprocess_exec のモック.

    呼び出されたタイミングで result.json を書き込む（実際のスキル動作のシミュレーション）。
    `payload_text=None` の場合は書き込みをスキップ（result.json 不在ケース用）。
    """
    result_path = repo_path / RESULT_FILE_RELATIVE

    async def fake_exec(*_args: object, **_kwargs: object) -> AsyncMock:
        if payload_text is not None:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(payload_text, encoding="utf-8")
        return _stub_proc(stdout=stdout, returncode=returncode)

    return AsyncMock(side_effect=fake_exec)


async def test_publish_diary_nonexistent_repo_raises(tmp_path: Path) -> None:
    """ARTICLE_WRITER_REPO_PATH が存在しない場合に RepositoryNotFoundError が発生."""
    publisher = _make_publisher(tmp_path / "does-not-exist")
    with pytest.raises(ArticlePublishRepositoryNotFoundError):
        await publisher.publish_diary()


async def test_publish_diary_claude_binary_missing(tmp_path: Path) -> None:
    """claude が PATH 上に無い場合に BinaryNotFoundError が発生."""
    publisher = _make_publisher(tmp_path)
    with patch("src.services.article_publisher.shutil.which", return_value=None):
        with pytest.raises(ArticlePublishBinaryNotFoundError):
            await publisher.publish_diary()


async def test_publish_diary_success_reads_result_file(tmp_path: Path) -> None:
    """終了コード 0 + レスポンスファイル解析成功時、ArticlePublishResult が返る."""
    payload = json.dumps({
        "status": "ok",
        "article_path": "articles/hatena/2026-05-20-diary.md",
        "edit_url": "https://blog.hatena.ne.jp/example/example.hatenablog.com/edit?entry=1234567890",
        "public_url": "https://example.hatenablog.com/entry/2026/05/20/000000",
        "pr_url": "https://github.com/becky3/article-writer/pull/71",
        "merged": True,
        "worktree_removed": True,
        "worktree_path": None,
    })
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=_make_subprocess_mock_writing_result(tmp_path, payload, returncode=0),
    ):
        result = await publisher.publish_diary()

    assert isinstance(result, ArticlePublishResult)
    assert result.status == "ok"
    assert result.article_path == "articles/hatena/2026-05-20-diary.md"
    assert result.edit_url == "https://blog.hatena.ne.jp/example/example.hatenablog.com/edit?entry=1234567890"
    assert result.public_url == "https://example.hatenablog.com/entry/2026/05/20/000000"
    assert result.pr_url == "https://github.com/becky3/article-writer/pull/71"
    assert result.worktree_removed is True
    assert result.worktree_path is None


async def test_publish_diary_passes_expected_args(tmp_path: Path) -> None:
    """claude -p に '/auto-publish-diary' + --dangerously-skip-permissions が渡される."""
    mock_exec = _make_subprocess_mock_writing_result(
        tmp_path, json.dumps({"status": "ok"}), returncode=0,
    )
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec", new=mock_exec,
    ):
        await publisher.publish_diary()

    args, kwargs = mock_exec.call_args
    assert args[0] == "/usr/bin/claude"
    assert "-p" in args
    assert "/auto-publish-diary" in args
    assert "--dangerously-skip-permissions" in args
    assert kwargs["cwd"] == str(tmp_path)


async def test_publish_diary_status_error_with_zero_exit_returns_result(tmp_path: Path) -> None:
    """終了コード 0 + status=error の場合、ArticlePublishResult に error / failed_phase が入る (Issue #848).

    article-writer 側が exit_code=0 で status=error を返すケース（例: cleanup phase の失敗）でも、
    本リポは ArticlePublishResult として受け取り、error / failed_phase を表示側に渡せるようにする。
    表示側 (_format_article_success) が status="error" を検出して汎用エラー表示に分岐する。
    """
    payload = json.dumps({
        "status": "error",
        "failed_phase": "cleanup",
        "error": "gh pr merge failed: stale review",
        "worktree_path": "../article-writer-wt-foo",
        "merged": False,
        "worktree_removed": False,
    })
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=_make_subprocess_mock_writing_result(tmp_path, payload, returncode=0),
    ):
        result = await publisher.publish_diary()

    assert isinstance(result, ArticlePublishResult)
    assert result.status == "error"
    assert result.error == "gh pr merge failed: stale review"
    assert result.failed_phase == "cleanup"
    assert result.worktree_removed is False
    assert result.worktree_path == "../article-writer-wt-foo"


async def test_publish_diary_failure_returns_failure(tmp_path: Path) -> None:
    """終了コード非 0 + レスポンスファイル解析成功時、ArticlePublishFailure が返る."""
    payload = json.dumps({
        "status": "error",
        "failed_phase": "publish",
        "error": "phase publish failed",
        "worktree_path": "../article-writer-wt-foo",
        "merged": False,
    })
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=_make_subprocess_mock_writing_result(tmp_path, payload, returncode=1),
    ):
        result = await publisher.publish_diary()

    assert isinstance(result, ArticlePublishFailure)
    assert result.exit_code == 1
    assert result.raw_json["status"] == "error"
    assert result.raw_json["worktree_path"] == "../article-writer-wt-foo"


async def test_publish_diary_missing_result_file_raises(tmp_path: Path) -> None:
    """レスポンスファイルが書き出されなかった場合、ResponseFileError が発生する."""
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_stub_proc(
            stdout=b"some final response from claude\n", returncode=0,
        )),
    ):
        with pytest.raises(ArticlePublishResponseFileError) as exc_info:
            await publisher.publish_diary()
    err = exc_info.value
    assert "見つかりません" in err.reason
    assert err.exit_code == 0
    assert err.result_path == tmp_path / RESULT_FILE_RELATIVE
    assert "some final response" in err.stdout_tail


async def test_publish_diary_invalid_json_raises(tmp_path: Path) -> None:
    """レスポンスファイルが JSON として不正な場合、ResponseFileError が発生する."""
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=_make_subprocess_mock_writing_result(tmp_path, "{not valid json", returncode=1),
    ):
        with pytest.raises(ArticlePublishResponseFileError) as exc_info:
            await publisher.publish_diary()
    err = exc_info.value
    assert "JSON 解析に失敗" in err.reason
    assert err.exit_code == 1


async def test_publish_diary_non_dict_json_raises(tmp_path: Path) -> None:
    """レスポンスファイルの JSON が dict でない場合、ResponseFileError が発生する."""
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=_make_subprocess_mock_writing_result(tmp_path, '["array", "is", "wrong"]', returncode=0),
    ):
        with pytest.raises(ArticlePublishResponseFileError) as exc_info:
            await publisher.publish_diary()
    assert "dict ではありません" in exc_info.value.reason


async def test_publish_diary_timeout_raises(tmp_path: Path) -> None:
    """タイムアウト時に ArticlePublishTimeoutError が発生し子プロセスが kill される."""
    proc = AsyncMock()
    proc.communicate.side_effect = asyncio.TimeoutError()
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    publisher = _make_publisher(tmp_path, timeout=1)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ):
        with pytest.raises(ArticlePublishTimeoutError, match="タイムアウト"):
            await publisher.publish_diary()
    proc.kill.assert_called_once()


async def test_result_path_property_returns_absolute_path(tmp_path: Path) -> None:
    """result_path プロパティが親リポ + 相対パスの絶対パスを返す."""
    publisher = _make_publisher(tmp_path)
    assert publisher.result_path == tmp_path / RESULT_FILE_RELATIVE
    assert publisher.result_path.is_absolute()


async def test_publish_diary_removes_stale_result_file_before_launch(tmp_path: Path) -> None:
    """前回実行の result.json が残っている場合、起動直前に削除される（古い結果の誤読防止）."""
    # 前回の result.json を残置
    stale_path = tmp_path / RESULT_FILE_RELATIVE
    stale_path.parent.mkdir(parents=True, exist_ok=True)
    stale_path.write_text(
        json.dumps({"status": "ok", "pr_url": "https://stale/old/pull/0"}),
        encoding="utf-8",
    )

    publisher = _make_publisher(tmp_path)

    # subprocess が result.json を書き戻さない場合、削除されているため ResponseFileError になる
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_stub_proc(returncode=0)),
    ):
        with pytest.raises(ArticlePublishResponseFileError):
            await publisher.publish_diary()

    # 前回の result.json が削除されていることを確認（subprocess の stub が書き戻さないため）
    assert not stale_path.exists()
