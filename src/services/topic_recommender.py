"""学習トピック提案サービス
仕様: docs/specs/f4-topic-recommend.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.db.models import Article, UserProfile
from src.llm.base import LLMProvider, Message

logger = logging.getLogger(__name__)

_TOPIC_SYSTEM_PROMPT = """\
あなたは学習アドバイザーです。ユーザーのプロファイル情報と最近の技術記事を参考に、
次に学ぶべきトピックを3〜5個提案してください。

各トピックには以下を含めてください:
- トピック名（太字）
- なぜこのユーザーにおすすめなのか（スキル・目標との関連性）

Slack向けフォーマットで出力してください（*太字*、番号付きリスト）。
最後に「:speech_balloon: 気になるトピックがあれば、詳しく聞いてね！」を付けてください。"""

_EMPTY_PROFILE_MESSAGE = (
    ":star2: おすすめ学習トピック\n"
    "\n"
    "まだあなたのプロファイル情報がないので、一般的なおすすめをお伝えしますね！\n"
    "\n"
    "1. *Pythonプログラミング入門*\n"
    "   幅広い分野で使える万能言語です。\n"
    "\n"
    "2. *Git/GitHubの基本*\n"
    "   開発の基礎スキルとして必須です。\n"
    "\n"
    "3. *Web開発の基礎*\n"
    "   HTML/CSS/JavaScriptの基本を押さえましょう。\n"
    "\n"
    ":pencil2: 会話を続けるとあなたの興味・スキルを自動で記録します。\n"
    "プロファイルが充実すると、よりパーソナライズされた提案ができるようになります！"
)


class TopicRecommender:
    """学習トピック提案サービス.

    仕様: docs/specs/f4-topic-recommend.md
    """

    def __init__(
        self,
        llm: LLMProvider,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory

    async def recommend(self, user_id: str) -> str:
        """ユーザーに合わせた学習トピックを提案する."""
        profile_info = await self._get_profile(user_id)
        if profile_info is None:
            return _EMPTY_PROFILE_MESSAGE

        articles_info = await self._get_recent_articles()

        user_prompt = self._build_user_prompt(profile_info, articles_info)
        messages = [
            Message(role="system", content=_TOPIC_SYSTEM_PROMPT),
            Message(role="user", content=user_prompt),
        ]

        response = await self._llm.complete(messages)
        return f":star2: あなたへのおすすめ学習トピック\n\n{response.content}"

    async def _get_profile(self, user_id: str) -> dict[str, object] | None:
        """ユーザープロファイルをDBから取得する."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.slack_user_id == user_id)
            )
            profile = result.scalar_one_or_none()

        if profile is None:
            return None

        interests: list[str] = json.loads(profile.interests) if profile.interests else []
        skills: list[dict[str, str]] = json.loads(profile.skills) if profile.skills else []
        goals: list[str] = json.loads(profile.goals) if profile.goals else []

        if not interests and not skills and not goals:
            return None

        return {"interests": interests, "skills": skills, "goals": goals}

    async def _get_recent_articles(self) -> list[dict[str, str]]:
        """直近7日間の記事を取得する."""
        since = datetime.now(timezone.utc) - timedelta(days=7)
        async with self._session_factory() as session:
            result = await session.execute(
                select(Article)
                .where(Article.collected_at >= since)
                .order_by(Article.collected_at.desc())
                .limit(20)
            )
            articles = result.scalars().all()

        return [
            {"title": a.title, "summary": a.summary or ""}
            for a in articles
        ]

    def _build_user_prompt(
        self,
        profile: dict[str, object],
        articles: list[dict[str, str]],
    ) -> str:
        """LLMに渡すユーザープロンプトを組み立てる."""
        raw_interests = profile.get("interests")
        interests: list[str] = raw_interests if isinstance(raw_interests, list) else []
        raw_skills = profile.get("skills")
        skills: list[dict[str, str]] = raw_skills if isinstance(raw_skills, list) else []
        raw_goals = profile.get("goals")
        goals: list[str] = raw_goals if isinstance(raw_goals, list) else []

        parts = ["## ユーザープロファイル"]
        if interests:
            parts.append(f"- 興味: {', '.join(str(i) for i in interests)}")
        else:
            parts.append("- 興味: なし")

        if skills:
            skills_str = ", ".join(
                f"{s.get('name', '')}({s.get('level', '')})" for s in skills
            )
            parts.append(f"- スキル: {skills_str}")
        else:
            parts.append("- スキル: なし")

        if goals:
            parts.append(f"- 目標: {', '.join(str(g) for g in goals)}")
        else:
            parts.append("- 目標: なし")

        if articles:
            parts.append("\n## 最近の技術記事")
            for art in articles:
                title = art["title"]
                summary = art["summary"]
                if summary:
                    parts.append(f"- {title}: {summary}")
                else:
                    parts.append(f"- {title}")
        else:
            parts.append("\n## 最近の技術記事\nなし")

        parts.append("\n上記を踏まえて、このユーザーにおすすめの学習トピックを提案してください。")
        return "\n".join(parts)
