from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from ..models import Item
from .base import parse_feed_entry_published


async def collect_rss(source_cfg: dict, http_client: httpx.AsyncClient) -> list[Item]:
    resp = await http_client.get(source_cfg["url"])
    resp.raise_for_status()
    parsed = feedparser.parse(resp.text)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 24))

    items = []
    for entry in parsed.entries:
        published = parse_feed_entry_published(entry)
        if published is None or published < cutoff:
            continue
        items.append(Item(
            title=entry.title,
            url=entry.link,
            source=source_cfg["name"],
            source_type="rss",
            published_at=published,
            excerpt=getattr(entry, "summary", "")[:300],
        ))
    return items
