import unittest

<<<<<<< HEAD
=======
from parser import (
    RelayEvent,
    expected_batters_message,
    format_batter_summary_stats,
    format_relay_event,
    should_send_relay_event,
)
>>>>>>> aff2c71 (fix: schedule, formatting, add video challenge)
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


<<<<<<< HEAD
=======
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


>>>>>>> aff2c71 (fix: schedule, formatting, add video challenge)
if __name__ == "__main__":
    unittest.main()
