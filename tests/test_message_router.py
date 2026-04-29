"""MessageRouter のテスト (Issue #496)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from src.llm.base import Message, ToolDefinition
from src.mcp_bridge.client_manager import MCPToolNotFoundError
from src.messaging.port import IncomingMessage, MessagingPort

from src.messaging.router import (
    MessageRouter,
    _build_status_message,
    _format_uptime,
    _parse_rag_command,
    _strip_reminder_prefix,
)


# --- MockAdapter ---


class MockAdapter(MessagingPort):
    """テスト用モックアダプター."""

    def __init__(self) -> None:
        self.sent_messages: list[tuple[str, str, str]] = []
        self.uploaded_files: list[tuple[str, str, str, str, str]] = []

    async def send_message(self, text: str, thread_id: str, channel: str) -> None:
        self.sent_messages.append((text, thread_id, channel))

    async def upload_file(
        self, content: str, filename: str,
        thread_id: str, channel: str, comment: str,
    ) -> None:
        self.uploaded_files.append((content, filename, thread_id, channel, comment))

    async def fetch_thread_history(
        self, channel: str, thread_id: str, current_message_id: str
    ) -> list[Message] | None:
        return None

    def get_format_instruction(self) -> str:
        return ""

    def get_bot_user_id(self) -> str:
        return "mock-bot"


def _make_msg(text: str, user_id: str = "U1", channel: str = "cli") -> IncomingMessage:
    return IncomingMessage(
        user_id=user_id,
        text=text,
        thread_id="t1",
        channel=channel,
        is_in_thread=False,
        message_id="m1",
    )


def _make_router(
    adapter: MockAdapter | None = None,
    chat_service: AsyncMock | None = None,
    collector: AsyncMock | None = None,
    session_factory: AsyncMock | None = None,
    mcp_manager: AsyncMock | None = None,
    bot_start_time: datetime | None = None,
    rag_bluesky_handle: str = "",
    rag_zenn_username: str = "",
    max_articles_per_feed: int = 10,
    feed_card_layout: Literal["vertical", "horizontal"] = "horizontal",
    bot_token: str | None = None,
    slack_client: AsyncMock | None = None,
    remote_control_launcher: object | None = None,
    remote_control_allowed_users: list[str] | None = None,
) -> tuple[MockAdapter, MessageRouter]:
    if adapter is None:
        adapter = MockAdapter()
    if chat_service is None:
        chat_service = AsyncMock()
        chat_service.respond.return_value = "チャット応答"

    router = MessageRouter(
        messaging=adapter,
        chat_service=chat_service,
        collector=collector,
        session_factory=session_factory,
        channel_id="C_TEST",
        max_articles_per_feed=max_articles_per_feed,
        feed_card_layout=feed_card_layout,
        bot_token=bot_token,
        timezone="Asia/Tokyo",
        env_name="test",
        mcp_manager=mcp_manager,
        bot_start_time=bot_start_time,
        slack_client=slack_client,
        rag_bluesky_handle=rag_bluesky_handle,
        rag_zenn_username=rag_zenn_username,
        rag_bluesky_max_posts=100,
        rag_zenn_max_articles=10,
        remote_control_launcher=remote_control_launcher,  # type: ignore[arg-type]
        remote_control_allowed_users=remote_control_allowed_users or [],
    )
    return adapter, router


# --- ユーティリティ関数テスト ---


def test_format_uptime_hours_and_minutes() -> None:
    """稼働時間のフォーマット（時間+分）."""
    assert _format_uptime(7500.0) == "2時間5分"


def test_format_uptime_minutes_only() -> None:
    """稼働時間のフォーマット（分のみ）."""
    assert _format_uptime(300.0) == "5分"


def test_format_uptime_zero() -> None:
    """稼働時間のフォーマット（0分）."""
    assert _format_uptime(0.0) == "0分"


def test_build_status_with_env_name() -> None:
    """ステータスメッセージに環境名が含まれる."""
    start_time = datetime(2026, 2, 5, 10, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = start_time + timedelta(hours=2, minutes=15)

    with patch("src.messaging.router.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = datetime
        result = _build_status_message("Asia/Tokyo", "production", start_time)

    assert "ボットステータス" in result
    assert "環境: production" in result
    assert "稼働 2時間15分" in result


def test_build_status_without_env_name() -> None:
    """環境名が未設定の場合は省略される."""
    start_time = datetime(2026, 2, 5, 10, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    now = start_time + timedelta(minutes=30)

    with patch("src.messaging.router.datetime") as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.side_effect = datetime
        result = _build_status_message("Asia/Tokyo", "", start_time)

    assert "ボットステータス" in result
    assert "環境:" not in result


# --- ルーティングテスト ---


async def test_status_command() -> None:
    """status コマンドでステータスが返される."""
    start = datetime.now(tz=ZoneInfo("Asia/Tokyo"))
    adapter, router = _make_router(bot_start_time=start)

    await router.process_message(_make_msg("status"))

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "ボットステータス" in text


async def test_info_command() -> None:
    """info コマンドでもステータスが返される."""
    start = datetime.now(tz=ZoneInfo("Asia/Tokyo"))
    adapter, router = _make_router(bot_start_time=start)

    await router.process_message(_make_msg("info"))

    assert len(adapter.sent_messages) == 1
    assert "ボットステータス" in adapter.sent_messages[0][0]


async def test_status_case_insensitive() -> None:
    """ステータスコマンドは大文字小文字不問."""
    start = datetime.now(tz=ZoneInfo("Asia/Tokyo"))
    for text in ["STATUS", "Status", "INFO", "Info"]:
        adapter, router = _make_router(bot_start_time=start)
        await router.process_message(_make_msg(text))
        assert "ボットステータス" in adapter.sent_messages[0][0], f"Failed for: {text}"


async def test_feed_list_command() -> None:
    """feed list コマンド."""
    collector = AsyncMock()
    collector.list_feeds.return_value = ([], [])
    adapter, router = _make_router(collector=collector)

    await router.process_message(_make_msg("feed list"))

    assert len(adapter.sent_messages) == 1
    assert "フィードが登録されていません" in adapter.sent_messages[0][0]


async def test_feed_unknown_subcommand() -> None:
    """feed の不明なサブコマンドでヘルプが表示される."""
    collector = AsyncMock()
    adapter, router = _make_router(collector=collector)

    await router.process_message(_make_msg("feed"))

    assert len(adapter.sent_messages) == 1
    assert "使用方法" in adapter.sent_messages[0][0]


async def test_default_chat_response() -> None:
    """キーワードに一致しない場合は ChatService で応答."""
    chat_service = AsyncMock()
    chat_service.respond.return_value = "こんにちは！"
    adapter, router = _make_router(chat_service=chat_service)

    await router.process_message(_make_msg("やあ"))

    assert len(adapter.sent_messages) == 1
    assert "こんにちは！" in adapter.sent_messages[0][0]
    chat_service.respond.assert_called_once()


async def test_chat_error_handling() -> None:
    """ChatService のエラーが適切にハンドリングされる."""
    chat_service = AsyncMock()
    chat_service.respond.side_effect = RuntimeError("API error")
    adapter, router = _make_router(chat_service=chat_service)

    await router.process_message(_make_msg("test"))

    assert len(adapter.sent_messages) == 1
    assert "エラー" in adapter.sent_messages[0][0]


async def test_feed_export_command() -> None:
    """feed export コマンドでファイルアップロードが呼ばれる."""
    collector = AsyncMock()
    feed_mock = AsyncMock()
    feed_mock.url = "http://example.com/rss"
    feed_mock.name = "Example"
    feed_mock.category = "Tech"
    collector.get_all_feeds.return_value = [feed_mock]
    adapter, router = _make_router(collector=collector)

    await router.process_message(_make_msg("feed export"))

    assert len(adapter.uploaded_files) == 1
    assert "feeds.csv" in adapter.uploaded_files[0][1]


# --- _parse_rag_command テスト ---


class TestParseRagCommand:
    """_parse_rag_command のユニットテスト."""

    def test_empty_input(self) -> None:
        """トークンが1つだけなら空タプルを返す."""
        assert _parse_rag_command("rag") == ("", "", "")

    def test_subcommand_only(self) -> None:
        """サブコマンドのみ."""
        sub, url, raw = _parse_rag_command("rag status")
        assert sub == "status"
        assert url == ""

    def test_valid_url(self) -> None:
        """有効な URL が正しくパースされる."""
        sub, url, raw = _parse_rag_command("rag delete https://example.com/page")
        assert sub == "delete"
        assert url == "https://example.com/page"

    def test_invalid_url_no_netloc(self) -> None:
        """netloc が無い URL は無効として扱う."""
        sub, url, raw = _parse_rag_command("rag delete not-a-url")
        assert sub == "delete"
        assert url == ""
        assert raw == "not-a-url"

    def test_slack_url_format(self) -> None:
        """Slack の <URL|表示名> 形式が正しく処理される."""
        sub, url, raw = _parse_rag_command(
            "rag delete <https://example.com|example.com>"
        )
        assert url == "https://example.com"


# --- rag コマンドルーティングテスト ---


async def test_rag_status_command() -> None:
    """rag status コマンドで rag_stats ツールが呼ばれる."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "総チャンク数: 100"
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag status"))

    assert len(adapter.sent_messages) == 1
    assert "総チャンク数: 100" in adapter.sent_messages[0][0]
    mcp_manager.call_tool.assert_called_once_with("rag_stats", {})


async def test_rag_unknown_subcommand_shows_help() -> None:
    """rag の不明なサブコマンドでヘルプが表示される."""
    mcp_manager = AsyncMock()
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag"))

    assert len(adapter.sent_messages) == 1
    assert "使用方法" in adapter.sent_messages[0][0]


async def test_rag_tool_not_found() -> None:
    """MCP ツールが見つからない場合のエラーハンドリング."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = MCPToolNotFoundError("rag_stats")
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag status"))

    assert len(adapter.sent_messages) == 1
    assert "利用できません" in adapter.sent_messages[0][0]


async def test_rag_delete_command() -> None:
    """rag delete コマンドで rag_delete ツールが呼ばれる."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "削除しました"
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag delete https://example.com/page"))

    assert len(adapter.sent_messages) == 1
    assert "削除しました" in adapter.sent_messages[0][0]
    mcp_manager.call_tool.assert_called_once_with(
        "rag_delete", {"url": "https://example.com/page"}
    )


async def test_rag_status_generic_error() -> None:
    """rag status で予期しない例外が発生した場合のエラーメッセージ."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = RuntimeError("connection failed")
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag status"))

    assert len(adapter.sent_messages) == 1
    assert "エラー" in adapter.sent_messages[0][0]


async def test_rag_update_both_configured() -> None:
    """rag update で BlueSky・Zenn 両方が設定済みなら両方呼ばれる."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "取り込み完了"
    adapter, router = _make_router(
        mcp_manager=mcp_manager,
        rag_bluesky_handle="user.bsky.social",
        rag_zenn_username="testuser",
    )

    await router.process_message(_make_msg("rag update"))

    assert len(adapter.sent_messages) == 2  # start message + results
    assert mcp_manager.call_tool.call_count == 2
    calls = mcp_manager.call_tool.call_args_list
    assert calls[0].args == ("rag_crawl_bluesky", {"handle": "user.bsky.social", "max_posts": 100})
    assert calls[1].args == ("rag_crawl_zenn", {"username": "testuser", "max_articles": 10})


async def test_rag_update_bluesky_only() -> None:
    """rag update で BlueSky のみ設定なら BlueSky だけ呼ばれる."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "取り込み完了"
    adapter, router = _make_router(
        mcp_manager=mcp_manager,
        rag_bluesky_handle="user.bsky.social",
    )

    await router.process_message(_make_msg("rag update"))

    assert len(adapter.sent_messages) == 2
    mcp_manager.call_tool.assert_called_once_with(
        "rag_crawl_bluesky", {"handle": "user.bsky.social", "max_posts": 100}
    )


async def test_rag_update_none_configured() -> None:
    """rag update で両方未設定ならエラーメッセージが返る."""
    mcp_manager = AsyncMock()
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag update"))

    assert len(adapter.sent_messages) == 1
    assert "エラー" in adapter.sent_messages[0][0]
    mcp_manager.call_tool.assert_not_called()


async def test_rag_update_tool_not_found() -> None:
    """rag update でツールが見つからない場合のエラーハンドリング."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = MCPToolNotFoundError("rag_crawl_bluesky")
    adapter, router = _make_router(
        mcp_manager=mcp_manager,
        rag_bluesky_handle="user.bsky.social",
        rag_zenn_username="testuser",
    )

    await router.process_message(_make_msg("rag update"))

    assert len(adapter.sent_messages) == 2
    result_msg = adapter.sent_messages[1][0]
    assert "利用できません" in result_msg


async def test_rag_rebuild_default_mode() -> None:
    """rag rebuild でモード省略時は index になる."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "リビルド完了"
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag rebuild"))

    assert len(adapter.sent_messages) == 2  # start message + result
    mcp_manager.call_tool.assert_called_once_with("rag_rebuild", {"mode": "index"})


async def test_rag_rebuild_explicit_mode() -> None:
    """rag rebuild full で指定したモードが渡される."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "リビルド完了"
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag rebuild full"))

    mcp_manager.call_tool.assert_called_once_with("rag_rebuild", {"mode": "full"})


async def test_rag_rebuild_invalid_mode() -> None:
    """rag rebuild に無効なモードを指定するとエラーメッセージが返る."""
    mcp_manager = AsyncMock()
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag rebuild invalid"))

    assert len(adapter.sent_messages) == 1
    assert "無効なモード" in adapter.sent_messages[0][0]
    mcp_manager.call_tool.assert_not_called()


async def test_rag_rebuild_tool_not_found() -> None:
    """rag rebuild でツールが見つからない場合のエラーハンドリング."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.side_effect = MCPToolNotFoundError("rag_rebuild")
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag rebuild index"))

    assert len(adapter.sent_messages) == 2
    assert "利用できません" in adapter.sent_messages[1][0]


async def test_rag_help_shows_mcp_tool_list() -> None:
    """rag help で MCP ツール一覧が表示される."""
    mcp_manager = AsyncMock()
    mcp_manager.get_available_tools.return_value = [
        ToolDefinition(name="rag_search", description="[rag-knowledge] RAG search - ナレッジベース検索", input_schema={}),
        ToolDefinition(name="rag_stats", description="統計情報表示", input_schema={}),
        ToolDefinition(name="other_tool", description="別のツール", input_schema={}),
    ]
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag help"))

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "rag_search" in text
    assert "ナレッジベース検索" in text
    assert "[rag-knowledge]" not in text
    assert "rag_stats" in text
    assert "other_tool" not in text


async def test_rag_help_no_tools_shows_error() -> None:
    """rag help で RAG ツールが0件の場合エラーが表示される."""
    mcp_manager = AsyncMock()
    mcp_manager.get_available_tools.return_value = []
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag help"))

    assert len(adapter.sent_messages) == 1
    assert "見つかりません" in adapter.sent_messages[0][0]


async def test_rag_help_exception_shows_error() -> None:
    """rag help でツール取得に失敗した場合エラーが表示される."""
    mcp_manager = AsyncMock()
    mcp_manager.get_available_tools.side_effect = RuntimeError("connection failed")
    adapter, router = _make_router(mcp_manager=mcp_manager)

    await router.process_message(_make_msg("rag help"))

    assert len(adapter.sent_messages) == 1
    assert "エラー" in adapter.sent_messages[0][0]


async def test_rag_without_mcp_falls_through_to_chat() -> None:
    """MCP マネージャーが無い場合は rag がチャットにフォールスルーする."""
    chat_service = AsyncMock()
    chat_service.respond.return_value = "チャット応答"
    adapter, router = _make_router(chat_service=chat_service, mcp_manager=None)

    await router.process_message(_make_msg("rag status"))

    assert len(adapter.sent_messages) == 1
    chat_service.respond.assert_called_once()


# --- _strip_reminder_prefix テスト ---


def test_strip_reminder_prefix_removes_prefix_and_trailing_dot() -> None:
    """Slack Reminder プレフィックスと末尾ピリオドが除去される."""
    assert _strip_reminder_prefix("Reminder: deliver.") == "deliver"


def test_strip_reminder_prefix_case_insensitive() -> None:
    """大文字小文字を問わず除去される."""
    assert _strip_reminder_prefix("reminder: rag update.") == "rag update"


def test_strip_reminder_prefix_no_prefix() -> None:
    """プレフィックスがなければそのまま返す（先頭空白・末尾ピリオドも残る）."""
    assert _strip_reminder_prefix("rag update.") == "rag update."
    assert _strip_reminder_prefix("  rag update") == "  rag update"


def test_strip_reminder_prefix_no_trailing_dot() -> None:
    """Reminder プレフィックスありでも末尾ピリオドがなければそのまま."""
    assert _strip_reminder_prefix("Reminder: rag update") == "rag update"


def test_strip_reminder_prefix_leading_whitespace() -> None:
    """先頭空白 + Reminder プレフィックスが除去される."""
    assert _strip_reminder_prefix("  Reminder: feed list.") == "feed list"


def test_strip_reminder_prefix_no_space_after_colon() -> None:
    """Reminder: の後に空白なしの場合はプレフィックス除去しない."""
    assert _strip_reminder_prefix("Reminder:deliver") == "Reminder:deliver"


# --- Reminder プレフィックス経由のルーティングテスト ---


async def test_reminder_rag_update_routes_to_rag_command() -> None:
    """Reminder 経由の rag update がコマンドとして認識される (#823)."""
    mcp_manager = AsyncMock()
    mcp_manager.call_tool.return_value = "取り込み完了"
    adapter, router = _make_router(
        mcp_manager=mcp_manager,
        rag_bluesky_handle="user.bsky.social",
    )

    await router.process_message(_make_msg("Reminder: rag update."))

    assert len(adapter.sent_messages) == 2
    mcp_manager.call_tool.assert_called_once()


async def test_reminder_deliver_routes_to_deliver() -> None:
    """Reminder 経由の deliver が deliver ハンドラに到達する."""
    collector = AsyncMock()
    session_factory = AsyncMock()
    adapter, router = _make_router(
        collector=collector,
        session_factory=session_factory,
    )

    await router.process_message(_make_msg("Reminder: deliver."))

    assert len(adapter.sent_messages) == 1
    assert "Slack 接続時のみ" in adapter.sent_messages[0][0]


# --- rc コマンドテスト (Issue #831) ---


def _make_rc_launcher(
    *,
    repositories: dict[str, str] | None = None,
    launch_result: object | None = None,
    launch_exception: BaseException | None = None,
) -> object:
    """RemoteControlLauncher のモックを構築する.

    get_repositories は同期メソッド、launch は非同期メソッドの混在のため、
    MagicMock 上に AsyncMock を被せる構成にする。
    """
    from unittest.mock import MagicMock

    launcher = MagicMock()
    launcher.get_repositories.return_value = repositories or {}
    launch_mock = AsyncMock()
    if launch_exception is not None:
        launch_mock.side_effect = launch_exception
    else:
        launch_mock.return_value = launch_result
    launcher.launch = launch_mock
    return launcher


async def test_rc_command_denied_for_unauthorized_user() -> None:
    """認可ユーザー allowlist にない user_id からは権限拒否される."""
    launcher = _make_rc_launcher(repositories={"ai-assistant": "/repo"})
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(_make_msg("rc start ai-assistant", user_id="U_OTHER"))

    assert len(adapter.sent_messages) == 1
    assert "権限がありません" in adapter.sent_messages[0][0]
    launcher.launch.assert_not_called()


async def test_rc_command_unknown_repo_key_returns_usage() -> None:
    """未登録の repo-key を渡すと使用方法 + 登録済みリストが返る."""
    from src.services.remote_control import RemoteControlError

    launcher = _make_rc_launcher(
        repositories={"ai-assistant": "/repo"},
        launch_exception=RemoteControlError(
            "未登録のリポジトリキーです: foo\n登録済み: ai-assistant",
        ),
    )
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(_make_msg("rc start foo", user_id="U_AUTHORIZED"))

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "未登録のリポジトリキー" in text
    assert "ai-assistant" in text
    launcher.launch.assert_awaited_once_with("foo")


async def test_rc_command_missing_repo_key_returns_usage() -> None:
    """rc start のみで repo-key が無い場合、使用方法を返す."""
    launcher = _make_rc_launcher(repositories={"ai-assistant": "/repo"})
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(_make_msg("rc start", user_id="U_AUTHORIZED"))

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "リポジトリキーを指定してください" in text
    assert "ai-assistant" in text
    launcher.launch.assert_not_called()


async def test_rc_command_unknown_subcommand_returns_usage() -> None:
    """rc 直下に start 以外を指定した場合、使用方法を返す."""
    launcher = _make_rc_launcher(repositories={"ai-assistant": "/repo"})
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(_make_msg("rc stop ai-assistant", user_id="U_AUTHORIZED"))

    assert len(adapter.sent_messages) == 1
    assert "使用方法" in adapter.sent_messages[0][0]
    launcher.launch.assert_not_called()


async def test_rc_command_success_returns_url() -> None:
    """正常系: 起動成功時に repo / session / URL を返す."""
    from pathlib import Path

    from src.services.remote_control import RemoteControlLaunchResult

    launcher = _make_rc_launcher(
        repositories={"ai-assistant": "/repo"},
        launch_result=RemoteControlLaunchResult(
            session_name="slack-ai-assistant-1714389600",
            connect_url="https://claude.ai/code?environment=env_TEST",
            log_path=Path(".tmp/remote-control/slack-ai-assistant-1714389600.log"),
        ),
    )
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(
        _make_msg("rc start ai-assistant", user_id="U_AUTHORIZED"),
    )

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "Remote Control を起動しました" in text
    assert "リポジトリ: ai-assistant" in text
    assert "slack-ai-assistant-1714389600" in text
    assert "https://claude.ai/code?environment=env_TEST" in text
    launcher.launch.assert_awaited_once_with("ai-assistant")


async def test_rc_command_disabled_falls_through_to_chat() -> None:
    """remote_control_launcher が None の場合、rc は通常 chat ルーティングに落ちる."""
    chat_service = AsyncMock()
    chat_service.respond.return_value = "通常応答"
    adapter, router = _make_router(
        chat_service=chat_service,
        remote_control_launcher=None,
        remote_control_allowed_users=[],
    )

    await router.process_message(_make_msg("rc start foo", user_id="U_AUTHORIZED"))

    assert len(adapter.sent_messages) == 1
    assert adapter.sent_messages[0][0] == "通常応答"
    chat_service.respond.assert_awaited_once()


async def test_rc_command_url_timeout_reports_log_path() -> None:
    """URL 抽出タイムアウトはログファイルパスを案内する."""
    from pathlib import Path

    from src.services.remote_control import RemoteControlURLTimeoutError

    log_path = Path(".tmp/remote-control/slack-foo-1.log")
    launcher = _make_rc_launcher(
        repositories={"foo": "/repo"},
        launch_exception=RemoteControlURLTimeoutError(
            f"接続 URL の抽出がタイムアウトしました（5秒）。ログファイルを直接確認してください: {log_path}",
        ),
    )
    adapter, router = _make_router(
        remote_control_launcher=launcher,
        remote_control_allowed_users=["U_AUTHORIZED"],
    )

    await router.process_message(_make_msg("rc start foo", user_id="U_AUTHORIZED"))

    assert len(adapter.sent_messages) == 1
    text = adapter.sent_messages[0][0]
    assert "タイムアウト" in text
    assert str(log_path) in text
