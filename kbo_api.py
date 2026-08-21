from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import requests


KBO_BASE_URL = "https://www.koreabaseball.com/"
KBO_PLAYER_SEARCH_URL = urljoin(KBO_BASE_URL, "ws/Controls.asmx/GetSearchPlayer")
KBO_SCHEDULE_URL = urljoin(KBO_BASE_URL, "ws/Schedule.asmx/GetScheduleList")


@dataclass(frozen=True)
class KBOPlayerCandidate:
    player_id: str
    name: str
    team: str
    position: str
    back_number: str
    bats_throws: str
    record_type: str


@dataclass
class KBOPlayerRecord:
    player_id: str
    record_type: str
    season: str = ""
    team: str = ""
    name: str = ""
    birthday: str = ""
    height_weight: str = ""
    salary: str = ""
    back_number: str = ""
    position: str = ""
    photo_url: str = ""
    stats: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class KBOGameResult:
    game_date: date
    away_team: str
    away_score: int
    home_score: int
    home_team: str


@dataclass
class _ParsedTable:
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


class _PlayerPageParser(HTMLParser):
    PROFILE_FIELDS = {
        "lblName": "name",
        "lblBackNo": "back_number",
        "lblBirthday": "birthday",
        "lblPosition": "position",
        "lblHeightWeight": "height_weight",
        "lblSalary": "salary",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.profile: dict[str, str] = {}
        self.photo_url = ""
        self.team = ""
        self.season = ""
        self.tables: list[_ParsedTable] = []
        self._profile_key: str | None = None
        self._profile_text: list[str] = []
        self._team_open = False
        self._team_text: list[str] = []
        self._heading_open = False
        self._heading_text: list[str] = []
        self._table: _ParsedTable | None = None
        self._table_section = ""
        self._row: list[str] | None = None
        self._cell_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        element_id = str(attributes.get("id") or "")

        if tag == "span":
            for suffix, key in self.PROFILE_FIELDS.items():
                if element_id.endswith(suffix):
                    self._profile_key = key
                    self._profile_text = []
                    break
        elif tag == "img" and "playerProfile_img" in element_id:
            self.photo_url = str(attributes.get("src") or "")
        elif tag == "h4" and element_id == "h4Team":
            self._team_open = True
            self._team_text = []
        elif tag == "h6":
            self._heading_open = True
            self._heading_text = []
        elif tag == "table":
            self._table = _ParsedTable()
            self._table_section = ""
        elif self._table is not None and tag in {"thead", "tbody", "tfoot"}:
            self._table_section = tag
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._table is not None and self._row is not None and tag in {"th", "td"}:
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._profile_key is not None:
            self._profile_text.append(data)
        if self._team_open:
            self._team_text.append(data)
        if self._heading_open:
            self._heading_text.append(data)
        if self._cell_text is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._profile_key is not None:
            self.profile[self._profile_key] = _clean_text("".join(self._profile_text))
            self._profile_key = None
            self._profile_text = []
        elif tag == "h4" and self._team_open:
            self.team = _clean_text("".join(self._team_text))
            self._team_open = False
            self._team_text = []
        elif tag == "h6" and self._heading_open:
            heading = _clean_text("".join(self._heading_text))
            match = re.search(r"(20\d{2})\s*성적", heading)
            if match and not self.season:
                self.season = match.group(1)
            self._heading_open = False
            self._heading_text = []
        elif tag in {"th", "td"} and self._cell_text is not None and self._row is not None:
            self._row.append(_clean_text("".join(self._cell_text)))
            self._cell_text = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            if self._table_section == "thead" and self._row:
                self._table.headers.extend(self._row)
            elif self._table_section == "tbody" and self._row:
                self._table.rows.append(self._row)
            self._row = None
            self._cell_text = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None
            self._table_section = ""


class _FragmentTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = _clean_text(data)
        if value:
            self.parts.append(value)


class KBOPlayerClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Referer": KBO_BASE_URL,
            }
        )

    def search_players(self, name: str, record_type: str) -> list[KBOPlayerCandidate]:
        response = self._request("post", KBO_PLAYER_SEARCH_URL, data={"name": name})
        return parse_player_candidates(response.json(), name, record_type)

    def player_record(self, player_id: str, record_type: str) -> KBOPlayerRecord:
        detail_kind = "HitterDetail" if record_type == "hitter" else "PitcherDetail"
        path = f"Record/Player/{detail_kind}/Basic.aspx?playerId={player_id}"
        basic_html = self._request("get", urljoin(KBO_BASE_URL, path)).text
        record = parse_player_basic_page(basic_html, player_id, record_type)
        if not record.name:
            raise ValueError(f"KBO player page did not contain a player profile: {player_id}")

        if record_type == "pitcher" and record.season and "HBP" not in record.stats:
            total_path = f"Record/Player/{detail_kind}/Total.aspx?playerId={player_id}"
            try:
                total_html = self._request("get", urljoin(KBO_BASE_URL, total_path)).text
                hbp = parse_pitcher_season_hbp(total_html, record.season)
                if hbp is not None:
                    record.stats["HBP"] = str(hbp)
            except (requests.RequestException, ValueError):
                logging.warning("KBO pitcher HBP lookup failed for player %s.", player_id, exc_info=True)
        return record

    def team_schedule_results(self, season: int, team_id: str = "HT") -> list[KBOGameResult]:
        response = self._request(
            "post",
            KBO_SCHEDULE_URL,
            data={
                "leId": 1,
                "srIdList": "0,9,6",
                "seasonId": int(season),
                "gameMonth": "",
                "teamId": team_id,
            },
        )
        return parse_schedule_results(response.json(), season)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        for attempt in range(3):
            try:
                response = self.session.request(method, url, timeout=10, **kwargs)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    logging.warning("KBO returned %s for %s. Retrying.", response.status_code, url)
                    time.sleep(0.5 * (2**attempt))
                    continue
                response.raise_for_status()
                return response
            except requests.HTTPError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= 2:
                    raise
                logging.warning("KBO request failed for %s. Retrying.", url)
                time.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"KBO request failed: {url}")


def parse_player_candidates(
    payload: dict[str, Any],
    query: str,
    record_type: str,
) -> list[KBOPlayerCandidate]:
    if str(payload.get("code") or "") != "100":
        return []
    normalized_query = _normalize_name(query)
    candidates: list[KBOPlayerCandidate] = []
    for player in payload.get("now") or []:
        name = str(player.get("P_NM") or "").strip()
        link = str(player.get("P_LINK") or "")
        candidate_type = _record_type_from_link(link)
        if _normalize_name(name) != normalized_query or candidate_type != record_type:
            continue
        candidates.append(
            KBOPlayerCandidate(
                player_id=str(player.get("P_ID") or ""),
                name=name,
                team=str(player.get("T_NM") or "-").strip(),
                position=str(player.get("POS_NO") or "-").strip(),
                back_number=str(player.get("BACK_NO") or "-").strip(),
                bats_throws=str(player.get("P_TYPE") or "-").strip(),
                record_type=record_type,
            )
        )
    return [candidate for candidate in candidates if candidate.player_id]


def parse_schedule_results(payload: dict[str, Any], season: int) -> list[KBOGameResult]:
    games: list[KBOGameResult] = []
    for item in payload.get("rows") or []:
        cells = item.get("row") or []
        play_html = next(
            (str(cell.get("Text") or "") for cell in cells if cell.get("Class") == "play"),
            "",
        )
        review_html = next(
            (
                str(cell.get("Text") or "")
                for cell in cells
                if "section=REVIEW" in str(cell.get("Text") or "")
            ),
            "",
        )
        if not play_html or not review_html:
            continue

        date_match = re.search(r"gameDate=(\d{8})", review_html)
        if not date_match:
            continue
        try:
            game_date = datetime.strptime(date_match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if game_date.year != int(season):
            continue

        parser = _FragmentTextParser()
        parser.feed(play_html)
        if len(parser.parts) < 5:
            continue
        away_team = parser.parts[0]
        home_team = parser.parts[-1]
        scores = [part for part in parser.parts[1:-1] if re.fullmatch(r"\d+", part)]
        if len(scores) != 2:
            continue
        games.append(
            KBOGameResult(
                game_date=game_date,
                away_team=away_team,
                away_score=int(scores[0]),
                home_score=int(scores[1]),
                home_team=home_team,
            )
        )
    return sorted(games, key=lambda game: game.game_date)


def format_head_to_head_results(
    games: list[KBOGameResult],
    opponent_name: str,
    team_name: str = "KIA",
) -> str:
    selected = sorted(
        (
            game
            for game in games
            if {game.away_team, game.home_team} == {team_name, opponent_name}
        ),
        key=lambda game: game.game_date,
    )
    wins = draws = losses = 0
    rows: list[str] = []
    for game in selected:
        team_score = game.away_score if game.away_team == team_name else game.home_score
        opponent_score = game.home_score if game.away_team == team_name else game.away_score
        if team_score > opponent_score:
            result = "승"
            wins += 1
        elif team_score < opponent_score:
            result = "패"
            losses += 1
        else:
            result = "무"
            draws += 1
        rows.append(
            f"{game.game_date.month}/{game.game_date.day} "
            f"{game.away_score}:{game.home_score} {result}"
        )

    lines = [
        f"{team_name} vs {opponent_name} 상대 전적",
        "",
        f"{team_name} {wins}승 {draws}무 {losses}패",
    ]
    if rows:
        lines.extend(rows)
    else:
        lines += ["", "아직 완료된 경기가 없습니다."]
    return "\n".join(lines)


def parse_player_basic_page(html: str, player_id: str, record_type: str) -> KBOPlayerRecord:
    parser = _PlayerPageParser()
    parser.feed(_prepare_kbo_html(html))
    required_tables = (
        (
            {"팀명", "AVG", "AB", "H", "HR", "RBI"},
            {"BB", "HBP", "SO", "SLG", "OBP", "OPS"},
        )
        if record_type == "hitter"
        else (
            {"팀명", "ERA", "W", "L", "SV", "HLD", "IP", "H", "HR"},
            {"BB", "SO", "R", "ER", "WHIP"},
        )
    )

    stats: dict[str, str] = {}
    for required_headers in required_tables:
        table = _find_table(parser.tables, required_headers)
        if table is not None:
            stats.update(_summary_row(table))

    return KBOPlayerRecord(
        player_id=str(player_id),
        record_type=record_type,
        season=parser.season,
        team=parser.team,
        name=parser.profile.get("name", ""),
        birthday=parser.profile.get("birthday", ""),
        height_weight=parser.profile.get("height_weight", ""),
        salary=parser.profile.get("salary", ""),
        back_number=parser.profile.get("back_number", ""),
        position=parser.profile.get("position", ""),
        photo_url=urljoin(KBO_BASE_URL, parser.photo_url) if parser.photo_url else "",
        stats=stats,
    )


def parse_pitcher_season_hbp(html: str, season: str) -> int | None:
    parser = _PlayerPageParser()
    parser.feed(_prepare_kbo_html(html))
    table = _find_table(parser.tables, {"연도", "팀명", "ERA", "BB", "HBP", "SO"})
    if table is None:
        return None

    rows = [_row_dict(table, row) for row in table.rows]
    season_rows = [row for row in rows if row.get("연도") == str(season)]
    if not season_rows:
        return None
    combined = next((row for row in season_rows if row.get("팀명") in {"합계", "TOTAL"}), None)
    if combined is not None:
        return _to_int_or_none(combined.get("HBP"))

    values = [_to_int_or_none(row.get("HBP")) for row in season_rows]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def format_player_record(record: KBOPlayerRecord) -> str:
    title = "타자" if record.record_type == "hitter" else "투수"
    team = _short_team_name(record.team)
    player_heading = record.name or "-"
    if team:
        player_heading += f" ({team})"

    back_number = record.back_number or "-"
    if back_number != "-" and not back_number.lower().startswith("no."):
        back_number = f"No.{back_number}"
    lines = [
        f"KBO {title} 기록 | {record.season or '현재 시즌'}",
        player_heading,
        f"생년월일: {record.birthday or '-'}",
        f"신장/체중: {record.height_weight or '-'}",
        f"연봉: {record.salary or '-'}",
        f"등번호: {back_number}",
        f"포지션: {record.position or '-'}",
    ]

    if not record.stats:
        lines += ["", "정규시즌 기록이 없습니다."]
        return "\n".join(lines)

    stats = record.stats
    walks = _sum_stats(stats, "BB", "HBP")
    lines.append("")
    if record.record_type == "hitter":
        lines.extend(
            [
                f"타율 {_rate(stats, 'AVG')} | 타수 {_stat(stats, 'AB')} | 안타 {_stat(stats, 'H')}",
                f"2루타 {_stat(stats, '2B')} | 3루타 {_stat(stats, '3B')} | 홈런 {_stat(stats, 'HR')}",
                f"타점 {_stat(stats, 'RBI')} | 득점 {_stat(stats, 'R')} | 도루 {_stat(stats, 'SB')}",
                f"사사구 {walks} | 삼진 {_stat(stats, 'SO')}",
                f"출루율 {_rate(stats, 'OBP')} | 장타율 {_rate(stats, 'SLG')} | OPS {_rate(stats, 'OPS')}",
            ]
        )
    else:
        lines.extend(
            [
                f"평균자책 {_stat(stats, 'ERA')} | 이닝 {_stat(stats, 'IP')}",
                f"승 {_stat(stats, 'W')} | 패 {_stat(stats, 'L')} | 세이브 {_stat(stats, 'SV')} | 홀드 {_stat(stats, 'HLD')}",
                f"탈삼진 {_stat(stats, 'SO')} | 피안타 {_stat(stats, 'H')} | 피홈런 {_stat(stats, 'HR')}",
                f"사사구 {walks} | 실점 {_stat(stats, 'R')} | 자책점 {_stat(stats, 'ER')}",
                f"WHIP {_stat(stats, 'WHIP')}",
            ]
        )
    return "\n".join(lines)


def _find_table(tables: list[_ParsedTable], required_headers: set[str]) -> _ParsedTable | None:
    return next((table for table in tables if required_headers.issubset(set(table.headers))), None)


def _summary_row(table: _ParsedTable) -> dict[str, str]:
    if not table.rows:
        return {}
    row = next((item for item in table.rows if item and item[0] in {"합계", "TOTAL"}), table.rows[-1])
    return _row_dict(table, row)


def _row_dict(table: _ParsedTable, row: list[str]) -> dict[str, str]:
    return {header: value for header, value in zip(table.headers, row)}


def _record_type_from_link(link: str) -> str | None:
    lowered = link.lower()
    if "/hitterdetail/" in lowered:
        return "hitter"
    if "/pitcherdetail/" in lowered:
        return "pitcher"
    return None


def _normalize_name(value: str) -> str:
    return "".join(str(value).split())


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _prepare_kbo_html(value: str) -> str:
    # KBO uses an em dash where an HTML conditional-comment double hyphen is expected.
    return value.replace("<!\u2014", "<!--").replace("\u2014>", "-->")


def _short_team_name(value: str) -> str:
    team = _clean_text(value)
    aliases = {
        "KIA 타이거즈": "KIA",
        "두산 베어스": "두산",
        "롯데 자이언츠": "롯데",
        "삼성 라이온즈": "삼성",
        "한화 이글스": "한화",
        "키움 히어로즈": "키움",
        "KT 위즈": "KT",
        "LG 트윈스": "LG",
        "NC 다이노스": "NC",
        "SSG 랜더스": "SSG",
    }
    return aliases.get(team, team)


def _stat(stats: dict[str, str], key: str) -> str:
    value = str(stats.get(key) or "").strip()
    return value or "-"


def _rate(stats: dict[str, str], key: str) -> str:
    value = _stat(stats, key)
    return value[1:] if value.startswith("0.") else value


def _sum_stats(stats: dict[str, str], *keys: str) -> str:
    values = [_to_int_or_none(stats.get(key)) for key in keys]
    if any(value is None for value in values):
        return "-"
    return str(sum(value for value in values if value is not None))


def _to_int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
