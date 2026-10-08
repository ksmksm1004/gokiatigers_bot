from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests


class TelegramAPIError(requests.HTTPError):
    def __init__(self, method: str, status_code: int, description: str) -> None:
        self.method = method
        self.status_code = status_code
        self.description = description
        super().__init__(f"Telegram {method} failed ({status_code}): {description}")


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
        self._raise_api_error("getChatAdministrators", response)
        data = response.json()
        if not data.get("ok"):
            return []
        result = data.get("result")
        return result if isinstance(result, list) else []

    def send_photo(self, photo_url: str, caption: str) -> None:
        if self.dry_run:
            self._dry_run_each("photo", f"{photo_url}\n{caption}")
            return
        download_cache: dict[str, tuple[bytes, str, str]] = {}
        self._send_each(
            "photo",
            lambda chat_id: self._send_photo_to_chat(
                chat_id,
                photo_url,
                caption,
                download_cache=download_cache,
            ),
        )

    def send_photo_bytes(self, photo: bytes, caption: str, filename: str = "photo.png") -> None:
        if self.dry_run:
            self._dry_run_each("photo file", f"{filename} ({len(photo)} bytes)\n{caption}")
            return

        def send(chat_id: str) -> None:
            try:
                self._post_photo_bytes(chat_id, photo, caption, filename)
            except TelegramAPIError as exc:
                if exc.status_code != 400:
                    raise
                logging.warning(
                    "Telegram rejected uploaded photo for chat %s: %s. Sending text instead.",
                    chat_id,
                    exc.description,
                )
                self._post("sendMessage", self._message_payload(chat_id, caption))

        self._send_each(
            "photo file",
            send,
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
        download_cache: dict[str, tuple[bytes, str, str]] = {}

        def send(chat_id: str) -> None:
            try:
                self._post("sendMediaGroup", {"chat_id": chat_id, "media": media})
                return
            except TelegramAPIError as exc:
                if exc.status_code != 400:
                    raise
                logging.warning(
                    "Telegram rejected remote media group for chat %s: %s. Sending individual uploads.",
                    chat_id,
                    exc.description,
                )
            for photo_url, caption in items[:10]:
                self._send_photo_to_chat(
                    chat_id,
                    photo_url,
                    caption,
                    prefer_upload=True,
                    download_cache=download_cache,
                )

        self._send_each(
            "media group",
            send,
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
                self._raise_api_error("getUpdates", response)
                data = response.json()
                if not data.get("ok"):
                    return []
                return data.get("result", [])
            except TelegramAPIError:
                raise
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 0:
                    logging.warning("Telegram getUpdates failed. Retrying once.")
                    time.sleep(0.5)
                    continue
                logging.warning("Telegram getUpdates failed again. Skipping this polling cycle.")
        return []

    def _post(self, method: str, payload: dict[str, Any]) -> None:
        try:
            response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=10)
        except requests.RequestException as exc:
            raise TelegramAPIError(method, 0, f"transport error: {type(exc).__name__}") from None
        if response.status_code == 429:
            retry_after = 3
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", retry_after))
            except (TypeError, ValueError):
                retry_after = 3
            logging.warning("Telegram rate limited on %s. Retrying after %ss.", method, retry_after)
            time.sleep(min(retry_after + 1, 65))
            try:
                response = self.session.post(f"{self.base_url}/{method}", json=payload, timeout=10)
            except requests.RequestException as exc:
                raise TelegramAPIError(method, 0, f"transport error: {type(exc).__name__}") from None
        self._raise_api_error(method, response)

    def _post_photo_bytes(
        self,
        chat_id: str,
        photo: bytes,
        caption: str,
        filename: str,
        content_type: str = "image/png",
    ) -> None:
        payload = {"chat_id": chat_id, "caption": caption}

        def post_photo():
            try:
                return self.session.post(
                    f"{self.base_url}/sendPhoto",
                    data=payload,
                    files={"photo": (filename, photo, content_type)},
                    timeout=20,
                )
            except requests.RequestException as exc:
                raise TelegramAPIError("sendPhoto", 0, f"transport error: {type(exc).__name__}") from None

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
        self._raise_api_error("sendPhoto", response)

    def _send_photo_to_chat(
        self,
        chat_id: str,
        photo_url: str,
        caption: str,
        prefer_upload: bool = False,
        download_cache: dict[str, tuple[bytes, str, str]] | None = None,
    ) -> None:
        if not prefer_upload:
            try:
                self._post(
                    "sendPhoto",
                    {"chat_id": chat_id, "photo": photo_url, "caption": caption},
                )
                return
            except TelegramAPIError as exc:
                if exc.status_code != 400:
                    raise
                logging.warning(
                    "Telegram rejected remote photo for chat %s: %s. Uploading downloaded bytes.",
                    chat_id,
                    exc.description,
                )

        try:
            cache = download_cache if download_cache is not None else {}
            downloaded = cache.get(photo_url)
            if downloaded is None:
                downloaded = self._download_photo(photo_url)
                cache[photo_url] = downloaded
            photo, filename, content_type = downloaded
            self._post_photo_bytes(chat_id, photo, caption, filename, content_type)
            return
        except Exception:
            logging.exception(
                "Telegram photo upload fallback failed for chat %s. Sending text instead.",
                chat_id,
            )

        self._post("sendMessage", self._message_payload(chat_id, caption))

    def _download_photo(self, photo_url: str) -> tuple[bytes, str, str]:
        response = self.session.get(
            photo_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://m.sports.naver.com/",
            },
            timeout=15,
        )
        response.raise_for_status()
        photo = response.content
        if not photo:
            raise ValueError("Downloaded photo is empty.")
        content_type = str(response.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0]
        extension = {
            "image/gif": "gif",
            "image/png": "png",
            "image/webp": "webp",
        }.get(content_type, "jpg")
        return photo, f"photo.{extension}", content_type

    @staticmethod
    def _message_payload(chat_id: str, text: str) -> dict[str, Any]:
        return {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }

    def _raise_api_error(self, method: str, response: requests.Response) -> None:
        status_code = int(response.status_code or 0)
        if status_code < 400:
            return
        description = str(response.text or "HTTP error")[:500]
        try:
            data = response.json()
            description = str(data.get("description") or description)[:500]
        except (TypeError, ValueError):
            pass
        if self.token:
            description = description.replace(self.token, "[redacted]")
        raise TelegramAPIError(method, status_code, description)

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
