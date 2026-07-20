import unittest

from parser import (
    RelayEvent,
    changed_pitcher_lines,
    expected_batters_message,
    format_batter_summary_stats,
    format_relay_event,
    format_relay_event_with_context,
    plate_result_history,
    should_send_relay_event,
)
from parser import format_preview


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
