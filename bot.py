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
    format_preview,
    format_relay_event,
    important_events,
    is_game_over,
    parse_game_summary,
    parse_relay_events,
    player_photo_url,
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


def process_relay(
    client: NaverSportsClient,
    telegram: TelegramBot,
    settings: Settings,
    state: dict[str, Any],
    game_id: str,
    away_name: str,
    home_name: str,
) -> bool:
    relay = unwrap(client.relay(game_id), "textRelayData")
    events = parse_relay_events(relay)
    if not events:
        return False

    last_seq = int(state.get("lastRelaySeq") or 0)
    if last_seq == 0 and not state.get("relayBootstrapped"):
        latest = events[-1]
        state.update(
            {
                "gameId": game_id,
                "inning": f"{latest.inning}회{latest.half}",
                "homeScore": latest.home_score,
                "awayScore": latest.away_score,
                "lastRelaySeq": latest.event_id,
                "relayBootstrapped": True,
                "updatedAt": datetime.now(settings.timezone).isoformat(),
            }
        )
        save_state(settings.state_path, state)
        telegram.send_message(
            "\n".join(
                [
                    "KIA 경기 중계 감시 시작",
                    f"{away_name} {latest.away_score} : {latest.home_score} {home_name}",
                    f"현재 {latest.inning}회{latest.half}",
                ]
            )
        )
        return False

    new_events = [event for event in important_events(events) if event.event_id > last_seq]

    for event in new_events:
        message = format_relay_event(event, away_name, home_name)
        photo = player_photo_url(event) if event.is_homer else None
        if photo:
            telegram.send_photo(photo, message)
        else:
            telegram.send_message(message)

    latest = events[-1]
    state.update(
        {
            "gameId": game_id,
            "inning": f"{latest.inning}회{latest.half}",
            "homeScore": latest.home_score,
            "awayScore": latest.away_score,
            "lastRelaySeq": max(last_seq, max(event.event_id for event in events)),
            "updatedAt": datetime.now(settings.timezone).isoformat(),
        }
    )
    save_state(settings.state_path, state)
    return is_game_over(events)


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

            send_preview_once(client, telegram, settings, state, summary.game_id)
            game_over = process_relay(
                client,
                telegram,
                settings,
                state,
                summary.game_id,
                summary.away_name or "원정",
                summary.home_name or "홈",
            )
            if game_over and state.get("gameOverSentGameId") != summary.game_id:
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
