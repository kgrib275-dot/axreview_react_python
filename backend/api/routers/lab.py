"""데이터 랩·지식 지도·참여 지도 HTML 문서 (/api/lab/html, /api/lab/map/html, /api/map/html).

React 화면은 iframe srcdoc 으로 띄운다. Streamlit 판 app_pages/lab.py·today.py 의 st.iframe 과 같은 문서.
참여 지도의 예시 데이터·개별 행(engage.map_data)은 관리자만 볼 수 있다 — 공개는 engage.map_public(묶은 값)만.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from api.deps import Caller, CallerDep
from app import datalab, geo_map
from pipeline import engage, knowledge, settings_store

router = APIRouter(tags=["lab"])

_cache: dict = {}


def _cached(key: str, fn, ttl: int):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


_HEADERS = {"Cache-Control": "private, max-age=120", "X-Content-Type-Options": "nosniff"}


@router.get("/lab/html", response_class=HTMLResponse)
def lab_html() -> HTMLResponse:
    """탐색 대시보드 — app/datalab.py 가 만들던 HTML 문서 그대로 (5분 캐시)."""
    html = _cached("lab", lambda: datalab.page_html(datalab.build_data()), 300)
    return HTMLResponse(html, headers=_HEADERS)


@router.get("/lab/map/html", response_class=HTMLResponse)
def knowledge_map_html() -> HTMLResponse:
    """지식 지도 — 노트·기사 임베딩을 2차원으로 펼친 문서 (10분 캐시)."""
    html = _cached("kmap", lambda: datalab.map_html(knowledge.knowledge_map()), 600)
    return HTMLResponse(html, headers=_HEADERS)


@router.get("/map/html", response_class=HTMLResponse)
def participation_map_html(days: int | None = Query(None, ge=1, le=3650), sample: str = "", c: Caller = CallerDep) -> HTMLResponse:
    """참여 지도. 공개: 서버에서 묶은 값만(설정의 예시 데이터 포함 여부 따름). 관리자: ?days·?sample=1 로 개별 행·예시 데이터."""
    if c.is_admin and (days or sample):
        data = engage.map_data(days, include_sample=sample == "1")
        return HTMLResponse(geo_map.html(data), headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    include = settings_store.load()["engage"]["sample_on_map"]
    html = _cached(f"pmap:{include}", lambda: geo_map.html(engage.map_public(include_sample=include)), 120)
    return HTMLResponse(html, headers=_HEADERS)
