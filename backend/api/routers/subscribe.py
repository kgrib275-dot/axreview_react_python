"""구독·확인·해지·추천·문의 (/api/subscribe, /api/subscribe/confirm, /api/unsubscribe, /api/refer, /api/contact).

Streamlit 판 app/dialogs.py(subscribe·contact), app_pages/confirm.py·unsubscribe.py·refer.py 를 옮겼다.
- 이미 구독 중인 주소인지 알려 주지 않는다 (남의 주소가 구독 중인지 확인하는 데 쓰일 수 있음). 추천 링크도
  화면에 보여 주지 않고 메일 하단(본인만 받는 주소)으로 보낸다.
- 확인·해지는 링크를 연 것만으로 확정하지 않는다 (메일 보안 검사기·미리보기 대비) — POST 로만 바뀐다.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading

from fastapi import APIRouter, Body, HTTPException, Query

from api.deps import Caller, CallerDep, throttle
from api.routers import me as me_state
from pipeline import db, email_check, engage, industry, mailer, referral, report_pdf

router = APIRouter(tags=["subscribe"])

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
SOURCES = {"header", "sticky_bar", "home_hero", "home_cta", "note_detail", "today", "type_test", "terms", "diagnosis", "habit", "career", "ask",
           "lab", "letter", "about", "refer", "notes"}


def _email(v) -> str:
    email = str(v or "").strip()
    if len(email) > 254 or not db.EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="이메일 주소 형식을 확인해 주세요.")
    return email


CONFIRM_MAIL_GAP_MIN = 10   # 같은 주소로 확인 메일은 10분에 한 번
CONFIRM_MAIL_PER_DAY = 3    # 하루 3번까지 — 남의 주소로 신청을 반복해 메일 폭탄을 보내지 못하게


MAIL_ACTIONS = ("confirm_mail", "ask_link_mail")  # 방문자가 남의 주소로 일으킬 수 있는 메일 — 하루 상한은 이 합계로 센다
log = logging.getLogger("axreview.subscribe")


def _may_mail(email: str, action: str = "confirm_mail", page: str = "구독 확인 메일") -> bool:
    """같은 주소로 보내는 메일 제한 (확인 메일, 질문하기 연결 메일 — api/routers/ask.py 도 action 을 달리해 쓴다).
    간격(10분)은 종류별, 하루 상한(3통)은 종류 합계 — 예전엔 종류별로 따로 세어 한 주소에 하루 6통까지 갔다 (2026-10-30)."""
    key = hashlib.sha256(email.lower().encode()).hexdigest()[:24]  # 주소 자체는 접속 기록에 남기지 않는다
    if db.access_count_detail_since(action, key, CONFIRM_MAIL_GAP_MIN):
        return False
    if sum(db.access_count_detail_since(a, key, 24 * 60) for a in MAIL_ACTIONS) >= CONFIRM_MAIL_PER_DAY:
        return False
    db.record_access(None, page, action, key)
    return True


def send_later(fn, *args) -> None:
    """메일을 백그라운드로 보낸다 — 요청 안에서 SMTP(수백 ms~수 초)를 기다리면 응답 시간 차이로 '이미 구독 중인 주소'인지
    알아낼 수 있었다 (2026-10-30 보안 점검). 실패는 서버 로그에만."""
    def run():
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("메일 발송 실패 (백그라운드)")
    threading.Thread(target=run, daemon=True).start()


@router.post("/subscribe")
def subscribe(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    email = _email(payload.get("email"))
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="만 14세 이상만 구독할 수 있습니다.")
    # 남용 제한을 DNS 확인보다 먼저 — 느린 DNS 를 노린 요청 폭주로 서버 작업 슬롯이 묶이지 않게
    throttle("subscribe_try", c, per_visitor=3, per_ip=30)
    bad = email_check.problem(email, typo_ok=payload.get("typo_ok") is True)  # 오타·없는 도메인 — 신청 전에 알려 준다
    if bad:
        raise HTTPException(status_code=400, detail=bad)  # {message, suggest} — 화면이 '고친 주소로 신청' 버튼을 보여 준다
    inds = payload.get("industries") or []
    inds = [x for x in inds if isinstance(x, str) and x in industry.NAMES] if isinstance(inds, list) else []
    source = str(payload.get("source") or "header")[:40]
    if source not in SOURCES:
        source = "other"
    ref = payload.get("ref")
    ref = ref if isinstance(ref, str) and referral.valid_code(ref) else ""
    token = db.subscribe(email, ",".join(inds), ref)
    if token:
        engage.record("subscribe", source, value=ref, visitor=c.visitor)
        if mailer.is_configured() and _may_mail(email):
            send_later(mailer.send_confirmation, email, token)  # 실패하면 관리 > 구독·발송에서 다시 보낼 수 있다
    # 이미 구독 중이어도 같은 응답 — 존재 여부 비노출
    me_state.save_state(c.visitor, {"sub_pending": True, "pref_inds": inds})  # 확인 대기 — 완료(subscribed)는 confirm 에서 (개인화: 노트 업종 필터 기본값)
    reward = f"구독 후 메일 하단의 내 추천 링크로 친구 {referral.REWARD_AT}명이 구독하면 지난 호 주간 PDF 전체를 열어 드립니다."
    if mailer.is_configured():
        msg = f"{email} 으로 확인 메일을 보냈습니다. 메일의 '구독 확인하기'를 눌러야 구독이 완료됩니다. 메일이 안 보이면 스팸함도 확인해 주세요. " + reward
    else:  # 메일 발송 설정 전 — 보냈다고 하지 않는다
        msg = f"구독 신청을 받았습니다 ({email}). 확인 메일은 발송 준비가 끝나는 대로 보내 드립니다. 메일의 '구독 확인하기'를 눌러야 구독이 완료됩니다."
    return {"ok": True, "message": msg, "reward_at": referral.REWARD_AT}


@router.post("/subscribe/confirm")
def confirm(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    t = payload.get("t")
    if not isinstance(t, str) or not _TOKEN_RE.match(t):
        raise HTTPException(status_code=400, detail="확인 메일의 '구독 확인하기' 링크로 들어와 주세요.")
    throttle("confirm_try", c, per_visitor=10, per_ip=30)
    email = db.confirm_subscription(t)
    if not email:
        raise HTTPException(status_code=400, detail="링크가 만료됐거나 이미 확인된 신청입니다. 구독 창에서 다시 신청해 주세요.")
    engage.record("subscribe_confirm", visitor=c.visitor)
    db.link_subscriber_visitor(c.visitor, email=email)  # 확인한 브라우저 = 구독자 → 다음 메일부터 개인 블록(연속 참여·지난 예측·내 유형)
    me_state.save_state(c.visitor, {"subscribed": True, "sub_pending": None})
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
