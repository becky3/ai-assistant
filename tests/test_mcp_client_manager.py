"""MCPクライアントマネージャーのテスト.

仕様: docs/specs/infrastructure/mcp-integration.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.base import ToolDefinition
from src.mcp_bridge.client_manager import (
    MCPClientManager,
    MCPServerConfig,
    MCPToolNotFoundError,
)


def _make_mock_tool(name: str = "sample_tool", description: str = "サンプルツール") -> MagicMock:
    """モックツールオブジェクトを作成する."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"],
    }
    return tool


def _make_mock_session(tools: list[MagicMock] | None = None) -> AsyncMock:
    """モックClientSessionを作成する."""
    session = AsyncMock()
    session.initialize = AsyncMock()

    list_tools_response = MagicMock()
    list_tools_response.tools = tools or [_make_mock_tool()]
    session.list_tools = AsyncMock(return_value=list_tools_response)

    call_result = MagicMock()
    text_content = MagicMock()
    text_content.text = "Sample result"
    call_result.content = [text_content]
    session.call_tool = AsyncMock(return_value=call_result)

    return session


@pytest.mark.asyncio
async def test_client_manager_connects_and_lists_tools() -> None:
    """MCPClientManager がMCPサーバーに接続し、ToolDefinition リストとしてツール一覧を取得できること."""
    manager = MCPClientManager()

    mock_session = _make_mock_session()

    with (
        patch("src.mcp_bridge.client_manager.stdio_client") as mock_stdio,
        patch("src.mcp_bridge.client_manager.ClientSession", return_value=mock_session),
    ):
        # stdio_client をコンテキストマネージャーとしてモック
        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_transport.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_transport

        # ClientSession もコンテキストマネージャーとしてモック
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        config = MCPServerConfig(
            name="test_server",
            transport="stdio",
            command="python",
            args=["dummy_server.py"],
        )
        await manager.initialize([config])

    tools = await manager.get_available_tools()
    assert len(tools) == 1
    assert isinstance(tools[0], ToolDefinition)
    assert tools[0].name == "sample_tool"
    assert tools[0].description == "サンプルツール"

    await manager.cleanup()


@pytest.mark.asyncio
async def test_client_manager_calls_tool() -> None:
    """MCPClientManager.call_tool() でツールを実行し、結果を取得できること."""
    manager = MCPClientManager()

    mock_session = _make_mock_session()

    with (
        patch("src.mcp_bridge.client_manager.stdio_client") as mock_stdio,
        patch("src.mcp_bridge.client_manager.ClientSession", return_value=mock_session),
    ):
        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_transport.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_transport

        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        config = MCPServerConfig(
            name="test_server",
            transport="stdio",
            command="python",
            args=["dummy_server.py"],
        )
        await manager.initialize([config])

    result = await manager.call_tool("sample_tool", {"query": "test"})
    assert "Sample" in result

    mock_session.call_tool.assert_called_once_with("sample_tool", {"query": "test"})

    await manager.cleanup()


@pytest.mark.asyncio
async def test_call_tool_not_found() -> None:
    """存在しないツールを呼び出すと MCPToolNotFoundError が発生すること."""
    manager = MCPClientManager()

    with pytest.raises(MCPToolNotFoundError, match="not_exist"):
        await manager.call_tool("not_exist", {})


@pytest.mark.asyncio
async def test_client_manager_handles_multiple_servers() -> None:
    """複数のMCPサーバーを同時に管理できること."""
    manager = MCPClientManager()

    # 2つの異なるサーバーのモックセッション
    tool_a = _make_mock_tool("sample_tool", "サンプルツール")
    calc_tool = _make_mock_tool("calculate", "計算する")

    mock_session_1 = _make_mock_session([tool_a])
    mock_session_2 = _make_mock_session([calc_tool])

    sessions = [mock_session_1, mock_session_2]
    session_idx = 0

    def session_factory(*args: object, **kwargs: object) -> AsyncMock:
        nonlocal session_idx
        s = sessions[session_idx]
        session_idx += 1
        return s

    with (
        patch("src.mcp_bridge.client_manager.stdio_client") as mock_stdio,
        patch("src.mcp_bridge.client_manager.ClientSession", side_effect=session_factory),
    ):
        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(return_value=(AsyncMock(), AsyncMock()))
        mock_transport.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_transport

        for s in sessions:
            s.__aenter__ = AsyncMock(return_value=s)
            s.__aexit__ = AsyncMock(return_value=False)

        configs = [
            MCPServerConfig(name="server_a", command="python", args=["server_a.py"]),
            MCPServerConfig(name="calc", command="python", args=["calc.py"]),
        ]
        await manager.initialize(configs)

    tools = await manager.get_available_tools()
    tool_names = [t.name for t in tools]
    assert "sample_tool" in tool_names
    assert "calculate" in tool_names
    assert len(tools) == 2

    await manager.cleanup()


@pytest.mark.asyncio
async def test_graceful_degradation_on_connection_failure() -> None:
    """サーバー接続失敗時にエラーログを出力し、ツールなしで続行すること."""
    manager = MCPClientManager()

    with (
        patch("src.mcp_bridge.client_manager.stdio_client") as mock_stdio,
        patch("src.mcp_bridge.client_manager.logger") as mock_logger,
    ):
        # 接続失敗をシミュレート
        mock_stdio.side_effect = ConnectionError("Server not found")

        config = MCPServerConfig(
            name="broken_server",
            transport="stdio",
            command="python",
            args=["nonexistent.py"],
        )
        # 例外が発生しないこと（グレースフルデグラデーション）
        await manager.initialize([config])

    # エラーログが出力されること
    mock_logger.exception.assert_called_once()
    assert "broken_server" in str(mock_logger.exception.call_args)

    # ツールは空のまま
    tools = await manager.get_available_tools()
    assert tools == []

    await manager.cleanup()


@pytest.mark.asyncio
async def test_http_transport_connects_and_lists_tools() -> None:
    """HTTP トランスポートでMCPサーバーに接続し、ツール一覧を取得できること."""
    manager = MCPClientManager()

    mock_session = _make_mock_session()

    with (
        patch("src.mcp_bridge.client_manager.streamable_http_client") as mock_http,
        patch("src.mcp_bridge.client_manager.ClientSession", return_value=mock_session),
    ):
        # streamable_http_client は (read, write, get_session_id) の3タプルを返す
        mock_transport = AsyncMock()
        mock_transport.__aenter__ = AsyncMock(
            return_value=(AsyncMock(), AsyncMock(), AsyncMock())
        )
        mock_transport.__aexit__ = AsyncMock(return_value=False)
        mock_http.return_value = mock_transport

        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        config = MCPServerConfig(
            name="test_http_server",
            transport="http",
            url="http://127.0.0.1:8081/mcp",
        )
        await manager.initialize([config])

    tools = await manager.get_available_tools()
    assert len(tools) == 1
    assert tools[0].name == "sample_tool"
    assert manager._tool_to_server["sample_tool"] == "test_http_server"

    mock_http.assert_called_once_with("http://127.0.0.1:8081/mcp")

    await manager.cleanup()


@pytest.mark.asyncio
async def test_http_transport_missing_url_logs_error() -> None:
    """HTTP トランスポートで url 未設定の場合、エラーログを出してスキップすること."""
    manager = MCPClientManager()

    with patch("src.mcp_bridge.client_manager.logger") as mock_logger:
        config = MCPServerConfig(
            name="no_url_server",
            transport="http",
        )
        await manager.initialize([config])

    mock_logger.exception.assert_called_once()
    assert "no_url_server" in str(mock_logger.exception.call_args)

    tools = await manager.get_available_tools()
    assert tools == []

    await manager.cleanup()


@pytest.mark.asyncio
async def test_unsupported_transport_skipped() -> None:
    """未対応トランスポートが指定された場合、warningログを出してスキップすること."""
    manager = MCPClientManager()

    with patch("src.mcp_bridge.client_manager.logger") as mock_logger:
        config = MCPServerConfig(
            name="remote_server",
            transport="grpc",
            url="grpc://localhost:50051",
        )
        await manager.initialize([config])

    mock_logger.warning.assert_called_once()
    assert "grpc" in str(mock_logger.warning.call_args)

    tools = await manager.get_available_tools()
    assert tools == []

    await manager.cleanup()
