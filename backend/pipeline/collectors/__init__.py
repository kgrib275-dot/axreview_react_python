from __future__ import annotations

import httpx

from ..models import Item
from .arxiv import collect_arxiv
from .hackernews import collect_hackernews
from .html_pages import collect_html
from .naver_news import collect_naver_news
from .reddit import collect_reddit
from .rss import collect_rss
from .youtube import collect_youtube


async def collect_source(
    src: dict,
    http_client: httpx.AsyncClient,
    naver_client_id: str,
    naver_client_secret: str,
    reddit_client_id: str = "",
    reddit_client_secret: str = "",
) -> list[Item]:
    src_type = src["type"]
    if src_type == "rss":
        return await collect_rss(src, http_client)
    if src_type == "html":
        return await collect_html(src, http_client)
    if src_type == "arxiv":
        return await collect_arxiv(src, http_client)
    if src_type == "hackernews":
        return await collect_hackernews(src, http_client)
    if src_type == "naver":
        return await collect_naver_news(src, http_client, naver_client_id, naver_client_secret)
    if src_type == "reddit":
        return await collect_reddit(src, http_client, reddit_client_id, reddit_client_secret)
    if src_type == "youtube":
        return await collect_youtube(src, http_client)
    raise ValueError(f"unknown source type: {src_type}")
