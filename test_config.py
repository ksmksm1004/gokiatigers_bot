import os
import unittest
from unittest.mock import patch

from config import Settings, get_settings, parse_telegram_chat_ids


class TelegramChatSettingsTest(unittest.TestCase):
    def test_parses_and_deduplicates_comma_separated_chat_ids(self):
        self.assertEqual(
            parse_telegram_chat_ids("chat-a", "chat-a, -100200, -100300"),
            ("chat-a", "-100200", "-100300"),
        )

    def test_settings_combines_primary_and_additional_chat_ids(self):
        settings = Settings(
            telegram_token="token",
            telegram_chat_id="chat-a",
            telegram_chat_ids=("-100200",),
        )

        self.assertEqual(settings.all_telegram_chat_ids, ("chat-a", "-100200"))

    @patch("config.load_dotenv")
    def test_multiple_chat_ids_can_be_configured_without_legacy_value(self, load_dotenv):
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_CHAT_IDS": "chat-a,-100200",
            },
            clear=True,
        ):
            settings = get_settings()

        self.assertEqual(settings.telegram_chat_id, "chat-a")
        self.assertEqual(settings.all_telegram_chat_ids, ("chat-a", "-100200"))

    @patch("config.load_dotenv")
    def test_additional_ids_are_combined_with_the_existing_chat(self, load_dotenv):
        with patch.dict(
            os.environ,
            {
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_CHAT_ID": "chat-a",
                "TELEGRAM_CHAT_IDS": "-100200,chat-a",
            },
            clear=True,
        ):
            settings = get_settings()

        self.assertEqual(settings.all_telegram_chat_ids, ("chat-a", "-100200"))


if __name__ == "__main__":
    unittest.main()
