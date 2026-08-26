from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode


KIA_CODE = "HT"
PLAYER_IMAGE = "https://sports-phinf.pstatic.net/player/kbo/default/{pcode}.png?type=w150"
PLAYER_IMAGE_OVERRIDES = {
    # Naver's stable URL can leave Telegram serving the pre-trade Hanwha image.
    "62700": "https://tigers.co.kr/files/playerImg/tigersImg2/2026_30_C_new.png",
}
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
    "비디오 판독",
    "비디오판독",
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


@dataclass(frozen=True)
class HalfOutResult:
    label: str
    out_numbers: tuple[int, ...]
    player_code: str | None = None
    player_name: str | None = None

    @property
    def tagged_label(self) -> str:
        numbers = "".join(str(number) for number in self.out_numbers)
        return f"{self.label}{numbers}"


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


def format_preview(preview: dict[str, Any], game_id: str, team_code: str = KIA_CODE) -> str:
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
    lines += _recent_lines(preview, team_code)
    lines += _vs_lines(preview, team_code)
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


def _team_side(preview: dict[str, Any], team_code: str) -> str | None:
    info = preview.get("gameInfo", {})
    if str(info.get("aCode") or info.get("awayTeamCode") or "") == team_code:
        return "away"
    if str(info.get("hCode") or info.get("homeTeamCode") or "") == team_code:
        return "home"
    return None


def _recent_lines(preview: dict[str, Any], team_code: str = KIA_CODE) -> list[str]:
    side = _team_side(preview, team_code)
    key_pairs = {
        "away": (("KIA", "awayTeamPreviousGames"), ("상대", "homeTeamPreviousGames")),
        "home": (("KIA", "homeTeamPreviousGames"), ("상대", "awayTeamPreviousGames")),
    }
    rows = ["최근 5경기"]
    for label, key in key_pairs.get(side, (("KIA", "homeTeamPreviousGames"), ("상대", "awayTeamPreviousGames"))):
        games = preview.get(key, [])[:5]
        if not games:
            continue
        result = " ".join(str(game.get("result", "-")) for game in games)
        rows.append(f"{label}: {result}")
    return rows + [""] if len(rows) > 1 else []


def _vs_lines(preview: dict[str, Any], team_code: str = KIA_CODE) -> list[str]:
    vs = preview.get("seasonVsResult", {})
    if not vs:
        return []

    side = _team_side(preview, team_code)
    prefix = "a" if side == "away" else "h"
    return [
        "상대전적",
        f"KIA {vs.get(prefix + 'w', 0)}승 {vs.get(prefix + 'd', 0)}무 {vs.get(prefix + 'l', 0)}패",
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
    return _has_complete_starting_lineup(preview, "away") and _has_complete_starting_lineup(preview, "home")


def _has_complete_starting_lineup(preview: dict[str, Any], side: str) -> bool:
    players = get_starting_lineup(preview, side)
    batting_orders = {_to_int(player.get("batorder")) for player in players if player.get("batorder")}
    has_starting_pitcher = any(not player.get("batorder") for player in players)
    return batting_orders == set(range(1, 10)) and has_starting_pitcher


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
    cache_key = info.get("gdate") or info.get("gameDate")
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
        items.append((player_image_url(code, cache_key), caption))
    return items[:10]


def parse_relay_events(relay: dict[str, Any] | None) -> list[RelayEvent]:
    if not isinstance(relay, dict):
        return []
    text_relays = relay.get("textRelays") or []
    events: list[RelayEvent] = []

    for group in text_relays:
        title = str(group.get("title") or "")
        inning = int(group.get("inn") or 0)
        half = "말" if str(group.get("homeOrAway")) == "1" else "초"
        for option in group.get("textOptions") or []:
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


def is_kia_pitching(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if event.home_or_away == "1":
        return away_code == team_code
    if event.home_or_away == "0":
        return home_code == team_code
    return False


def batting_team_name(event: RelayEvent, home_name: str, away_name: str) -> str:
    return home_name if event.home_or_away == "1" else away_name


def is_kia_batter_event(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if is_video_review_event(event) or is_runner_event(event):
        return False
    if not is_kia_batting(event, home_code, away_code, team_code):
        return False
    return is_run_relevant_batter_event(event)


def is_batter_result_event(event: RelayEvent) -> bool:
    return event.is_plate_result and not is_runner_event(event) and not is_video_review_event(event) and (
        is_hit_event(event)
        or is_walk_event(event)
        or is_sacrifice_event(event)
        or is_batter_out_event(event)
    )


def is_run_relevant_batter_event(event: RelayEvent) -> bool:
    return event.is_plate_result and not is_runner_event(event) and not is_video_review_event(event) and (
        is_hit_event(event)
        or is_walk_event(event)
        or is_sacrifice_event(event)
    )


def is_runner_event(event: RelayEvent) -> bool:
    return bool(re.match(r"\d루주자\s+", event.text))


def is_video_review_event(event: RelayEvent) -> bool:
    return "비디오 판독" in event.text or "비디오판독" in event.text


def is_hit_event(event: RelayEvent) -> bool:
    return any(word in event.text for word in ("1루타", "2루타", "3루타", "안타", "홈런"))


def is_walk_event(event: RelayEvent) -> bool:
    return any(word in event.text for word in ("볼넷", "사구", "몸에 맞는 볼", "몸에맞는볼", "고의4구"))


def is_sacrifice_event(event: RelayEvent) -> bool:
    return "희생플라이" in event.text or "희생번트" in event.text


def is_steal_event(event: RelayEvent) -> bool:
    return "도루" in event.text and "실패" not in event.text


def is_batter_out_event(event: RelayEvent) -> bool:
    return any(word in event.text for word in ("삼진", "땅볼", "플라이", "뜬공", "직선타", "병살타"))


def should_send_relay_event(event: RelayEvent, home_code: str, away_code: str, team_code: str = KIA_CODE) -> bool:
    if event.text == "투수 투수판 이탈":
        return False
    if event.text.startswith("승리투수") or event.text.startswith("패전투수"):
        return False
    if is_video_review_event(event):
        return True
    if event.is_pitching_change or event.is_game_marker:
        return True
    if event.is_score_event:
        return True
    if is_kia_batter_event(event, home_code, away_code, team_code):
        return True
    return is_kia_batting(event, home_code, away_code, team_code) and is_runner_event(event) and is_steal_event(event)


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


def _previous_batter_order(
    events: list[RelayEvent],
    event: RelayEvent,
    relay: dict[str, Any],
    side: str,
) -> int:
    lineup_key = "homeLineup" if side == "home" else "awayLineup"
    lineup_by_code = {
        str(player.get("pcode") or ""): player
        for player in relay.get(lineup_key, {}).get("batter", [])
    }
    for candidate in sorted(events, key=lambda item: item.event_id, reverse=True):
        if candidate.event_id >= event.event_id or candidate.home_or_away != event.home_or_away:
            continue
        if candidate.is_attack_start:
            continue
        order = _to_int((candidate.batter_record or {}).get("batOrder"))
        if not order and candidate.batter_code:
            order = _to_int(lineup_by_code.get(str(candidate.batter_code), {}).get("batOrder"))
        if not order:
            match = re.match(r"(\d+)번타자", candidate.title)
            order = _to_int(match.group(1)) if match else 0
        if 1 <= order <= 9:
            return order
    return 0


def expected_batters_message(
    event: RelayEvent,
    relay: dict[str, Any],
    home_code: str,
    away_code: str,
    away_name: str,
    home_name: str,
    team_code: str = KIA_CODE,
    pitcher_lines: list[str] | None = None,
    previous_out_labels: list[str] | None = None,
    relay_events: list[RelayEvent] | None = None,
) -> str:
    if not is_kia_batting(event, home_code, away_code, team_code):
        return ""
    side = "home" if event.home_or_away == "1" else "away"
    batters = active_lineup(relay, side)
    if not batters:
        return ""

    start_index: int | None = None
    batter_record = event.batter_record or {}
    record_code = str(batter_record.get("pcode") or "")
    record_order = _to_int(batter_record.get("batOrder"))
    if record_code:
        start_index = next(
            (index for index, player in enumerate(batters) if str(player.get("pcode")) == record_code),
            None,
        )
    if start_index is None and record_order:
        start_index = next(
            (index for index, player in enumerate(batters) if _to_int(player.get("batOrder")) == record_order),
            None,
        )
    if start_index is None and relay_events:
        previous_order = _previous_batter_order(relay_events, event, relay, side)
        next_order = previous_order % 9 + 1 if previous_order else 0
        if next_order:
            start_index = next(
                (index for index, player in enumerate(batters) if _to_int(player.get("batOrder")) == next_order),
                None,
            )
    if start_index is None:
        start_code = event.batter_code or (event.current_state or {}).get("batter")
        start_index = next(
            (index for index, player in enumerate(batters) if str(player.get("pcode")) == str(start_code)),
            0,
        )
    expected = [batters[(start_index + offset) % len(batters)] for offset in range(min(3, len(batters)))]
    team_name = batting_team_name(event, home_name, away_name)
    score = f"{away_name} {event.away_score} : {event.home_score} {home_name}"
    if previous_out_labels:
        score += f" ({' '.join(previous_out_labels)})"
    lines = [
        f"KIA 공격 시작 | {event.inning}회{event.half}",
        score,
        f"{team_name} 예상 타자",
    ]
    lines.extend(format_batter_snapshot(p) for p in expected)
    if pitcher_lines:
        lines += ["", *pitcher_lines]
    return "\n".join(lines)


def pitcher_snapshot(relay: dict[str, Any], side: str) -> dict[str, dict[str, Any]]:
    key = "homeLineup" if side == "home" else "awayLineup"
    pitchers = relay.get(key, {}).get("pitcher", [])
    result: dict[str, dict[str, Any]] = {}
    for pitcher in pitchers:
        code = str(pitcher.get("pcode") or "")
        if not code:
            continue
        result[code] = {
            "name": pitcher.get("name", "-"),
            "ballCount": _to_int(pitcher.get("ballCount")),
            "inn": str(pitcher.get("inn") or "0"),
            "hit": _to_int(pitcher.get("hit")),
            "run": _to_int(pitcher.get("run")),
            "er": _to_int(pitcher.get("er")),
            "bb": _to_int(pitcher.get("bb")),
            "hbp": _to_int(pitcher.get("hbp")),
            "kk": _to_int(pitcher.get("kk")),
            "seasonEra": pitcher.get("seasonEra", "-"),
            "seqno": _to_int(pitcher.get("seqno")),
        }
    return result


def changed_pitcher_lines(
    relay: dict[str, Any],
    side: str,
    previous_snapshot: dict[str, dict[str, Any]] | None,
    team_label: str | None = None,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    current = pitcher_snapshot(relay, side)
    if not previous_snapshot:
        active = [pitcher for pitcher in current.values() if _pitcher_has_game_activity(pitcher)]
        active.sort(key=lambda pitcher: _to_int(pitcher.get("seqno")))
        return ([format_pitcher_snapshot(active[-1], team_label)] if active else []), current

    changed = []
    for code, pitcher in current.items():
        previous = previous_snapshot.get(code, {})
        if _pitcher_changed_since_snapshot(previous, pitcher):
            changed.append(pitcher)
    changed.sort(key=lambda pitcher: _to_int(pitcher.get("seqno")))
    return [format_pitcher_snapshot(pitcher, team_label) for pitcher in changed], current


def _pitcher_changed_since_snapshot(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    keys = ("ballCount", "inn", "hit", "run", "er", "bb", "hbp", "kk")
    return any(str(previous.get(key, 0)) != str(current.get(key, 0)) for key in keys)


def _pitcher_has_game_activity(pitcher: dict[str, Any]) -> bool:
    if any(_to_int(pitcher.get(key)) > 0 for key in ("ballCount", "hit", "run", "er", "bb", "hbp", "kk")):
        return True
    innings = str(pitcher.get("inn") or "").strip()
    return innings not in {"", "0", "0.0", "0 0/3"}


def format_pitcher_snapshot(pitcher: dict[str, Any], team_label: str | None = None) -> str:
    walk = _to_int(pitcher.get("bb")) + _to_int(pitcher.get("hbp"))
    name = str(pitcher.get("name") or "-")
    if team_label:
        name += f"({team_label})"
    fields = [
        f"{_format_innings(pitcher.get('inn'))}이닝",
        f"{_to_int(pitcher.get('hit'))}피안타",
        f"{_to_int(pitcher.get('run'))}실점",
        f"{_to_int(pitcher.get('er'))}자책",
        f"{walk}사사구",
        f"{_to_int(pitcher.get('kk'))}삼진",
        f"ERA {pitcher.get('seasonEra', '-')}",
    ]
    return f"{name} | {_to_int(pitcher.get('ballCount'))}개 | " + " ".join(fields)


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


def current_player_record(relay: dict[str, Any], event: RelayEvent) -> dict[str, Any]:
    lineup_record = relay_player_record(relay, event)
    if lineup_record and event.batter_record:
        merged = lineup_record.copy()
        merged.update({key: value for key, value in event.batter_record.items() if value not in (None, "")})
        return merged
    if lineup_record:
        return lineup_record
    return event.batter_record or event.player_info or {}


def plate_result_label(event: RelayEvent | None, player: dict[str, Any] | None = None) -> str:
    return _plate_result_label(event, player or {})


def plate_result_history(
    events: list[RelayEvent],
    event: RelayEvent,
    player_record: dict[str, Any] | None = None,
) -> list[str]:
    if not event.batter_code or not is_batter_result_event(event):
        return []

    labels: list[str] = []
    for candidate in sorted(events, key=lambda item: item.event_id):
        if candidate.event_id > event.event_id:
            break
        if candidate.batter_code != event.batter_code or not is_batter_result_event(candidate):
            continue
        label_player = (player_record or {}) if candidate.event_id == event.event_id else {}
        label = plate_result_label(candidate, label_player)
        if label:
            labels.append(label)
    return labels


def format_relay_event_with_context(
    event: RelayEvent,
    away_name: str,
    home_name: str,
    previous_plate_event: RelayEvent | None = None,
    player_record: dict[str, Any] | None = None,
    plate_results: list[str] | None = None,
) -> str:
    show_player_stats = is_batter_result_event(event)
    text = format_relay_event(event, away_name, home_name, player_record, plate_results, show_player_stats)
    if event.is_score_event and not is_batter_result_event(event) and previous_plate_event and previous_plate_event.text not in text:
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
    pitcher_lines: list[str] | None = None,
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
    lineup_key = "homeLineup" if side == "home" else "awayLineup"
    lineup = relay.get(lineup_key, {}).get("batter", [])
    active_batters = active_lineup(relay, side)
    lineup_by_code = {str(player.get("pcode")): player for player in lineup}
    active_by_order = {_to_int(player.get("batOrder")): player for player in active_batters}
    out_results = half_out_results(events, inning, half)
    stranded_runners = half_stranded_runners(events, inning, half)
    stranded_by_order: dict[int, list[int]] = {}
    for base, batting_order in stranded_runners.items():
        stranded_by_order.setdefault(batting_order, []).append(base)
    used_codes: list[str] = []
    for event in events:
        if event.inning == inning and event.half == half and event.batter_code and event.batter_code not in used_codes:
            used_codes.append(event.batter_code)
    for batting_order in stranded_by_order:
        player = active_by_order.get(batting_order)
        code = str((player or {}).get("pcode") or "")
        if code and code not in used_codes:
            used_codes.append(code)
    if not used_codes:
        return ""

    lines = [
        f"KIA 공격 종료 | {inning}회{half}",
        f"{away_name} {finished_by_event.away_score} : {finished_by_event.home_score} {home_name}",
    ]
    for code in used_codes:
        player = lineup_by_code.get(str(code))
        if player:
            line = format_batter_summary_stats(player)
            player_name = str(player.get("name") or "")
            result_labels = [
                result.tagged_label
                for result in out_results
                if (result.player_code and result.player_code == str(code))
                or (result.player_name and result.player_name == player_name)
            ]
            batting_order = _to_int(player.get("batOrder"))
            active_player = active_by_order.get(batting_order)
            active_code = str((active_player or {}).get("pcode") or "")
            stranded_bases = (
                stranded_by_order.get(batting_order, [])
                if active_code == str(code)
                else []
            )
            if stranded_bases:
                result_labels.append(_stranded_runner_label(stranded_bases))
            if result_labels:
                line += f" | {' '.join(result_labels)}"
            lines.append(line)
    if pitcher_lines:
        lines += ["", *pitcher_lines]
    return "\n".join(lines)


def opponent_half_summary_message(
    events: list[RelayEvent],
    finished_by_event: RelayEvent,
    home_code: str,
    away_code: str,
    away_name: str,
    home_name: str,
    team_code: str = KIA_CODE,
    pitcher_lines: list[str] | None = None,
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
    if not is_kia_pitching(probe, home_code, away_code, team_code):
        return ""

    labels = previous_half_result_labels(events, finished_by_event)
    lines = [
        f"{batting_team_name(probe, home_name, away_name)} 공격 종료 | {inning}회{half}",
        f"{away_name} {finished_by_event.away_score} : {finished_by_event.home_score} {home_name}",
    ]
    if labels:
        lines.append(" ".join(labels))
    if pitcher_lines:
        lines += ["", *pitcher_lines]
    return "\n".join(lines)


def previous_half_out_labels(events: list[RelayEvent], started_by_event: RelayEvent) -> list[str]:
    previous_half = _previous_half(started_by_event)
    if previous_half is None:
        return []
    inning, half = previous_half
    return [result.tagged_label for result in half_out_results(events, inning, half)]


def previous_half_result_labels(events: list[RelayEvent], started_by_event: RelayEvent) -> list[str]:
    previous_half = _previous_half(started_by_event)
    if previous_half is None:
        return []
    inning, half = previous_half
    labels = [result.tagged_label for result in half_out_results(events, inning, half)]
    stranded_runners = half_stranded_runners(events, inning, half)
    if stranded_runners:
        labels.append(_stranded_runner_label(list(stranded_runners)))
    return labels


def half_stranded_runners(events: list[RelayEvent], inning: int, half: str) -> dict[int, int]:
    half_events = sorted(
        (event for event in events if event.inning == inning and event.half == half),
        key=lambda event: event.event_id,
    )
    if not half_events:
        return {}
    final_state = half_events[-1].current_state or {}
    return {
        base: _to_int(final_state.get(f"base{base}"))
        for base in (1, 2, 3)
        if _to_int(final_state.get(f"base{base}"))
    }


def previous_half_pitcher_lines(
    events: list[RelayEvent],
    relay: dict[str, Any],
    started_by_event: RelayEvent,
    pitching_side: str,
    team_label: str | None = None,
) -> list[str]:
    previous_half = _previous_half(started_by_event)
    if previous_half is None:
        return []
    inning, half = previous_half
    pitcher_codes: list[str] = []
    for event in sorted(events, key=lambda item: item.event_id):
        if event.inning != inning or event.half != half:
            continue
        if event.is_attack_start:
            continue
        code = str((event.current_state or {}).get("pitcher") or "")
        if code and code not in pitcher_codes:
            pitcher_codes.append(code)

    snapshot = pitcher_snapshot(relay, pitching_side)
    lines = [
        format_pitcher_snapshot(snapshot[code], team_label)
        for code in pitcher_codes
        if code in snapshot
    ]
    if lines:
        return lines
    fallback, _ = changed_pitcher_lines(relay, pitching_side, None, team_label)
    return fallback


def half_out_results(events: list[RelayEvent], inning: int, half: str) -> list[HalfOutResult]:
    results: list[HalfOutResult] = []
    previous_out = 0
    half_events = sorted(
        (event for event in events if event.inning == inning and event.half == half),
        key=lambda event: event.event_id,
    )

    for event in half_events:
        current_out = _relay_out_count(event)
        if current_out is None:
            continue
        if current_out < previous_out:
            results = [
                result
                for result in results
                if not result.out_numbers or max(result.out_numbers) <= current_out
            ]
        elif current_out > previous_out:
            label = _out_result_label(event)
            if label:
                player_code, player_name = _out_result_player(event)
                results.append(
                    HalfOutResult(
                        label=label,
                        out_numbers=tuple(range(previous_out + 1, current_out + 1)),
                        player_code=player_code,
                        player_name=player_name,
                    )
                )
        previous_out = current_out

    return sorted(results, key=lambda result: result.out_numbers[0])


def _stranded_runner_label(bases: list[int]) -> str:
    return "잔루" + "".join(str(base) for base in sorted(bases))


def half_key(event: RelayEvent) -> str:
    return f"{event.inning}{event.half}"


def format_relay_event(
    event: RelayEvent,
    away_name: str,
    home_name: str,
    player_record: dict[str, Any] | None = None,
    plate_results: list[str] | None = None,
    show_player_stats: bool = True,
) -> str:
    prefix = "득점" if event.is_score_event else "교체" if event.is_pitching_change else "중계"
    out_count = _relay_out_count(event)
    out_text = f" ({out_count} out)" if out_count is not None and not event.is_attack_start else ""
    lines = [
        f"{prefix} | {event.inning}회{event.half}{out_text}",
        f"{away_name} {event.away_score} : {event.home_score} {home_name}",
        event.text,
    ]

    if event.is_game_marker or event.is_pitching_change or not show_player_stats:
        return "\n".join(lines)

    player = player_record or event.batter_record or event.player_info or {}
    stats = format_batter_snapshot(player, event.player_name, event, plate_results)
    if stats:
        lines += ["", stats]
    return "\n".join(lines)


def _relay_out_count(event: RelayEvent) -> int | None:
    state = event.current_state or {}
    value = state.get("out")
    if value in (None, ""):
        return None
    try:
        out_count = int(value)
    except (TypeError, ValueError):
        return None
    return out_count if 0 <= out_count <= 3 else None


def _out_result_label(event: RelayEvent) -> str:
    text = event.text.split(":", 1)[1].strip() if ":" in event.text else event.text
    if "병살타" in text:
        return "병살타"
    if "삼중살" in text:
        return "삼중살"
    if "태그아웃" in text:
        return "태그"
    if "포스아웃" in text:
        return "포스"
    if "도루" in text and "실패" in text:
        return "도루실패"
    if "견제" in text and "아웃" in text:
        return "견제"
    if "희생플라이" in text:
        return "희생플라이"
    if "희생번트" in text:
        return "희생번트"
    if "삼진" in text or "스트라이크 낫 아웃" in text:
        return "삼진"
    if "땅볼" in text:
        return "땅볼"
    if "플라이" in text or "뜬공" in text:
        return "플라이"
    if "직선타" in text:
        return "직선타"
    if "주루사" in text:
        return "주루사"
    if "아웃" in text:
        return "아웃"
    return ""


def _out_result_player(event: RelayEvent) -> tuple[str | None, str | None]:
    runner = re.match(r"(?:[123]루주자|타자주자)\s+(.+?)\s*:", event.text)
    if runner:
        return None, runner.group(1).strip()
    code = str(event.batter_code) if event.batter_code else None
    return code, event.player_name or _extract_player_name(event.text)


def format_batter_snapshot(
    player: dict[str, Any],
    fallback_name: str | None = None,
    event: RelayEvent | None = None,
    plate_results: list[str] | None = None,
) -> str:
    if not player:
        return ""
    name = player.get("name") or player.get("playerName") or fallback_name
    if not name:
        return ""
    parts = [
        str(player.get("batOrder") or player.get("batorder") or "-"),
        name,
        "|",
        _compact_avg(player.get("seasonHra", player.get("hra", "-"))),
        "|",
        f"{_to_int(player.get('hit'))}-{_to_int(player.get('ab'))}",
    ]
    result = " ".join(plate_results or []) if plate_results else plate_result_label(event, player) if event else ""
    if result:
        parts += ["|", result]
    return " ".join(parts)


def format_batter_summary_stats(player: dict[str, Any], fallback_name: str | None = None) -> str:
    if not player:
        return ""
    name = player.get("name") or player.get("playerName") or fallback_name
    if not name:
        return ""
    fields = _nonzero_batter_fields(player)
    base = f"{player.get('batOrder') or player.get('batorder') or '-'} {name} | {_compact_avg(player.get('seasonHra', player.get('hra', '-')))}"
    if fields:
        return f"{base} | {' '.join(fields)}"
    return base


def _nonzero_batter_fields(player: dict[str, Any]) -> list[str]:
    pairs = [
        ("ab", "타수"),
        ("run", "득점"),
        ("hit", "안타"),
        ("rbi", "타점"),
        ("hr", "홈런"),
        ("bb", "볼넷"),
        ("so", "삼진"),
        ("kk", "삼진"),
        ("sb", "도루"),
    ]
    fields: list[str] = []
    seen_labels: set[str] = set()
    for key, label in pairs:
        if label in seen_labels:
            continue
        value = _to_int(player.get(key))
        if value:
            fields.append(f"{value}{label}")
            seen_labels.add(label)
    return fields


def _plate_result_label(event: RelayEvent | None, player: dict[str, Any]) -> str:
    if event is None:
        return ""
    text = event.text.split(":", 1)[1].strip() if ":" in event.text else event.text
    label = ""
    if "홈런" in text:
        label = "홈런"
    elif "3루타" in text:
        label = "3루타"
    elif "2루타" in text:
        label = "땅볼 2루타" if "땅볼" in text else "2루타"
    elif "1루타" in text or "안타" in text:
        label = "안타"
    elif "볼넷" in text or "고의4구" in text:
        label = "볼넷"
    elif "사구" in text or "몸에 맞는 볼" in text or "몸에맞는볼" in text:
        label = "사구"
    elif "희생플라이" in text:
        label = "희생플라이"
    elif "희생번트" in text:
        label = "희생번트"
    elif "삼진" in text:
        label = "삼진"
    elif "병살타" in text:
        label = "병살타"
    elif "땅볼" in text:
        label = "땅볼"
    elif "플라이" in text or "뜬공" in text:
        label = "플라이"
    elif "직선타" in text:
        label = "직선타"
    elif "도루" in text and "실패" not in text:
        label = "도루"

    rbi = _to_int(player.get("rbi"))
    if label and rbi:
        return f"{label}(타점{rbi})"
    return label


def format_kia_record(
    record: dict[str, Any],
    team_code: str = KIA_CODE,
    milestones: list[str] | None = None,
) -> str:
    info = record.get("gameInfo", {})
    side = "home" if info.get("hCode") == team_code else "away"
    team_name = info.get("hName" if side == "home" else "aName", "KIA")
    batters = record.get("battersBoxscore", {}).get(side, [])
    pitchers = record.get("pitchersBoxscore", {}).get(side, [])
    team_batting = record.get("battersBoxscore", {}).get(f"{side}Total", {})
    team_pitching = record.get("teamPitchingBoxscore", {}).get(side, {})

    lines = [
        f"{team_name} 경기 기록",
        f"타격 합계: {' '.join(_nonzero_batter_fields(team_batting)) or '기록 없음'}",
        "",
        "타자",
    ]

    for player in batters:
        lines.append(format_batter_summary_stats(player))

    lines += [
        "",
        f"투구 합계: {_pitcher_stats_text(team_pitching)}",
        "",
        "투수",
    ]

    for player in pitchers:
        decision = _pitching_decision(player) or _pitching_result_for_player(record, player)
        result = f" {decision}" if decision else ""
        lines.append(f"{player.get('name', '-')}{result} | {_pitcher_stats_text(player)}")

    if milestones:
        lines += ["", "오늘의 기록", *milestones]

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
        stats = " ".join(_nonzero_batter_fields(player))
        if stats:
            highlights.append(f"{player.get('name')}: {stats}")

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


def format_monthly_team_records(
    games: list[dict[str, Any]],
    team_names: dict[str, str],
    as_of: date,
) -> str:
    records = {
        code: {"code": code, "name": name, "wins": 0, "losses": 0, "draws": 0}
        for code, name in team_names.items()
    }
    counted_games = 0

    for game in games:
        status = str(game.get("statusCode") or game.get("gameStatus") or "").upper()
        if status not in {"RESULT", "END", "ENDED", "FINAL"}:
            continue
        away_code = str(game.get("awayTeamCode") or game.get("aCode") or "")
        home_code = str(game.get("homeTeamCode") or game.get("hCode") or "")
        if away_code not in records or home_code not in records:
            continue
        winner = str(game.get("winner") or "").upper()
        if winner == "AWAY":
            records[away_code]["wins"] += 1
            records[home_code]["losses"] += 1
        elif winner == "HOME":
            records[home_code]["wins"] += 1
            records[away_code]["losses"] += 1
        elif winner == "DRAW":
            records[away_code]["draws"] += 1
            records[home_code]["draws"] += 1
        else:
            continue
        counted_games += 1

    lines = [
        f"{as_of.year} KBO {as_of.month}월 월간 성적",
        f"{as_of.month}월 {as_of.day}일 종료 경기 기준",
    ]
    if not counted_games:
        return "\n".join([*lines, "이번 달 종료된 KBO 경기가 없습니다."])

    rows = []
    for record in records.values():
        decisions = int(record["wins"]) + int(record["losses"])
        record["winRate"] = Fraction(int(record["wins"]), decisions) if decisions else Fraction(0, 1)
        rows.append(record)
    rows.sort(
        key=lambda record: (
            record["winRate"],
            int(record["wins"]),
            int(record["draws"]),
        ),
        reverse=True,
    )

    rank = 0
    previous_rate: Fraction | None = None
    for index, record in enumerate(rows, start=1):
        win_rate = record["winRate"]
        if previous_rate is None or win_rate != previous_rate:
            rank = index
            previous_rate = win_rate
        lines.append(
            f"{rank}. {record['name']} | "
            f"{record['wins']}승 {record['losses']}패 {record['draws']}무 | "
            f"승률 {float(win_rate):.3f}"
        )
    return "\n".join(lines)


def format_daily_game_results(
    results: list[dict[str, Any]],
    title: str = "오늘의 KBO 경기 결과",
) -> str:
    lines = [title]
    for result in results:
        away_name = result.get("awayName", "원정")
        home_name = result.get("homeName", "홈")
        if result.get("cancelled"):
            lines.append(f"{away_name} vs {home_name} | 경기취소")
            continue
        status_text = str(result.get("statusText") or "").strip()
        suffix = f" ({status_text})" if status_text else ""
        away_score = result.get("awayScore")
        home_score = result.get("homeScore")
        if away_score is None and home_score is None:
            lines.append(f"{away_name} vs {home_name}{suffix}")
            continue
        lines.append(
            f"{away_name} {away_score if away_score is not None else '-'} : "
            f"{home_score if home_score is not None else '-'} {home_name}{suffix}"
        )
    return "\n".join(lines)


TEAM_RECORD_OPTIONS = {
    "타율": {"field": "offenseHra", "direction": "desc", "suffix": "", "precision": 3, "extra": "offenseHit", "extra_label": "안타"},
    "평균자책": {"field": "defenseEra", "direction": "asc", "suffix": "", "extra": "defenseInning", "extra_label": "이닝"},
    "홈런": {"field": "offenseHr", "direction": "desc", "suffix": "개", "extra": "offenseSlg", "extra_label": "장타율"},
    "안타": {"field": "offenseHit", "direction": "desc", "suffix": "개", "extra": "offenseHra", "extra_label": "타율"},
    "도루": {"field": "offenseSb", "direction": "desc", "suffix": "개", "extra": "offenseHra", "extra_label": "타율"},
    "득점": {"field": "offenseRun", "direction": "desc", "suffix": "점", "extra": "offenseHra", "extra_label": "타율"},
    "실점": {"field": "defenseR", "direction": "asc", "suffix": "점", "extra": "defenseEra", "extra_label": "평균자책"},
}

HITTER_RECORD_OPTIONS = {
    "타율": {"field": "hitterHra", "direction": "desc", "suffix": "", "precision": 3, "qualified": True},
    "홈런": {"field": "hitterHr", "direction": "desc", "suffix": "개"},
    "타점": {"field": "hitterRbi", "direction": "desc", "suffix": "점"},
    "도루": {"field": "hitterSb", "direction": "desc", "suffix": "개"},
    "OPS": {"field": "hitterOps", "direction": "desc", "suffix": "", "precision": 3, "qualified": True},
    "WAR": {"field": "hitterWar", "direction": "desc", "suffix": ""},
}

PITCHER_RECORD_OPTIONS = {
    "승": {"field": "pitcherWin", "direction": "desc", "suffix": "승"},
    "평균자책": {"field": "pitcherEra", "direction": "asc", "suffix": "", "precision": 2, "qualified": True},
    "탈삼진": {"field": "pitcherKk", "direction": "desc", "suffix": "개"},
    "세이브": {"field": "pitcherSave", "direction": "desc", "suffix": "개"},
    "WHIP": {"field": "pitcherWhip", "direction": "asc", "suffix": "", "precision": 2, "qualified": True},
    "WAR": {"field": "pitcherWar", "direction": "desc", "suffix": ""},
}


def record_options_message(record_type: str) -> str:
    labels = _record_option_labels(record_type)
    title = {"team": "팀기록", "hitter": "타자기록", "pitcher": "투수기록"}.get(record_type, "기록")
    lines = [f"{title} 중 알고 싶은게 있으세요?"]
    lines.extend(f"{idx}. {label}" for idx, label in enumerate(labels, 1))
    if record_type in {"hitter", "pitcher"}:
        lines += ["", f"개인 기록: /{title} 선수명"]
    return "\n".join(lines)


def resolve_record_option(record_type: str, text: str) -> str | None:
    query = text.strip().upper()
    for label in _record_option_labels(record_type):
        if query == label.upper() or query == f"{label.upper()} 알려줘":
            return label
    return None


def format_team_record_stats(rows: list[dict[str, Any]], option: str) -> str:
    config = TEAM_RECORD_OPTIONS[option]
    field = str(config["field"])
    reverse = config.get("direction") == "desc"
    sorted_rows = sorted(rows, key=lambda row: _to_float(row.get(field)), reverse=reverse)
    ranked = _rank_rows(sorted_rows, field)

    lines = [f"KBO 팀 기록 | {option}"]
    for rank, row in ranked:
        value = _format_record_value(row.get(field), str(config.get("suffix", "")), config.get("precision"))
        extra = _format_extra_record(row, str(config.get("extra", "")), str(config.get("extra_label", "")))
        lines.append(f"{rank}. {row.get('teamName', '-')} | {value}{extra}")
    return "\n".join(lines)


def format_player_record_stats(rows: list[dict[str, Any]], record_type: str, option: str, limit: int = 10) -> str:
    options = HITTER_RECORD_OPTIONS if record_type == "hitter" else PITCHER_RECORD_OPTIONS
    config = options[option]
    field = str(config["field"])
    reverse = config.get("direction") == "desc"
    if config.get("qualified"):
        rows = [row for row in rows if _is_qualified(row)]
    sorted_rows = sorted(rows, key=lambda row: _to_float(row.get(field)), reverse=reverse)[:limit]
    ranked = _rank_rows(sorted_rows, field)
    title = "타자 기록" if record_type == "hitter" else "투수 기록"

    lines = [f"KBO {title} | {option} TOP {limit}"]
    for rank, row in ranked:
        value = _format_record_value(row.get(field), str(config.get("suffix", "")), config.get("precision"))
        lines.append(f"{rank}. {row.get('playerName', '-')} ({row.get('teamName', '-')}) | {value}")
    return "\n".join(lines)


def kia_news_articles(*article_lists: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    articles: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for article_list in article_lists:
        for article in article_list:
            if not _is_kia_article(article):
                continue
            key = (str(article.get("oid") or article.get("officeId") or ""), str(article.get("aid") or article.get("articleId") or ""))
            if key in seen:
                continue
            seen.add(key)
            articles.append(article)
            if len(articles) >= limit:
                return articles
    return articles


def format_kia_news_articles(articles: list[dict[str, Any]]) -> str:
    lines = ["KIA 주요 기사"]
    for idx, article in enumerate(articles, 1):
        title = str(article.get("title") or "-")
        source = str(article.get("sourceName") or article.get("officeName") or "").strip()
        source_text = f" ({source})" if source else ""
        lines.append(f"{idx}. {title}{source_text}")
        lines.append(_article_url(article))
    return "\n".join(lines)


def format_kia_highlight(highlight: dict[str, Any]) -> str:
    return "\n".join(
        [
            "KIA 경기 하이라이트",
            str(highlight.get("title") or "-"),
            str(highlight.get("url") or "https://www.youtube.com/@tvingsports"),
        ]
    )


def naver_game_shorts(
    videos: list[dict[str, Any]],
    game_id: str,
    limit: int = 5,
) -> list[dict[str, str]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for video in videos:
        media_id = str(video.get("masterVid") or "").strip()
        if (
            not media_id
            or media_id in seen
            or str(video.get("gameId") or "") != game_id
            or str(video.get("videoType") or "").lower() != "shortform"
        ):
            continue
        seen.add(media_id)
        candidates.append(video)

    candidates.sort(
        key=lambda video: (
            "kia" in str(video.get("seasonName") or "").lower(),
            _to_float(video.get("hit")),
        ),
        reverse=True,
    )

    shorts: list[dict[str, str]] = []
    for video in candidates[:limit]:
        short_form = video.get("shortForm") if isinstance(video.get("shortForm"), dict) else {}
        service_type = str(short_form.get("serviceType") or video.get("serviceType") or "SPORTS")
        rec_type = str(short_form.get("recType") or "SPORTS")
        media_id = str(video.get("masterVid"))
        query = urlencode(
            {
                "mediaId": media_id,
                "serviceType": service_type,
                "recType": rec_type,
                "includePost": "false",
                "recId": f"rec-game-{game_id}",
            }
        )
        shorts.append(
            {
                "mediaId": media_id,
                "title": str(video.get("title") or "KIA 경기 쇼츠"),
                "url": f"https://m.naver.com/shorts/?{query}",
            }
        )
    return shorts


def format_naver_short(short: dict[str, str]) -> str:
    return "\n".join(
        [
            f"네이버 쇼츠 | {short.get('title') or 'KIA 경기'}",
            str(short.get("url") or ""),
        ]
    )


def format_pitching_decisions(record: dict[str, Any], away_name: str, home_name: str, away_score: int, home_score: int) -> str:
    by_result = _collect_pitching_decisions(record)
    decisions = by_result["승"] + by_result["패"] + by_result["세"] + by_result["홀"]
    return "\n".join(["중계 | 경기종료", f"{away_name} {away_score} : {home_score} {home_name}", *decisions])


def format_pitching_decision_update(record: dict[str, Any]) -> str:
    by_result = _collect_pitching_decisions(record)
    decisions = by_result["승"] + by_result["패"] + by_result["세"] + by_result["홀"]
    return "\n".join(["투수 판정 업데이트", *decisions])


def pitching_decisions_ready(record: dict[str, Any], away_score: int, home_score: int) -> bool:
    if away_score == home_score:
        return True
    by_result = _collect_pitching_decisions(record)
    return bool(by_result["승"] and by_result["패"])


def _collect_pitching_decisions(record: dict[str, Any]) -> dict[str, list[str]]:
    pitchers = record.get("pitchersBoxscore", {})
    by_result: dict[str, list[str]] = {"승": [], "패": [], "세": [], "홀": []}
    seen: set[tuple[str, str]] = set()
    for player in record.get("pitchingResult", []):
        _append_pitching_decision(by_result, seen, player)
    for side in ("away", "home"):
        for player in pitchers.get(side, []):
            _append_pitching_decision(by_result, seen, player)
    return by_result


def _append_pitching_decision(
    by_result: dict[str, list[str]],
    seen: set[tuple[str, str]],
    player: dict[str, Any],
) -> None:
    result = _pitching_decision(player)
    if not result:
        return
    name = str(player.get("name") or "-")
    key = (result, name)
    if key in seen:
        return
    seen.add(key)
    if result == "승":
        by_result["승"].append(f"승리투수: {name}")
    elif result == "패":
        by_result["패"].append(f"패전투수: {name}")
    elif result == "세":
        by_result["세"].append(f"세이브: {name}")
    elif result == "홀":
        by_result["홀"].append(f"홀드: {name}")


def _pitching_result_for_player(record: dict[str, Any], player: dict[str, Any]) -> str:
    pcode = str(player.get("pcode") or player.get("pCode") or "")
    name = str(player.get("name") or "")
    for result in record.get("pitchingResult", []):
        result_pcode = str(result.get("pCode") or result.get("pcode") or "")
        result_name = str(result.get("name") or "")
        if (pcode and result_pcode == pcode) or (name and result_name == name):
            return _pitching_decision(result)
    return ""


def _pitching_decision(player: dict[str, Any]) -> str:
    for key in ("wls", "result", "winLoseSave", "wlsName"):
        value = str(player.get(key) or "").strip()
        if value in {"승", "패", "세", "홀"}:
            return value
        if value in {"W", "WIN", "승리"}:
            return "승"
        if value in {"L", "LOSE", "LOSS", "패전"}:
            return "패"
        if value in {"S", "SAVE", "세이브"}:
            return "세"
        if value in {"H", "HOLD", "홀드"}:
            return "홀"
    return ""


def player_photo_url(event: RelayEvent) -> str | None:
    player = event.batter_record or event.player_info or {}
    pcode = player.get("pcode") or player.get("playerCode") or player.get("pCode")
    if not pcode:
        pcode = event.player_code or event.batter_code
    if not pcode:
        return None
    return player_image_url(pcode)


def pitcher_photo_url(event: RelayEvent) -> str | None:
    pcode = (event.current_state or {}).get("pitcher")
    if not pcode:
        return None
    return player_image_url(pcode)


def player_image_url(pcode: Any, cache_key: Any = None) -> str:
    code = str(pcode)
    version = re.sub(r"\D", "", str(cache_key or date.today().isoformat()))
    override = PLAYER_IMAGE_OVERRIDES.get(code)
    if override:
        separator = "&" if "?" in override else "?"
        return f"{override}{separator}v={version}"
    return f"{PLAYER_IMAGE.format(pcode=code)}&v={version}"


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


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _record_option_labels(record_type: str) -> list[str]:
    if record_type == "team":
        return list(TEAM_RECORD_OPTIONS)
    if record_type == "hitter":
        return list(HITTER_RECORD_OPTIONS)
    if record_type == "pitcher":
        return list(PITCHER_RECORD_OPTIONS)
    return []


def _rank_rows(rows: list[dict[str, Any]], field: str) -> list[tuple[int, dict[str, Any]]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    previous_value: Any = object()
    current_rank = 0
    for index, row in enumerate(rows, 1):
        value = row.get(field)
        if index == 1 or value != previous_value:
            current_rank = index
            previous_value = value
        ranked.append((current_rank, row))
    return ranked


def _is_qualified(row: dict[str, Any]) -> bool:
    value = row.get("isQualified")
    if isinstance(value, bool):
        return value
    return str(value or "").strip().upper() in {"Y", "TRUE", "1"}


def _is_kia_article(article: dict[str, Any]) -> bool:
    title = str(article.get("title") or "")
    return "KIA" in title.upper() or "기아" in title


def _article_url(article: dict[str, Any]) -> str:
    oid = article.get("oid") or article.get("officeId")
    aid = article.get("aid") or article.get("articleId")
    section = article.get("sportsSection") or "kbaseball"
    if oid and aid:
        return f"https://m.sports.naver.com/{section}/article/{oid}/{aid}"
    return "https://m.sports.naver.com/kbaseball/news"


def _format_record_value(value: Any, suffix: str = "", precision: Any = None) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        if precision is not None:
            text = f"{value:.{int(precision)}f}"
        else:
            text = f"{value:.3f}" if abs(value) < 1 else f"{value:.2f}"
            text = text.rstrip("0").rstrip(".") if "." in text and abs(value) >= 1 else text
    else:
        text = str(value)
    return f"{text}{suffix}"


def _format_extra_record(row: dict[str, Any], field: str, label: str) -> str:
    if not field or not label:
        return ""
    value = row.get(field)
    if value in (None, ""):
        return ""
    return f" | {label} {_format_record_value(value)}"


def _format_innings(value: Any) -> str:
    raw = str(value or "0")
    if "." not in raw:
        return raw
    whole, fraction = raw.split(".", 1)
    suffix = {"0": "", "1": " ⅓", "2": " ⅔"}.get(fraction[:1], f".{fraction}")
    return f"{whole}{suffix}" if suffix else whole


def _fmt_avg(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        if value < 1:
            return f"{value:.3f}"
        return f"{value:.2f}"
    return str(value)


def _compact_avg(value: Any) -> str:
    avg = _fmt_avg(value)
    if avg.startswith("0."):
        return avg[1:]
    return avg


def _pitcher_stats_text(player: dict[str, Any]) -> str:
    fields = []
    inn = player.get("inn")
    if inn not in (None, "", "-"):
        fields.append(f"{_format_innings(inn)}이닝")
    for key, label in (
        ("hit", "피안타"),
        ("r", "실점"),
        ("er", "자책"),
        ("bbhp", "사사구"),
        ("kk", "삼진"),
    ):
        value = _to_int(player.get(key))
        if value:
            fields.append(f"{value}{label}")
    era = player.get("era")
    if era not in (None, ""):
        fields.append(f"ERA {era}")
    return " ".join(fields) or "기록 없음"
