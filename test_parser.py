import unittest

from parser import (
    RelayEvent,
    changed_pitcher_lines,
    expected_batters_message,
    format_batter_summary_stats,
    format_kia_news_articles,
    format_player_record_stats,
    format_relay_event,
    format_relay_event_with_context,
    format_team_record_stats,
    has_starting_lineups,
    kia_news_articles,
    parse_relay_events,
    plate_result_history,
    record_options_message,
    resolve_record_option,
    should_send_relay_event,
)
from parser import format_preview


class StartingLineupTest(unittest.TestCase):
    @staticmethod
    def lineup(prefix):
        return [
            {
                "playerCode": f"{prefix}-pitcher",
                "playerName": f"{prefix} 선발",
                "batorder": None,
                "positionName": "선발투수",
            },
            *[
                {
                    "playerCode": f"{prefix}-{order}",
                    "playerName": f"{prefix} 타자 {order}",
                    "batorder": order,
                    "positionName": "타자",
                }
                for order in range(1, 10)
            ],
        ]

    def test_pitchers_only_are_not_treated_as_complete_lineups(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": [self.lineup("away")[0]]},
            "homeTeamLineUp": {"fullLineUp": [self.lineup("home")[0]]},
        }

        self.assertFalse(has_starting_lineups(preview))

    def test_both_pitchers_and_batting_orders_one_through_nine_are_complete(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": self.lineup("away")},
            "homeTeamLineUp": {"fullLineUp": self.lineup("home")},
        }

        self.assertTrue(has_starting_lineups(preview))

    def test_one_incomplete_team_keeps_lineup_pending(self):
        preview = {
            "awayTeamLineUp": {"fullLineUp": self.lineup("away")},
            "homeTeamLineUp": {"fullLineUp": self.lineup("home")[:-1]},
        }

        self.assertFalse(has_starting_lineups(preview))


class RelayParsingTest(unittest.TestCase):
    def test_null_relay_payload_is_treated_as_no_events(self):
        self.assertEqual(parse_relay_events(None), [])
        self.assertEqual(parse_relay_events({"textRelays": None}), [])


class FormatPreviewTest(unittest.TestCase):
    def test_away_kia_recent_and_vs_records_use_away_data(self):
        preview = {
            "gameInfo": {
                "aCode": "HT",
                "hCode": "LT",
                "aName": "KIA",
                "hName": "롯데",
                "gdate": 20260707,
                "gtime": "18:30",
                "stadium": "사직",
            },
            "awayTeamPreviousGames": [{"result": result} for result in ["승", "무", "승", "패", "패"]],
            "homeTeamPreviousGames": [{"result": result} for result in ["패", "승", "승", "패", "승"]],
            "seasonVsResult": {"aw": 6, "ad": 1, "al": 2, "hw": 2, "hd": 1, "hl": 6},
        }

        message = format_preview(preview, "20260707HTLT02026", "HT")

        self.assertIn("KIA: 승 무 승 패 패", message)
        self.assertIn("상대: 패 승 승 패 승", message)
        self.assertIn("KIA 6승 1무 2패", message)

    def test_home_kia_recent_and_vs_records_use_home_data(self):
        preview = {
            "gameInfo": {
                "aCode": "LT",
                "hCode": "HT",
                "aName": "롯데",
                "hName": "KIA",
                "gdate": 20260708,
                "gtime": "18:30",
                "stadium": "광주",
            },
            "awayTeamPreviousGames": [{"result": result} for result in ["패", "승", "승", "패", "승"]],
            "homeTeamPreviousGames": [{"result": result} for result in ["승", "무", "승", "패", "패"]],
            "seasonVsResult": {"aw": 2, "ad": 1, "al": 6, "hw": 6, "hd": 1, "hl": 2},
        }

        message = format_preview(preview, "20260708LTHT02026", "HT")

        self.assertIn("KIA: 승 무 승 패 패", message)
        self.assertIn("상대: 패 승 승 패 승", message)
        self.assertIn("KIA 6승 1무 2패", message)


class RecordStatsFormatTest(unittest.TestCase):
    def test_team_record_stats_sort_by_selected_metric(self):
        rows = [
            {"teamName": "KIA", "offenseHra": 0.26844, "offenseHit": 848},
            {"teamName": "KT", "offenseHra": 0.28132, "offenseHit": 860},
            {"teamName": "삼성", "offenseHra": 0.27713, "offenseHit": 858},
        ]

        message = format_team_record_stats(rows, "타율")

        self.assertIn("KBO 팀 기록 | 타율", message)
        self.assertLess(message.index("1. KT"), message.index("2. 삼성"))
        self.assertLess(message.index("2. 삼성"), message.index("3. KIA"))
        self.assertIn("0.281", message)

    def test_player_record_stats_recomputes_tied_ranks(self):
        rows = [
            {"playerName": "오스틴", "teamName": "LG", "hitterHr": 28},
            {"playerName": "김도영", "teamName": "KIA", "hitterHr": 27},
            {"playerName": "강백호", "teamName": "KT", "hitterHr": 23},
            {"playerName": "힐리어드", "teamName": "한화", "hitterHr": 23},
            {"playerName": "최정", "teamName": "SSG", "hitterHr": 20},
        ]

        message = format_player_record_stats(rows, "hitter", "홈런")

        self.assertIn("1. 오스틴 (LG) | 28개", message)
        self.assertIn("3. 강백호 (KT) | 23개", message)
        self.assertIn("3. 힐리어드 (한화) | 23개", message)
        self.assertIn("5. 최정 (SSG) | 20개", message)

    def test_rate_stats_exclude_unqualified_players_before_sorting(self):
        rows = [
            {"playerName": "최원준", "teamName": "KT", "hitterHra": 0.3577, "isQualified": True},
            {"playerName": "레이예스", "teamName": "롯데", "hitterHra": 0.3474, "isQualified": True},
            {"playerName": "전다민", "teamName": "두산", "hitterHra": 1.0, "isQualified": False},
        ]

        message = format_player_record_stats(rows, "hitter", "타율")

        self.assertIn("1. 최원준 (KT) | 0.358", message)
        self.assertIn("2. 레이예스 (롯데) | 0.347", message)
        self.assertNotIn("전다민", message)

    def test_pitcher_rate_stats_exclude_unqualified_players_before_sorting(self):
        rows = [
            {"playerName": "올러", "teamName": "KIA", "pitcherWhip": 1.06, "isQualified": True},
            {"playerName": "알칸타라", "teamName": "키움", "pitcherWhip": 1.08, "isQualified": True},
            {"playerName": "김한종", "teamName": "두산", "pitcherWhip": 0.0, "isQualified": False},
        ]

        message = format_player_record_stats(rows, "pitcher", "WHIP")

        self.assertIn("1. 올러 (KIA) | 1.06", message)
        self.assertIn("2. 알칸타라 (키움) | 1.08", message)
        self.assertNotIn("김한종", message)

    def test_record_option_prompt_and_resolution(self):
        self.assertIn("1. 타율", record_options_message("team"))
        self.assertEqual(resolve_record_option("team", "타율 알려줘"), "타율")
        self.assertEqual(resolve_record_option("hitter", "ops"), "OPS")


class KiaNewsFormatTest(unittest.TestCase):
    def test_kia_news_articles_filter_title_and_deduplicate(self):
        game_news = [
            {"oid": "001", "aid": "1", "title": "KIA 타선 폭발", "sourceName": "A", "sportsSection": "kbaseball"},
            {"oid": "001", "aid": "2", "title": "한화 선발 호투", "sourceName": "B", "sportsSection": "kbaseball"},
        ]
        section_news = [
            {"oid": "001", "aid": "1", "title": "KIA 타선 폭발", "sourceName": "A", "sportsSection": "kbaseball"},
            {"oid": "002", "aid": "3", "title": "기아 불펜 점검", "sourceName": "C", "sportsSection": "kbaseball"},
        ]

        articles = kia_news_articles(game_news, section_news, limit=5)
        message = format_kia_news_articles(articles)

        self.assertEqual([article["aid"] for article in articles], ["1", "3"])
        self.assertIn("KIA 주요 기사", message)
        self.assertIn("1. KIA 타선 폭발 (A)", message)
        self.assertIn("https://m.sports.naver.com/kbaseball/article/001/1", message)
        self.assertIn("2. 기아 불펜 점검 (C)", message)


class CompactBatterFormatTest(unittest.TestCase):
    def test_relay_batter_snapshot_uses_short_result_format(self):
        event = RelayEvent(
            event_id=1,
            inning=1,
            half="초",
            text="나성범 : 좌익수 앞 1루타",
            home_score=0,
            away_score=0,
            player_name="나성범",
        )
        message = format_relay_event(
            event,
            "KIA",
            "롯데",
            {
                "name": "나성범",
                "batOrder": 4,
                "seasonHra": "0.296",
                "ab": 1,
                "hit": 1,
                "rbi": 1,
            },
        )

        self.assertIn("4 나성범 | .296 | 1-1 | 안타(타점1)", message)

    def test_relay_batter_snapshot_omits_empty_result(self):
        event = RelayEvent(
            event_id=1,
            inning=1,
            half="초",
            text="김호령 : 타석 준비",
            home_score=5,
            away_score=1,
            player_name="김호령",
        )
        message = format_relay_event(
            event,
            "KIA",
            "롯데",
            {
                "name": "김호령",
                "batOrder": 9,
                "seasonHra": "0.281",
                "ab": 0,
                "hit": 0,
            },
        )

        self.assertIn("9 김호령 | .281 | 0-0", message)
        self.assertNotIn(" | 타석 준비", message)

    def test_relay_batter_snapshot_uses_full_plate_history(self):
        events = [
            RelayEvent(
                event_id=1,
                inning=2,
                half="초",
                text="김선빈 : 삼진 아웃",
                home_score=0,
                away_score=0,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
            RelayEvent(
                event_id=2,
                inning=5,
                half="초",
                text="김선빈 : 유격수 땅볼 아웃",
                home_score=3,
                away_score=1,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
            RelayEvent(
                event_id=3,
                inning=8,
                half="초",
                text="김선빈 : 우익수 오른쪽 1루타",
                home_score=5,
                away_score=5,
                batter_code="6",
                home_or_away="0",
                player_name="김선빈",
            ),
        ]
        player = {"name": "김선빈", "batOrder": 6, "seasonHra": "0.251", "ab": 3, "hit": 1, "rbi": 1}

        history = plate_result_history(events, events[-1], player)
        message = format_relay_event_with_context(events[-1], "KIA", "SSG", player_record=player, plate_results=history)

        self.assertEqual(history, ["삼진", "땅볼", "안타(타점1)"])
        self.assertIn("6 김선빈 | .251 | 1-3 | 삼진 땅볼 안타(타점1)", message)

    def test_score_runner_event_omits_repeated_batter_snapshot(self):
        previous = RelayEvent(
            event_id=1,
            inning=8,
            half="초",
            text="김호령 : 중견수 앞 1루타",
            home_score=5,
            away_score=5,
            batter_code="1",
            home_or_away="0",
            player_name="김호령",
        )
        score = RelayEvent(
            event_id=2,
            inning=8,
            half="초",
            text="2루주자 김규성 : 홈인",
            home_score=5,
            away_score=6,
            batter_code="1",
            home_or_away="0",
        )
        player = {"name": "김호령", "batOrder": 1, "seasonHra": "0.283", "ab": 4, "hit": 1, "rbi": 2}

        message = format_relay_event_with_context(score, "KIA", "SSG", previous, player)

        self.assertIn("김호령 : 중견수 앞 1루타", message)
        self.assertNotIn("1 김호령 | .283 | 1-4", message)

    def test_score_homer_event_keeps_batter_snapshot(self):
        previous = RelayEvent(
            event_id=0,
            inning=8,
            half="초",
            text="김호령 : 중견수 앞 1루타",
            home_score=5,
            away_score=7,
            batter_code="1",
            home_or_away="0",
            player_name="김호령",
        )
        events = [
            RelayEvent(
                event_id=1,
                inning=1,
                half="초",
                text="카스트로 : 삼진 아웃",
                home_score=0,
                away_score=0,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=2,
                inning=3,
                half="초",
                text="카스트로 : 우익수 앞 1루타",
                home_score=0,
                away_score=1,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=3,
                inning=5,
                half="초",
                text="카스트로 : 2루수 땅볼 아웃",
                home_score=3,
                away_score=2,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=4,
                inning=7,
                half="초",
                text="카스트로 : 좌익수 앞 1루타",
                home_score=5,
                away_score=5,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
            RelayEvent(
                event_id=5,
                inning=8,
                half="초",
                text="카스트로 : 우익수 뒤 홈런 (홈런거리:125M)",
                home_score=5,
                away_score=8,
                batter_code="2",
                home_or_away="0",
                player_name="카스트로",
            ),
        ]
        event = events[-1]
        player = {"name": "카스트로", "batOrder": 2, "seasonHra": "0.324", "ab": 5, "hit": 3, "rbi": 2}
        history = plate_result_history(events, event, player)

        message = format_relay_event_with_context(event, "KIA", "SSG", previous, player, history)

        self.assertIn("득점 | 8회초", message)
        self.assertIn("2 카스트로 | .324 | 3-5 | 삼진 안타 땅볼 안타 홈런(타점2)", message)
        self.assertNotIn("김호령 : 중견수 앞 1루타", message)

    def test_runner_steal_and_video_review_do_not_use_current_batter_stats(self):
        steal = RelayEvent(
            event_id=1,
            inning=8,
            half="초",
            text="1루주자 김호령 : 도루로 2루까지 진루",
            home_score=5,
            away_score=7,
            batter_code="2",
            home_or_away="0",
        )
        video = RelayEvent(
            event_id=2,
            inning=8,
            half="초",
            text="8회초 2번타순 2구 후 SSG요청 비디오 판독: 김호령 2루 도루 관련 세이프→세이프",
            home_score=5,
            away_score=7,
            batter_code="2",
            home_or_away="0",
        )
        player = {"name": "카스트로", "batOrder": 2, "seasonHra": "0.320", "ab": 4, "hit": 2, "sb": 1}

        self.assertTrue(should_send_relay_event(steal, "SK", "HT", "HT"))
        self.assertNotIn("카스트로", format_relay_event_with_context(steal, "KIA", "SSG", player_record=player))
        self.assertNotIn("카스트로", format_relay_event_with_context(video, "KIA", "SSG", player_record=player))

    def test_half_summary_omits_zero_stats(self):
        self.assertEqual(
            format_batter_summary_stats(
                {
                    "name": "박재현",
                    "batOrder": 1,
                    "seasonHra": "0.284",
                    "ab": 0,
                    "run": 1,
                    "hit": 0,
                    "rbi": 0,
                    "hr": 0,
                    "bb": 1,
                    "so": 0,
                    "sb": 0,
                }
            ),
            "1 박재현 | .284 | 1득점 1볼넷",
        )

    def test_expected_batters_use_short_snapshot_without_plate_result(self):
        event = RelayEvent(
            event_id=1,
            inning=2,
            half="초",
            text="2회초 KIA 공격",
            home_score=4,
            away_score=1,
            batter_code="6",
            home_or_away="0",
        )
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "6", "name": "박상준", "batOrder": 6, "seasonHra": "0.303", "ab": 0, "hit": 0},
                    {"pcode": "7", "name": "김선빈", "batOrder": 7, "seasonHra": "0.248", "ab": 0, "hit": 0},
                    {"pcode": "8", "name": "김규성", "batOrder": 8, "seasonHra": "0.245", "ab": 0, "hit": 0},
                ]
            }
        }

        message = expected_batters_message(event, relay, "LT", "HT", "KIA", "롯데", "HT")

        self.assertIn("6 박상준 | .303 | 0-0", message)
        self.assertIn("7 김선빈 | .248 | 0-0", message)
        self.assertIn("8 김규성 | .245 | 0-0", message)

    def test_expected_batters_can_include_previous_kia_pitcher_stats(self):
        event = RelayEvent(
            event_id=1,
            inning=3,
            half="초",
            text="3회초 KIA 공격",
            home_score=1,
            away_score=0,
            batter_code="9",
            home_or_away="0",
        )
        relay = {
            "awayLineup": {
                "batter": [
                    {"pcode": "9", "name": "김규성", "batOrder": 9, "seasonHra": "0.245", "ab": 0, "hit": 0},
                    {"pcode": "1", "name": "박재현", "batOrder": 1, "seasonHra": "0.280", "ab": 1, "hit": 0},
                    {"pcode": "2", "name": "김호령", "batOrder": 2, "seasonHra": "0.283", "ab": 1, "hit": 1},
                ],
                "pitcher": [
                    {
                        "pcode": "50054",
                        "name": "성영탁",
                        "seqno": 2,
                        "ballCount": 22,
                        "inn": "0.2",
                        "hit": 4,
                        "run": 4,
                        "er": 3,
                        "bb": 1,
                        "hbp": 0,
                        "kk": 2,
                        "seasonEra": "4.11",
                    }
                ],
            }
        }
        previous = {
            "50054": {
                "name": "성영탁",
                "seqno": 2,
                "ballCount": 0,
                "inn": "0",
                "hit": 0,
                "run": 0,
                "er": 0,
                "bb": 0,
                "hbp": 0,
                "kk": 0,
                "seasonEra": "4.11",
            }
        }

        pitcher_lines, snapshot = changed_pitcher_lines(relay, "away", previous)
        message = expected_batters_message(event, relay, "LT", "HT", "KIA", "롯데", "HT", pitcher_lines)

        self.assertEqual(
            pitcher_lines,
            ["성영탁 | 22개 | 0 ⅔이닝 4피안타 4실점 3자책 1사사구 2삼진 ERA 4.11"],
        )
        self.assertEqual(snapshot["50054"]["ballCount"], 22)
        self.assertIn("9 김규성 | .245 | 0-0", message)
        self.assertIn("\n\n성영탁 | 22개 | 0 ⅔이닝", message)

    def test_first_kia_attack_only_stores_pitcher_snapshot(self):
        relay = {
            "awayLineup": {
                "pitcher": [
                    {
                        "pcode": "50054",
                        "name": "성영탁",
                        "seqno": 2,
                        "ballCount": 22,
                        "inn": "0.2",
                        "hit": 4,
                        "run": 4,
                        "er": 3,
                        "bb": 1,
                        "hbp": 0,
                        "kk": 2,
                        "seasonEra": "4.11",
                    }
                ]
            }
        }

        pitcher_lines, snapshot = changed_pitcher_lines(relay, "away", None)

        self.assertEqual(pitcher_lines, [])
        self.assertEqual(snapshot["50054"]["inn"], "0.2")

    def test_video_review_is_sent_for_any_team(self):
        event = RelayEvent(
            event_id=1,
            inning=4,
            half="말",
            text="비디오 판독 : 세이프 여부",
            home_score=1,
            away_score=1,
            home_or_away="1",
        )

        self.assertTrue(should_send_relay_event(event, "LT", "HT", "HT"))


if __name__ == "__main__":
    unittest.main()
