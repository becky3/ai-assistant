"""MessagingPort ABC と IncomingMessage データクラス.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from src.llm.base import Message


@dataclass
class IncomingFile:
    """プラットフォーム非依存の受信ファイル参照.

    各プラットフォーム（Slack の file dict、Discord の attachment 等）を
    中立表現に正規化したもの。実体の取得は `MessagingPort.read_file` が担う。
    """

    name: str
    mimetype: str
    download_url: str
    size: int | None = None


@dataclass
class IncomingMessage:
    """プラットフォーム非依存の受信メッセージ."""

    user_id: str
    text: str
    thread_id: str
    channel: str
    is_in_thread: bool
    message_id: str
    files: list[IncomingFile] | None = field(default=None)


class MessagingPort(abc.ABC):
    """メッセージ送受信の抽象インターフェース.

    仕様: docs/specs/features/cli-adapter.md
    """

    @abc.abstractmethod
    async def send_message(self, text: str, thread_id: str, channel: str) -> None:
        """テキストメッセージを送信する."""

    @abc.abstractmethod
    async def upload_file(
        self,
        content: str,
        filename: str,
        thread_id: str,
        channel: str,
        comment: str,
    ) -> None:
        """ファイルをアップロードする."""

    @abc.abstractmethod
    async def fetch_thread_history(
        self, channel: str, thread_id: str, current_message_id: str
    ) -> list[Message] | None:
        """スレッド/セッション履歴を取得する.

        Returns:
            Message のリスト。取得不可の場合は None（DBフォールバック）。
        """

    @abc.abstractmethod
    async def read_file(self, file: IncomingFile) -> bytes:
        """受信ファイルの実体（バイト列）を取得する.

        プラットフォーム固有の認証・ダウンロード手段はアダプター内に閉じる
        （Slack=token 付き DL / Discord=attachment URL / CLI=ローカル読込）。
        """

    @abc.abstractmethod
    def get_format_instruction(self) -> str:
        """プラットフォーム固有のフォーマット指示を返す."""

    @abc.abstractmethod
    def get_bot_user_id(self) -> str:
        """ボットのユーザーIDを返す."""
