"""チャットオーケストレーション・会話履歴管理
仕様: docs/specs/f1-chat.md
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Conversation
from src.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)


class ChatService:
    """チャット応答サービス.

    仕様: docs/specs/f1-chat.md
    """

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
        system_prompt: str = "",
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory
        self._system_prompt = system_prompt

    async def respond(self, user_id: str, text: str, thread_ts: str) -> str:
        """ユーザーメッセージに対する応答を生成し、履歴を保存する."""
        async with self._session_factory() as session:
            # 会話履歴を取得
            history = await self._load_history(session, thread_ts)

            # メッセージリストを構築
            messages: list[Message] = []
            if self._system_prompt:
                messages.append(Message(role="system", content=self._system_prompt))
            messages.extend(history)
            messages.append(Message(role="user", content=text))

            # LLM 応答生成
            response = await self._llm.complete(messages)

            # 履歴を保存
            session.add(Conversation(
                slack_user_id=user_id,
                thread_ts=thread_ts,
                role="user",
                content=text,
            ))
            session.add(Conversation(
                slack_user_id=user_id,
                thread_ts=thread_ts,
                role="assistant",
                content=response.content,
            ))
            await session.commit()

            return response.content

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
