from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests


class TelegramBot:
    def __init__(
        self,
        token: str,
        chat_ids: str | Iterable[str],
        dry_run: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self.token = token
        values = [chat_ids] if isinstance(chat_ids, str) else list(chat_ids)
        self.chat_ids = tuple(
            dict.fromkeys(str(value).strip() for value in values if str(value).strip())
        )
        self.chat_id = self.chat_ids[0] if self.chat_ids else ""
        self.dry_run = dry_run
        self.session = session or requests.Session()

    def for_chat(self, chat_id: str) -> TelegramBot:
        return TelegramBot(self.token, str(chat_id), self.dry_run, session=self.session)

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, reply_markup: dict[str, Any] | None = None) -> None:
        if self.dry_run:
            self._dry_run_each("message", text)
            return

        def send(chat_id: str) -> None:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": False,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup
            self._post("sendMessage", payload)

        self._send_each("message", send)

    def answer_callback_query(self, callback_query_id: str) -> None:
        if self.dry_run:
            return
        self._post("answerCallbackQuery", {"callback_query_id": callback_query_id})

    def get_chat_administrators(self, chat_id: str) -> list[dict[str, Any]]:
        if self.dry_run:
            return []
        response = self.session.get(
            f"{self.base_url}/getChatAdministrators",
            params={"chat_id": chat_id},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            return []
        result = data.get("result")
        return result if isinstance(result, list) else []

    def send_photo(self, photo_url: str, caption: str) -> None:
        if self.dry_run:
            self._dry_run_each("photo", f"{photo_url}\n{caption}")
            return
        self._send_each(
            "photo",
            lambda chat_id: self._post(
                "sendPhoto",
                {"chat_id": chat_id, "photo": photo_url, "caption": caption},
            ),
        )

    def send_photo_bytes(self, photo: bytes, caption: str, filename: str = "photo.png") -> None:
        if self.dry_run:
            self._dry_run_each("photo file", f"{filename} ({len(photo)} bytes)\n{caption}")
            return
        self._send_each(
            "photo file",
            lambda chat_id: self._post_photo_bytes(chat_id, photo, caption, filename),
        )

    def send_media_group(self, items: list[tuple[str, str]]) -> None:
        if not items:
            return
        if self.dry_run:
            for chat_id in self.chat_ids or ("",):
                for photo_url, caption in items:
                    logging.info("[DRY_RUN] Telegram media to %s %s:\n%s", chat_id, photo_url, caption)
                    print(f"{photo_url}\n{caption}")
            return

        media = [
            {"type": "photo", "media": photo_url, "caption": caption}
            for photo_url, caption in items[:10]
        ]
        self._send_each(
            "media group",
            lambda chat_id: self._post("sendMediaGroup", {"chat_id": chat_id, "media": media}),
        )

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
        for attempt in range(2):
            try:
                response = self.session.get(f"{self.base_url}/getUpdates", params=payload, timeout=10)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok"):
                    return []
                return data.get("result", [])
            except requests.HTTPError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 0:
                    logging.warning("Telegram getUpdates failed. Retrying once.")
                    time.sleep(0.5)
                    continue
                logging.warning("Telegram getUpdates failed again. Skipping this polling cycle.")
        return []

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

    def _post_photo_bytes(self, chat_id: str, photo: bytes, caption: str, filename: str) -> None:
        payload = {"chat_id": chat_id, "caption": caption}

        def post_photo():
            return self.session.post(
                f"{self.base_url}/sendPhoto",
                data=payload,
                files={"photo": (filename, photo, "image/png")},
                timeout=20,
            )

        response = post_photo()
        if response.status_code == 429:
            retry_after = 3
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", retry_after))
            except (TypeError, ValueError):
                retry_after = 3
            logging.warning("Telegram rate limited on sendPhoto. Retrying after %ss.", retry_after)
            time.sleep(min(retry_after + 1, 65))
            response = post_photo()
        response.raise_for_status()

    def _send_each(self, label: str, send: Callable[[str], None]) -> None:
        failures: list[Exception] = []
        for chat_id in self.chat_ids:
            try:
                send(chat_id)
            except Exception as exc:
                failures.append(exc)
                logging.exception("Telegram %s delivery failed for chat %s.", label, chat_id)
        if failures and len(failures) == len(self.chat_ids):
            raise failures[0]

    def _dry_run_each(self, label: str, content: str) -> None:
        for chat_id in self.chat_ids or ("",):
            logging.info("[DRY_RUN] Telegram %s to %s:\n%s", label, chat_id, content)
            print(content)
