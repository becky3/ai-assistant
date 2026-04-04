"""Claude CLI ワンショット実行のテスト (#797).

テスト方針:
- call_claude のプロセス呼び出しを subprocess モックでテスト
- 正常系・エラー系・タイムアウトを検証
- ChatService の claude モード分岐をテスト
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Base
from src.llm.claude_cli import call_claude
from src.services.chat import ChatService


# --- call_claude 単体テスト ---


async def test_call_claude_returns_response() -> None:
    """正常系: Claude CLI が応答テキストを返す."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"Hello from Claude", b"")
    mock_proc.returncode = 0

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await call_claude(
            prompt="test prompt",
            system_prompt="test system",
            allowed_tools="mcp__test__*",
            timeout=30,
        )

    assert result == "Hello from Claude"


async def test_call_claude_passes_stdin() -> None:
    """プロンプトが stdin 経由で渡される."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"response", b"")
    mock_proc.returncode = 0

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc):
        await call_claude(
            prompt="my prompt",
            system_prompt="sys",
            allowed_tools="",
            timeout=30,
        )

    mock_proc.communicate.assert_called_once_with(input=b"my prompt")


async def test_call_claude_omits_allowed_tools_when_empty() -> None:
    """allowed_tools が空文字列の場合は --allowedTools フラグを省略する."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"response", b"")
    mock_proc.returncode = 0

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await call_claude(
            prompt="test",
            system_prompt="sys",
            allowed_tools="",
            timeout=30,
        )

    cmd_args = mock_exec.call_args[0]
    assert "--allowedTools" not in cmd_args


async def test_call_claude_includes_allowed_tools_when_set() -> None:
    """allowed_tools が設定されている場合は --allowedTools フラグを含める."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"response", b"")
    mock_proc.returncode = 0

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        await call_claude(
            prompt="test",
            system_prompt="sys",
            allowed_tools="mcp__rag__*",
            timeout=30,
        )

    cmd_args = mock_exec.call_args[0]
    assert "--allowedTools" in cmd_args
    tools_idx = cmd_args.index("--allowedTools")
    assert cmd_args[tools_idx + 1] == "mcp__rag__*"


async def test_call_claude_raises_on_nonzero_exit() -> None:
    """非0 exit code で RuntimeError を送出する."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"error message")
    mock_proc.returncode = 1

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="exit code 1"):
            await call_claude(
                prompt="test",
                system_prompt="",
                allowed_tools="",
                timeout=30,
            )


async def test_call_claude_raises_on_timeout() -> None:
    """タイムアウト時に TimeoutError を送出する."""
    mock_proc = AsyncMock()
    mock_proc.communicate.side_effect = asyncio.TimeoutError()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(TimeoutError, match="タイムアウト"):
            await call_claude(
                prompt="test",
                system_prompt="",
                allowed_tools="",
                timeout=5,
            )
    mock_proc.kill.assert_called_once()


async def test_call_claude_raises_on_empty_response() -> None:
    """空の応答で RuntimeError を送出する."""
    mock_proc = AsyncMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0

    with patch("src.llm.claude_cli.asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(RuntimeError, match="空の応答"):
            await call_claude(
                prompt="test",
                system_prompt="",
                allowed_tools="",
                timeout=30,
            )


# --- ChatService claude モード分岐テスト ---


@pytest.fixture
async def db_session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_chat_service_claude_mode_calls_cli(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """claude モード時は call_claude が呼ばれる."""
    service = ChatService(
        llm=None,
        session_factory=db_session_factory,
        system_prompt="テスト性格",
        claude_mode=True,
        claude_allowed_tools="mcp__test__*",
        claude_timeout=60,
    )

    with patch("src.llm.claude_cli.call_claude", new_callable=AsyncMock) as mock_cli:
        mock_cli.return_value = "CLI応答"
        result = await service.respond(user_id="U1", text="こんにちは", thread_ts="t1")

    assert result == "CLI応答"
    mock_cli.assert_called_once()
    call_kwargs = mock_cli.call_args[1]
    assert call_kwargs["allowed_tools"] == "mcp__test__*"
    assert call_kwargs["timeout"] == 60
    assert "テスト性格" in call_kwargs["system_prompt"]


async def test_chat_service_local_mode_calls_llm(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """local モード時は従来の LLM プロバイダーが呼ばれる."""
    from src.llm.base import LLMResponse

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="LLM応答")

    service = ChatService(
        llm=llm,
        session_factory=db_session_factory,
        system_prompt="テスト",
        claude_mode=False,
    )

    result = await service.respond(user_id="U1", text="hello", thread_ts="t1")

    assert result == "LLM応答"
    llm.complete.assert_called_once()
