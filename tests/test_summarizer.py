"""Summarizer要約プロンプトのテスト (Issue #102)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.llm.base import LLMProvider, LLMResponse
from src.services.summarizer import SUMMARIZE_PROMPT, Summarizer


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock(spec=LLMProvider)


async def test_prompt_contains_title_inference_instruction() -> None:
    """プロンプトに概要なし時のタイトル推測指示が含まれる."""
    assert "タイトルから内容を推測して要約" in SUMMARIZE_PROMPT


async def test_prompt_prohibits_cannot_understand_response() -> None:
    """プロンプトに「把握できません」系の回答禁止が含まれる."""
    assert "内容を把握できません" in SUMMARIZE_PROMPT
    assert "禁止" in SUMMARIZE_PROMPT


async def test_prompt_no_inference_when_description_exists() -> None:
    """プロンプトに概要がある場合は推測しない指示が含まれる."""
    assert "概要がある場合は" in SUMMARIZE_PROMPT
    assert "推測は入れないでください" in SUMMARIZE_PROMPT


async def test_summarize_with_no_description(mock_llm: AsyncMock) -> None:
    """概要なしの場合、descriptionが「なし」としてプロンプトに渡される."""
    mock_llm.complete.return_value = LLMResponse(content="タイトルから推測した要約")
    summarizer = Summarizer(llm=mock_llm)

    result = await summarizer.summarize("Python 3.13の新機能", "https://example.com/article")

    assert result == "タイトルから推測した要約"
    # LLMに渡されたプロンプトにdescription=なしが含まれる
    call_args = mock_llm.complete.call_args[0][0]
    prompt_content = call_args[0].content
    assert "概要: なし" in prompt_content
    assert "タイトル: Python 3.13の新機能" in prompt_content


async def test_summarize_with_description(mock_llm: AsyncMock) -> None:
    """概要ありの場合、descriptionがそのままプロンプトに渡される."""
    mock_llm.complete.return_value = LLMResponse(content="概要に基づく要約")
    summarizer = Summarizer(llm=mock_llm)

    result = await summarizer.summarize(
        "Python 3.13の新機能",
        "https://example.com/article",
        "Python 3.13ではasyncioにTaskGroupが追加されました。",
    )

    assert result == "概要に基づく要約"
    call_args = mock_llm.complete.call_args[0][0]
    prompt_content = call_args[0].content
    assert "概要: Python 3.13ではasyncioにTaskGroupが追加されました。" in prompt_content


async def test_summarize_empty_description_treated_as_none(mock_llm: AsyncMock) -> None:
    """空文字列の概要は「なし」として扱われる."""
    mock_llm.complete.return_value = LLMResponse(content="推測された要約")
    summarizer = Summarizer(llm=mock_llm)

    await summarizer.summarize("記事タイトル", "https://example.com/article", "")

    call_args = mock_llm.complete.call_args[0][0]
    prompt_content = call_args[0].content
    assert "概要: なし" in prompt_content


async def test_summarize_fallback_to_title_on_empty_response(mock_llm: AsyncMock) -> None:
    """LLMが空の応答を返した場合、タイトルをフォールバックとして返す."""
    mock_llm.complete.return_value = LLMResponse(content="")
    summarizer = Summarizer(llm=mock_llm)

    result = await summarizer.summarize("フォールバックテスト", "https://example.com/article")

    assert result == "フォールバックテスト"


async def test_summarize_fallback_to_title_on_exception(mock_llm: AsyncMock) -> None:
    """LLM呼び出しが例外を投げた場合、タイトルをフォールバックとして返す."""
    mock_llm.complete.side_effect = RuntimeError("LLM error")
    summarizer = Summarizer(llm=mock_llm)

    result = await summarizer.summarize("エラーテスト", "https://example.com/article")

    assert result == "エラーテスト"
