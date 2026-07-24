import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from bot import (
    dispatch_relay_events,
    final_score_from_record,
    finish_stopped_relay_game_if_done,
    format_team_schedule,
    option_from_callback_data,
    process_relay,
    record_options_keyboard,
    resume_relay_for_game,
    send_due_kia_news,
    send_game_end_record_once,
    send_kia_news_command,
)
from config import Settings


class FakeClient:
    def __init__(self, record=None, relay=None, games=None, game_news=None, section_news=None, relay_by_inning=None):
        self._record = record
        self._relay = relay or {"textRelays": []}
        self._relay_by_inning = relay_by_inning or {}
        self._games = games or []
        self._game_news = game_news or []
        self._section_news = section_news or []
        self.record_calls = 0

    def record(self, game_id):
        self.record_calls += 1
        return {"result": {"recordData": self._record}}

    def relay(self, game_id, inning=None):
        relay = self._relay_by_inning.get(inning, self._relay)
        return {"result": {"textRelayData": relay}}

    def games_on(self, day):
        return self._games

    def game_news(self, game_id, page_size=10):
        return {"result": {"newsList": self._game_news}}

    def section_news(self, section_id="kbaseball", page_size=40, date_yyyymmdd=None):
        return {"result": {"newsList": self._section_news}}


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.reply_markups = []

    def send_message(self, text, reply_markup=None):
        self.messages.append(text)
        self.reply_markups.append(reply_markup)

    def send_photo(self, photo_url, caption):
        self.photos.append((photo_url, caption))
        self.messages.append(caption)


class RecordOptionCallbackTest(unittest.TestCase):
    def test_record_options_keyboard_uses_short_callback_data(self):
        keyboard = record_options_keyboard("hitter")

        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "타율")
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "rec:hitter:0")
        self.assertEqual(option_from_callback_data("rec:hitter:1"), ("hitter", "홈런"))


class KiaNewsScheduleTest(unittest.TestCase):
    def test_game_end_record_schedules_and_sends_kia_news(self):
        record = {
            "gameInfo": {"aName": "한화", "hName": "KIA", "aCode": "HH", "hCode": "HT"},
            "battersBoxscore": {"awayTotal": {"run": 7}, "homeTotal": {"run": 3}, "away": [], "home": []},
            "teamPitchingBoxscore": {"home": {}},
            "pitchingResult": [
                {"name": "화이트", "wls": "W"},
                {"name": "올러", "wls": "L"},
            ],
            "pitchersBoxscore": {"away": [], "home": []},
        }
        game_news = [
            {
                "oid": "109",
                "aid": "1",
                "title": "KIA 경기 후속 기사",
                "sourceName": "OSEN",
                "sportsSection": "kbaseball",
            }
        ]

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            state = {}
            telegram = FakeTelegram()
            client = FakeClient(record, game_news=game_news)

            send_game_end_record_once(client, telegram, settings, state, "game1", "한화", "KIA", 7, 3)
            state["nextKiaNewsAt"] = datetime(2026, 7, 22, 23, 0, tzinfo=settings.timezone).isoformat()
            sent = send_due_kia_news(
                client,
                telegram,
                settings,
                state,
                datetime(2026, 7, 22, 23, 1, tzinfo=settings.timezone),
            )

        self.assertTrue(sent)
        joined = "\n".join(telegram.messages)
        self.assertIn("KIA 주요 기사", joined)
        self.assertIn("KIA 경기 후속 기사", joined)
        self.assertEqual(state["kiaNewsSentGameId"], "game1")
        self.assertNotIn("nextKiaNewsAt", state)

    def test_news_command_sends_up_to_ten_deduplicated_articles(self):
        section_news = [
            {
                "oid": f"{idx:03d}",
                "aid": str(idx),
                "title": f"KIA 기사 {idx}",
                "sourceName": "OSEN",
                "sportsSection": "kbaseball",
            }
            for idx in range(12)
        ]
        section_news.append(section_news[0].copy())

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            telegram = FakeTelegram()
            send_kia_news_command(FakeClient(section_news=section_news), telegram, settings, None)

        message = telegram.messages[-1]
        self.assertIn("KIA 주요 기사", message)
        self.assertIn("10. KIA 기사 9", message)
        self.assertNotIn("11. KIA 기사 10", message)


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
                "away": [{"name": "네일", "result": "패"}],
                "home": [
                    {"name": "나균안", "result": "승"},
                    {"name": "전상현", "result": "홀"},
                    {"name": "정해영", "result": "세"},
                ],
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
        joined = "\n".join(telegram.messages)
        self.assertIn("중계 | 경기종료", joined)
        self.assertIn("KIA 3 : 11 롯데", joined)
        self.assertIn("승리투수: 나균안", joined)
        self.assertIn("패전투수: 네일", joined)
        self.assertIn("세이브: 정해영", joined)
        self.assertIn("홀드: 전상현", joined)

    def test_pitching_decisions_use_pitching_result_when_boxscore_wls_is_empty(self):
        record = {
            "gameInfo": {"aName": "한화", "hName": "KIA", "aCode": "HH", "hCode": "HT"},
            "battersBoxscore": {
                "awayTotal": {"run": 7},
                "homeTotal": {"run": 3},
                "away": [],
                "home": [],
            },
            "teamPitchingBoxscore": {"home": {}},
            "pitchingResult": [
                {"pCode": "55633", "name": "올러", "wls": "L"},
                {"pCode": "56724", "name": "화이트", "wls": "W"},
            ],
            "pitchersBoxscore": {
                "away": [{"name": "화이트", "wls": ""}],
                "home": [{"name": "올러", "wls": ""}],
            },
        }

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            telegram = FakeTelegram()
            send_game_end_record_once(
                FakeClient(record),
                telegram,
                settings,
                {},
                "game1",
                "한화",
                "KIA",
                7,
                3,
            )

        joined = "\n".join(telegram.messages)
        self.assertIn("승리투수: 화이트", joined)
        self.assertIn("패전투수: 올러", joined)
        self.assertIn("올러 패 |", joined)

    def test_game_end_record_waits_until_win_and_loss_decisions_are_ready(self):
        incomplete_record = {
            "gameInfo": {"aName": "한화", "hName": "KIA", "aCode": "HH", "hCode": "HT"},
            "battersBoxscore": {
                "awayTotal": {"run": 9},
                "homeTotal": {"run": 3},
                "away": [],
                "home": [],
            },
            "teamPitchingBoxscore": {"home": {}},
            "pitchingResult": [],
            "pitchersBoxscore": {
                "away": [{"name": "왕옌청", "wls": ""}],
                "home": [{"name": "시라카와", "wls": ""}],
            },
        }

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            state = {}
            telegram = FakeTelegram()
            client = FakeClient(incomplete_record)

            sent = send_game_end_record_once(
                client,
                telegram,
                settings,
                state,
                "game1",
                "한화",
                "KIA",
                9,
                3,
            )

            self.assertFalse(sent)
            self.assertIn("중계 | 경기종료", "\n".join(telegram.messages))
            self.assertIn("KIA 경기 기록", "\n".join(telegram.messages))
            self.assertEqual(state["recordSentGameId"], "game1")
            self.assertNotIn("pitchingDecisionsSentGameId", state)

            client._record["pitchingResult"] = [
                {"name": "왕옌청", "wls": "W"},
                {"name": "시라카와", "wls": "L"},
            ]
            sent = send_game_end_record_once(
                client,
                telegram,
                settings,
                state,
                "game1",
                "한화",
                "KIA",
                9,
                3,
            )

        self.assertTrue(sent)
        self.assertEqual(state["recordSentGameId"], "game1")
        self.assertEqual(state["pitchingDecisionsSentGameId"], "game1")
        self.assertEqual(sum("KIA 경기 기록" in message for message in telegram.messages), 1)
        joined = "\n".join(telegram.messages)
        self.assertIn("승리투수: 왕옌청", joined)
        self.assertIn("패전투수: 시라카와", joined)

    def test_already_sent_record_only_sends_missing_pitching_decisions(self):
        record = {
            "gameInfo": {"aName": "한화", "hName": "KIA", "aCode": "HH", "hCode": "HT"},
            "battersBoxscore": {
                "awayTotal": {"run": 9},
                "homeTotal": {"run": 3},
                "away": [],
                "home": [],
            },
            "teamPitchingBoxscore": {"home": {}},
            "pitchingResult": [
                {"name": "왕옌청", "wls": "W"},
                {"name": "시라카와", "wls": "L"},
            ],
            "pitchersBoxscore": {"away": [], "home": []},
        }

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            state = {"recordSentGameId": "game1", "gameOverSentGameId": "game1"}
            telegram = FakeTelegram()

            sent = send_game_end_record_once(
                FakeClient(record),
                telegram,
                settings,
                state,
                "game1",
                "한화",
                "KIA",
                9,
                3,
            )

        self.assertTrue(sent)
        self.assertEqual(len(telegram.messages), 1)
        self.assertIn("승리투수: 왕옌청", telegram.messages[0])
        self.assertIn("패전투수: 시라카와", telegram.messages[0])
        self.assertNotIn("KIA 경기 기록", telegram.messages[0])

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
            state["dailyRankingSentDate"] = datetime.now(settings.timezone).date().isoformat()
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


class KiaHalfSummaryTest(unittest.TestCase):
    def test_process_relay_loads_previous_inning_for_home_kia_summary(self):
        current_relay = {
            "homeLineup": {
                "batter": [
                    {
                        "pcode": "3",
                        "name": "김도영",
                        "batOrder": 3,
                        "seasonHra": "0.294",
                        "ab": 2,
                        "run": 1,
                        "hit": 1,
                        "bb": 1,
                    },
                    {
                        "pcode": "4",
                        "name": "나성범",
                        "batOrder": 4,
                        "seasonHra": "0.298",
                        "ab": 2,
                        "run": 1,
                        "hit": 1,
                        "rbi": 3,
                        "hr": 1,
                        "bb": 1,
                        "kk": 1,
                    },
                ]
            },
            "textRelays": [
                {
                    "inn": 9,
                    "homeOrAway": "0",
                    "title": "9회초 키움 공격",
                    "textOptions": [
                        {
                            "seqno": 508,
                            "text": "9회초 키움 공격",
                            "currentGameState": {
                                "awayScore": 1,
                                "homeScore": 4,
                                "batter": "away-1",
                            },
                        }
                    ],
                }
            ],
        }
        previous_relay = {
            "textRelays": [
                {
                    "inn": 8,
                    "homeOrAway": "1",
                    "title": "3번타자 김도영",
                    "textOptions": [
                        {
                            "seqno": 500,
                            "text": "김도영 : 우익수 앞 1루타",
                            "currentGameState": {
                                "awayScore": 1,
                                "homeScore": 4,
                                "batter": "3",
                            },
                        }
                    ],
                },
                {
                    "inn": 8,
                    "homeOrAway": "1",
                    "title": "4번타자 나성범",
                    "textOptions": [
                        {
                            "seqno": 507,
                            "text": "나성범 : 삼진 아웃",
                            "currentGameState": {
                                "awayScore": 1,
                                "homeScore": 4,
                                "batter": "4",
                            },
                        }
                    ],
                },
            ]
        }

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            state = {
                "lastRelaySeq": 507,
                "relayBootstrapped": True,
                "kiaHalfSummariesSent": [],
            }
            telegram = FakeTelegram()
            client = FakeClient(relay=current_relay, relay_by_inning={8: previous_relay})

            process_relay(
                client,
                telegram,
                settings,
                state,
                "game1",
                "키움",
                "KIA",
                "WO",
                "HT",
            )

        joined = "\n".join(telegram.messages)
        self.assertIn("KIA 공격 종료 | 8회말", joined)
        self.assertIn("키움 1 : 4 KIA", joined)
        self.assertIn("3 김도영 | .294 | 2타수 1득점 1안타 1볼넷", joined)
        self.assertIn("4 나성범 | .298 | 2타수 1득점 1안타 3타점 1홈런 1볼넷 1삼진", joined)
        self.assertIn("9초", state["kiaHalfSummariesSent"])


class RelayPlateHistoryStateTest(unittest.TestCase):
    def test_dispatch_uses_state_history_and_fixes_stale_plate_totals(self):
        relay = {
            "homeLineup": {
                "batter": [
                    {
                        "pcode": "5",
                        "name": "한준수",
                        "batOrder": 5,
                        "seasonHra": "0.316",
                        "ab": 1,
                        "hit": 1,
                        "rbi": 3,
                    }
                ]
            }
        }
        events = [
            SimpleNamespace(
                event_id=1,
                inning=1,
                half="말",
                text="한준수 : 우익수 뒤 홈런 (홈런거리:120M)",
                home_score=2,
                away_score=1,
                batter_code="5",
                player_code="5",
                player_name="한준수",
                home_or_away="1",
                batter_record=None,
                player_info=None,
                current_state={},
                title="1회말",
                is_attack_start=False,
                is_score_event=True,
                is_pitching_change=False,
                is_game_marker=False,
                is_plate_result=True,
            ),
            SimpleNamespace(
                event_id=2,
                inning=3,
                half="말",
                text="한준수 : 우익수 앞 1루타",
                home_score=6,
                away_score=1,
                batter_code="5",
                player_code="5",
                player_name="한준수",
                home_or_away="1",
                batter_record=None,
                player_info=None,
                current_state={},
                title="3회말",
                is_attack_start=False,
                is_score_event=False,
                is_pitching_change=False,
                is_game_marker=False,
                is_plate_result=True,
            ),
        ]
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)
        telegram = FakeTelegram()
        state = {}

        dispatch_relay_events(telegram, settings, state, relay, events, events, set(), "한화", "KIA", "HH", "HT")

        self.assertIn("5 한준수 | .316 | 2-2 | 홈런(타점3) 안타", telegram.messages[-1])

    def test_dispatch_records_simple_outs_without_sending_until_next_relevant_result(self):
        relay = {
            "homeLineup": {
                "batter": [
                    {
                        "pcode": "7",
                        "name": "김호령",
                        "batOrder": 7,
                        "seasonHra": "0.282",
                        "ab": 0,
                        "hit": 0,
                        "rbi": 0,
                    }
                ]
            }
        }
        events = [
            SimpleNamespace(
                event_id=1,
                inning=1,
                half="말",
                text="김호령 : 중견수 플라이 아웃",
                home_score=4,
                away_score=1,
                batter_code="7",
                player_code="7",
                player_name="김호령",
                home_or_away="1",
                batter_record=None,
                player_info=None,
                current_state={},
                title="1회말",
                is_attack_start=False,
                is_score_event=False,
                is_pitching_change=False,
                is_game_marker=False,
                is_plate_result=True,
            ),
            SimpleNamespace(
                event_id=2,
                inning=3,
                half="말",
                text="김호령 : 3루수 병살타로 출루",
                home_score=6,
                away_score=1,
                batter_code="7",
                player_code="7",
                player_name="김호령",
                home_or_away="1",
                batter_record=None,
                player_info=None,
                current_state={},
                title="3회말",
                is_attack_start=False,
                is_score_event=False,
                is_pitching_change=False,
                is_game_marker=False,
                is_plate_result=True,
            ),
            SimpleNamespace(
                event_id=3,
                inning=6,
                half="말",
                text="김호령 : 우익수 앞 안타",
                home_score=6,
                away_score=1,
                batter_code="7",
                player_code="7",
                player_name="김호령",
                home_or_away="1",
                batter_record={"name": "김호령", "batOrder": 7, "seasonHra": "0.282", "ab": 3, "hit": 1, "rbi": 0},
                player_info=None,
                current_state={},
                title="6회말",
                is_attack_start=False,
                is_score_event=False,
                is_pitching_change=False,
                is_game_marker=False,
                is_plate_result=True,
            ),
        ]
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)
        telegram = FakeTelegram()
        state = {}

        dispatch_relay_events(telegram, settings, state, relay, events, events, set(), "한화", "KIA", "HH", "HT")

        self.assertEqual(len(telegram.messages), 1)
        self.assertIn("7 김호령 | .282 | 1-3 | 플라이 병살타 안타", telegram.messages[0])


if __name__ == "__main__":
    unittest.main()
