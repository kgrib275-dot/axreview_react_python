"""관리 > 수집 기사 — 기간·상태·점수·검색 필터 목록, 선택 초안 생성(jobs.start draft), 상태 변경 (app_pages/admin/articles.py)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.common import csv_list
from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import db, jobs

router = APIRouter(prefix="/admin/articles", tags=["admin-articles"], dependencies=[Depends(require_admin)])

_STATUSES = ("new", "drafted", "skipped")
_DAYS = (1, 3, 7, 30, 90)


def _row(a: dict) -> dict:
    return {
        "url_hash": a["url_hash"], "score": a["llm_score"] or 0, "title": a["title"],
        "summary": a["summary_ko"] or a["excerpt"] or "", "source": a["source"],
        "keywords": json.loads(a["matched_kw"] or "[]"), "published_at": (a["published_at"] or "")[:16],
        "collected_at": a.get("collected_at"), "status": a["status"], "url": a["url"],
    }


@router.get("")
def list_articles(days: int = 7, q: str = "", min_score: int = 3, status: str = "new") -> dict:
    """status: 쉼표 구분 (new,drafted,skipped), 비우면 전체."""
    if days not in _DAYS:
        raise HTTPException(400, f"days 는 {', '.join(map(str, _DAYS))} 중 하나입니다")
    statuses = [s for s in csv_list(status) if s in _STATUSES]
    ql = q.strip().lower()
    rows = [
        _row(a) for a in db.articles(days)
        if (not statuses or a["status"] in statuses) and (a["llm_score"] or 0) >= min_score
        and (not ql or ql in f"{a['title']} {a['summary_ko']} {a['source']}".lower())
    ]
    return {"articles": rows, "count": len(rows), "days": days, "min_score": min_score, "status": statuses,
            "draft_running": "draft" in jobs.active(), "jobs": admin_jobs.status()}


@router.post("/draft")
def draft_selected(request: Request, body: dict[str, Any]) -> dict:
    """선택 기사로 노트 초안 생성 (Gemini) — 이미 초안 작업이 돌고 있으면 started=False."""
    hashes = [h for h in (body.get("hashes") or []) if isinstance(h, str) and h]
    if not hashes:
        raise HTTPException(400, "기사를 선택하세요")
    started = jobs.start("draft", trigger="수동", hashes=hashes)
    if started:
        log_action(request, "초안 생성 요청", f"{len(hashes)}건")
    return {"started": started, "count": len(hashes)}


@router.put("/{url_hash}/status")
def set_status(url_hash: str, request: Request, body: dict[str, Any]) -> dict:
    status = body.get("status")
    if status not in _STATUSES:
        raise HTTPException(400, "status 는 new·drafted·skipped 중 하나입니다")
    if not db.article(url_hash):
        raise HTTPException(404, "기사가 없습니다")
    db.set_article_status(url_hash, status)
    return {"ok": True}


@router.put("/status")
def set_status_many(request: Request, body: dict[str, Any]) -> dict:
    """여러 건 한 번에 — {hashes: [...], status} (화면의 '선택 N건 건너뛰기/대기로 되돌리기')."""
    status = body.get("status")
    if status not in _STATUSES:
        raise HTTPException(400, "status 는 new·drafted·skipped 중 하나입니다")
    hashes = [h for h in (body.get("hashes") or []) if isinstance(h, str)]
    for h in hashes:
        db.set_article_status(h, status)
    log_action(request, "기사 상태 변경", f"{status} {len(hashes)}건")
    return {"ok": True, "count": len(hashes)}
