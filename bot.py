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
    format_kia_record,
    format_pitching_decisions,
    format_preview,
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


def should_poll_game(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return True
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return start_at - timedelta(minutes=settings.pregame_minutes) <= now <= start_at + timedelta(hours=5, minutes=settings.postgame_minutes)


def is_before_game_start(summary, settings: Settings, now: datetime) -> bool:
    if summary.start_at is None:
        return False
    if summary.start_at.tzinfo is None:
        start_at = summary.start_at.replace(tzinfo=settings.timezone)
    else:
        start_at = summary.start_at.astimezone(settings.timezone)
    return now < start_at


def send_preview_once(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
) -> None:
    if state.get("previewSentGameId") == game_id:
        return
    preview = unwrap(client.preview(game_id), "previewData")
    telegram.send_message(format_preview(preview, game_id))
    state["previewSentGameId"] = game_id
    save_state(settings.state_path, state)


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
        telegram.send_message("아직 선발 라인업이 발표되지 않았습니다.")
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
    game_id: str,
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
            if command == "/라인업":
                send_lineup(client, telegram, game_id)
            elif command == "/기록":
                send_kia_record(client, telegram, game_id, settings.team_code)
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
    decisions = format_pitching_decisions(record, away_name, home_name, away_score, home_score)
    if decisions:
        telegram.send_message(decisions)
    telegram.send_message(format_kia_record(record, settings.team_code))
    state["recordSentGameId"] = game_id
    save_state(settings.state_path, state)


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    client = NaverSportsClient()
    telegram = TelegramBot(settings.telegram_token, settings.telegram_chat_id, settings.dry_run)
    state = load_state(settings.state_path)

    logging.info("KIA Telegram bot started. dry_run=%s", settings.dry_run)

    while True:
        try:
            now = datetime.now(settings.timezone)
            game = find_today_kia_game(client, settings, now)

            if not game:
                logging.info("No KIA game found today. Sleeping %ss.", settings.idle_poll_seconds)
                time.sleep(settings.idle_poll_seconds)
                continue

            summary = parse_game_summary(game, settings.naver_game_id)
            if not summary.game_id:
                logging.warning("KIA game found but gameId is missing: %s", game)
                time.sleep(settings.idle_poll_seconds)
                continue

            if state.get("gameId") != summary.game_id:
                state = {"gameId": summary.game_id}
                save_state(settings.state_path, state)

            if not should_poll_game(summary, settings, now):
                logging.info("KIA game %s is outside polling window. Sleeping.", summary.game_id)
                time.sleep(settings.idle_poll_seconds)
                continue

            handle_telegram_commands(client, telegram, settings, state, summary.game_id)
            send_preview_once(client, telegram, settings, state, summary.game_id)
            if is_before_game_start(summary, settings, now):
                try:
                    send_lineup_once(client, telegram, settings, state, summary.game_id)
                except Exception:
                    logging.exception("Lineup check failed. Continuing relay polling.")
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
                time.sleep(settings.idle_poll_seconds)
            else:
                time.sleep(settings.poll_seconds)

        except KeyboardInterrupt:
            logging.info("Stopped by user.")
            raise
        except Exception:
            logging.exception("Loop failed.")
            time.sleep(min(settings.idle_poll_seconds, 60))


if __name__ == "__main__":
    main()
