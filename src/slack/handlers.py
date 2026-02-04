"""Slack イベントハンドラ
仕様: docs/specs/f1-chat.md, docs/specs/f2-feed-collection.md, docs/specs/f3-user-profiling.md, docs/specs/f4-topic-recommend.md
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from slack_bolt.async_app import AsyncApp

from src.services.chat import ChatService
from src.services.topic_recommender import TopicRecommender
from src.services.user_profiler import UserProfiler

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.services.feed_collector import FeedCollector

logger = logging.getLogger(__name__)

_PROFILE_KEYWORDS = ("プロファイル", "プロフィール", "profile")
_TOPIC_KEYWORDS = ("おすすめ", "トピック", "何を学ぶ", "何学ぶ", "学習提案", "recommend")
_DELIVER_KEYWORDS = ("deliver",)
_FEED_KEYWORDS = ("feed",)


def strip_mention(text: str) -> str:
    """メンション部分 (<@U...>) を除去する."""
    return re.sub(r"<@[A-Za-z0-9]+>\s*", "", text).strip()


def _parse_feed_command(text: str) -> tuple[str, list[str], str]:
    """feedコマンドを解析する.

    Args:
        text: "feed add https://example.com/rss Python" のようなコマンド文字列

    Returns:
        (サブコマンド, URLリスト, カテゴリ名) のタプル
        カテゴリ名は add の場合のみ使用されるが、全コマンドで解析される。カテゴリトークンが無い場合は「一般」となる。
    """
    tokens = text.split()
    if len(tokens) < 2:
        return ("", [], "")

    subcommand = tokens[1].lower()
    urls: list[str] = []
    category_tokens: list[str] = []

    for token in tokens[2:]:
        # Slackは URL を <https://...|label> 形式に変換するため除去
        cleaned = token.strip("<>")
        if "|" in cleaned:
            cleaned = cleaned.split("|")[0]

        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed_url = urlparse(cleaned)
            if parsed_url.netloc:
                urls.append(cleaned)
            # ドメインなしの不正URLは無視（カテゴリにも追加しない）
        else:
            category_tokens.append(token)

    category = " ".join(category_tokens) if category_tokens else "一般"
    return (subcommand, urls, category)


async def _handle_feed_add(
    collector: FeedCollector, urls: list[str], category: str
) -> str:
    """フィード追加処理."""
    if not urls:
        return "エラー: URLを指定してください。\n例: `@bot feed add https://example.com/rss Python`"

    results: list[str] = []
    for url in urls:
        try:
            feed = await collector.add_feed(url, url, category)
            results.append(f"✅ {feed.url} を追加しました（カテゴリ: {feed.category}）")
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
        except Exception:
            logger.exception("Failed to add feed: %s", url)
            results.append(f"❌ {url}: 追加中にエラーが発生しました")

    return "\n".join(results)


async def _handle_feed_list(collector: FeedCollector) -> str:
    """フィード一覧表示処理."""
    enabled, disabled = await collector.list_feeds()

    if not enabled and not disabled:
        return "フィードが登録されていません"

    lines: list[str] = []
    if enabled:
        lines.append("*有効なフィード*")
        for feed in enabled:
            lines.append(f"• {feed.url} — {feed.category}")
    else:
        lines.append("有効なフィードはありません")

    if disabled:
        lines.append("\n*無効なフィード*")
        for feed in disabled:
            lines.append(f"• {feed.url} — {feed.category}")

    return "\n".join(lines)


async def _handle_feed_delete(collector: FeedCollector, urls: list[str]) -> str:
    """フィード削除処理."""
    if not urls:
        return "エラー: URLを指定してください。\n例: `@bot feed delete https://example.com/rss`"

    results: list[str] = []
    for url in urls:
        try:
            await collector.delete_feed(url)
            results.append(f"✅ {url} を削除しました")
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
        except Exception:
            logger.exception("Failed to delete feed: %s", url)
            results.append(f"❌ {url}: 削除中にエラーが発生しました")

    return "\n".join(results)


async def _handle_feed_enable(collector: FeedCollector, urls: list[str]) -> str:
    """フィード有効化処理."""
    if not urls:
        return "エラー: URLを指定してください。\n例: `@bot feed enable https://example.com/rss`"

    results: list[str] = []
    for url in urls:
        try:
            await collector.enable_feed(url)
            results.append(f"✅ {url} を有効化しました")
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
        except Exception:
            logger.exception("Failed to enable feed: %s", url)
            results.append(f"❌ {url}: 有効化中にエラーが発生しました")

    return "\n".join(results)


async def _handle_feed_disable(collector: FeedCollector, urls: list[str]) -> str:
    """フィード無効化処理."""
    if not urls:
        return "エラー: URLを指定してください。\n例: `@bot feed disable https://example.com/rss`"

    results: list[str] = []
    for url in urls:
        try:
            await collector.disable_feed(url)
            results.append(f"✅ {url} を無効化しました")
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
        except Exception:
            logger.exception("Failed to disable feed: %s", url)
            results.append(f"❌ {url}: 無効化中にエラーが発生しました")

    return "\n".join(results)


def register_handlers(
    app: AsyncApp,
    chat_service: ChatService,
    user_profiler: UserProfiler | None = None,
    topic_recommender: TopicRecommender | None = None,
    collector: FeedCollector | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    slack_client: object | None = None,
    channel_id: str | None = None,
    max_articles_per_category: int = 10,
) -> None:
    """app_mention ハンドラを登録する."""

    @app.event("app_mention")
    async def handle_mention(event: dict, say: object) -> None:  # type: ignore[type-arg]
        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        thread_ts: str = event.get("thread_ts") or event.get("ts", "")

        cleaned_text = strip_mention(text)
        if not cleaned_text:
            return

        # プロファイル確認キーワード (AC4)
        if user_profiler is not None and any(
            kw in cleaned_text.lower() for kw in _PROFILE_KEYWORDS
        ):
            profile_text = await user_profiler.get_profile(user_id)
            if profile_text:
                await say(text=profile_text, thread_ts=thread_ts)  # type: ignore[operator]
            else:
                await say(  # type: ignore[operator]
                    text="まだプロファイル情報がありません。会話を続けると自動的に記録されます！",
                    thread_ts=thread_ts,
                )
            return

        # feedコマンド (F2 - AC7)
        lower_text = cleaned_text.lower().lstrip()
        if collector is not None and any(
            re.match(rf"^{re.escape(kw)}\b", lower_text) for kw in _FEED_KEYWORDS
        ):
            subcommand, urls, category = _parse_feed_command(cleaned_text)

            if subcommand == "add":
                response_text = await _handle_feed_add(collector, urls, category)
            elif subcommand == "list":
                response_text = await _handle_feed_list(collector)
            elif subcommand == "delete":
                response_text = await _handle_feed_delete(collector, urls)
            elif subcommand == "enable":
                response_text = await _handle_feed_enable(collector, urls)
            elif subcommand == "disable":
                response_text = await _handle_feed_disable(collector, urls)
            else:
                response_text = (
                    "使用方法:\n"
                    "• `@bot feed add <URL> [カテゴリ]` — フィード追加\n"
                    "• `@bot feed list` — フィード一覧\n"
                    "• `@bot feed delete <URL>` — フィード削除\n"
                    "• `@bot feed enable <URL>` — フィード有効化\n"
                    "• `@bot feed disable <URL>` — フィード無効化\n"
                    "※ URL・カテゴリは複数指定可能（スペース区切り）"
                )

            await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
            return

        # 配信テストキーワード (F2)
        if (
            collector is not None
            and session_factory is not None
            and slack_client is not None
            and channel_id is not None
            and any(kw in cleaned_text.lower() for kw in _DELIVER_KEYWORDS)
        ):
            from src.scheduler.jobs import daily_collect_and_deliver

            try:
                await say(text="配信を開始します...", thread_ts=thread_ts)  # type: ignore[operator]
                await daily_collect_and_deliver(
                    collector, session_factory, slack_client, channel_id,
                    max_articles_per_category=max_articles_per_category,
                )
                await say(text="配信が完了しました", thread_ts=thread_ts)  # type: ignore[operator]
            except Exception:
                logger.exception("Failed to run manual delivery")
                await say(  # type: ignore[operator]
                    text="配信中にエラーが発生しました。",
                    thread_ts=thread_ts,
                )
            return

        # トピック提案キーワード (F4)
        if topic_recommender is not None and any(
            kw in cleaned_text.lower() for kw in _TOPIC_KEYWORDS
        ):
            try:
                recommendation = await topic_recommender.recommend(user_id)
                await say(text=recommendation, thread_ts=thread_ts)  # type: ignore[operator]
            except Exception:
                logger.exception("Failed to generate topic recommendation")
                await say(  # type: ignore[operator]
                    text="申し訳ありません、トピック提案の生成中にエラーが発生しました。",
                    thread_ts=thread_ts,
                )
            return

        try:
            response = await chat_service.respond(
                user_id=user_id,
                text=cleaned_text,
                thread_ts=thread_ts,
            )
            await say(text=response, thread_ts=thread_ts)  # type: ignore[operator]

            # ユーザー情報抽出を非同期で実行 (AC3)
            if user_profiler is not None:
                asyncio.create_task(
                    _safe_extract_profile(user_profiler, user_id, cleaned_text)
                )
        except Exception:
            logger.exception("Failed to generate response")
            await say(  # type: ignore[operator]
                text="申し訳ありません、応答の生成中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                thread_ts=thread_ts,
            )


async def _safe_extract_profile(
    profiler: UserProfiler, user_id: str, message: str
) -> None:
    """プロファイル抽出を安全に実行する（例外をログに記録）."""
    try:
        await profiler.extract_profile(user_id, message)
    except Exception:
        logger.exception("Failed to extract user profile for %s", user_id)
