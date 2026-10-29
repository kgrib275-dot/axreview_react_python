from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import feedparser
import httpx

from ..models import Item
from .base import parse_feed_entry_published

log = logging.getLogger(__name__)


async def collect_youtube(source_cfg: dict, http_client: httpx.AsyncClient) -> list[Item]:
    channel_ids = source_cfg.get("channel_ids", [])
    if not channel_ids:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 24))

    items = []
    for channel_id in channel_ids:
        # YouTube의 feeds/videos.xml는 채널 하나가 일시적으로 404/5xx를 던지는 경우가
        # 잦다(실측 확인) — 채널 하나 실패로 나머지 채널까지 통째로 날아가지 않도록
        # 채널별로 격리해서 스킵한다.
        try:
            resp = await http_client.get(
                "https://www.youtube.com/feeds/videos.xml", params={"channel_id": channel_id}
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("YouTube channel %s fetch failed: %s", channel_id, e)
            continue
        parsed = feedparser.parse(resp.text)

        for entry in parsed.entries:
            published = parse_feed_entry_published(entry)
            if published is None or published < cutoff:
                continue
            items.append(Item(
                title=entry.title,
                url=entry.link,
                source=source_cfg.get("name", "YouTube"),
                source_type="youtube",
                published_at=published,
                excerpt=getattr(entry, "summary", "")[:300],
            ))
    return items
