import unittest
from unittest.mock import Mock, patch

import requests

from telegram import TelegramAPIError, TelegramBot


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
        response = Mock(status_code=200)
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
        response = Mock(status_code=401, text="Unauthorized")
        response.json.return_value = {"ok": False, "description": "Unauthorized"}
        bot.session = Mock()
        bot.session.get.return_value = response

        with self.assertRaises(TelegramAPIError):
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

    def test_send_photo_uploads_bytes_when_telegram_rejects_remote_url(self):
        bot = TelegramBot("token", "chat")
        rejected = Mock(status_code=400, text="Bad Request")
        rejected.json.return_value = {
            "ok": False,
            "description": "Bad Request: failed to get HTTP URL content",
        }
        uploaded = Mock(status_code=200)
        downloaded = Mock(
            status_code=200,
            content=b"png-data",
            headers={"Content-Type": "image/png"},
        )
        bot.session = Mock()
        bot.session.post.side_effect = [rejected, uploaded]
        bot.session.get.return_value = downloaded

        bot.send_photo("https://example.com/player.png", "투수 교체")

        self.assertEqual(bot.session.post.call_count, 2)
        self.assertEqual(
            bot.session.post.call_args_list[0].kwargs["json"]["photo"],
            "https://example.com/player.png",
        )
        upload = bot.session.post.call_args_list[1]
        self.assertEqual(upload.kwargs["data"], {"chat_id": "chat", "caption": "투수 교체"})
        self.assertEqual(upload.kwargs["files"]["photo"], ("photo.png", b"png-data", "image/png"))

    def test_send_photo_falls_back_to_text_when_upload_is_rejected(self):
        bot = TelegramBot("token", "chat")
        remote_rejected = Mock(status_code=400, text="Bad Request")
        remote_rejected.json.return_value = {
            "ok": False,
            "description": "Bad Request: failed to get HTTP URL content",
        }
        upload_rejected = Mock(status_code=400, text="Bad Request")
        upload_rejected.json.return_value = {
            "ok": False,
            "description": "Bad Request: photo_invalid_dimensions",
        }
        message_sent = Mock(status_code=200)
        downloaded = Mock(
            status_code=200,
            content=b"png-data",
            headers={"Content-Type": "image/png"},
        )
        bot.session = Mock()
        bot.session.post.side_effect = [remote_rejected, upload_rejected, message_sent]
        bot.session.get.return_value = downloaded

        with self.assertLogs(level="ERROR"):
            bot.send_photo("https://example.com/player.png", "투수 교체")

        text_fallback = bot.session.post.call_args_list[2].kwargs["json"]
        self.assertEqual(text_fallback["chat_id"], "chat")
        self.assertEqual(text_fallback["text"], "투수 교체")

    def test_media_group_falls_back_to_individual_file_uploads(self):
        bot = TelegramBot("token", "chat")
        group_rejected = Mock(status_code=400, text="Bad Request")
        group_rejected.json.return_value = {
            "ok": False,
            "description": "Bad Request: failed to send message #1 with the error message failed to get HTTP URL content",
        }
        uploaded = Mock(status_code=200)
        downloaded = Mock(
            status_code=200,
            content=b"jpeg-data",
            headers={"Content-Type": "image/jpeg"},
        )
        bot.session = Mock()
        bot.session.post.side_effect = [group_rejected, uploaded]
        bot.session.get.return_value = downloaded

        bot.send_media_group([("https://example.com/lineup.jpg", "선발 라인업")])

        self.assertEqual(bot.session.post.call_count, 2)
        self.assertEqual(bot.session.post.call_args_list[0].args[0], "https://api.telegram.org/bottoken/sendMediaGroup")
        upload = bot.session.post.call_args_list[1]
        self.assertEqual(upload.kwargs["files"]["photo"], ("photo.jpg", b"jpeg-data", "image/jpeg"))

    def test_telegram_api_error_does_not_expose_bot_token(self):
        bot = TelegramBot("super-secret-token", "chat")
        response = Mock(status_code=400, text="Bad Request")
        response.json.return_value = {"ok": False, "description": "Bad Request: chat not found"}
        bot.session = Mock()
        bot.session.post.return_value = response

        with self.assertLogs(level="ERROR"), self.assertRaises(TelegramAPIError) as raised:
            bot.send_message("테스트")

        self.assertNotIn("super-secret-token", str(raised.exception))
        self.assertIn("chat not found", str(raised.exception))

    def test_telegram_transport_error_does_not_expose_bot_token(self):
        bot = TelegramBot("super-secret-token", "chat")
        bot.session = Mock()
        bot.session.post.side_effect = requests.ConnectionError(
            "connection failed for https://api.telegram.org/botsuper-secret-token/sendMessage"
        )

        with self.assertLogs(level="ERROR"), self.assertRaises(TelegramAPIError) as raised:
            bot.send_message("테스트")

        self.assertNotIn("super-secret-token", str(raised.exception))
        self.assertIn("transport error", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
