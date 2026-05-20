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


def _write_result(repo_path: Path, payload: dict[str, object]) -> Path:
    """テスト用に repo_path 配下にレスポンスファイルを作成する."""
    result_path = repo_path / RESULT_FILE_RELATIVE
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(payload), encoding="utf-8")
    return result_path


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
    _write_result(tmp_path, {
        "status": "ok",
        "article_path": "articles/hatena/2026-05-20-diary.md",
        "draft_url": "https://example.hatenablog.com/entry/2026/05/20/152523",
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
        new=AsyncMock(return_value=_stub_proc(returncode=0)),
    ):
        result = await publisher.publish_diary()

    assert isinstance(result, ArticlePublishResult)
    assert result.status == "ok"
    assert result.article_path == "articles/hatena/2026-05-20-diary.md"
    assert result.draft_url == "https://example.hatenablog.com/entry/2026/05/20/152523"
    assert result.pr_url == "https://github.com/becky3/article-writer/pull/71"
    assert result.worktree_removed is True
    assert result.worktree_path is None


async def test_publish_diary_passes_expected_args(tmp_path: Path) -> None:
    """claude -p に '/auto-publish-diary' + --dangerously-skip-permissions が渡される."""
    _write_result(tmp_path, {"status": "ok"})
    publisher = _make_publisher(tmp_path)
    mock_exec = AsyncMock(return_value=_stub_proc(returncode=0))
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


async def test_publish_diary_failure_returns_failure(tmp_path: Path) -> None:
    """終了コード非 0 + レスポンスファイル解析成功時、ArticlePublishFailure が返る."""
    _write_result(tmp_path, {
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
        new=AsyncMock(return_value=_stub_proc(returncode=1)),
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
    result_path = tmp_path / RESULT_FILE_RELATIVE
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("{not valid json", encoding="utf-8")
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_stub_proc(returncode=1)),
    ):
        with pytest.raises(ArticlePublishResponseFileError) as exc_info:
            await publisher.publish_diary()
    err = exc_info.value
    assert "JSON 解析に失敗" in err.reason
    assert err.exit_code == 1


async def test_publish_diary_non_dict_json_raises(tmp_path: Path) -> None:
    """レスポンスファイルの JSON が dict でない場合、ResponseFileError が発生する."""
    result_path = tmp_path / RESULT_FILE_RELATIVE
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('["array", "is", "wrong"]', encoding="utf-8")
    publisher = _make_publisher(tmp_path)
    with patch(
        "src.services.article_publisher.shutil.which", return_value="/usr/bin/claude",
    ), patch(
        "src.services.article_publisher.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=_stub_proc(returncode=0)),
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
