from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


KIA_CODE = "HT"
PLAYER_IMAGE = "https://sports-phinf.pstatic.net/player/kbo/default/{pcode}.png?type=w150"
IMPORTANT_WORDS = (
    "홈런",
    "홈인",
    "득점",
    "투수 ",
    "교체",
    "경기종료",
    "공격",
    "선발",
    "승리투수",
    "패전투수",
)


@dataclass(frozen=True)
class GameSummary:
    game_id: str
    away_code: str
    home_code: str
    away_name: str
    home_name: str
    stadium: str
    start_at: datetime | None
    status_code: str


@dataclass(frozen=True)
class RelayEvent:
    event_id: int
    inning: int
    half: str
    text: str
    home_score: int
    away_score: int
    title: str = ""
    batter_record: dict[str, Any] | None = None
    player_info: dict[str, Any] | None = None
    player_name: str | None = None
    player_code: str | None = None

    @property
    def is_homer(self) -> bool:
        return "홈런" in self.text

    @property
    def is_pitching_change(self) -> bool:
        return self.text.startswith("투수 ") and "교체" in self.text

    @property
    def is_score_event(self) -> bool:
        return "홈인" in self.text or "홈런" in self.text or "득점" in self.text


def parse_game_summary(game: dict[str, Any], fallback_game_id: str | None = None) -> GameSummary:
    game_id = str(game.get("gameId") or fallback_game_id or "")
    gdate = str(game.get("gdate") or game.get("gameDate") or "")[:8]
    gtime = str(game.get("gtime") or game.get("gameTime") or "")
    start_at = None
    if game.get("gameDateTime"):
        try:
            start_at = datetime.fromisoformat(str(game["gameDateTime"]))
        except ValueError:
            start_at = None
    elif gdate and gtime:
        try:
            start_at = datetime.strptime(f"{gdate} {gtime}", "%Y%m%d %H:%M")
        except ValueError:
            start_at = None

    return GameSummary(
        game_id=game_id,
        away_code=str(game.get("aCode") or game.get("awayTeamCode") or ""),
        home_code=str(game.get("hCode") or game.get("homeTeamCode") or ""),
        away_name=str(game.get("aName") or game.get("awayTeamName") or ""),
        home_name=str(game.get("hName") or game.get("homeTeamName") or ""),
        stadium=str(game.get("stadium") or game.get("stadiumName") or ""),
        start_at=start_at,
        status_code=str(game.get("statusCode") or game.get("gameStatus") or ""),
    )


def team_in_game(game: dict[str, Any], team_code: str) -> bool:
    codes = {
        str(game.get("aCode") or game.get("awayTeamCode") or ""),
        str(game.get("hCode") or game.get("homeTeamCode") or ""),
    }
    return team_code in codes


def format_preview(preview: dict[str, Any], game_id: str) -> str:
    info = preview.get("gameInfo", {})
    away = info.get("aName", "원정")
    home = info.get("hName", "홈")
    date = info.get("gdate", "")
    time = info.get("gtime", "")
    stadium = info.get("stadium", "")

    lines = [
        "KIA 경기 프리뷰",
        f"{date} {time} {stadium}",
        f"{away} vs {home}",
        "",
    ]

    lines += _standings_lines(preview)
    lines += _starter_lines(preview)
    lines += _recent_lines(preview)
    lines += _vs_lines(preview)
    lines += _lineup_lines(preview)
    lines.append("")
    lines.append(f"네이버 중계: https://m.sports.naver.com/game/{game_id}/relay")
    return "\n".join(line for line in lines if line is not None)


def _standings_lines(preview: dict[str, Any]) -> list[str]:
    away = preview.get("awayStandings", {})
    home = preview.get("homeStandings", {})
    if not away and not home:
        return []
    return [
        "순위",
        f"{away.get('name', '원정')} {away.get('rank', '-')}위 {away.get('w', 0)}승 {away.get('d', 0)}무 {away.get('l', 0)}패 승률 {away.get('wra', '-')}",
        f"{home.get('name', '홈')} {home.get('rank', '-')}위 {home.get('w', 0)}승 {home.get('d', 0)}무 {home.get('l', 0)}패 승률 {home.get('wra', '-')}",
        f"팀타율 {away.get('hra', '-')} : {home.get('hra', '-')} / ERA {away.get('era', '-')} : {home.get('era', '-')}",
        "",
    ]


def _starter_lines(preview: dict[str, Any]) -> list[str]:
    rows = ["선발투수"]
    for label, key in (("원정", "awayStarter"), ("홈", "homeStarter")):
        starter = preview.get(key, {})
        info = starter.get("playerInfo", {})
        stats = starter.get("currentSeasonStats", {})
        if not info:
            continue
        rows.append(
            f"{label} {info.get('name', '-')} ({info.get('hitType', '-')}) "
            f"{stats.get('w', 0)}승 {stats.get('l', 0)}패 ERA {stats.get('era', '-')} "
            f"WHIP {stats.get('whip', '-')}"
        )
    return rows + [""] if len(rows) > 1 else []


def _recent_lines(preview: dict[str, Any]) -> list[str]:
    rows = ["최근 5경기"]
    for label, key in (("KIA", "homeTeamPreviousGames"), ("상대", "awayTeamPreviousGames")):
        games = preview.get(key, [])[:5]
        if not games:
            continue
        result = " ".join(str(game.get("result", "-")) for game in games)
        rows.append(f"{label}: {result}")
    return rows + [""] if len(rows) > 1 else []


def _vs_lines(preview: dict[str, Any]) -> list[str]:
    vs = preview.get("seasonVsResult", {})
    if not vs:
        return []
    return [
        "상대전적",
        f"KIA {vs.get('hw', 0)}승 {vs.get('hd', 0)}무 {vs.get('hl', 0)}패",
        "",
    ]


def _lineup_lines(preview: dict[str, Any]) -> list[str]:
    rows = ["선발 라인업"]
    for label, key in (("원정", "awayTeamLineUp"), ("KIA", "homeTeamLineUp")):
        lineup = preview.get(key, {}).get("fullLineUp", [])
        batters = sorted((p for p in lineup if p.get("batorder")), key=lambda p: int(p.get("batorder", 99)))
        if not batters:
            continue
        rows.append(label)
        for player in batters[:9]:
            rows.append(
                f"{player.get('batorder')}. {player.get('playerName')} "
                f"{player.get('positionName', '')}, {player.get('batsThrows', '')}"
            )
    return rows if len(rows) > 1 else []


def parse_relay_events(relay: dict[str, Any]) -> list[RelayEvent]:
    text_relays = relay.get("textRelays", [])
    events: list[RelayEvent] = []

    for group in text_relays:
        title = str(group.get("title") or "")
        inning = int(group.get("inn") or 0)
        half = "말" if str(group.get("homeOrAway")) == "1" else "초"
        for option in group.get("textOptions", []):
            state = option.get("currentGameState", {})
            text = str(option.get("text") or "").strip()
            seqno = option.get("seqno")
            if not text or seqno is None:
                continue
            events.append(
                RelayEvent(
                    event_id=int(seqno),
                    inning=inning,
                    half=half,
                    text=text,
                    home_score=_to_int(state.get("homeScore")),
                    away_score=_to_int(state.get("awayScore")),
                    title=title,
                    batter_record=option.get("batterRecord"),
                    player_info=_pick_player_info(option.get("currentPlayersInfo", {})),
                    player_name=_extract_player_name(text),
                    player_code=str(state.get("batter") or ""),
                )
            )

    return sorted({event.event_id: event for event in events}.values(), key=lambda e: e.event_id)


def important_events(events: list[RelayEvent]) -> list[RelayEvent]:
    return [event for event in events if any(word in event.text for word in IMPORTANT_WORDS)]


def format_relay_event(event: RelayEvent, away_name: str, home_name: str) -> str:
    prefix = "득점" if event.is_score_event else "교체" if event.is_pitching_change else "중계"
    lines = [
        f"{prefix} | {event.inning}회{event.half}",
        f"{away_name} {event.away_score} : {event.home_score} {home_name}",
        event.text,
    ]

    player = event.batter_record or event.player_info or {}
    stats = format_player_stats(player, event.player_name)
    if stats:
        lines += ["", stats]
    return "\n".join(lines)


def format_player_stats(player: dict[str, Any], fallback_name: str | None = None) -> str:
    if not player:
        return ""
    name = player.get("name") or player.get("playerName") or fallback_name
    if not name:
        return ""
    fields = [
        f"{player.get('ab', 0)}타수",
        f"{player.get('run', 0)}득점",
        f"{player.get('hit', 0)}안타",
        f"{player.get('rbi', 0)}타점",
        f"{player.get('hr', 0)}홈런",
        f"{player.get('bb', 0)}볼넷",
        f"{player.get('so', player.get('kk', 0))}삼진",
        f"{player.get('sb', 0)}도루",
    ]
    return f"{name} | " + " ".join(fields)


def player_photo_url(event: RelayEvent) -> str | None:
    player = event.batter_record or event.player_info or {}
    pcode = player.get("pcode") or player.get("playerCode") or player.get("pCode")
    if not pcode and event.is_homer:
        pcode = event.player_code
    if not pcode:
        return None
    return PLAYER_IMAGE.format(pcode=pcode)


def is_game_over(events: list[RelayEvent]) -> bool:
    return any("경기종료" in event.text or "승리투수" in event.text for event in events)


def _pick_player_info(players: dict[str, Any]) -> dict[str, Any] | None:
    for side in ("home", "away"):
        data = players.get(side, {})
        if data.get("playerType") == "batter":
            current = data.get("currentGamePlayerStats", {}).copy()
            return current
    return None


def _extract_player_name(text: str) -> str | None:
    match = re.match(r"([^: ]+)\s*:", text)
    if not match:
        return None
    return match.group(1)


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
