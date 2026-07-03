from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urljoin

import requests


NAVER_API_BASE = "https://api-gw.sports.naver.com/"


class NaverSportsClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://m.sports.naver.com",
                "Referer": "https://m.sports.naver.com/",
            }
        )

    def get_json(self, url_or_path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = url_or_path
        if not url.startswith("http"):
            url = urljoin(NAVER_API_BASE, url.lstrip("/"))
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def preview(self, game_id: str) -> dict[str, Any]:
        return self.get_json(f"/schedule/games/{game_id}/preview")

    def relay(self, game_id: str, inning: int | None = None) -> dict[str, Any]:
        params = {"inning": inning} if inning else None
        return self.get_json(f"/schedule/games/{game_id}/relay", params=params)

    def games_on(self, day: date) -> list[dict[str, Any]]:
        ymd = day.strftime("%Y-%m-%d")
        compact = day.strftime("%Y%m%d")
        candidates = [
            ("/schedule/games", {"categoryId": "kbo", "fromDate": ymd, "toDate": ymd}),
            ("/schedule/games", {"categoryId": "kbo", "date": ymd}),
            ("/schedule/games", {"category": "kbo", "date": compact}),
        ]

        last_error: Exception | None = None
        for path, params in candidates:
            try:
                data = self.get_json(path, params=params)
                games = find_game_dicts(data)
                if games:
                    return games
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        return []


def find_game_dicts(value: Any) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "gameId" in node and any(k in node for k in ("hCode", "aCode", "homeTeamCode", "awayTeamCode")):
                games.append(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    unique: dict[str, dict[str, Any]] = {}
    for game in games:
        unique[str(game["gameId"])] = game
    return list(unique.values())


def unwrap(data: dict[str, Any], key: str) -> dict[str, Any]:
    result = data.get("result", data)
    return result.get(key, result)
