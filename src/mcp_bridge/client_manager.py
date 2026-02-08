"""MCPクライアント管理
仕様: docs/specs/f5-mcp-integration.md

複数のMCPサーバーを管理し、ツール一覧を統合するクライアントマネージャー。
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.llm.base import ToolDefinition

logger = logging.getLogger(__name__)


class MCPToolNotFoundError(Exception):
    """指定されたツールが見つからない場合の例外."""


class MCPToolExecutionError(Exception):
    """ツール実行中にエラーが発生した場合の例外."""


@dataclass
class MCPServerConfig:
    """MCPサーバーの接続設定."""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    response_instruction: str = ""  # ツール結果を使った応答時にLLMへ追加する指示


class MCPClientManager:
    """MCPサーバーへの接続を管理し、ツール一覧を統合する.

    仕様: docs/specs/f5-mcp-integration.md
    """

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tool_to_server: dict[str, str] = {}
        self._tools: list[ToolDefinition] = []
        self._server_instructions: dict[str, str] = {}  # server_name → response_instruction

    async def initialize(self, server_configs: list[MCPServerConfig]) -> None:
        """設定されたMCPサーバーに接続し、利用可能ツールを取得する.

        各サーバーへの接続を試み、失敗したサーバーはスキップしてログ出力する。
        """
        for config in server_configs:
            if config.transport != "stdio":
                logger.warning(
                    "MCPサーバー '%s': transport '%s' は未対応です（stdioのみサポート）。スキップします。",
                    config.name,
                    config.transport,
                )
                continue

            try:
                await self._connect_stdio_server(config)
                if config.response_instruction:
                    self._server_instructions[config.name] = config.response_instruction
                logger.info("MCPサーバー '%s' に接続しました。", config.name)
            except Exception:
                logger.exception(
                    "MCPサーバー '%s' への接続に失敗しました。スキップします。",
                    config.name,
                )

    async def _connect_stdio_server(self, config: MCPServerConfig) -> None:
        """stdioトランスポートでMCPサーバーに接続する."""
        server_params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env=config.env if config.env else None,
        )

        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read_stream, write_stream = stdio_transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        self._sessions[config.name] = session

        # ツール一覧を取得
        response = await session.list_tools()
        for tool in response.tools:
            td = ToolDefinition(
                name=tool.name,
                description=tool.description or "",
                input_schema=dict(tool.inputSchema) if tool.inputSchema else {},
            )
            self._tools.append(td)
            self._tool_to_server[tool.name] = config.name

    async def get_available_tools(self) -> list[ToolDefinition]:
        """全サーバーのツールをプロバイダー非依存形式で返す."""
        return list(self._tools)

    def get_response_instruction(self, tool_name: str) -> str:
        """ツール名に対応するサーバーの応答指示を返す."""
        server_name = self._tool_to_server.get(tool_name, "")
        return self._server_instructions.get(server_name, "")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """指定ツールを実行し、結果を返す.

        Raises:
            MCPToolNotFoundError: 指定ツールが見つからない場合
            MCPToolExecutionError: ツール実行失敗時
        """
        server_name = self._tool_to_server.get(tool_name)
        if server_name is None:
            raise MCPToolNotFoundError(f"ツール '{tool_name}' が見つかりません。")

        session = self._sessions.get(server_name)
        if session is None:
            raise MCPToolExecutionError(
                f"ツール '{tool_name}' のサーバー '{server_name}' に接続されていません。"
            )

        try:
            result = await session.call_tool(tool_name, arguments)
        except Exception as e:
            raise MCPToolExecutionError(
                f"ツール '{tool_name}' の実行中にエラーが発生しました: {e}"
            ) from e

        # MCP SDK の result.content は TextContent のリスト
        text_parts: list[str] = []
        for content_item in result.content:
            if hasattr(content_item, "text"):
                text_parts.append(content_item.text)
            else:
                text_parts.append(str(content_item))
        return "\n".join(text_parts)

    async def cleanup(self) -> None:
        """全接続をクリーンアップする."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tool_to_server.clear()
        self._tools.clear()
        self._server_instructions.clear()
