import unittest
from unittest.mock import Mock, patch

import requests

from telegram import TelegramBot


class TelegramBotTest(unittest.TestCase):
    def test_send_message_broadcasts_to_every_configured_chat(self):
        bot = TelegramBot("token", ("chat-a", "chat-b"))
        response = Mock(status_code=200)
        bot.session = Mock()
        bot.session.post.return_value = response

        bot.send_message("KIA 경기 시작")

        self.assertEqual(bot.session.post.call_count, 2)
        self.assertEqual(
            [call.kwargs["json"]["chat_id"] for call in bot.session.post.call_args_list],
            ["chat-a", "chat-b"],
        )

    def test_for_chat_sends_only_to_the_selected_chat(self):
        bot = TelegramBot("token", ("chat-a", "chat-b"))
        response = Mock(status_code=200)
        bot.session = Mock()
        bot.session.post.return_value = response

        bot.for_chat("chat-b").send_message("명령 응답")

        bot.session.post.assert_called_once()
        self.assertEqual(bot.session.post.call_args.kwargs["json"]["chat_id"], "chat-b")

    def test_get_chat_administrators_returns_api_members(self):
        bot = TelegramBot("token", "-100200")
        response = Mock()
        response.json.return_value = {
            "ok": True,
            "result": [
                {"status": "creator", "user": {"id": 10}},
                {"status": "administrator", "user": {"id": 20}},
            ],
        }
        bot.session = Mock()
        bot.session.get.return_value = response

        administrators = bot.get_chat_administrators("-100200")

        self.assertEqual([member["user"]["id"] for member in administrators], [10, 20])
        self.assertEqual(bot.session.get.call_args.kwargs["params"], {"chat_id": "-100200"})
        response.raise_for_status.assert_called_once_with()

    def test_photo_and_media_group_broadcast_to_every_chat(self):
        bot = TelegramBot("token", ("chat-a", "chat-b"))
        response = Mock(status_code=200)
        bot.session = Mock()
        bot.session.post.return_value = response

        bot.send_photo("https://example.com/player.png", "선수 기록")
        bot.send_media_group([("https://example.com/lineup.png", "라인업")])

        self.assertEqual(
            [call.kwargs["json"]["chat_id"] for call in bot.session.post.call_args_list],
            ["chat-a", "chat-b", "chat-a", "chat-b"],
        )

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

    def test_send_photo_bytes_broadcasts_to_every_chat(self):
        bot = TelegramBot("token", ("chat-a", "chat-b"))
        response = Mock(status_code=200)
        bot.session = Mock()
        bot.session.post.return_value = response

        bot.send_photo_bytes(b"png-data", "KIA 선발 수비", "kia-defense.png")

        self.assertEqual(
            [call.kwargs["data"]["chat_id"] for call in bot.session.post.call_args_list],
            ["chat-a", "chat-b"],
        )


if __name__ == "__main__":
    unittest.main()
