"""テスト用設定デフォルト値."""

from __future__ import annotations

# Settings の全必須フィールドのテスト用デフォルト値。
# config.toml / .env のフィールドにデフォルト値がないため、テストで Settings を
# 直接生成する際にこの辞書を使用する。
# Optional (デフォルトあり) フィールドは含まない。
# 注意: 本番 config.toml の値とは意図的に異なる場合がある（テスト用に安全な値を使用）。
TEST_SETTINGS_DEFAULTS: dict[str, object] = {
    # .env フィールド
    "slack_news_channel_id": "",
    "slack_auto_reply_channels": "",
    "lmstudio_base_url": "http://localhost:1234",
    "database_url": "sqlite+aiosqlite:///./test.db",
    "env_name": "",
    "mcp_enabled": False,
    "mcp_rag_transport": "http",
    "mcp_rag_url": "",
    "log_level": "INFO",
    "debug_log_enabled": False,
    "log_dir": "",
    "rag_bluesky_handle": "",
    "rag_zenn_username": "",
    "online_llm_provider": "openai",
    "chat_llm_provider": "local",
    "summarizer_llm_provider": "local",
    "remote_control_allowed_users": "",
    "remote_control_repositories": "",
    "remote_control_log_dir": "",
    # config.toml フィールド
    "openai_model": "gpt-4o-mini",
    "anthropic_model": "claude-3-5-sonnet-20241022",
    "lmstudio_model": "local-model",
    "timezone": "Asia/Tokyo",
    "feed_articles_per_feed": 10,
    "feed_card_layout": "horizontal",
    "feed_summarize_timeout": 180,
    "feed_collect_days": 7,
    "thread_history_limit": 20,
    "rag_show_sources": False,
    "rag_bluesky_max_posts": 100,
    "rag_zenn_max_articles": 10,
    "feed_summarize_reasoning_effort": "none",
    "claude_allowed_tools": "",
    "claude_timeout": 120,
    "log_file_max_bytes": 10485760,
    "remote_control_url_timeout": 15,
}
