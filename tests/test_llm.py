"""LLM抽象化層のテスト (Issue #4, #75)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.config.settings import DEFAULT_LMSTUDIO_BASE_URL, Settings
from src.llm.base import LLMProvider
from src.llm.factory import create_local_provider, create_online_provider, get_provider_for_service
from src.llm.lmstudio_provider import LMStudioProvider

from .settings_defaults import TEST_SETTINGS_DEFAULTS


def test_llm_provider_abc_has_complete() -> None:
    """LLMProvider ABCに async complete(messages) -> LLMResponse を定義."""
    assert hasattr(LLMProvider, "complete")
    assert hasattr(LLMProvider, "is_available")

    # ABC なので直接インスタンス化できない
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_three_providers_exist() -> None:
    """OpenAI/Anthropic/LM Studio の3プロバイダーが存在する."""
    from src.llm.anthropic_provider import AnthropicProvider
    from src.llm.openai_provider import OpenAIProvider

    assert issubclass(OpenAIProvider, LLMProvider)
    assert issubclass(AnthropicProvider, LLMProvider)
    assert issubclass(LMStudioProvider, LLMProvider)


def test_lmstudio_uses_openai_sdk() -> None:
    """LM StudioはOpenAI SDKでbase_url変更で対応."""
    provider = LMStudioProvider(base_url=DEFAULT_LMSTUDIO_BASE_URL)
    assert provider._client.base_url.host == "localhost"
    # base_url にホストのみ指定しても /v1 がコード側で付加される
    assert provider._client.base_url.path == "/v1/"


def test_lmstudio_base_url_with_v1_suffix_no_duplication() -> None:
    """base_url に /v1 が既に含まれている場合、/v1/v1 にならないこと."""
    provider = LMStudioProvider(base_url="http://localhost:1234/v1")
    assert provider._client.base_url.path == "/v1/"


def test_factory_creates_openai_provider() -> None:
    """ファクトリで設定値からOpenAIプロバイダーを生成できる."""
    settings = Settings(**{**TEST_SETTINGS_DEFAULTS, "online_llm_provider": "openai"})
    with patch("src.llm.factory.get_secret", return_value="sk-test"):
        provider = create_online_provider(settings)
    from src.llm.openai_provider import OpenAIProvider
    assert isinstance(provider, OpenAIProvider)


def test_factory_creates_anthropic_provider() -> None:
    """ファクトリで設定値からAnthropicプロバイダーを生成できる."""
    settings = Settings(**{**TEST_SETTINGS_DEFAULTS, "online_llm_provider": "anthropic"})
    with patch("src.llm.factory.get_secret", return_value="sk-ant-test"):
        provider = create_online_provider(settings)
    from src.llm.anthropic_provider import AnthropicProvider
    assert isinstance(provider, AnthropicProvider)


def test_factory_creates_local_provider() -> None:
    """ファクトリでローカルプロバイダーを生成できる."""
    settings = Settings(**TEST_SETTINGS_DEFAULTS)
    provider = create_local_provider(settings)
    assert isinstance(provider, LMStudioProvider)


def test_get_provider_for_service_returns_local_by_default() -> None:
    """サービスLLM設定が'local'の場合、ローカルプロバイダーを返す."""
    settings = Settings(**TEST_SETTINGS_DEFAULTS)
    provider = get_provider_for_service(settings, "local")
    assert isinstance(provider, LMStudioProvider)


def test_get_provider_for_service_returns_online_when_configured() -> None:
    """サービスLLM設定が'online'の場合、オンラインプロバイダーを返す."""
    settings = Settings(**{**TEST_SETTINGS_DEFAULTS, "online_llm_provider": "openai"})
    with patch("src.llm.factory.get_secret", return_value="sk-test"):
        provider = get_provider_for_service(settings, "online")
    from src.llm.openai_provider import OpenAIProvider
    assert isinstance(provider, OpenAIProvider)


def test_service_llm_settings_default_to_local() -> None:
    """config.toml のデフォルト値で各サービスのLLM設定が'local'."""
    settings = Settings(**TEST_SETTINGS_DEFAULTS)
    assert settings.chat_llm_provider == "local"
    assert settings.summarizer_llm_provider == "local"


def test_service_llm_settings_can_be_configured() -> None:
    """各サービスのLLM設定は変更可能."""
    settings = Settings(**{
        **TEST_SETTINGS_DEFAULTS,
        "chat_llm_provider": "online",
        "summarizer_llm_provider": "online",
    })
    assert settings.chat_llm_provider == "online"
    assert settings.summarizer_llm_provider == "online"


def test_openai_message_role_mapping() -> None:
    """role ごとに正しい ChatCompletionMessageParam 型にマッピングされる."""
    from src.llm.base import Message
    from src.llm.openai_provider import _to_openai_message

    system_msg = _to_openai_message(Message(role="system", content="sys"))
    assert system_msg["role"] == "system"

    user_msg = _to_openai_message(Message(role="user", content="hi"))
    assert user_msg["role"] == "user"

    assistant_msg = _to_openai_message(Message(role="assistant", content="hello"))
    assert assistant_msg["role"] == "assistant"


def test_lmstudio_message_role_mapping() -> None:
    """LMStudio provider でも role が正しくマッピングされる."""
    from src.llm.base import Message
    from src.llm.lmstudio_provider import _to_openai_message

    for role in ("system", "user", "assistant"):
        msg = _to_openai_message(Message(role=role, content="test"))  # type: ignore[arg-type]
        assert msg["role"] == role


# --- MCP統合: ツール呼び出し対応テスト ---


def test_complete_with_tools_method_exists_and_tool_definition_is_constructable() -> None:
    """LLMProvider.complete_with_tools() が存在し、ToolDefinition を構築できること."""
    from src.llm.base import ToolDefinition

    assert hasattr(LLMProvider, "complete_with_tools")

    # ToolDefinition が正しく構築できること
    td = ToolDefinition(
        name="sample_tool",
        description="サンプルツール",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "検索クエリ"},
            },
            "required": ["query"],
        },
    )
    assert td.name == "sample_tool"
    assert td.description == "サンプルツール"
    assert "properties" in td.input_schema


def test_openai_converts_tool_definition_and_tool_messages_to_openai_format() -> None:
    """OpenAIProvider が ToolDefinition と tool/assistant メッセージを OpenAI 形式に変換できること."""
    from src.llm.base import Message, ToolCall, ToolDefinition
    from src.llm.openai_provider import _to_openai_message, _tool_def_to_openai

    # ToolDefinition → OpenAI形式変換
    td = ToolDefinition(
        name="sample_tool",
        description="サンプルツール",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    result = _tool_def_to_openai(td)
    assert result["type"] == "function"
    func = result["function"]
    assert func["name"] == "sample_tool"
    assert func["description"] == "サンプルツール"
    assert func["parameters"] == td.input_schema

    # role="tool" メッセージの変換
    tool_msg = Message(role="tool", content="晴れ", tool_call_id="call_123")
    openai_msg = _to_openai_message(tool_msg)
    assert openai_msg["role"] == "tool"
    assert openai_msg["content"] == "晴れ"  # type: ignore[typeddict-item]
    assert openai_msg["tool_call_id"] == "call_123"  # type: ignore[typeddict-item]

    # role="assistant" + tool_calls メッセージの変換
    assistant_msg = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="call_456", name="sample_tool", arguments={"query": "test"})],
    )
    openai_assistant = _to_openai_message(assistant_msg)
    assert openai_assistant["role"] == "assistant"
    assert "tool_calls" in openai_assistant  # type: ignore[operator]


def test_anthropic_converts_tool_definition_and_tool_result_to_anthropic_format() -> None:
    """AnthropicProvider が ToolDefinition と tool_result メッセージを Anthropic 形式に変換できること."""
    from src.llm.base import Message, ToolCall, ToolDefinition
    from src.llm.anthropic_provider import _build_anthropic_messages, _tool_def_to_anthropic

    # ToolDefinition → Anthropic形式変換
    td = ToolDefinition(
        name="sample_tool",
        description="サンプルツール",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    result = _tool_def_to_anthropic(td)
    assert result["name"] == "sample_tool"
    assert result["description"] == "サンプルツール"

    # role="tool" → role="user" + tool_result 変換
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="toolu_01", name="sample_tool", arguments={"query": "test"})],
        ),
        Message(role="tool", content="晴れ 15°C", tool_call_id="toolu_01"),
    ]
    system_prompt, chat_msgs = _build_anthropic_messages(messages)
    assert chat_msgs[0]["role"] == "assistant"
    assert chat_msgs[1]["role"] == "user"
    # tool_result ブロック
    content_blocks = chat_msgs[1]["content"]
    assert isinstance(content_blocks, list)
    assert content_blocks[0]["type"] == "tool_result"
    assert content_blocks[0]["tool_use_id"] == "toolu_01"


@pytest.mark.asyncio
async def test_lmstudio_complete_with_tools_returns_tool_call_response() -> None:
    """LMStudioProvider が Function Calling でツール呼び出し応答を返すこと."""
    import json
    from unittest.mock import AsyncMock, MagicMock

    from src.llm.base import Message, ToolDefinition
    from src.llm.lmstudio_provider import LMStudioProvider

    provider = LMStudioProvider(base_url=DEFAULT_LMSTUDIO_BASE_URL)

    # OpenAI互換APIのモックレスポンス（ツール呼び出しあり）
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_1"
    mock_tool_call.function = MagicMock()
    mock_tool_call.function.name = "sample_tool"
    mock_tool_call.function.arguments = json.dumps({"query": "test"})

    mock_choice = MagicMock()
    mock_choice.message.content = ""
    mock_choice.message.tool_calls = [mock_tool_call]

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.model = "qwen3-30b"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 100
    mock_response.usage.completion_tokens = 20

    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    tools = [
        ToolDefinition(
            name="sample_tool",
            description="サンプルツール",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        ),
    ]
    messages = [Message(role="user", content="テスト質問")]

    result = await provider.complete_with_tools(messages, tools)
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "sample_tool"
    assert result.tool_calls[0].arguments == {"query": "test"}
    assert result.stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_lmstudio_complete_with_tools_returns_text_when_no_tool_call() -> None:
    """LMStudioProvider でツール呼び出しなしの場合、通常のテキスト応答を返すこと."""
    from unittest.mock import AsyncMock, MagicMock

    from src.llm.base import Message, ToolDefinition
    from src.llm.lmstudio_provider import LMStudioProvider

    provider = LMStudioProvider(base_url=DEFAULT_LMSTUDIO_BASE_URL)

    # ツール呼び出しなしのモックレスポンス
    mock_choice = MagicMock()
    mock_choice.message.content = "東京は今日晴れです。"
    mock_choice.message.tool_calls = None

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.model = "qwen3-30b"
    mock_response.usage = MagicMock()
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 10

    provider._client.chat.completions.create = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    tools = [
        ToolDefinition(
            name="sample_tool",
            description="サンプルツール",
            input_schema={"type": "object", "properties": {}},
        ),
    ]
    messages = [Message(role="user", content="こんにちは")]

    result = await provider.complete_with_tools(messages, tools)
    assert result.content == "東京は今日晴れです。"
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"
