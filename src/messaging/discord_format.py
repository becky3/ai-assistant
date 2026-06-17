"""Slack mrkdwn → Discord Markdown 変換.

仕様: docs/specs/features/cli-adapter.md

Core / LLM / bot 内部文字列は canonical な Slack mrkdwn で出力する（仕様:
cli-adapter.md の「canonical な Slack mrkdwn に統一し、Discord Markdown 変換は
各送信アダプター内に閉じる」制約）。Discord 送信時に本モジュールで Discord
Markdown へ変換する（整形差分のアダプター内局所化）。コードスパン（インライン /
フェンス）は保護し、その外側のみ変換する。

Note: slack-formatting.md の「後処理変換方式は採用しない」は LLM 出力方向
（Markdown → mrkdwn）の話であり、本モジュールの送信前変換（mrkdwn → Discord
Markdown）は別レイヤーの責務。
"""

from __future__ import annotations

import re

# アプリが実際に使用する既知の絵文字ショートコードのみを unicode に変換する
_EMOJI_MAP = {
    ":bulb:": "💡",
    ":newspaper:": "📰",
    ":file_folder:": "📁",
    ":books:": "📚",
    ":robot_face:": "🤖",
}

# Slack リンク <url|text> / <url>
_LINK_LABELED = re.compile(r"<(https?://[^|>]+)\|([^>]+)>")
_LINK_BARE = re.compile(r"<(https?://[^>]+)>")
# Slack 太字 *bold*（** ではない単一アスタリスク）
_BOLD = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
# Slack 取り消し線 ~strike~（~~ ではない単一チルダ）
_STRIKE = re.compile(r"(?<!~)~([^~\n]+)~(?!~)")
# コードスパン（フェンス ```...``` / インライン `...`）— 保護対象
_CODE_SPLIT = re.compile(r"(```.*?```|`[^`\n]+`)", re.DOTALL)


def _convert_segment(text: str) -> str:
    """コードスパン外のセグメントを Discord Markdown に変換する."""
    text = _LINK_LABELED.sub(r"\2 (\1)", text)
    text = _LINK_BARE.sub(r"\1", text)
    text = _BOLD.sub(r"**\1**", text)
    text = _STRIKE.sub(r"~~\1~~", text)
    for shortcode, emoji in _EMOJI_MAP.items():
        text = text.replace(shortcode, emoji)
    return text


def to_discord_markdown(text: str) -> str:
    """Slack mrkdwn を Discord Markdown へ変換する（コードスパンは保護）."""
    if not text:
        return text
    parts = _CODE_SPLIT.split(text)
    return "".join(
        part if part.startswith("`") else _convert_segment(part) for part in parts
    )
