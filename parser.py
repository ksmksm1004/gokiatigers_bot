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
    batter_code: str | None = None
    home_or_away: str = ""
    current_state: dict[str, Any] | None = None

    @property
    def is_homer(self) -> bool:
        return "홈런" in self.text

    @property
    def is_pitching_change(self) -> bool:
        return self.text.startswith("투수 ") and "교체" in self.text

    @property
    def is_score_event(self) -> bool:
        return "홈인" in self.text or "홈런" in self.text or "득점" in self.text

    @property
    def is_attack_start(self) -> bool:
        return bool(re.match(r"\d+회[초말]\s+.+\s+공격$", self.text))

    @property
    def is_game_marker(self) -> bool:
        return any(word in self.text for word in ("경기종료", "승리투수", "패전투수"))

    @property
    def is_plate_result(self) -> bool:
        return ":" in self.text and not self.text.startswith("투수 ")


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


def has_starting_lineups(preview: dict[str, Any]) -> bool:
    return bool(get_starting_lineup(preview, "away") and get_starting_lineup(preview, "home"))


def get_starting_lineup(preview: dict[str, Any], side: str) -> list[dict[str, Any]]:
    key = "awayTeamLineUp" if side == "away" else "homeTeamLineUp"
    lineup = preview.get(key, {}).get("fullLineUp", [])
    return sorted(
        (player for player in lineup if player.get("playerCode")),
        key=lambda player: int(player.get("batorder") or 0),
    )


def lineup_media_items(preview: dict[str, Any], side: str) -> list[tuple[str, str]]:
    info = preview.get("gameInfo", {})
    team_name = info.get("aName" if side == "away" else "hName", side)
    players = get_starting_lineup(preview, side)
    items: list[tuple[str, str]] = []
    for player in players:
        code = player.get("playerCode")
        if not code:
            continue
        order = player.get("batorder")
        label = "선발투수" if not order else f"{order}번타자"
        caption = "\n".join(
            [
                f"{team_name} {label}",
                f"{player.get('playerName', '-')}",
                f"{player.get('positionName', '-')} / {player.get('batsThrows', '-')}",
            ]
        )
        items.append((PLAYER_IMAGE.format(pcode=code), caption))
    return items[:10]


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
                    batter_code=str(state.get("batter") or ""),
                    home_or_away=str(group.get("homeOrAway") or ""),
                    current_state=state,
                )
            )

    return sorted({event.event_id: event for event in events}.values(), key=lambda e: e.event_id)


def important_events(events: list[RelayEvent]) -> list[RelayEvent]:
    return [event for event in events if any(word in event.text for word in IMPORTANT_WORDS)]


def is_kia_batting(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if event.home_or_away == "1":
        return home_code == team_code
    if event.home_or_away == "0":
        return away_code == team_code
    return False


def batting_team_name(event: RelayEvent, home_name: str, away_name: str) -> str:
    return home_name if event.home_or_away == "1" else away_name


def is_kia_batter_event(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if not is_kia_batting(event, home_code, away_code, team_code):
        return False
    return event.is_plate_result and (
        is_hit_event(event)
        or is_walk_event(event)
        or is_sacrifice_event(event)
        or is_steal_event(event)
    )


def is_hit_event(event: RelayEvent) -> bool:
    return any(word in event.text for word in ("1루타", "2루타", "3루타", "안타", "홈런"))


def is_walk_event(event: RelayEvent) -> bool:
    return any(word in event.text for word in ("볼넷", "사구", "몸에 맞는 볼", "몸에맞는볼", "고의4구"))


def is_sacrifice_event(event: RelayEvent) -> bool:
    return "희생플라이" in event.text or "희생번트" in event.text


def is_steal_event(event: RelayEvent) -> bool:
    return "도루" in event.text and "실패" not in event.text


def should_send_relay_event(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if event.text == "투수 투수판 이탈":
        return False
    if event.text.startswith("승리투수") or event.text.startswith("패전투수"):
        return False
    if event.is_pitching_change or event.is_game_marker:
        return True
    if event.is_score_event:
        return True
    return is_kia_batter_event(event, home_code, away_code, team_code)


def active_lineup(relay: dict[str, Any], side: str) -> list[dict[str, Any]]:
    key = "homeLineup" if side == "home" else "awayLineup"
    batters = relay.get(key, {}).get("batter", [])
    by_order: dict[int, dict[str, Any]] = {}
    for player in batters:
        if str(player.get("cout")).lower() == "true":
            continue
        order = _to_int(player.get("batOrder"))
        if not order:
            continue
        current = by_order.get(order)
        if current is None or _to_int(player.get("seqno")) >= _to_int(current.get("seqno")):
            by_order[order] = player
    return [by_order[order] for order in sorted(by_order)]


def expected_batters_message(
    event: RelayEvent,
    relay: dict[str, Any],
    home_code: str,
    away_code: str,
    away_name: str,
    home_name: str,
    team_code: str = KIA_CODE,
) -> str:
    if not is_kia_batting(event, home_code, away_code, team_code):
        return ""
    side = "home" if event.home_or_away == "1" else "away"
    batters = active_lineup(relay, side)
    if not batters:
        return ""

    start_code = event.batter_code or (event.current_state or {}).get("batter")
    start_index = 0
    for index, player in enumerate(batters):
        if str(player.get("pcode")) == str(start_code):
            start_index = index
            break
    expected = [batters[(start_index + offset) % len(batters)] for offset in range(min(3, len(batters)))]
    team_name = batting_team_name(event, home_name, away_name)
    lines = [
        f"KIA 공격 시작 | {event.inning}회{event.half}",
        f"{away_name} {event.away_score} : {event.home_score} {home_name}",
        f"{team_name} 예상 타자",
    ]
    lines.extend(f"{p.get('name', '-')} | {p.get('ab', 0)}타수 {p.get('hit', 0)}안타" for p in expected)
    return "\n".join(lines)


def find_previous_plate_event(events: list[RelayEvent], event: RelayEvent) -> RelayEvent | None:
    previous = [candidate for candidate in events if candidate.event_id < event.event_id and candidate.title == event.title]
    for candidate in reversed(previous):
        if candidate.is_plate_result:
            return candidate
    return None


def relay_player_record(relay: dict[str, Any], event: RelayEvent) -> dict[str, Any]:
    if not event.batter_code:
        return {}
    side = "home" if event.home_or_away == "1" else "away"
    for player in relay.get(f"{side}Lineup", {}).get("batter", []):
        if str(player.get("pcode")) == str(event.batter_code):
            return player
    return {}


def format_relay_event_with_context(
    event: RelayEvent,
    away_name: str,
    home_name: str,
    previous_plate_event: RelayEvent | None = None,
    player_record: dict[str, Any] | None = None,
) -> str:
    text = format_relay_event(event, away_name, home_name, player_record)
    if event.is_score_event and previous_plate_event and previous_plate_event.text not in text:
        lines = text.splitlines()
        insert_at = 3 if len(lines) >= 3 else len(lines)
        lines.insert(insert_at, previous_plate_event.text)
        return "\n".join(lines)
    return text


def kia_half_summary_message(
    events: list[RelayEvent],
    relay: dict[str, Any],
    finished_by_event: RelayEvent,
    home_code: str,
    away_code: str,
    away_name: str,
    home_name: str,
    team_code: str = KIA_CODE,
) -> str:
    previous_half = _previous_half(finished_by_event)
    if previous_half is None:
        return ""
    inning, half = previous_half
    probe = RelayEvent(
        event_id=0,
        inning=inning,
        half=half,
        text="",
        home_score=finished_by_event.home_score,
        away_score=finished_by_event.away_score,
        home_or_away="1" if half == "말" else "0",
    )
    if not is_kia_batting(probe, home_code, away_code, team_code):
        return ""

    side = "home" if half == "말" else "away"
    lineup_by_code = {str(player.get("pcode")): player for player in active_lineup(relay, side)}
    used_codes: list[str] = []
    for event in events:
        if event.inning == inning and event.half == half and event.batter_code and event.batter_code not in used_codes:
            used_codes.append(event.batter_code)
    if not used_codes:
        return ""

    lines = [
        f"KIA 공격 종료 | {inning}회{half}",
        f"{away_name} {finished_by_event.away_score} : {finished_by_event.home_score} {home_name}",
    ]
    for code in used_codes:
        player = lineup_by_code.get(str(code))
        if player:
            lines.append(format_player_stats(player))
    return "\n".join(line for line in lines if line)


def half_key(event: RelayEvent) -> str:
    return f"{event.inning}{event.half}"


def format_relay_event(
    event: RelayEvent,
    away_name: str,
    home_name: str,
    player_record: dict[str, Any] | None = None,
) -> str:
    prefix = "득점" if event.is_score_event else "교체" if event.is_pitching_change else "중계"
    lines = [
        f"{prefix} | {event.inning}회{event.half}",
        f"{away_name} {event.away_score} : {event.home_score} {home_name}",
        event.text,
    ]

    if event.is_game_marker or event.is_pitching_change:
        return "\n".join(lines)

    player = player_record or event.batter_record or event.player_info or {}
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
    prefix = ""
    if player.get("batOrder") and player.get("seasonHra") not in (None, ""):
        prefix = f"{player.get('batOrder')}번타자 타율 {player.get('seasonHra', '-')}" + " | "
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
    return f"{name} | {prefix}" + " ".join(fields)


def format_kia_record(record: dict[str, Any], team_code: str = KIA_CODE) -> str:
    info = record.get("gameInfo", {})
    side = "home" if info.get("hCode") == team_code else "away"
    team_name = info.get("hName" if side == "home" else "aName", "KIA")
    batters = record.get("battersBoxscore", {}).get(side, [])
    pitchers = record.get("pitchersBoxscore", {}).get(side, [])
    team_batting = record.get("battersBoxscore", {}).get(f"{side}Total", {})
    team_pitching = record.get("teamPitchingBoxscore", {}).get(side, {})

    lines = [
        f"{team_name} 경기 기록",
        f"타격 합계: {team_batting.get('ab', 0)}타수 {team_batting.get('run', 0)}득점 "
        f"{team_batting.get('hit', 0)}안타 {team_batting.get('rbi', 0)}타점 "
        f"{team_batting.get('hr', 0)}홈런 {team_batting.get('sb', 0)}도루",
        "",
        "타자",
    ]

    for player in batters:
        order = player.get("batOrder", "-")
        pos = player.get("pos", "")
        lines.append(
            f"{order}. {player.get('name', '-')} {pos} | 타율 {player.get('hra', '-')} | "
            f"{player.get('ab', 0)}타수 {player.get('run', 0)}득점 {player.get('hit', 0)}안타 "
            f"{player.get('rbi', 0)}타점 {player.get('hr', 0)}홈런 {player.get('bb', 0)}볼넷 "
            f"{player.get('kk', 0)}삼진 {player.get('sb', 0)}도루"
        )

    lines += [
        "",
        f"투구 합계: {team_pitching.get('inn', '-')}이닝 {team_pitching.get('hit', 0)}피안타 "
        f"{team_pitching.get('r', 0)}실점 {team_pitching.get('er', 0)}자책 "
        f"{team_pitching.get('bbhp', 0)}사사구 {team_pitching.get('kk', 0)}삼진",
        "",
        "투수",
    ]

    for player in pitchers:
        result = f" {player.get('wls')}" if player.get("wls") else ""
        lines.append(
            f"{player.get('name', '-')}{result} | {player.get('inn', '-')}이닝 "
            f"{player.get('hit', 0)}피안타 {player.get('r', 0)}실점 {player.get('er', 0)}자책 "
            f"{player.get('bbhp', 0)}사사구 {player.get('kk', 0)}삼진 ERA {player.get('era', '-')}"
        )

    return "\n".join(lines)


def format_game_highlights(record: dict[str, Any], team_code: str = KIA_CODE) -> str:
    info = record.get("gameInfo", {})
    away = info.get("aName", "원정")
    home = info.get("hName", "홈")
    highlights = []

    for item in record.get("etcRecords", []):
        how = item.get("how")
        result = item.get("result")
        if how and result:
            highlights.append(f"{how}: {result}")

    side = "home" if info.get("hCode") == team_code else "away"
    batters = record.get("battersBoxscore", {}).get(side, [])
    top_hitters = sorted(
        (p for p in batters if _to_int(p.get("hit")) > 0),
        key=lambda p: (_to_int(p.get("hit")), _to_int(p.get("rbi")), _to_int(p.get("run"))),
        reverse=True,
    )[:3]
    for player in top_hitters:
        highlights.append(
            f"{player.get('name')}: {player.get('hit', 0)}안타 "
            f"{player.get('rbi', 0)}타점 {player.get('run', 0)}득점"
        )

    if not highlights:
        return ""
    return "\n".join([f"경기 하이라이트 | {away} vs {home}", *highlights[:8]])


def format_team_rankings(rankings: dict[str, Any], last_ten: dict[str, Any]) -> str:
    ranking_rows = rankings.get("seasonTeamStats", [])
    recent_by_team = {
        row.get("teamId"): row.get("lastTenGameResult", "-")
        for row in last_ten.get("seasonTeamLastTenGameStats", [])
    }

    lines = ["KBO 팀 순위"]
    for row in sorted(ranking_rows, key=lambda item: _to_int(item.get("ranking"))):
        team_id = row.get("teamId")
        rank = row.get("ranking", "-")
        name = row.get("teamName", "-")
        lines.append(
            f"{rank}. {name} | "
            f"{row.get('winGameCount', 0)}승 {row.get('drawnGameCount', 0)}무 {row.get('loseGameCount', 0)}패 | "
            f"{row.get('gameBehind', '-')}G | "
            f"{row.get('continuousGameResult', '-')} | "
            f"{recent_by_team.get(team_id, '-')}"
        )
    return "\n".join(lines)


def format_pitching_decisions(record: dict[str, Any], away_name: str, home_name: str, away_score: int, home_score: int) -> str:
    pitchers = record.get("pitchersBoxscore", {})
    by_result: dict[str, list[str]] = {"승": [], "패": [], "세": []}
    for side in ("away", "home"):
        for player in pitchers.get(side, []):
            result = player.get("wls")
            if result == "승":
                by_result["승"].append(f"승리투수: {player.get('name', '-')}")
            elif result == "패":
                by_result["패"].append(f"패전투수: {player.get('name', '-')}")
            elif result == "세":
                by_result["세"].append(f"세이브: {player.get('name', '-')}")
    decisions = by_result["승"] + by_result["패"] + by_result["세"]
    if not decisions:
        return ""
    return "\n".join(["중계 | 경기종료", f"{away_name} {away_score} : {home_score} {home_name}", *decisions])


def player_photo_url(event: RelayEvent) -> str | None:
    player = event.batter_record or event.player_info or {}
    pcode = player.get("pcode") or player.get("playerCode") or player.get("pCode")
    if not pcode:
        pcode = event.player_code or event.batter_code
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


def _previous_half(event: RelayEvent) -> tuple[int, str] | None:
    if event.half == "말":
        return event.inning, "초"
    if event.inning <= 1:
        return None
    return event.inning - 1, "말"


def _to_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fmt_avg(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value < 1:
            return f"{value:.3f}"
        return f"{value:.2f}"
    return str(value)
