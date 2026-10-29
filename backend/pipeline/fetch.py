"""노트 초안용 원문 본문 추출.

외부 파서(lxml 등) 없이 <p> 문단만 모으는 단순 추출이다 — 사내 PC의 애플리케이션
제어 정책상 새 네이티브 확장을 피한다. 본문이 너무 짧으면(페이월·JS 렌더링·구글 뉴스
리다이렉트) 페이지가 공개한 JSON-LD 요약(abstract/description, 예: HBR)과 수집 시 받은 발췌문으로
대신한다 — 페이월 본문을 우회해 꺼내지는 않는다.
"""
from __future__ import annotations

import html
import json
import re

import httpx

from . import safe_http

_DROP_RE = re.compile(r"<(script|style|noscript|header|footer|nav|aside|form)\b.*?</\1>", re.S | re.I)
_P_RE = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_LD_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
MIN_BODY_CHARS = 600


def extract_text(page_html: str) -> str:
    cleaned = _DROP_RE.sub(" ", page_html)
    paras = []
    for raw in _P_RE.findall(cleaned):
        text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
        if len(text) >= 40:
            paras.append(text)
    return "\n\n".join(paras)


def ld_summary(page_html: str) -> str:
    """JSON-LD Article의 abstract(없으면 description)."""
    for raw in _LD_RE.findall(page_html):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for node in data.get("@graph", [data]) if isinstance(data, dict) else data:
            if isinstance(node, dict) and "Article" in str(node.get("@type", "")):
                text = node.get("abstract") or node.get("description") or ""
                if text:
                    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", text))).strip()
    return ""


def article_text(article: dict, max_chars: int = 15000) -> tuple[str, bool]:
    """(본문, 원문 확보 여부)를 반환한다."""
    try:
        resp = safe_http.get(article["url"])  # 사설·내부 주소 차단, 리다이렉트마다 재검사, 크기 제한
        body, summary = extract_text(resp.text), ld_summary(resp.text)
    except httpx.HTTPError:
        body = summary = ""
    if len(body) >= MIN_BODY_CHARS:
        return body[:max_chars], True
    fallback = "\n\n".join(x for x in (summary, article.get("excerpt") or "", article.get("summary_ko") or "") if x)
    return f"(원문 본문을 가져오지 못해 발췌만 제공됨)\n{fallback}", False
