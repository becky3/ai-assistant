"""スケジューラ・配信フォーマットのテスト (Issue #8)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.db.models import Article, Feed
from src.scheduler.jobs import format_daily_digest, setup_scheduler


def _make_article(feed_id: int, title: str, url: str, summary: str) -> Article:
    a = Article(feed_id=feed_id, title=title, url=url, summary=summary)
    return a


def test_ac5_format_daily_digest_categorized() -> None:
    """AC5: 専用チャンネルにカテゴリ別フォーマットで記事要約を投稿する."""
    feeds = {
        1: Feed(id=1, url="https://a.com/rss", name="A", category="Python"),
        2: Feed(id=2, url="https://b.com/rss", name="B", category="機械学習"),
    }
    articles = [
        _make_article(1, "asyncioの新機能", "https://a.com/1", "asyncio要約"),
        _make_article(2, "transformer効率化", "https://b.com/1", "transformer要約"),
    ]

    result = format_daily_digest(articles, feeds)

    assert "今日の学習ニュース" in result
    assert "【Python】" in result
    assert "【機械学習】" in result
    assert "asyncioの新機能" in result
    assert "transformer効率化" in result
    assert ":bulb:" in result


def test_ac5_format_empty_articles() -> None:
    """AC5: 記事がない場合は空文字を返す."""
    assert format_daily_digest([], {}) == ""


def test_ac4_scheduler_registers_cron_job() -> None:
    """AC4: 毎朝指定時刻にスケジューラが収集・配信ジョブを実行する."""
    collector = MagicMock()
    session_factory = MagicMock()
    slack_client = MagicMock()

    scheduler = setup_scheduler(
        collector=collector,
        session_factory=session_factory,
        slack_client=slack_client,
        channel_id="C123",
        hour=7,
        minute=30,
        timezone="Asia/Tokyo",
    )

    jobs = scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "daily_feed_job"
    trigger = jobs[0].trigger
    # cron トリガーのフィールドを確認
    assert str(trigger.fields[5]) == "7"   # hour
    assert str(trigger.fields[6]) == "30"  # minute
