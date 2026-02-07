"""チャットオーケストレーション・会話履歴管理
仕様: docs/specs/f1-chat.md, docs/specs/f5-mcp-integration.md, docs/specs/f8-thread-support.md
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Conversation
from src.llm.base import LLMProvider, LLMResponse, Message, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from src.mcp_bridge.client_manager import MCPClientManager
    from src.services.thread_history import ThreadHistoryService

logger = logging.getLogger(__name__)

# ツール呼び出しループの安全弁
# 10回: 通常のマルチステップ推論で十分な回数。無限ループ防止の上限。
TOOL_LOOP_MAX_ITERATIONS = 10
# 30秒: 外部API呼び出し（天気予報等）の遅延を許容しつつ、応答全体をブロックしない値。
TOOL_CALL_TIMEOUT_SEC = 30


class ChatService:
    """チャット応答サービス.

    仕様: docs/specs/f1-chat.md, docs/specs/f5-mcp-integration.md, docs/specs/f8-thread-support.md
    """

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        system_prompt: str = "",
        mcp_manager: MCPClientManager | None = None,
        thread_history_service: ThreadHistoryService | None = None,
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory
        self._system_prompt = system_prompt
        self._mcp_manager = mcp_manager
        self._thread_history = thread_history_service

    async def respond(
        self,
        user_id: str,
        text: str,
        thread_ts: str,
        channel: str = "",
        is_in_thread: bool = False,
        current_ts: str = "",
    ) -> str:
        """ユーザーメッセージに対する応答を生成し、履歴を保存する."""
        async with self._session_factory() as session:
            # スレッド内かつ ThreadHistoryService が利用可能な場合は Slack API から取得
            history: list[Message] | None = None
            if is_in_thread and self._thread_history and channel:
                history = await self._thread_history.fetch_thread_messages(
                    channel=channel,
                    thread_ts=thread_ts,
                    current_ts=current_ts,
                )

            # Slack API から取得できなかった場合は DB フォールバック
            if history is None:
                history = await self._load_history(session, thread_ts)

            # メッセージリストを構築
            messages: list[Message] = []
            if self._system_prompt:
                messages.append(Message(role="system", content=self._system_prompt))
            messages.extend(history)
            messages.append(Message(role="user", content=text))

            # MCP無効 or MCPClientManager未注入 → 従来通り
            if not self._mcp_manager:
                response = await self._llm.complete(messages)
                return await self._save_and_return(
                    session, user_id, thread_ts, text, response.content
                )

            # ツール呼び出しループ
            tools = await self._mcp_manager.get_available_tools()
            if not tools:
                # ツールがない場合は従来通り
                response = await self._llm.complete(messages)
                return await self._save_and_return(
                    session, user_id, thread_ts, text, response.content
                )

            final_response = await self._run_tool_loop(messages, tools)
            return await self._save_and_return(
                session, user_id, thread_ts, text, final_response.content
            )

    async def _run_tool_loop(
        self, messages: list[Message], tools: list[ToolDefinition]
    ) -> LLMResponse:
        """ツール呼び出しループを実行する."""
        applied_instructions: set[str] = set()
        for _ in range(TOOL_LOOP_MAX_ITERATIONS):
            response = await self._llm.complete_with_tools(messages, tools)

            if not response.tool_calls:
                return response

            # ツール実行 & 結果をメッセージに追加
            messages.append(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))
            for tc in response.tool_calls:
                result = await self._execute_tool_with_timeout(tc.name, tc.arguments)
                messages.append(Message(
                    role="tool",
                    content=result.content,
                    tool_call_id=tc.id,
                ))
                # ツール固有の応答指示をシステムプロンプトに追加（重複防止）
                self._apply_response_instruction(
                    messages, tc.name, applied_instructions
                )

        # 最大反復到達 → 強制的にテキスト応答を要求
        messages.append(Message(
            role="user",
            content="ツール呼び出しの上限に達しました。現在の情報で回答してください。",
        ))
        return await self._llm.complete(messages)

    def _apply_response_instruction(
        self,
        messages: list[Message],
        tool_name: str,
        applied: set[str],
    ) -> None:
        """ツール固有の応答指示をシステムプロンプトに追加する."""
        if not self._mcp_manager:
            return
        instruction = self._mcp_manager.get_response_instruction(tool_name)
        if not instruction or instruction in applied:
            return
        applied.add(instruction)
        if messages and messages[0].role == "system":
            messages[0] = Message(
                role="system",
                content=messages[0].content + "\n\n" + instruction,
            )

    async def _execute_tool_with_timeout(
        self, tool_name: str, arguments: dict[str, object]
    ) -> ToolResult:
        """タイムアウト付きでツールを実行する."""
        if self._mcp_manager is None:
            raise RuntimeError("MCPClientManagerが未設定のため、ツール実行できません")
        try:
            result_text = await asyncio.wait_for(
                self._mcp_manager.call_tool(tool_name, arguments),
                timeout=TOOL_CALL_TIMEOUT_SEC,
            )
            return ToolResult(tool_call_id="", content=result_text)
        except asyncio.TimeoutError:
            logger.warning("ツール '%s' の実行がタイムアウトしました（%d秒）", tool_name, TOOL_CALL_TIMEOUT_SEC)
            return ToolResult(
                tool_call_id="",
                content=f"ツール '{tool_name}' の実行がタイムアウトしました。",
                is_error=True,
            )
        except Exception as e:
            logger.exception("ツール '%s' の実行中にエラーが発生しました", tool_name)
            return ToolResult(
                tool_call_id="",
                content=f"ツール '{tool_name}' の実行中にエラーが発生しました: {e}",
                is_error=True,
            )

    async def _save_and_return(
        self,
        session: AsyncSession,
        user_id: str,
        thread_ts: str,
        user_text: str,
        assistant_text: str,
    ) -> str:
        """ユーザーメッセージとアシスタント応答をDBに保存し、応答テキストを返す."""
        session.add(Conversation(
            slack_user_id=user_id,
            thread_ts=thread_ts,
            role="user",
            content=user_text,
        ))
        session.add(Conversation(
            slack_user_id=user_id,
            thread_ts=thread_ts,
            role="assistant",
            content=assistant_text,
        ))
        await session.commit()
        return assistant_text

    async def _load_history(
        self, session: AsyncSession, thread_ts: str
    ) -> list[Message]:
        """スレッドの会話履歴を取得する."""
        result = await session.execute(
            select(Conversation)
            .where(Conversation.thread_ts == thread_ts)
            .order_by(Conversation.created_at)
        )
        rows = result.scalars().all()
        return [
            Message(role=r.role, content=r.content)  # type: ignore[arg-type]
            for r in rows
        ]
