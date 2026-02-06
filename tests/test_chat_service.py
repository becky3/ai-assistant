"""チャットサービスのテスト (Issue #6, #97)."""

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


async def test_ac4_non_thread_uses_db_history(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """F8-AC4: スレッド外ではDB履歴を使用する."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="回答")

    thread_history = AsyncMock()

    service = ChatService(
        llm=llm,
        session_factory=db_session_factory,
        thread_history_service=thread_history,
    )

    # is_in_thread=False → DB フォールバック
    await service.respond(
        user_id="U1", text="hello", thread_ts="t1",
        is_in_thread=False, channel="C1", current_ts="1000.0",
    )

    # ThreadHistoryService は呼ばれない
    thread_history.fetch_thread_messages.assert_not_called()


async def test_ac5_fallback_to_db_on_api_failure(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """F8-AC5: Slack API 失敗時に DB フォールバック."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="fallback回答")

    thread_history = AsyncMock()
    thread_history.fetch_thread_messages.return_value = None  # API 失敗

    service = ChatService(
        llm=llm,
        session_factory=db_session_factory,
        thread_history_service=thread_history,
    )

    result = await service.respond(
        user_id="U1", text="hello", thread_ts="t1",
        is_in_thread=True, channel="C1", current_ts="1000.0",
    )

    assert result == "fallback回答"
    thread_history.fetch_thread_messages.assert_called_once()


async def test_ac6_auto_reply_channel_thread_uses_slack_api_history(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """F8-AC6: 自動返信チャンネルのスレッド内でもスレッド履歴が使用される."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="thread回答")

    thread_history = AsyncMock()
    thread_history.fetch_thread_messages.return_value = [
        Message(role="user", content="<@U1>: previous msg"),
    ]

    service = ChatService(
        llm=llm,
        session_factory=db_session_factory,
        thread_history_service=thread_history,
    )

    result = await service.respond(
        user_id="U1", text="new msg", thread_ts="parent_ts",
        is_in_thread=True, channel="C_AUTO", current_ts="1001.0",
    )

    assert result == "thread回答"
    thread_history.fetch_thread_messages.assert_called_once_with(
        channel="C_AUTO", thread_ts="parent_ts", current_ts="1001.0",
    )
    # LLM に渡されたメッセージにスレッド履歴が含まれる
    call_messages = llm.complete.call_args[0][0]
    assert any("previous msg" in m.content for m in call_messages)


async def test_thread_uses_slack_api_history(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """スレッド内で Slack API 履歴が使用される."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="応答")

    thread_history = AsyncMock()
    thread_history.fetch_thread_messages.return_value = [
        Message(role="user", content="<@U1>: msg1"),
        Message(role="assistant", content="bot reply"),
    ]

    service = ChatService(
        llm=llm,
        session_factory=db_session_factory,
        thread_history_service=thread_history,
    )

    await service.respond(
        user_id="U1", text="msg2", thread_ts="parent_ts",
        is_in_thread=True, channel="C1", current_ts="1002.0",
    )

    call_messages = llm.complete.call_args[0][0]
    roles = [m.role for m in call_messages]
    # history(user, assistant) + new user (system prompt なし)
    assert roles == ["user", "assistant", "user"]
    assert call_messages[-1].content == "msg2"
