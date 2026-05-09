"""Claude CLI ワンショット実行
仕様: docs/specs/features/chat-response.md (claude モード)

Claude CLI (`claude -p`) を subprocess で呼び出し、応答テキストを返す。
プロンプトはコマンドライン引数の文字数制限を回避するため stdin 経由で渡す。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger(__name__)


async def call_claude(
    prompt: str,
    system_prompt: str,
    allowed_tools: str,
    timeout: int,
) -> str:
    """Claude CLI をワンショットで呼び出し、応答テキストを返す.

    Args:
        prompt: ユーザープロンプト（stdin 経由で渡す）
        system_prompt: システムプロンプト（--system-prompt フラグ）
        allowed_tools: 許可する MCP ツールパターン（空文字列の場合はフラグ省略）
        timeout: プロセスタイムアウト（秒）

    Returns:
        Claude CLI の応答テキスト

    Raises:
        RuntimeError: Claude CLI の実行に失敗した場合
        TimeoutError: タイムアウトした場合
    """
    cmd = ["claude", "-p", "--output-format", "text"]
    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if allowed_tools:
        cmd.extend(["--allowedTools", allowed_tools])

    logger.info("call_claude start: prompt_len=%d, timeout=%d", len(prompt), timeout)
    logger.debug("Claude CLI 実行: %s", " ".join(cmd[:4]))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        msg = f"Claude CLI がタイムアウトしました（{timeout}秒）"
        logger.error(msg)
        raise TimeoutError(msg)

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace").strip()
        msg = f"Claude CLI がエラーで終了しました（exit code {proc.returncode}）: {err_text}"
        logger.error(msg)
        raise RuntimeError(msg)

    response = stdout.decode("utf-8", errors="replace").strip()
    if not response:
        msg = "Claude CLI から空の応答が返されました"
        logger.warning(msg)
        raise RuntimeError(msg)

    logger.info("call_claude complete: response_len=%d", len(response))
    return response
