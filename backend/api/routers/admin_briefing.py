"""관리 > 데일리 브리핑 — 날짜별 수집 현황(오늘은 실시간, 지난 날짜는 아카이브), 핵심 TOP5, 소스·카테고리별 (app_pages/admin/briefing.py).

AI 종합 브리핑(agent_chat.synthesize_spotlight)은 Gemini 를 쓰므로 ?spotlight=1 일 때만 만들고 15분 캐시한다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import agent_chat, archiving, db, jobs

router = APIRouter(prefix="/admin/briefing", tags=["admin-briefing"], dependencies=[Depends(require_admin)])

_SPOT_TTL = 900
_spot_lock = threading.Lock()
_spot_cache: dict[str, tuple[float, dict]] = {}  # 날짜 -> (만든 시각, {url: 브리핑})


def _today() -> str:
    return datetime.now(db.KST).strftime("%Y-%m-%d")


def _content(day: str) -> dict | None:
    if day == _today():
        arts = db.articles_on(day)
        return archiving.build_content(arts) if arts else None
    return db.get_archive(day)


def _spotlight(day: str, top: list[dict]) -> dict[str, str]:
    key = day + "|" + "|".join(a["url_hash"] for a in top)
    with _spot_lock:
        hit = _spot_cache.get(key)
        if hit and time.time() - hit[0] < _SPOT_TTL:
            return hit[1]
    try:
        out = agent_chat.synthesize_spotlight(top)
    except Exception:  # noqa: BLE001 - Gemini 한도·장애면 요약 없이 보여 준다
        out = {}
    with _spot_lock:
        _spot_cache.clear()
        _spot_cache[key] = (time.time(), out)
    return out


@router.get("/dates")
def dates() -> dict:
    today = _today()
    return {"today": today, "dates": [today] + db.archived_dates()}


@router.get("")
def briefing(date: str | None = None, spotlight: int = 0) -> dict:
    today = _today()
    day = (date or today)[:10]
    content = _content(day)
    if not content:
        return {"date": day, "is_today": day == today, "content": None, "spotlight": {}, "dates": [today] + db.archived_dates()}
    top = content.get("top_articles") or []
    briefs = _spotlight(day, top[:3]) if spotlight and day == today and top else {}
    return {"date": day, "is_today": day == today, "content": content, "spotlight": briefs,
            "categories": ["AX Strategy", "AX Implementation", "AX Enablement"],
            "draft_running": "draft" in jobs.active(), "dates": [today] + db.archived_dates()}


@router.post("/archive")
def archive(request: Request, body: dict[str, Any]) -> dict:
    """지난 날짜를 지금 확정(아카이브)한다 — 스케줄러가 매일 하는 일을 수동으로. 오늘·미래는 거부."""
    day = str(body.get("date") or "")[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "date 는 YYYY-MM-DD 형식이어야 합니다")
    if day >= _today():
        raise HTTPException(400, "오늘과 미래 날짜는 확정할 수 없습니다")
    if db.get_archive(day):
        return {"ok": True, "already": True}
    arts = db.articles_on(day)
    if not arts:
        raise HTTPException(404, "이 날짜에 수집된 기사가 없습니다")
    ok = db.insert_archive(day, archiving.build_content(arts))
    log_action(request, "데일리 아카이브 확정", day)
    return {"ok": ok, "already": not ok}


@router.post("/draft")
def draft_from_briefing(request: Request, body: dict[str, Any]) -> dict:
    """'이 기사로 노트 초안 만들기' — jobs.start('draft', hashes=[hash])."""
    h = body.get("hash") or body.get("url_hash")
    if not h:
        raise HTTPException(400, "hash 가 필요합니다")
    a = db.article(h)
    if not a:
        raise HTTPException(404, "기사가 없습니다")
    started = jobs.start("draft", trigger="수동", hashes=[h])
    if started:
        log_action(request, "초안 생성 요청", a["title"])
    return {"started": started}
