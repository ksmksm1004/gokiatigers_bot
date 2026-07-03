from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    telegram_chat_id: str
    team_code: str = "HT"
    timezone: ZoneInfo = ZoneInfo("Asia/Seoul")
    poll_seconds: int = 5
    idle_poll_seconds: int = 300
    pregame_minutes: int = 60
    postgame_minutes: int = 30
    naver_game_id: str | None = None
    dry_run: bool = False
    state_path: Path = BASE_DIR / "logs" / "state.json"
    log_path: Path = BASE_DIR / "logs" / "bot.log"


def get_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token and not os.getenv("DRY_RUN"):
        raise RuntimeError("TELEGRAM_TOKEN is required. Put it in .env.")
    if not chat_id and not os.getenv("DRY_RUN"):
        raise RuntimeError("TELEGRAM_CHAT_ID is required. Put it in .env.")

    return Settings(
        telegram_token=token,
        telegram_chat_id=chat_id,
        team_code=os.getenv("TEAM_CODE", "HT"),
        poll_seconds=env_int("POLL_SECONDS", 5),
        idle_poll_seconds=env_int("IDLE_POLL_SECONDS", 300),
        pregame_minutes=env_int("PREGAME_MINUTES", 60),
        postgame_minutes=env_int("POSTGAME_MINUTES", 30),
        naver_game_id=os.getenv("NAVER_GAME_ID") or None,
        dry_run=os.getenv("DRY_RUN", "").lower() in {"1", "true", "yes", "y"},
    )
