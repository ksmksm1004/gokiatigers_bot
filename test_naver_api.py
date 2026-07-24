import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests

from naver_api import NaverSportsClient, find_calendar_game_dicts, unwrap


class CalendarOnlyClient(NaverSportsClient):
    def __init__(self, calendar_data):
        self.calendar_data = calendar_data
        self.fallback_called = False

    def calendar(self, day):
        return self.calendar_data

    def get_json(self, url_or_path, params=None):
        self.fallback_called = True
        raise AssertionError("fallback schedule API should not be called after a valid calendar response")


class NaverApiTest(unittest.TestCase):
    def test_unwrap_converts_null_payload_to_empty_dict(self):
        self.assertEqual(unwrap({"result": {"textRelayData": None}}, "textRelayData"), {})

    @patch("naver_api.time.sleep")
    def test_get_json_retries_transient_connection_error(self, sleep):
        response = Mock(status_code=200)
        response.json.return_value = {"success": True}
        client = NaverSportsClient()
        client.session = Mock()
        client.session.get.side_effect = [requests.ConnectionError("reset"), response]

        result = client.get_json("/schedule/test")

        self.assertEqual(result, {"success": True})
        self.assertEqual(client.session.get.call_count, 2)
        sleep.assert_called_once()

    def test_games_on_returns_empty_when_calendar_has_no_games(self):
        client = CalendarOnlyClient(
            {
                "result": {
                    "dates": [
                        {
                            "ymd": "2026-07-20",
                            "gameInfos": None,
                        }
                    ]
                }
            }
        )

        self.assertEqual(client.games_on(date(2026, 7, 20)), [])
        self.assertFalse(client.fallback_called)

    def test_find_calendar_game_dicts_ignores_empty_non_kbo_games(self):
        games = find_calendar_game_dicts(
            {
                "result": {
                    "dates": [
                        {
                            "ymd": "2026-07-20",
                            "gameInfos": [
                                {"gameId": "20260720KBO1", "homeTeamCode": "", "awayTeamCode": ""},
                                {
                                    "gameId": "20260720HTSK02026",
                                    "homeTeamCode": "SK",
                                    "awayTeamCode": "HT",
                                    "statusCode": "BEFORE",
                                },
                            ],
                        }
                    ]
                }
            },
            date(2026, 7, 20),
        )

        self.assertEqual(games[0]["gameId"], "20260720HTSK02026")


if __name__ == "__main__":
    unittest.main()
