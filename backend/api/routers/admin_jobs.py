"""관리 > 배치 작업 — 시작(jobs.start)·진행 상태(joblog 버퍼)·실행 기록(run_logs).

Streamlit 판 app/admin_ui.py 의 start_job / job_status / log_view / run_log_table / log_action 을 API 로 옮겼다.
log_action 은 다른 관리 라우터도 함께 쓴다 (접속 기록 테이블에 page='관리' 로 남김 → 관리자·접속에서 조회).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from pipeline import db, joblog, jobs, settings_store

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"], dependencies=[Depends(require_admin)])

# 작업별 kwargs 허용 목록 — 임의 인자가 작업 함수로 흘러가지 않게 한다 (jobs._JOBS 의 시그니처 기준)
_KWARGS = {
    "collect": {"only_sources"}, "draft": {"per_run", "min_score", "hashes"}, "weekly": {"target_day", "auto_publish"},
    "newsletter": {"only_to"}, "vectorize": {"limit"}, "teams": {"only_url"}, "report": {"issue_id"},
    "warehouse": {"full"},
}


def log_action(request: Request, action: str, detail: str = "") -> None:
    """관리자 행동 기록 (admin_ui.log_action) — 접속 기록에 action 을 달리해 남긴다."""
    raw = request.client.host if request.client else None
    ip, _ = settings_store.client_ip(raw, {k: v for k, v in request.headers.items()})
    db.record_access(ip, "관리", action, (detail or "")[:500])


def summary(kind: str, result: dict) -> str:
    """실행 기록 한 줄 요약 (admin_ui._summary)."""
    if not result:
        return ""
    if kind == "collect":
        s = (f"수집 {result.get('collected', 0)} → 신규 {result.get('new', 0)} → 키워드 통과 {result.get('filtered', 0)} "
             f"(채점 {result.get('scored', 0)}, 재채점 {result.get('rescored', 0)})")
        return s  # 실패 소스 수는 message("소스 N곳 실패")에 이미 있다
    if kind == "draft":
        return f"대상 {result.get('targets', 0)} · 초안 {len(result.get('created', []))} · 실패 {len(result.get('failed', []))}"
    if kind == "weekly":
        return f"{result.get('week')} · 노트 {result.get('notes')}편 · {'게시' if result.get('published') else '초안'}"
    if kind in ("newsletter", "teams"):
        return f"발송 {result.get('sent', 0)} · 실패 {len(result.get('failed', []))}"
    if kind == "vectorize":
        return " · ".join(f"{'노트' if t == 'notes' else '기사'} {v['embedded']}/{v['pending']}" for t, v in result.items()
                         if isinstance(v, dict))
    if kind == "report":
        return f"{result.get('file')} · {result.get('pages')}쪽"
    if kind == "warehouse":
        s = " · ".join(f"{t} {v['upserted']}" + (f"(-{v['deleted']})" if v["deleted"] else "")
                       for t, v in result.get("tables", {}).items() if v["upserted"] or v["deleted"]) or "바뀐 행 없음"
        if result.get("failed"):
            s += f" · 실패 {', '.join(result['failed'])}"
        return f"{result.get('target')} ← {s}"
    return ""


def run_log_rows(kind: str | None = None, limit: int = 50) -> list[dict]:
    """run_logs 표 (admin_ui.run_log_table) — 최근 300건 중 kind 로 거른 뒤 limit 개."""
    logs = [r for r in db.run_logs(300) if kind is None or r["kind"] == kind][:limit]
    out = []
    for r in logs:
        result = json.loads(r["result"] or "{}")
        out.append({
            "id": r["id"], "kind": r["kind"], "label": jobs.KIND_LABELS.get(r["kind"], r["kind"]),
            "started_at": r["started_at"], "finished_at": r.get("finished_at"), "trigger": r["trigger"],
            # 숫자 요약 + 메시지 둘 다 — 예전엔 메시지("소스 1곳 실패")가 있으면 수집 건수가 숨어 전부 실패한 것처럼 읽혔다 (2026-10-30)
            "ok": bool(r["ok"]), "message": r["message"] or "",
            "summary": " · ".join(x for x in (summary(r["kind"], result), r["message"] or "") if x),
            "result": result,
        })
    return out


def status() -> dict:
    """진행 중 작업 + 작업별 joblog 버퍼 (admin_ui.job_status). 다른 라우터의 화면 응답에도 끼워 넣는다."""
    running = jobs.active()
    last = joblog.last_finished()
    return {
        "active": [{"kind": k, "label": jobs.KIND_LABELS.get(k, k), "since": since,
                    "lines": [{"time": t, "level": lv, "msg": m} for t, lv, m in joblog.lines(k)]}
                   for k, since in running.items()],
        "last_finished": ({"kind": last[0], "label": jobs.KIND_LABELS.get(last[0], last[0]), "ended": last[1],
                           "lines": [{"time": t, "level": lv, "msg": m} for t, lv, m in joblog.lines(last[0])]}
                          if last and last[0] in jobs.KIND_LABELS else None),
        "kinds": jobs.KIND_LABELS,
    }


@router.get("/status")
def get_status() -> dict:
    return status()


@router.get("/logs")
def get_logs(kind: str | None = None, limit: int = 50) -> dict:
    if kind is not None and kind not in jobs.KIND_LABELS:
        raise HTTPException(400, "없는 작업 종류입니다")
    rows = run_log_rows(kind, max(1, min(limit, 300)))
    return {"logs": rows, "latest": rows[0]["result"] or {"message": rows[0]["message"]} if rows else None}


@router.get("/{kind}/log")
def get_joblog(kind: str) -> dict:
    """작업 하나의 실행 로그 버퍼 (수집 미리보기 'preview' 도 포함)."""
    if kind not in jobs.KIND_LABELS and kind != "preview":
        raise HTTPException(404, "없는 작업 종류입니다")
    return {"kind": kind, "running": kind in jobs.active(),
            "lines": [{"time": t, "level": lv, "msg": m} for t, lv, m in joblog.lines(kind)]}


@router.post("/{kind}")
def start_job(kind: str, request: Request, body: dict[str, Any] | None = None) -> dict:
    """작업 시작 — jobs._JOBS 에 있는 종류만, 허용된 kwargs 만 넘긴다. 이미 돌고 있으면 started=False."""
    if kind not in jobs._JOBS:
        raise HTTPException(400, f"없는 작업 종류입니다: {kind}")
    body = body or {}
    bad = set(body) - _KWARGS.get(kind, set())
    if bad:
        raise HTTPException(400, f"허용되지 않는 인자: {', '.join(sorted(bad))}")
    kwargs = dict(body)
    if kind == "weekly" and kwargs.get("target_day"):
        from datetime import date
        try:
            kwargs["target_day"] = date.fromisoformat(str(kwargs["target_day"]))
        except ValueError:
            raise HTTPException(400, "target_day 는 YYYY-MM-DD 형식이어야 합니다")
    started = jobs.start(kind, trigger="수동", **kwargs)
    if started:
        log_action(request, "작업 실행", jobs.KIND_LABELS[kind])
    return {"started": started, "kind": kind, "label": jobs.KIND_LABELS[kind],
            "message": f"{jobs.KIND_LABELS[kind]} 작업을 시작했습니다." if started else "이미 같은 작업이 진행 중입니다."}
