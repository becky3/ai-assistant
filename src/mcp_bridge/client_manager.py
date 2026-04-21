"""MCPクライアント管理
仕様: docs/specs/infrastructure/mcp-integration.md

複数のMCPサーバーを管理し、ツール一覧を統合するクライアントマネージャー。
"""

from __future__ import annotations

import contextlib
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

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
    system_instruction: str = ""  # ツール利用を促すためシステムプロンプトに常時追加する指示
    response_instruction: str = ""  # ツール結果を使った応答時にLLMへ追加する指示
    auto_context_tool: str = ""  # ユーザークエリで自動呼び出しし結果をコンテキスト注入するツール名


def build_mcp_server_configs(
    settings: Any,
    assistant_config: dict[str, Any],
) -> list[MCPServerConfig]:
    """settings と assistant.yaml から MCPServerConfig を構築する."""
    if not settings.mcp_rag_url:
        logger.warning("MCP_RAG_URL が未設定です。RAG MCP サーバーをスキップします。")
        return []

    return [MCPServerConfig(
        name="rag",
        transport=settings.mcp_rag_transport,
        url=settings.mcp_rag_url,
        system_instruction=str(assistant_config.get("mcp_system_instruction", "")),
        response_instruction=str(assistant_config.get("mcp_response_instruction", "")),
    )]


class MCPClientManager:
    """MCPサーバーへの接続を管理し、ツール一覧を統合する.

    仕様: docs/specs/infrastructure/mcp-integration.md
    """

    def __init__(self) -> None:
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tool_to_server: dict[str, str] = {}
        self._tools: list[ToolDefinition] = []
        self._system_instructions: list[str] = []  # ツール利用を促す常設指示
        self._server_instructions: dict[str, str] = {}  # server_name → response_instruction
        self._auto_context_tools: list[str] = []  # 自動コンテキスト注入ツール名

    async def initialize(self, server_configs: list[MCPServerConfig]) -> None:
        """設定されたMCPサーバーに接続し、利用可能ツールを取得する.

        各サーバーへの接続を試み、失敗したサーバーはスキップしてログ出力する。
        """
        _supported_transports = ("stdio", "http")
        for config in server_configs:
            if config.transport not in _supported_transports:
                logger.warning(
                    "MCPサーバー '%s': transport '%s' は未対応です（%s をサポート）。スキップします。",
                    config.name,
                    config.transport,
                    ", ".join(_supported_transports),
                )
                continue

            try:
                if config.transport == "http":
                    await self._connect_http_server(config)
                else:
                    await self._connect_stdio_server(config)
                if config.system_instruction:
                    self._system_instructions.append(config.system_instruction)
                if config.response_instruction:
                    self._server_instructions[config.name] = config.response_instruction
                if config.auto_context_tool:
                    self._auto_context_tools.append(config.auto_context_tool)
                logger.info("MCPサーバー '%s' に接続しました。", config.name)
            except BaseException as exc:
                # KeyboardInterrupt / SystemExit は再送出（シャットダウン用）
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                # CancelledError / ExceptionGroup 等を含む接続エラーをキャッチし、
                # MCP 機能を無効化して起動を継続する
                logger.warning(
                    "MCPサーバー '%s' への接続に失敗しました。スキップします: %s",
                    config.name,
                    exc,
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
        await self._initialize_session(config, session)

    async def _connect_http_server(self, config: MCPServerConfig) -> None:
        """HTTP（streamable-http）トランスポートでMCPサーバーに接続する.

        接続試行中の anyio cancel scope がイベントループに残ることを防ぐため、
        一時的な AsyncExitStack で隔離し、成功時のみメインの exit stack に移管する。
        """
        if not config.url:
            raise ValueError(
                f"MCPサーバー '{config.name}': HTTP トランスポートには url の設定が必要です。"
            )

        temp_stack = AsyncExitStack()
        try:
            http_transport = await temp_stack.enter_async_context(
                streamable_http_client(config.url)
            )
            read_stream, write_stream, _ = http_transport
            session = await temp_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._initialize_session(config, session)
        except BaseException:
            # 接続失敗 — 一時スタックをクリーンアップして cancel scope の漏洩を防ぐ
            with contextlib.suppress(BaseException):  # noqa: SIM117
                await temp_stack.aclose()
            raise

        # 接続成功 — メインの exit stack に移管
        self._exit_stack.push_async_callback(temp_stack.aclose)

    async def _initialize_session(
        self, config: MCPServerConfig, session: ClientSession
    ) -> None:
        """セッションを初期化し、ツール一覧を登録する."""
        await session.initialize()

        self._sessions[config.name] = session

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

    def get_system_instructions(self) -> list[str]:
        """全サーバーのシステム指示を返す."""
        return list(self._system_instructions)

    def get_auto_context_tools(self) -> list[str]:
        """自動コンテキスト注入するツール名のリストを返す."""
        return list(self._auto_context_tools)

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
        logger.info("call_tool: %s", tool_name)
        logger.debug("call_tool args: %s", arguments)
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
        result_text = "\n".join(text_parts)
        logger.info("call_tool completed: %s, result_length=%d", tool_name, len(result_text))
        return result_text

    async def cleanup(self) -> None:
        """全接続をクリーンアップする."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tool_to_server.clear()
        self._tools.clear()
        self._system_instructions.clear()
        self._server_instructions.clear()
        self._auto_context_tools.clear()
