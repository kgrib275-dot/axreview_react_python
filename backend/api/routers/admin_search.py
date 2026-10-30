"""관리 > 의미 검색·질문하기 — 임베딩 현황, 검색 테스트(Gemini 임베딩 1회), 공개 '질문하기' 설정 (app_pages/admin/search.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import agent_chat, db, settings_store, vectorizer

router = APIRouter(prefix="/admin", tags=["admin-search"], dependencies=[Depends(require_admin)])


@router.get("/search")
def search_status() -> dict:
    """벡터화 현황 + 진행 중 작업 + 키 유무 (검색 자체는 POST)."""
    return {"embeddings": db.embedding_counts(), "has_keys": vectorizer.has_api_keys(),
            "min_similarity": agent_chat.MIN_SIMILARITY, "jobs": admin_jobs.status()}


@router.post("/search")
def search_test(body: dict[str, Any]) -> dict:
    q = (body.get("q") or "").strip()
    if not q:
        raise HTTPException(400, "질문을 입력하세요")
    if not vectorizer.has_api_keys():
        raise HTTPException(400, "GEMINI_API_KEYS가 없어 의미 검색을 쓸 수 없습니다.")
    notes, articles = agent_chat.retrieve(q)
    return {
        "q": q, "sufficient": agent_chat.is_sufficient(notes, articles), "min_similarity": agent_chat.MIN_SIMILARITY,
        "results": [{"similarity": round(r["similarity"], 3), "kind": "노트", "title": r["title"], "id": r.get("id")} for r in notes]
        + [{"similarity": round(r["similarity"], 3), "kind": r["source"], "title": r["title"], "url": r.get("url")} for r in articles],
    }


@router.get("/ask-settings")
def get_ask_settings() -> dict:
    return {"ask": settings_store.load()["ask"], "has_keys": vectorizer.has_api_keys()}


@router.put("/ask-settings")
def put_ask_settings(request: Request, body: dict[str, Any]) -> dict:
    cfg = settings_store.load()["ask"]

    def num(key: str, lo: int, hi: int) -> int:
        try:
            v = int(body.get(key, cfg.get(key)))
        except (TypeError, ValueError):
            raise HTTPException(400, f"{key} 는 정수여야 합니다")
        if not lo <= v <= hi:
            raise HTTPException(400, f"{key} 는 {lo}~{hi} 사이여야 합니다")
        return v

    new = {**cfg, "enabled": bool(body.get("enabled", cfg["enabled"])),
           "free_credits": num("free_credits", 0, 100), "free_daily": num("free_daily", 0, 100), "member_daily": num("member_daily", 1, 500),
           "per_ip_daily": num("per_ip_daily", 1, 1000), "global_daily": num("global_daily", 1, 100000),
           "plan_price": str(body.get("plan_price", cfg.get("plan_price", "")) or "").strip()[:80],
           "web_search": bool(body.get("web_search", cfg["web_search"]))}
    settings_store.save_section("ask", new)
    log_action(request, "질문하기 설정 저장",
               f"사용={new['enabled']}, 무료횟수={new['free_credits']}, 구독={new['member_daily']}, IP당={new['per_ip_daily']}")
    return {"ok": True, "ask": new}
