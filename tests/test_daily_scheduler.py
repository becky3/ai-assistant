"""定時実行スケジューラのテスト (Issue #850)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from src.messaging.port import ThreadRef
from src.scheduler.daily_scheduler import DailyScheduler, seconds_until_next
from src.scheduler.schedule_config import ScheduledJob, load_schedule

TZ = ZoneInfo("Asia/Tokyo")


def _make_messaging(thread: ThreadRef | None = None) -> AsyncMock:
    """open_thread が ThreadRef を返す messaging mock."""
    messaging = AsyncMock()
    messaging.open_thread = AsyncMock(
        return_value=thread or ThreadRef(channel="T", thread_key="T")
    )
    return messaging


# --- schedule_config ---

def test_load_schedule_missing_returns_empty(tmp_path: Path) -> None:
    assert load_schedule(tmp_path / "nonexistent.toml") == []


def test_load_schedule_parses_jobs(tmp_path: Path) -> None:
    p = tmp_path / "schedule.toml"
    p.write_text(
        '[[jobs]]\ntime = "03:00"\ncommand = "deliver"\n\n'
        '[[jobs]]\ntime = "04:30"\ncommand = "article write-hatena"\n'
        'user_id = "U1"\nchannel = "C9"\n',
        encoding="utf-8",
    )
    jobs = load_schedule(p)
    assert len(jobs) == 2
    assert jobs[0] == ScheduledJob(hour=3, minute=0, command="deliver")
    assert jobs[1] == ScheduledJob(
        hour=4, minute=30, command="article write-hatena", channel="C9", user_id="U1"
    )


def test_load_schedule_skips_invalid(tmp_path: Path) -> None:
    p = tmp_path / "schedule.toml"
    p.write_text(
        '[[jobs]]\ntime = "25:00"\ncommand = "bad-hour"\n\n'      # 範囲外
        '[[jobs]]\ntime = "9am"\ncommand = "bad-format"\n\n'     # 形式不正
        '[[jobs]]\ntime = "03:00"\ncommand = ""\n\n'            # command 空
        '[[jobs]]\ntime = "05:00"\ncommand = "ok"\n',           # 有効
        encoding="utf-8",
    )
    jobs = load_schedule(p)
    assert len(jobs) == 1
    assert jobs[0].command == "ok"


# --- seconds_until_next ---

def test_seconds_until_next_later_today() -> None:
    now = datetime(2026, 6, 17, 2, 0, 0, tzinfo=TZ)
    assert seconds_until_next(now, 3, 0) == 3600.0


def test_seconds_until_next_already_passed_rolls_to_next_day() -> None:
    now = datetime(2026, 6, 17, 5, 0, 0, tzinfo=TZ)
    # 翌日 03:00 まで = 22 時間
    assert seconds_until_next(now, 3, 0) == 22 * 3600.0


# --- DailyScheduler._fire ---

async def test_fire_announces_and_routes_into_thread() -> None:
    router = AsyncMock()
    messaging = _make_messaging(ThreadRef(channel="TH", thread_key="TH"))
    scheduler = DailyScheduler(
        [], router, messaging, default_channel="C_NEWS", timezone="Asia/Tokyo"
    )
    job = ScheduledJob(hour=3, minute=0, command="deliver")

    await scheduler._fire(job)

    # 告知スレッドを C_NEWS に開く
    messaging.open_thread.assert_awaited_once_with("C_NEWS", "🕒 定時実行: deliver")
    router.process_message.assert_awaited_once()
    msg = router.process_message.await_args.args[0]
    assert msg.text == "deliver"
    assert msg.channel == "TH"      # 応答はスレッドへ
    assert msg.thread_id == "TH"
    assert msg.is_in_thread is False
    assert msg.user_id == ""


async def test_fire_uses_job_channel_and_user() -> None:
    router = AsyncMock()
    messaging = _make_messaging()
    scheduler = DailyScheduler(
        [], router, messaging, default_channel="C_NEWS", timezone="Asia/Tokyo"
    )
    job = ScheduledJob(
        hour=4, minute=30, command="article write-hatena", channel="C9", user_id="U1"
    )

    await scheduler._fire(job)

    messaging.open_thread.assert_awaited_once_with("C9", "🕒 定時実行: article write-hatena")
    msg = router.process_message.await_args.args[0]
    assert msg.user_id == "U1"


async def test_fire_skips_when_no_channel() -> None:
    router = AsyncMock()
    messaging = _make_messaging()
    scheduler = DailyScheduler(
        [], router, messaging, default_channel="", timezone="Asia/Tokyo"
    )
    job = ScheduledJob(hour=3, minute=0, command="deliver")

    await scheduler._fire(job)

    messaging.open_thread.assert_not_awaited()
    router.process_message.assert_not_awaited()


async def test_fire_falls_back_to_channel_when_open_thread_fails() -> None:
    router = AsyncMock()
    messaging = _make_messaging()
    messaging.open_thread.side_effect = RuntimeError("no thread perms")
    scheduler = DailyScheduler(
        [], router, messaging, default_channel="C_NEWS", timezone="Asia/Tokyo"
    )
    job = ScheduledJob(hour=3, minute=0, command="deliver")

    await scheduler._fire(job)

    # スレッド作成失敗 → チャンネル直下にフォールバック
    msg = router.process_message.await_args.args[0]
    assert msg.channel == "C_NEWS"
    assert msg.thread_id == "C_NEWS"


async def test_fire_swallows_router_exception() -> None:
    router = AsyncMock()
    router.process_message.side_effect = RuntimeError("boom")
    messaging = _make_messaging()
    scheduler = DailyScheduler(
        [], router, messaging, default_channel="C_NEWS", timezone="Asia/Tokyo"
    )
    job = ScheduledJob(hour=3, minute=0, command="deliver")

    # 例外を握り潰すこと（送出しない）
    await scheduler._fire(job)
    router.process_message.assert_awaited_once()
