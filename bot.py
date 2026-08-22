from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from kbo_api import (
    KBOPlayerCandidate,
    KBOPlayerClient,
    format_head_to_head_results,
    format_player_record,
    format_recent_series_results,
)
from lineup_image import render_defensive_lineup_image
from naver_api import NaverSportsClient, unwrap
from naver_weather import NaverWeatherClient
from parser import (
    changed_pitcher_lines,
    current_player_record,
    expected_batters_message,
    find_previous_plate_event,
    format_daily_game_results,
    format_game_highlights,
    format_kia_highlight,
    format_kia_news_articles,
    format_monthly_team_records,
    format_naver_short,
    format_player_record_stats,
    format_kia_record,
    format_pitching_decision_update,
    format_pitching_decisions,
    format_preview,
    format_team_record_stats,
    format_team_rankings,
    HITTER_RECORD_OPTIONS,
    PITCHER_RECORD_OPTIONS,
    TEAM_RECORD_OPTIONS,
    format_relay_event_with_context,
    half_key,
    has_starting_lineups,
    is_game_over,
    kia_news_articles,
    naver_game_shorts,
    is_batter_result_event,
    is_kia_batting,
    is_kia_batter_event,
    is_kia_pitching,
    kia_half_summary_message,
    lineup_media_items,
    parse_game_summary,
    parse_relay_events,
    pitching_decisions_ready,
    plate_result_label,
    plate_result_history,
    player_photo_url,
    pitcher_photo_url,
    previous_half_pitcher_lines,
    previous_half_result_labels,
    record_options_message,
    resolve_record_option,
    should_send_relay_event,
    team_in_game,
)
from telegram import TelegramBot
from youtube import find_tving_kia_highlight


BOT_COMMANDS = [
    (("/라인업", "/lineup"), "오늘 KIA 경기 선발 라인업 확인"),
    (("/일정", "/schedule"), "KIA 향후 경기 일정 확인"),
    (("/최근경기", "/recentgames"), "KIA 최근 4개 시리즈 결과 확인"),
    (("/스코어", "/score"), "오늘 KBO 전체 경기 현재 스코어 확인"),
    (("/상대전적", "/headtohead"), "KIA 상대 팀별 시즌 전적 확인"),
    (("/기록", "/record"), "오늘 KIA 경기 기록 확인"),
    (("/순위", "/rank"), "KBO 팀 순위 확인"),
    (("/월간성적", "/monthlyrecord"), "이번 달 KBO 팀 성적 확인"),
    (("/팀기록", "/teamrecord"), "KBO 팀 주요 기록 확인"),
    (("/타자기록", "/hitterrecord"), "KBO 타자 TOP 10·개인 기록 확인"),
    (("/투수기록", "/pitcherrecord"), "KBO 투수 TOP 10·개인 기록 확인"),
    (("/뉴스", "/news"), "KIA 주요 기사 확인"),
    (("/날씨", "/weather"), "오늘 KIA 경기 구장 날씨 확인"),
    (("/gg",), "관리자: 오늘 경기 중계 중단 후 종료 결과만 받기"),
    (("/re",), "관리자: 중단한 오늘 경기 중계 재개"),
    (("/도움말", "/명령어", "/help", "/start"), "사용 가능한 명령어 보기"),
]

TELEGRAM_MENU_COMMANDS = [
    ("/lineup", "오늘 KIA 경기 선발 라인업 확인"),
    ("/schedule", "KIA 향후 경기 일정 확인"),
    ("/recentgames", "KIA 최근 4개 시리즈 결과"),
    ("/score", "오늘 KBO 전체 경기 현재 스코어"),
    ("/headtohead", "KIA 상대 팀별 시즌 전적 확인"),
    ("/record", "오늘 KIA 경기 기록 확인"),
    ("/rank", "KBO 팀 순위 확인"),
    ("/monthlyrecord", "이번 달 KBO 팀 성적 확인"),
    ("/teamrecord", "KBO 팀 주요 기록 확인"),
    ("/hitterrecord", "KBO 타자 TOP 10·개인 기록"),
    ("/pitcherrecord", "KBO 투수 TOP 10·개인 기록"),
    ("/news", "KIA 주요 기사 확인"),
    ("/weather", "오늘 KIA 경기 구장 날씨"),
    ("/gg", "관리자: 오늘 경기 중계 중단"),
    ("/re", "관리자: 오늘 경기 중계 재개"),
    ("/help", "사용 가능한 명령어 보기"),
]

TEAM_NAMES = {
    "HT": "KIA",
    "LT": "롯데",
    "SK": "SSG",
    "SS": "삼성",
    "LG": "LG",
    "OB": "두산",
    "HH": "한화",
    "NC": "NC",
    "WO": "키움",
    "KT": "KT",
}

TEAM_QUERY_ALIASES = {
    "기아": "HT",
    "기아타이거즈": "HT",
    "kia타이거즈": "HT",
    "엘지": "LG",
    "lg트윈스": "LG",
    "한화이글스": "HH",
    "ssg랜더스": "SK",
    "쓱": "SK",
    "삼성라이온즈": "SS",
    "nc다이노스": "NC",
    "엔씨": "NC",
    "kt위즈": "KT",
    "케이티": "KT",
    "롯데자이언츠": "LT",
    "두산베어스": "OB",
    "키움히어로즈": "WO",
}

TEAM_PITCHER_LABELS = {
    "HT": "KIA",
    "LT": "롯",
    "SK": "SSG",
    "SS": "삼",
    "LG": "LG",
    "OB": "두",
    "HH": "한",
    "NC": "NC",
    "WO": "키",
    "KT": "KT",
}

TERMINAL_SCHEDULE_STATUS = {"RESULT", "END", "ENDED", "CANCEL", "CANCELED", "CANCELLED"}
PITCHING_DECISION_POLL_SECONDS = 60
KIA_HIGHLIGHT_RETRY_MINUTES = 10
KIA_HIGHLIGHT_MAX_ATTEMPTS = 12
KIA_SHORTS_LIMIT = 5
KIA_SHORTS_RETRY_MINUTES = 10
KIA_SHORTS_MAX_ATTEMPTS = 12


def opponent_pitching_context(home_code: str, away_code: str, team_code: str) -> tuple[str, str] | None:
    if away_code == team_code:
        return "home", home_code
    if home_code == team_code:
        return "away", away_code
    return None


def setup_logging(settings: Settings) -> None:
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(settings.log_path, encoding="utf-8"), logging.StreamHandler()],
    )


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def current_game_id(state: dict[str, Any]) -> str | None:
    if state.get("gameId"):
        return str(state["gameId"])
    scheduled = state.get("scheduledGame") or {}
    if scheduled.get("gameId"):
        return str(scheduled["gameId"])
    if state.get("detailedGameId"):
        return str(state["detailedGameId"])
    return None


def score_from_game(game: dict[str, Any], side: str) -> int:
    keys = (
        ("aScore", "awayScore", "awayTeamScore", "away_score")
        if side == "away"
        else ("hScore", "homeScore", "homeTeamScore", "home_score")
    )
    for key in keys:
        value = game.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def final_score_from_record(record: dict[str, Any], fallback_away: int, fallback_home: int) -> tuple[int, int]:
    batting = record.get("battersBoxscore", {})
    away_total = batting.get("awayTotal", {})
    home_total = batting.get("homeTotal", {})
    away = _optional_int(away_total.get("run"))
    home = _optional_int(home_total.get("run"))

    info = record.get("gameInfo", {})
    if away is None:
        away = _optional_score_from_game(info, "away")
    if home is None:
        home = _optional_score_from_game(info, "home")

    return (
        fallback_away if away is None else away,
        fallback_home if home is None else home,
    )


def _optional_score_from_game(game: dict[str, Any], side: str) -> int | None:
    keys = (
        ("aScore", "awayScore", "awayTeamScore", "away_score")
        if side == "away"
        else ("hScore", "homeScore", "homeTeamScore", "home_score")
    )
    for key in keys:
        value = _optional_int(game.get(key))
        if value is not None:
            return value
    return None


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def merge_game_status(base: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in update.items():
        if value not in (None, ""):
            merged[key] = value
    return merged


def find_today_kia_game(client: NaverSportsClient, settings: Settings, now: datetime) -> dict[str, Any] | None:
    if settings.naver_game_id:
        preview = unwrap(client.preview(settings.naver_game_id), "previewData")
        game = preview.get("gameInfo", {})
        game["gameId"] = settings.naver_game_id
        return game

    games = client.games_on(now.date())
    for game in games:
        if team_in_game(game, settings.team_code):
            return game
    return None


def get_cached_today_game(
    client: NaverSportsClient,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
) -> dict[str, Any] | None:
    today = now.date().isoformat()
    if state.get("scheduleDate") == today and state.get("scheduledGame"):
        return state["scheduledGame"]

    next_check = _parse_dt(state.get("nextScheduleCheckAt"))
    if state.get("scheduleDate") == today and next_check and now < next_check:
        return None

    game = find_today_kia_game(client, settings, now)
    state["scheduleDate"] = today
    if game:
        state["scheduledGame"] = game
        state.pop("nextScheduleCheckAt", None)
    else:
        state.pop("scheduledGame", None)
        state["nextScheduleCheckAt"] = next_schedule_lookup_at(now).isoformat()
    save_state(settings.state_path, state)
    return game


def get_detailed_game(
    client: NaverSportsClient,
    settings: Settings,
    state: dict[str, Any],
    game: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    game_id = str(game.get("gameId") or "")
    if not game_id:
        return game
    cached = state.get("detailedGame")
    if not force and state.get("detailedGameId") == game_id and cached:
        return cached
    if settings.naver_game_id:
        return game
    preview = unwrap(client.preview(game_id), "previewData")
    detail = preview.get("gameInfo", {}).copy()
    detail["gameId"] = game_id
    state["detailedGameId"] = game_id
    state["detailedGame"] = detail
    save_state(settings.state_path, state)
    return detail


def should_poll_game(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return True
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return start_at - timedelta(minutes=settings.pregame_minutes) <= now <= start_at + timedelta(hours=5, minutes=settings.postgame_minutes)


def seconds_until_pregame(summary, settings: Settings, now: datetime) -> int:
    if summary.start_at is None:
        return settings.idle_poll_seconds
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    seconds = int((start_at - timedelta(minutes=settings.pregame_minutes) - now).total_seconds())
    return max(seconds, settings.idle_poll_seconds)


def should_check_game_status(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return True
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return now >= start_at - timedelta(minutes=settings.pregame_minutes)


def is_before_game_start(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return False
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return now < start_at


def is_after_game_start(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return True
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return now >= start_at


def is_cancelled_game(game: dict[str, Any]) -> bool:
    cancel_flag = str(game.get("cancelFlag") or "").upper()
    status = str(game.get("statusCode") or "").upper()
    return bool(game.get("cancel")) or cancel_flag == "Y" or status in {"CANCEL", "CANCELED", "CANCELLED"}


def send_cancelled_once(
    client: NaverSportsClient,
    weather_client: NaverWeatherClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    summary,
    game: dict[str, Any],
) -> None:
    if state.get("cancelSentGameId") == summary.game_id:
        return
    stadium = summary.stadium or str(game.get("stadium") or "")
    reason = resolve_cancellation_reason(
        client,
        weather_client,
        summary.game_id,
        stadium,
        game,
    )
    lines = [
        "KIA 경기 취소",
        f"{summary.away_name or game.get('aName', '원정')} vs {summary.home_name or game.get('hName', '홈')}",
        f"{stadium} {reason}".strip(),
    ]
    telegram.send_message("\n".join(line for line in lines if line))
    state["cancelSentGameId"] = summary.game_id
    state["gameCancelled"] = True
    cancelled_ids = set(state.get("cancelledGameIds", []))
    cancelled_ids.add(summary.game_id)
    state["cancelledGameIds"] = sorted(cancelled_ids)
    save_state(settings.state_path, state)


def resolve_cancellation_reason(
    client: NaverSportsClient,
    weather_client: NaverWeatherClient,
    game_id: str,
    stadium: str,
    game: dict[str, Any],
) -> str:
    reason = _explicit_cancellation_reason(game)
    detailed_game: dict[str, Any] = {}
    if not reason:
        try:
            detailed_game = unwrap(client.game_detail(game_id), "game")
            reason = _explicit_cancellation_reason(detailed_game)
        except Exception:
            logging.exception("Failed to fetch cancellation details for %s.", game_id)
    if reason:
        return reason

    try:
        conditions = weather_client.stadium_current_conditions(stadium)
    except Exception:
        logging.exception("Failed to fetch cancellation weather for %s.", game_id)
        conditions = {}

    weather_text = str(conditions.get("wetrTxt") or "")
    rain_amount = conditions.get("oneHourRainAmt", conditions.get("rainAmt"))
    fallback_weather = detailed_game.get("weatherInfo") or game.get("weatherInfo") or {}
    if not weather_text and isinstance(fallback_weather, dict):
        weather_text = str(fallback_weather.get("weather") or "")

    if _is_rain_weather(weather_text) or _positive_rain_amount(rain_amount):
        return "우천 취소"
    if "맑음" in weather_text or _zero_rain_amount(rain_amount):
        return "폭염 취소"
    return "경기 취소"


def _explicit_cancellation_reason(game: dict[str, Any]) -> str:
    keys = (
        "cancelReason",
        "cancellationReason",
        "reason",
        "statusInfo",
        "info",
        "generalTitle",
        "generalInfo3",
        "title",
    )
    for key in keys:
        text = str(game.get(key) or "").strip()
        normalized = text.replace(" ", "")
        if "폭염" in normalized:
            return "폭염 취소"
        if any(word in normalized for word in ("우천", "강우", "호우")):
            return "우천 취소"
        if normalized and normalized not in {"경기취소", "취소"} and "취소" in normalized:
            return text
    return ""


def _is_rain_weather(weather_text: str) -> bool:
    return any(word in weather_text for word in ("비", "소나기", "뇌우", "눈"))


def _rain_amount_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def _positive_rain_amount(value: Any) -> bool:
    amount = _rain_amount_number(value)
    return amount is not None and amount > 0


def _zero_rain_amount(value: Any) -> bool:
    amount = _rain_amount_number(value)
    return amount == 0


def send_preview_once(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> bool:
    if state.get("previewSentGameId") == game_id:
        return True
    try:
        preview = unwrap(client.preview(game_id), "previewData")
    except Exception:
        state["nextPreviewCheckAt"] = next_hour_at(datetime.now(settings.timezone)).isoformat()
        save_state(settings.state_path, state)
        logging.exception("Preview check failed for %s. Will retry hourly.", game_id)
        return False
    if not has_preview_content(preview):
        state["nextPreviewCheckAt"] = next_hour_at(datetime.now(settings.timezone)).isoformat()
        save_state(settings.state_path, state)
        logging.info("Preview content is not ready for %s. Next check: %s", game_id, state["nextPreviewCheckAt"])
        return False
    telegram.send_message(format_preview(preview, game_id, settings.team_code))
    state["previewSentGameId"] = game_id
    state.pop("nextPreviewCheckAt", None)
    save_state(settings.state_path, state)
    return True


def has_preview_content(preview: dict[str, Any]) -> bool:
    return any(
        preview.get(key)
        for key in (
            "awayStandings",
            "homeStandings",
            "awayStarter",
            "homeStarter",
            "awayTeamPreviousGames",
            "homeTeamPreviousGames",
            "seasonVsResult",
        )
    )


def next_hour_at(now: datetime) -> datetime:
    base = now.replace(minute=0, second=0, microsecond=0)
    if base <= now:
        base += timedelta(hours=1)
    return base


def next_schedule_lookup_at(now: datetime) -> datetime:
    for hour in (9, 12, 15, 17, 18, 19, 20, 21):
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now < candidate:
            return candidate
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)


def should_check_preview(state: dict[str, Any], game_id: str, now: datetime) -> bool:
    if state.get("previewSentGameId") == game_id:
        return False
    next_check = _parse_dt(state.get("nextPreviewCheckAt"))
    return next_check is None or now >= next_check


def send_lineup_once(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    if (
        state.get("lineupSentGameId") == game_id
        and state.get("lineupAwaySentGameId") == game_id
        and state.get("lineupHomeSentGameId") == game_id
        and state.get("lineupDefenseSentGameId") == game_id
    ):
        return
    if state.get("lineupSentGameId") == game_id:
        state.pop("lineupSentGameId", None)

    preview = unwrap(client.preview(game_id), "previewData")
    if not has_starting_lineups(preview):
        return

    info = preview.get("gameInfo", {})
    away_name = info.get("aName", "원정")
    home_name = info.get("hName", "홈")
    kia_side = lineup_side_for_team(preview, settings.team_code)

    if state.get("lineupHeaderSentGameId") != game_id:
        state["lineupHeaderSentGameId"] = game_id
        save_state(settings.state_path, state)
        telegram.send_message(f"선발 라인업\n{away_name} vs {home_name}")

    for side, label in (("away", away_name), ("home", home_name)):
        sent_key = f"lineup{side.title()}SentGameId"
        if state.get(sent_key) == game_id:
            continue

        items = lineup_media_items(preview, side)
        if not items:
            continue
        try:
            telegram.send_media_group(items)
            state[sent_key] = game_id
            save_state(settings.state_path, state)
            logging.info("Sent %s lineup for %s.", label, game_id)
        except Exception:
            logging.exception("Failed to send %s lineup for %s. It will not be retried automatically.", label, game_id)

    if kia_side and state.get("lineupDefenseSentGameId") != game_id:
        try:
            if send_defensive_lineup_image(telegram, preview, kia_side):
                state["lineupDefenseSentGameId"] = game_id
                save_state(settings.state_path, state)
        except Exception:
            logging.exception("Failed to send KIA defensive lineup for %s.", game_id)

    if (
        state.get("lineupAwaySentGameId") == game_id
        and state.get("lineupHomeSentGameId") == game_id
        and (not kia_side or state.get("lineupDefenseSentGameId") == game_id)
    ):
        state["lineupSentGameId"] = game_id
    save_state(settings.state_path, state)


def send_lineup(
    client: NaverSportsClient,
    telegram: TelegramBot,
    game_id: str,
) -> None:
    preview = unwrap(client.preview(game_id), "previewData")
    if not has_starting_lineups(preview):
        telegram.send_message("라인업 발표 전입니다.")
        return

    info = preview.get("gameInfo", {})
    away_name = info.get("aName", "원정")
    home_name = info.get("hName", "홈")
    telegram.send_message(f"선발 라인업\n{away_name} vs {home_name}")
    for side in ("away", "home"):
        items = lineup_media_items(preview, side)
        if items:
            telegram.send_media_group(items)
            time.sleep(3)
    kia_side = lineup_side_for_team(preview)
    if kia_side:
        send_defensive_lineup_image(telegram, preview, kia_side)


def lineup_side_for_team(preview: dict[str, Any], team_code: str = "HT") -> str | None:
    info = preview.get("gameInfo") or {}
    if str(info.get("aCode") or info.get("awayTeamCode") or "") == team_code:
        return "away"
    if str(info.get("hCode") or info.get("homeTeamCode") or "") == team_code:
        return "home"
    if team_code == "HT":
        if str(info.get("aName") or "") == "KIA":
            return "away"
        if str(info.get("hName") or "") == "KIA":
            return "home"
    return None


def send_defensive_lineup_image(
    telegram: TelegramBot,
    preview: dict[str, Any],
    side: str,
) -> bool:
    image = render_defensive_lineup_image(preview, side)
    if not image:
        return False
    game_date = re.sub(r"\D", "", str((preview.get("gameInfo") or {}).get("gdate") or ""))
    filename = f"kia-defense-{game_date or 'lineup'}.png"
    telegram.send_photo_bytes(image, "KIA 선발 수비", filename)
    return True


def send_kia_record(
    client: NaverSportsClient,
    telegram: TelegramBot,
    game_id: str,
    team_code: str,
) -> None:
    record = unwrap(client.record(game_id), "recordData")
    if not record:
        telegram.send_message("경기 기록은 아직 제공되지 않았습니다.")
        return
    telegram.send_message(format_kia_record(record, team_code))


def send_team_rankings(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
) -> None:
    now = datetime.now(settings.timezone)
    rankings = unwrap(client.team_rankings(now.year), "seasonTeamStats")
    last_ten = unwrap(client.last_ten_games(now.year), "seasonTeamLastTenGameStats")
    telegram.send_message(format_team_rankings({"seasonTeamStats": rankings}, {"seasonTeamLastTenGameStats": last_ten}))


def send_monthly_team_records(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(settings.timezone)
    games = client.games_in_month(current.date())
    telegram.send_message(format_monthly_team_records(games, TEAM_NAMES, current.date()))


def resolve_opponent_team(query: str) -> tuple[str, str] | None:
    normalized = re.sub(r"\s+", "", str(query or "")).lower()
    if not normalized:
        return None
    for code, name in TEAM_NAMES.items():
        if normalized in {code.lower(), re.sub(r"\s+", "", name).lower()}:
            return code, name
    code = TEAM_QUERY_ALIASES.get(normalized)
    if not code:
        return None
    return code, TEAM_NAMES[code]


def head_to_head_usage_message(query: str = "") -> str:
    teams = ", ".join(TEAM_NAMES[code] for code in TEAM_NAMES if code != "HT")
    if query:
        return f"'{query}' 팀을 찾지 못했습니다.\n사용법: /상대전적 키움\n팀: {teams}"
    return f"상대 팀을 입력해주세요.\n사용법: /상대전적 키움\n팀: {teams}"


def send_head_to_head_record(
    telegram: TelegramBot,
    settings: Settings,
    opponent_query: str,
    kbo_client: KBOPlayerClient | None = None,
    now: datetime | None = None,
) -> None:
    opponent = resolve_opponent_team(opponent_query)
    if not opponent:
        telegram.send_message(head_to_head_usage_message(opponent_query))
        return
    opponent_code, opponent_name = opponent
    if opponent_code == settings.team_code:
        telegram.send_message("KIA 이외의 상대 팀을 입력해주세요.")
        return

    current = now or datetime.now(settings.timezone)
    games = (kbo_client or KBOPlayerClient()).team_schedule_results(current.year, settings.team_code)
    team_name = TEAM_NAMES.get(settings.team_code, settings.team_code)
    telegram.send_message(format_head_to_head_results(games, opponent_name, team_name))


def send_recent_games(
    telegram: TelegramBot,
    settings: Settings,
    kbo_client: KBOPlayerClient | None = None,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(settings.timezone)
    games = (kbo_client or KBOPlayerClient()).team_schedule_results(
        current.year,
        settings.team_code,
    )
    team_name = TEAM_NAMES.get(settings.team_code, settings.team_code)
    telegram.send_message(format_recent_series_results(games, team_name, max_series=4))


def pending_record_command(state: dict[str, Any], chat_id: str) -> str:
    pending = state.get("pendingRecordCommands") or {}
    return str(pending.get(str(chat_id)) or "") if isinstance(pending, dict) else ""


def set_pending_record_command(state: dict[str, Any], chat_id: str, record_type: str) -> None:
    pending = state.get("pendingRecordCommands")
    if not isinstance(pending, dict):
        pending = {}
    pending[str(chat_id)] = record_type
    state["pendingRecordCommands"] = pending
    state.pop("pendingRecordCommand", None)


def clear_pending_record_command(state: dict[str, Any], chat_id: str) -> None:
    pending = state.get("pendingRecordCommands")
    if isinstance(pending, dict):
        pending.pop(str(chat_id), None)
        if not pending:
            state.pop("pendingRecordCommands", None)
    state.pop("pendingRecordCommand", None)


def send_record_options(
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    chat_id: str,
    record_type: str,
) -> None:
    set_pending_record_command(state, chat_id, record_type)
    telegram.send_message(
        record_options_message(record_type),
        reply_markup=record_options_keyboard(record_type),
    )
    save_state(settings.state_path, state)


def record_options_keyboard(record_type: str) -> dict[str, Any]:
    labels = record_option_labels(record_type)
    buttons = [
        {"text": label, "callback_data": f"rec:{record_type}:{idx}"}
        for idx, label in enumerate(labels)
    ]
    return {"inline_keyboard": [buttons[index : index + 3] for index in range(0, len(buttons), 3)]}


def record_option_labels(record_type: str) -> list[str]:
    if record_type == "team":
        return list(TEAM_RECORD_OPTIONS)
    if record_type == "hitter":
        return list(HITTER_RECORD_OPTIONS)
    if record_type == "pitcher":
        return list(PITCHER_RECORD_OPTIONS)
    return []


def option_from_callback_data(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "rec":
        return None
    record_type = parts[1]
    try:
        option_index = int(parts[2])
    except ValueError:
        return None
    labels = record_option_labels(record_type)
    if option_index < 0 or option_index >= len(labels):
        return None
    return record_type, labels[option_index]


def player_from_callback_data(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "player":
        return None
    record_type = {"h": "hitter", "p": "pitcher"}.get(parts[1])
    player_id = parts[2]
    if not record_type or not player_id.isdigit():
        return None
    return record_type, player_id


def player_selection_keyboard(candidates: list[KBOPlayerCandidate]) -> dict[str, Any]:
    short_types = {"hitter": "h", "pitcher": "p"}
    rows = []
    for player in candidates:
        label = f"{player.name} | {player.team} | {player.position} | {player.back_number}번"
        rows.append(
            [
                {
                    "text": label,
                    "callback_data": f"player:{short_types[player.record_type]}:{player.player_id}",
                }
            ]
        )
    return {"inline_keyboard": rows}


def send_player_record(
    client: KBOPlayerClient,
    telegram: TelegramBot,
    record_type: str,
    player_id: str,
) -> None:
    record = client.player_record(player_id, record_type)
    photo_url = record.photo_url or player_image_url(record.player_id)
    telegram.send_photo(photo_url, format_player_record(record))


def send_player_record_lookup(
    telegram: TelegramBot,
    record_type: str,
    player_name: str,
    client: KBOPlayerClient | None = None,
) -> None:
    player_client = client or KBOPlayerClient()
    candidates = player_client.search_players(player_name, record_type)
    record_label = "타자" if record_type == "hitter" else "투수"
    if not candidates:
        telegram.send_message(f"현재 등록된 KBO {record_label} 중 '{player_name}' 선수를 찾지 못했습니다.")
        return
    if len(candidates) == 1:
        send_player_record(player_client, telegram, record_type, candidates[0].player_id)
        return

    lines = [f"동명이인이 있습니다. 확인할 {record_label}를 선택해주세요."]
    for index, player in enumerate(candidates, 1):
        lines.append(
            f"{index}. {player.name} | {player.team} | {player.position} | "
            f"{player.back_number}번 | {player.bats_throws}"
        )
    telegram.send_message("\n".join(lines), reply_markup=player_selection_keyboard(candidates))


def send_selected_record_stats(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    record_type: str,
    option: str,
) -> None:
    now = datetime.now(settings.timezone)
    if record_type == "team":
        rows = unwrap(client.team_record_stats(now.year), "seasonTeamStats")
        telegram.send_message(format_team_record_stats(rows, option))
        return

    options = HITTER_RECORD_OPTIONS if record_type == "hitter" else PITCHER_RECORD_OPTIONS
    config = options[option]
    rows = unwrap(
        client.player_record_stats(
            now.year,
            "HITTER" if record_type == "hitter" else "PITCHER",
            str(config["field"]),
            str(config["direction"]),
            page_size=50,
        ),
        "seasonPlayerStats",
    )
    telegram.send_message(format_player_record_stats(rows, record_type, option, limit=10))


def send_team_schedule(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    now: datetime,
) -> None:
    message = format_team_schedule(fetch_team_schedule_games(client, now.date(), settings.team_code), settings.team_code)
    telegram.send_message(message)


def send_current_kbo_scores(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    now: datetime | None = None,
) -> None:
    current = now or datetime.now(settings.timezone)
    games = client.games_on(current.date())
    games = [
        game
        for game in games
        if str(game.get("awayTeamCode") or game.get("aCode") or "") in TEAM_NAMES
        and str(game.get("homeTeamCode") or game.get("hCode") or "") in TEAM_NAMES
    ]
    if not games:
        telegram.send_message("오늘 예정된 KBO 경기가 없습니다.")
        return
    results = fetch_current_game_results(client, games)
    telegram.send_message(format_daily_game_results(results, "현재 KBO 경기 결과"))


def fetch_current_game_results(
    client: NaverSportsClient,
    games: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for game in games:
        game_id = str(game.get("gameId") or "")
        detail: dict[str, Any] = {}
        if game_id:
            try:
                detail = unwrap(client.game_detail(game_id), "game")
            except Exception:
                logging.exception("Failed to load current score for %s.", game_id)
        current_game = merge_game_status(game, detail)
        away_code = str(current_game.get("awayTeamCode") or current_game.get("aCode") or "")
        home_code = str(current_game.get("homeTeamCode") or current_game.get("hCode") or "")
        away_name = str(
            current_game.get("awayTeamName")
            or current_game.get("aName")
            or TEAM_NAMES.get(away_code, away_code or "원정")
        )
        home_name = str(
            current_game.get("homeTeamName")
            or current_game.get("hName")
            or TEAM_NAMES.get(home_code, home_code or "홈")
        )
        cancelled = is_cancelled_game(current_game)
        result: dict[str, Any] = {
            "awayName": away_name,
            "homeName": home_name,
            "cancelled": cancelled,
        }
        if not cancelled:
            status = str(current_game.get("statusCode") or current_game.get("gameStatus") or "").upper()
            if status not in {"BEFORE", "SCHEDULED", "READY"}:
                away_score = _optional_score_from_game(current_game, "away")
                home_score = _optional_score_from_game(current_game, "home")
                if away_score is not None:
                    result["awayScore"] = away_score
                if home_score is not None:
                    result["homeScore"] = home_score
            result["statusText"] = (
                current_game_status_text(current_game) if detail else "정보 확인 중"
            )
        results.append(result)
    return results


def current_game_status_text(game: dict[str, Any]) -> str:
    status = str(game.get("statusCode") or game.get("gameStatus") or "").upper()
    if is_cancelled_game(game) or status in TERMINAL_SCHEDULE_STATUS:
        return ""
    for key in ("statusInfo", "currentInning"):
        value = str(game.get(key) or "").strip()
        if value and value not in {"경기종료", "종료"}:
            return value
    if status in {"STARTED", "LIVE", "PLAYING"}:
        return "경기중"
    if status in {"BEFORE", "SCHEDULED", "READY"}:
        return "경기전"
    return ""


def fetch_team_schedule_games(
    client: NaverSportsClient,
    start: date,
    team_code: str,
    max_groups: int = 4,
    months_to_scan: int = 4,
) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    current_month = start.replace(day=1)

    for month_offset in range(months_to_scan):
        month = _add_months(current_month, month_offset)
        data = client.calendar(month)
        result = data.get("result", data)
        for date_info in result.get("dates", []):
            ymd = str(date_info.get("ymd") or "")
            game_date = _parse_ymd(ymd)
            if not game_date or game_date < start:
                continue
            for game in date_info.get("gameInfos") or []:
                away_code = str(game.get("awayTeamCode") or game.get("aCode") or "")
                home_code = str(game.get("homeTeamCode") or game.get("hCode") or "")
                if team_code not in {away_code, home_code}:
                    continue
                if str(game.get("statusCode") or game.get("gameStatus") or "") in TERMINAL_SCHEDULE_STATUS:
                    continue
                key = (ymd, away_code, home_code)
                if key in seen:
                    continue
                seen.add(key)
                games.append(
                    {
                        "date": game_date,
                        "awayCode": away_code,
                        "homeCode": home_code,
                    }
                )
        if len(_schedule_groups(games)) >= max_groups:
            break

    return sorted(games, key=lambda game: game["date"])


def format_team_schedule(games: list[dict[str, Any]], team_code: str, max_groups: int = 4) -> str:
    team_name = TEAM_NAMES.get(team_code, team_code)
    groups = _schedule_groups(games)[:max_groups]
    lines = [f"{team_name} 경기 일정"]
    if not groups:
        lines.append("확인된 향후 경기가 없습니다.")
        return "\n\n".join([lines[0], lines[1]])

    lines.append("")
    for group in groups:
        away_name = TEAM_NAMES.get(group["awayCode"], group["awayCode"])
        home_name = TEAM_NAMES.get(group["homeCode"], group["homeCode"])
        lines.append(f"{away_name} vs {home_name} {_format_schedule_range(group['start'], group['end'])}")
    return "\n".join(lines)


def _schedule_groups(games: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for game in sorted(games, key=lambda item: item["date"]):
        if (
            groups
            and groups[-1]["awayCode"] == game["awayCode"]
            and groups[-1]["homeCode"] == game["homeCode"]
            and game["date"] <= groups[-1]["end"] + timedelta(days=1)
        ):
            if game["date"] > groups[-1]["end"]:
                groups[-1]["end"] = game["date"]
            continue
        groups.append(
            {
                "awayCode": game["awayCode"],
                "homeCode": game["homeCode"],
                "start": game["date"],
                "end": game["date"],
            }
        )
    return groups


def _format_schedule_range(start: date, end: date) -> str:
    start_text = f"{start.month}/{start.day}"
    if start == end:
        return start_text
    return f"{start_text} - {end.month}/{end.day}"


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _parse_ymd(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def send_stadium_weather(
    client: NaverSportsClient,
    weather_client: NaverWeatherClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    summary, detail = command_game_detail(client, settings, state, game_id)
    stadium = summary.stadium or str(detail.get("stadium") or detail.get("stadiumName") or "")
    if not stadium:
        telegram.send_message("오늘 경기 구장 정보를 찾지 못했습니다.")
        return
    telegram.send_message(weather_client.stadium_weather(stadium, datetime.now(settings.timezone)))


def command_help_message() -> str:
    lines = ["사용 가능한 명령어"]
    for commands, description in BOT_COMMANDS:
        aliases = f" ({', '.join(commands[1:])})" if len(commands) > 1 else ""
        lines.append(f"{commands[0]}{aliases} - {description}")
    return "\n".join(lines)


def command_game_detail(
    client: NaverSportsClient,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> tuple[Any, dict[str, Any]]:
    preview = unwrap(client.preview(game_id), "previewData")
    detail = preview.get("gameInfo", {}).copy()
    detail["gameId"] = game_id
    state["detailedGameId"] = game_id
    state["detailedGame"] = detail
    save_state(settings.state_path, state)
    return parse_game_summary(detail, settings.naver_game_id), detail


def command_game_phase(summary, detail: dict[str, Any], settings: Settings, now: datetime) -> str:
    if is_terminal_game(detail, set()):
        return "ended"
    if is_before_game_start(summary, settings, now):
        return "before"
    return "live"


def stop_relay_for_game(
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    if state.get("relayStoppedGameId") == game_id:
        telegram.send_message("이미 오늘 경기 중계는 중단되어 있습니다. 경기 종료 후 결과와 순위는 계속 확인합니다.")
        return
    state["relayStoppedGameId"] = game_id
    save_state(settings.state_path, state)
    telegram.send_message("GG 선언 접수. 오늘 경기 중계는 여기서 멈추고, 경기 종료 후 결과와 순위만 보내겠습니다.")


def relay_has_game_over(client: NaverSportsClient, game_id: str) -> bool:
    relay = unwrap(client.relay(game_id), "textRelayData")
    return is_game_over(parse_relay_events(relay))


def resume_relay_for_game(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    if state.get("relayStoppedGameId") != game_id:
        telegram.send_message("현재 중단된 중계가 없습니다.")
        return

    try:
        relay = unwrap(client.relay(game_id), "textRelayData")
        events = parse_relay_events(relay)
    except Exception:
        logging.exception("Failed to align relay sequence while resuming %s.", game_id)
        telegram.send_message("중계 재개 준비 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
        return

    if not events:
        telegram.send_message("중계 데이터가 아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요.")
        return

    latest = events[-1]
    state.update(
        {
            "inning": f"{latest.inning}회{latest.half}",
            "homeScore": latest.home_score,
            "awayScore": latest.away_score,
            "lastRelaySeq": latest.event_id,
            "relayBootstrapped": True,
            "updatedAt": datetime.now(settings.timezone).isoformat(),
        }
    )
    if not is_game_over(events):
        for key in ("recordSentGameId", "pitchingDecisionsSentGameId", "gameOverSentGameId"):
            if state.get(key) == game_id:
                state.pop(key, None)
        today = datetime.now(settings.timezone).date().isoformat()
        if state.get("dailyRankingSentDate") == today:
            state.pop("dailyRankingSentDate", None)
        if state.get("dailyScoresSentDate") == today:
            state.pop("dailyScoresSentDate", None)
    state.pop("relayStoppedGameId", None)
    save_state(settings.state_path, state)
    telegram.send_message("중계 재개합니다. 지금 이후 새 소식부터 보내겠습니다.")


def process_relay(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
    away_name: str,
    home_name: str,
    away_code: str,
    home_code: str,
) -> bool:
    relay = unwrap(client.relay(game_id), "textRelayData")
    events = parse_relay_events(relay)
    if not events:
        return False

    last_seq = int(state.get("lastRelaySeq") or 0)
    sent_summaries = set(state.get("kiaHalfSummariesSent", []))
    relay, events = include_previous_half_events(
        client,
        game_id,
        relay,
        events,
        sent_summaries,
        home_code,
        away_code,
        settings.team_code,
        last_seq,
    )
    if last_seq == 0 and not state.get("relayBootstrapped"):
        latest = events[-1]
        telegram.send_message(
            "\n".join(
                [
                    "KIA 경기 중계 감시 시작",
                    f"{away_name} {latest.away_score} : {latest.home_score} {home_name}",
                    f"현재 {latest.inning}회{latest.half}",
                ]
            )
        )
        bootstrap_events = [
            event
            for event in events
            if event.inning == latest.inning and event.half == latest.half
        ]
        sent_summaries = dispatch_relay_events(
            telegram,
            settings,
            state,
            relay,
            events,
            bootstrap_events,
            sent_summaries,
            away_name,
            home_name,
            away_code,
            home_code,
        )
        state.update(
            {
                "gameId": game_id,
                "inning": f"{latest.inning}회{latest.half}",
                "homeScore": latest.home_score,
                "awayScore": latest.away_score,
                "lastRelaySeq": latest.event_id,
                "relayBootstrapped": True,
                "kiaHalfSummariesSent": sorted(sent_summaries),
                "updatedAt": datetime.now(settings.timezone).isoformat(),
            }
        )
        save_state(settings.state_path, state)
        return is_game_over(events)

    new_events = [event for event in events if event.event_id > last_seq]
    sent_summaries = dispatch_relay_events(
        telegram,
        settings,
        state,
        relay,
        events,
        new_events,
        sent_summaries,
        away_name,
        home_name,
        away_code,
        home_code,
    )

    latest = events[-1]
    state.update(
        {
            "gameId": game_id,
            "inning": f"{latest.inning}회{latest.half}",
            "homeScore": latest.home_score,
            "awayScore": latest.away_score,
            "lastRelaySeq": max(last_seq, max(event.event_id for event in events)),
            "kiaHalfSummariesSent": sorted(sent_summaries),
            "updatedAt": datetime.now(settings.timezone).isoformat(),
        }
    )
    save_state(settings.state_path, state)
    return is_game_over(events)


def include_previous_half_events(
    client: NaverSportsClient,
    game_id: str,
    relay: dict[str, Any],
    events: list,
    sent_summaries: set,
    home_code: str,
    away_code: str,
    team_code: str,
    last_seq: int,
) -> tuple[dict[str, Any], list]:
    available_halves = {(event.inning, event.half) for event in events}
    missing_innings: set[int] = set()
    for event in events:
        if not event.is_attack_start:
            continue
        if is_kia_batting(event, home_code, away_code, team_code):
            if event.event_id <= last_seq:
                continue
        elif half_key(event) in sent_summaries:
            continue
        previous_half = (event.inning, "초") if event.half == "말" else (event.inning - 1, "말")
        if previous_half[0] > 0 and previous_half not in available_halves:
            missing_innings.add(previous_half[0])

    if not missing_innings:
        return relay, events

    combined_groups = list(relay.get("textRelays", []))
    for inning in sorted(missing_innings):
        try:
            previous_relay = unwrap(client.relay(game_id, inning=inning), "textRelayData")
            combined_groups = list(previous_relay.get("textRelays", [])) + combined_groups
        except Exception:
            logging.exception("Failed to load inning %s for half-inning notification context.", inning)

    enriched_relay = relay.copy()
    enriched_relay["textRelays"] = combined_groups
    return enriched_relay, parse_relay_events(enriched_relay)


def dispatch_relay_events(
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    relay: dict[str, Any],
    all_events: list,
    events_to_send: list,
    sent_summaries: set,
    away_name: str,
    home_name: str,
    away_code: str,
    home_code: str,
) -> set:
    for event in events_to_send:
        player_record = current_player_record(relay, event)
        if is_kia_batting(event, home_code, away_code, settings.team_code):
            remember_plate_rbi_baseline(state, event)
            if is_batter_result_event(event):
                remember_plate_result(state, event, player_record)
            remember_plate_score(state, event)

        if event.is_attack_start:
            pitcher_lines = []
            previous_half_labels = []
            if is_kia_batting(event, home_code, away_code, settings.team_code):
                side = "home" if event.home_or_away == "1" else "away"
                pitcher_lines, current_snapshot = changed_pitcher_lines(
                    relay,
                    side,
                    state.get("lastKiaPitcherSnapshot"),
                )
                state["lastKiaPitcherSnapshot"] = current_snapshot
                previous_half_labels = previous_half_result_labels(all_events, event)
            expected = expected_batters_message(
                event,
                relay,
                home_code,
                away_code,
                away_name,
                home_name,
                settings.team_code,
                pitcher_lines,
                previous_half_labels,
            )
            if expected:
                telegram.send_message(expected)

            summary_key = half_key(event)
            if summary_key not in sent_summaries:
                opponent_pitcher_lines = []
                context = opponent_pitching_context(home_code, away_code, settings.team_code)
                if context and is_kia_pitching(event, home_code, away_code, settings.team_code):
                    pitching_side, opponent_code = context
                    opponent_pitcher_lines = previous_half_pitcher_lines(
                        all_events,
                        relay,
                        event,
                        pitching_side,
                        TEAM_PITCHER_LABELS.get(opponent_code, opponent_code),
                    )
                summary = kia_half_summary_message(
                    all_events,
                    relay,
                    event,
                    home_code,
                    away_code,
                    away_name,
                    home_name,
                    settings.team_code,
                    opponent_pitcher_lines,
                )
                if summary:
                    telegram.send_message(summary)
                    sent_summaries.add(summary_key)
            continue

        if not should_send_relay_event(event, home_code, away_code, settings.team_code):
            continue

        previous_plate = find_previous_plate_event(all_events, event)
        player_record = with_state_plate_totals(player_record, state_plate_results(state, event.batter_code))
        plate_results = state_plate_labels(state, event.batter_code) or plate_result_history(all_events, event, player_record)
        message = format_relay_event_with_context(event, away_name, home_name, previous_plate, player_record, plate_results)
        photo = None
        if (
            event.is_pitching_change
            and is_kia_pitching(event, home_code, away_code, settings.team_code)
        ):
            photo = pitcher_photo_url(event)
        elif is_kia_batter_event(event, home_code, away_code, settings.team_code):
            photo = player_photo_url(event)
        elif event.is_score_event and previous_plate and is_kia_batter_event(previous_plate, home_code, away_code, settings.team_code):
            photo = player_photo_url(previous_plate)
        if photo:
            telegram.send_photo(photo, message)
        else:
            telegram.send_message(message)
    return sent_summaries


def remember_plate_result(state: dict[str, Any], event, player_record: dict[str, Any]) -> None:
    if not event.batter_code:
        return
    player_for_label = player_record.copy()
    totals = state.setdefault("plateResultTotals", {})
    batter_totals = totals.setdefault(str(event.batter_code), {})
    current_rbi = _int_like(player_record.get("rbi"))
    had_completed_total = "rbi" in batter_totals
    remaining_rbi = _allocate_delayed_rbi(state, str(event.batter_code), current_rbi)
    known_completed_rbi = _int_like(batter_totals.get("rbi"))
    if "pendingRbi" in batter_totals:
        player_for_label["rbi"] = max(
            _int_like(batter_totals.get("pendingRbi")),
            remaining_rbi,
        )
        completed_rbi = max(
            known_completed_rbi,
            current_rbi,
            _int_like(batter_totals.get("pendingRbiTotal")),
        )
    elif had_completed_total:
        player_for_label["rbi"] = remaining_rbi
        completed_rbi = max(known_completed_rbi, current_rbi)
    else:
        player_for_label["rbi"] = current_rbi if _int_like(player_record.get("ab")) <= 1 else 0
        completed_rbi = current_rbi
    label = plate_result_label(event, player_for_label)
    batter_totals["rbi"] = completed_rbi
    batter_totals.pop("pendingRbi", None)
    batter_totals.pop("pendingRbiTotal", None)
    if not label:
        return
    histories = state.setdefault("plateResultHistories", {})
    history = histories.setdefault(str(event.batter_code), [])
    event_id = int(event.event_id)
    if any(int(item.get("eventId") or 0) == event_id for item in history):
        return
    history.append(
        {
            "eventId": event_id,
            "label": label,
            "rbi": _int_like(player_for_label.get("rbi")),
        }
    )
    history.sort(key=lambda item: int(item.get("eventId") or 0))
    active_results = state.setdefault("activePlateResults", {})
    active_results[str(event.batter_code)] = event_id


def remember_plate_rbi_baseline(state: dict[str, Any], event) -> None:
    if not event.batter_code or event.is_plate_result or not event.batter_record:
        return
    batter_code = str(event.batter_code)
    (state.get("activePlateResults") or {}).pop(batter_code, None)
    totals = state.setdefault("plateResultTotals", {})
    batter_totals = totals.setdefault(batter_code, {})
    snapshot_rbi = _int_like(event.batter_record.get("rbi"))
    had_completed_total = "rbi" in batter_totals
    remaining_rbi = _allocate_delayed_rbi(state, batter_code, snapshot_rbi)
    if had_completed_total:
        plate_rbi = remaining_rbi
    else:
        plate_appearances = _int_like(event.batter_record.get("pa"))
        if not plate_appearances:
            plate_appearances = sum(
                _int_like(event.batter_record.get(key))
                for key in ("ab", "bb", "hbp")
            )
        if plate_appearances:
            plate_rbi = snapshot_rbi if plate_appearances == 1 else 0
        else:
            batter_totals["rbi"] = snapshot_rbi
            plate_rbi = 0
    batter_totals["pendingRbi"] = plate_rbi
    batter_totals["pendingRbiTotal"] = snapshot_rbi


def remember_plate_score(state: dict[str, Any], event) -> None:
    if not event.batter_code or not event.is_score_event:
        return
    batter_code = str(event.batter_code)
    active_event_id = _int_like((state.get("activePlateResults") or {}).get(batter_code))
    if not active_event_id:
        return
    history = (state.get("plateResultHistories") or {}).get(batter_code, [])
    for item in reversed(history):
        if _int_like(item.get("eventId")) == active_event_id:
            item["runsScored"] = _int_like(item.get("runsScored")) + 1
            return


def _allocate_delayed_rbi(state: dict[str, Any], batter_code: str, cumulative_rbi: int) -> int:
    totals = state.setdefault("plateResultTotals", {})
    batter_totals = totals.setdefault(str(batter_code), {})
    if "rbi" not in batter_totals:
        return max(0, cumulative_rbi)

    completed_rbi = _int_like(batter_totals.get("rbi"))
    remaining_rbi = max(0, cumulative_rbi - completed_rbi)
    if not remaining_rbi:
        return 0

    history = (state.get("plateResultHistories") or {}).get(str(batter_code), [])
    for item in history:
        assigned_rbi = _history_item_rbi(item)
        available_rbi = max(0, _int_like(item.get("runsScored")) - assigned_rbi)
        if not available_rbi:
            continue
        added_rbi = min(remaining_rbi, available_rbi)
        total_rbi = assigned_rbi + added_rbi
        item["rbi"] = total_rbi
        item["label"] = _plate_label_with_rbi(str(item.get("label") or ""), total_rbi)
        completed_rbi += added_rbi
        remaining_rbi -= added_rbi
        if not remaining_rbi:
            break

    batter_totals["rbi"] = completed_rbi
    return remaining_rbi


def _history_item_rbi(item: dict[str, Any]) -> int:
    if "rbi" in item:
        return _int_like(item.get("rbi"))
    match = re.search(r"\(타점(\d+)\)$", str(item.get("label") or ""))
    return int(match.group(1)) if match else 0


def _plate_label_with_rbi(label: str, rbi: int) -> str:
    base_label = re.sub(r"\(타점\d+\)$", "", label)
    return f"{base_label}(타점{rbi})" if base_label and rbi else base_label


def state_plate_results(state: dict[str, Any], batter_code: str | None) -> list[dict[str, Any]]:
    if not batter_code:
        return []
    return list((state.get("plateResultHistories") or {}).get(str(batter_code), []))


def state_plate_labels(state: dict[str, Any], batter_code: str | None) -> list[str]:
    return [str(item.get("label")) for item in state_plate_results(state, batter_code) if item.get("label")]


def with_state_plate_totals(player_record: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    if not player_record or not history:
        return player_record
    hits = 0
    at_bats = 0
    for item in history:
        label = str(item.get("label") or "")
        if is_plate_history_hit(label):
            hits += 1
            at_bats += 1
        elif is_plate_history_at_bat(label):
            at_bats += 1
    if not at_bats:
        return player_record
    adjusted = player_record.copy()
    api_at_bats = _int_like(adjusted.get("ab"))
    if at_bats >= api_at_bats:
        adjusted["hit"] = hits
        adjusted["ab"] = at_bats
    else:
        adjusted["hit"] = max(_int_like(adjusted.get("hit")), hits)
    return adjusted


def is_plate_history_hit(label: str) -> bool:
    return any(token in label for token in ("안타", "2루타", "3루타", "홈런"))


def is_plate_history_at_bat(label: str) -> bool:
    no_at_bat = ("볼넷", "사구", "희생플라이", "희생번트")
    return bool(label) and not any(token in label for token in no_at_bat)


def _int_like(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def relay_control_denial_message(telegram: TelegramBot, message: dict[str, Any]) -> str:
    chat = message.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    chat_type = str(chat.get("type") or "").lower()
    if chat_type == "private" or (not chat_type and not chat_id.startswith("-")):
        return ""

    sender_chat = message.get("sender_chat") or {}
    if str(sender_chat.get("id") or "") == chat_id:
        return ""

    user_id = str((message.get("from") or {}).get("id") or "")
    if not user_id:
        return "이 명령은 그룹 관리자만 사용할 수 있습니다."
    try:
        administrators = telegram.get_chat_administrators(chat_id)
    except Exception:
        logging.exception("Failed to check Telegram administrators for chat %s.", chat_id)
        return "관리자 권한을 확인하지 못했습니다. 잠시 후 다시 시도해주세요."

    for administrator in administrators:
        status = str(administrator.get("status") or "").lower()
        administrator_id = str((administrator.get("user") or {}).get("id") or "")
        if administrator_id == user_id and status in {"creator", "administrator"}:
            return ""
    return "이 명령은 그룹 관리자만 사용할 수 있습니다."


def handle_telegram_commands(
    client: NaverSportsClient,
    weather_client: NaverWeatherClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str | None,
) -> None:
    offset = state.get("telegramUpdateOffset")
    updates = telegram.get_updates(offset)
    if not updates:
        return

    if offset is None:
        state["telegramUpdateOffset"] = max(int(update["update_id"]) for update in updates) + 1
        save_state(settings.state_path, state)
        return

    allowed_chat_ids = set(settings.all_telegram_chat_ids)
    for update in updates:
        state["telegramUpdateOffset"] = max(int(state.get("telegramUpdateOffset") or 0), int(update["update_id"]) + 1)
        callback = update.get("callback_query") or {}
        if callback:
            callback_message = callback.get("message") or {}
            callback_chat = callback_message.get("chat", {})
            callback_chat_id = str(callback_chat.get("id") or "")
            if callback_chat_id not in allowed_chat_ids:
                continue
            reply = telegram.for_chat(callback_chat_id)
            try:
                data = str(callback.get("data") or "")
                selected = option_from_callback_data(data)
                if selected:
                    record_type, option = selected
                    clear_pending_record_command(state, callback_chat_id)
                    reply.answer_callback_query(str(callback.get("id") or ""))
                    send_selected_record_stats(client, reply, settings, record_type, option)
                    continue

                selected_player = player_from_callback_data(data)
                if selected_player:
                    record_type, player_id = selected_player
                    clear_pending_record_command(state, callback_chat_id)
                    reply.answer_callback_query(str(callback.get("id") or ""))
                    send_player_record(KBOPlayerClient(), reply, record_type, player_id)
                    continue

                reply.answer_callback_query(str(callback.get("id") or ""))
                continue
            except Exception:
                logging.exception("Telegram callback failed: %s", callback.get("data"))
                reply.send_message("명령 처리 중 오류가 발생했습니다. logs/bot.log를 확인해주세요.")
                continue

        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat", {})
        chat_id = str(chat.get("id") or "")
        if chat_id not in allowed_chat_ids:
            continue
        reply = telegram.for_chat(chat_id)
        text = str(message.get("text") or "").strip()
        command = text.split()[0].split("@")[0] if text else ""
        command_arg = text[len(text.split()[0]) :].strip() if text else ""
        try:
            pending_record_type = pending_record_command(state, chat_id)
            if pending_record_type and command not in {
                "/팀기록",
                "/teamrecord",
                "/타자기록",
                "/hitterrecord",
                "/투수기록",
                "/pitcherrecord",
            }:
                if command.startswith("/"):
                    clear_pending_record_command(state, chat_id)
                else:
                    option = resolve_record_option(str(pending_record_type), text)
                    if option:
                        clear_pending_record_command(state, chat_id)
                        send_selected_record_stats(client, reply, settings, str(pending_record_type), option)
                    else:
                        reply.send_message(record_options_message(str(pending_record_type)))
                    continue

            if command in {"/라인업", "/lineup"}:
                if not game_id:
                    reply.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                send_lineup(client, reply, game_id)
            elif command in {"/기록", "/record"}:
                if not game_id:
                    reply.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                send_kia_record(client, reply, game_id, settings.team_code)
            elif command in {"/일정", "/schedule"}:
                send_team_schedule(client, reply, settings, datetime.now(settings.timezone))
            elif command in {"/최근경기", "/recentgames"}:
                send_recent_games(reply, settings)
            elif command in {"/스코어", "/score"}:
                send_current_kbo_scores(client, reply, settings)
            elif command in {"/상대전적", "/headtohead"}:
                send_head_to_head_record(reply, settings, command_arg)
            elif command in {"/순위", "/rank"}:
                send_team_rankings(client, reply, settings)
            elif command in {"/월간성적", "/monthlyrecord"}:
                send_monthly_team_records(client, reply, settings)
            elif command in {"/팀기록", "/teamrecord"}:
                option = resolve_record_option("team", command_arg)
                if option:
                    clear_pending_record_command(state, chat_id)
                    send_selected_record_stats(client, reply, settings, "team", option)
                    continue
                send_record_options(reply, settings, state, chat_id, "team")
            elif command in {"/타자기록", "/hitterrecord"}:
                option = resolve_record_option("hitter", command_arg)
                if option:
                    clear_pending_record_command(state, chat_id)
                    send_selected_record_stats(client, reply, settings, "hitter", option)
                    continue
                if command_arg:
                    clear_pending_record_command(state, chat_id)
                    send_player_record_lookup(reply, "hitter", command_arg)
                    continue
                send_record_options(reply, settings, state, chat_id, "hitter")
            elif command in {"/투수기록", "/pitcherrecord"}:
                option = resolve_record_option("pitcher", command_arg)
                if option:
                    clear_pending_record_command(state, chat_id)
                    send_selected_record_stats(client, reply, settings, "pitcher", option)
                    continue
                if command_arg:
                    clear_pending_record_command(state, chat_id)
                    send_player_record_lookup(reply, "pitcher", command_arg)
                    continue
                send_record_options(reply, settings, state, chat_id, "pitcher")
            elif command in {"/뉴스", "/news"}:
                send_kia_news_command(client, reply, settings, game_id)
            elif command in {"/날씨", "/weather"}:
                if not game_id:
                    reply.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                send_stadium_weather(client, weather_client, reply, settings, state, game_id)
            elif command == "/gg":
                denial_message = relay_control_denial_message(reply, message)
                if denial_message:
                    reply.send_message(denial_message)
                    continue
                if not game_id:
                    reply.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                summary, detail = command_game_detail(client, settings, state, game_id)
                phase = command_game_phase(summary, detail, settings, datetime.now(settings.timezone))
                if phase == "before":
                    reply.send_message("경기 시작 전입니다.")
                    continue
                if phase == "ended":
                    reply.send_message("경기가 끝났습니다.")
                    continue
                stop_relay_for_game(reply, settings, state, game_id)
            elif command == "/re":
                denial_message = relay_control_denial_message(reply, message)
                if denial_message:
                    reply.send_message(denial_message)
                    continue
                if not game_id:
                    reply.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                summary, detail = command_game_detail(client, settings, state, game_id)
                phase = command_game_phase(summary, detail, settings, datetime.now(settings.timezone))
                if phase == "before":
                    reply.send_message("경기 시작 전입니다.")
                    continue
                if phase == "ended":
                    reply.send_message("경기가 끝났습니다.")
                    continue
                resume_relay_for_game(client, reply, settings, state, game_id)
            elif command in {"/도움말", "/명령어", "/help", "/start"}:
                reply.send_message(command_help_message())
        except Exception:
            logging.exception("Telegram command failed: %s", command)
            reply.send_message("명령 처리 중 오류가 발생했습니다. logs/bot.log를 확인해주세요.")

    save_state(settings.state_path, state)


def send_game_end_record_once(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
    away_name: str,
    home_name: str,
    away_score: int,
    home_score: int,
    kbo_client: KBOPlayerClient | None = None,
) -> bool:
    if state.get("pitchingDecisionsSentGameId") == game_id:
        return True
    record_already_sent = state.get("recordSentGameId") == game_id
    record = unwrap(client.record(game_id), "recordData")
    if not record:
        logging.info("Game record is not ready for %s. Will retry later.", game_id)
        return False
    away_score, home_score = final_score_from_record(record, away_score, home_score)
    decisions_ready = pitching_decisions_ready(record, away_score, home_score)
    decisions = format_pitching_decisions(record, away_name, home_name, away_score, home_score)
    if record_already_sent:
        if not decisions_ready:
            logging.info("Pitching decisions are not ready for %s. Will retry later.", game_id)
            return True
        milestones = new_game_milestones(
            kbo_client,
            record,
            settings.team_code,
            state,
            game_id,
        )
        telegram.send_message(format_pitching_decision_update(record))
        if milestones:
            telegram.send_message(format_today_milestones(milestones))
            mark_game_milestones_sent(state, game_id, milestones)
        state["pitchingDecisionsSentGameId"] = game_id
        save_state(settings.state_path, state)
        return True
    highlights = format_game_highlights(record, settings.team_code)
    if highlights:
        telegram.send_message(highlights)
    telegram.send_message(decisions)
    milestones = new_game_milestones(
        kbo_client,
        record,
        settings.team_code,
        state,
        game_id,
    )
    telegram.send_message(format_kia_record(record, settings.team_code, milestones))
    if milestones:
        mark_game_milestones_sent(state, game_id, milestones)
    state["recordSentGameId"] = game_id
    if decisions_ready:
        state["pitchingDecisionsSentGameId"] = game_id
    schedule_kia_news_after_game(settings, state, game_id)
    save_state(settings.state_path, state)
    if not decisions_ready:
        logging.info("Pitching decisions are not ready for %s. Will retry later.", game_id)
    return True


def new_game_milestones(
    kbo_client: KBOPlayerClient | None,
    record: dict[str, Any],
    team_code: str,
    state: dict[str, Any],
    game_id: str,
) -> list[str]:
    if kbo_client is None:
        return []
    try:
        milestones = kbo_client.game_milestones(record, team_code)
    except Exception:
        logging.exception(
            "KBO milestone lookup failed for %s. Sending the box score without it.",
            game_id,
        )
        return []

    milestone_state = state.get("gameMilestones") or {}
    sent = (
        set(milestone_state.get("sent") or [])
        if milestone_state.get("gameId") == game_id
        else set()
    )
    return [milestone for milestone in milestones if milestone not in sent]


def mark_game_milestones_sent(
    state: dict[str, Any],
    game_id: str,
    milestones: list[str],
) -> None:
    milestone_state = state.get("gameMilestones") or {}
    sent = (
        list(milestone_state.get("sent") or [])
        if milestone_state.get("gameId") == game_id
        else []
    )
    for milestone in milestones:
        if milestone not in sent:
            sent.append(milestone)
    state["gameMilestones"] = {"gameId": game_id, "sent": sent}


def format_today_milestones(milestones: list[str]) -> str:
    return "\n".join(["오늘의 기록", *milestones])


def schedule_kia_news_after_game(settings: Settings, state: dict[str, Any], game_id: str) -> None:
    if state.get("kiaNewsSentGameId") == game_id:
        return
    if state.get("kiaNewsGameId") == game_id and state.get("nextKiaNewsAt"):
        return
    now = datetime.now(settings.timezone)
    state["kiaNewsGameId"] = game_id
    state["nextKiaNewsAt"] = (now + timedelta(minutes=10)).isoformat()
    state["kiaNewsAttemptCount"] = 0


def send_due_kia_news(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
) -> bool:
    game_id = state.get("kiaNewsGameId")
    if not game_id or state.get("kiaNewsSentGameId") == game_id:
        return False

    next_news_at = _parse_dt(state.get("nextKiaNewsAt"))
    if next_news_at and now < next_news_at:
        return False

    try:
        articles = fetch_kia_news_articles(client, str(game_id), now)
    except Exception:
        logging.exception("Failed to fetch KIA news for %s.", game_id)
        articles = []

    if articles:
        telegram.send_message(format_kia_news_articles(articles))
        state["kiaNewsSentGameId"] = game_id
        state.pop("nextKiaNewsAt", None)
        state.pop("kiaNewsAttemptCount", None)
        save_state(settings.state_path, state)
        return True

    attempts = int(state.get("kiaNewsAttemptCount") or 0) + 1
    state["kiaNewsAttemptCount"] = attempts
    if attempts < 3:
        state["nextKiaNewsAt"] = (now + timedelta(minutes=10)).isoformat()
    else:
        logging.info("No KIA news found for %s after %s attempts.", game_id, attempts)
        state["kiaNewsSentGameId"] = game_id
        state.pop("nextKiaNewsAt", None)
    save_state(settings.state_path, state)
    return False


def fetch_kia_news_articles(
    client: NaverSportsClient,
    game_id: str | None,
    now: datetime,
    limit: int = 5,
) -> list[dict[str, Any]]:
    game_news = unwrap(client.game_news(game_id, page_size=20), "newsList") if game_id else []
    section_news_today = unwrap(
        client.section_news("kbaseball", page_size=40, date_yyyymmdd=now.strftime("%Y%m%d")),
        "newsList",
    )
    section_news_latest = unwrap(client.section_news("kbaseball", page_size=40), "newsList")
    return kia_news_articles(game_news, section_news_today, section_news_latest, limit=limit)


def send_kia_news_command(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    game_id: str | None,
) -> None:
    articles = fetch_kia_news_articles(client, game_id, datetime.now(settings.timezone), limit=10)
    if not articles:
        telegram.send_message("KIA 관련 기사를 아직 찾지 못했습니다.")
        return
    telegram.send_message(format_kia_news_articles(articles))


def schedule_kia_highlight_after_rankings(
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
    games: list[dict[str, Any]],
    cancelled_ids: set[str],
) -> None:
    target_date = now.date().isoformat()
    if state.get("kiaHighlightSentDate") == target_date or state.get("kiaHighlightStoppedDate") == target_date:
        return
    if state.get("kiaHighlightDate") == target_date and state.get("nextKiaHighlightAt"):
        return

    kia_game = next(
        (
            game
            for game in games
            if team_in_game(game, settings.team_code)
            and str(game.get("gameId") or "") not in cancelled_ids
            and str(game.get("statusCode") or "").upper()
            not in {"CANCEL", "CANCELED", "CANCELLED"}
        ),
        None,
    )
    if not kia_game:
        return

    state["kiaHighlightDate"] = target_date
    state["kiaHighlightGameId"] = str(kia_game.get("gameId") or "")
    state["nextKiaHighlightAt"] = now.isoformat()
    state["kiaHighlightAttemptCount"] = 0
    save_state(settings.state_path, state)


def send_due_kia_highlight(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
) -> bool:
    target_date_text = str(state.get("kiaHighlightDate") or "")
    if (
        not target_date_text
        or state.get("kiaHighlightSentDate") == target_date_text
        or state.get("kiaHighlightStoppedDate") == target_date_text
    ):
        return False

    next_check_at = _parse_dt(state.get("nextKiaHighlightAt"))
    if next_check_at and now < next_check_at:
        return False

    try:
        target_date = date.fromisoformat(target_date_text)
        highlight = find_tving_kia_highlight(target_date)
    except Exception:
        logging.exception("Failed to fetch TVING SPORTS highlight for %s.", target_date_text)
        highlight = None

    if highlight:
        telegram.send_message(format_kia_highlight(highlight))
        state["kiaHighlightSentDate"] = target_date_text
        state.pop("nextKiaHighlightAt", None)
        state.pop("kiaHighlightAttemptCount", None)
        state["kiaShortsDate"] = target_date_text
        state["kiaShortsGameId"] = str(state.get("kiaHighlightGameId") or "")
        state["nextKiaShortsAt"] = now.isoformat()
        state["kiaShortsAttemptCount"] = 0
        state["kiaShortsSentMediaIds"] = []
        save_state(settings.state_path, state)
        send_due_kia_shorts(client, telegram, settings, state, now)
        return True

    attempts = int(state.get("kiaHighlightAttemptCount") or 0) + 1
    state["kiaHighlightAttemptCount"] = attempts
    if attempts < KIA_HIGHLIGHT_MAX_ATTEMPTS:
        state["nextKiaHighlightAt"] = (
            now + timedelta(minutes=KIA_HIGHLIGHT_RETRY_MINUTES)
        ).isoformat()
    else:
        logging.info(
            "No TVING SPORTS KIA highlight found for %s after %s attempts.",
            target_date_text,
            attempts,
        )
        state["kiaHighlightStoppedDate"] = target_date_text
        state.pop("nextKiaHighlightAt", None)
    save_state(settings.state_path, state)
    return False


def send_due_kia_shorts(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
) -> int:
    target_date = str(state.get("kiaShortsDate") or "")
    game_id = str(state.get("kiaShortsGameId") or "")
    if (
        not target_date
        or not game_id
        or state.get("kiaShortsSentDate") == target_date
        or state.get("kiaShortsStoppedDate") == target_date
    ):
        return 0

    next_check_at = _parse_dt(state.get("nextKiaShortsAt"))
    if next_check_at and now < next_check_at:
        return 0

    sent_ids = {
        str(media_id)
        for media_id in state.get("kiaShortsSentMediaIds", [])
        if media_id
    }
    try:
        videos = unwrap(client.game_videos(game_id), "vodList")
        shorts = naver_game_shorts(videos, game_id, limit=KIA_SHORTS_LIMIT)
    except Exception:
        logging.exception("Failed to fetch Naver shorts for %s.", game_id)
        shorts = []

    sent_count = 0
    for short in shorts:
        media_id = str(short.get("mediaId") or "")
        if not media_id or media_id in sent_ids:
            continue
        telegram.send_message(format_naver_short(short))
        sent_ids.add(media_id)
        sent_count += 1
        state["kiaShortsSentMediaIds"] = list(sent_ids)
        save_state(settings.state_path, state)

    if len(sent_ids) >= KIA_SHORTS_LIMIT:
        state["kiaShortsSentDate"] = target_date
        state.pop("nextKiaShortsAt", None)
        state.pop("kiaShortsAttemptCount", None)
        save_state(settings.state_path, state)
        return sent_count

    attempts = int(state.get("kiaShortsAttemptCount") or 0) + 1
    state["kiaShortsAttemptCount"] = attempts
    if attempts < KIA_SHORTS_MAX_ATTEMPTS:
        state["nextKiaShortsAt"] = (
            now + timedelta(minutes=KIA_SHORTS_RETRY_MINUTES)
        ).isoformat()
    else:
        state["kiaShortsStoppedDate"] = target_date
        state.pop("nextKiaShortsAt", None)
        logging.info(
            "Only %s Naver shorts found for %s after %s attempts.",
            len(sent_ids),
            game_id,
            attempts,
        )
    save_state(settings.state_path, state)
    return sent_count


def refresh_game_status_from_schedule(
    client: NaverSportsClient,
    settings: Settings,
    state: dict[str, Any],
    summary,
    detailed_game: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    try:
        games = client.games_on(now.date())
    except Exception:
        logging.exception("Failed to refresh schedule status for %s.", summary.game_id)
        return detailed_game
    for game in games:
        if str(game.get("gameId") or "") != summary.game_id:
            continue
        refreshed = merge_game_status(detailed_game, game)
        state["detailedGameId"] = summary.game_id
        state["detailedGame"] = refreshed
        state["scheduledGame"] = merge_game_status(state.get("scheduledGame") or {}, game)
        save_state(settings.state_path, state)
        return refreshed
    return detailed_game


def finish_stopped_relay_game_if_done(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    summary,
    detailed_game: dict[str, Any],
    now: datetime,
    kbo_client: KBOPlayerClient | None = None,
) -> bool:
    if state.get("relayStoppedGameId") != summary.game_id:
        return False
    detailed_game = refresh_game_status_from_schedule(client, settings, state, summary, detailed_game, now)
    if not relay_has_game_over(client, summary.game_id):
        logging.debug("Relay stopped for %s by /gg. Waiting for relay game-over marker.", summary.game_id)
        return True

    if state.get("gameOverSentGameId") != summary.game_id:
        away_score = score_from_game(detailed_game, "away") or int(state.get("awayScore") or 0)
        home_score = score_from_game(detailed_game, "home") or int(state.get("homeScore") or 0)
        record_sent = send_game_end_record_once(
            client,
            telegram,
            settings,
            state,
            summary.game_id,
            summary.away_name or "원정",
            summary.home_name or "홈",
            away_score,
            home_score,
            kbo_client,
        )
        if not record_sent:
            send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
            return True
        telegram.send_message("경기 종료 알림을 확인했습니다. 오늘도 수고하셨습니다.")
        state["gameOverSentGameId"] = summary.game_id
        save_state(settings.state_path, state)
    elif state.get("pitchingDecisionsSentGameId") != summary.game_id:
        send_game_end_record_once(
            client,
            telegram,
            settings,
            state,
            summary.game_id,
            summary.away_name or "원정",
            summary.home_name or "홈",
            score_from_game(detailed_game, "away") or int(state.get("awayScore") or 0),
            score_from_game(detailed_game, "home") or int(state.get("homeScore") or 0),
            kbo_client,
        )
    send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
    return True


def send_team_rankings_once(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    if state.get("rankingSentGameId") == game_id:
        return
    send_team_rankings(client, telegram, settings)
    state["rankingSentGameId"] = game_id
    save_state(settings.state_path, state)


def send_daily_rankings_if_all_games_done(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    now: datetime,
) -> bool:
    today = now.date().isoformat()
    if state.get("dailyRankingSentDate") == today:
        return True

    next_check = _parse_dt(state.get("nextDailyRankingCheckAt"))
    if next_check and now < next_check:
        return False

    games = client.games_on(now.date())
    if not games:
        state["nextDailyRankingCheckAt"] = (now + timedelta(seconds=settings.schedule_check_seconds)).isoformat()
        save_state(settings.state_path, state)
        return False

    cancelled_ids = refresh_cancelled_games(client, state, games)
    pending = [game for game in games if not is_terminal_game(game, cancelled_ids)]
    if pending:
        state["nextDailyRankingCheckAt"] = (now + timedelta(seconds=settings.idle_poll_seconds)).isoformat()
        save_state(settings.state_path, state)
        logging.debug("Daily rankings pending. Unfinished games: %s", [game.get("gameId") for game in pending])
        return False

    if state.get("dailyScoresSentDate") != today:
        results = fetch_daily_game_results(client, games, cancelled_ids)
        if results is None:
            state["nextDailyRankingCheckAt"] = (now + timedelta(seconds=settings.idle_poll_seconds)).isoformat()
            save_state(settings.state_path, state)
            return False
        telegram.send_message(format_daily_game_results(results))
        state["dailyScoresSentDate"] = today
        save_state(settings.state_path, state)

    send_team_rankings(client, telegram, settings)
    state["dailyRankingSentDate"] = today
    state.pop("nextDailyRankingCheckAt", None)
    save_state(settings.state_path, state)
    schedule_kia_highlight_after_rankings(settings, state, now, games, cancelled_ids)
    send_due_kia_highlight(client, telegram, settings, state, now)
    return True


def fetch_daily_game_results(
    client: NaverSportsClient,
    games: list[dict[str, Any]],
    cancelled_ids: set[str],
) -> list[dict[str, Any]] | None:
    results: list[dict[str, Any]] = []
    for game in games:
        game_id = str(game.get("gameId") or "")
        away_code = str(game.get("awayTeamCode") or game.get("aCode") or "")
        home_code = str(game.get("homeTeamCode") or game.get("hCode") or "")
        away_name = str(game.get("awayTeamName") or game.get("aName") or TEAM_NAMES.get(away_code, away_code or "원정"))
        home_name = str(game.get("homeTeamName") or game.get("hName") or TEAM_NAMES.get(home_code, home_code or "홈"))
        status = str(game.get("statusCode") or "").upper()
        cancelled = game_id in cancelled_ids or status in {"CANCEL", "CANCELED", "CANCELLED"}
        if cancelled:
            results.append({"awayName": away_name, "homeName": home_name, "cancelled": True})
            continue

        try:
            record = unwrap(client.record(game_id), "recordData")
        except Exception:
            logging.exception("Failed to load final score for %s.", game_id)
            return None
        if not record:
            logging.info("Final score is not ready for %s. Will retry later.", game_id)
            return None

        info = record.get("gameInfo", {})
        away_name = str(info.get("aName") or away_name)
        home_name = str(info.get("hName") or home_name)
        away_score, home_score = final_score_from_record(record, -1, -1)
        if away_score < 0 or home_score < 0:
            logging.info("Final score is not ready for %s. Will retry later.", game_id)
            return None
        results.append(
            {
                "awayName": away_name,
                "homeName": home_name,
                "awayScore": away_score,
                "homeScore": home_score,
                "cancelled": False,
            }
        )
    return results


def is_terminal_game(game: dict[str, Any], cancelled_ids: set[str]) -> bool:
    game_id = str(game.get("gameId") or "")
    status = str(game.get("statusCode") or "").upper()
    if game_id in cancelled_ids:
        return True
    return status in TERMINAL_SCHEDULE_STATUS


def refresh_cancelled_games(
    client: NaverSportsClient,
    state: dict[str, Any],
    games: list[dict[str, Any]],
) -> set[str]:
    cancelled_ids = set(state.get("cancelledGameIds", []))
    changed = False
    for game in games:
        game_id = str(game.get("gameId") or "")
        if not game_id or is_terminal_game(game, cancelled_ids):
            continue
        try:
            preview = unwrap(client.preview(game_id), "previewData")
        except Exception:
            logging.exception("Failed to inspect pending game %s for cancellation.", game_id)
            continue
        game_info = preview.get("gameInfo", {})
        if is_cancelled_game(game_info):
            cancelled_ids.add(game_id)
            changed = True
            logging.info("Marked cancelled game %s while checking daily rankings.", game_id)
    if changed:
        state["cancelledGameIds"] = sorted(cancelled_ids)
    return cancelled_ids


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed


def seconds_until_next_due(now: datetime, default_seconds: int, *iso_values: Any) -> int:
    candidates = []
    for value in iso_values:
        parsed = _parse_dt(value)
        if parsed:
            candidates.append(max(60, int((parsed - now).total_seconds())))
    if not candidates:
        return default_seconds
    return min([default_seconds, *candidates])


def sleep_with_command_polling(
    client: NaverSportsClient,
    weather_client: NaverWeatherClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    seconds: int,
) -> None:
    deadline = datetime.now(settings.timezone) + timedelta(seconds=max(0, seconds))
    remaining = max(0, int((deadline - datetime.now(settings.timezone)).total_seconds()))
    while remaining > 0:
        chunk = min(remaining, 5)
        time.sleep(chunk)
        handle_telegram_commands(client, weather_client, telegram, settings, state, current_game_id(state))
        poll_now = datetime.now(settings.timezone)
        send_due_kia_news(client, telegram, settings, state, poll_now)
        send_due_kia_highlight(client, telegram, settings, state, poll_now)
        send_due_kia_shorts(client, telegram, settings, state, poll_now)
        remaining = max(0, int((deadline - datetime.now(settings.timezone)).total_seconds()))


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    client = NaverSportsClient()
    kbo_client = KBOPlayerClient()
    weather_client = NaverWeatherClient()
    telegram = TelegramBot(settings.telegram_token, settings.all_telegram_chat_ids, settings.dry_run)
    state = load_state(settings.state_path)

    logging.info("KIA Telegram bot started. dry_run=%s", settings.dry_run)
    try:
        telegram.set_commands(TELEGRAM_MENU_COMMANDS)
    except Exception:
        logging.exception("Failed to register Telegram commands.")

    while True:
        try:
            now = datetime.now(settings.timezone)
            handle_telegram_commands(client, weather_client, telegram, settings, state, current_game_id(state))
            send_due_kia_news(client, telegram, settings, state, now)
            send_due_kia_highlight(client, telegram, settings, state, now)
            send_due_kia_shorts(client, telegram, settings, state, now)
            game = get_cached_today_game(client, settings, state, now)

            if not game:
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    settings.schedule_check_seconds,
                    state.get("nextScheduleCheckAt"),
                    state.get("nextDailyRankingCheckAt"),
                    state.get("nextKiaNewsAt"),
                    state.get("nextKiaHighlightAt"),
                    state.get("nextKiaShortsAt"),
                )
                logging.info("No KIA game found today. Sleeping %ss.", sleep_seconds)
                sleep_with_command_polling(client, weather_client, telegram, settings, state, sleep_seconds)
                continue

            detailed_game = get_detailed_game(client, settings, state, game)
            summary = parse_game_summary(detailed_game, settings.naver_game_id)
            if not summary.game_id:
                logging.warning("KIA game found but gameId is missing: %s", game)
                sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.idle_poll_seconds)
                continue

            if state.get("gameId") != summary.game_id:
                state = {
                    "gameId": summary.game_id,
                    "scheduleDate": state.get("scheduleDate"),
                    "scheduledGame": state.get("scheduledGame"),
                    "detailedGameId": state.get("detailedGameId"),
                    "detailedGame": state.get("detailedGame"),
                    "telegramUpdateOffset": state.get("telegramUpdateOffset"),
                    "cancelledGameIds": state.get("cancelledGameIds", []),
                    "dailyScoresSentDate": state.get("dailyScoresSentDate"),
                    "dailyRankingSentDate": state.get("dailyRankingSentDate"),
                    "nextDailyRankingCheckAt": state.get("nextDailyRankingCheckAt"),
                    "nextPreviewCheckAt": state.get("nextPreviewCheckAt"),
                    "relayStoppedGameId": state.get("relayStoppedGameId"),
                    "pendingRecordCommands": state.get("pendingRecordCommands"),
                    "kiaNewsGameId": state.get("kiaNewsGameId"),
                    "nextKiaNewsAt": state.get("nextKiaNewsAt"),
                    "kiaNewsSentGameId": state.get("kiaNewsSentGameId"),
                    "kiaNewsAttemptCount": state.get("kiaNewsAttemptCount"),
                    "kiaHighlightDate": state.get("kiaHighlightDate"),
                    "kiaHighlightGameId": state.get("kiaHighlightGameId"),
                    "nextKiaHighlightAt": state.get("nextKiaHighlightAt"),
                    "kiaHighlightAttemptCount": state.get("kiaHighlightAttemptCount"),
                    "kiaHighlightSentDate": state.get("kiaHighlightSentDate"),
                    "kiaHighlightStoppedDate": state.get("kiaHighlightStoppedDate"),
                    "kiaShortsDate": state.get("kiaShortsDate"),
                    "kiaShortsGameId": state.get("kiaShortsGameId"),
                    "nextKiaShortsAt": state.get("nextKiaShortsAt"),
                    "kiaShortsAttemptCount": state.get("kiaShortsAttemptCount"),
                    "kiaShortsSentMediaIds": state.get("kiaShortsSentMediaIds", []),
                    "kiaShortsSentDate": state.get("kiaShortsSentDate"),
                    "kiaShortsStoppedDate": state.get("kiaShortsStoppedDate"),
                }
                save_state(settings.state_path, state)

            if should_check_game_status(summary, settings, now):
                detailed_game = get_detailed_game(client, settings, state, game, force=True)
                summary = parse_game_summary(detailed_game, settings.naver_game_id)
                if is_cancelled_game(detailed_game):
                    send_cancelled_once(
                        client,
                        weather_client,
                        telegram,
                        settings,
                        state,
                        summary,
                        detailed_game,
                    )
                    send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                    sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.idle_poll_seconds)
                    continue

            if not should_poll_game(summary, settings, now):
                if state.get("relayStoppedGameId") != summary.game_id and should_check_preview(state, summary.game_id, now):
                    send_preview_once(client, telegram, settings, state, summary.game_id)
                after_game_start = is_after_game_start(summary, settings, now)
                if after_game_start:
                    send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    seconds_until_pregame(summary, settings, now),
                    state.get("nextDailyRankingCheckAt") if after_game_start else None,
                    state.get("nextPreviewCheckAt"),
                    state.get("nextKiaNewsAt"),
                    state.get("nextKiaHighlightAt"),
                    state.get("nextKiaShortsAt"),
                )
                logging.debug(
                    "KIA game %s is outside polling window. Sleeping %ss.",
                    summary.game_id,
                    sleep_seconds,
                )
                sleep_with_command_polling(client, weather_client, telegram, settings, state, sleep_seconds)
                continue

            if state.get("relayStoppedGameId") == summary.game_id and not is_after_game_start(summary, settings, now):
                logging.debug("Relay stopped for %s by /gg before game start. Waiting for final result.", summary.game_id)
                sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if should_check_preview(state, summary.game_id, now):
                send_preview_once(client, telegram, settings, state, summary.game_id)
            if is_before_game_start(summary, settings, now):
                try:
                    send_lineup_once(client, telegram, settings, state, summary.game_id)
                except Exception:
                    logging.exception("Lineup check failed. Continuing relay polling.")
                sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if not is_after_game_start(summary, settings, now):
                sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if state.get("lineupSentGameId") != summary.game_id:
                try:
                    send_lineup_once(client, telegram, settings, state, summary.game_id)
                except Exception:
                    logging.exception("Late lineup check failed. Continuing relay polling.")

            if state.get("relayStoppedGameId") == summary.game_id:
                handled = finish_stopped_relay_game_if_done(
                    client,
                    telegram,
                    settings,
                    state,
                    summary,
                    detailed_game,
                    now,
                    kbo_client,
                )
                if handled:
                    sleep_seconds = (
                        PITCHING_DECISION_POLL_SECONDS
                        if state.get("gameOverSentGameId") == summary.game_id
                        and state.get("pitchingDecisionsSentGameId") != summary.game_id
                        else settings.idle_poll_seconds
                    )
                    sleep_with_command_polling(client, weather_client, telegram, settings, state, sleep_seconds)
                    continue

            game_over = process_relay(
                client,
                telegram,
                settings,
                state,
                summary.game_id,
                summary.away_name or "원정",
                summary.home_name or "홈",
                summary.away_code,
                summary.home_code,
            )
            if game_over and state.get("gameOverSentGameId") != summary.game_id:
                record_sent = send_game_end_record_once(
                    client,
                    telegram,
                    settings,
                    state,
                    summary.game_id,
                    summary.away_name or "원정",
                    summary.home_name or "홈",
                    int(state.get("awayScore") or 0),
                    int(state.get("homeScore") or 0),
                    kbo_client,
                )
                if not record_sent:
                    sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.idle_poll_seconds)
                    continue
                telegram.send_message("경기 종료 알림을 확인했습니다. 오늘도 수고하셨습니다.")
                state["gameOverSentGameId"] = summary.game_id
                save_state(settings.state_path, state)
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = (
                    PITCHING_DECISION_POLL_SECONDS
                    if state.get("pitchingDecisionsSentGameId") != summary.game_id
                    else settings.idle_poll_seconds
                )
                sleep_with_command_polling(client, weather_client, telegram, settings, state, sleep_seconds)
            elif game_over:
                if state.get("pitchingDecisionsSentGameId") != summary.game_id:
                    send_game_end_record_once(
                        client,
                        telegram,
                        settings,
                        state,
                        summary.game_id,
                        summary.away_name or "원정",
                        summary.home_name or "홈",
                        int(state.get("awayScore") or 0),
                        int(state.get("homeScore") or 0),
                        kbo_client,
                    )
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    (
                        PITCHING_DECISION_POLL_SECONDS
                        if state.get("pitchingDecisionsSentGameId") != summary.game_id
                        else settings.schedule_check_seconds
                    ),
                    state.get("nextDailyRankingCheckAt"),
                    state.get("nextKiaNewsAt"),
                    state.get("nextKiaHighlightAt"),
                    state.get("nextKiaShortsAt"),
                )
                logging.info("Game %s already ended. Sleeping %ss.", summary.game_id, sleep_seconds)
                sleep_with_command_polling(client, weather_client, telegram, settings, state, sleep_seconds)
            else:
                sleep_with_command_polling(client, weather_client, telegram, settings, state, settings.poll_seconds)

        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            raise
        except Exception:
            logging.exception("Loop failed.")
            time.sleep(5)


if __name__ == "__main__":
    main()
