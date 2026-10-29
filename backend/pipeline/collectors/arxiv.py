from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from ..models import Item
from .base import parse_feed_entry_published


async def collect_arxiv(source_cfg: dict, http_client: httpx.AsyncClient) -> list[Item]:
    categories = source_cfg.get("categories", ["cs.AI", "cs.CL", "cs.LG"])
    search_query = " OR ".join(f"cat:{c}" for c in categories)

    resp = await http_client.get(
        "http://export.arxiv.org/api/query",
        params={
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": source_cfg.get("max_results", 50),
        },
    )
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
            source=source_cfg.get("name", "arXiv"),
            source_type="arxiv",
            published_at=published,
            excerpt=getattr(entry, "summary", "")[:300],
        ))
    return items
