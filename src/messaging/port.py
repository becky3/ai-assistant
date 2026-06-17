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


@dataclass
class ArticleCard:
    """フィード配信の記事カードの中立表現.

    各プラットフォームが描画する（Slack=Block Kit / Discord=Embed）。
    summary はプラットフォーム側の文字数制限に応じてアダプターが切り詰める。
    """

    title: str
    url: str
    datetime_str: str
    summary: str
    image_url: str | None = None


@dataclass
class ThreadRef:
    """配信スレッドの不透明ハンドル.

    `thread_key` の意味はプラットフォーム依存（Slack=thread_ts / Discord=スレッド
    channel id）。Core 側はこの値を解釈せず、そのままアダプターに渡し返す。
    """

    channel: str
    thread_key: str


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
    async def post_header(self, channel: str, text: str) -> None:
        """配信の見出しメッセージを投稿する."""

    @abc.abstractmethod
    async def start_feed_thread(self, channel: str, feed_name: str) -> ThreadRef:
        """フィードの親メッセージを投稿しスレッドを開始する.

        Returns:
            以降の記事カード投稿先となるスレッド参照。
        """

    @abc.abstractmethod
    async def post_article_card(self, thread: ThreadRef, card: ArticleCard) -> None:
        """スレッドに記事カードを投稿する（描画はプラットフォーム依存）."""

    @abc.abstractmethod
    async def post_footer(self, channel: str, text: str) -> None:
        """配信のフッターメッセージを投稿する."""

    @abc.abstractmethod
    def get_format_instruction(self) -> str:
        """プラットフォーム固有のフォーマット指示を返す."""

    @abc.abstractmethod
    def get_bot_user_id(self) -> str:
        """ボットのユーザーIDを返す."""
