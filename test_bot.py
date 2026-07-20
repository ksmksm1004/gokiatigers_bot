import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from bot import (
    final_score_from_record,
    finish_stopped_relay_game_if_done,
    format_team_schedule,
    resume_relay_for_game,
    send_game_end_record_once,
)
from config import Settings


class FakeClient:
    def __init__(self, record=None, relay=None, games=None):
        self._record = record
        self._relay = relay or {"textRelays": []}
        self._games = games or []
        self.record_calls = 0

    def record(self, game_id):
        self.record_calls += 1
        return {"result": {"recordData": self._record}}

    def relay(self, game_id):
        return {"result": {"textRelayData": self._relay}}

    def games_on(self, day):
        return self._games


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send_message(self, text):
        self.messages.append(text)


class FinalScoreTest(unittest.TestCase):
    def test_final_score_prefers_record_totals_over_stale_state_score(self):
        record = {
            "gameInfo": {"aName": "KIA", "hName": "롯데", "aCode": "HT", "hCode": "LT"},
            "battersBoxscore": {
                "awayTotal": {"run": 3},
                "homeTotal": {"run": 11},
                "away": [],
                "home": [],
            },
            "teamPitchingBoxscore": {"away": {}},
            "pitchersBoxscore": {
                "away": [{"name": "네일", "wls": "패"}],
                "home": [{"name": "나균안", "wls": "승"}],
            },
        }

        self.assertEqual(final_score_from_record(record, 0, 5), (3, 11))

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            telegram = FakeTelegram()
            sent = send_game_end_record_once(
                FakeClient(record),
                telegram,
                settings,
                {},
                "game1",
                "KIA",
                "롯데",
                0,
                5,
            )

        self.assertTrue(sent)
        self.assertIn("KIA 3 : 11 롯데", "\n".join(telegram.messages))

    def test_stopped_relay_does_not_send_record_before_relay_game_over(self):
        record = {
            "gameInfo": {"aName": "KIA", "hName": "SSG", "aCode": "HT", "hCode": "SK"},
            "battersBoxscore": {"awayTotal": {"run": 0}, "homeTotal": {"run": 6}, "away": [], "home": []},
            "teamPitchingBoxscore": {"away": {}},
            "pitchersBoxscore": {"away": [], "home": []},
        }
        relay = {
            "textRelays": [
                {
                    "inn": 9,
                    "homeOrAway": "0",
                    "title": "9회초",
                    "textOptions": [
                        {"seqno": 1, "text": "한준수 : 볼넷", "currentGameState": {"awayScore": 0, "homeScore": 6}}
                    ],
                }
            ]
        }
        client = FakeClient(
            record,
            relay,
            [{"gameId": "game1", "awayTeamCode": "HT", "homeTeamCode": "SK", "statusCode": "BEFORE"}],
        )
        telegram = FakeTelegram()
        state = {"relayStoppedGameId": "game1"}
        summary = SimpleNamespace(game_id="game1", away_name="KIA", home_name="SSG")

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            handled = finish_stopped_relay_game_if_done(
                client,
                telegram,
                settings,
                state,
                summary,
                {"gameId": "game1", "statusCode": "BEFORE"},
                datetime(2026, 7, 16, 21, 19, tzinfo=settings.timezone),
            )

        self.assertTrue(handled)
        self.assertEqual(client.record_calls, 0)
        self.assertNotIn("recordSentGameId", state)
        self.assertEqual(telegram.messages, [])

    def test_resume_clears_premature_game_over_flags_when_game_is_live(self):
        relay = {
            "textRelays": [
                {
                    "inn": 9,
                    "homeOrAway": "0",
                    "title": "9회초",
                    "textOptions": [
                        {"seqno": 20, "text": "한준수 : 볼넷", "currentGameState": {"awayScore": 0, "homeScore": 6}}
                    ],
                }
            ]
        }
        state = {
            "relayStoppedGameId": "game1",
            "recordSentGameId": "game1",
            "gameOverSentGameId": "game1",
            "dailyRankingSentDate": "2026-07-20",
        }
        telegram = FakeTelegram()

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            resume_relay_for_game(FakeClient(relay=relay), telegram, settings, state, "game1")

        self.assertNotIn("relayStoppedGameId", state)
        self.assertNotIn("recordSentGameId", state)
        self.assertNotIn("gameOverSentGameId", state)
        self.assertNotIn("dailyRankingSentDate", state)
        self.assertEqual(state["lastRelaySeq"], 20)


class TeamScheduleTest(unittest.TestCase):
    def test_format_team_schedule_groups_consecutive_matchups(self):
        games = [
            {"date": date(2026, 7, 9), "awayCode": "HT", "homeCode": "LT"},
            {"date": date(2026, 7, 16), "awayCode": "HT", "homeCode": "SK"},
            {"date": date(2026, 7, 17), "awayCode": "HT", "homeCode": "SK"},
            {"date": date(2026, 7, 18), "awayCode": "HT", "homeCode": "SK"},
            {"date": date(2026, 7, 19), "awayCode": "HT", "homeCode": "SK"},
            {"date": date(2026, 7, 21), "awayCode": "HH", "homeCode": "HT"},
            {"date": date(2026, 7, 22), "awayCode": "HH", "homeCode": "HT"},
            {"date": date(2026, 7, 23), "awayCode": "HH", "homeCode": "HT"},
            {"date": date(2026, 7, 24), "awayCode": "WO", "homeCode": "HT"},
            {"date": date(2026, 7, 25), "awayCode": "WO", "homeCode": "HT"},
            {"date": date(2026, 7, 26), "awayCode": "WO", "homeCode": "HT"},
            {"date": date(2026, 7, 28), "awayCode": "HT", "homeCode": "OB"},
        ]

        message = format_team_schedule(games, "HT")

        self.assertEqual(
            message,
            "\n".join(
                [
                    "KIA 경기 일정",
                    "",
                    "KIA vs 롯데 7/9",
                    "KIA vs SSG 7/16 - 7/19",
                    "한화 vs KIA 7/21 - 7/23",
                    "키움 vs KIA 7/24 - 7/26",
                ]
            ),
        )
        self.assertNotIn("두산", message)


if __name__ == "__main__":
    unittest.main()
