"""メッセージルーター — キーワードルーティング + サービス層呼び出し.

仕様: docs/specs/features/cli-adapter.md
handlers.py の _process_message ロジックを移植したクラス。
"""

from __future__ import annotations

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
from py_common_lib.httpx import ConstrainedClient

from src.mcp_bridge.client_manager import MCPToolNotFoundError
from src.messaging.port import IncomingMessage, MessagingPort
from src.services.chat import ChatService
from src.services.remote_control import (
    RemoteControlError,
    RemoteControlLauncher,
    RemoteControlURLTimeoutError,
)

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.mcp_bridge.client_manager import MCPClientManager
    from src.services.feed_collector import FeedCollector

logger = logging.getLogger(__name__)

_DELIVER_KEYWORDS = ("deliver",)
_FEED_KEYWORDS = ("feed",)
_RAG_KEYWORDS = ("rag",)
_RC_KEYWORDS = ("rc",)
_STATUS_KEYWORDS = ("status", "info")

_REMINDER_PREFIX = re.compile(r"^reminder:\s+", re.IGNORECASE)


def _strip_reminder_prefix(text: str) -> str:
    """Slack Reminder のプレフィックスと末尾ピリオドを除去する."""
    lstripped = text.lstrip()
    stripped = _REMINDER_PREFIX.sub("", lstripped)
    if stripped == lstripped:
        return text
    return stripped.rstrip(".")


def _parse_rag_command(text: str) -> tuple[str, str, str]:
    """ragコマンドを解析する."""
    tokens = text.split()
    if len(tokens) < 2:
        return ("", "", "")

    subcommand = tokens[1].lower()
    url = ""
    raw_url_token = ""

    if len(tokens) >= 3:
        url_token = tokens[2].strip("<>")
        if "|" in url_token:
            url_token = url_token.split("|")[0]
        raw_url_token = url_token
        parsed_url = urlparse(url_token)
        if parsed_url.scheme in ("http", "https") and parsed_url.netloc:
            url = url_token

    return (subcommand, url, raw_url_token)


def _parse_feed_command(text: str) -> tuple[str, list[str], str]:
    """feedコマンドを解析する."""
    tokens = text.split()
    if len(tokens) < 2:
        return ("", [], "")

    subcommand = tokens[1].lower()
    urls: list[str] = []
    category_tokens: list[str] = []

    for token in tokens[2:]:
        cleaned = token.strip("<>")
        if "|" in cleaned:
            cleaned = cleaned.split("|")[0]

        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            parsed_url = urlparse(cleaned)
            if parsed_url.netloc:
                urls.append(cleaned)
        elif cleaned.startswith("--"):
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


def _build_status_message(
    timezone: str, env_name: str, bot_start_time: datetime | None = None
) -> str:
    """ボットステータスメッセージを構築する (F5)."""
    hostname = socket.gethostname()
    now = datetime.now(tz=ZoneInfo(timezone))

    lines = ["\U0001f916 ボットステータス", f"ホスト: {hostname}"]

    if env_name:
        lines.append(f"環境: {env_name}")

    if bot_start_time is not None:
        start_str = bot_start_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        uptime = now - bot_start_time
        uptime_str = _format_uptime(uptime.total_seconds())
        lines.append(f"起動: {start_str}（稼働 {uptime_str}）")

    return "\n".join(lines)


# --- Feed ハンドラ群 ---


async def _handle_feed_add(
    collector: FeedCollector, urls: list[str], category: str
) -> str:
    """フィード追加処理."""
    logger.info("handle_feed_add start: urls=%d, category=%s", len(urls), category)

    if not urls:
        logger.info("handle_feed_add complete: result=empty_urls")
        return "エラー: URLを指定してください。\n例: `@bot feed add https://example.com/rss [カテゴリ]`"

    success_count = 0
    error_count = 0
    results: list[str] = []
    for url in urls:
        try:
            name = await collector.fetch_feed_title(url)
            feed = await collector.add_feed(url, name, category)
            results.append(f"✅ {feed.url} を追加しました（名前: {feed.name}、カテゴリ: {feed.category}）")
            success_count += 1
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
            error_count += 1
        except Exception:
            logger.exception("Failed to add feed: %s", url)
            results.append(f"❌ {url}: 追加中にエラーが発生しました")
            error_count += 1

    logger.info(
        "handle_feed_add complete: success=%d, error=%d, total=%d",
        success_count, error_count, len(urls),
    )
    return "\n".join(results)


async def _handle_feed_list(collector: FeedCollector) -> str:
    """フィード一覧表示処理."""
    logger.info("handle_feed_list start")
    enabled, disabled = await collector.list_feeds()

    if not enabled and not disabled:
        logger.info("handle_feed_list complete: enabled=0, disabled=0")
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

    logger.info(
        "handle_feed_list complete: enabled=%d, disabled=%d",
        len(enabled), len(disabled),
    )
    return "\n".join(lines)


async def _handle_feed_delete(collector: FeedCollector, urls: list[str]) -> str:
    """フィード削除処理."""
    logger.info("handle_feed_delete start: urls=%d", len(urls))
    if not urls:
        logger.info("handle_feed_delete complete: result=empty_urls")
        return "エラー: URLを指定してください。\n例: `@bot feed delete https://example.com/rss`"

    success_count = 0
    error_count = 0
    results: list[str] = []
    for url in urls:
        try:
            await collector.delete_feed(url)
            results.append(f"✅ {url} を削除しました")
            success_count += 1
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
            error_count += 1
        except Exception:
            logger.exception("Failed to delete feed: %s", url)
            results.append(f"❌ {url}: 削除中にエラーが発生しました")
            error_count += 1

    logger.info(
        "handle_feed_delete complete: success=%d, error=%d, total=%d",
        success_count, error_count, len(urls),
    )
    return "\n".join(results)


async def _handle_feed_enable(collector: FeedCollector, urls: list[str]) -> str:
    """フィード有効化処理."""
    logger.info("handle_feed_enable start: urls=%d", len(urls))
    if not urls:
        logger.info("handle_feed_enable complete: result=empty_urls")
        return "エラー: URLを指定してください。\n例: `@bot feed enable https://example.com/rss`"

    success_count = 0
    error_count = 0
    results: list[str] = []
    for url in urls:
        try:
            await collector.enable_feed(url)
            results.append(f"✅ {url} を有効化しました")
            success_count += 1
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
            error_count += 1
        except Exception:
            logger.exception("Failed to enable feed: %s", url)
            results.append(f"❌ {url}: 有効化中にエラーが発生しました")
            error_count += 1

    logger.info(
        "handle_feed_enable complete: success=%d, error=%d, total=%d",
        success_count, error_count, len(urls),
    )
    return "\n".join(results)


async def _handle_feed_disable(collector: FeedCollector, urls: list[str]) -> str:
    """フィード無効化処理."""
    logger.info("handle_feed_disable start: urls=%d", len(urls))
    if not urls:
        logger.info("handle_feed_disable complete: result=empty_urls")
        return "エラー: URLを指定してください。\n例: `@bot feed disable https://example.com/rss`"

    success_count = 0
    error_count = 0
    results: list[str] = []
    for url in urls:
        try:
            await collector.disable_feed(url)
            results.append(f"✅ {url} を無効化しました")
            success_count += 1
        except ValueError as e:
            results.append(f"❌ {url}: {e}")
            error_count += 1
        except Exception:
            logger.exception("Failed to disable feed: %s", url)
            results.append(f"❌ {url}: 無効化中にエラーが発生しました")
            error_count += 1

    logger.info(
        "handle_feed_disable complete: success=%d, error=%d, total=%d",
        success_count, error_count, len(urls),
    )
    return "\n".join(results)


async def _download_and_parse_csv(
    files: list[dict[str, object]] | None,
    bot_token: str,
) -> tuple[list[dict[str, str]], str | None]:
    """CSV添付ファイルを検証・ダウンロード・パースする."""
    if not files:
        return ([], (
            "エラー: CSVファイルを添付してください。\n"
            "使用方法: `@bot feed import` または `@bot feed replace` にCSVファイルを添付\n"
            "CSV形式: `url,name,category`"
        ))

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

    max_file_size = 1 * 1024 * 1024
    file_size = csv_file.get("size", 0)
    if isinstance(file_size, int) and file_size > max_file_size:
        return ([], f"エラー: ファイルサイズが大きすぎます（最大1MB、実際: {file_size // 1024}KB）")

    url_private = csv_file.get("url_private")
    if not url_private or not isinstance(url_private, str):
        return ([], "エラー: ファイルのダウンロードURLが取得できませんでした。")

    download_url = csv_file.get("url_private_download") or url_private
    if not isinstance(download_url, str):
        download_url = url_private

    try:
        async with ConstrainedClient(
            request_timeout=30.0,
            headers={"Authorization": f"Bearer {bot_token}"},
        ) as client:
            response = await client.get(download_url)
            if response.status_code == 302:
                logger.error("File download redirected - auth may have failed")
                return ([], "エラー: ファイルのダウンロードに失敗しました（認証エラー）。Bot権限を確認してください。")
            response.raise_for_status()
            content = response.text
    except httpx.HTTPError as e:
        logger.exception("Failed to download CSV file")
        return ([], f"エラー: ファイルのダウンロードに失敗しました: {e}")

    try:
        reader = csv.DictReader(io.StringIO(content))
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
    """CSVの行リストからフィードを登録する."""
    success_count = 0
    errors: list[str] = []

    for line_number, row in enumerate(rows, start=2):
        url = (row.get("url") or "").strip()
        name = (row.get("name") or "").strip()
        category = (row.get("category") or "").strip() or "一般"

        if not url or not name:
            errors.append(f"行{line_number}: url または name が空です")
            continue

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
    logger.info("handle_feed_import start: files=%d", len(files) if files else 0)
    rows, error = await _download_and_parse_csv(files, bot_token)
    if error is not None:
        logger.info("handle_feed_import complete: result=download_or_parse_error")
        return error

    success_count, errors = await _import_feeds_from_rows(collector, rows)

    result_lines = [
        "*フィードインポート完了*",
        f"✅ 成功: {success_count}件",
        f"❌ 失敗: {len(errors)}件",
    ]
    result_lines.extend(_format_error_details(errors))

    logger.info(
        "handle_feed_import complete: success=%d, error=%d, total=%d",
        success_count, len(errors), len(rows),
    )
    return "\n".join(result_lines)


async def _handle_feed_replace(
    collector: FeedCollector,
    files: list[dict[str, object]] | None,
    bot_token: str,
) -> str:
    """CSVファイルで全フィードを置換する（全削除→再登録）."""
    logger.info("handle_feed_replace start: files=%d", len(files) if files else 0)
    rows, error = await _download_and_parse_csv(files, bot_token)
    if error is not None:
        logger.info("handle_feed_replace complete: result=download_or_parse_error")
        return error

    try:
        deleted_count = await collector.delete_all_feeds()
    except Exception:
        logger.exception("Failed to delete all feeds in replace")
        logger.info("handle_feed_replace complete: result=delete_all_failed")
        return (
            "*フィード置換エラー*\n"
            "🗑️ 既存フィードの削除中に予期せぬエラーが発生しました。\n"
            "❌ フィードの置換を完了できませんでした。"
        )

    try:
        success_count, errors = await _import_feeds_from_rows(collector, rows)
    except Exception:
        logger.exception("Failed to import feeds after delete_all in replace")
        logger.info(
            "handle_feed_replace complete: result=import_failed, deleted=%d",
            deleted_count,
        )
        return (
            "*フィード置換エラー*\n"
            f"🗑️ 削除: {deleted_count}件（既存フィード）\n"
            "❌ インポート中に予期せぬエラーが発生しました。"
        )

    result_lines = [
        "*フィード置換完了*",
        f"🗑️ 削除: {deleted_count}件（既存フィード）",
        f"✅ 登録成功: {success_count}件",
        f"❌ 登録失敗: {len(errors)}件",
    ]
    result_lines.extend(_format_error_details(errors))

    logger.info(
        "handle_feed_replace complete: deleted=%d, success=%d, error=%d, total=%d",
        deleted_count, success_count, len(errors), len(rows),
    )
    return "\n".join(result_lines)


async def _handle_feed_export_via_port(
    collector: FeedCollector,
    messaging: MessagingPort,
    thread_id: str,
    channel: str,
) -> str:
    """全フィードをCSV形式でエクスポートする（MessagingPort経由）."""
    logger.info("handle_feed_export start")
    feeds = await collector.get_all_feeds()

    if not feeds:
        logger.info("handle_feed_export complete: result=no_feeds")
        return "エクスポートするフィードがありません。"

    def _sanitize_csv_field(value: str) -> str:
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

    try:
        await messaging.upload_file(
            content=csv_content,
            filename="feeds.csv",
            thread_id=thread_id,
            channel=channel,
            comment=f"フィード一覧をエクスポートしました（{len(feeds)}件）",
        )
    except Exception as e:
        error_msg = str(e)
        if "missing_scope" in error_msg or "not_allowed_token_type" in error_msg:
            logger.error("File upload failed due to missing scope: %s", e)
            logger.info("handle_feed_export complete: result=missing_scope")
            return (
                "エラー: ファイルのアップロードに失敗しました。\n"
                "Slack Appに `files:write` スコープの追加が必要です。"
            )
        logger.exception("Failed to upload CSV file")
        logger.info("handle_feed_export complete: result=upload_error")
        return f"エラー: ファイルのアップロードに失敗しました: {e}"

    logger.info("handle_feed_export complete: feeds=%d", len(feeds))
    return ""


class MessageRouter:
    """キーワードルーティング + サービス層呼び出し.

    仕様: docs/specs/features/cli-adapter.md
    """

    def __init__(
        self,
        messaging: MessagingPort,
        chat_service: ChatService,
        *,
        collector: FeedCollector | None,
        session_factory: async_sessionmaker[AsyncSession] | None,
        channel_id: str | None,
        max_articles_per_feed: int,
        feed_card_layout: Literal["vertical", "horizontal"],
        bot_token: str | None,
        timezone: str,
        env_name: str,
        mcp_manager: MCPClientManager | None,
        bot_start_time: datetime | None,
        slack_client: AsyncWebClient | None,
        rag_bluesky_handle: str,
        rag_zenn_username: str,
        rag_bluesky_max_posts: int,
        rag_zenn_max_articles: int,
        remote_control_launcher: RemoteControlLauncher | None,
        remote_control_allowed_users: list[str],
    ) -> None:
        self._messaging = messaging
        self._chat_service = chat_service
        self._collector = collector
        self._session_factory = session_factory
        self._channel_id = channel_id
        self._max_articles_per_feed = max_articles_per_feed
        self._feed_card_layout = feed_card_layout
        self._bot_token = bot_token
        self._timezone = timezone
        self._env_name = env_name
        self._mcp_manager = mcp_manager
        self._bot_start_time = bot_start_time
        self._slack_client = slack_client
        self._rag_bluesky_handle = rag_bluesky_handle
        self._rag_zenn_username = rag_zenn_username
        self._rag_bluesky_max_posts = rag_bluesky_max_posts
        self._rag_zenn_max_articles = rag_zenn_max_articles
        self._remote_control_launcher = remote_control_launcher
        self._remote_control_allowed_users = remote_control_allowed_users

    async def process_message(self, msg: IncomingMessage) -> None:
        """受信メッセージをキーワードルーティングし、適切なサービスに委譲する."""
        cleaned_text = _strip_reminder_prefix(msg.text)
        if cleaned_text != msg.text:
            logger.debug("strip_reminder_prefix: %r -> %r", msg.text, cleaned_text)
        user_id = msg.user_id
        thread_id = msg.thread_id
        channel = msg.channel

        # ステータスコマンド (F5)
        if cleaned_text.lower().strip() in _STATUS_KEYWORDS:
            logger.info("routing: text=%r -> handler=status", cleaned_text[:200])
            response_text = _build_status_message(
                self._timezone, self._env_name, self._bot_start_time
            )
            await self._messaging.send_message(response_text, thread_id, channel)
            return

        # feedコマンド (F2)
        lower_text = cleaned_text.lower().lstrip()
        if self._collector is not None and any(
            re.match(rf"^{re.escape(kw)}\b", lower_text) for kw in _FEED_KEYWORDS
        ):
            logger.info("routing: text=%r -> handler=feed", cleaned_text[:200])
            await self._handle_feed_command(msg, cleaned_text, lower_text)
            return

        # ragコマンド (F7)
        if self._mcp_manager is not None and any(
            re.match(rf"^{re.escape(kw)}\b", lower_text) for kw in _RAG_KEYWORDS
        ):
            logger.info("routing: text=%r -> handler=rag", cleaned_text[:200])
            await self._handle_rag_command(msg, cleaned_text)
            return

        # rc コマンド (Remote Control 起動)
        if any(re.match(rf"^{re.escape(kw)}\b", lower_text) for kw in _RC_KEYWORDS):
            if self._remote_control_launcher is None:
                logger.info(
                    "routing: text=%r -> handler=rc_disabled", cleaned_text[:200],
                )
                await self._messaging.send_message(
                    "Remote Control 機能は現在無効です。管理者に設定を依頼してください。",
                    thread_id, channel,
                )
                return
            logger.info("routing: text=%r -> handler=rc", cleaned_text[:200])
            await self._handle_rc_command(msg, cleaned_text)
            return

        # 配信テストキーワード (F2)
        if (
            self._collector is not None
            and self._session_factory is not None
            and self._channel_id is not None
            and any(
                re.match(rf"^{re.escape(kw)}\b", lower_text)
                for kw in _DELIVER_KEYWORDS
            )
        ):
            logger.info("routing: text=%r -> handler=deliver", cleaned_text[:200])
            await self._handle_deliver(msg)
            return

        # デフォルト: ChatService で応答
        logger.info("routing: text=%r -> handler=chat", cleaned_text[:200])
        try:
            response = await self._chat_service.respond(
                user_id=user_id,
                text=cleaned_text,
                thread_ts=thread_id,
                channel=channel,
                is_in_thread=msg.is_in_thread,
                current_ts=msg.message_id,
            )
            await self._messaging.send_message(response, thread_id, channel)
        except Exception:
            logger.exception("Failed to generate response")
            await self._messaging.send_message(
                "申し訳ありません、応答の生成中にエラーが発生しました。しばらくしてからもう一度お試しください。",
                thread_id, channel,
            )

    async def _handle_feed_command(
        self, msg: IncomingMessage, cleaned_text: str, lower_text: str
    ) -> None:
        """feedコマンドのルーティング."""
        assert self._collector is not None
        thread_id = msg.thread_id
        channel = msg.channel

        subcommand, urls, category = _parse_feed_command(cleaned_text)
        logger.info(
            "handle_feed_command start: subcommand=%s, urls=%d, category=%s",
            subcommand, len(urls), category,
        )
        logger.debug("feed command parsed: subcommand=%s, urls=%s, category=%s", subcommand, urls, category)

        if subcommand == "add":
            response_text = await _handle_feed_add(self._collector, urls, category)
        elif subcommand == "list":
            response_text = await _handle_feed_list(self._collector)
        elif subcommand == "delete":
            response_text = await _handle_feed_delete(self._collector, urls)
        elif subcommand == "enable":
            response_text = await _handle_feed_enable(self._collector, urls)
        elif subcommand == "disable":
            response_text = await _handle_feed_disable(self._collector, urls)
        elif subcommand == "import":
            if not self._bot_token:
                response_text = "エラー: Bot Tokenが設定されていません。"
            else:
                response_text = await _handle_feed_import(
                    self._collector, msg.files, self._bot_token
                )
        elif subcommand == "replace":
            if not self._bot_token:
                response_text = "エラー: Bot Tokenが設定されていません。"
            else:
                response_text = await _handle_feed_replace(
                    self._collector, msg.files, self._bot_token
                )
        elif subcommand == "export":
            response_text = await _handle_feed_export_via_port(
                self._collector, self._messaging, thread_id, channel
            )
            if response_text:
                await self._messaging.send_message(response_text, thread_id, channel)
            logger.info("handle_feed_command complete: subcommand=export")
            return
        elif subcommand == "collect":
            await self._handle_feed_collect(msg, cleaned_text)
            logger.info("handle_feed_command complete: subcommand=collect")
            return
        elif subcommand == "test":
            await self._handle_feed_test(msg)
            logger.info("handle_feed_command complete: subcommand=test")
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

        await self._messaging.send_message(response_text, thread_id, channel)
        logger.info("handle_feed_command complete: subcommand=%s", subcommand)

    async def _handle_feed_collect(
        self, msg: IncomingMessage, cleaned_text: str
    ) -> None:
        """feed collect コマンド処理."""
        logger.info("handle_feed_collect start")
        thread_id = msg.thread_id
        channel = msg.channel

        if "--skip-summary" in cleaned_text.lower():
            if (
                self._collector is not None
                and self._session_factory is not None
                and self._channel_id is not None
                and self._slack_client is not None
            ):
                from src.scheduler.jobs import daily_collect_and_deliver

                try:
                    await self._messaging.send_message(
                        "要約スキップ収集を開始します...", thread_id, channel
                    )
                    feed_count, article_count = await daily_collect_and_deliver(
                        self._collector, self._session_factory,
                        self._slack_client, self._channel_id,
                        max_articles_per_feed=self._max_articles_per_feed,
                        layout=self._feed_card_layout,
                        skip_summary=True,
                    )
                    await self._messaging.send_message(
                        f"要約スキップ収集が完了しました\n収集フィード数: {feed_count}\n収集記事数: {article_count}",
                        thread_id, channel,
                    )
                    logger.info(
                        "handle_feed_collect complete: feeds=%d, articles=%d",
                        feed_count, article_count,
                    )
                except Exception:
                    logger.exception("Failed to collect feeds with skip-summary")
                    await self._messaging.send_message(
                        "要約スキップ収集中にエラーが発生しました。",
                        thread_id, channel,
                    )
                    logger.info("handle_feed_collect complete: result=error")
            else:
                await self._messaging.send_message(
                    "エラー: 配信設定が不足しています。", thread_id, channel
                )
                logger.info("handle_feed_collect complete: result=missing_config")
        else:
            response_text = (
                "使用方法:\n"
                "• `@bot feed collect --skip-summary` — 要約なし一括収集"
            )
            await self._messaging.send_message(response_text, thread_id, channel)
            logger.info("handle_feed_collect complete: result=usage_help")

    async def _handle_feed_test(self, msg: IncomingMessage) -> None:
        """feed test コマンド処理."""
        logger.info("handle_feed_test start")
        thread_id = msg.thread_id
        channel = msg.channel

        if (
            self._session_factory is not None
            and self._channel_id is not None
            and self._slack_client is not None
        ):
            from src.scheduler.jobs import feed_test_deliver

            try:
                await self._messaging.send_message(
                    "テスト配信を開始します...", thread_id, channel
                )
                await feed_test_deliver(
                    session_factory=self._session_factory,
                    slack_client=self._slack_client,
                    channel_id=self._channel_id,
                    layout=self._feed_card_layout,
                )
                await self._messaging.send_message(
                    "テスト配信が完了しました", thread_id, channel
                )
                logger.info("handle_feed_test complete: result=success")
            except Exception:
                logger.exception("Failed to run feed test delivery")
                await self._messaging.send_message(
                    "テスト配信中にエラーが発生しました。",
                    thread_id, channel,
                )
                logger.info("handle_feed_test complete: result=error")
        else:
            await self._messaging.send_message(
                "エラー: 配信設定が不足しています（Slack接続が必要です）。",
                thread_id, channel,
            )
            logger.info("handle_feed_test complete: result=missing_config")

    async def _handle_deliver(self, msg: IncomingMessage) -> None:
        """deliver コマンド処理."""
        logger.info("handle_deliver start")
        assert self._collector is not None
        assert self._session_factory is not None
        assert self._channel_id is not None
        thread_id = msg.thread_id
        channel = msg.channel

        if self._slack_client is None:
            await self._messaging.send_message(
                "エラー: deliver コマンドは Slack 接続時のみ使用できます。",
                thread_id, channel,
            )
            logger.info("handle_deliver complete: result=no_slack_client")
            return

        from src.scheduler.jobs import daily_collect_and_deliver

        try:
            await self._messaging.send_message(
                "配信を開始します...", thread_id, channel
            )
            await daily_collect_and_deliver(
                self._collector, self._session_factory,
                self._slack_client, self._channel_id,
                max_articles_per_feed=self._max_articles_per_feed,
                layout=self._feed_card_layout,
            )
            await self._messaging.send_message(
                "配信が完了しました", thread_id, channel
            )
            logger.info("handle_deliver complete: result=success")
        except Exception:
            logger.exception("Failed to run manual delivery")
            await self._messaging.send_message(
                "配信中にエラーが発生しました。", thread_id, channel
            )
            logger.info("handle_deliver complete: result=error")

    async def _handle_rag_command(
        self, msg: IncomingMessage, cleaned_text: str
    ) -> None:
        """ragコマンドのルーティング（MCP経由）."""
        assert self._mcp_manager is not None
        thread_id = msg.thread_id
        channel = msg.channel

        subcommand, url, raw_url_token = _parse_rag_command(cleaned_text)
        logger.info("handle_rag_command start: subcommand=%s", subcommand)
        logger.debug("rag command parsed: subcommand=%s, url=%s", subcommand, url)

        if subcommand == "status":
            try:
                response_text = await self._mcp_manager.call_tool("rag_stats", {})
            except MCPToolNotFoundError:
                response_text = "エラー: RAG統計ツールが利用できません。"
            except Exception:
                logger.exception("Failed to call rag_stats tool")
                response_text = "エラー: 統計情報の取得中にエラーが発生しました。"
        elif subcommand == "delete":
            response_text = await self._call_rag_url_tool(
                "rag_delete", url, raw_url_token,
                usage_hint="例: `@bot rag delete https://example.com/page`",
            )
        elif subcommand == "update":
            await self._handle_rag_update(thread_id, channel)
            logger.info("handle_rag_command complete: subcommand=update")
            return
        elif subcommand == "rebuild":
            tokens = cleaned_text.split()
            mode = tokens[2] if len(tokens) >= 3 else "index"
            await self._handle_rag_rebuild(mode, thread_id, channel)
            logger.info("handle_rag_command complete: subcommand=rebuild")
            return
        elif subcommand == "help":
            await self._handle_rag_help(thread_id, channel)
            logger.info("handle_rag_command complete: subcommand=help")
            return
        else:
            response_text = (
                "使用方法:\n"
                "• `@bot rag status` — ナレッジベース統計表示\n"
                "• `@bot rag delete <URL>` — ソースURL指定で削除\n"
                "• `@bot rag update` — BlueSky・Zenn の定期更新\n"
                "• `@bot rag rebuild [mode]` — インデックス再構築（mode: full/convert/index/incremental、デフォルト: index）\n"
                "• `@bot rag help` — RAG MCPツール一覧を表示"
            )

        if response_text:
            await self._messaging.send_message(response_text, thread_id, channel)
        logger.info("handle_rag_command complete: subcommand=%s", subcommand)

    async def _call_rag_url_tool(
        self,
        tool_name: str,
        url: str,
        raw_url_token: str,
        usage_hint: str,
    ) -> str:
        """URL必須のRAGツールを呼び出す共通ヘルパー."""
        assert self._mcp_manager is not None
        if not url:
            if raw_url_token:
                return f"エラー: 無効なURLスキームです: {raw_url_token}\nhttp:// または https:// で始まるURLを指定してください。"
            return f"エラー: URLを指定してください。\n{usage_hint}"

        try:
            return await self._mcp_manager.call_tool(tool_name, {"url": url})
        except MCPToolNotFoundError:
            return f"エラー: ツール '{tool_name}' が利用できません。"
        except Exception:
            logger.exception("Failed to call %s tool", tool_name)
            return f"エラー: ツール '{tool_name}' の実行中にエラーが発生しました。"

    async def _handle_rag_update(
        self, thread_id: str, channel: str,
    ) -> None:
        """BlueSky・Zenn の定期更新を一括実行する."""
        logger.info("handle_rag_update start")
        assert self._mcp_manager is not None

        if not self._rag_bluesky_handle and not self._rag_zenn_username:
            await self._messaging.send_message(
                "エラー: RAG_BLUESKY_HANDLE / RAG_ZENN_USERNAME が .env に設定されていません。",
                thread_id, channel,
            )
            logger.info("handle_rag_update complete: result=missing_config")
            return

        targets: list[tuple[str, str, dict[str, object]]] = []
        if self._rag_bluesky_handle:
            targets.append(("BlueSky", "rag_crawl_bluesky", {
                "handle": self._rag_bluesky_handle, "max_posts": self._rag_bluesky_max_posts,
            }))
        if self._rag_zenn_username:
            targets.append(("Zenn", "rag_crawl_zenn", {
                "username": self._rag_zenn_username, "max_articles": self._rag_zenn_max_articles,
            }))

        await self._messaging.send_message(
            "RAG更新を開始します...", thread_id, channel,
        )

        results: list[str] = []
        for label, tool, args in targets:
            try:
                result = await self._mcp_manager.call_tool(tool, args)
                results.append(f"*{label}*: {result}")
            except MCPToolNotFoundError:
                results.append(f"*{label}*: エラー — ツール '{tool}' が利用できません")
            except Exception:
                logger.exception("Failed to call %s tool", tool)
                results.append(f"*{label}*: エラー — 実行中にエラーが発生しました")

        await self._messaging.send_message(
            "\n".join(results), thread_id, channel,
        )
        logger.info("handle_rag_update complete: targets=%d", len(targets))

    _VALID_REBUILD_MODES = frozenset({"full", "convert", "index", "incremental"})

    async def _handle_rag_rebuild(
        self, mode: str, thread_id: str, channel: str,
    ) -> None:
        """RAG インデックスの再構築を実行する."""
        logger.info("handle_rag_rebuild start: mode=%s", mode)
        assert self._mcp_manager is not None

        if mode not in self._VALID_REBUILD_MODES:
            await self._messaging.send_message(
                f"エラー: 無効なモードです: {mode}\n"
                f"有効な mode: {', '.join(sorted(self._VALID_REBUILD_MODES))}",
                thread_id, channel,
            )
            logger.info("handle_rag_rebuild complete: result=invalid_mode")
            return

        await self._messaging.send_message(
            f"RAGリビルドを開始します（mode: {mode}）...", thread_id, channel,
        )

        try:
            result = await self._mcp_manager.call_tool(
                "rag_rebuild", {"mode": mode},
            )
            response_text = result
        except MCPToolNotFoundError:
            response_text = "エラー: RAGリビルドツールが利用できません。"
        except Exception:
            logger.exception("Failed to call rag_rebuild tool")
            response_text = "エラー: リビルド中にエラーが発生しました。"

        await self._messaging.send_message(response_text, thread_id, channel)
        logger.info("handle_rag_rebuild complete: mode=%s", mode)

    async def _handle_rag_help(
        self, thread_id: str, channel: str,
    ) -> None:
        """RAG MCPツール一覧を動的に取得して表示する."""
        logger.info("handle_rag_help start")
        assert self._mcp_manager is not None

        try:
            tools = await self._mcp_manager.get_available_tools()
        except Exception:
            logger.exception("Failed to get available tools")
            await self._messaging.send_message(
                "エラー: RAG ツール一覧の取得に失敗しました。",
                thread_id, channel,
            )
            logger.info("handle_rag_help complete: result=tools_fetch_error")
            return

        rag_tools = [t for t in tools if t.name.startswith("rag_")]

        if not rag_tools:
            await self._messaging.send_message(
                "RAG ツールが見つかりません。MCP サーバーが起動しているか確認してください。",
                thread_id, channel,
            )
            logger.info("handle_rag_help complete: result=no_rag_tools")
            return

        lines = ["*RAG MCPツール一覧:*\n"]
        for tool in sorted(rag_tools, key=lambda t: t.name):
            first_line = tool.description.split("\n")[0] if tool.description else ""
            # "[サーバー名] 英語概要 - 日本語説明" から日本語部分を抽出
            desc = first_line.split(" - ", 1)[1] if " - " in first_line else first_line
            desc = desc or "(説明なし)"
            lines.append(f"• `{tool.name}` — {desc}")

        await self._messaging.send_message("\n".join(lines), thread_id, channel)
        logger.info("handle_rag_help complete: tools=%d", len(rag_tools))

    async def _handle_rc_command(
        self, msg: IncomingMessage, cleaned_text: str,
    ) -> None:
        """rc コマンドのルーティング（Remote Control 起動）.

        仕様: docs/specs/features/remote-control-launch.md
        """
        logger.info("handle_rc_command start: user=%s", msg.user_id)
        assert self._remote_control_launcher is not None
        thread_id = msg.thread_id
        channel = msg.channel

        if msg.user_id not in self._remote_control_allowed_users:
            logger.warning(
                "rc command denied: user=%s not in allowlist", msg.user_id,
            )
            await self._messaging.send_message(
                "❌ このコマンドを実行する権限がありません",
                thread_id, channel,
            )
            logger.info("handle_rc_command complete: result=permission_denied")
            return

        tokens = cleaned_text.split()
        if len(tokens) < 2:
            await self._messaging.send_message(
                self._build_rc_usage(), thread_id, channel,
            )
            logger.info("handle_rc_command complete: result=usage")
            return

        subcommand = tokens[1].lower()
        if subcommand != "start":
            await self._messaging.send_message(
                self._build_rc_usage(), thread_id, channel,
            )
            logger.info("handle_rc_command complete: result=invalid_subcommand")
            return

        if len(tokens) < 3:
            await self._messaging.send_message(
                "エラー: リポジトリキーを指定してください。\n" + self._build_rc_usage(),
                thread_id, channel,
            )
            logger.info("handle_rc_command complete: result=missing_repo_key")
            return

        repo_key = tokens[2]

        try:
            result = await self._remote_control_launcher.launch(repo_key)
        except RemoteControlURLTimeoutError as e:
            await self._messaging.send_message(f"⌛ {e}", thread_id, channel)
            logger.info("handle_rc_command complete: result=url_timeout, repo_key=%s", repo_key)
            return
        except RemoteControlError as e:
            # 既知エラー（未登録 key / claude 未インストール / プロセス即時終了 等）は
            # サービス層が日本語メッセージを組み立て済みのため、そのまま転送する
            await self._messaging.send_message(f"❌ {e}", thread_id, channel)
            logger.info("handle_rc_command complete: result=known_error, repo_key=%s", repo_key)
            return
        except Exception:
            logger.exception("Failed to launch remote control: repo_key=%s", repo_key)
            await self._messaging.send_message(
                "❌ Remote Control の起動中に予期せぬエラーが発生しました。",
                thread_id, channel,
            )
            logger.info("handle_rc_command complete: result=unexpected_error, repo_key=%s", repo_key)
            return

        response = (
            "✅ Remote Control を起動しました\n"
            f"リポジトリ: {repo_key}\n"
            f"セッション名: {result.session_name}\n"
            f"接続: {result.connect_url}"
        )
        await self._messaging.send_message(response, thread_id, channel)
        logger.info(
            "handle_rc_command complete: result=success, repo_key=%s, session=%s",
            repo_key, result.session_name,
        )

    def _build_rc_usage(self) -> str:
        """rc コマンドの使用方法と登録済み repo-key を返す."""
        assert self._remote_control_launcher is not None
        repos = self._remote_control_launcher.get_repositories()
        registered = ", ".join(sorted(repos.keys())) or "(未登録)"
        return (
            "使用方法:\n"
            "• `@bot rc start <repo-key>` — 指定リポジトリで Claude Code Remote Control を起動\n"
            f"登録済み: {registered}"
        )

