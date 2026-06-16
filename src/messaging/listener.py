"""受信側（inbound）の抽象 Port.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import abc


class MessagingListener(abc.ABC):
    """プラットフォームの受信接続を抽象化する Port.

    抽象 Port が規定するのは接続のライフサイクル（`run`）と bot identity の
    保持・公開（`bot_user_id`）のみ。イベントの正規化（→ IncomingMessage）・
    受信フィルタ・ルーターへの dispatch は各プラットフォーム実装
    （SlackListener 等、Slack Bolt / Discord Gateway 固有部分）に閉じる。

    仕様: docs/specs/features/cli-adapter.md
    """

    @property
    @abc.abstractmethod
    def bot_user_id(self) -> str:
        """解決済みの bot ユーザー ID を返す."""

    @abc.abstractmethod
    async def run(self) -> None:
        """接続しイベントを dispatch する.

        シャットダウンまでブロックする。`asyncio.CancelledError` を受けたら
        graceful に停止する。
        """
