"""Persistent, article-based alerts for KIA trades and rookie draft results."""
from __future__ import annotations

import hashlib
import html
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from naver_api import unwrap


TEAM = re.compile(r"(?<![a-z])KIA(?![a-z])|기아|타이거즈", re.I)
UNCERTAIN = re.compile(
    r"루머|트레이드\s*설|이적설|가능성|전망|예상|시나리오|제안|추진|검토|논의|관심|"
    r"불발|무산|부인|사실무근|없다|아니다|않았다|만약|할까|될까|누굴|앞두|예정|개최|참가|[?？]"
)
RETROSPECTIVE = re.compile(
    r"출신|트레이드\s*(?:효과|성공작|실패작)|재조명|재평가|돌아보|되돌아|당시|"
    r"지난해|작년|\d+년\s*전|후일담|비화|효과|활약|대박|포토|\[사진\]"
)


def clean_text(value: Any) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).split())


def roster_news_kind(article: dict[str, Any]) -> str | None:
    """Require announcement language; this is a conservative headline filter."""
    title = clean_text(article.get("title"))
    if UNCERTAIN.search(title) or RETROSPECTIVE.search(title):
        return None
    if TEAM.search(title) and "트레이드" in title:
        if re.search(r"단행|성사|합의|발표|영입|이적|맞교환|완료|확정|공식|↔|\d\s*(?:대|:)\s*\d", title):
            return "트레이드"
    if re.search(r"신인\s*(?:선수\s*)?(?:드래프트|지명)", title):
        kia_related = TEAM.search(title) or TEAM.search(clean_text(article.get("subContent")))
        if kia_related and re.search(r"결과|명단|지명|선택|품었다|뽑았다|선발|완료|확정", title):
            return "신인 드래프트"
    return None


def article_time(article: dict[str, Any], timezone) -> datetime | None:
    try:
        value = datetime.fromisoformat(str(article.get("dateTime") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)


def article_id(article: dict[str, Any]) -> str | None:
    office = str(article.get("oid") or article.get("officeId") or "")
    aid = str(article.get("aid") or article.get("articleId") or "")
    return f"{office}/{aid}" if office.isdigit() and aid.isdigit() else None


def title_key(article: dict[str, Any]) -> str:
    title = re.sub(r"\[[^]]*\]|[^\w]", "", clean_text(article.get("title"))).lower()
    return hashlib.sha256(title.encode()).hexdigest()[:24]


def fetch_roster_news(client, now: datetime) -> list[dict[str, Any]]:
    articles = []
    for page in range(1, 4):
        rows = unwrap(client.section_news("kbaseball", page_size=100, page=page), "newsList")
        if not isinstance(rows, list):
            raise ValueError("Unexpected Naver news list response")
        articles.extend(row for row in rows if isinstance(row, dict))
        times = [article_time(row, now.tzinfo) for row in rows if isinstance(row, dict)]
        if len(rows) < 100 or any(t and t < now - timedelta(hours=48) for t in times):
            break
    return articles


def poll_roster_news(client, telegram, settings, state: dict[str, Any], now: datetime,
                     persist: Callable[[], None]) -> bool:
    if not settings.stove_news_enabled:
        return False
    tracking = state.setdefault("stoveNews", {})
    next_check = tracking.get("nextCheckAt")
    if next_check and now < datetime.fromisoformat(next_check):
        return False
    tracking["nextCheckAt"] = (now + timedelta(seconds=max(60, settings.stove_news_poll_seconds))).isoformat()
    persist()
    articles = fetch_roster_news(client, now)
    if not tracking.get("initializedAt"):
        tracking.update(
            initializedAt=now.isoformat(),
            seen={key: now.isoformat() for a in articles if (key := article_id(a))},
            sentTitles={}, pending=[],
        )
        persist()
        logging.info("KIA roster news monitoring initialized; existing articles were baselined without sending.")
        return False

    initialized = datetime.fromisoformat(tracking["initializedAt"])
    cutoff = max(initialized, now - timedelta(hours=48))
    seen = tracking.setdefault("seen", {})
    sent_titles = tracking.setdefault("sentTitles", {})
    pending = tracking.setdefault("pending", [])
    queued_titles = {item["titleKey"] for item in pending}
    for article in sorted(articles, key=lambda a: str(a.get("dateTime") or "")):
        key = article_id(article)
        published = article_time(article, now.tzinfo)
        if not key or key in seen or not published or not cutoff <= published <= now:
            continue
        kind = roster_news_kind(article)
        if not kind:
            continue
        fingerprint = title_key(article)
        seen[key] = now.isoformat()
        if fingerprint in sent_titles or fingerprint in queued_titles:
            continue
        queued_titles.add(fingerprint)
        pending.append({
            "id": key, "titleKey": fingerprint, "kind": kind,
            "title": clean_text(article.get("title"))[:500],
            "source": clean_text(article.get("sourceName") or article.get("officeName"))[:80],
            "published": published.isoformat(), "deliveredChats": [],
        })
    # Save the queue before sending; failures can be retried even if the feed moves on.
    persist()
    sent = False
    for item in list(pending[:5]):
        delivered = item["deliveredChats"]
        message = "\n".join([
            f"KIA 선수 소식 | {item['kind']}", item["title"],
            f"{item['source']} · {datetime.fromisoformat(item['published']).strftime('%m/%d %H:%M')}",
            f"https://m.sports.naver.com/kbaseball/article/{item['id']}",
        ])
        for chat in settings.all_telegram_chat_ids:
            if chat in delivered:
                continue
            try:
                telegram.for_chat(chat).send_message(message)
            except Exception:
                logging.exception("KIA roster news delivery failed for article %s.", item["id"])
                continue
            delivered.append(chat)
            sent = True
            persist()
        if settings.all_telegram_chat_ids and all(c in delivered for c in settings.all_telegram_chat_ids):
            sent_titles[item["titleKey"]] = now.isoformat()
            pending.remove(item)
            logging.info("Sent KIA %s article %s.", item["kind"], item["id"])
            persist()
    expiry = (now - timedelta(days=30)).isoformat()
    for history in (seen, sent_titles):
        for key in list(history):
            if history[key] < expiry:
                del history[key]
        while len(history) > 2000:
            del history[next(iter(history))]
    persist()
    return sent
