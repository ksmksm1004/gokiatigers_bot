from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


KBO_BASE_URL = "https://www.koreabaseball.com/"
KBO_PLAYER_SEARCH_URL = urljoin(KBO_BASE_URL, "ws/Controls.asmx/GetSearchPlayer")
KBO_SCHEDULE_URL = urljoin(KBO_BASE_URL, "ws/Schedule.asmx/GetScheduleList")
KBO_EXPECTED_RECORD_LIST_URL = urljoin(KBO_BASE_URL, "Record/Expectation/DailyList.aspx")
KBO_FIRST_TEAM_SERIES_IDS = "0,9,6,3,4,5,7"


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


@dataclass(frozen=True)
class KBOExpectedRecord:
    subject: str
    achievement: str
    remaining: Fraction
    rank: str
    stat: str
    raw_text: str


@dataclass(frozen=True)
class KBOOCRLine:
    x: float
    y: float
    width: float
    height: float
    text: str

    @property
    def mid_y(self) -> float:
        return self.y + self.height / 2


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


class _ExpectedRecordListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = str(dict(attrs).get("href") or "")
        if "DailyView.aspx" in href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.entries.append((self._href, _clean_text("".join(self._text))))
            self._href = ""
            self._text = []


class _ExpectedRecordViewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.image_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self.image_href:
            return
        href = str(dict(attrs).get("href") or "")
        if "FileDownload.ashx" in href and ".png" in href.lower():
            self.image_href = href


class KBOPlayerClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self._expected_record_cache: dict[tuple[date, str], list[KBOExpectedRecord]] = {}
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
                "srIdList": KBO_FIRST_TEAM_SERIES_IDS,
                "seasonId": int(season),
                "gameMonth": "",
                "teamId": team_id,
            },
        )
        return parse_schedule_results(response.json(), season)

    def game_milestones(self, record: dict[str, Any], team_code: str = "HT") -> list[str]:
        info = record.get("gameInfo") or {}
        game_date = _game_date(info.get("gdate"))
        side = "home" if str(info.get("hCode") or "") == team_code else "away"
        pitchers = record.get("pitchersBoxscore", {}).get(side, [])
        starter_name = str((pitchers[0] if pitchers else {}).get("name") or "").strip()
        if game_date is None or not starter_name:
            return []

        candidates = self.expected_record_candidates(game_date, starter_name)
        return evaluate_achieved_milestones(record, candidates, team_code)

    def expected_record_candidates(
        self,
        game_date: date,
        starter_name: str,
    ) -> list[KBOExpectedRecord]:
        cache_key = (game_date, _normalize_name(starter_name))
        if cache_key in self._expected_record_cache:
            return self._expected_record_cache[cache_key]

        response = self._request("get", KBO_EXPECTED_RECORD_LIST_URL)
        list_parser = _ExpectedRecordListParser()
        list_parser.feed(_prepare_kbo_html(response.text))
        date_token = game_date.strftime("%Y%m%d")
        entries = [entry for entry in list_parser.entries if date_token in entry[1]]

        for view_href, _title in entries:
            view_response = self._request("get", urljoin(KBO_EXPECTED_RECORD_LIST_URL, view_href))
            view_parser = _ExpectedRecordViewParser()
            view_parser.feed(_prepare_kbo_html(view_response.text))
            if not view_parser.image_href:
                continue
            image_response = self._request(
                "get",
                urljoin(KBO_BASE_URL, view_parser.image_href),
            )
            ocr_output = recognize_kbo_expected_record_image(image_response.content)
            found, candidates = expected_records_for_team(ocr_output, [starter_name])
            if found:
                self._expected_record_cache[cache_key] = candidates
                return candidates

        self._expected_record_cache[cache_key] = []
        return []

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


_EXPECTED_STAT_ALIASES = (
    ("경기출장", "games"),
    ("탈삼진", "strikeouts"),
    ("세이브", "saves"),
    ("홀드", "holds"),
    ("4사구", "walk_hbp"),
    ("사사구", "walk_hbp"),
    ("2루타", "doubles"),
    ("3루타", "triples"),
    ("홈런", "home_runs"),
    ("타점", "rbi"),
    ("득점", "runs"),
    ("도루", "stolen_bases"),
    ("안타", "hits"),
    ("루타", "total_bases"),
    ("타석", "plate_appearances"),
    ("타수", "at_bats"),
    ("4구", "walks"),
    ("볼넷", "walks"),
    ("이닝", "innings"),
    ("승리", "wins"),
    ("패전", "losses"),
    ("승", "wins"),
    ("패", "losses"),
)


def recognize_kbo_expected_record_image(image: bytes) -> str:
    if sys.platform != "darwin":
        raise RuntimeError("KBO expected-record OCR requires macOS Vision")
    executable = _kbo_ocr_executable()
    with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
        image_file.write(image)
        image_file.flush()
        completed = subprocess.run(
            [str(executable), image_file.name],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
        )
    return completed.stdout


def _kbo_ocr_executable() -> Path:
    source = Path(__file__).with_name("kbo_record_ocr.m")
    if not source.exists():
        raise RuntimeError(f"KBO OCR source is missing: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:12]
    executable = Path(tempfile.gettempdir()) / f"gokiatigers-kbo-record-ocr-{digest}"
    if executable.exists() and os.access(executable, os.X_OK):
        return executable

    temporary = executable.with_name(f"{executable.name}.{os.getpid()}")
    module_cache = Path(tempfile.gettempdir()) / "gokiatigers-clang-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["CLANG_MODULE_CACHE_PATH"] = str(module_cache)
    try:
        subprocess.run(
            [
                "/usr/bin/clang",
                "-O2",
                "-fobjc-arc",
                "-fblocks",
                "-framework",
                "Foundation",
                "-framework",
                "AppKit",
                "-framework",
                "Vision",
                str(source),
                "-o",
                str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=environment,
        )
        temporary.replace(executable)
    finally:
        if temporary.exists():
            temporary.unlink()
    return executable


def parse_kbo_ocr_lines(output: str) -> list[KBOOCRLine]:
    lines: list[KBOOCRLine] = []
    for raw_line in output.splitlines():
        parts = raw_line.split("\t", 4)
        if len(parts) != 5:
            continue
        try:
            x, y, width, height = (float(value) for value in parts[:4])
        except ValueError:
            continue
        text = _clean_text(parts[4])
        if text:
            lines.append(KBOOCRLine(x, y, width, height, text))
    return lines


def parse_expected_record_candidate(text: str) -> KBOExpectedRecord | None:
    normalized = _clean_text(text).replace("−", "-")
    match = re.fullmatch(
        r"(?P<body>.+?)\(\s*-?\s*(?P<remaining>\d+(?:\.\d+)?(?:\s+\d+/\d+)?)\s*\)\s*"
        r"(?P<rank>첫\s*번째|\d+\s*번째)",
        normalized,
    )
    if not match:
        return None

    body = match.group("body").strip().lstrip("★*# ")
    body = re.sub(r"(?<=\d)\.\s+(?=4(?:구|사구))", " ", body)
    if re.match(r"^(?:KIA(?:\s*타이거즈)?\s+)?\d", body, re.IGNORECASE):
        subject = ""
        achievement = re.sub(r"^KIA(?:\s*타이거즈)?\s+", "", body, flags=re.IGNORECASE)
    else:
        parts = body.split(" ", 1)
        if len(parts) != 2:
            return None
        subject = parts[0].lstrip("★*#")
        achievement = parts[1]

    stat = _expected_record_stat(achievement)
    remaining = _parse_fraction(match.group("remaining"))
    if not stat or remaining is None or remaining <= 0:
        return None
    return KBOExpectedRecord(
        subject=subject,
        achievement=achievement,
        remaining=remaining,
        rank=_clean_text(match.group("rank")),
        stat=stat,
        raw_text=normalized,
    )


def expected_records_for_team(
    ocr_output: str,
    anchor_names: list[str],
) -> tuple[bool, list[KBOExpectedRecord]]:
    lines = parse_kbo_ocr_lines(ocr_output)
    anchor = _find_team_anchor(lines, anchor_names)
    if anchor is None:
        return False, []

    team_rows = [
        line
        for line in lines
        if re.fullmatch(r"\d+승\d+패\d+무", "".join(line.text.split()))
    ]
    if team_rows:
        target_row = min(team_rows, key=lambda line: abs(line.mid_y - anchor.mid_y))
        ordered_rows = sorted(team_rows, key=lambda line: line.mid_y, reverse=True)
        index = ordered_rows.index(target_row)
        upper = (
            (ordered_rows[index - 1].mid_y + target_row.mid_y) / 2
            if index > 0
            else target_row.mid_y + 0.055
        ) + 0.008
        lower = (
            (ordered_rows[index + 1].mid_y + target_row.mid_y) / 2
            if index + 1 < len(ordered_rows)
            else target_row.mid_y - 0.055
        ) - 0.008
    else:
        upper = anchor.mid_y + 0.055
        lower = anchor.mid_y - 0.055

    candidates: list[KBOExpectedRecord] = []
    seen: set[str] = set()
    for line in lines:
        if not lower <= line.mid_y <= upper:
            continue
        candidate = parse_expected_record_candidate(line.text)
        if candidate is None or candidate.raw_text in seen:
            continue
        seen.add(candidate.raw_text)
        candidates.append(candidate)
    return True, candidates


def evaluate_achieved_milestones(
    record: dict[str, Any],
    candidates: list[KBOExpectedRecord],
    team_code: str = "HT",
) -> list[str]:
    messages: list[str] = []
    for candidate in candidates:
        increment = _game_record_increment(record, candidate, team_code)
        if increment < candidate.remaining:
            continue
        message = format_achieved_milestone(candidate)
        if message not in messages:
            messages.append(message)
    return messages


def format_achieved_milestone(candidate: KBOExpectedRecord) -> str:
    rank = "".join(candidate.rank.split())
    if candidate.subject:
        order = "KBO 최초" if rank == "첫번째" else f"KBO 역대 {rank}"
        return f"{candidate.subject} {order} {candidate.achievement}"

    achievement = candidate.achievement
    for label, _stat in sorted(_EXPECTED_STAT_ALIASES, key=lambda item: len(item[0]), reverse=True):
        achievement = re.sub(rf"(?<=\d)(?={re.escape(label)})", " ", achievement)
    order = "KBO 최초" if rank == "첫번째" else f"KBO 역대 {rank}"
    return f"KIA 타이거즈 {order} 팀 {achievement}"


def _find_team_anchor(lines: list[KBOOCRLine], names: list[str]) -> KBOOCRLine | None:
    for index, name in enumerate(names):
        normalized_name = _normalize_name(name)
        if not normalized_name:
            continue
        matches = [
            line
            for line in lines
            if normalized_name in _normalize_name(line.text) and line.x < 0.88
        ]
        if not matches:
            continue
        if index == 0:
            starter_column = [line for line in matches if 0.24 <= line.x <= 0.36]
            if starter_column:
                return min(starter_column, key=lambda line: len(line.text))
            continue
        return min(matches, key=lambda line: len(line.text))
    return None


def _expected_record_stat(achievement: str) -> str:
    matches: list[tuple[int, int, str]] = []
    for label, stat in _EXPECTED_STAT_ALIASES:
        for match in re.finditer(re.escape(label), achievement):
            matches.append((match.end(), len(label), stat))
    return max(matches, default=(-1, -1, ""))[2]


def _game_record_increment(
    record: dict[str, Any],
    candidate: KBOExpectedRecord,
    team_code: str,
) -> Fraction:
    info = record.get("gameInfo") or {}
    side = "home" if str(info.get("hCode") or "") == team_code else "away"
    batters = record.get("battersBoxscore", {}).get(side, [])
    pitchers = record.get("pitchersBoxscore", {}).get(side, [])

    if not candidate.subject:
        return _team_stat_increment(record, side, candidate.stat)

    normalized_subject = _normalize_name(candidate.subject)
    batter = next(
        (player for player in batters if _normalize_name(player.get("name", "")) == normalized_subject),
        None,
    )
    pitcher = next(
        (player for player in pitchers if _normalize_name(player.get("name", "")) == normalized_subject),
        None,
    )
    if pitcher is not None and candidate.stat in {
        "strikeouts",
        "innings",
        "wins",
        "losses",
        "saves",
        "holds",
    }:
        return _pitcher_stat_increment(record, pitcher, candidate.stat)
    if batter is not None:
        return _batter_stat_increment(batter, candidate.stat)
    if pitcher is not None and candidate.stat == "games":
        return Fraction(1)
    return Fraction(0)


def _team_stat_increment(record: dict[str, Any], side: str, stat: str) -> Fraction:
    batter_box = record.get("battersBoxscore", {})
    batters = batter_box.get(side, [])
    batting = batter_box.get(f"{side}Total", {})
    pitching = record.get("teamPitchingBoxscore", {}).get(side, {})
    if stat == "strikeouts":
        return _fraction_from_value(pitching.get("kk") or pitching.get("so"))
    if stat == "innings":
        return _innings_fraction(pitching.get("inn"))
    if stat == "total_bases":
        return sum((_batter_stat_increment(player, stat) for player in batters), Fraction(0))
    if stat == "walk_hbp":
        return sum((_batter_stat_increment(player, stat) for player in batters), Fraction(0))
    if stat in {"wins", "losses"}:
        away_runs = _to_int_or_none(batter_box.get("awayTotal", {}).get("run")) or 0
        home_runs = _to_int_or_none(batter_box.get("homeTotal", {}).get("run")) or 0
        won = (side == "away" and away_runs > home_runs) or (side == "home" and home_runs > away_runs)
        lost = away_runs != home_runs and not won
        return Fraction(int(won if stat == "wins" else lost))
    if stat in {"saves", "holds"}:
        pitchers = record.get("pitchersBoxscore", {}).get(side, [])
        return sum((_pitcher_stat_increment(record, player, stat) for player in pitchers), Fraction(0))

    fields = {
        "games": None,
        "plate_appearances": "pa",
        "at_bats": "ab",
        "hits": "hit",
        "home_runs": "hr",
        "rbi": "rbi",
        "runs": "run",
        "stolen_bases": "sb",
        "walks": "bb",
    }
    if stat == "games":
        return Fraction(1)
    field = fields.get(stat)
    if field:
        return _fraction_from_value(batting.get(field))
    if stat in {"doubles", "triples"}:
        return sum((_batter_stat_increment(player, stat) for player in batters), Fraction(0))
    return Fraction(0)


def _batter_stat_increment(player: dict[str, Any], stat: str) -> Fraction:
    results = _batter_results(player)
    doubles = sum(1 for result in results if "2루타" in result or re.search(r"[좌우중]+2$", result))
    triples = sum(1 for result in results if "3루타" in result or re.search(r"[좌우중]+3$", result))
    hit_by_pitch = sum(1 for result in results if "사구" in result or "몸에 맞" in result)
    values = {
        "games": 1,
        "plate_appearances": player.get("pa"),
        "at_bats": player.get("ab"),
        "hits": player.get("hit"),
        "doubles": doubles,
        "triples": triples,
        "home_runs": player.get("hr"),
        "rbi": player.get("rbi"),
        "runs": player.get("run"),
        "stolen_bases": player.get("sb"),
        "walks": player.get("bb"),
        "walk_hbp": (_to_int_or_none(player.get("bb")) or 0) + hit_by_pitch,
    }
    if stat == "total_bases":
        hits = _to_int_or_none(player.get("hit")) or 0
        home_runs = _to_int_or_none(player.get("hr")) or 0
        return Fraction(hits + doubles + 2 * triples + 3 * home_runs)
    return _fraction_from_value(values.get(stat))


def _pitcher_stat_increment(
    record: dict[str, Any],
    player: dict[str, Any],
    stat: str,
) -> Fraction:
    if stat == "games":
        return Fraction(1)
    if stat == "strikeouts":
        return _fraction_from_value(player.get("kk") or player.get("so"))
    if stat == "innings":
        return _innings_fraction(player.get("inn"))
    decision = _pitching_decision(record, player)
    expected = {"wins": "승", "losses": "패", "saves": "세", "holds": "홀"}.get(stat)
    return Fraction(int(bool(expected and decision == expected)))


def _pitching_decision(record: dict[str, Any], player: dict[str, Any]) -> str:
    player_code = str(player.get("pcode") or player.get("pCode") or "")
    player_name = _normalize_name(player.get("name", ""))
    rows = [player, *(record.get("pitchingResult") or [])]
    for row in rows:
        row_code = str(row.get("pcode") or row.get("pCode") or "")
        row_name = _normalize_name(row.get("name", ""))
        if row is not player and not (
            (player_code and player_code == row_code) or (player_name and player_name == row_name)
        ):
            continue
        for key in ("wls", "result", "winLoseSave", "wlsName"):
            value = str(row.get(key) or "").strip().upper()
            if value in {"승", "W", "WIN", "승리"}:
                return "승"
            if value in {"패", "L", "LOSE", "LOSS", "패전"}:
                return "패"
            if value in {"세", "S", "SAVE", "세이브"}:
                return "세"
            if value in {"홀", "H", "HOLD", "홀드"}:
                return "홀"
    return ""


def _batter_results(player: dict[str, Any]) -> list[str]:
    return [
        str(player.get(f"inn{inning}") or "").strip()
        for inning in range(1, 26)
        if str(player.get(f"inn{inning}") or "").strip()
    ]


def _parse_fraction(value: Any) -> Fraction | None:
    raw = str(value or "").strip().replace("⅓", "1/3").replace("⅔", "2/3")
    if not raw:
        return None
    try:
        if " " in raw:
            whole, fraction = raw.split(None, 1)
            return Fraction(whole) + Fraction(fraction)
        return Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return None


def _fraction_from_value(value: Any) -> Fraction:
    parsed = _parse_fraction(value)
    return parsed if parsed is not None else Fraction(0)


def _innings_fraction(value: Any) -> Fraction:
    raw = str(value or "").strip()
    mixed = _parse_fraction(raw)
    if " " in raw or "/" in raw or "⅓" in raw or "⅔" in raw:
        return mixed if mixed is not None else Fraction(0)
    if "." in raw:
        whole, outs = raw.split(".", 1)
        if outs[:1] in {"1", "2"}:
            try:
                return Fraction(int(whole) * 3 + int(outs[:1]), 3)
            except ValueError:
                return Fraction(0)
    return mixed if mixed is not None else Fraction(0)


def _game_date(value: Any) -> date | None:
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


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
        result = _game_result_for_team(game, team_name)
        if result == "승":
            wins += 1
        elif result == "패":
            losses += 1
        else:
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


def format_recent_series_results(
    games: list[KBOGameResult],
    team_name: str = "KIA",
    max_series: int = 4,
) -> str:
    series: list[dict[str, Any]] = []
    selected = sorted(
        (game for game in games if team_name in {game.away_team, game.home_team}),
        key=lambda game: game.game_date,
    )
    for game in selected:
        opponent = game.home_team if game.away_team == team_name else game.away_team
        previous_game = series[-1]["games"][-1] if series else None
        if (
            series
            and series[-1]["opponent"] == opponent
            and previous_game is not None
            and (game.game_date - previous_game.game_date).days <= 4
        ):
            series[-1]["games"].append(game)
        else:
            series.append({"opponent": opponent, "games": [game]})

    lines = [f"{team_name} 최근 경기"]
    recent = series[-max(0, max_series) :] if max_series > 0 else []
    if not recent:
        return "\n\n".join([lines[0], "완료된 경기가 없습니다."])

    for group in recent:
        lines += ["", f"vs {group['opponent']}"]
        for game in group["games"]:
            lines.append(
                f"{game.game_date.month}/{game.game_date.day} "
                f"{game.away_score}:{game.home_score} {_game_result_for_team(game, team_name)}"
            )
    return "\n".join(lines)


def _game_result_for_team(game: KBOGameResult, team_name: str) -> str:
    team_score = game.away_score if game.away_team == team_name else game.home_score
    opponent_score = game.home_score if game.away_team == team_name else game.away_score
    if team_score > opponent_score:
        return "승"
    if team_score < opponent_score:
        return "패"
    return "무"


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
