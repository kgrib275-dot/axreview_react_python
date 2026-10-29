"""관리 > 대시보드 — 숫자·연결 상태·Gemini 키 상태·켜진 스케줄·진행 중 작업·실행 기록 (app_pages/admin/dashboard.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import require_admin
from api.routers import admin_jobs
from pipeline import db, gemini_keys, jobs, llm, mailer, settings_store, vectorizer

router = APIRouter(prefix="/admin/dashboard", tags=["admin-dashboard"], dependencies=[Depends(require_admin)])

_SCHEDULE_LABELS = (("collection", "수집"), ("drafting", "초안"), ("weekly", "주간"), ("newsletter", "발송"),
                    ("vectorize", "벡터화"), ("teams", "Teams"))


def gemini_models() -> list[str]:
    g = jobs.config()["pipeline"]["gemini"]
    return sorted({g.get(k) or g["model"] for k in ("score_model", "note_model", "weekly_model", "chat_model")}
                  | {vectorizer.EMBEDDING_MODEL})


@router.get("")
def dashboard() -> dict:
    cfg = settings_store.load()
    models = gemini_models()
    return {
        "counts": db.counts(),
        "gemini_ok": llm.pool_from_env() is not None,
        "smtp_ok": mailer.is_configured(),
        "schedules_on": [n for k, n in _SCHEDULE_LABELS if cfg[k]["enabled"]],
        "drafting": {"min_score": cfg["drafting"]["min_score"], "per_run": cfg["drafting"]["per_run"]},
        "gemini": {"models": models, "rows": gemini_keys.status_rows(models)},
        "jobs": admin_jobs.status(),
        "run_logs": admin_jobs.run_log_rows(None, 50),
    }
