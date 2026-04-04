"""チャット統合テスト: ツール呼び出し対応.

仕様: docs/specs/infrastructure/mcp-integration.md
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base
from src.llm.base import LLMProvider, LLMResponse, ToolCall, ToolDefinition
from src.services.chat import TOOL_LOOP_MAX_ITERATIONS, ChatService, RagSource


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    """テスト用インメモリDBセッションファクトリ."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    return factory


def _make_mock_llm(
    text_response: str = "テスト応答",
    tool_calls: list[ToolCall] | None = None,
) -> AsyncMock:
    """モックLLMプロバイダーを作成する."""
    mock_llm = AsyncMock(spec=LLMProvider)

    # complete() はテキスト応答のみ
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(content=text_response, model="test-model")
    )

    # complete_with_tools() はツール呼び出し or テキスト応答
    if tool_calls:
        # 1回目: ツール呼び出し、2回目: テキスト応答
        mock_llm.complete_with_tools = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="",
                    model="test-model",
                    tool_calls=tool_calls,
                    stop_reason="tool_use",
                ),
                LLMResponse(
                    content=text_response,
                    model="test-model",
                    tool_calls=[],
                    stop_reason="end_turn",
                ),
            ]
        )
    else:
        mock_llm.complete_with_tools = AsyncMock(
            return_value=LLMResponse(
                content=text_response,
                model="test-model",
                tool_calls=[],
                stop_reason="end_turn",
            )
        )

    return mock_llm


def _make_mock_mcp_manager(
    tools: list[ToolDefinition] | None = None,
    call_result: str = "Sample result",
) -> AsyncMock:
    """モックMCPClientManagerを作成する."""
    mock_manager = AsyncMock()

    if tools is None:
        tools = [
            ToolDefinition(
                name="sample_tool",
                description="サンプルツール",
                input_schema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            )
        ]

    mock_manager.get_available_tools = AsyncMock(return_value=tools)
    mock_manager.call_tool = AsyncMock(return_value=call_result)
    # get_system_instructions / get_response_instruction は同期メソッドなので MagicMock を使用する
    # AsyncMock のままだと呼び出し時にコルーチンが生成されるが await されず
    # RuntimeWarning: coroutine was never awaited が発生する
    mock_manager.get_system_instructions = MagicMock(return_value=[])
    mock_manager.get_auto_context_tools = MagicMock(return_value=[])
    mock_manager.get_response_instruction = MagicMock(return_value="")
    return mock_manager


@pytest.mark.asyncio
async def test_chat_responds_with_tool_data(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ユーザーが質問すると、LLMがツールを呼び出して実データで回答すること."""
    tool_calls = [
        ToolCall(id="call_1", name="sample_tool", arguments={"query": "test"}),
    ]
    mock_llm = _make_mock_llm(
        text_response="ツールの結果に基づく応答です。",
        tool_calls=tool_calls,
    )
    mock_mcp = _make_mock_mcp_manager(call_result="Sample tool result data")

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    result = await service.respond("U001", "テスト質問", "ts_001")

    assert result == "ツールの結果に基づく応答です。"
    # complete_with_tools が呼ばれること
    assert mock_llm.complete_with_tools.call_count == 2
    # MCPツールが呼び出されること
    mock_mcp.call_tool.assert_called_once_with("sample_tool", {"query": "test"})


@pytest.mark.asyncio
async def test_chat_backward_compatible(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツール呼び出しが不要な通常の質問は、従来通り応答すること（後方互換性）."""
    mock_llm = _make_mock_llm(text_response="こんにちは！")

    # MCPManager なし → 従来通り complete() を使用
    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
    )

    result = await service.respond("U001", "こんにちは", "ts_002")

    assert result == "こんにちは！"
    mock_llm.complete.assert_called_once()
    mock_llm.complete_with_tools.assert_not_called()


@pytest.mark.asyncio
async def test_tool_error_handled_gracefully(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツール実行中にエラーが発生した場合、エラー内容をLLMに伝え、適切な応答を生成すること."""
    tool_calls = [
        ToolCall(id="call_1", name="sample_tool", arguments={"query": "invalid"}),
    ]
    mock_llm = _make_mock_llm(
        text_response="申し訳ありませんが、情報を取得できませんでした。",
        tool_calls=tool_calls,
    )
    mock_mcp = _make_mock_mcp_manager()
    # ツール実行時にエラーを発生させる
    mock_mcp.call_tool = AsyncMock(side_effect=Exception("API connection error"))

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    result = await service.respond("U001", "テスト質問", "ts_003")

    # エラーでもクラッシュせず応答が返ること
    assert result == "申し訳ありませんが、情報を取得できませんでした。"


@pytest.mark.asyncio
async def test_mcp_disabled_mode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """MCP無効時（mcp_manager=None）は従来通りの動作をすること."""
    mock_llm = _make_mock_llm(text_response="通常応答です。")

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=None,  # MCP無効
    )

    result = await service.respond("U001", "テスト", "ts_004")

    assert result == "通常応答です。"
    mock_llm.complete.assert_called_once()


def testbuild_mcp_server_configs_with_url() -> None:
    """MCP_RAG_URL が設定されている場合、RAG サーバー設定が構築される."""
    from src.config.settings import Settings
    from src.mcp_bridge.client_manager import build_mcp_server_configs

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    settings = Settings(**{
        **TEST_SETTINGS_DEFAULTS,
        "mcp_rag_transport": "http",
        "mcp_rag_url": "http://192.168.11.2:8081/mcp",
    })
    assistant_config: dict[str, object] = {
        "mcp_system_instruction": "検索してください",
        "mcp_response_instruction": "結果を使って回答",
    }

    configs = build_mcp_server_configs(settings, assistant_config)
    assert len(configs) == 1
    assert configs[0].name == "rag"
    assert configs[0].transport == "http"
    assert configs[0].url == "http://192.168.11.2:8081/mcp"
    assert configs[0].system_instruction == "検索してください"
    assert configs[0].response_instruction == "結果を使って回答"


def testbuild_mcp_server_configs_without_url() -> None:
    """MCP_RAG_URL が未設定の場合、空リストを返す."""
    from src.config.settings import Settings
    from src.mcp_bridge.client_manager import build_mcp_server_configs

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    settings = Settings(**{
        **TEST_SETTINGS_DEFAULTS,
        "mcp_rag_url": "",
    })

    configs = build_mcp_server_configs(settings, {})
    assert configs == []


def test_mcp_enabled_env_control() -> None:
    """MCP_ENABLED 設定でMCP機能のON/OFFを制御できること."""
    from src.config.settings import Settings

    from .settings_defaults import TEST_SETTINGS_DEFAULTS

    # デフォルト: 無効
    settings = Settings(**TEST_SETTINGS_DEFAULTS)
    assert settings.mcp_enabled is False

    # 有効化
    settings = Settings(**{**TEST_SETTINGS_DEFAULTS, "mcp_enabled": True})
    assert settings.mcp_enabled is True

    # 無効化
    settings = Settings(**{**TEST_SETTINGS_DEFAULTS, "mcp_enabled": False})
    assert settings.mcp_enabled is False


@pytest.mark.asyncio
async def test_tool_loop_max_iterations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツール呼び出しが最大反復回数に達した場合、ループを打ち切りテキスト応答を返すこと."""
    # 常にツール呼び出しを返すLLM（終わらないループ）
    always_tool_response = LLMResponse(
        content="",
        model="test-model",
        tool_calls=[ToolCall(id="call_x", name="sample_tool", arguments={"query": "test"})],
        stop_reason="tool_use",
    )

    mock_llm = AsyncMock(spec=LLMProvider)
    mock_llm.complete_with_tools = AsyncMock(return_value=always_tool_response)
    # 最大反復到達後の強制テキスト応答
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(content="上限に達しました。現在の情報でお答えします。", model="test-model")
    )

    mock_mcp = _make_mock_mcp_manager()

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    result = await service.respond("U001", "テスト質問", "ts_005")

    # 最大反復回数分 complete_with_tools が呼ばれること
    assert mock_llm.complete_with_tools.call_count == TOOL_LOOP_MAX_ITERATIONS
    # 最後に complete() が呼ばれて強制テキスト応答
    mock_llm.complete.assert_called_once()
    assert "上限に達しました" in result


@pytest.mark.asyncio
async def test_chat_with_tools_saves_only_final_response(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツール呼び出しの中間ステップはDBに保存されず、最終応答のみ保存されること."""
    from sqlalchemy import select

    from src.db.models import Conversation

    tool_calls = [
        ToolCall(id="call_1", name="sample_tool", arguments={"query": "test"}),
    ]
    mock_llm = _make_mock_llm(
        text_response="ツールの結果に基づく応答です。",
        tool_calls=tool_calls,
    )
    mock_mcp = _make_mock_mcp_manager()

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    await service.respond("U001", "テスト質問", "ts_006")

    # DBに保存されたメッセージを確認
    async with session_factory() as session:
        result = await session.execute(
            select(Conversation)
            .where(Conversation.thread_ts == "ts_006")
            .order_by(Conversation.created_at)
        )
        rows = result.scalars().all()

    # user + assistant の2件のみ（tool 中間ステップは含まない）
    assert len(rows) == 2
    assert rows[0].role == "user"
    assert rows[0].content == "テスト質問"
    assert rows[1].role == "assistant"
    assert rows[1].content == "ツールの結果に基づく応答です。"


@pytest.mark.asyncio
async def test_chat_no_tools_available(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """MCPManagerが接続済みだがツールが0個の場合、従来のcomplete()にフォールバックすること."""
    mock_llm = _make_mock_llm(text_response="ツールなし応答")
    mock_mcp = _make_mock_mcp_manager(tools=[])

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    result = await service.respond("U001", "テスト", "ts_007")

    assert result == "ツールなし応答"
    mock_llm.complete.assert_called_once()


class TestExtractRagSourcesFromMessages:
    """_extract_rag_sources_from_messages() のテスト（準Agentic Search, Issue #548）."""

    def test_extracts_source_urls_from_tool_messages(self) -> None:
        """ツールメッセージから検索エンジン種別・スコア・URLを抽出すること."""
        from src.llm.base import Message

        messages = [
            Message(role="user", content="テスト"),
            Message(role="assistant", content=""),
            Message(
                role="tool",
                content=(
                    "## ベクトル検索結果 (意味的類似度)\n\n"
                    "### Result 1 [distance=0.234]\n"
                    "Source: https://example.com/page1\n"
                    "テキスト内容1\n\n"
                    "### Result 2 [distance=0.567]\n"
                    "Source: https://example.com/page2\n"
                    "テキスト内容2\n\n"
                    "## BM25検索結果 (キーワード一致)\n\n"
                    "### Result 1 [score=4.521]\n"
                    "Source: https://example.com/page1\n"
                    "テキスト内容3"
                ),
                tool_call_id="call_1",
            ),
        ]

        sources = ChatService._extract_rag_sources_from_messages(messages)

        assert sources == [
            RagSource(url="https://example.com/page1", engine="vector", score=0.234),
            RagSource(url="https://example.com/page2", engine="vector", score=0.567),
            RagSource(url="https://example.com/page1", engine="bm25", score=4.521),
        ]

    def test_returns_empty_when_no_tool_messages(self) -> None:
        """ツールメッセージがない場合は空リストを返すこと."""
        from src.llm.base import Message

        messages = [
            Message(role="user", content="こんにちは"),
            Message(role="assistant", content="こんにちは！"),
        ]

        sources = ChatService._extract_rag_sources_from_messages(messages)
        assert sources == []

    def test_returns_empty_when_no_source_in_tool_message(self) -> None:
        """ツールメッセージに Source: がない場合は空リストを返すこと."""
        from src.llm.base import Message

        messages = [
            Message(
                role="tool",
                content="東京: 晴れ 最高15°C",
                tool_call_id="call_1",
            ),
        ]

        sources = ChatService._extract_rag_sources_from_messages(messages)
        assert sources == []

    def test_deduplicates_same_engine_source_urls(self) -> None:
        """同一エンジン・同一URLの重複は1つにまとめること."""
        from src.llm.base import Message

        messages = [
            Message(
                role="tool",
                content=(
                    "### Result 1 [distance=0.1]\n"
                    "Source: https://example.com/same\n"
                    "テキスト1\n\n"
                    "### Result 2 [distance=0.2]\n"
                    "Source: https://example.com/same\n"
                    "テキスト2"
                ),
                tool_call_id="call_1",
            ),
        ]

        sources = ChatService._extract_rag_sources_from_messages(messages)
        assert sources == [
            RagSource(url="https://example.com/same", engine="vector", score=0.1),
        ]

    def test_extracts_source_urls_with_hash_prefix(self) -> None:
        """'## Source: ' プレフィックスも処理できること."""
        from src.llm.base import Message

        messages = [
            Message(
                role="tool",
                content=(
                    "### Result 1 [distance=0.123]\n"
                    "## Source: https://example.com/page\n"
                    "テキスト内容"
                ),
                tool_call_id="call_1",
            ),
        ]

        sources = ChatService._extract_rag_sources_from_messages(messages)
        assert sources == [
            RagSource(url="https://example.com/page", engine="vector", score=0.123),
        ]


@pytest.mark.asyncio
async def test_rag_sources_from_tool_loop(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツールループで rag_search が呼ばれた場合、ソースURLが抽出されること."""
    tool_calls = [
        ToolCall(id="call_1", name="rag_search", arguments={"query": "テスト"}),
    ]
    mock_llm = _make_mock_llm(
        text_response="ナレッジベースによると...",
        tool_calls=tool_calls,
    )
    mock_mcp = _make_mock_mcp_manager(
        tools=[
            ToolDefinition(
                name="rag_search",
                description="ナレッジベース検索",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
        call_result=(
            "## ベクトル検索結果 (意味的類似度)\n\n"
            "### Result 1 [distance=0.234]\n"
            "Source: https://example.com/page1\n"
            "関連テキスト"
        ),
    )
    # rag_show_sources を有効にする
    from unittest.mock import patch

    mock_settings = MagicMock()
    mock_settings.rag_show_sources = True

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    with patch("src.services.chat.get_settings", return_value=mock_settings):
        result = await service.respond("U001", "テスト質問", "ts_rag_001")

    assert "参照元:" in result
    assert "[vector: distance=0.234]" in result
    assert "https://example.com/page1" in result


@pytest.mark.asyncio
async def test_rag_sources_bm25_format_in_output(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """ツールループで bm25 結果を含む場合、参照元に [bm25: score=X.XXX] が表示されること."""
    tool_calls = [
        ToolCall(id="call_1", name="rag_search", arguments={"query": "テスト"}),
    ]
    mock_llm = _make_mock_llm(
        text_response="ナレッジベースによると...",
        tool_calls=tool_calls,
    )
    mock_mcp = _make_mock_mcp_manager(
        tools=[
            ToolDefinition(
                name="rag_search",
                description="ナレッジベース検索",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            )
        ],
        call_result=(
            "## ベクトル検索結果 (意味的類似度)\n\n"
            "### Result 1 [distance=0.234]\n"
            "Source: https://example.com/page1\n"
            "関連テキスト\n\n"
            "## BM25検索結果 (キーワード一致)\n\n"
            "### Result 1 [score=4.521]\n"
            "Source: https://example.com/page2\n"
            "BM25テキスト"
        ),
    )
    from unittest.mock import patch

    mock_settings = MagicMock()
    mock_settings.rag_show_sources = True

    service = ChatService(
        llm=mock_llm,
        session_factory=session_factory,
        mcp_manager=mock_mcp,
    )

    with patch("src.services.chat.get_settings", return_value=mock_settings):
        result = await service.respond("U001", "テスト質問", "ts_rag_002")

    assert "参照元:" in result
    assert "[vector: distance=0.234]" in result
    assert "[bm25: score=4.521]" in result
    assert "https://example.com/page1" in result
    assert "https://example.com/page2" in result
