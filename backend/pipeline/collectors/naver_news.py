from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx

from ..models import Item

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return html.unescape(_TAG_RE.sub("", text))


async def collect_naver_news(source_cfg: dict, http_client: httpx.AsyncClient, client_id: str, client_secret: str) -> list[Item]:
    if not client_id or not client_secret:
        return []

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 24))

    items = []
    for keyword in source_cfg.get("keywords", []):
        resp = await http_client.get(
            "https://openapi.naver.com/v1/search/news.json",
            params={"query": keyword, "display": source_cfg.get("display", 20), "sort": "date"},
            headers=headers,
        )
        resp.raise_for_status()
        for entry in resp.json().get("items", []):
            published = parsedate_to_datetime(entry["pubDate"])
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published < cutoff:
                continue
            items.append(Item(
                title=_strip_html(entry["title"]),
                url=entry.get("originallink") or entry["link"],
                source=source_cfg.get("name", "네이버뉴스"),
                source_type="naver",
                published_at=published,
                excerpt=_strip_html(entry.get("description", ""))[:300],
            ))
    return items
