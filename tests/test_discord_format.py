"""Slack mrkdwn → Discord Markdown 変換のテスト (Issue #850)."""

from __future__ import annotations

from src.messaging.discord_format import to_discord_markdown


def test_empty() -> None:
    assert to_discord_markdown("") == ""


def test_bold() -> None:
    assert to_discord_markdown("*有効なフィード*") == "**有効なフィード**"


def test_strike() -> None:
    assert to_discord_markdown("~old~") == "~~old~~"


def test_labeled_link() -> None:
    assert (
        to_discord_markdown("詳細は <https://example.com|こちら>")
        == "詳細は こちら (https://example.com)"
    )


def test_bare_link() -> None:
    assert to_discord_markdown("<https://example.com>") == "https://example.com"


def test_emoji_shortcodes() -> None:
    assert to_discord_markdown(":bulb: ヒント") == "💡 ヒント"
    assert to_discord_markdown(":newspaper: ニュース") == "📰 ニュース"


def test_code_span_protected() -> None:
    # コードスパン内の *...* は変換しない
    assert to_discord_markdown("`*not bold*`") == "`*not bold*`"
    assert to_discord_markdown("```\n*x*\n```") == "```\n*x*\n```"


def test_mixed_outside_and_code() -> None:
    result = to_discord_markdown("*bold* と `*code*`")
    assert result == "**bold** と `*code*`"


def test_italic_unchanged() -> None:
    assert to_discord_markdown("_italic_") == "_italic_"
