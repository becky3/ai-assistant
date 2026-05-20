"""DBスキーマ・セッション管理のテスト (Issue #3)."""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config.settings import _EnvLoader
from src.db.models import Article, Base, Conversation, Feed
from src.db import session as session_mod


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def test_feed_crud(session: AsyncSession) -> None:
    """feeds テーブルの CRUD."""
    feed = Feed(url="https://example.com/rss", name="Example", category="tech")
    session.add(feed)
    await session.commit()

    result = await session.execute(select(Feed))
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].url == "https://example.com/rss"


async def test_article_belongs_to_feed(session: AsyncSession) -> None:
    """articles は feed_id で feeds に紐付く."""
    feed = Feed(url="https://example.com/rss", name="Example")
    session.add(feed)
    await session.flush()

    article = Article(feed_id=feed.id, title="Test Article", url="https://example.com/1")
    session.add(article)
    await session.commit()

    result = await session.execute(select(Article))
    a = result.scalar_one()
    assert a.feed_id == feed.id


async def test_conversation(session: AsyncSession) -> None:
    """conversations テーブル."""
    conv = Conversation(slack_user_id="U123", thread_ts="123.456", role="user", content="hello")
    session.add(conv)
    await session.commit()

    result = await session.execute(select(Conversation))
    c = result.scalar_one()
    assert c.role == "user"


async def test_init_db_and_get_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """init_db/get_session 経由でテーブル作成とセッション取得ができる."""
    # .env.example をベースに読み込み、DATABASE_URL のみテスト用にオーバーライド
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    # .env.example は主要動作環境 (Windows) 形式の絶対パス (C:/...) を持つ。
    # Linux/macOS では Path("C:/...").is_absolute() が False を返し
    # _validate_remote_control_repositories の絶対パス判定で弾かれるため、
    # POSIX 互換の絶対パスにオーバーライドする。
    if sys.platform != "win32":
        monkeypatch.setenv(
            "REMOTE_CONTROL_REPOSITORIES",
            "ai-assistant=/path/to/ai-assistant,agent-commons=/path/to/agent-commons",
        )
        monkeypatch.setenv(
            "ARTICLE_WRITER_REPO_PATH", "/path/to/article-writer",
        )
    monkeypatch.setattr(
        _EnvLoader, "model_config",
        {**_EnvLoader.model_config, "env_file": ".env.example"},
    )

    # グローバル状態をリセット
    session_mod._engine = None
    session_mod._session_factory = None
    from src.config.settings import get_settings
    get_settings.cache_clear()

    try:
        await session_mod.init_db()

        gen = session_mod.get_session()
        s = await gen.__anext__()
        try:
            s.add(Feed(url="https://test.com/rss", name="Test"))
            await s.commit()
            result = await s.execute(select(Feed))
            assert result.scalar_one().name == "Test"
        finally:
            await gen.aclose()
    finally:
        # クリーンアップ
        if session_mod._engine is not None:
            await session_mod._engine.dispose()
        session_mod._engine = None
        session_mod._session_factory = None
        get_settings.cache_clear()
