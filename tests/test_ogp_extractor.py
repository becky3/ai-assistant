"""OGP画像URL抽出のテスト."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.services.ogp_extractor import OgpExtractor


def _mock_constrained_client(resp: httpx.Response) -> AsyncMock:
    """ConstrainedClient の async context manager モックを生成する."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_response(status_code: int, text: str = "", headers: dict[str, str] | None = None) -> httpx.Response:
    """テスト用の httpx.Response を生成する."""
    resp = httpx.Response(
        status_code=status_code,
        text=text,
        headers=headers or {},
        request=httpx.Request("GET", "https://example.com"),
    )
    return resp


async def test_extract_image_url_from_og_image_meta_tag() -> None:
    """HTMLのog:imageメタタグからURLを取得できる."""
    html = """
    <html><head>
    <meta property="og:image" content="https://example.com/img.png">
    </head><body></body></html>
    """
    extractor = OgpExtractor()
    resp = _make_response(200, html)
    mock_client = _mock_constrained_client(resp)

    with patch("src.services.ogp_extractor.ConstrainedClient", return_value=mock_client):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result == "https://example.com/img.png"


async def test_extract_image_url_from_og_image_with_reversed_attributes() -> None:
    """content属性がproperty属性の前にあるケースでも取得できる."""
    html = '<html><head><meta content="https://img.com/a.jpg" property="og:image"></head></html>'
    extractor = OgpExtractor()
    resp = _make_response(200, html)
    mock_client = _mock_constrained_client(resp)

    with patch("src.services.ogp_extractor.ConstrainedClient", return_value=mock_client):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result == "https://img.com/a.jpg"


async def test_extract_image_url_from_rss_media_content() -> None:
    """RSSエントリのmedia_contentから画像URLを取得できる."""
    extractor = OgpExtractor()
    entry = {
        "media_content": [{"url": "https://example.com/media.jpg", "type": "image/jpeg"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://example.com/media.jpg"


async def test_extract_image_url_from_rss_enclosure() -> None:
    """RSSエントリのenclosureから画像URLを取得できる."""
    extractor = OgpExtractor()
    entry = {
        "enclosures": [{"href": "https://example.com/enc.png", "type": "image/png"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://example.com/enc.png"


async def test_extract_image_url_from_rss_media_thumbnail() -> None:
    """RSSエントリのmedia_thumbnailから画像URLを取得できる (Reddit等)."""
    extractor = OgpExtractor()
    entry = {
        "media_thumbnail": [{"url": "https://reddit.com/thumb.jpg"}],
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://reddit.com/thumb.jpg"


async def test_extract_image_url_from_rss_summary_img_tag() -> None:
    """RSSエントリのsummary内のimgタグから画像URLを取得できる (Medium等)."""
    extractor = OgpExtractor()
    entry = {
        "summary": '<p>Text</p><img src="https://cdn-images-1.medium.com/max/2600/img.jpg" />',
    }
    result = await extractor.extract_image_url("https://example.com/article", entry)
    assert result == "https://cdn-images-1.medium.com/max/2600/img.jpg"


async def test_extract_image_url_returns_none_on_exception() -> None:
    """取得失敗時はNoneを返す."""
    extractor = OgpExtractor()

    with patch("src.services.ogp_extractor.ConstrainedClient", side_effect=Exception("timeout")):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result is None


async def test_extract_image_url_returns_none_on_non_200_status() -> None:
    """HTTP 200以外の場合はNoneを返す."""
    extractor = OgpExtractor()
    resp = _make_response(404)
    mock_client = _mock_constrained_client(resp)

    with patch("src.services.ogp_extractor.ConstrainedClient", return_value=mock_client):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result is None


@pytest.mark.parametrize("status_code", [301, 302, 303, 307, 308])
async def test_extract_image_url_returns_none_on_redirect_for_ssrf_protection(
    status_code: int, caplog: pytest.LogCaptureFixture
) -> None:
    """リダイレクト応答時はSSRF対策としてNoneを返しwarningログを出す."""
    extractor = OgpExtractor()
    resp = _make_response(status_code, headers={"location": "http://internal-server/secret"})
    mock_client = _mock_constrained_client(resp)

    with (
        patch("src.services.ogp_extractor.ConstrainedClient", return_value=mock_client),
        caplog.at_level(logging.WARNING),
    ):
        result = await extractor.extract_image_url("https://example.com/article")

    assert result is None
    assert "Redirect detected (SSRF protection)" in caplog.text
