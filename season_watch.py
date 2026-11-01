"""Pause automatic game polling over winter while other bot features keep running."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta


def start_offseason(state, ended_year, timezone, persist):
    first_check = datetime(ended_year + 1, 3, 1, 9, tzinfo=timezone)
    state["seasonWatch"] = {
        "mode": "offseason", "endedSeason": ended_year,
        "firstCheckAt": first_check.isoformat(),
        "nextScheduleCheckAt": first_check.isoformat(),
    }
    for key in ("nextGamePendingDate", "nextGameScheduleCheckAt", "nextScheduleCheckAt",
                "dailyRankingTargetDate", "nextDailyRankingCheckAt"):
        state.pop(key, None)
    persist()


def automatic_games_paused(state):
    return state.get("seasonWatch", {}).get("mode") == "offseason"


def _resume(state, now, persist):
    watch = state["seasonWatch"]
    watch["mode"] = "active"
    watch["resumedAt"] = now.isoformat()
    watch.pop("nextScheduleCheckAt", None)
    # Resolve the current season from scratch, without last year's cached game.
    for key in ("scheduledGame", "scheduleDate", "detailedGame", "detailedGameId",
                "nextScheduleCheckAt", "nextGameDetailRetryAt"):
        state.pop(key, None)
    persist()
    logging.info("New KIA season game day reached; normal game polling resumed.")


def wait_for_new_season(client, settings, state, now, persist):
    """Return True while automatic game queries should remain paused."""
    if not automatic_games_paused(state):
        return False
    watch = state["seasonWatch"]
    first_check = datetime.fromisoformat(watch["firstCheckAt"])
    if now < first_check:
        return True
    first_game = watch.get("firstGameDate")
    if first_game and now.date() >= date.fromisoformat(first_game):
        _resume(state, now, persist)
        return False
    next_check = datetime.fromisoformat(watch["nextScheduleCheckAt"])
    if now < next_check:
        return True
    # Failed API requests also wait until the next weekly check.
    watch["lastScheduleCheckAt"] = now.isoformat()
    watch["nextScheduleCheckAt"] = (now + timedelta(days=7)).isoformat()
    persist()
    month = now.date().replace(day=1)
    following_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    try:
        games = client.games_in_month(month) + client.games_in_month(following_month)
    except Exception:
        logging.exception("Weekly KIA new-season schedule check failed; game polling stays paused.")
        return True
    candidates = []
    for game in games:
        if settings.team_code not in (game.get("homeTeamCode"), game.get("awayTeamCode")):
            continue
        if str(game.get("statusCode") or "").upper() in {
            "4", "RESULT", "END", "ENDED", "CANCEL", "CANCELED", "CANCELLED",
        } or game.get("cancel"):
            continue
        try:
            scheduled_date = date.fromisoformat(str(game.get("gameDate") or ""))
        except ValueError:
            continue
        if scheduled_date >= now.date():
            candidates.append((scheduled_date, str(game.get("gameId") or "")))
    if not candidates:
        watch.pop("firstGameDate", None)
        watch.pop("firstGameId", None)
        persist()
        logging.info("Weekly KIA new-season check: no future game registered; checking again in 7 days.")
        return True
    scheduled_date, game_id = min(candidates)
    watch["firstGameDate"] = scheduled_date.isoformat()
    watch["firstGameId"] = game_id
    game_day = datetime.combine(scheduled_date, time.min, tzinfo=settings.timezone)
    watch["nextScheduleCheckAt"] = min(now + timedelta(days=7), game_day).isoformat()
    persist()
    logging.info("New KIA season schedule found: %s (%s); waiting until game day.", scheduled_date, game_id)
    if scheduled_date == now.date():
        _resume(state, now, persist)
        return False
    return True
