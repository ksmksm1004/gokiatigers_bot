"""Korean Series score-only coverage, independent of KIA's offseason mode."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from naver_api import unwrap
from stove_news import article_id, article_time, clean_text


LIVE = {"2", "STARTED", "LIVE", "PLAYING"}
FINAL = {"4", "RESULT", "END", "ENDED"}
CANCELLED = {"CANCEL", "CANCELED", "CANCELLED"}


def is_korean_series_game(game):
    return (str(game.get("roundCode") or "").lower() == "kbo_ps_ks"
            or str(game.get("gameFlag") or "") == "7"
            or str(game.get("gameId") or "").startswith("7777"))


def involves_team(game, team_code):
    if team_code in (game.get("homeTeamCode"), game.get("awayTeamCode"),
                     game.get("hCode"), game.get("aCode")):
        return True
    # Calendar/detail cache records may contain only Naver's encoded game ID.
    match = re.match(r"^7777\d{4}([A-Z]{2})([A-Z]{2})\d{5}$", str(game.get("gameId") or ""))
    return bool(match and team_code in match.groups())


def is_score_only_series_game(game, team_code="HT"):
    return is_korean_series_game(game) and not involves_team(game, team_code)


def _queue(record, key, message):
    if key not in record.setdefault("events", {}):
        record["events"][key] = {"message": message, "deliveredChats": []}


def _deliver(record, telegram, settings, persist):
    for event in record.get("events", {}).values():
        for chat in settings.all_telegram_chat_ids:
            if chat in event["deliveredChats"]:
                continue
            try:
                telegram.for_chat(chat).send_message(event["message"])
            except Exception:
                logging.exception("Korean Series message delivery failed.")
                continue
            event["deliveredChats"].append(chat)
            persist()


def _news(client, record, now, persist):
    if not record.get("finished") or record.get("newsDone"):
        return
    if now < datetime.fromisoformat(record["newsDueAt"]):
        return
    record["newsAttempts"] = record.get("newsAttempts", 0) + 1
    record["newsDueAt"] = (now + timedelta(minutes=10)).isoformat()
    persist()
    try:
        rows = unwrap(client.game_news(record["gameId"], page_size=20), "newsList")
        if not isinstance(rows, list):
            raise ValueError("Unexpected game news response")
        start = datetime.fromisoformat(record["finishedAt"]) - timedelta(hours=6)
        game_start = article_time({"dateTime": record.get("startedAt")}, now.tzinfo)
        if game_start:
            start = max(start, game_start)
        articles, seen = [], set()
        for article in sorted(rows, key=lambda a: str(a.get("dateTime") or ""), reverse=True):
            key = article_id(article)
            published = article_time(article, now.tzinfo)
            if not key or key in seen or not published or not start <= published <= now:
                continue
            seen.add(key)
            articles.append(article)
            if len(articles) == 3:
                break
        if articles:
            lines = [f"{record['label']} 관련 기사"]
            for a in articles:
                lines.extend([clean_text(a.get("title"))[:500],
                              f"https://m.sports.naver.com/kbaseball/article/{article_id(a)}"])
            _queue(record, "news", "\n".join(lines))
            record["newsDone"] = True
    except Exception:
        logging.exception("Korean Series postgame news lookup failed for %s.", record["gameId"])
    if record["newsAttempts"] >= 3:
        record["newsDone"] = True
    persist()


def poll_korean_series(client, telegram, settings, state, now, persist):
    tracking = state.setdefault("koreanSeriesWatch", {"games": {}})
    due = tracking.get("nextPollAt")
    if due and now < datetime.fromisoformat(due):
        return
    tracking["nextPollAt"] = (now + timedelta(seconds=max(5, settings.poll_seconds))).isoformat()
    persist()
    # Discover Korean Series games only in autumn, or continue already tracked games.
    if 9 <= now.month <= 11 and tracking.get("completedSeason") != now.year:
        schedule_due = tracking.get("nextScheduleCheckAt")
        if not schedule_due or now >= datetime.fromisoformat(schedule_due):
            tracking["nextScheduleCheckAt"] = (now + timedelta(hours=6)).isoformat()
            persist()
            try:
                for game in client.games_on(now.date()):
                    if is_score_only_series_game(game, settings.team_code):
                        gid = str(game["gameId"])
                        tracking["games"].setdefault(gid, {"gameId": gid, "date": now.date().isoformat()})
                persist()
            except Exception:
                logging.exception("Korean Series schedule lookup failed.")
    for gid, record in list(tracking["games"].items()):
        if involves_team(record, settings.team_code):
            # Drop any KIA records left by the former all-team score-only policy.
            del tracking["games"][gid]
            persist()
            continue
        _deliver(record, telegram, settings, persist)
        if record.get("finished"):
            _news(client, record, now, persist)
            _deliver(record, telegram, settings, persist)
            continue
        check_due = record.get("nextCheckAt")
        if check_due and now < datetime.fromisoformat(check_due):
            continue
        record["nextCheckAt"] = (now + timedelta(seconds=max(5, settings.poll_seconds))).isoformat()
        persist()
        try:
            game = unwrap(client.game_detail(gid), "game")
            if not is_score_only_series_game(game, settings.team_code):
                del tracking["games"][gid]
                persist()
                continue
            record["homeTeamCode"] = game.get("homeTeamCode")
            record["awayTeamCode"] = game.get("awayTeamCode")
            status = str(game.get("statusCode") or "").upper()
            if status in CANCELLED or game.get("cancel"):
                record.update(finished=True, newsDone=True)
                persist()
                continue
            if status not in LIVE | FINAL:
                record["nextCheckAt"] = (now + timedelta(minutes=5)).isoformat()
                persist()
                continue
            away, home = game.get("awayTeamScore"), game.get("homeTeamScore")
            if away is None or home is None:
                continue
            away, home = int(away), int(home)
            if away < 0 or home < 0:
                continue
            a_name, h_name = game.get("awayTeamName") or "원정", game.get("homeTeamName") or "홈"
            number = game.get("seriesGameNo")
            if game.get("gameDateTime"):
                record["startedAt"] = game["gameDateTime"]
            label = "한국시리즈" + (f" {number}차전" if number else "")
            record["label"] = label
            scoreboard = f"{a_name} {away} : {home} {h_name}"
            previous = record.get("score")
            if previous is None:
                logging.info("Korean Series score baseline set for %s: %s.", gid, scoreboard)
            if previous is not None and away + home > sum(previous):
                inning = str(game.get("currentInning") or game.get("statusInfo") or "")
                _queue(record, f"score:{away}:{home}", f"{label} 득점 | {inning}\n{scoreboard}")
                logging.info("Korean Series scoring update queued for %s: %s.", gid, scoreboard)
            record["score"] = [away, home]
            if status in FINAL:
                winner = f"{a_name} 승리" if away > home else f"{h_name} 승리" if home > away else "무승부"
                lines = [f"{label} 경기 종료", scoreboard, winner]
                outcome = game.get("latestSeriesOutcome") or {}
                if outcome:
                    a_wins, h_wins = int(outcome.get("away") or 0), int(outcome.get("home") or 0)
                    lines.append(f"시리즈 전적: {a_name} {a_wins}승 : {h_name} {h_wins}승")
                    if max(a_wins, h_wins) >= 4:
                        tracking["completedSeason"] = now.year
                _queue(record, "result", "\n".join(lines))
                record.update(finished=True, finishedAt=now.isoformat(),
                              newsDueAt=(now + timedelta(minutes=10)).isoformat(), newsAttempts=0)
                logging.info("Korean Series final result queued for %s; news check due %s.", gid, record["newsDueAt"])
            persist()
            _deliver(record, telegram, settings, persist)
        except Exception:
            logging.exception("Korean Series score polling failed for %s.", gid)
    # Keep only the current and previous season's small set of game records.
    for gid in list(tracking["games"]):
        record = tracking["games"][gid]
        if record.get("finished") and int(record.get("date", str(now.year))[:4]) < now.year - 1:
            del tracking["games"][gid]
    future_checks = []
    if 9 <= now.month <= 11 and tracking.get("completedSeason") != now.year:
        if tracking.get("nextScheduleCheckAt"):
            future_checks.append(datetime.fromisoformat(tracking["nextScheduleCheckAt"]))
    for record in tracking["games"].values():
        if not record.get("finished") and record.get("nextCheckAt"):
            future_checks.append(datetime.fromisoformat(record["nextCheckAt"]))
        if record.get("finished") and not record.get("newsDone"):
            future_checks.append(datetime.fromisoformat(record["newsDueAt"]))
        if any(any(chat not in event["deliveredChats"] for chat in settings.all_telegram_chat_ids)
               for event in record.get("events", {}).values()):
            future_checks.append(now + timedelta(seconds=30))
    tracking["nextPollAt"] = min(future_checks or [now + timedelta(hours=1)]).isoformat()
    persist()
