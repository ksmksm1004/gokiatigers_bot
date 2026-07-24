import unittest
from unittest.mock import Mock, patch

import requests

from telegram import TelegramBot


class TelegramBotTest(unittest.TestCase):
    @patch("telegram.time.sleep")
    def test_get_updates_skips_cycle_after_transient_failures(self, sleep):
        bot = TelegramBot("token", "chat")
        bot.session = Mock()
        bot.session.get.side_effect = requests.ConnectionError("reset")

        self.assertEqual(bot.get_updates(10), [])
        self.assertEqual(bot.session.get.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_get_updates_does_not_hide_http_errors(self):
        bot = TelegramBot("token", "chat")
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("unauthorized")
        bot.session = Mock()
        bot.session.get.return_value = response

        with self.assertRaises(requests.HTTPError):
            bot.get_updates()


if __name__ == "__main__":
    unittest.main()
