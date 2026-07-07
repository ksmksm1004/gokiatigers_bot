from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import Settings, get_settings
from naver_api import NaverSportsClient, unwrap
from parser import (
    expected_batters_message,
    find_previous_plate_event,
    format_game_highlights,
    format_kia_record,
    format_pitching_decisions,
    format_preview,
    format_team_rankings,
    format_relay_event_with_context,
    half_key,
    has_starting_lineups,
    is_game_over,
    is_kia_batter_event,
    kia_half_summary_message,
    lineup_media_items,
    parse_game_summary,
    parse_relay_events,
    player_photo_url,
    relay_player_record,
    should_send_relay_event,
    team_in_game,
)
from telegram import TelegramBot


BOT_COMMANDS = [
    ("/라인업", "오늘 KIA 경기 선발 라인업 확인"),
    ("/lineup", "오늘 KIA 경기 선발 라인업 확인"),
    ("/기록", "오늘 KIA 경기 기록 확인"),
    ("/record", "오늘 KIA 경기 기록 확인"),
    ("/순위", "KBO 팀 순위 확인"),
    ("/rank", "KBO 팀 순위 확인"),
    ("/gg", "오늘 경기 중계 중단 후 종료 결과만 받기"),
    ("/re", "중단한 오늘 경기 중계 재개"),
    ("/도움말", "사용 가능한 명령어 보기"),
    ("/help", "사용 가능한 명령어 보기"),
]

TELEGRAM_MENU_COMMANDS = [
    ("/lineup", "오늘 KIA 경기 선발 라인업 확인"),
    ("/record", "오늘 KIA 경기 기록 확인"),
    ("/rank", "KBO 팀 순위 확인"),
    ("/gg", "오늘 경기 중계 중단"),
    ("/re", "오늘 경기 중계 재개"),
    ("/help", "사용 가능한 명령어 보기"),
]


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
    return cancel_flag == "Y" or status in {"CANCEL", "CANCELED", "CANCELLED"}


def send_cancelled_once(
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    summary,
    game: dict[str, Any],
) -> None:
    if state.get("cancelSentGameId") == summary.game_id:
        return
    reason = "우천취소" if str(game.get("cancelFlag") or "").upper() == "Y" else "경기취소"
    lines = [
        "KIA 경기 취소",
        f"{summary.away_name or game.get('aName', '원정')} vs {summary.home_name or game.get('hName', '홈')}",
        f"{summary.stadium or game.get('stadium', '')} {reason}".strip(),
    ]
    telegram.send_message("\n".join(line for line in lines if line))
    state["cancelSentGameId"] = summary.game_id
    state["gameCancelled"] = True
    cancelled_ids = set(state.get("cancelledGameIds", []))
    cancelled_ids.add(summary.game_id)
    state["cancelledGameIds"] = sorted(cancelled_ids)
    save_state(settings.state_path, state)


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
    for hour in (9, 12):
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
    if state.get("lineupSentGameId") == game_id:
        return

    preview = unwrap(client.preview(game_id), "previewData")
    if not has_starting_lineups(preview):
        return

    info = preview.get("gameInfo", {})
    away_name = info.get("aName", "원정")
    home_name = info.get("hName", "홈")

    if state.get("lineupHeaderSentGameId") != game_id:
        state["lineupHeaderSentGameId"] = game_id
        save_state(settings.state_path, state)
        telegram.send_message(f"선발 라인업\n{away_name} vs {home_name}")

    for side, label in (("away", away_name), ("home", home_name)):
        sent_key = f"lineup{side.title()}SentGameId"
        attempted_key = f"lineup{side.title()}AttemptedGameId"
        if state.get(sent_key) == game_id or state.get(attempted_key) == game_id:
            continue

        state[attempted_key] = game_id
        save_state(settings.state_path, state)
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

    if state.get("lineupAwaySentGameId") == game_id and state.get("lineupHomeSentGameId") == game_id:
        state["lineupSentGameId"] = game_id
    else:
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


def send_kia_record(
    client: NaverSportsClient,
    telegram: TelegramBot,
    game_id: str,
    team_code: str,
) -> None:
    record = unwrap(client.record(game_id), "recordData")
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


def command_help_message() -> str:
    lines = ["사용 가능한 명령어"]
    lines.extend(f"{command} - {description}" for command, description in BOT_COMMANDS)
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

    if events:
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


def dispatch_relay_events(
    telegram: TelegramBot,
    settings: Settings,
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
        if event.is_attack_start:
            expected = expected_batters_message(event, relay, home_code, away_code, away_name, home_name, settings.team_code)
            if expected:
                telegram.send_message(expected)

            summary_key = half_key(event)
            if summary_key not in sent_summaries:
                summary = kia_half_summary_message(
                    all_events,
                    relay,
                    event,
                    home_code,
                    away_code,
                    away_name,
                    home_name,
                    settings.team_code,
                )
                if summary:
                    telegram.send_message(summary)
                    sent_summaries.add(summary_key)
            continue

        if not should_send_relay_event(event, home_code, away_code, settings.team_code):
            continue

        previous_plate = find_previous_plate_event(all_events, event)
        player_record = relay_player_record(relay, event)
        message = format_relay_event_with_context(event, away_name, home_name, previous_plate, player_record)
        photo = None
        if is_kia_batter_event(event, home_code, away_code, settings.team_code):
            photo = player_photo_url(event)
        elif event.is_score_event and previous_plate and is_kia_batter_event(previous_plate, home_code, away_code, settings.team_code):
            photo = player_photo_url(previous_plate)
        if photo:
            telegram.send_photo(photo, message)
        else:
            telegram.send_message(message)
    return sent_summaries


def handle_telegram_commands(
    client: NaverSportsClient,
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

    for update in updates:
        state["telegramUpdateOffset"] = max(int(state.get("telegramUpdateOffset") or 0), int(update["update_id"]) + 1)
        message = update.get("message") or update.get("channel_post") or {}
        chat = message.get("chat", {})
        if str(chat.get("id")) != str(settings.telegram_chat_id):
            continue
        text = str(message.get("text") or "").strip()
        command = text.split()[0].split("@")[0] if text else ""
        try:
            if command in {"/라인업", "/lineup"}:
                if not game_id:
                    telegram.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                send_lineup(client, telegram, game_id)
            elif command in {"/기록", "/record"}:
                if not game_id:
                    telegram.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                send_kia_record(client, telegram, game_id, settings.team_code)
            elif command in {"/순위", "/rank"}:
                send_team_rankings(client, telegram, settings)
            elif command == "/gg":
                if not game_id:
                    telegram.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                summary, detail = command_game_detail(client, settings, state, game_id)
                phase = command_game_phase(summary, detail, settings, datetime.now(settings.timezone))
                if phase == "before":
                    telegram.send_message("경기 시작 전입니다.")
                    continue
                if phase == "ended":
                    telegram.send_message("경기가 끝났습니다.")
                    continue
                stop_relay_for_game(telegram, settings, state, game_id)
            elif command == "/re":
                if not game_id:
                    telegram.send_message("오늘 확인된 KIA 경기가 없습니다.")
                    continue
                summary, detail = command_game_detail(client, settings, state, game_id)
                phase = command_game_phase(summary, detail, settings, datetime.now(settings.timezone))
                if phase == "before":
                    telegram.send_message("경기 시작 전입니다.")
                    continue
                if phase == "ended":
                    telegram.send_message("경기가 끝났습니다.")
                    continue
                resume_relay_for_game(client, telegram, settings, state, game_id)
            elif command in {"/도움말", "/명령어", "/help", "/start"}:
                telegram.send_message(command_help_message())
        except Exception:
            logging.exception("Telegram command failed: %s", command)
            telegram.send_message("명령 처리 중 오류가 발생했습니다. logs/bot.log를 확인해주세요.")

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
) -> None:
    if state.get("recordSentGameId") == game_id:
        return
    record = unwrap(client.record(game_id), "recordData")
    highlights = format_game_highlights(record, settings.team_code)
    if highlights:
        telegram.send_message(highlights)
    decisions = format_pitching_decisions(record, away_name, home_name, away_score, home_score)
    if decisions:
        telegram.send_message(decisions)
    telegram.send_message(format_kia_record(record, settings.team_code))
    state["recordSentGameId"] = game_id
    save_state(settings.state_path, state)


def finish_stopped_relay_game_if_done(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    summary,
    detailed_game: dict[str, Any],
    now: datetime,
) -> bool:
    if state.get("relayStoppedGameId") != summary.game_id:
        return False
    if not is_terminal_game(detailed_game, set(state.get("cancelledGameIds", []))):
        logging.info("Relay stopped for %s by /gg. Waiting for final result.", summary.game_id)
        return True
    if state.get("gameOverSentGameId") != summary.game_id:
        away_score = score_from_game(detailed_game, "away") or int(state.get("awayScore") or 0)
        home_score = score_from_game(detailed_game, "home") or int(state.get("homeScore") or 0)
        send_game_end_record_once(
            client,
            telegram,
            settings,
            state,
            summary.game_id,
            summary.away_name or "원정",
            summary.home_name or "홈",
            away_score,
            home_score,
        )
        telegram.send_message("경기 종료 알림을 확인했습니다. 오늘도 수고하셨습니다.")
        state["gameOverSentGameId"] = summary.game_id
        save_state(settings.state_path, state)
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
        logging.info("Daily rankings pending. Unfinished games: %s", [game.get("gameId") for game in pending])
        return False

    send_team_rankings(client, telegram, settings)
    state["dailyRankingSentDate"] = today
    state.pop("nextDailyRankingCheckAt", None)
    save_state(settings.state_path, state)
    return True


def is_terminal_game(game: dict[str, Any], cancelled_ids: set[str]) -> bool:
    game_id = str(game.get("gameId") or "")
    status = str(game.get("statusCode") or "").upper()
    if game_id in cancelled_ids:
        return True
    return status in {"RESULT", "END", "CANCEL", "CANCELED", "CANCELLED"}


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
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    seconds: int,
) -> None:
    remaining = max(0, seconds)
    while remaining > 0:
        chunk = min(remaining, 5)
        time.sleep(chunk)
        remaining -= chunk
        handle_telegram_commands(client, telegram, settings, state, current_game_id(state))


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    client = NaverSportsClient()
    telegram = TelegramBot(settings.telegram_token, settings.telegram_chat_id, settings.dry_run)
    state = load_state(settings.state_path)

    logging.info("KIA Telegram bot started. dry_run=%s", settings.dry_run)
    try:
        telegram.set_commands(TELEGRAM_MENU_COMMANDS)
    except Exception:
        logging.exception("Failed to register Telegram commands.")

    while True:
        try:
            now = datetime.now(settings.timezone)
            handle_telegram_commands(client, telegram, settings, state, current_game_id(state))
            game = get_cached_today_game(client, settings, state, now)

            if not game:
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    settings.schedule_check_seconds,
                    state.get("nextScheduleCheckAt"),
                    state.get("nextDailyRankingCheckAt"),
                )
                logging.info("No KIA game found today. Sleeping %ss.", sleep_seconds)
                sleep_with_command_polling(client, telegram, settings, state, min(sleep_seconds, 60))
                continue

            detailed_game = get_detailed_game(client, settings, state, game)
            summary = parse_game_summary(detailed_game, settings.naver_game_id)
            if not summary.game_id:
                logging.warning("KIA game found but gameId is missing: %s", game)
                sleep_with_command_polling(client, telegram, settings, state, min(settings.idle_poll_seconds, 60))
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
                    "dailyRankingSentDate": state.get("dailyRankingSentDate"),
                    "nextDailyRankingCheckAt": state.get("nextDailyRankingCheckAt"),
                    "nextPreviewCheckAt": state.get("nextPreviewCheckAt"),
                    "relayStoppedGameId": state.get("relayStoppedGameId"),
                }
                save_state(settings.state_path, state)

            if should_check_game_status(summary, settings, now):
                detailed_game = get_detailed_game(client, settings, state, game, force=True)
                summary = parse_game_summary(detailed_game, settings.naver_game_id)
                if is_cancelled_game(detailed_game):
                    send_cancelled_once(telegram, settings, state, summary, detailed_game)
                    send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                    sleep_with_command_polling(client, telegram, settings, state, min(settings.idle_poll_seconds, 60))
                    continue

            if not should_poll_game(summary, settings, now):
                if state.get("relayStoppedGameId") != summary.game_id and should_check_preview(state, summary.game_id, now):
                    send_preview_once(client, telegram, settings, state, summary.game_id)
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    seconds_until_pregame(summary, settings, now),
                    state.get("nextDailyRankingCheckAt"),
                    state.get("nextPreviewCheckAt"),
                )
                logging.info(
                    "KIA game %s is outside polling window. Sleeping %ss.",
                    summary.game_id,
                    sleep_seconds,
                )
                sleep_with_command_polling(client, telegram, settings, state, min(sleep_seconds, 60))
                continue

            if state.get("relayStoppedGameId") == summary.game_id and not is_after_game_start(summary, settings, now):
                logging.info("Relay stopped for %s by /gg before game start. Waiting for final result.", summary.game_id)
                sleep_with_command_polling(client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if should_check_preview(state, summary.game_id, now):
                send_preview_once(client, telegram, settings, state, summary.game_id)
            if is_before_game_start(summary, settings, now):
                try:
                    send_lineup_once(client, telegram, settings, state, summary.game_id)
                except Exception:
                    logging.exception("Lineup check failed. Continuing relay polling.")
                sleep_with_command_polling(client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if not is_after_game_start(summary, settings, now):
                sleep_with_command_polling(client, telegram, settings, state, settings.pregame_poll_seconds)
                continue

            if state.get("relayStoppedGameId") == summary.game_id:
                handled = finish_stopped_relay_game_if_done(
                    client,
                    telegram,
                    settings,
                    state,
                    summary,
                    detailed_game,
                    now,
                )
                if handled:
                    sleep_with_command_polling(client, telegram, settings, state, min(settings.idle_poll_seconds, 60))
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
                )
                telegram.send_message("경기 종료 알림을 확인했습니다. 오늘도 수고하셨습니다.")
                state["gameOverSentGameId"] = summary.game_id
                save_state(settings.state_path, state)
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_with_command_polling(client, telegram, settings, state, min(settings.idle_poll_seconds, 60))
            elif game_over:
                send_daily_rankings_if_all_games_done(client, telegram, settings, state, now)
                sleep_seconds = seconds_until_next_due(
                    now,
                    settings.schedule_check_seconds,
                    state.get("nextDailyRankingCheckAt"),
                )
                logging.info("Game %s already ended. Sleeping %ss.", summary.game_id, sleep_seconds)
                sleep_with_command_polling(client, telegram, settings, state, min(sleep_seconds, 60))
            else:
                sleep_with_command_polling(client, telegram, settings, state, settings.poll_seconds)

        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            raise
        except Exception:
            logging.exception("Loop failed.")
            time.sleep(5)


if __name__ == "__main__":
    main()
