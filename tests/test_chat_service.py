"""チャットサービスのテスト (Issue #6)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Base, Conversation
from src.llm.base import LLMResponse, Message
from src.services.chat import ChatService


@pytest.fixture
async def db_session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_ac2_conversation_history_maintained(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC2: 同一スレッド内の会話履歴を保持し文脈を踏まえた応答ができる."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="回答1")

    service = ChatService(llm=llm, session_factory=db_session_factory, system_prompt="テスト")

    await service.respond(user_id="U1", text="質問1", thread_ts="t1")

    llm.complete.return_value = LLMResponse(content="回答2")
    await service.respond(user_id="U1", text="質問2", thread_ts="t1")

    # 2回目の呼び出しで履歴が含まれているか確認
    call_args = llm.complete.call_args[0][0]
    roles = [m.role for m in call_args]
    # system + history(user, assistant) + new user
    assert roles == ["system", "user", "assistant", "user"]
    assert call_args[-1].content == "質問2"


async def test_ac3_system_prompt_reflected(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC3: assistant.yamlの性格設定がシステムプロンプトに反映される."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="応答")

    service = ChatService(llm=llm, session_factory=db_session_factory, system_prompt="優しい口調で")

    await service.respond(user_id="U1", text="hi", thread_ts="t1")

    messages = llm.complete.call_args[0][0]
    assert messages[0].role == "system"
    assert messages[0].content == "優しい口調で"


async def test_ac5_uses_online_llm(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC5: オンラインLLMで応答を生成する."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="LLM応答")

    service = ChatService(llm=llm, session_factory=db_session_factory)
    result = await service.respond(user_id="U1", text="test", thread_ts="t1")

    assert result == "LLM応答"
    llm.complete.assert_called_once()


async def test_ac6_conversation_saved_to_db(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC6: 会話履歴をDBに保存する."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="保存テスト")

    service = ChatService(llm=llm, session_factory=db_session_factory)
    await service.respond(user_id="U1", text="入力", thread_ts="t1")

    async with db_session_factory() as session:
        result = await session.execute(
            select(Conversation).order_by(Conversation.created_at)
        )
        rows = result.scalars().all()
        assert len(rows) == 2
        assert rows[0].role == "user"
        assert rows[0].content == "入力"
        assert rows[1].role == "assistant"
        assert rows[1].content == "保存テスト"
