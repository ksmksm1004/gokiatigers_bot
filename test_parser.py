import unittest

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


if __name__ == "__main__":
    unittest.main()
