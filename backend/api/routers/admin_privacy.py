"""관리 > 개인정보 처리방침 — 기재사항 저장, 새 버전 공지, 공지 거두기, 지금 공지하면 게시될 내용(snapshot) (app_pages/admin/privacy_settings.py)."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import privacy, settings_store

router = APIRouter(prefix="/admin/privacy", tags=["admin-privacy"], dependencies=[Depends(require_admin)])

_FIELDS = ("operator", "officer_name", "officer_dept", "officer_email", "officer_phone", "request_dept",
           "smtp_vendor", "smtp_country", "databricks_region", "admin_measures")
_MAX = {"operator": 100, "officer_name": 60, "officer_dept": 60, "officer_email": 120, "officer_phone": 40,
        "request_dept": 100, "smtp_vendor": 80, "smtp_country": 40, "databricks_region": 40, "admin_measures": 500}


def _view() -> dict:
    vs = privacy.versions()
    cur = privacy.current()
    first = not vs
    return {
        "settings": privacy.settings(), "required": privacy.REQUIRED, "missing": privacy.missing(),
        "current": {"id": cur["id"], "effective_date": cur["effective_date"], "announced_at": cur["announced_at"],
                    "summary": cur["summary"]} if cur else None,
        "upcoming": len(privacy.upcoming()), "outdated": privacy.outdated() if vs else False, "first": first,
        "versions": [{k: v[k] for k in ("id", "announced_at", "effective_date", "summary", "status")} for v in vs],
        "notice_days": privacy.NOTICE_DAYS, "major_notice_days": privacy.MAJOR_NOTICE_DAYS,
        "default_effective_date": (date.today() if first else date.today() + timedelta(days=privacy.NOTICE_DAYS)).isoformat(),
        "default_summary": "개인정보 처리방침 제정" if first else "",
        "snapshot": privacy.snapshot(),
    }


@router.get("")
def get_privacy() -> dict:
    return _view()


@router.put("")
def put_privacy(request: Request, body: dict[str, Any]) -> dict:
    """기재사항 저장 — 준 키만 바꾼다. 공개 화면 반영은 새 버전 공지 후."""
    s = privacy.settings()
    new = {k: str(body.get(k, s.get(k, "")) or "").strip()[:_MAX[k]] for k in _FIELDS}
    new["smtp_country"] = new["smtp_country"] or "대한민국"
    new["databricks_region"] = new["databricks_region"] or "미국"
    settings_store.save_section("privacy", new)
    log_action(request, "개인정보 처리방침 기재사항 저장")
    return {"ok": True, **_view()}


@router.post("/publish")
def publish(request: Request, body: dict[str, Any]) -> dict:
    if privacy.missing():
        raise HTTPException(400, "비어 있는 필수 기재사항: " + ", ".join(privacy.missing()))
    eff = str(body.get("effective_date") or "")[:10]
    try:
        if date.fromisoformat(eff) < date.today():
            raise HTTPException(400, "시행일은 오늘 이후여야 합니다")
    except ValueError:
        raise HTTPException(400, "effective_date 는 YYYY-MM-DD 형식이어야 합니다")
    summary = str(body.get("summary") or "").strip()[:200]
    major = bool(body.get("major")) and bool(privacy.versions())  # 첫 게시는 '중요 변경' 없음
    try:
        vid = privacy.publish(eff, summary, major=major)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001 - 같은 시행일 중복 등
        raise HTTPException(400, f"공지하지 못했습니다: {str(e)[:200]}")
    log_action(request, "개인정보 처리방침 공지", f"{eff} 시행 · {summary}")
    return {"ok": True, "id": vid, **_view()}


@router.delete("/versions/{version_id}")
def withdraw(version_id: int, request: Request) -> dict:
    """시행 전 공지만 거둘 수 있다."""
    v = next((v for v in privacy.versions() if v["id"] == version_id), None)
    if not v:
        raise HTTPException(404, "공지한 버전이 없습니다")
    if not privacy.withdraw(version_id):
        raise HTTPException(400, "시행 중이거나 지난 버전은 거둘 수 없습니다")
    log_action(request, "개인정보 처리방침 공지 거둠", v["effective_date"])
    return {"ok": True, **_view()}
