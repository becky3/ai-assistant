"""記事自動投稿サービス
仕様: docs/specs/features/article-publishing.md

article-writer リポジトリで `claude -p '/auto-publish-diary'` を起動し、
親リポ直下のレスポンスファイル（`.tmp/auto-publish-diary/result.json`）を結果 dataclass にパースする。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# article-writer 側 `/auto-publish-diary` スキル名（ハードコード固定。外部入力から組み立てない）
_AUTO_PUBLISH_DIARY_SKILL = "/auto-publish-diary"

# レスポンスファイルの親リポ相対パス（article-writer 側スキルとの SSoT 結合）
# 親リポ固定の理由: worktree は Phase 4 で削除されるため、worktree 内に置くと cleanup で消える
RESULT_FILE_RELATIVE = Path(".tmp") / "auto-publish-diary" / "result.json"


class ArticlePublishError(Exception):
    """記事自動投稿の共通エラー."""


class ArticlePublishBinaryNotFoundError(ArticlePublishError):
    """claude 実行ファイルが PATH 上に存在しない."""


class ArticlePublishRepositoryNotFoundError(ArticlePublishError):
    """ARTICLE_WRITER_REPO_PATH のパスがディレクトリとして存在しない."""


class ArticlePublishTimeoutError(ArticlePublishError):
    """claude -p の実行がタイムアウトした."""


class ArticlePublishResponseFileError(ArticlePublishError):
    """レスポンスファイルが読めない・解析できない（仕様書「実行結果の解析失敗時」出力に対応）.

    Slack 通知用に終了コードと診断情報を構造化して保持する。
    """

    def __init__(
        self,
        reason: str,
        exit_code: int,
        stdout_tail: str,
        result_path: Path,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code
        self.stdout_tail = stdout_tail
        self.result_path = result_path


@dataclass(frozen=True)
class ArticlePublishResult:
    """起動成功時の結果（result.json のうち本機能が依存するフィールド）."""

    status: str
    article_path: str | None
    draft_url: str | None
    pr_url: str | None
    worktree_removed: bool
    worktree_path: str | None


@dataclass(frozen=True)
class ArticlePublishFailure:
    """終了コード非 0 + result.json 解析に成功した失敗結果."""

    exit_code: int
    raw_json: dict[str, object]


class ArticleWriterPublisher:
    """`claude -p '/auto-publish-diary'` を起動して結果を返すサービス.

    仕様: docs/specs/features/article-publishing.md
    """

    def __init__(self, repo_path: Path, timeout: int) -> None:
        self._repo_path = repo_path
        self._timeout = timeout

    @property
    def repo_path(self) -> Path:
        """設定された article-writer リポジトリパス."""
        return self._repo_path

    @property
    def timeout(self) -> int:
        """設定されたタイムアウト秒数."""
        return self._timeout

    @property
    def result_path(self) -> Path:
        """レスポンスファイルの絶対パス."""
        return self._repo_path / RESULT_FILE_RELATIVE

    async def publish_diary(self) -> ArticlePublishResult | ArticlePublishFailure:
        """`/auto-publish-diary` を起動し、結果を返す.

        Returns:
            終了コード 0 + result.json 解析成功時: ArticlePublishResult
            終了コード非 0 + result.json 解析成功時: ArticlePublishFailure

        Raises:
            ArticlePublishRepositoryNotFoundError: repo_path が実在しない
            ArticlePublishBinaryNotFoundError: claude が PATH 上に無い
            ArticlePublishTimeoutError: タイムアウト
            ArticlePublishResponseFileError: result.json 不在 / 解析失敗
        """
        logger.info("article_publish start: repo_path=%s", self._repo_path)
        if not self._repo_path.is_dir():
            msg = f"ARTICLE_WRITER_REPO_PATH のディレクトリが存在しません: {self._repo_path}"
            raise ArticlePublishRepositoryNotFoundError(msg)

        claude_bin = shutil.which("claude")
        if claude_bin is None:
            msg = "claude コマンドが PATH 上に見つかりません。Claude Code CLI をインストールしてください。"
            raise ArticlePublishBinaryNotFoundError(msg)

        cmd = (
            claude_bin, "-p", _AUTO_PUBLISH_DIARY_SKILL,
            "--dangerously-skip-permissions",
            "--output-format", "text",
        )

        # 防御的クリーンアップ: 前回実行の result.json が残っている状態で
        # 今回 subprocess が result.json 未更新のまま失敗（Phase 0 到達前のクラッシュ等）した場合、
        # 古い結果を誤読しないよう、起動直前に既存ファイルを削除する。
        # article-writer 側スキルも Phase 0 で同等の削除を行うが、ai-assistant 側でも二重に防御する
        result_path = self.result_path
        try:
            result_path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning(
                "article_publish failed to remove stale result file: %s, err=%s",
                result_path, e,
            )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self._repo_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            msg = f"claude -p '/auto-publish-diary' がタイムアウトしました（{self._timeout}秒）"
            logger.error(msg)
            raise ArticlePublishTimeoutError(msg) from None

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode if proc.returncode is not None else -1

        logger.info(
            "article_publish subprocess complete: exit_code=%d, stdout_len=%d",
            exit_code, len(stdout_text),
        )

        tail = _tail_lines(stdout_text, 10)

        if not result_path.is_file():
            reason = (
                f"レスポンスファイルが見つかりません: {RESULT_FILE_RELATIVE.as_posix()}"
            )
            logger.error(
                "article_publish response file missing: %s, exit_code=%d, stderr=%r",
                result_path, exit_code, stderr_text[:200],
            )
            raise ArticlePublishResponseFileError(
                reason=reason, exit_code=exit_code, stdout_tail=tail,
                result_path=result_path,
            )

        try:
            raw_text = result_path.read_text(encoding="utf-8")
        except OSError as e:
            reason = f"レスポンスファイルの読み取りに失敗しました: {e}"
            logger.error("article_publish response file read failed: %s", reason)
            raise ArticlePublishResponseFileError(
                reason=reason, exit_code=exit_code, stdout_tail=tail,
                result_path=result_path,
            ) from e

        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as e:
            reason = f"レスポンスファイルの JSON 解析に失敗しました: {e}"
            logger.error("article_publish response file parse failed: %s", reason)
            raise ArticlePublishResponseFileError(
                reason=reason, exit_code=exit_code, stdout_tail=tail,
                result_path=result_path,
            ) from e

        if not isinstance(payload, dict):
            reason = (
                f"レスポンスファイルの JSON が dict ではありません: "
                f"type={type(payload).__name__}"
            )
            logger.error("article_publish response file shape error: %s", reason)
            raise ArticlePublishResponseFileError(
                reason=reason, exit_code=exit_code, stdout_tail=tail,
                result_path=result_path,
            )

        if exit_code != 0:
            logger.warning("article_publish failure: exit_code=%d", exit_code)
            return ArticlePublishFailure(exit_code=exit_code, raw_json=payload)

        result = ArticlePublishResult(
            status=str(payload.get("status", "")),
            article_path=_optional_str(payload.get("article_path")),
            draft_url=_optional_str(payload.get("draft_url")),
            pr_url=_optional_str(payload.get("pr_url")),
            worktree_removed=bool(payload.get("worktree_removed", False)),
            worktree_path=_optional_str(payload.get("worktree_path")),
        )
        logger.info(
            "article_publish complete: status=%s, draft_url=%s, pr_url=%s",
            result.status, result.draft_url, result.pr_url,
        )
        return result


def _tail_lines(text: str, n: int) -> str:
    """末尾 n 行を 1 つの文字列として返す（ログ表示用）."""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _optional_str(value: object) -> str | None:
    """JSON の値を任意文字列に変換する.

    `None` はそのまま `None` を返す。文字列はそのまま返す。
    非文字列（数値・bool 等）は `str(value)` で文字列化して返す（スキーマ違反データに対する防御的変換）。
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
