"""구독·확인·해지·추천·문의 (/api/subscribe, /api/subscribe/confirm, /api/unsubscribe, /api/refer, /api/contact).

Streamlit 판 app/dialogs.py(subscribe·contact), app_pages/confirm.py·unsubscribe.py·refer.py 를 옮겼다.
- 이미 구독 중인 주소인지 알려 주지 않는다 (남의 주소가 구독 중인지 확인하는 데 쓰일 수 있음). 추천 링크도
  화면에 보여 주지 않고 메일 하단(본인만 받는 주소)으로 보낸다.
- 확인·해지는 링크를 연 것만으로 확정하지 않는다 (메일 보안 검사기·미리보기 대비) — POST 로만 바뀐다.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, HTTPException, Query

from api.deps import Caller, CallerDep, throttle
from api.routers import me as me_state
from pipeline import db, engage, industry, mailer, referral, report_pdf

router = APIRouter(tags=["subscribe"])

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCES = {"header", "sticky_bar", "home_hero", "home_cta", "note_detail", "today", "type_test", "terms", "diagnosis",
           "lab", "letter", "about", "refer", "notes"}


def _email(v) -> str:
    email = str(v or "").strip()
    if len(email) > 254 or not db.EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="이메일 주소 형식을 확인해 주세요.")
    return email


@router.post("/subscribe")
def subscribe(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    email = _email(payload.get("email"))
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="만 14세 이상만 구독할 수 있습니다.")
    inds = payload.get("industries") or []
    inds = [x for x in inds if isinstance(x, str) and x in industry.NAMES] if isinstance(inds, list) else []
    source = str(payload.get("source") or "header")[:40]
    if source not in SOURCES:
        source = "other"
    throttle("subscribe_try", c, per_visitor=3, per_ip=10)
    ref = payload.get("ref")
    ref = ref if isinstance(ref, str) and referral.valid_code(ref) else ""
    token = db.subscribe(email, ",".join(inds), ref)
    if token:
        engage.record("subscribe", source, value=ref, visitor=c.visitor)
        mailer.send_confirmation(email, token)  # SMTP가 없으면 관리 화면에서 나중에 보낸다
    # 이미 구독 중이어도 같은 응답 — 존재 여부 비노출
    me_state.save_state(c.visitor, {"subscribed": True, "pref_inds": inds})  # 노트 업종 필터 기본값 (개인화)
    return {"ok": True, "message": "확인 메일을 보냈습니다. 메일의 '구독 확인하기'를 눌러야 구독이 완료됩니다. "
                                   f"구독 후 메일 하단의 내 추천 링크로 친구 {referral.REWARD_AT}명이 구독하면 지난 호 주간 PDF 전체를 열어 드립니다.",
            "reward_at": referral.REWARD_AT}


@router.post("/subscribe/confirm")
def confirm(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    t = payload.get("t")
    if not isinstance(t, str) or not _TOKEN_RE.match(t):
        raise HTTPException(status_code=400, detail="확인 메일의 '구독 확인하기' 링크로 들어와 주세요.")
    throttle("confirm_try", c, per_visitor=10, per_ip=30)
    if not db.confirm_subscription(t):
        raise HTTPException(status_code=400, detail="링크가 만료됐거나 이미 확인된 신청입니다. 구독 창에서 다시 신청해 주세요.")
    engage.record("subscribe_confirm", visitor=c.visitor)
    me_state.save_state(c.visitor, {"subscribed": True})
    return {"ok": True, "message": "구독이 완료됐습니다. 다음 호부터 매주 월요일에 보내 드릴게요."}


def _unsub_token(v) -> str:
    token = str(v or "")[:100]
    if not _TOKEN_RE.match(token):
        raise HTTPException(status_code=404, detail="유효하지 않은 해지 링크입니다. 메일 하단의 링크를 다시 눌러 주세요.")
    return token


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}"


@router.get("/unsubscribe")
def unsubscribe_info(token: str = Query(""), c: Caller = CallerDep) -> dict:
    """해지 전 확인 화면 — 링크를 연 것만으로 해지하지 않는다."""
    token = _unsub_token(token)
    throttle("unsub_try", c, per_visitor=20, per_ip=60)
    rows = db._rows("SELECT email, active FROM subscribers WHERE token = ?", (token,))
    if not rows:
        raise HTTPException(status_code=404, detail="유효하지 않은 해지 링크입니다. 메일 하단의 링크를 다시 눌러 주세요.")
    return {"email_masked": _mask(rows[0]["email"]), "active": bool(rows[0]["active"])}


@router.post("/unsubscribe")
def unsubscribe(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    token = _unsub_token(payload.get("token"))
    throttle("unsub_try", c, per_visitor=20, per_ip=60)
    email = db.unsubscribe(token)
    if not email:
        raise HTTPException(status_code=404, detail="유효하지 않은 해지 링크입니다. 메일 하단의 링크를 다시 눌러 주세요.")
    me_state.save_state(c.visitor, {"subscribed": None})
    return {"ok": True, "email_masked": _mask(email),
            "message": f"{_mask(email)} 주소의 구독을 해지했습니다. 다시 받고 싶으면 홈에서 언제든 구독할 수 있습니다."}


@router.get("/refer")
def refer(k: str = Query(""), c: Caller = CallerDep) -> dict:
    """내 추천 현황 — 메일 하단 링크(본인만 아는 열쇠)로만 들어온다."""
    throttle("refer_try", c, per_visitor=30, per_ip=90)
    info = referral.by_token(k[:64])
    if not info:
        raise HTTPException(status_code=404, detail="메일 하단의 '내 추천 링크 받기'로 들어와 주세요. 구독을 해지했다면 다시 구독한 뒤 다음 메일의 링크를 쓰면 됩니다.")
    files = sorted(report_pdf.REPORT_DIR.glob("axreview_*.pdf"), reverse=True) if report_pdf.REPORT_DIR.exists() else []
    published = db.issues("published")
    latest = report_pdf.report_filename(published[-1]) if published else None
    pdfs = []
    for f in files:
        is_latest = f.name == latest
        label = f.stem.removeprefix("axreview_")
        if is_latest or info["unlocked"]:
            url = f"/r/{f.name}" if is_latest else referral.pdf_link(f.name)  # 지난 호: 7일짜리 서명 링크
            pdfs.append({"name": f.name, "label": label, "url": url, "locked": False, "latest": is_latest})
        else:
            pdfs.append({"name": f.name, "label": label, "url": None, "locked": True, "latest": False})
    return {"email": info["email"], "code": info["code"], "count": info["count"], "unlocked": info["unlocked"],
            "reward_at": referral.REWARD_AT, "link": f"{mailer.site_url()}/?ref={info['code']}", "pdfs": pdfs,
            "share": {"title": "AX Review — 기업 AX 노트를 매주 메일로",
                      "text": "기업 AI 전환(AX) 사례를 매주 한 번 정리해 보내 주는 뉴스레터인데, 실무에 꽤 도움이 됩니다. 구독은 무료예요."}}


@router.post("/contact")
def contact(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="개인정보 수집·이용에 동의해야 문의를 남길 수 있습니다.")
    name = str(payload.get("name") or "").strip()[:100]
    message = str(payload.get("message") or "").strip()[:5000]
    company = str(payload.get("company") or "").strip()[:100]
    if not (name and message):
        raise HTTPException(status_code=400, detail="이름과 내용을 입력해 주세요.")
    email = _email(payload.get("email"))
    if not engage.attempt("contact_try", c.visitor, c.ip, per_visitor=3, per_ip=10):
        raise HTTPException(status_code=429, detail="문의가 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
    db.add_contact(name, email, company, message)
    return {"ok": True, "message": "문의가 접수됐습니다. 확인 후 답장 드리겠습니다."}
