"""チャットオーケストレーション・会話履歴管理
仕様: docs/specs/features/chat-response.md, docs/specs/infrastructure/mcp-integration.md, docs/specs/features/thread-support.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config.settings import get_settings
from src.db.models import Conversation
from src.llm.base import LLMProvider, LLMResponse, Message, ToolDefinition, ToolResult

if TYPE_CHECKING:
    from src.mcp_bridge.client_manager import MCPClientManager

logger = logging.getLogger(__name__)

# ツール呼び出しループの安全弁
# 10回: 通常のマルチステップ推論で十分な回数。無限ループ防止の上限。
TOOL_LOOP_MAX_ITERATIONS = 10
# 30秒: 外部API呼び出し（MCP ツール等）の遅延を許容しつつ、応答全体をブロックしない値。
TOOL_CALL_TIMEOUT_SEC = 30

# rag_search ツール結果からスコア情報を抽出するパターン
# "### Result N [distance=X.XXX]" or "### Result N [score=X.XXX]"
_VECTOR_HEADER_RE = re.compile(r"###\s+Result\s+\d+\s+\[distance=(\d+(?:\.\d+)?)\]")
_BM25_HEADER_RE = re.compile(r"###\s+Result\s+\d+\s+\[score=(\d+(?:\.\d+)?)\]")

RagEngineType = Literal["vector", "bm25", "unknown"]


@dataclass(frozen=True)
class RagSource:
    """RAG検索のソース情報（参照元表示用）."""

    url: str
    engine: RagEngineType
    score: float  # distance (vector) or score (bm25)


def _parse_rag_sources_from_text(
    text: str,
    seen: set[tuple[str, str]],
) -> list[RagSource]:
    """テキストからRAGソース情報を抽出する.

    ヘッダ行（Result [distance=...] / [score=...]）で検索エンジン種別・スコアを取得し、
    Source: 行からURLを抽出する。seen セットで (engine, url) の重複を排除する。

    Args:
        text: パース対象のテキスト
        seen: 重複排除用のセット（呼び出し元と共有、破壊的に更新される）

    Returns:
        抽出された RagSource のリスト
    """
    sources: list[RagSource] = []
    current_engine: RagEngineType | None = None
    current_score: float | None = None
    for line in text.splitlines():
        m_vec = _VECTOR_HEADER_RE.match(line)
        if m_vec:
            current_engine = "vector"
            current_score = float(m_vec.group(1))
            continue
        m_bm25 = _BM25_HEADER_RE.match(line)
        if m_bm25:
            current_engine = "bm25"
            current_score = float(m_bm25.group(1))
            continue
        # "## Source: " と "Source: " の両方に対応
        url: str | None = None
        if line.startswith("## Source: "):
            url = line[len("## Source: "):].strip()
        elif line.startswith("Source: "):
            url = line[len("Source: "):].strip()
        if url is not None:
            if url:
                engine: RagEngineType = current_engine or "unknown"
                score = current_score if current_score is not None else 0.0
                key = (engine, url)
                if key not in seen:
                    seen.add(key)
                    sources.append(RagSource(url=url, engine=engine, score=score))
            # URL の有無に関わらず、Source 行を見たらヘッダ情報をリセット
            current_engine = None
            current_score = None
    return sources


class ChatService:
    """チャット応答サービス.

    仕様: docs/specs/features/chat-response.md, docs/specs/infrastructure/mcp-integration.md, docs/specs/features/thread-support.md
    """

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        system_prompt: str = "",
        mcp_manager: MCPClientManager | None = None,
        thread_history_fetcher: Callable[[str, str, str], Awaitable[list[Message] | None]] | None = None,
        format_instruction: str = "",
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory
        self._system_prompt = system_prompt
        self._mcp_manager = mcp_manager
        self._thread_history_fetcher = thread_history_fetcher
        self._format_instruction = format_instruction

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
            # スレッド内かつ thread_history_fetcher が利用可能な場合は外部から取得
            history: list[Message] | None = None
            if is_in_thread and self._thread_history_fetcher and channel:
                history = await self._thread_history_fetcher(
                    channel, thread_ts, current_ts,
                )

            # Slack API から取得できなかった場合は DB フォールバック
            if history is None:
                history = await self._load_history(session, thread_ts)

            # メッセージリストを構築
            # 構成順: format_instruction → personality
            # MCP system_instructions は後段で先頭に挿入される
            messages: list[Message] = []
            parts: list[str] = []
            if self._format_instruction:
                parts.append(self._format_instruction)
            if self._system_prompt:
                parts.append(self._system_prompt)
            system_content = "\n\n".join(parts)
            if system_content:
                messages.append(Message(role="system", content=system_content))
            messages.extend(history)
            messages.append(Message(role="user", content=text))

            # MCP無効 or MCPClientManager未注入 → 従来通り
            if not self._mcp_manager:
                response = await self._llm.complete(messages)
                return await self._save_and_return(
                    session, user_id, thread_ts, text, response.content,
                )

            # ツール呼び出しループ
            tools = await self._mcp_manager.get_available_tools()
            if not tools:
                # ツールがない場合は従来通り
                response = await self._llm.complete(messages)
                return await self._save_and_return(
                    session, user_id, thread_ts, text, response.content,
                )

            # MCPサーバーのシステム指示をシステムプロンプトの先頭に追加
            # ツール動作の指示はキャラクター設定より優先度が高いため先頭に配置
            system_instructions = self._mcp_manager.get_system_instructions()
            if system_instructions:
                extra = "\n\n".join(system_instructions)
                if messages and messages[0].role == "system":
                    messages[0] = Message(
                        role="system",
                        content=extra + "\n\n" + messages[0].content,
                    )
                else:
                    messages.insert(0, Message(role="system", content=extra))

            # 自動コンテキスト注入（RAG等）
            rag_sources, auto_applied = await self._inject_auto_context(messages, text)

            final_response = await self._run_tool_loop(
                messages, tools, applied_instructions=auto_applied,
            )

            # ツールループで rag_search が呼ばれた場合のソースURL抽出
            if not rag_sources:
                rag_sources = self._extract_rag_sources_from_messages(messages)

            return await self._save_and_return(
                session, user_id, thread_ts, text, final_response.content,
                rag_sources=rag_sources,
            )

    async def _run_tool_loop(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
        *,
        applied_instructions: set[str] | None = None,
    ) -> LLMResponse:
        """ツール呼び出しループを実行する."""
        applied_instructions = applied_instructions if applied_instructions is not None else set()
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

    async def _inject_auto_context(
        self, messages: list[Message], user_text: str
    ) -> tuple[list[RagSource], set[str]]:
        """auto_context_tool で設定されたツールを自動呼び出しし、結果をシステムプロンプトに注入する.

        Returns:
            (検索結果のRagSourceリスト, 適用済みresponse_instructionのセット)
        """
        sources: list[RagSource] = []
        seen: set[tuple[str, str]] = set()
        applied: set[str] = set()
        if not self._mcp_manager:
            return sources, applied
        auto_tools = self._mcp_manager.get_auto_context_tools()
        if not auto_tools:
            return sources, applied

        for tool_name in auto_tools:
            try:
                result = await asyncio.wait_for(
                    self._mcp_manager.call_tool(tool_name, {"query": user_text}),
                    timeout=TOOL_CALL_TIMEOUT_SEC,
                )
            except Exception:
                logger.debug("Auto-context tool '%s' failed", tool_name, exc_info=True)
                continue

            if not result or "該当する情報が見つかりませんでした" in result:
                continue

            # ソース情報を抽出（エンジン種別・スコア付き）
            sources.extend(_parse_rag_sources_from_text(result, seen))

            # 検索結果をシステムプロンプトに注入
            context_block = (
                "以下は質問に関連する参考情報です。"
                "回答に役立つ場合は活用してください:\n" + result
            )
            if messages and messages[0].role == "system":
                messages[0] = Message(
                    role="system",
                    content=messages[0].content + "\n\n" + context_block,
                )
            else:
                messages.insert(0, Message(role="system", content=context_block))

            # 対応する response_instruction も適用（重複防止）
            instruction = self._mcp_manager.get_response_instruction(tool_name)
            if instruction and instruction not in applied:
                applied.add(instruction)
                if messages and messages[0].role == "system":
                    messages[0] = Message(
                        role="system",
                        content=messages[0].content + "\n\n" + instruction,
                    )

        return sources, applied

    @staticmethod
    def _extract_rag_sources_from_messages(messages: list[Message]) -> list[RagSource]:
        """ツールループ内の rag_search 結果からソース情報を抽出する.

        messages 内の role="tool" メッセージから検索エンジン種別・スコア・URLを
        検出し、ユニークなソース情報リストを返す。

        Returns:
            RagSourceのリスト（(engine, url) の重複なし、出現順）
        """
        sources: list[RagSource] = []
        seen: set[tuple[str, str]] = set()
        for msg in messages:
            if msg.role != "tool":
                continue
            sources.extend(_parse_rag_sources_from_text(msg.content, seen))
        return sources

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
        *,
        rag_sources: list[RagSource] | None = None,
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

        # ソース情報を追記（設定有効時のみ）
        if rag_sources and get_settings().rag_show_sources:
            sources_text = "\n---\n参照元:\n" + "\n".join(
                self._format_rag_source(src) for src in rag_sources
            )
            return assistant_text + sources_text

        return assistant_text

    @staticmethod
    def _format_rag_source(src: RagSource) -> str:
        """RagSource を参照元表示用の文字列にフォーマットする."""
        if src.engine == "vector":
            return f"• [vector: distance={src.score:.3f}] {src.url}"
        if src.engine == "bm25":
            return f"• [bm25: score={src.score:.3f}] {src.url}"
        return f"• {src.url}"

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
