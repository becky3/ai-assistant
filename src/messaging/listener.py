"""受信側（inbound）の抽象 Port.

仕様: docs/specs/features/cli-adapter.md
"""

from __future__ import annotations

import abc


class MessagingListener(abc.ABC):
    """プラットフォームの受信接続を抽象化する Port.

    接続のライフサイクル管理・bot identity の保持・イベントの正規化と
    dispatch を担う。プラットフォーム固有（Slack Bolt / Discord Gateway 等）の
    実装はサブクラスに閉じる。

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
