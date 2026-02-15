"""OGP画像URL抽出のテスト (AC10)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.ogp_extractor import OgpExtractor


async def test_ac10_extract_from_html_og_image() -> None:
    """AC10: HTMLのog:imageメタタグからURLを取得できる."""
    html = """
    <html><head>
    <meta property="og:image" content="https://example.com/img.png">
    </head><body></body></html>
    """
    extractor = OgpExtractor()

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=html)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.ogp_extractor.aiohttp.ClientSession", return_value=mock_session):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result == "https://example.com/img.png"


async def test_ac10_extract_from_html_og_image_reversed_attrs() -> None:
    """AC10: content属性がproperty属性の前にあるケースでも取得できる."""
    html = '<html><head><meta content="https://img.com/a.jpg" property="og:image"></head></html>'
    extractor = OgpExtractor()

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value=html)
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.ogp_extractor.aiohttp.ClientSession", return_value=mock_session):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result == "https://img.com/a.jpg"


async def test_ac10_extract_from_rss_media_content() -> None:
    """AC10: RSSエントリのmedia_contentから画像URLを取得できる."""
    extractor = OgpExtractor()
    entry = {
        "media_content": [{"url": "https://example.com/media.jpg", "type": "image/jpeg"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://example.com/media.jpg"


async def test_ac10_extract_from_rss_enclosure() -> None:
    """AC10: RSSエントリのenclosureから画像URLを取得できる."""
    extractor = OgpExtractor()
    entry = {
        "enclosures": [{"href": "https://example.com/enc.png", "type": "image/png"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://example.com/enc.png"


async def test_ac10_extract_from_media_thumbnail() -> None:
    """AC10: RSSエントリのmedia_thumbnailから画像URLを取得できる (Reddit等)."""
    extractor = OgpExtractor()
    entry = {
        "media_thumbnail": [{"url": "https://reddit.com/thumb.jpg"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://reddit.com/thumb.jpg"


async def test_ac10_extract_from_summary_img_tag() -> None:
    """AC10: RSSエントリのsummary内のimgタグから画像URLを取得できる (Medium等)."""
    extractor = OgpExtractor()
    entry = {
        "summary": '<p>Text</p><img src="https://cdn-images-1.medium.com/max/2600/img.jpg" />',
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://cdn-images-1.medium.com/max/2600/img.jpg"


async def test_ac10_returns_none_on_failure() -> None:
    """AC10: 取得失敗時はNoneを返す."""
    extractor = OgpExtractor()

    with patch("src.services.ogp_extractor.aiohttp.ClientSession", side_effect=Exception("timeout")):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result is None


async def test_ac10_returns_none_on_non_200() -> None:
    """AC10: HTTP 200以外の場合はNoneを返す."""
    extractor = OgpExtractor()

    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("src.services.ogp_extractor.aiohttp.ClientSession", return_value=mock_session):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result is None


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
async def test_ac10_returns_none_on_redirect(
    status_code: int, caplog: pytest.LogCaptureFixture
) -> None:
    """AC10: リダイレクト応答時はSSRF対策としてNoneを返しwarningログを出す."""
    extractor = OgpExtractor()

    mock_resp = AsyncMock()
    mock_resp.status = status_code
    mock_resp.headers = {"Location": "http://internal-server/secret"}
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.get = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch(
            "src.services.ogp_extractor.aiohttp.ClientSession",
            return_value=mock_session,
        ),
        caplog.at_level(logging.WARNING),
    ):
        result = await extractor.extract_image_url(
            "https://example.com/article"
        )

    assert result is None
    assert "Redirect detected (SSRF protection)" in caplog.text
