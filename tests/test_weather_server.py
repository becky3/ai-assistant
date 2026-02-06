"""天気予報MCPサーバーのテスト (Issue #83, AC1-AC3).

仕様: docs/specs/f5-mcp-integration.md
気象庁API（非公式）を使用。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


def _make_area_response() -> bytes:
    """気象庁 area.json のモックレスポンスを生成する."""
    return json.dumps({
        "offices": {
            "130000": {"name": "東京都", "officeName": "気象庁"},
            "270000": {"name": "大阪府", "officeName": "大阪管区気象台"},
            "016000": {"name": "石狩・空知・後志地方", "officeName": "札幌管区気象台"},
            "400000": {"name": "福岡県", "officeName": "福岡管区気象台"},
            "471000": {"name": "沖縄本島地方", "officeName": "沖縄気象台"},
        }
    }).encode("utf-8")


def _make_forecast_response(
    dates: list[str] | None = None,
    weathers: list[str] | None = None,
    pops: list[str] | None = None,
    temps: list[str] | None = None,
) -> bytes:
    """気象庁 forecast API のモックレスポンスを生成する."""
    if dates is None:
        dates = [
            "2026-02-06T00:00:00+09:00",
            "2026-02-07T00:00:00+09:00",
            "2026-02-08T00:00:00+09:00",
        ]
    if weathers is None:
        weathers = ["晴れ　時々　くもり", "くもり　時々　雨", "晴れ"]
    if pops is None:
        pops = ["0", "10", "20", "50", "30", "20"]
    if temps is None:
        temps = ["15", "5"]

    # 短期予報（forecast_data[0]）
    short_forecast = {
        "timeSeries": [
            {
                "timeDefines": dates,
                "areas": [{"area": {"name": "東京地方"}, "weathers": weathers}],
            },
            {
                "timeDefines": ["T00", "T06", "T12", "T18", "T00", "T06"],
                "areas": [{"area": {"name": "東京地方"}, "pops": pops}],
            },
            {
                "timeDefines": ["T00", "T09"],
                "areas": [{"area": {"name": "東京"}, "temps": temps}],
            },
        ]
    }

    # 週間予報（forecast_data[1]）
    week_dates = [f"2026-02-{7 + i:02d}T00:00:00+09:00" for i in range(7)]
    week_forecast = {
        "timeSeries": [
            {
                "timeDefines": week_dates,
                "areas": [{
                    "area": {"name": "東京地方"},
                    "weatherCodes": ["100", "200", "300", "202", "100", "100", "200"],
                    "pops": ["10", "30", "50", "70", "20", "10", "30"],
                }],
            },
            {
                "timeDefines": week_dates,
                "areas": [{
                    "area": {"name": "東京"},
                    "tempsMin": ["3", "2", "1", "4", "5", "3", "2"],
                    "tempsMax": ["12", "10", "8", "11", "14", "13", "10"],
                }],
            },
        ]
    }

    return json.dumps([short_forecast, week_forecast]).encode("utf-8")


def _mock_urlopen_factory(
    area_response: bytes | None = None,
    forecast_response: bytes | None = None,
) -> MagicMock:
    """urlopen のモックを作成する."""
    if area_response is None:
        area_response = _make_area_response()
    if forecast_response is None:
        forecast_response = _make_forecast_response()

    def side_effect(req: object, timeout: int = 10, context: object = None) -> MagicMock:
        mock_resp = MagicMock()
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "area.json" in url:
            mock_resp.read.return_value = area_response
        else:
            mock_resp.read.return_value = forecast_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    mock = MagicMock(side_effect=side_effect)
    return mock


def _reset_office_map() -> None:
    """テスト間で _office_map をリセットする."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    mod._office_map.clear()


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """各テスト前にキャッシュをクリアする."""
    _reset_office_map()


@pytest.mark.asyncio
async def test_ac1_weather_server_exposes_tool() -> None:
    """AC1: 天気予報MCPサーバーが起動し、get_weather ツールを公開すること."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    server = mod.mcp

    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "get_weather" in tool_names


@pytest.mark.asyncio
async def test_ac2_get_weather_returns_forecast_today() -> None:
    """AC2: get_weather ツールが今日の天気予報テキストを返すこと."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("東京", "today")

    assert "東京都" in result
    assert "今日" in result
    assert "晴れ" in result
    assert "降水確率" in result


@pytest.mark.asyncio
async def test_ac2_get_weather_returns_forecast_tomorrow() -> None:
    """AC2: get_weather ツールが明日の天気予報テキストを返すこと."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("大阪", "tomorrow")

    assert "大阪府" in result
    assert "明日" in result


@pytest.mark.asyncio
async def test_ac2_get_weather_returns_week_forecast() -> None:
    """AC2: get_weather ツールが週間予報テキストを返すこと."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("東京", "week")

    assert "東京都" in result
    assert "週間予報" in result
    # 7日分のデータが含まれる
    assert "2/7" in result


@pytest.mark.asyncio
async def test_ac3_jma_api_called_correctly() -> None:
    """AC3: 気象庁APIの正しいエンドポイントが呼ばれること."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        await get_weather("東京", "today")

    # area.json + forecast の2回呼ばれる
    assert mock_urlopen.call_count == 2

    # 1回目: area.json
    first_call_url = mock_urlopen.call_args_list[0][0][0].full_url
    assert "jma.go.jp" in first_call_url
    assert "area.json" in first_call_url

    # 2回目: forecast API（東京都 = 130000）
    second_call_url = mock_urlopen.call_args_list[1][0][0].full_url
    assert "jma.go.jp" in second_call_url
    assert "130000" in second_call_url


@pytest.mark.asyncio
async def test_ac3_location_not_found() -> None:
    """AC3: 存在しない地域名の場合、エラーメッセージを返すこと."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("存在しない場所XYZ", "today")

    assert "見つかりませんでした" in result


@pytest.mark.asyncio
async def test_city_name_fallback() -> None:
    """主要都市名（札幌など）でフォールバック検索が機能すること."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("札幌", "today")

    # 石狩・空知・後志地方のofficeコード 016000 で取得される
    assert "見つかりませんでした" not in result
    assert "今日" in result


@pytest.mark.asyncio
async def test_umbrella_recommendation_rain() -> None:
    """天気に「雨」が含まれる場合、傘の推奨メッセージが出ること."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    rainy_forecast = _make_forecast_response(
        weathers=["雨　時々　くもり", "くもり", "晴れ"],
        pops=["80", "60", "40", "20", "10", "10"],
    )
    mock_urlopen = _mock_urlopen_factory(forecast_response=rainy_forecast)

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("東京", "today")

    assert "傘を持っていくことをおすすめします" in result


@pytest.mark.asyncio
async def test_invalid_date_parameter() -> None:
    """無効な日付パラメータの場合、エラーメッセージを返すこと."""
    from importlib import import_module

    mod = import_module("mcp-servers.weather.server")
    get_weather = mod.get_weather

    mock_urlopen = _mock_urlopen_factory()

    with patch("urllib.request.urlopen", mock_urlopen):
        result = await get_weather("東京", "invalid_date")

    assert "無効です" in result
