from __future__ import annotations

from rapidfuzz import fuzz

from .models import Item
from .normalize import url_hash


def dedup_by_url_hash(items: list[Item], existing_hashes: set[str]) -> list[Item]:
    seen = set(existing_hashes)
    result = []
    for item in items:
        h = url_hash(item.url)
        item.url_hash = h
        if h in seen:
            continue
        seen.add(h)
        result.append(item)
    return result


def dedup_by_title_similarity(items: list[Item], existing_titles: list[str], threshold: float = 88.0) -> list[Item]:
    kept_titles = list(existing_titles)
    result = []
    for item in items:
        if any(fuzz.ratio(item.title, t) >= threshold for t in kept_titles):
            continue
        kept_titles.append(item.title)
        result.append(item)
    return result
