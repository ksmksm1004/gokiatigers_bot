from __future__ import annotations

import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from parser import get_starting_lineup, player_image_url


IMAGE_SIZE = (1200, 960)
POSITION_POINTS = {
    "1": (600, 535),
    "2": (600, 815),
    "3": (960, 410),
    "4": (790, 300),
    "5": (240, 410),
    "6": (410, 300),
    "7": (180, 150),
    "8": (600, 105),
    "9": (1020, 150),
}
POSITION_CODES = {
    "투수": "1",
    "선발투수": "1",
    "포수": "2",
    "1루수": "3",
    "2루수": "4",
    "3루수": "5",
    "유격수": "6",
    "좌익수": "7",
    "중견수": "8",
    "우익수": "9",
}
FONT_CANDIDATES = (
    Path("/System/Library/Fonts/AppleSDGothicNeo.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
)

PhotoLoader = Callable[[str], Optional[bytes]]


def defensive_lineup_players(preview: dict[str, Any], side: str) -> list[dict[str, Any]]:
    cache_key = (preview.get("gameInfo") or {}).get("gdate")
    defenders: dict[str, dict[str, Any]] = {}
    for player in get_starting_lineup(preview, side):
        position_code = str(player.get("position") or "")
        if position_code not in POSITION_POINTS:
            position_code = POSITION_CODES.get(str(player.get("positionName") or ""), "")
        if position_code not in POSITION_POINTS:
            continue
        player_code = player.get("playerCode")
        defenders[position_code] = {
            **player,
            "positionCode": position_code,
            "photoUrl": player_image_url(player_code, cache_key) if player_code else "",
        }
    return [defenders[code] for code in sorted(defenders, key=int)]


def render_defensive_lineup_image(
    preview: dict[str, Any],
    side: str,
    photo_loader: PhotoLoader | None = None,
) -> bytes | None:
    players = defensive_lineup_players(preview, side)
    if {player["positionCode"] for player in players} != set(POSITION_POINTS):
        return None

    image = Image.new("RGB", IMAGE_SIZE, "#2f7d45")
    draw = ImageDraw.Draw(image)
    _draw_field(draw)
    name_font = _load_font(30, bold=True)
    fallback_font = _load_font(42, bold=True)
    loader = photo_loader or download_player_photo

    for player in players:
        photo = None
        photo_url = str(player.get("photoUrl") or "")
        if photo_url:
            photo_data = loader(photo_url)
            if photo_data:
                try:
                    photo = Image.open(BytesIO(photo_data)).convert("RGBA")
                except (OSError, ValueError):
                    logging.warning("Could not decode lineup photo for %s.", player.get("playerName"))
        _draw_player(
            image,
            draw,
            POSITION_POINTS[player["positionCode"]],
            str(player.get("playerName") or "-"),
            photo,
            name_font,
            fallback_font,
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def download_player_photo(url: str) -> bytes | None:
    try:
        return _download_player_photo(url)
    except requests.RequestException:
        logging.warning("Could not download lineup photo: %s", url)
        return None


@lru_cache(maxsize=128)
def _download_player_photo(url: str) -> bytes:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.content


def _draw_field(draw: ImageDraw.ImageDraw) -> None:
    grass = "#2f7d45"
    line = "#78a987"
    dirt = "#bda682"
    base = "#fffdf6"

    home = (600, 735)
    first = (920, 500)
    second = (600, 275)
    third = (280, 500)
    draw.line((home, (1200, 365)), fill=line, width=5)
    draw.line((home, (0, 365)), fill=line, width=5)
    draw.line((home, first, second, third, home), fill=dirt, width=118, joint="curve")
    draw.polygon(((600, 342), (830, 505), (600, 670), (370, 505)), fill=grass)
    draw.ellipse((532, 476, 668, 594), fill=dirt)
    draw.ellipse((525, 680, 675, 812), fill=dirt)

    _draw_base(draw, second)
    _draw_base(draw, first)
    _draw_base(draw, third)
    draw.polygon(((600, 716), (624, 731), (618, 757), (582, 757), (576, 731)), fill=base)


def _draw_base(draw: ImageDraw.ImageDraw, point: tuple[int, int]) -> None:
    x, y = point
    radius = 20
    draw.polygon(((x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)), fill="#fffdf6")


def _draw_player(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    name: str,
    photo: Image.Image | None,
    name_font: ImageFont.ImageFont,
    fallback_font: ImageFont.ImageFont,
) -> None:
    x, y = point
    avatar_size = 112
    avatar_left = x - avatar_size // 2
    avatar_top = y - avatar_size // 2
    avatar = Image.new("RGBA", (avatar_size, avatar_size), "#f1eadb")

    if photo is not None:
        photo.thumbnail((avatar_size - 8, avatar_size + 18), Image.Resampling.LANCZOS)
        photo_x = (avatar_size - photo.width) // 2
        photo_y = avatar_size - photo.height + 5
        avatar.alpha_composite(photo, (photo_x, photo_y))
    else:
        fallback_draw = ImageDraw.Draw(avatar)
        initial = name[:1] or "-"
        box = fallback_draw.textbbox((0, 0), initial, font=fallback_font)
        fallback_draw.text(
            ((avatar_size - (box[2] - box[0])) / 2, (avatar_size - (box[3] - box[1])) / 2 - box[1]),
            initial,
            font=fallback_font,
            fill="#31513d",
        )

    mask = Image.new("L", (avatar_size, avatar_size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
    image.paste(avatar.convert("RGB"), (avatar_left, avatar_top), mask)
    draw.ellipse(
        (avatar_left, avatar_top, avatar_left + avatar_size, avatar_top + avatar_size),
        outline="#f8f4ea",
        width=5,
    )

    text_box = draw.textbbox((0, 0), name, font=name_font)
    text_width = text_box[2] - text_box[0]
    label_width = max(94, text_width + 34)
    label_height = 44
    label_left = x - label_width / 2
    label_top = y + 42
    draw.rounded_rectangle(
        (label_left, label_top, label_left + label_width, label_top + label_height),
        radius=18,
        fill="#173f27",
    )
    draw.text(
        (x - text_width / 2, label_top + (label_height - (text_box[3] - text_box[1])) / 2 - text_box[1]),
        name,
        font=name_font,
        fill="#ffffff",
    )


def _load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if not path.exists():
            continue
        try:
            index = 6 if bold and path.name == "AppleSDGothicNeo.ttc" else 0
            return ImageFont.truetype(str(path), size=size, index=index)
        except OSError:
            continue
    return ImageFont.load_default(size=size)
