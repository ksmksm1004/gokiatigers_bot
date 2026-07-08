import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bot import final_score_from_record, send_game_end_record_once
from config import Settings


class FakeClient:
    def __init__(self, record):
        self._record = record

    def record(self, game_id):
        return {"result": {"recordData": self._record}}


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


if __name__ == "__main__":
    unittest.main()
