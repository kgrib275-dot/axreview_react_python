"""개인정보 처리방침 (/api/privacy) — 공지한 버전을 날짜별로 골라 본다 (기본: 지금 시행 중인 버전).

Streamlit 판 app_pages/privacy.py 를 옮겼다. 버전 내용은 공지할 때 고정된다(pipeline/privacy.py).
공지 전이면 지금 기능으로 만든 초안(snapshot)을 보여 준다. 개인정보를 처리하지 않으면 active=false.
'내 기록 지우기'는 DELETE /api/me, 문의는 POST /api/contact.
"""
from __future__ import annotations

import re

from fastapi import APIRouter

from api.deps import Caller, CallerDep
from pipeline import privacy

router = APIRouter(tags=["privacy"])

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/privacy")
def get_privacy(v: str | None = None, c: Caller = CallerDep) -> dict:
    active = privacy.active()
    out: dict = {"active": active, "versions": [], "current_date": None, "upcoming": [], "selected": None}
    if not active:
        return out
    vs = privacy.versions()
    meta = lambda x: {"id": x["id"], "announced_at": x["announced_at"], "effective_date": x["effective_date"],  # noqa: E731
                      "summary": x["summary"], "status": x["status"]}
    out["versions"] = [meta(x) for x in vs]
    out["upcoming"] = [meta(x) for x in privacy.upcoming()]
    if vs:
        cur = privacy.current() or vs[-1]
        out["current_date"] = cur["effective_date"]
        want = v if v and _DAY_RE.match(v) and any(x["effective_date"] == v for x in vs) else cur["effective_date"]
        sel = next(x for x in vs if x["effective_date"] == want)
        out["selected"] = {**meta(sel), "content": sel["content"]}
    else:
        out["draft"] = privacy.snapshot()
    if c.is_admin:  # 관리자에게만 보이는 점검 안내 (Streamlit 판과 같음)
        missing = privacy.missing()
        out["admin_notice"] = ("필수 기재사항이 비어 있습니다: " + ", ".join(missing) + " — 관리 > 개인정보 처리방침") if missing \
            else ("아직 공지한 처리방침이 없어 지금 기능으로 만든 초안을 보여 줍니다 — 관리 > 개인정보 처리방침에서 공지하세요." if not vs
                  else ("기능·설정이 가장 최근 공지와 다릅니다 — 새 버전을 공지하세요 (관리 > 개인정보 처리방침)." if privacy.outdated() else None))
    return out
