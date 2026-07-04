from __future__ import annotations

import logging
from typing import Any

import requests


class TelegramBot:
    def __init__(self, token: str, chat_id: str, dry_run: bool = False) -> None:
        self.token = token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self.session = requests.Session()

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str) -> None:
        if self.dry_run:
            logging.info("[DRY_RUN] Telegram message:\n%s", text)
            print(text)
            return
        self._post("sendMessage", {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": False})

    def send_photo(self, photo_url: str, caption: str) -> None:
        if self.dry_run:
            logging.info("[DRY_RUN] Telegram photo %s:\n%s", photo_url, caption)
            print(f"{photo_url}\n{caption}")
            return
        self._post("sendPhoto", {"chat_id": self.chat_id, "photo": photo_url, "caption": caption})

    def send_media_group(self, items: list[tuple[str, str]]) -> None:
        if not items:
            return
        if self.dry_run:
            for photo_url, caption in items:
                logging.info("[DRY_RUN] Telegram media %s:\n%s", photo_url, caption)
                print(f"{photo_url}\n{caption}")
            return

        media = [
            {"type": "photo", "media": photo_url, "caption": caption}
            for photo_url, caption in items[:10]
        ]
        self._post("sendMediaGroup", {"chat_id": self.chat_id, "media": media})

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=10)
        response.raise_for_status()
