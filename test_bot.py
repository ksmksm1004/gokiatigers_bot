import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bot import (
    dispatch_relay_events,
    final_score_from_record,
    finish_stopped_relay_game_if_done,
    format_team_schedule,
    handle_telegram_commands,
    option_from_callback_data,
    player_from_callback_data,
    player_selection_keyboard,
    process_relay,
    record_options_keyboard,
    remember_plate_result,
    remember_plate_rbi_baseline,
    remember_plate_score,
    resolve_cancellation_reason,
    resume_relay_for_game,
    schedule_kia_highlight_after_rankings,
    send_lineup,
    send_lineup_once,
    send_daily_rankings_if_all_games_done,
    send_due_kia_shorts,
    send_due_kia_news,
    send_due_kia_highlight,
    send_game_end_record_once,
    send_kia_news_command,
    send_monthly_team_records,
    send_player_record_lookup,
    with_state_plate_totals,
)
from config import Settings
from kbo_api import KBOPlayerCandidate, KBOPlayerRecord
from parser import RelayEvent


class FakeClient:
    def __init__(
        self,
        record=None,
        relay=None,
        games=None,
        game_news=None,
        section_news=None,
        relay_by_inning=None,
        game_videos=None,
        monthly_games=None,
        preview=None,
    ):
        self._record = record
        self._relay = relay or {"textRelays": []}
        self._relay_by_inning = relay_by_inning or {}
        self._games = games or []
        self._game_news = game_news or []
        self._section_news = section_news or []
        self._game_videos = game_videos or []
        self._monthly_games = monthly_games or []
        self._preview = preview or {}
        self.monthly_game_dates = []
        self.record_calls = 0

    def record(self, game_id):
        self.record_calls += 1
        return {"result": {"recordData": self._record}}

    def preview(self, game_id):
        return {"result": {"previewData": self._preview}}

    def relay(self, game_id, inning=None):
        relay = self._relay_by_inning.get(inning, self._relay)
        return {"result": {"textRelayData": relay}}

    def games_on(self, day):
        return self._games

    def games_in_month(self, month):
        self.monthly_game_dates.append(month)
        return self._monthly_games

    def game_news(self, game_id, page_size=10):
        return {"result": {"newsList": self._game_news}}

    def game_videos(self, game_id):
        return {"result": {"vodList": self._game_videos}}

    def section_news(self, section_id="kbaseball", page_size=40, date_yyyymmdd=None):
        return {"result": {"newsList": self._section_news}}


class FakeTelegram:
    def __init__(self):
        self.messages = []
        self.photos = []
        self.reply_markups = []
        self.media_groups = []
        self.photo_files = []
        self.calls = []

    def send_message(self, text, reply_markup=None):
        self.messages.append(text)
        self.reply_markups.append(reply_markup)

    def send_photo(self, photo_url, caption):
        self.photos.append((photo_url, caption))
        self.messages.append(caption)

    def send_media_group(self, items):
        self.media_groups.append(items)
        self.calls.append("media_group")

    def send_photo_bytes(self, photo, caption, filename="photo.png"):
        self.photo_files.append((photo, caption, filename))
        self.calls.append("photo_bytes")


class FakeCommandTelegram(FakeTelegram):
    def __init__(self, updates):
        super().__init__()
        self.updates = updates
        self.answered_callbacks = []

    def get_updates(self, offset=None):
        return self.updates

    def answer_callback_query(self, callback_query_id):
        self.answered_callbacks.append(callback_query_id)


class LineupDefenseDeliveryTest(unittest.TestCase):
    @staticmethod
    def lineup(prefix):
        positions = [
            (None, "1", "선발투수"),
            (1, "7", "좌익수"),
            (2, "4", "2루수"),
            (3, "0", "지명타자"),
            (4, "3", "1루수"),
            (5, "9", "우익수"),
            (6, "5", "3루수"),
            (7, "2", "포수"),
            (8, "6", "유격수"),
            (9, "8", "중견수"),
        ]
        return [
            {
                "playerCode": f"{prefix}-{position}",
                "playerName": f"{prefix} 선수 {position}",
                "batorder": order,
                "position": position,
                "positionName": position_name,
            }
            for order, position, position_name in positions
        ]

    @classmethod
    def preview(cls):
        return {
            "gameInfo": {
                "aCode": "HT",
                "aName": "KIA",
                "hCode": "HH",
                "hName": "한화",
                "gdate": 20260820,
            },
            "awayTeamLineUp": {"fullLineUp": cls.lineup("KIA")},
            "homeTeamLineUp": {"fullLineUp": cls.lineup("한화")},
        }

    @patch("bot.time.sleep")
    @patch("bot.render_defensive_lineup_image", return_value=b"defense-png")
    def test_lineup_command_sends_both_face_groups_then_kia_defense(self, render_image, _sleep):
        telegram = FakeTelegram()

        send_lineup(FakeClient(preview=self.preview()), telegram, "game1")

        self.assertEqual(len(telegram.media_groups), 2)
        self.assertEqual(telegram.calls, ["media_group", "media_group", "photo_bytes"])
        self.assertEqual(
            telegram.photo_files,
            [(b"defense-png", "KIA 선발 수비", "kia-defense-20260820.png")],
        )
        render_image.assert_called_once()
        self.assertEqual(render_image.call_args.args[1], "away")

    @patch("bot.render_defensive_lineup_image", return_value=b"defense-png")
    def test_automatic_lineup_sends_defense_once_and_persists_state(self, render_image):
        telegram = FakeTelegram()
        state = {}
        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
            )
            client = FakeClient(preview=self.preview())

            send_lineup_once(client, telegram, settings, state, "game1")
            send_lineup_once(client, telegram, settings, state, "game1")

        self.assertEqual(len(telegram.media_groups), 2)
        self.assertEqual(len(telegram.photo_files), 1)
        self.assertEqual(render_image.call_count, 1)
        self.assertEqual(state["lineupAwaySentGameId"], "game1")
        self.assertEqual(state["lineupHomeSentGameId"], "game1")
        self.assertEqual(state["lineupDefenseSentGameId"], "game1")
        self.assertEqual(state["lineupSentGameId"], "game1")


class RecordOptionCallbackTest(unittest.TestCase):
    def test_record_options_keyboard_uses_short_callback_data(self):
        keyboard = record_options_keyboard("hitter")

        self.assertEqual(keyboard["inline_keyboard"][0][0]["text"], "타율")
        self.assertEqual(keyboard["inline_keyboard"][0][0]["callback_data"], "rec:hitter:0")
        self.assertEqual(option_from_callback_data("rec:hitter:1"), ("hitter", "홈런"))

    def test_player_callback_data_identifies_record_type_and_player(self):
        self.assertEqual(player_from_callback_data("player:h:52605"), ("hitter", "52605"))
        self.assertEqual(player_from_callback_data("player:p:77637"), ("pitcher", "77637"))
        self.assertIsNone(player_from_callback_data("player:h:not-a-number"))


class FakeKBOPlayerClient:
    def __init__(self, candidates, record=None):
        self.candidates = candidates
        self.record = record
        self.search_calls = []
        self.record_calls = []

    def search_players(self, name, record_type):
        self.search_calls.append((name, record_type))
        return self.candidates

    def player_record(self, player_id, record_type):
        self.record_calls.append((player_id, record_type))
        return self.record


class PersonalPlayerRecordTest(unittest.TestCase):
    def test_unique_player_sends_photo_with_basic_record(self):
        candidate = KBOPlayerCandidate("52605", "김도영", "KIA", "내야수", "5", "우투우타", "hitter")
        record = KBOPlayerRecord(
            player_id="52605",
            record_type="hitter",
            season="2026",
            team="KIA 타이거즈",
            name="김도영",
            birthday="2003년 10월 02일",
            height_weight="183cm/85kg",
            salary="25000만원",
            back_number="5",
            position="내야수(우투우타)",
            photo_url="https://images.example/52605.jpg",
            stats={
                "AVG": "0.298",
                "AB": "400",
                "H": "119",
                "2B": "21",
                "3B": "1",
                "HR": "37",
                "RBI": "93",
                "R": "89",
                "SB": "8",
                "BB": "62",
                "HBP": "5",
                "SO": "81",
                "OBP": "0.395",
                "SLG": "0.633",
                "OPS": "1.028",
            },
        )
        client = FakeKBOPlayerClient([candidate], record)
        telegram = FakeTelegram()

        send_player_record_lookup(telegram, "hitter", "김도영", client)

        self.assertEqual(client.search_calls, [("김도영", "hitter")])
        self.assertEqual(client.record_calls, [("52605", "hitter")])
        self.assertEqual(telegram.photos[0][0], "https://images.example/52605.jpg")
        self.assertIn("타율 .298 | 타수 400 | 안타 119", telegram.photos[0][1])

    def test_duplicate_players_send_selection_keyboard(self):
        candidates = [
            KBOPlayerCandidate("10001", "김민수", "KT", "투수", "26", "우투우타", "pitcher"),
            KBOPlayerCandidate("10002", "김민수", "삼성", "투수", "57", "우투우타", "pitcher"),
        ]
        client = FakeKBOPlayerClient(candidates)
        telegram = FakeTelegram()

        send_player_record_lookup(telegram, "pitcher", "김민수", client)

        self.assertEqual(client.record_calls, [])
        self.assertIn("동명이인이 있습니다", telegram.messages[0])
        self.assertEqual(
            telegram.reply_markups[0],
            player_selection_keyboard(candidates),
        )
        self.assertEqual(
            telegram.reply_markups[0]["inline_keyboard"][1][0]["callback_data"],
            "player:p:10002",
        )

    def test_unknown_player_returns_clear_message(self):
        telegram = FakeTelegram()

        send_player_record_lookup(telegram, "hitter", "없는선수", FakeKBOPlayerClient([]))

        self.assertEqual(
            telegram.messages,
            ["현재 등록된 KBO 타자 중 '없는선수' 선수를 찾지 못했습니다."],
        )

    def test_hitter_command_with_name_routes_to_personal_record(self):
        candidate = KBOPlayerCandidate("52605", "김도영", "KIA", "내야수", "5", "우투우타", "hitter")
        record = KBOPlayerRecord(
            player_id="52605",
            record_type="hitter",
            season="2026",
            team="KIA 타이거즈",
            name="김도영",
            photo_url="https://images.example/52605.jpg",
        )
        kbo_client = FakeKBOPlayerClient([candidate], record)
        telegram = FakeCommandTelegram(
            [{"update_id": 10, "message": {"chat": {"id": "chat"}, "text": "/타자기록 김도영"}}]
        )

        with TemporaryDirectory() as directory, patch("bot.KBOPlayerClient", return_value=kbo_client):
            settings = Settings(
                telegram_token="",
                telegram_chat_id="chat",
                dry_run=True,
                state_path=Path(directory) / "state.json",
            )
            handle_telegram_commands(FakeClient(), object(), telegram, settings, {"telegramUpdateOffset": 10}, None)

        self.assertEqual(kbo_client.search_calls, [("김도영", "hitter")])
        self.assertEqual(kbo_client.record_calls, [("52605", "hitter")])
        self.assertEqual(telegram.photos[0][0], "https://images.example/52605.jpg")

    def test_player_selection_callback_loads_selected_pitcher(self):
        record = KBOPlayerRecord(
            player_id="77637",
            record_type="pitcher",
            season="2026",
            team="KIA 타이거즈",
            name="양현종",
            photo_url="https://images.example/77637.jpg",
        )
        kbo_client = FakeKBOPlayerClient([], record)
        telegram = FakeCommandTelegram(
            [
                {
                    "update_id": 11,
                    "callback_query": {
                        "id": "callback-1",
                        "data": "player:p:77637",
                        "message": {"chat": {"id": "chat"}},
                    },
                }
            ]
        )

        with TemporaryDirectory() as directory, patch("bot.KBOPlayerClient", return_value=kbo_client):
            settings = Settings(
                telegram_token="",
                telegram_chat_id="chat",
                dry_run=True,
                state_path=Path(directory) / "state.json",
            )
            handle_telegram_commands(FakeClient(), object(), telegram, settings, {"telegramUpdateOffset": 11}, None)

        self.assertEqual(telegram.answered_callbacks, ["callback-1"])
        self.assertEqual(kbo_client.record_calls, [("77637", "pitcher")])
        self.assertEqual(telegram.photos[0][0], "https://images.example/77637.jpg")


class MonthlyTeamRecordCommandTest(unittest.TestCase):
    def test_send_monthly_team_records_uses_current_month_results(self):
        games = [
            {
                "awayTeamCode": "SK",
                "homeTeamCode": "HT",
                "statusCode": "RESULT",
                "winner": "HOME",
            }
        ]
        client = FakeClient(monthly_games=games)
        telegram = FakeTelegram()
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)
        now = datetime(2026, 8, 18, 23, 30, tzinfo=settings.timezone)

        send_monthly_team_records(client, telegram, settings, now)

        self.assertEqual(client.monthly_game_dates, [date(2026, 8, 18)])
        self.assertIn("2026 KBO 8월 월간 성적", telegram.messages[0])
        self.assertIn("1. KIA | 1승 0패 0무 | 승률 1.000", telegram.messages[0])


class PitchingChangePhotoTest(unittest.TestCase):
    def test_kia_pitching_change_sends_new_pitcher_photo(self):
        event = RelayEvent(
            event_id=1,
            inning=7,
            half="초",
            text="투수 전상현 : 투수 조상우 (으)로 교체",
            home_score=4,
            away_score=3,
            home_or_away="0",
            current_state={"pitcher": "63342", "out": "1"},
        )
        telegram = FakeTelegram()
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)

        dispatch_relay_events(
            telegram,
            settings,
            {},
            {},
            [event],
            [event],
            set(),
            "삼성",
            "KIA",
            "SS",
            "HT",
        )

        self.assertEqual(len(telegram.photos), 1)
        photo_url, caption = telegram.photos[0]
        self.assertIn("/63342.png?type=w150", photo_url)
        self.assertTrue(caption.startswith("교체 | 7회초 (1 out)"))

    def test_opponent_pitching_change_does_not_send_photo(self):
        event = RelayEvent(
            event_id=1,
            inning=7,
            half="말",
            text="투수 원태인 : 투수 김재윤 (으)로 교체",
            home_score=4,
            away_score=3,
            home_or_away="1",
            current_state={"pitcher": "65062", "out": "0"},
        )
        telegram = FakeTelegram()
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)

        dispatch_relay_events(
            telegram,
            settings,
            {},
            {},
            [event],
            [event],
            set(),
            "삼성",
            "KIA",
            "SS",
            "HT",
        )

        self.assertEqual(telegram.photos, [])
        self.assertEqual(len(telegram.messages), 1)


class CancellationReasonTest(unittest.TestCase):
    class Client:
        def __init__(self, detail=None):
            self.detail = detail or {"statusInfo": "경기취소"}

        def game_detail(self, game_id):
            return {"result": {"game": self.detail}}

    class WeatherClient:
        def __init__(self, conditions):
            self.conditions = conditions
            self.calls = 0

        def stadium_current_conditions(self, stadium):
            self.calls += 1
            return self.conditions

    def test_explicit_api_reason_takes_priority(self):
        weather = self.WeatherClient({"wetrTxt": "비", "oneHourRainAmt": "5"})

        reason = resolve_cancellation_reason(
            self.Client(),
            weather,
            "game1",
            "창원",
            {"cancelReason": "폭염으로 경기취소"},
        )

        self.assertEqual(reason, "폭염 취소")
        self.assertEqual(weather.calls, 0)

    def test_clear_or_zero_rain_weather_means_heat_cancellation(self):
        reason = resolve_cancellation_reason(
            self.Client(),
            self.WeatherClient({"wetrTxt": "맑음", "oneHourRainAmt": "0.0"}),
            "game1",
            "창원",
            {"cancelFlag": "Y"},
        )

        self.assertEqual(reason, "폭염 취소")

    def test_rain_weather_means_rain_cancellation(self):
        reason = resolve_cancellation_reason(
            self.Client(),
            self.WeatherClient({"wetrTxt": "비", "oneHourRainAmt": "2.5"}),
            "game1",
            "창원",
            {"cancelFlag": "Y"},
        )

        self.assertEqual(reason, "우천 취소")


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


class DailyGameResultsTest(unittest.TestCase):
    @patch(
        "bot.find_tving_kia_highlight",
        return_value={
            "title": "[키움 vs KIA] 7/24 경기 I 하이라이트 I TVING",
            "url": "https://www.youtube.com/watch?v=highlight",
        },
    )
    def test_daily_scores_rankings_and_highlight_are_sent_in_order(self, find_highlight):
        games = [
            {
                "gameId": "game1",
                "awayTeamCode": "KT",
                "homeTeamCode": "LT",
                "statusCode": "RESULT",
            },
            {
                "gameId": "game2",
                "awayTeamCode": "WO",
                "homeTeamCode": "HT",
                "statusCode": "RESULT",
            },
        ]
        records = {
            "game1": {
                "gameInfo": {"aName": "KT", "hName": "롯데"},
                "battersBoxscore": {
                    "awayTotal": {"run": 5},
                    "homeTotal": {"run": 4},
                },
            },
            "game2": {
                "gameInfo": {"aName": "키움", "hName": "KIA"},
                "battersBoxscore": {
                    "awayTotal": {"run": 8},
                    "homeTotal": {"run": 5},
                },
            },
        }

        class DailyClient:
            def games_on(self, day):
                return games

            def record(self, game_id):
                return {"result": {"recordData": records[game_id]}}

            def team_rankings(self, season):
                return {
                    "result": {
                        "seasonTeamStats": [
                            {
                                "teamId": "HT",
                                "teamName": "KIA",
                                "ranking": 5,
                                "winGameCount": 49,
                                "drawnGameCount": 2,
                                "loseGameCount": 42,
                                "gameBehind": "7.5",
                                "continuousGameResult": "1패",
                            }
                        ]
                    }
                }

            def last_ten_games(self, season):
                return {
                    "result": {
                        "seasonTeamLastTenGameStats": [
                            {"teamId": "HT", "lastTenGameResult": "4승 6패"}
                        ]
                    }
                }

            def game_videos(self, game_id):
                return {
                    "result": {
                        "vodList": [
                            {
                                "gameId": game_id,
                                "masterVid": f"short-{index}",
                                "title": f"KIA 쇼츠 {index}",
                                "videoType": "shortform",
                                "seasonName": "KIA타이거즈",
                                "serviceType": "SPORTS",
                                "shortForm": {
                                    "serviceType": "SPORTS",
                                    "recType": "SPORTS",
                                },
                                "hit": 100 - index,
                            }
                            for index in range(1, 6)
                        ]
                    }
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
            sent = send_daily_rankings_if_all_games_done(
                DailyClient(),
                telegram,
                settings,
                state,
                datetime(2026, 7, 24, 22, 30, tzinfo=settings.timezone),
            )

        self.assertTrue(sent)
        self.assertEqual(len(telegram.messages), 8)
        self.assertEqual(
            telegram.messages[0],
            "\n".join(
                [
                    "오늘의 KBO 경기 결과",
                    "KT 5 : 4 롯데",
                    "키움 8 : 5 KIA",
                ]
            ),
        )
        self.assertTrue(telegram.messages[1].startswith("KBO 팀 순위"))
        self.assertEqual(
            telegram.messages[2],
            "\n".join(
                [
                    "KIA 경기 하이라이트",
                    "[키움 vs KIA] 7/24 경기 I 하이라이트 I TVING",
                    "https://www.youtube.com/watch?v=highlight",
                ]
            ),
        )
        for index, message in enumerate(telegram.messages[3:], 1):
            self.assertTrue(message.startswith(f"네이버 쇼츠 | KIA 쇼츠 {index}\n"))
            self.assertIn(f"mediaId=short-{index}", message)
            self.assertIn("recId=rec-game-game2", message)
        find_highlight.assert_called_once_with(date(2026, 7, 24))
        self.assertEqual(state["dailyScoresSentDate"], "2026-07-24")
        self.assertEqual(state["dailyRankingSentDate"], "2026-07-24")
        self.assertEqual(state["kiaHighlightSentDate"], "2026-07-24")
        self.assertEqual(state["kiaShortsSentDate"], "2026-07-24")
        self.assertEqual(len(state["kiaShortsSentMediaIds"]), 5)

    @patch("bot.find_tving_kia_highlight", return_value=None)
    def test_missing_highlight_is_retried_ten_minutes_later(self, find_highlight):
        now = datetime(2026, 7, 29, 22, 10)
        games = [
            {
                "gameId": "20260729HTSS02026",
                "awayTeamCode": "HT",
                "homeTeamCode": "SS",
                "statusCode": "RESULT",
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
            now = now.replace(tzinfo=settings.timezone)
            state = {}
            telegram = FakeTelegram()
            schedule_kia_highlight_after_rankings(settings, state, now, games, set())
            sent = send_due_kia_highlight(FakeClient(), telegram, settings, state, now)

        self.assertFalse(sent)
        self.assertEqual(telegram.messages, [])
        self.assertEqual(state["kiaHighlightAttemptCount"], 1)
        self.assertEqual(
            state["nextKiaHighlightAt"],
            datetime(2026, 7, 29, 22, 20, tzinfo=settings.timezone).isoformat(),
        )
        find_highlight.assert_called_once_with(date(2026, 7, 29))

    def test_partial_shorts_are_not_resent_while_waiting_for_five(self):
        now = datetime(2026, 7, 30, 23, 0)
        first_batch = [
            {
                "gameId": "20260730HTSS02026",
                "masterVid": f"media-{index}",
                "title": f"쇼츠 {index}",
                "videoType": "shortform",
                "serviceType": "SPORTS",
                "hit": index,
            }
            for index in range(1, 4)
        ]

        with TemporaryDirectory() as temp_dir:
            settings = Settings(
                telegram_token="",
                telegram_chat_id="",
                dry_run=True,
                state_path=Path(temp_dir) / "state.json",
                log_path=Path(temp_dir) / "bot.log",
            )
            now = now.replace(tzinfo=settings.timezone)
            state = {
                "kiaShortsDate": "2026-07-30",
                "kiaShortsGameId": "20260730HTSS02026",
                "nextKiaShortsAt": now.isoformat(),
                "kiaShortsSentMediaIds": [],
            }
            telegram = FakeTelegram()
            sent = send_due_kia_shorts(
                FakeClient(game_videos=first_batch),
                telegram,
                settings,
                state,
                now,
            )
            self.assertEqual(sent, 3)
            self.assertEqual(len(telegram.messages), 3)
            self.assertNotIn("kiaShortsSentDate", state)

            second_batch = first_batch + [
                {
                    "gameId": "20260730HTSS02026",
                    "masterVid": f"media-{index}",
                    "title": f"쇼츠 {index}",
                    "videoType": "shortform",
                    "serviceType": "SPORTS",
                    "hit": index,
                }
                for index in range(4, 6)
            ]
            sent = send_due_kia_shorts(
                FakeClient(game_videos=second_batch),
                telegram,
                settings,
                state,
                now + timedelta(minutes=10),
            )

        self.assertEqual(sent, 2)
        self.assertEqual(len(telegram.messages), 5)
        self.assertEqual(state["kiaShortsSentDate"], "2026-07-30")


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

            self.assertTrue(sent)
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
        self.assertTrue(telegram.messages[0].startswith("투수 판정 업데이트"))
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
    def test_away_kia_half_summary_includes_opponent_pitcher_stats(self):
        events = [
            RelayEvent(
                1,
                7,
                "초",
                "김태군 : 중견수 플라이 아웃",
                0,
                2,
                batter_code="8",
                player_name="김태군",
                home_or_away="0",
                current_state={"pitcher": "56724", "out": "1"},
            ),
            RelayEvent(
                2,
                7,
                "초",
                "박정우 : 유격수 땅볼 아웃",
                0,
                2,
                batter_code="2",
                player_name="박정우",
                home_or_away="0",
                current_state={"pitcher": "56724", "out": "3"},
            ),
            RelayEvent(
                3,
                7,
                "말",
                "7회말 한화 공격",
                0,
                2,
                home_or_away="1",
                current_state={"out": "0"},
            ),
        ]
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "8", "name": "김태군", "batOrder": 8, "seasonHra": "0.279", "ab": 2, "bb": 1},
                    {"pcode": "2", "name": "박정우", "batOrder": 2, "seasonHra": "0.300", "ab": 4, "hit": 1, "so": 1},
                ]
            },
            "homeLineup": {
                "pitcher": [
                    {
                        "pcode": "56724",
                        "name": "화이트",
                        "seqno": 1,
                        "ballCount": 103,
                        "inn": "7.0",
                        "hit": 5,
                        "run": 2,
                        "er": 2,
                        "bb": 2,
                        "hbp": 0,
                        "kk": 6,
                        "seasonEra": "3.11",
                    }
                ]
            },
        }
        telegram = FakeTelegram()
        settings = Settings(telegram_token="", telegram_chat_id="", dry_run=True)

        dispatch_relay_events(
            telegram,
            settings,
            {},
            relay,
            events,
            [events[-1]],
            set(),
            "KIA",
            "한화",
            "HT",
            "HH",
        )

        self.assertEqual(len(telegram.messages), 1)
        self.assertIn("KIA 공격 종료 | 7회초", telegram.messages[0])
        self.assertTrue(
            telegram.messages[0].endswith(
                "\n\n화이트(한) | 103개 | 7이닝 5피안타 2실점 2자책 2사사구 6삼진 ERA 3.11"
            )
        )

    def test_process_relay_loads_previous_inning_for_away_kia_out_summary(self):
        current_relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "1", "name": "박재현", "batOrder": 1, "seasonHra": "0.284", "ab": 3, "hit": 1},
                    {"pcode": "2", "name": "김선빈", "batOrder": 2, "seasonHra": "0.272", "ab": 2, "hit": 0},
                    {"pcode": "3", "name": "김도영", "batOrder": 3, "seasonHra": "0.294", "ab": 2, "hit": 0},
                ]
            },
            "textRelays": [
                {
                    "inn": 7,
                    "homeOrAway": "0",
                    "title": "7회초 KIA 공격",
                    "textOptions": [
                        {
                            "seqno": 346,
                            "text": "7회초 KIA 공격",
                            "currentGameState": {
                                "awayScore": 3,
                                "homeScore": 2,
                                "batter": "1",
                                "out": "0",
                            },
                        }
                    ],
                }
            ],
        }
        previous_relay = {
            "textRelays": [
                {
                    "inn": 6,
                    "homeOrAway": "1",
                    "title": "5번타자 노시환",
                    "textOptions": [
                        {
                            "seqno": 341,
                            "text": "노시환 : 삼진 아웃",
                            "currentGameState": {
                                "awayScore": 3,
                                "homeScore": 2,
                                "batter": "5",
                                "out": "1",
                                "base1": "0",
                                "base2": "0",
                                "base3": "0",
                            },
                        }
                    ],
                },
                {
                    "inn": 6,
                    "homeOrAway": "1",
                    "title": "7번타자 문현빈",
                    "textOptions": [
                        {
                            "seqno": 342,
                            "text": "문현빈 : 2루수 앞 땅볼로 출루",
                            "currentGameState": {
                                "awayScore": 3,
                                "homeScore": 2,
                                "batter": "7",
                                "out": "1",
                                "base1": "7",
                                "base2": "0",
                                "base3": "0",
                            },
                        },
                        {
                            "seqno": 343,
                            "text": "1루주자 채은성 : 포스아웃",
                            "currentGameState": {
                                "awayScore": 3,
                                "homeScore": 2,
                                "batter": "7",
                                "out": "2",
                                "base1": "7",
                                "base2": "0",
                                "base3": "0",
                            },
                        },
                    ],
                },
                {
                    "inn": 6,
                    "homeOrAway": "1",
                    "title": "8번타자 최재훈",
                    "textOptions": [
                        {
                            "seqno": 345,
                            "text": "최재훈 : 우익수 플라이 아웃",
                            "currentGameState": {
                                "awayScore": 3,
                                "homeScore": 2,
                                "batter": "8",
                                "out": "3",
                                "base1": "7",
                                "base2": "0",
                                "base3": "0",
                            },
                        },
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
                "lastRelaySeq": 345,
                "relayBootstrapped": True,
                "kiaHalfSummariesSent": [],
            }
            telegram = FakeTelegram()
            client = FakeClient(relay=current_relay, relay_by_inning={6: previous_relay})

            process_relay(
                client,
                telegram,
                settings,
                state,
                "game1",
                "KIA",
                "한화",
                "HT",
                "HH",
            )

        self.assertEqual(len(telegram.messages), 1)
        self.assertIn("KIA 3 : 2 한화 (삼진1 포스2 플라이3 잔루1)", telegram.messages[0])

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
    def test_existing_cumulative_rbi_is_not_attached_without_baseline(self):
        event = SimpleNamespace(
            event_id=261,
            text="김도영 : 볼넷",
            batter_code="52605",
        )
        state = {}

        remember_plate_result(
            state,
            event,
            {"name": "김도영", "batOrder": 3, "ab": 2, "hit": 0, "rbi": 3},
        )

        self.assertEqual(state["plateResultHistories"]["52605"][0]["label"], "볼넷")

    def test_rbi_baseline_only_labels_increase_from_current_plate(self):
        header = SimpleNamespace(
            batter_code="52605",
            is_plate_result=False,
            batter_record={"rbi": 2},
        )
        result = SimpleNamespace(
            event_id=262,
            text="김도영 : 좌익수 앞 1루타",
            batter_code="52605",
        )
        state = {}

        remember_plate_rbi_baseline(state, header)
        remember_plate_result(
            state,
            result,
            {"name": "김도영", "batOrder": 3, "ab": 3, "hit": 1, "rbi": 3},
        )

        self.assertEqual(state["plateResultHistories"]["52605"][0]["label"], "안타(타점1)")

    def test_post_plate_rbi_snapshots_attach_rbi_to_the_correct_result(self):
        state = {}
        plate_appearances = [
            ("카스트로 : 우익수 플라이 아웃", {"pa": 1, "ab": 1, "rbi": 0}),
            ("카스트로 : 몸에 맞는 볼", {"pa": 2, "ab": 1, "hbp": 1, "rbi": 1}),
            ("카스트로 : 우중간 1루타", {"pa": 3, "ab": 2, "hbp": 1, "rbi": 2}),
            ("카스트로 : 우익수 오른쪽 1루타", {"pa": 4, "ab": 3, "hbp": 1, "rbi": 2}),
        ]

        for index, (text, snapshot) in enumerate(plate_appearances, 1):
            remember_plate_rbi_baseline(
                state,
                SimpleNamespace(
                    batter_code="56626",
                    is_plate_result=False,
                    batter_record=snapshot,
                ),
            )
            remember_plate_result(
                state,
                SimpleNamespace(event_id=index, text=text, batter_code="56626"),
                {"name": "카스트로", "batOrder": 4, **snapshot},
            )

        labels = [item["label"] for item in state["plateResultHistories"]["56626"]]
        self.assertEqual(labels, ["플라이", "사구(타점1)", "안타(타점1)", "안타"])

    def test_delayed_rbi_update_is_attached_to_the_previous_scoring_hit(self):
        state = {
            "plateResultTotals": {"56626": {"rbi": 1}},
            "plateResultHistories": {
                "56626": [
                    {"eventId": 61, "label": "플라이", "rbi": 0},
                    {"eventId": 159, "label": "사구(타점1)", "rbi": 1, "runsScored": 1},
                ]
            },
        }
        sixth_inning_hit = SimpleNamespace(
            event_id=284,
            text="카스트로 : 우중간 1루타",
            batter_code="56626",
        )

        remember_plate_result(
            state,
            sixth_inning_hit,
            {"name": "카스트로", "batOrder": 4, "ab": 2, "hit": 1, "rbi": 1},
        )
        remember_plate_score(
            state,
            SimpleNamespace(batter_code="56626", is_score_event=True),
        )
        remember_plate_rbi_baseline(
            state,
            SimpleNamespace(
                batter_code="56626",
                is_plate_result=False,
                batter_record={"pa": 4, "ab": 3, "hbp": 1, "rbi": 2},
            ),
        )
        remember_plate_result(
            state,
            SimpleNamespace(
                event_id=430,
                text="카스트로 : 우익수 오른쪽 1루타",
                batter_code="56626",
            ),
            {"name": "카스트로", "batOrder": 4, "ab": 3, "hit": 2, "rbi": 2},
        )

        labels = [item["label"] for item in state["plateResultHistories"]["56626"]]
        self.assertEqual(labels, ["플라이", "사구(타점1)", "안타(타점1)", "안타"])

    def test_complete_plate_history_corrects_inflated_api_hit_total(self):
        player = {
            "name": "김호령",
            "batOrder": 2,
            "seasonHra": "0.279",
            "ab": 2,
            "hit": 2,
        }
        history = [
            {"eventId": 78, "label": "플라이"},
            {"eventId": 220, "label": "3루타"},
        ]

        adjusted = with_state_plate_totals(player, history)

        self.assertEqual(adjusted["ab"], 2)
        self.assertEqual(adjusted["hit"], 1)

    def test_partial_plate_history_keeps_larger_api_totals(self):
        player = {
            "name": "김호령",
            "batOrder": 2,
            "seasonHra": "0.279",
            "ab": 3,
            "hit": 2,
        }
        history = [{"eventId": 220, "label": "3루타"}]

        adjusted = with_state_plate_totals(player, history)

        self.assertEqual(adjusted["ab"], 3)
        self.assertEqual(adjusted["hit"], 2)

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
