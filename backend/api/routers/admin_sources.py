"""관리 > 수집 설정 — 소스 on/off, 키워드 규칙, 수집 미리보기(DB 저장 없음), 선택 소스 실제 수집 (app_pages/admin/collect_settings.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import db, joblog, jobs, llm, settings_store
from pipeline.filters import apply_keyword_filter

router = APIRouter(prefix="/admin", tags=["admin-sources"], dependencies=[Depends(require_admin)])


def _sources() -> list[dict]:
    return jobs.config()["sources"]


@router.get("/sources")
def get_sources() -> dict:
    sources = _sources()
    enabled = set(settings_store.enabled_sources([s["name"] for s in sources]))
    rows = [{"name": s["name"], "enabled": s["name"] in enabled, "group": s.get("group", ""), "type": s["type"],
             "hours": s.get("published_within_hours", 24), "url": s.get("url", "")} for s in sources]
    return {"sources": rows, "enabled_count": len(enabled), "total": len(rows),
            "collect_running": "collect" in jobs.active(), "jobs": admin_jobs.status()}


@router.put("/sources")
def put_sources(request: Request, body: dict[str, Any]) -> dict:
    """{enabled: [소스 이름…]} — 목록에 없는 이름은 버린다."""
    names = [s["name"] for s in _sources()]
    enabled = [n for n in names if n in set(body.get("enabled") or [])]
    settings_store.save_section("enabled_sources", enabled)
    log_action(request, "소스 설정 저장", f"{len(enabled)}/{len(names)}개 사용")
    return {"ok": True, "enabled": enabled}


@router.post("/sources/test")
def test_sources(body: dict[str, Any]) -> dict:
    """미리보기 — 지정 소스를 수집해 보고(저장 안 함) 키워드 통과 여부를 붙인다. 로그는 joblog 'preview' 버퍼."""
    names = [s["name"] for s in _sources()]
    picked = [n for n in (body.get("names") or []) if n in names]
    if not picked:
        raise HTTPException(400, "소스를 하나 이상 고르세요")
    joblog.begin("preview")
    try:
        items, errors = jobs.preview(picked)
    finally:
        joblog.end("preview")
    passed = {id(i) for i in apply_keyword_filter(list(items), db.load_active_keyword_rules())}
    return {
        "count": len(items), "passed": len(passed), "errors": {k: str(v) for k, v in errors.items()},
        "items": [{"passed": id(i) in passed, "source": i.source, "title": i.title,
                   "published_at": i.published_at.strftime("%Y-%m-%d %H:%M") if i.published_at else "", "url": i.url}
                  for i in items],
        "log": [{"time": t, "level": lv, "msg": m} for t, lv, m in joblog.lines("preview")],
    }


@router.post("/sources/collect")
def collect_selected(request: Request, body: dict[str, Any]) -> dict:
    """선택 소스 실제 수집 — jobs.start('collect', only_sources=[…]) (Gemini 채점 포함)."""
    names = [s["name"] for s in _sources()]
    picked = [n for n in (body.get("names") or []) if n in names]
    if not picked:
        raise HTTPException(400, "소스를 하나 이상 고르세요")
    started = jobs.start("collect", trigger="수동", only_sources=picked)
    if started:
        log_action(request, "작업 실행", f"수집 ({', '.join(picked)[:200]})")
    return {"started": started}


# ───────────────────────── 키워드 ─────────────────────────

@router.get("/keywords")
def get_keywords() -> dict:
    return {"keywords": db.list_keywords(), "modes": ["include", "exclude"], "categories": ["", *llm.CATEGORIES]}


@router.put("/keywords")
def put_keywords(request: Request, body: dict[str, Any]) -> dict:
    """표 전체 교체 — {keywords: [{keyword, aliases: [] | 'a, b', mode, weight, active, category}]}."""
    rows = []
    for r in body.get("keywords") or []:
        kw = str(r.get("keyword") or "").strip()
        if not kw:
            continue
        aliases = r.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.split(",") if a.strip()]
        mode = r.get("mode") or "include"
        if mode not in ("include", "exclude"):
            raise HTTPException(400, f"모드 값을 확인해 주세요: {kw}")
        category = r.get("category") or ""
        if category not in ("", *llm.CATEGORIES):
            raise HTTPException(400, f"카테고리 값을 확인해 주세요: {kw}")
        try:
            weight = float(r.get("weight") if r.get("weight") is not None else 1.0)
        except (TypeError, ValueError):
            raise HTTPException(400, f"가중치는 숫자여야 합니다: {kw}")
        rows.append({"keyword": kw, "aliases": [str(a) for a in aliases], "mode": mode,
                     "weight": min(5.0, max(0.1, weight)), "active": bool(r.get("active", True)), "category": category})
    db.replace_keywords(rows)
    log_action(request, "키워드 저장", f"{len(rows)}개")
    return {"ok": True, "count": len(rows)}
