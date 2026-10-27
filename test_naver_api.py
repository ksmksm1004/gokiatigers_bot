import unittest
from datetime import date
from unittest.mock import Mock, patch

import requests
from curl_cffi.requests import exceptions as browser_errors

from naver_api import NaverSportsClient, find_calendar_game_dicts, find_calendar_month_game_dicts, unwrap


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
    @patch("naver_api.time.sleep")
    def test_browser_connection_reset_is_retried(self, sleep):
        response = Mock(status_code=200)
        response.json.return_value = {"result": {"textRelayData": {"inn": 8}}}
        client = NaverSportsClient()
        client.session = Mock()
        client.session.get.side_effect = [browser_errors.ConnectionError("reset"), response]
        self.assertEqual(client.relay("game")["result"]["textRelayData"]["inn"], 8)
        self.assertEqual(client.session.get.call_count, 2)

    @patch("naver_api.time.sleep")
    def test_browser_network_errors_keep_requests_contract_after_retries(self, sleep):
        for transport_error, public_error in (
            (browser_errors.Timeout, requests.Timeout),
            (browser_errors.ConnectionError, requests.ConnectionError),
        ):
            with self.subTest(error=transport_error):
                client = NaverSportsClient()
                client.session = Mock()
                client.session.get.side_effect = transport_error("unavailable")
                with self.assertRaises(public_error):
                    client.preview("game")
                self.assertEqual(client.session.get.call_count, 3)

    def test_browser_http_error_keeps_status_and_is_not_retried(self):
        response = Mock(status_code=404)
        response.raise_for_status.side_effect = browser_errors.HTTPError("not found", response=response)
        client = NaverSportsClient()
        client.session = Mock()
        client.session.get.return_value = response
        with self.assertRaises(requests.HTTPError) as caught:
            client.relay("missing")
        self.assertEqual(caught.exception.response.status_code, 404)
        self.assertEqual(client.session.get.call_count, 1)

    @patch("naver_api.time.sleep")
    def test_service_unavailable_is_retried_before_parsing(self, sleep):
        busy = Mock(status_code=503)
        ok = Mock(status_code=200)
        ok.json.return_value = {"success": True}
        client = NaverSportsClient()
        client.session = Mock()
        client.session.get.side_effect = [busy, ok]
        self.assertEqual(client.get_json("/schedule/test"), {"success": True})
        busy.json.assert_not_called()
        self.assertEqual(client.session.get.call_count, 2)

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

    def test_asian_games_baseball_games_uses_service_game_id(self):
        client = NaverSportsClient()
        client.get_json = Mock(
            return_value={
                "result": {
                    "games": [
                        {
                            "gameId": "event-game",
                            "serviceGameId": "relay-game",
                            "disciplineId": "BSB",
                            "koreaPlayer": True,
                        },
                        {
                            "gameId": "other-discipline",
                            "serviceGameId": "other-relay",
                            "disciplineId": "SOC",
                            "koreaPlayer": True,
                        },
                    ]
                }
            }
        )

        games = client.asian_games_baseball_games(date(2026, 9, 21))

        self.assertEqual([game["serviceGameId"] for game in games], ["relay-game"])
        client.get_json.assert_called_once_with(
            "/olympic/asiangames2026/games",
            params={
                "fromDate": "2026-09-21",
                "toDate": "2026-09-21",
                "disciplineId": "BSB",
                "includeKorean": "true",
                "includeMedal": "false",
                "includeScheduledTv": "false",
                "page": 1,
                "pageSize": 100,
                "sort": "dateAsc",
                "fields": "all",
            },
        )

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

    def test_find_calendar_month_game_dicts_returns_every_game_in_selected_month(self):
        games = find_calendar_month_game_dicts(
            {
                "result": {
                    "dates": [
                        {
                            "ymd": "2026-07-31",
                            "gameInfos": [
                                {
                                    "gameId": "july",
                                    "homeTeamCode": "HT",
                                    "awayTeamCode": "SS",
                                    "statusCode": "RESULT",
                                    "winner": "HOME",
                                }
                            ],
                        },
                        {
                            "ymd": "2026-08-01",
                            "gameInfos": [
                                {
                                    "gameId": "august-1",
                                    "homeTeamCode": "HT",
                                    "awayTeamCode": "SS",
                                    "statusCode": "RESULT",
                                    "winner": "HOME",
                                },
                                {"gameId": "news", "homeTeamCode": "", "awayTeamCode": ""},
                            ],
                        },
                        {
                            "ymd": "2026-08-18",
                            "gameInfos": [
                                {
                                    "gameId": "august-18",
                                    "homeTeamCode": "HH",
                                    "awayTeamCode": "HT",
                                    "statusCode": "STARTED",
                                    "winner": "DRAW",
                                }
                            ],
                        },
                    ]
                }
            },
            date(2026, 8, 18),
        )

        self.assertEqual([game["gameId"] for game in games], ["august-1", "august-18"])
        self.assertEqual(games[0]["winner"], "HOME")


if __name__ == "__main__":
    unittest.main()
