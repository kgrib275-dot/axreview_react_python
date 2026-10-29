"""RSS가 없는 사이트를 목록 페이지 HTML로 수집한다 (HBR·BCG).

사이트마다 구조가 달라서 파서를 따로 둔다. 화면 구조가 바뀌면 0건이 나오므로, 0건이면
수집 결과의 소스별 오류에 남겨 관리 화면에서 바로 보이게 한다. robots.txt 확인(2026-10-28):
두 사이트 모두 아래 목록 페이지 경로는 허용.

- HBR: Next.js 페이지에 기사 목록 JSON(__NEXT_DATA__)이 그대로 들어 있어 카드 HTML보다 이쪽을 읽는다.
  책·PDF 상품도 섞여 있어 uri가 wp://website/article-content/... 인 기사만 쓴다.
- BCG: 카드(data-component-type="Promo")마다 제목 링크·날짜·설명이 있다. 맨 위 추천 카드 몇 개는
  날짜가 없어서 기사 페이지의 article:published_time 메타를 한 번 더 읽는다(최대 detail_limit건).
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..models import Item

_TAG_RE = re.compile(r"<[^>]+>")


def _text(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub(" ", raw or ""))).strip()


class LayoutChanged(RuntimeError):
    """목록을 하나도 못 찾음 — 사이트 화면 구조가 바뀐 것으로 본다."""


# ───────────────────────── HBR ─────────────────────────

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_HBR_WP = "wp://website/article-content/"


def parse_hbr(page_html: str) -> list[dict]:
    m = _NEXT_RE.search(page_html)
    if not m:
        raise LayoutChanged("HBR: __NEXT_DATA__ 없음")
    try:
        results = json.loads(m.group(1))["props"]["pageProps"]["staticState"]["controllers"]["resultList"]["state"]["results"]
    except (KeyError, TypeError, ValueError) as e:
        raise LayoutChanged(f"HBR: 기사 목록 경로 없음 ({e})") from e
    rows = []
    for r in results:
        uri, raw = r.get("uri", ""), r.get("raw") or {}
        if not uri.startswith(_HBR_WP) or not raw.get("publication_date"):
            continue
        rows.append({
            "title": _text(r.get("title")),
            "url": "https://hbr.org/" + uri[len(_HBR_WP):].removesuffix(".xml"),
            "published_at": datetime.fromtimestamp(raw["publication_date"] / 1000, tz=timezone.utc),
            "excerpt": _text(raw.get("abstract") or r.get("excerpt")),
        })
    return rows


# ───────────────────────── BCG ─────────────────────────

_BCG_TITLE_RE = re.compile(r'class="Promo-title"[^>]*>\s*<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_BCG_DATE_RE = re.compile(r'class="Promo-date[^"]*"[^>]*>(.*?)</', re.S)
_BCG_DESC_RE = re.compile(r'class="Promo-description[^"]*"[^>]*>(.*?)</div>', re.S)
_PUBLISHED_META_RE = re.compile(r'<meta[^>]+property="article:published_time"[^>]*content="([^"]+)"')


def parse_bcg(page_html: str) -> list[dict]:
    rows: dict[str, dict] = {}
    for block in page_html.split('data-component-type="Promo"')[1:]:
        m = _BCG_TITLE_RE.search(block)
        if not m or "/publications/" not in m.group(1):
            continue
        url = m.group(1) if m.group(1).startswith("http") else "https://www.bcg.com" + m.group(1)
        d, desc = _BCG_DATE_RE.search(block), _BCG_DESC_RE.search(block)
        published = None
        if d:
            try:
                published = datetime.strptime(_text(d.group(1)), "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        row = rows.setdefault(url, {"title": _text(m.group(2)), "url": url, "published_at": None, "excerpt": ""})
        row["published_at"] = row["published_at"] or published
        row["excerpt"] = row["excerpt"] or (_text(desc.group(1)) if desc else "")
    if not rows:
        raise LayoutChanged("BCG: Promo 카드 없음")
    return list(rows.values())


async def _bcg_published(url: str, http_client: httpx.AsyncClient) -> datetime | None:
    try:
        resp = await http_client.get(url)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    m = _PUBLISHED_META_RE.search(resp.text)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1)[:19])
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


# ───────────────────────── 공통 ─────────────────────────

_PARSERS = {"hbr": parse_hbr, "bcg": parse_bcg}


async def collect_html(source_cfg: dict, http_client: httpx.AsyncClient) -> list[Item]:
    parser = source_cfg["parser"]
    resp = await http_client.get(source_cfg["url"])
    resp.raise_for_status()
    rows = _PARSERS[parser](resp.text)

    if parser == "bcg":
        undated = [r for r in rows if r["published_at"] is None][: source_cfg.get("detail_limit", 8)]
        dates = await asyncio.gather(*(_bcg_published(r["url"], http_client) for r in undated))
        for r, dt in zip(undated, dates):
            r["published_at"] = dt

    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 168))
    return [
        Item(title=r["title"], url=r["url"], source=source_cfg["name"], source_type="html",
             published_at=r["published_at"], excerpt=r["excerpt"][:300])
        for r in rows
        if r["title"] and r["published_at"] and r["published_at"] >= cutoff
    ]
