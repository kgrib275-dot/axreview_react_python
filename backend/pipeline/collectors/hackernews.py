from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..models import Item


async def collect_hackernews(source_cfg: dict, http_client: httpx.AsyncClient) -> list[Item]:
    params = {
        "tags": "story",
        "numericFilters": f"points>{source_cfg.get('min_points', 80)}",
        "query": source_cfg.get("query", ""),
    }
    resp = await http_client.get("https://hn.algolia.com/api/v1/search_by_date", params=params)
    resp.raise_for_status()
    data = resp.json()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 24))

    items = []
    for hit in data.get("hits", []):
        created = datetime.fromisoformat(hit["created_at"].replace("Z", "+00:00"))
        if created < cutoff:
            continue
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        items.append(Item(
            title=hit["title"],
            url=url,
            source=source_cfg["name"],
            source_type="hn",
            published_at=created,
        ))
    return items
