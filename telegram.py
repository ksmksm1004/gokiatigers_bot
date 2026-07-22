from __future__ import annotations

import logging
import time
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

    def send_message(self, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        if self.dry_run:
            logging.info("[DRY_RUN] Telegram message:\n%s", text)
            print(text)
            return
        payload: dict[str, Any] = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": False}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self._post("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str) -> None:
        if self.dry_run:
            return
        self._post("answerCallbackQuery", {"callback_query_id": callback_query_id})

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

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        payload = {
            "commands": [
                {"command": command.lstrip("/"), "description": description}
                for command, description in commands
            ]
        }
        if self.dry_run:
            logging.info("[DRY_RUN] Telegram commands: %s", payload["commands"])
            return
        self._post("setMyCommands", payload)

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        if self.dry_run:
            return []
        payload: dict[str, Any] = {"timeout": 0}
        if offset is not None:
            payload["offset"] = offset
        response = self.session.get(f"{self.base_url}/getUpdates", params=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return []
        return data.get("result", [])

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=10)
        if response.status_code == 429:
            retry_after = 3
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", retry_after))
            except (TypeError, ValueError):
                retry_after = 3
            logging.warning("Telegram rate limited on %s. Retrying after %ss.", method, retry_after)
            time.sleep(min(retry_after + 1, 65))
            response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=10)
        response.raise_for_status()
