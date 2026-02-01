"""学習トピック提案のテスト (Issue #10)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db.models import Article, Base, Feed, UserProfile
from src.llm.base import LLMResponse
from src.services.topic_recommender import TopicRecommender


@pytest.fixture
async def db_session_factory():  # type: ignore[no-untyped-def]
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def _seed_profile(
    factory: async_sessionmaker,  # type: ignore[type-arg]
    user_id: str = "U123",
    interests: list[str] | None = None,
    skills: list[dict[str, str]] | None = None,
    goals: list[str] | None = None,
) -> None:
    async with factory() as session:
        session.add(UserProfile(
            slack_user_id=user_id,
            interests=json.dumps(interests or [], ensure_ascii=False),
            skills=json.dumps(skills or [], ensure_ascii=False),
            goals=json.dumps(goals or [], ensure_ascii=False),
        ))
        await session.commit()


async def _seed_articles(
    factory: async_sessionmaker,  # type: ignore[type-arg]
    articles: list[dict[str, str]],
) -> None:
    async with factory() as session:
        feed = Feed(url="https://example.com/feed", name="Test Feed")
        session.add(feed)
        await session.flush()
        for art in articles:
            session.add(Article(
                feed_id=feed.id,
                title=art["title"],
                url=art.get("url", "https://example.com"),
                summary=art.get("summary", ""),
                collected_at=datetime.now(timezone.utc),
            ))
        await session.commit()


async def test_ac1_profile_reflected_in_recommendation(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC1: ユーザープロファイルをDBから取得して提案に反映できる."""
    await _seed_profile(
        db_session_factory,
        interests=["Python", "機械学習"],
        skills=[{"name": "Python", "level": "中級"}],
        goals=["MLエンジニアになりたい"],
    )

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        content="1. *scikit-learn入門*\n   Pythonスキルを活かせます。"
    )

    recommender = TopicRecommender(llm=llm, session_factory=db_session_factory)
    result = await recommender.recommend("U123")

    # LLMに渡されたプロンプトにプロファイル情報が含まれている
    call_args = llm.complete.call_args[0][0]
    user_msg = call_args[1].content
    assert "Python" in user_msg
    assert "機械学習" in user_msg
    assert "MLエンジニア" in user_msg
    assert "おすすめ学習トピック" in result


async def test_ac2_recent_articles_used_as_context(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC2: 最近の収集記事の情報を提案のコンテキストとして使用できる."""
    await _seed_profile(
        db_session_factory,
        interests=["Python"],
        skills=[{"name": "Python", "level": "初心者"}],
        goals=["エンジニアになりたい"],
    )
    await _seed_articles(db_session_factory, [
        {"title": "FastAPI最新機能", "summary": "FastAPI 0.100のリリース"},
        {"title": "React 19の新機能", "summary": "Server Componentsの改善"},
    ])

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(content="1. *FastAPI入門*\n   最近話題です。")

    recommender = TopicRecommender(llm=llm, session_factory=db_session_factory)
    await recommender.recommend("U123")

    call_args = llm.complete.call_args[0][0]
    user_msg = call_args[1].content
    assert "FastAPI最新機能" in user_msg
    assert "React 19" in user_msg


async def test_ac3_generates_3_to_5_topics(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC3: 3〜5個のトピック提案を生成できる（システムプロンプトで指示）."""
    await _seed_profile(
        db_session_factory,
        interests=["Python"],
        skills=[],
        goals=["学習したい"],
    )

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        content="1. *トピックA*\n   説明A\n\n2. *トピックB*\n   説明B\n\n3. *トピックC*\n   説明C"
    )

    recommender = TopicRecommender(llm=llm, session_factory=db_session_factory)
    result = await recommender.recommend("U123")

    # システムプロンプトに3〜5個の指示が含まれている
    call_args = llm.complete.call_args[0][0]
    system_msg = call_args[0].content
    assert "3" in system_msg
    assert "5" in system_msg
    assert "トピックA" in result


async def test_ac4_includes_relevance_explanation(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC4: 各提案にユーザーのスキル・目標との関連性の説明が含まれる（プロンプトで指示）."""
    await _seed_profile(
        db_session_factory,
        interests=["データ分析"],
        skills=[{"name": "SQL", "level": "中級"}],
        goals=["データサイエンティスト"],
    )

    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        content="1. *pandas入門*\n   SQL経験を活かしてデータ操作を学べます。"
    )

    recommender = TopicRecommender(llm=llm, session_factory=db_session_factory)
    await recommender.recommend("U123")

    # システムプロンプトに関連性説明の指示がある
    call_args = llm.complete.call_args[0][0]
    system_msg = call_args[0].content
    assert "関連性" in system_msg


async def test_ac5_empty_profile_returns_general_recommendation(db_session_factory) -> None:  # type: ignore[no-untyped-def]
    """AC5: プロファイルが空の場合、一般的なおすすめを返しつつプロファイル充実を促す."""
    llm = AsyncMock()

    recommender = TopicRecommender(llm=llm, session_factory=db_session_factory)
    result = await recommender.recommend("UNOTFOUND")

    # LLMは呼ばれない
    llm.complete.assert_not_called()
    # 一般的なおすすめが返る
    assert "おすすめ学習トピック" in result
    assert "プロファイル" in result
    # プロファイル充実を促すメッセージ
    assert "パーソナライズ" in result
