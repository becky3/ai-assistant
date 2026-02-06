"""天気予報MCPサーバー
仕様: docs/specs/f5-mcp-integration.md

気象庁API（非公式）を使用して日本国内の天気予報データを提供する。
分離制約: src/ 配下のモジュールは一切importしない。
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.request
from typing import Any

try:
    import certifi
    _ssl_context = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _ssl_context = None

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("weather")

# --- 気象庁 エリアコード管理 ---

_AREA_URL = "https://www.jma.go.jp/bosai/common/const/area.json"
_FORECAST_URL = "https://www.jma.go.jp/bosai/forecast/data/forecast/{code}.json"

# offices レベル: コード → 名前 のマッピング（起動時にロード）
_office_map: dict[str, str] = {}

# 主要都市名 → officeコード のフォールバック
# 気象庁の offices は都道府県・地方単位のため、市名で検索できるようにする
_CITY_TO_OFFICE: dict[str, str] = {
    "札幌": "016000",  # 石狩・空知・後志地方
    "仙台": "040000",  # 宮城県
    "名古屋": "230000",  # 愛知県
    "横浜": "140000",  # 神奈川県
    "神戸": "280000",  # 兵庫県
    "広島": "340000",  # 広島県
    "那覇": "471000",  # 沖縄本島地方
    "さいたま": "110000",  # 埼玉県
    "千葉": "120000",  # 千葉県
    "京都": "260000",  # 京都府
}


def _load_area_map() -> dict[str, str]:
    """気象庁 area.json から offices レベルのマッピングを取得する."""
    try:
        req = urllib.request.Request(_AREA_URL)
        with urllib.request.urlopen(req, timeout=10, context=_ssl_context) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        logger.exception("気象庁 area.json の取得に失敗しました")
        return {}

    offices: dict[str, str] = {}
    for code, info in data.get("offices", {}).items():
        name = info.get("name", "")
        if name:
            offices[code] = name
    return offices


def _find_office_code(location: str) -> tuple[str, str] | None:
    """地名からオフィスコードを検索する.

    完全一致 → 前方一致 → 部分一致 の順で検索。

    Returns:
        (code, name) タプル、見つからない場合は None
    """
    global _office_map
    if not _office_map:
        _office_map = _load_area_map()

    if not _office_map:
        return None

    # 完全一致
    for code, name in _office_map.items():
        if name == location:
            return code, name

    # 前方一致（"東京" → "東京都"）
    for code, name in _office_map.items():
        if name.startswith(location):
            return code, name

    # 部分一致（"大阪" → "大阪府"）
    for code, name in _office_map.items():
        if location in name:
            return code, name

    # 主要都市名フォールバック
    if location in _CITY_TO_OFFICE:
        code = _CITY_TO_OFFICE[location]
        name = _office_map.get(code, location)
        return code, name

    return None


def _fetch_forecast(office_code: str) -> list[dict[str, Any]]:
    """気象庁APIから天気予報データを取得する."""
    url = _FORECAST_URL.format(code=office_code)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10, context=_ssl_context) as resp:
        data: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
    return data


def _parse_short_forecast(forecast_data: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """短期予報（3日間）を解析する.

    Returns:
        {
            "dates": [...],
            "weathers": [...],
            "pops": [...],       # 降水確率（6期間）
            "pop_labels": [...], # 降水確率の時間ラベル
            "temps": [...],      # 気温
            "temp_labels": [...] # 気温ラベル
        }
    """
    result: dict[str, list[Any]] = {
        "dates": [],
        "weathers": [],
        "pops": [],
        "pop_labels": [],
        "temps": [],
        "temp_labels": [],
    }

    if not forecast_data:
        return result

    short = forecast_data[0]
    time_series = short.get("timeSeries", [])

    # timeSeries[0]: 天気・風（3日分）
    if len(time_series) > 0:
        ts0 = time_series[0]
        result["dates"] = ts0.get("timeDefines", [])
        areas = ts0.get("areas", [])
        if areas:
            result["weathers"] = areas[0].get("weathers", [])

    # timeSeries[1]: 降水確率（6期間）
    if len(time_series) > 1:
        ts1 = time_series[1]
        result["pop_labels"] = ts1.get("timeDefines", [])
        areas = ts1.get("areas", [])
        if areas:
            result["pops"] = areas[0].get("pops", [])

    # timeSeries[2]: 気温
    if len(time_series) > 2:
        ts2 = time_series[2]
        result["temp_labels"] = ts2.get("timeDefines", [])
        areas = ts2.get("areas", [])
        if areas:
            result["temps"] = areas[0].get("temps", [])

    return result


def _parse_week_forecast(forecast_data: list[dict[str, Any]]) -> dict[str, list[Any]]:
    """週間予報（7日間）を解析する.

    Returns:
        {
            "dates": [...],
            "weather_codes": [...],
            "pops": [...],
            "temp_maxes": [...],
            "temp_mins": [...],
        }
    """
    result: dict[str, list[Any]] = {
        "dates": [],
        "weather_codes": [],
        "pops": [],
        "temp_maxes": [],
        "temp_mins": [],
    }

    if len(forecast_data) < 2:
        return result

    week = forecast_data[1]
    time_series = week.get("timeSeries", [])

    # timeSeries[0]: 天気コード・降水確率
    if len(time_series) > 0:
        ts0 = time_series[0]
        result["dates"] = ts0.get("timeDefines", [])
        areas = ts0.get("areas", [])
        if areas:
            result["weather_codes"] = areas[0].get("weatherCodes", [])
            result["pops"] = areas[0].get("pops", [])

    # timeSeries[1]: 気温（最低・最高）
    if len(time_series) > 1:
        ts1 = time_series[1]
        areas = ts1.get("areas", [])
        if areas:
            result["temp_mins"] = areas[0].get("tempsMin", [])
            result["temp_maxes"] = areas[0].get("tempsMax", [])

    return result


def _format_date(iso_date: str) -> str:
    """ISO日付文字列を短い表示形式にする."""
    # "2026-02-06T17:00:00+09:00" → "2/6"
    try:
        date_part = iso_date.split("T")[0]
        parts = date_part.split("-")
        return f"{int(parts[1])}/{int(parts[2])}"
    except (IndexError, ValueError):
        return iso_date


@mcp.tool()
async def get_weather(location: str, date: str = "today") -> str:
    """指定された日本国内の場所の天気予報を取得する.

    Args:
        location: 地域名（例: "東京", "大阪", "札幌", "福岡"）
        date: 日付指定（"today" = 今日, "tomorrow" = 明日, "week" = 週間予報）

    Returns:
        天気予報のテキスト
    """
    match = _find_office_code(location)
    if match is None:
        if not _office_map:
            return "気象庁の地域データの取得に失敗しました。しばらく待ってからもう一度お試しください。"
        return (
            f"地域 '{location}' が見つかりませんでした。"
            "都道府県名（東京、大阪、北海道など）で指定してください。"
            "※日本国内のみ対応しています。"
        )

    office_code, area_name = match

    try:
        forecast_data = _fetch_forecast(office_code)
    except Exception:
        logger.exception("天気予報の取得に失敗しました: %s (%s)", area_name, office_code)
        return f"'{area_name}' の天気予報の取得中にエラーが発生しました。"

    if date in ("today", "tomorrow"):
        return _format_short_forecast(forecast_data, area_name, date)
    elif date == "week":
        return _format_week_forecast(forecast_data, area_name)
    else:
        return f"日付指定 '{date}' は無効です。'today', 'tomorrow', 'week' のいずれかを指定してください。"


def _format_short_forecast(
    forecast_data: list[dict[str, Any]],
    area_name: str,
    date: str,
) -> str:
    """短期予報をテキストに整形する."""
    parsed = _parse_short_forecast(forecast_data)

    weathers = parsed["weathers"]
    pops = parsed["pops"]
    temps = parsed["temps"]

    if date == "today":
        idx = 0
        label = "今日"
    else:  # tomorrow
        idx = 1
        label = "明日"

    if idx >= len(weathers):
        return f"'{area_name}' の{label}の天気予報データがありません。"

    weather = weathers[idx]
    date_str = _format_date(parsed["dates"][idx]) if idx < len(parsed["dates"]) else ""

    lines = [f"{area_name} の天気予報（{label} {date_str}）:"]
    lines.append(f"  天気: {weather}")

    # 降水確率（今日: 最初の数値、明日: 後半の数値）
    if pops:
        pop_str = "／".join(f"{p}%" for p in pops if p)
        if pop_str:
            lines.append(f"  降水確率: {pop_str}")

    # 気温
    temp_values = [t for t in temps if t]
    if temp_values:
        lines.append(f"  気温: {'／'.join(f'{t}°C' for t in temp_values)}")

    # 傘判定
    has_rain = any(weather_text in weather for weather_text in ["雨", "雪", "みぞれ"])
    high_pop = any(int(p) >= 50 for p in pops if p and p.isdigit())
    if has_rain or high_pop:
        lines.append("  → 傘を持っていくことをおすすめします")
    else:
        lines.append("  → 傘は不要そうです")

    return "\n".join(lines)


def _format_week_forecast(
    forecast_data: list[dict[str, Any]],
    area_name: str,
) -> str:
    """週間予報をテキストに整形する."""
    parsed = _parse_week_forecast(forecast_data)

    dates = parsed["dates"]
    weather_codes = parsed["weather_codes"]
    pops = parsed["pops"]
    temp_maxes = parsed["temp_maxes"]
    temp_mins = parsed["temp_mins"]

    if not dates:
        return f"'{area_name}' の週間予報データがありません。"

    lines = [f"{area_name} の週間予報:"]
    for i, d in enumerate(dates):
        date_str = _format_date(d)
        pop = pops[i] if i < len(pops) else "-"
        t_max = temp_maxes[i] if i < len(temp_maxes) else "-"
        t_min = temp_mins[i] if i < len(temp_mins) else "-"

        temp_str = ""
        if t_max and t_min:
            temp_str = f"、{t_min}°C〜{t_max}°C"
        elif t_max:
            temp_str = f"、最高{t_max}°C"

        pop_str = f"、降水確率{pop}%" if pop and pop != "-" else ""

        lines.append(f"  {date_str}: 天気コード{weather_codes[i] if i < len(weather_codes) else '?'}{temp_str}{pop_str}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
