"""관리 > 주간 흐름 — 편집 관점(lens), AI 생성(jobs.start weekly), 직접 작성, 호별 편집(에디터 코멘트·리더 3가지 picks) (app_pages/admin/issues.py)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.common import note_card
from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import db, editorial, jobs, settings_store
from pipeline.llm import AUDIENCES

router = APIRouter(prefix="/admin", tags=["admin-issues"], dependencies=[Depends(require_admin)])


def _split(x) -> list[str]:
    if isinstance(x, list):
        return [str(w).strip() for w in x if str(w).strip()][:20]
    return [w.strip() for w in str(x or "").split(",") if w.strip()][:20]


def _week_info(day: date) -> dict:
    monday, sunday = jobs.week_bounds(day)
    pool = db.notes_published_between(monday.isoformat(), sunday.isoformat())
    return {"week": jobs.week_label(monday), "monday": monday.isoformat(), "sunday": sunday.isoformat(),
            "range": f"{monday:%Y.%m.%d} – {sunday:%m.%d}", "notes": len(pool)}


def _issue_row(it: dict) -> dict:
    """호 하나 + 그 주 후보 노트(picks 선택지) + picks 가 비었을 때의 자동 선정 미리보기."""
    pool = []
    if it.get("week_start"):
        mon, sun = jobs.week_bounds(date.fromisoformat(it["week_start"]))
        pool = db.notes_published_between(mon.isoformat(), sun.isoformat())
    ids = {n["id"] for n in pool}
    picks = [int(x) for x in (it.get("picks") or "").split(",") if x.strip().isdigit() and int(x) in ids]
    auto = editorial.leader_three(pool) if pool and not picks else []
    return {**it, "picks_list": picks,
            "candidates": [note_card(n) for n in pool],
            "leader_three": [{"id": t.get("id"), "title": t.get("title"), "point": t.get("point"), "category": t.get("category")}
                             for t in (editorial.leader_three(pool, it.get("picks") or "") if pool else [])],
            "auto_preview": [t.get("point", "")[:30] for t in auto]}


# ───────────────────────── 편집 관점 ─────────────────────────

@router.get("/lens")
def get_lens() -> dict:
    return {"lens": editorial.lens(), "audiences": AUDIENCES}


@router.put("/lens")
def put_lens(request: Request, body: dict[str, Any]) -> dict:
    audience = body.get("audience") or ""
    if audience and audience not in AUDIENCES:
        raise HTTPException(400, "주 독자 값을 확인해 주세요")
    lens = {"stance": (body.get("stance") or "").strip()[:120], "focus": _split(body.get("focus")),
            "industries": _split(body.get("industries")), "audience": audience}
    settings_store.save_section("lens", lens)
    log_action(request, "편집 관점 저장", lens["stance"][:40])
    return {"ok": True, "lens": lens}


# ───────────────────────── 주간 흐름 ─────────────────────────

@router.get("/issues")
def list_issues(target_day: str | None = None) -> dict:
    """목록(초안 포함) + 생성 대상 주 정보 + 직접 작성 기본값."""
    try:
        target = date.fromisoformat(target_day) if target_day else date.today() - timedelta(days=7)
    except ValueError:
        raise HTTPException(400, "target_day 는 YYYY-MM-DD 형식이어야 합니다")
    return {"issues": [_issue_row(it) for it in db.issues(status=None)],
            "target": {"day": target.isoformat(), **_week_info(target)},
            "this_week": _week_info(date.today()),
            "weekly_running": "weekly" in jobs.active(), "jobs": admin_jobs.status()}


@router.post("/issues/generate")
def generate(request: Request, body: dict[str, Any] | None = None) -> dict:
    """AI 로 주간 흐름 초안 쓰기 — jobs.start('weekly', target_day, auto_publish=False)."""
    body = body or {}
    try:
        target = date.fromisoformat(str(body.get("target_day"))) if body.get("target_day") else date.today() - timedelta(days=7)
    except ValueError:
        raise HTTPException(400, "target_day 는 YYYY-MM-DD 형식이어야 합니다")
    started = jobs.start("weekly", trigger="수동", target_day=target, auto_publish=False)
    if started:
        log_action(request, "작업 실행", f"주간 흐름 {target.isoformat()}")
    return {"started": started, "target": {"day": target.isoformat(), **_week_info(target)}}


@router.post("/issues")
def create_issue(request: Request, body: dict[str, Any]) -> dict:
    """직접 작성 — 바로 게시 (원본과 같음). week_start 를 주면 그 주 노트가 picks 후보가 된다."""
    week = (body.get("week") or "").strip()
    headline = (body.get("headline") or "").strip()
    if not (week and headline):
        raise HTTPException(400, "주차와 헤드라인은 필수입니다.")
    week_start = body.get("week_start") or None
    if week_start:
        try:
            week_start = jobs.week_bounds(date.fromisoformat(str(week_start)))[0].isoformat()
        except ValueError:
            raise HTTPException(400, "week_start 는 YYYY-MM-DD 형식이어야 합니다")
    issue_id = db.add_issue(week, (body.get("range") or "").strip(), (body.get("headline_em") or "").strip(), headline,
                            (body.get("body") or "").strip(), status=body.get("status") or "published", week_start=week_start)
    if body.get("editor_note") or body.get("picks"):
        db.update_issue(issue_id, editor_note=(body.get("editor_note") or "").strip()[:600],
                        picks=",".join(map(str, body.get("picks") or [])))
    log_action(request, "주간 흐름 직접 게시", week)
    return {"id": issue_id}


@router.put("/issues/{issue_id}")
def update_issue(issue_id: int, request: Request, body: dict[str, Any]) -> dict:
    """편집 저장. body.status = 'published'(게시/저장) | 'draft'(초안으로). picks 는 노트 id 목록(최대 3)."""
    it = next((i for i in db.issues(status=None) if i["id"] == issue_id), None)
    if not it:
        raise HTTPException(404, "주간 흐름이 없습니다")
    status = body.get("status") or "published"
    if status not in ("published", "draft"):
        raise HTTPException(400, "status 는 published 또는 draft 입니다")
    picks = body.get("picks")
    if picks is None:
        picks = it.get("picks") or ""
    elif isinstance(picks, list):
        picks = ",".join(str(int(p)) for p in picks[:3])
    else:
        picks = ",".join(x.strip() for x in str(picks).split(",") if x.strip().isdigit())[:50]
    fields = dict(
        week=(body.get("week", it["week"]) or "").strip(), range=(body.get("range", it["range"]) or "").strip(),
        headline_em=(body.get("headline_em", it["headline_em"]) or "").strip(),
        headline=(body.get("headline", it["headline"]) or "").strip(), body=(body.get("body", it["body"]) or "").strip(),
        editor_note=(body.get("editor_note", it.get("editor_note") or "") or "").strip()[:600], picks=picks,
    )
    if not (fields["week"] and fields["headline"]):
        raise HTTPException(400, "주차와 헤드라인은 필수입니다.")
    db.update_issue(issue_id, **fields, status=status)
    log_action(request, "주간 흐름 게시" if status == "published" else "주간 흐름 초안으로", fields["week"])
    return {"ok": True, "issue": _issue_row(next(i for i in db.issues(status=None) if i["id"] == issue_id))}


@router.delete("/issues/{issue_id}")
def delete_issue(issue_id: int, request: Request) -> dict:
    it = next((i for i in db.issues(status=None) if i["id"] == issue_id), None)
    if not it:
        raise HTTPException(404, "주간 흐름이 없습니다")
    db.delete_issue(issue_id)
    log_action(request, "주간 흐름 삭제", it["week"])
    return {"ok": True}
