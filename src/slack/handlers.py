"""Slack イベントハンドラ
仕様: docs/specs/f1-chat.md, docs/specs/f2-feed-collection.md, docs/specs/f3-user-profiling.md, docs/specs/f4-topic-recommend.md, docs/specs/f6-auto-reply.md, docs/specs/f7-bot-status.md, docs/specs/f8-thread-support.md
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import socket
from datetime import datetime
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
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
_STATUS_KEYWORDS = ("status", "info")

# 起動時刻（main.py から設定される）
BOT_START_TIME: datetime | None = None


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
        elif cleaned.startswith("--"):
            # フラグ引数（--skip-summary など）はカテゴリに含めない
            pass
        else:
            category_tokens.append(token)

    category = " ".join(category_tokens) if category_tokens else "一般"
    return (subcommand, urls, category)


def _format_uptime(seconds: float) -> str:
    """稼働時間を「N時間M分」形式にフォーマットする."""
    total_minutes = int(seconds) // 60
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}時間{minutes}分"
    return f"{minutes}分"


def _build_status_message(timezone: str, env_name: str) -> str:
    """ボットステータスメッセージを構築する (F7)."""
    hostname = socket.gethostname()
    now = datetime.now(tz=ZoneInfo(timezone))

    lines = ["\U0001f916 ボットステータス", f"ホスト: {hostname}"]

    if env_name:
        lines.append(f"環境: {env_name}")

    if BOT_START_TIME is not None:
        start_str = BOT_START_TIME.strftime("%Y-%m-%d %H:%M:%S %Z")
        uptime = now - BOT_START_TIME
        uptime_str = _format_uptime(uptime.total_seconds())
        lines.append(f"起動: {start_str}（稼働 {uptime_str}）")

    return "\n".join(lines)


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
            lines.append(f"• {feed.url} — {feed.name}")
    else:
        lines.append("有効なフィードはありません")

    if disabled:
        lines.append("\n*無効なフィード*")
        for feed in disabled:
            lines.append(f"• {feed.url} — {feed.name}")

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


async def _download_and_parse_csv(
    files: list[dict[str, object]] | None,
    bot_token: str,
) -> tuple[list[dict[str, str]], str | None]:
    """CSV添付ファイルを検証・ダウンロード・パースする.

    Returns:
        (行リスト, エラーメッセージ) のタプル。
        成功時はエラーメッセージがNone、失敗時は行リストが空。
    """
    if not files:
        return ([], (
            "エラー: CSVファイルを添付してください。\n"
            "使用方法: `@bot feed import` または `@bot feed replace` にCSVファイルを添付\n"
            "CSV形式: `url,name,category`"
        ))

    # CSVファイルを探す
    csv_file = None
    for f in files:
        mimetype = str(f.get("mimetype", ""))
        name = str(f.get("name", ""))
        if mimetype == "text/csv" or name.endswith(".csv"):
            csv_file = f
            break

    if not csv_file:
        return ([], (
            "エラー: CSVファイルが見つかりません。\n"
            "CSV形式のファイル（.csv）を添付してください。"
        ))

    # ファイルサイズ検証（最大1MB）
    max_file_size = 1 * 1024 * 1024  # 1MB
    file_size = csv_file.get("size", 0)
    if isinstance(file_size, int) and file_size > max_file_size:
        return ([], f"エラー: ファイルサイズが大きすぎます（最大1MB、実際: {file_size // 1024}KB）")

    # ファイルをダウンロード
    url_private = csv_file.get("url_private")
    if not url_private or not isinstance(url_private, str):
        return ([], "エラー: ファイルのダウンロードURLが取得できませんでした。")

    # url_private_download を優先的に使用（より確実）
    download_url = csv_file.get("url_private_download") or url_private
    if not isinstance(download_url, str):
        download_url = url_private

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                download_url,
                headers={"Authorization": f"Bearer {bot_token}"},
                follow_redirects=False,
            )
            # 302リダイレクトの場合は認証エラー
            if response.status_code == 302:
                logger.error("File download redirected - auth may have failed")
                return ([], "エラー: ファイルのダウンロードに失敗しました（認証エラー）。Bot権限を確認してください。")
            response.raise_for_status()
            content = response.text
    except httpx.HTTPError as e:
        logger.exception("Failed to download CSV file")
        return ([], f"エラー: ファイルのダウンロードに失敗しました: {e}")

    # CSVをパース
    try:
        reader = csv.DictReader(io.StringIO(content))
        # ヘッダー検証
        fieldnames = reader.fieldnames or []
        if "url" not in fieldnames or "name" not in fieldnames:
            return ([], (
                "エラー: CSVヘッダーが不正です。\n"
                "`url,name,category` の形式で記述してください。\n"
                f"検出されたヘッダー: {', '.join(fieldnames)}"
            ))

        rows = list(reader)
    except csv.Error as e:
        return ([], f"エラー: CSVのパースに失敗しました: {e}")

    if not rows:
        return ([], "エラー: CSVにデータがありません。")

    return (rows, None)


async def _import_feeds_from_rows(
    collector: FeedCollector,
    rows: list[dict[str, str]],
) -> tuple[int, list[str]]:
    """CSVの行リストからフィードを登録する.

    Returns:
        (成功件数, エラーリスト) のタプル
    """
    success_count = 0
    errors: list[str] = []

    for line_number, row in enumerate(rows, start=2):  # ヘッダー行が1行目なので2から開始
        url = (row.get("url") or "").strip()
        name = (row.get("name") or "").strip()
        category = (row.get("category") or "").strip() or "一般"

        if not url or not name:
            errors.append(f"行{line_number}: url または name が空です")
            continue

        # URLの形式を検証
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append(f"行{line_number}: 無効なURL形式です（{url}）")
            continue

        try:
            await collector.add_feed(url, name, category)
            success_count += 1
        except ValueError as e:
            errors.append(f"行{line_number}: {e}")
        except Exception:
            logger.exception("Failed to add feed: %s", url)
            errors.append(f"行{line_number}: 追加中にエラーが発生しました")

    return (success_count, errors)


def _format_error_details(errors: list[str]) -> list[str]:
    """エラー詳細をフォーマットする."""
    lines: list[str] = []
    if errors:
        lines.append("\n*エラー詳細:*")
        for error in errors[:10]:
            lines.append(f"  • {error}")
        if len(errors) > 10:
            lines.append(f"  ...他 {len(errors) - 10}件")
    return lines


async def _handle_feed_import(
    collector: FeedCollector,
    files: list[dict[str, object]] | None,
    bot_token: str,
) -> str:
    """CSVファイルからフィードを一括インポートする."""
    rows, error = await _download_and_parse_csv(files, bot_token)
    if error is not None:
        return error

    success_count, errors = await _import_feeds_from_rows(collector, rows)

    # 結果サマリーを作成
    result_lines = [
        "*フィードインポート完了*",
        f"✅ 成功: {success_count}件",
        f"❌ 失敗: {len(errors)}件",
    ]
    result_lines.extend(_format_error_details(errors))

    return "\n".join(result_lines)


async def _handle_feed_replace(
    collector: FeedCollector,
    files: list[dict[str, object]] | None,
    bot_token: str,
) -> str:
    """CSVファイルで全フィードを置換する（全削除→再登録）."""
    rows, error = await _download_and_parse_csv(files, bot_token)
    if error is not None:
        return error

    # 全フィード削除
    try:
        deleted_count = await collector.delete_all_feeds()
    except Exception:
        logger.exception("Failed to delete all feeds in replace")
        return (
            "*フィード置換エラー*\n"
            "🗑️ 既存フィードの削除中に予期せぬエラーが発生しました。\n"
            "❌ フィードの置換を完了できませんでした。"
        )

    # CSVからフィードを登録
    try:
        success_count, errors = await _import_feeds_from_rows(collector, rows)
    except Exception:
        logger.exception("Failed to import feeds after delete_all in replace")
        return (
            "*フィード置換エラー*\n"
            f"🗑️ 削除: {deleted_count}件（既存フィード）\n"
            "❌ インポート中に予期せぬエラーが発生しました。"
        )

    # 結果サマリーを作成
    result_lines = [
        "*フィード置換完了*",
        f"🗑️ 削除: {deleted_count}件（既存フィード）",
        f"✅ 登録成功: {success_count}件",
        f"❌ 登録失敗: {len(errors)}件",
    ]
    result_lines.extend(_format_error_details(errors))

    return "\n".join(result_lines)


async def _handle_feed_collect_skip_summary(
    collector: FeedCollector,
) -> str:
    """要約をスキップして全フィードから記事を一括収集する（初回インポート用）."""
    try:
        articles = await collector.collect_all(skip_summary=True)
    except Exception:
        logger.exception("Failed to collect feeds with skip-summary")
        return "要約スキップ収集中にエラーが発生しました。"

    feed_count = len({a.feed_id for a in articles})
    article_count = len(articles)

    return (
        "*要約スキップ収集完了*\n"
        f"📰 収集フィード数: {feed_count}\n"
        f"📝 収集記事数: {article_count}"
    )


async def _handle_feed_export(
    collector: FeedCollector,
    slack_client: object,
    channel: str,
    thread_ts: str,
) -> str:
    """全フィードをCSV形式でエクスポートする."""
    feeds = await collector.get_all_feeds()

    if not feeds:
        return "エクスポートするフィードがありません。"

    # CSV文字列を生成
    def _sanitize_csv_field(value: str) -> str:
        """CSVインジェクション対策: 先頭が危険な文字の場合にシングルクォートを付与."""
        if value and value[0] in ("=", "+", "-", "@"):
            return f"'{value}"
        return value

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["url", "name", "category"])
    for feed in feeds:
        writer.writerow([
            feed.url,
            _sanitize_csv_field(feed.name),
            _sanitize_csv_field(feed.category),
        ])
    csv_content = output.getvalue()

    # Slackにファイルをアップロード
    try:
        await slack_client.files_upload_v2(  # type: ignore[attr-defined]
            channel=channel,
            thread_ts=thread_ts,
            content=csv_content,
            filename="feeds.csv",
            initial_comment=f"フィード一覧をエクスポートしました（{len(feeds)}件）",
        )
    except Exception as e:
        error_msg = str(e)
        if "missing_scope" in error_msg or "not_allowed_token_type" in error_msg:
            logger.error("File upload failed due to missing scope: %s", e)
            return (
                "エラー: ファイルのアップロードに失敗しました。\n"
                "Slack Appに `files:write` スコープの追加が必要です。"
            )
        logger.exception("Failed to upload CSV file")
        return f"エラー: ファイルのアップロードに失敗しました: {e}"

    return ""


def register_handlers(
    app: AsyncApp,
    chat_service: ChatService,
    user_profiler: UserProfiler | None = None,
    topic_recommender: TopicRecommender | None = None,
    collector: FeedCollector | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    slack_client: object | None = None,
    channel_id: str | None = None,
    max_articles_per_feed: int = 10,
    feed_card_layout: Literal["vertical", "horizontal"] = "horizontal",
    auto_reply_channels: list[str] | None = None,
    bot_token: str | None = None,
    timezone: str = "Asia/Tokyo",
    env_name: str = "",
) -> None:
    """app_mention および message ハンドラを登録する."""

    async def _process_message(
        user_id: str,
        cleaned_text: str,
        thread_ts: str,
        say: object,
        files: list[dict[str, object]] | None = None,
        channel: str = "",
        is_in_thread: bool = False,
        current_ts: str = "",
    ) -> None:
        """共通メッセージ処理ロジック（app_mention / message 共用）."""
        # ステータスコマンド (F7)
        if cleaned_text.lower().strip() in _STATUS_KEYWORDS:
            response_text = _build_status_message(timezone, env_name)
            await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
            return

        # プロファイル確認キーワード (F3-AC4, F6-AC4)
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

        # feedコマンド (F2-AC7, F6-AC4)
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
            elif subcommand == "import":
                if not bot_token:
                    response_text = "エラー: Bot Tokenが設定されていません。"
                else:
                    response_text = await _handle_feed_import(
                        collector, files, bot_token
                    )
            elif subcommand == "replace":
                if not bot_token:
                    response_text = "エラー: Bot Tokenが設定されていません。"
                else:
                    response_text = await _handle_feed_replace(
                        collector, files, bot_token
                    )
            elif subcommand == "export":
                if slack_client is not None and channel:
                    response_text = await _handle_feed_export(
                        collector, slack_client, channel, thread_ts
                    )
                    if response_text:
                        await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
                else:
                    await say(  # type: ignore[operator]
                        text="エラー: Slack連携の設定が不足しています。",
                        thread_ts=thread_ts,
                    )
                return
            elif subcommand == "collect":
                # feed collect --skip-summary
                if "--skip-summary" in cleaned_text.lower():
                    await say(text="要約スキップ収集を開始します...", thread_ts=thread_ts)  # type: ignore[operator]
                    response_text = await _handle_feed_collect_skip_summary(collector)
                    await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
                else:
                    response_text = (
                        "使用方法:\n"
                        "• `@bot feed collect --skip-summary` — 要約なし一括収集"
                    )
                    await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
                return
            elif subcommand == "test":
                if (
                    session_factory is not None
                    and slack_client is not None
                    and channel_id is not None
                ):
                    from src.scheduler.jobs import feed_test_deliver

                    try:
                        await say(text="テスト配信を開始します...", thread_ts=thread_ts)  # type: ignore[operator]
                        await feed_test_deliver(
                            session_factory=session_factory,
                            slack_client=slack_client,
                            channel_id=channel_id,
                            layout=feed_card_layout,
                        )
                        await say(text="テスト配信が完了しました", thread_ts=thread_ts)  # type: ignore[operator]
                    except Exception:
                        logger.exception("Failed to run feed test delivery")
                        await say(  # type: ignore[operator]
                            text="テスト配信中にエラーが発生しました。",
                            thread_ts=thread_ts,
                        )
                else:
                    response_text = "エラー: 配信設定が不足しています。"
                    await say(text=response_text, thread_ts=thread_ts)  # type: ignore[operator]
                return
            else:
                response_text = (
                    "使用方法:\n"
                    "• `@bot feed add <URL> [カテゴリ]` — フィード追加\n"
                    "• `@bot feed list` — フィード一覧\n"
                    "• `@bot feed delete <URL>` — フィード削除\n"
                    "• `@bot feed enable <URL>` — フィード有効化\n"
                    "• `@bot feed disable <URL>` — フィード無効化\n"
                    "• `@bot feed import` + CSV添付 — フィード一括インポート\n"
                    "• `@bot feed replace` + CSV添付 — フィード一括置換\n"
                    "• `@bot feed export` — フィード一覧をCSVエクスポート\n"
                    "• `@bot feed collect --skip-summary` — 要約なし一括収集\n"
                    "• `@bot feed test` — テスト配信（上位3フィード・各5件）\n"
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
                    max_articles_per_feed=max_articles_per_feed,
                    layout=feed_card_layout,
                )
                await say(text="配信が完了しました", thread_ts=thread_ts)  # type: ignore[operator]
            except Exception:
                logger.exception("Failed to run manual delivery")
                await say(  # type: ignore[operator]
                    text="配信中にエラーが発生しました。",
                    thread_ts=thread_ts,
                )
            return

        # トピック提案キーワード (F4, F6-AC4)
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

        # デフォルト: ChatService で応答
        try:
            response = await chat_service.respond(
                user_id=user_id,
                text=cleaned_text,
                thread_ts=thread_ts,
                channel=channel,
                is_in_thread=is_in_thread,
                current_ts=current_ts,
            )
            await say(text=response, thread_ts=thread_ts)  # type: ignore[operator]

            # ユーザー情報抽出を非同期で実行 (F3-AC3)
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

    @app.event("app_mention")
    async def handle_mention(event: dict, say: object) -> None:  # type: ignore[type-arg]
        user_id: str = event.get("user", "")
        text: str = event.get("text", "")
        raw_thread_ts: str | None = event.get("thread_ts")
        event_ts: str = event.get("ts", "")
        thread_ts: str = raw_thread_ts or event_ts
        files: list[dict[str, object]] | None = event.get("files")
        channel: str = event.get("channel", "")

        cleaned_text = strip_mention(text)
        if not cleaned_text:
            return

        await _process_message(
            user_id, cleaned_text, thread_ts, say, files,
            channel=channel,
            is_in_thread=raw_thread_ts is not None,
            current_ts=event_ts,
        )

    @app.event("message")
    async def handle_message(event: dict, say: object) -> None:  # type: ignore[type-arg]
        """自動返信チャンネルでのメッセージ処理 (F6).

        フィルタリング (F6-AC2, AC3, AC6, AC7):
        - bot_id がある → 無視（Bot自身の投稿）
        - subtype がある → 無視（編集、削除など）
        - channel が auto_reply_channels に含まれない → 無視
        - メンション付き → 無視（app_mention で処理される）
        """
        # F6-AC6: 自動返信チャンネルが設定されていない場合は無視
        if not auto_reply_channels:
            return

        # F6-AC2: Bot自身の投稿は無視
        if event.get("bot_id"):
            return

        # F6-AC3: サブタイプ付きメッセージ（編集、削除など）は無視
        if event.get("subtype"):
            return

        # F6-AC1: 対象チャンネルのみ処理
        channel: str = event.get("channel", "")
        if channel not in auto_reply_channels:
            return

        text: str = event.get("text", "")

        # F6-AC7: メンション付きメッセージは app_mention で処理されるためスキップ
        # strip_mention と同じパターンを使用
        if re.search(r"<@[A-Za-z0-9]+>\s*", text):
            return

        user_id: str = event.get("user", "")
        # user_id が空の場合はスキップ（システムメッセージなどのエッジケース対応）
        if not user_id:
            return

        raw_thread_ts: str | None = event.get("thread_ts")
        event_ts: str = event.get("ts", "")
        thread_ts: str = raw_thread_ts or event_ts
        files: list[dict[str, object]] | None = event.get("files")

        cleaned_text = text.strip()
        if not cleaned_text:
            return

        logger.info("Processing auto-reply message in channel %s", channel)
        await _process_message(
            user_id, cleaned_text, thread_ts, say, files,
            channel=channel,
            is_in_thread=raw_thread_ts is not None,
            current_ts=event_ts,
        )


async def _safe_extract_profile(
    profiler: UserProfiler, user_id: str, message: str
) -> None:
    """プロファイル抽出を安全に実行する（例外をログに記録）."""
    try:
        await profiler.extract_profile(user_id, message)
    except Exception:
        logger.exception("Failed to extract user profile for %s", user_id)
