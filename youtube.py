from __future__ import annotations

from datetime import date
from typing import Any
from xml.etree import ElementTree

import requests


TVING_SPORTS_CHANNEL_ID = "UC8JtQf77wqhVpOQ8Cze8JjA"
TVING_SPORTS_FEED_URL = (
    "https://www.youtube.com/feeds/videos.xml"
    f"?channel_id={TVING_SPORTS_CHANNEL_ID}"
)
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"


def find_tving_kia_highlight(
    game_date: date,
    session: requests.Session | None = None,
) -> dict[str, Any] | None:
    http = session or requests.Session()
    response = http.get(TVING_SPORTS_FEED_URL, timeout=10)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    date_label = f"{game_date.month}/{game_date.day} 경기"

    for entry in root.findall(f"{{{ATOM_NAMESPACE}}}entry"):
        title = str(entry.findtext(f"{{{ATOM_NAMESPACE}}}title") or "").strip()
        matchup = title.split("]", 1)[0] if title.startswith("[") and "]" in title else ""
        if (
            "KIA" not in matchup.upper()
            or date_label not in title
            or "하이라이트" not in title
            or "TVING" not in title.upper()
        ):
            continue

        url = ""
        for link in entry.findall(f"{{{ATOM_NAMESPACE}}}link"):
            if link.get("rel") == "alternate" and link.get("href"):
                url = str(link.get("href"))
                break
        if title and url:
            return {"title": title, "url": url}
    return None
