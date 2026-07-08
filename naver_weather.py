from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests


NAVER_WEATHER_BASE = "https://weather.naver.com/today"


@dataclass(frozen=True)
class WeatherRegion:
    code: str
    name: str
    keywords: tuple[str, ...]


STADIUM_WEATHER_REGIONS = (
    WeatherRegion("18300105", "광주 북구 임동", ("광주", "기아챔피언스필드", "챔피언스필드")),
    WeatherRegion("09710101", "서울 송파구 잠실동", ("잠실", "서울종합운동장")),
    WeatherRegion("09530106", "서울 구로구 고척동", ("고척", "스카이돔")),
    WeatherRegion("11177107", "인천 미추홀구 문학동", ("문학", "인천", "랜더스")),
    WeatherRegion("02111136", "수원 장안구 조원동", ("수원", "케이티", "kt위즈파크", "위즈파크")),
    WeatherRegion("07140111", "대전 중구 부사동", ("대전", "한화생명", "이글스파크")),
    WeatherRegion("06260123", "대구 수성구 연호동", ("대구", "라이온즈파크")),
    WeatherRegion("03127105", "창원 마산회원구 양덕동", ("창원", "마산", "엔씨파크", "nc파크")),
    WeatherRegion("08260109", "부산 동래구 사직동", ("사직", "부산")),
    WeatherRegion("10140102", "울산 남구 옥동", ("울산", "문수")),
    WeatherRegion("04113122", "포항 북구 양덕동", ("포항",)),
    WeatherRegion("16112101", "청주 서원구 사직동", ("청주",)),
)


class NaverWeatherClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://weather.naver.com/",
            }
        )

    def stadium_weather(self, stadium: str, now: datetime, hours: int = 8) -> str:
        region = resolve_stadium_weather_region(stadium)
        if region is None:
            return f"구장 날씨 위치를 찾지 못했습니다: {stadium or '-'}"

        html = self._get_region_html(region.code)
        data = parse_weather_page(html)
        return format_stadium_weather(stadium, region, data, now, hours)

    def _get_region_html(self, region_code: str) -> str:
        response = self.session.get(f"{NAVER_WEATHER_BASE}/{region_code}", timeout=10)
        response.raise_for_status()
        return response.text


def resolve_stadium_weather_region(stadium: str) -> WeatherRegion | None:
    normalized = re.sub(r"\s+", "", stadium or "").lower()
    if not normalized:
        return None
    for region in STADIUM_WEATHER_REGIONS:
        if any(re.sub(r"\s+", "", keyword).lower() in normalized for keyword in region.keywords):
            return region
    return None


def parse_weather_page(html: str) -> dict[str, Any]:
    marker = "var blockApiResult = "
    start = html.find(marker)
    if start < 0:
        raise ValueError("blockApiResult not found in Naver weather page")
    json_start = start + len(marker)
    json_end = _find_json_object_end(html, json_start)
    block_api_result = json.loads(html[json_start:json_end])
    return block_api_result.get("results", {}).get("choiceResult", {})


def _find_json_object_end(text: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError("blockApiResult JSON is not closed")


def format_stadium_weather(
    stadium: str,
    region: WeatherRegion,
    data: dict[str, Any],
    now: datetime,
    hours: int = 8,
) -> str:
    current = _first_block_value(data, "talkHeader").get("nowFcastInfo", {})
    air = _first_block_value(data, "talkHeader").get("airNowInfo", {})
    hourly = _first_block_value(data, "visualMap").get("domesticWetrList", [])
    upcoming = _upcoming_hourly(hourly, now, hours)

    lines = [
        f"구장 날씨 | {stadium or '-'}",
        region.name,
    ]
    if current:
        lines.append(
            "현재 "
            f"{_weather_text(current.get('wetrTxt', '-'))} {current.get('tmpr', '-')}°"
            f" | 바람 {current.get('windSpd', '-')}m/s"
            f" | 1시간 강수 {_rain_amount_text(current.get('oneHourRainAmt', '-'))}"
        )
    if air:
        lines.append(
            f"미세먼지 {air.get('stationPm10Legend', '-')} | 초미세먼지 {air.get('stationPm25Legend', '-')}"
        )
    if upcoming:
        lines += ["", "시간별 날씨"]
        lines.extend(_format_hourly_item(item) for item in upcoming)
    return "\n".join(lines)


def _first_block_value(data: dict[str, Any], prefix: str) -> dict[str, Any]:
    for key, value in data.items():
        if key.startswith(prefix) and isinstance(value, dict):
            return value
    return {}


def _upcoming_hourly(hourly: list[dict[str, Any]], now: datetime, hours: int) -> list[dict[str, Any]]:
    now_key = now.strftime("%Y%m%d%H")
    future = [
        item
        for item in hourly
        if str(item.get("aplYmd", "")) + str(item.get("aplTm", "")).zfill(2) >= now_key
    ]
    return future[:hours] if future else hourly[:hours]


def _format_hourly_item(item: dict[str, Any]) -> str:
    label = f"{str(item.get('aplTm', '--')).zfill(2)}시"
    rain_prob = item.get("rainProb", "-")
    rain_amt = item.get("rainAmt", item.get("oneHourRainAmt", "-"))
    return (
        f"{label} {_weather_text(item.get('wetrTxt', '-'))} {item.get('tmpr', '-')}°"
        f" | 강수 {_rain_prob_text(rain_prob)} ({_rain_amount_text(rain_amt)})"
        f" | 바람 {item.get('windSpd', '-')}m/s"
    )


def _rain_prob_text(value: Any) -> str:
    if value in (None, "", "-"):
        return "-"
    return f"{value}%"


def _rain_amount_text(value: Any) -> str:
    if value in (None, ""):
        return "-"
    text = str(value)
    if text == "-":
        return "-"
    if text.endswith("mm"):
        return text
    return f"{text}mm"


def _weather_text(value: Any) -> str:
    text = str(value or "-")
    if text == "구름많음":
        return "흐림"
    return text
