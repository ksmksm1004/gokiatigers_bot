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

    def test_send_photo_bytes_uses_multipart_upload(self):
        bot = TelegramBot("token", "chat")
        response = Mock(status_code=200)
        bot.session = Mock()
        bot.session.post.return_value = response

        bot.send_photo_bytes(b"png-data", "KIA 선발 수비", "kia-defense.png")

        url = bot.session.post.call_args.args[0]
        kwargs = bot.session.post.call_args.kwargs
        self.assertEqual(url, "https://api.telegram.org/bottoken/sendPhoto")
        self.assertEqual(kwargs["data"], {"chat_id": "chat", "caption": "KIA 선발 수비"})
        self.assertEqual(kwargs["files"]["photo"], ("kia-defense.png", b"png-data", "image/png"))
        response.raise_for_status.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
