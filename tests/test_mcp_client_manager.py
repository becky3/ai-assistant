"""MCPクライアントマネージャーのテスト (Issue #83, AC4-AC7).

仕様: docs/specs/f5-mcp-integration.md
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


def _make_mock_tool(name: str = "get_weather", description: str = "天気予報を取得する") -> MagicMock:
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
    text_content.text = "晴れ 15°C"
    call_result.content = [text_content]
    session.call_tool = AsyncMock(return_value=call_result)

    return session


@pytest.mark.asyncio
async def test_ac4_client_manager_connects_and_lists_tools() -> None:
    """AC4: MCPClientManager がMCPサーバーに接続し、ToolDefinition リストとしてツール一覧を取得できること."""
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
            name="weather",
            transport="stdio",
            command="python",
            args=["mcp-servers/weather/server.py"],
        )
        await manager.initialize([config])

    tools = await manager.get_available_tools()
    assert len(tools) == 1
    assert isinstance(tools[0], ToolDefinition)
    assert tools[0].name == "get_weather"
    assert tools[0].description == "天気予報を取得する"

    await manager.cleanup()


@pytest.mark.asyncio
async def test_ac5_client_manager_calls_tool() -> None:
    """AC5: MCPClientManager.call_tool() でツールを実行し、結果を取得できること."""
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
            name="weather",
            transport="stdio",
            command="python",
            args=["mcp-servers/weather/server.py"],
        )
        await manager.initialize([config])

    result = await manager.call_tool("get_weather", {"location": "東京"})
    assert "晴れ" in result
    assert "15°C" in result

    mock_session.call_tool.assert_called_once_with("get_weather", {"location": "東京"})

    await manager.cleanup()


@pytest.mark.asyncio
async def test_ac5_call_tool_not_found() -> None:
    """AC5: 存在しないツールを呼び出すと MCPToolNotFoundError が発生すること."""
    manager = MCPClientManager()

    with pytest.raises(MCPToolNotFoundError, match="not_exist"):
        await manager.call_tool("not_exist", {})


@pytest.mark.asyncio
async def test_ac6_client_manager_handles_multiple_servers() -> None:
    """AC6: 複数のMCPサーバーを同時に管理できること."""
    manager = MCPClientManager()

    # 2つの異なるサーバーのモックセッション
    weather_tool = _make_mock_tool("get_weather", "天気予報")
    calc_tool = _make_mock_tool("calculate", "計算する")

    mock_session_1 = _make_mock_session([weather_tool])
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
            MCPServerConfig(name="weather", command="python", args=["weather.py"]),
            MCPServerConfig(name="calc", command="python", args=["calc.py"]),
        ]
        await manager.initialize(configs)

    tools = await manager.get_available_tools()
    tool_names = [t.name for t in tools]
    assert "get_weather" in tool_names
    assert "calculate" in tool_names
    assert len(tools) == 2

    await manager.cleanup()


@pytest.mark.asyncio
async def test_ac7_graceful_degradation_on_connection_failure() -> None:
    """AC7: サーバー接続失敗時にエラーログを出力し、ツールなしで続行すること."""
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
async def test_ac7_http_transport_skipped() -> None:
    """AC7: HTTP トランスポートが指定された場合、warningログを出してスキップすること."""
    manager = MCPClientManager()

    with patch("src.mcp_bridge.client_manager.logger") as mock_logger:
        config = MCPServerConfig(
            name="remote_server",
            transport="http",
            url="http://localhost:8001/mcp",
        )
        await manager.initialize([config])

    mock_logger.warning.assert_called_once()
    assert "http" in str(mock_logger.warning.call_args)

    tools = await manager.get_available_tools()
    assert tools == []
