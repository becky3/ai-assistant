"""ユーザー情報抽出のテスト (Issue #9)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Base, UserProfile
from src.llm.base import LLMResponse
from src.services.user_profiler import UserProfiler


@pytest.fixture
async def db_session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _make_llm_response(data: dict) -> LLMResponse:  # type: ignore[type-arg]
    return LLMResponse(content=json.dumps(data, ensure_ascii=False))


async def test_ac1_extract_interests_skills_goals(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC1: 会話メッセージからinterests/skills/goalsをLLMで抽出できる."""
    llm = AsyncMock()
    llm.complete.return_value = _make_llm_response({
        "interests": ["Python", "機械学習"],
        "skills": [{"name": "Python", "level": "中級"}],
        "goals": ["MLエンジニアになりたい"],
    })

    profiler = UserProfiler(llm=llm, session_factory=db_session_factory)
    await profiler.extract_profile("U123", "Pythonで機械学習を勉強中です")

    llm.complete.assert_called_once()

    async with db_session_factory() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.slack_user_id == "U123")
        )
        profile = result.scalar_one()
        assert json.loads(profile.interests) == ["Python", "機械学習"]
        assert json.loads(profile.skills) == [{"name": "Python", "level": "中級"}]
        assert json.loads(profile.goals) == ["MLエンジニアになりたい"]


async def test_ac2_merge_existing_profile(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC2: 抽出結果を既存プロファイルとマージできる."""
    llm = AsyncMock()

    # 1回目
    llm.complete.return_value = _make_llm_response({
        "interests": ["Python"],
        "skills": [{"name": "Python", "level": "初心者"}],
        "goals": ["転職したい"],
    })
    profiler = UserProfiler(llm=llm, session_factory=db_session_factory)
    await profiler.extract_profile("U123", "msg1")

    # 2回目（マージ）
    llm.complete.return_value = _make_llm_response({
        "interests": ["Python", "React"],
        "skills": [{"name": "Python", "level": "中級"}, {"name": "React", "level": "初心者"}],
        "goals": ["転職したい", "フロントエンドも学びたい"],
    })
    await profiler.extract_profile("U123", "msg2")

    async with db_session_factory() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.slack_user_id == "U123")
        )
        profile = result.scalar_one()
        interests = json.loads(profile.interests)
        skills = json.loads(profile.skills)
        goals = json.loads(profile.goals)

        # 重複除去されている
        assert interests == ["Python", "React"]
        # スキルレベルが更新されている
        assert {"name": "Python", "level": "中級"} in skills
        assert {"name": "React", "level": "初心者"} in skills
        assert goals == ["転職したい", "フロントエンドも学びたい"]


async def test_ac3_async_execution_via_create_task() -> None:
    """AC3: asyncio.create_taskによる非同期実行."""
    from src.slack.handlers import _safe_extract_profile

    profiler = AsyncMock()
    profiler.extract_profile = AsyncMock()

    task = asyncio.create_task(_safe_extract_profile(profiler, "U1", "hello"))
    await task

    profiler.extract_profile.assert_called_once_with("U1", "hello")


async def test_ac3_safe_extract_profile_logs_exception() -> None:
    """AC3: 非同期抽出でエラーが発生してもログに記録しクラッシュしない."""
    from src.slack.handlers import _safe_extract_profile

    profiler = AsyncMock()
    profiler.extract_profile.side_effect = RuntimeError("LLM error")

    with patch("src.slack.handlers.logger") as mock_logger:
        await _safe_extract_profile(profiler, "U1", "hello")
        mock_logger.exception.assert_called_once()


async def test_ac4_get_profile_formatted(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: ユーザーが自分のプロファイルを確認できる."""
    # DBにプロファイルを直接作成
    async with db_session_factory() as session:
        session.add(UserProfile(
            slack_user_id="U123",
            interests=json.dumps(["Python", "機械学習"]),
            skills=json.dumps([{"name": "Python", "level": "中級"}]),
            goals=json.dumps(["データサイエンティストになりたい"]),
        ))
        await session.commit()

    llm = AsyncMock()
    profiler = UserProfiler(llm=llm, session_factory=db_session_factory)
    result = await profiler.get_profile("U123")

    assert result is not None
    assert "あなたのプロファイル" in result
    assert "Python" in result
    assert "中級" in result
    assert "データサイエンティストになりたい" in result


async def test_ac4_get_profile_returns_none_when_empty(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: プロファイルが存在しない場合はNoneを返す."""
    llm = AsyncMock()
    profiler = UserProfiler(llm=llm, session_factory=db_session_factory)
    result = await profiler.get_profile("UNOTFOUND")
    assert result is None


async def test_ac5_json_parse_failure_skips(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC5: LLMの抽出結果がJSON形式でない場合、ログに記録し処理をスキップする."""
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="これはJSONではありません")

    profiler = UserProfiler(llm=llm, session_factory=db_session_factory)

    with patch("src.services.user_profiler.logger") as mock_logger:
        await profiler.extract_profile("U123", "test message")
        mock_logger.warning.assert_called_once()

    # DBにプロファイルが作成されていないことを確認
    async with db_session_factory() as session:
        result = await session.execute(
            select(UserProfile).where(UserProfile.slack_user_id == "U123")
        )
        assert result.scalar_one_or_none() is None


async def test_ac4_profile_keyword_handler() -> None:
    """AC4: プロファイル確認キーワードでget_profileが呼ばれる."""
    from src.slack.handlers import register_handlers

    chat_service = AsyncMock()
    user_profiler = AsyncMock()
    user_profiler.get_profile.return_value = ":bust_in_silhouette: あなたのプロファイル\n..."

    app = AsyncMock()
    handlers: dict = {}

    def capture_event(event_type: str):  # type: ignore[no-untyped-def]
        def decorator(func):  # type: ignore[no-untyped-def]
            handlers[event_type] = func
            return func
        return decorator

    app.event = capture_event
    register_handlers(app, chat_service, user_profiler=user_profiler)

    say = AsyncMock()
    event = {"user": "U123", "text": "<@UBOT> プロファイルを見せて", "ts": "123.456"}
    await handlers["app_mention"](event=event, say=say)

    user_profiler.get_profile.assert_called_once_with("U123")
    say.assert_called_once()
    assert "プロファイル" in say.call_args[1]["text"]
    # chat_service should NOT have been called
    chat_service.respond.assert_not_called()
