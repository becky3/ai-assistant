"""LLM抽象化層のテスト (Issue #4, #75)."""

from __future__ import annotations

import pytest

from src.config.settings import Settings
from src.llm.base import LLMProvider, LLMResponse
from src.llm.factory import create_local_provider, create_online_provider, get_provider_for_service
from src.llm.lmstudio_provider import LMStudioProvider


def test_ac1_llm_provider_abc_has_complete() -> None:
    """AC1: LLMProvider ABCに async complete(messages) -> LLMResponse を定義."""
    assert hasattr(LLMProvider, "complete")
    assert hasattr(LLMProvider, "is_available")

    # ABC なので直接インスタンス化できない
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]


def test_ac2_three_providers_exist() -> None:
    """AC2: OpenAI/Anthropic/LM Studio の3プロバイダーが存在する."""
    from src.llm.anthropic_provider import AnthropicProvider
    from src.llm.openai_provider import OpenAIProvider

    assert issubclass(OpenAIProvider, LLMProvider)
    assert issubclass(AnthropicProvider, LLMProvider)
    assert issubclass(LMStudioProvider, LLMProvider)


def test_ac3_lmstudio_uses_openai_sdk() -> None:
    """AC3: LM StudioはOpenAI SDKでbase_url変更で対応."""
    provider = LMStudioProvider(base_url="http://localhost:1234/v1")
    assert provider._client.base_url.host == "localhost"


def test_ac4_factory_creates_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: ファクトリで設定値からOpenAIプロバイダーを生成できる."""
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings()
    provider = create_online_provider(settings)
    from src.llm.openai_provider import OpenAIProvider
    assert isinstance(provider, OpenAIProvider)


def test_ac4_factory_creates_anthropic_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: ファクトリで設定値からAnthropicプロバイダーを生成できる."""
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    settings = Settings()
    provider = create_online_provider(settings)
    from src.llm.anthropic_provider import AnthropicProvider
    assert isinstance(provider, AnthropicProvider)


def test_ac4_factory_creates_local_provider() -> None:
    """AC4: ファクトリでローカルプロバイダーを生成できる."""
    settings = Settings()
    provider = create_local_provider(settings)
    assert isinstance(provider, LMStudioProvider)


def test_get_provider_for_service_returns_local_by_default() -> None:
    """サービスLLM設定が'local'の場合、ローカルプロバイダーを返す."""
    settings = Settings()
    provider = get_provider_for_service(settings, "local")
    assert isinstance(provider, LMStudioProvider)


def test_get_provider_for_service_returns_online_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """サービスLLM設定が'online'の場合、オンラインプロバイダーを返す."""
    monkeypatch.setenv("ONLINE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = Settings()
    provider = get_provider_for_service(settings, "online")
    from src.llm.openai_provider import OpenAIProvider
    assert isinstance(provider, OpenAIProvider)


def test_service_llm_settings_default_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """各サービスのLLM設定はデフォルトで'local'."""
    # 環境変数をクリア (_env_file=Noneで.envファイルの影響を排除)
    monkeypatch.delenv("CHAT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("PROFILER_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("TOPIC_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("SUMMARIZER_LLM_PROVIDER", raising=False)
    settings = Settings(_env_file=None)
    assert settings.chat_llm_provider == "local"
    assert settings.profiler_llm_provider == "local"
    assert settings.topic_llm_provider == "local"
    assert settings.summarizer_llm_provider == "local"


def test_service_llm_settings_can_be_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """各サービスのLLM設定は環境変数で変更可能."""
    monkeypatch.setenv("CHAT_LLM_PROVIDER", "online")
    monkeypatch.setenv("PROFILER_LLM_PROVIDER", "online")
    monkeypatch.setenv("TOPIC_LLM_PROVIDER", "local")
    monkeypatch.setenv("SUMMARIZER_LLM_PROVIDER", "online")
    settings = Settings()
    assert settings.chat_llm_provider == "online"
    assert settings.profiler_llm_provider == "online"
    assert settings.topic_llm_provider == "local"
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


# --- F5: MCP統合 ツール呼び出し対応テスト (AC8-AC11) ---


def test_ac8_complete_with_tools_passes_tool_definitions() -> None:
    """AC8: LLMProvider.complete_with_tools() が ToolDefinition リストを受け取れること."""
    from src.llm.base import ToolDefinition

    assert hasattr(LLMProvider, "complete_with_tools")

    # ToolDefinition が正しく構築できること
    td = ToolDefinition(
        name="get_weather",
        description="天気予報を取得する",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "地域名"},
            },
            "required": ["location"],
        },
    )
    assert td.name == "get_weather"
    assert td.description == "天気予報を取得する"
    assert "properties" in td.input_schema


def test_ac9_openai_function_calling() -> None:
    """AC9: OpenAIProvider が Function Calling に対応し、ToolDefinition → OpenAI形式の変換ができること."""
    from src.llm.base import Message, ToolCall, ToolDefinition
    from src.llm.openai_provider import _to_openai_message, _tool_def_to_openai

    # ToolDefinition → OpenAI形式変換
    td = ToolDefinition(
        name="get_weather",
        description="天気予報を取得する",
        input_schema={"type": "object", "properties": {"location": {"type": "string"}}},
    )
    result = _tool_def_to_openai(td)
    assert result["type"] == "function"
    func = result["function"]
    assert func["name"] == "get_weather"
    assert func["description"] == "天気予報を取得する"
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
        tool_calls=[ToolCall(id="call_456", name="get_weather", arguments={"location": "東京"})],
    )
    openai_assistant = _to_openai_message(assistant_msg)
    assert openai_assistant["role"] == "assistant"
    assert "tool_calls" in openai_assistant  # type: ignore[operator]


def test_ac10_anthropic_tool_use() -> None:
    """AC10: AnthropicProvider が Tool Use に対応し、ToolDefinition → Anthropic形式の変換ができること."""
    from src.llm.base import Message, ToolCall, ToolDefinition
    from src.llm.anthropic_provider import _build_anthropic_messages, _tool_def_to_anthropic

    # ToolDefinition → Anthropic形式変換
    td = ToolDefinition(
        name="get_weather",
        description="天気予報を取得する",
        input_schema={"type": "object", "properties": {"location": {"type": "string"}}},
    )
    result = _tool_def_to_anthropic(td)
    assert result["name"] == "get_weather"
    assert result["description"] == "天気予報を取得する"

    # role="tool" → role="user" + tool_result 変換
    messages = [
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="toolu_01", name="get_weather", arguments={"location": "東京"})],
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
async def test_ac11_lmstudio_fallback_to_complete() -> None:
    """AC11: ツール非対応のプロバイダー（LMStudio等）は complete_with_tools() が従来の complete() にフォールバックすること."""
    from unittest.mock import AsyncMock

    from src.llm.base import Message, ToolDefinition
    from src.llm.lmstudio_provider import LMStudioProvider

    provider = LMStudioProvider(base_url="http://localhost:1234/v1")

    # complete() をモック化
    mock_response = LLMResponse(content="フォールバック応答", model="local-model")
    provider.complete = AsyncMock(return_value=mock_response)  # type: ignore[method-assign]

    tools = [
        ToolDefinition(
            name="get_weather",
            description="天気予報",
            input_schema={"type": "object", "properties": {}},
        ),
    ]
    messages = [Message(role="user", content="東京の天気は？")]

    # complete_with_tools() は complete() にフォールバック
    result = await provider.complete_with_tools(messages, tools)
    assert result.content == "フォールバック応答"
    assert result.tool_calls == []
    provider.complete.assert_called_once_with(messages)  # type: ignore[union-attr]
