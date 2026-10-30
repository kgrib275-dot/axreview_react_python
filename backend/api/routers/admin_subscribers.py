"""관리 > 구독·발송 — 구독자·뉴스레터·월 구독·Teams 웹훅·문의 (app_pages/admin/subscribers.py).

- 구독자 token·confirm_token·ref_key 는 클라이언트에 내려보내지 않는다 (원본도 token 열을 뺐다).
- 월 구독 코드는 발급 응답에 한 번만 실린다 (저장은 해시).
- 웹훅 주소는 settings_store.webhook_url_ok 를 통과해야 등록·테스트한다.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from api.common import note_card
from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import db, jobs, mailer, membership, notify, referral, settings_store

router = APIRouter(prefix="/admin", tags=["admin-subscribers"], dependencies=[Depends(require_admin)])

_SUB_PUBLIC = ("email", "created_at", "active", "industries", "ref_code", "referred_by")


def _sub_rows(q: str = "") -> list[dict]:
    subs = db.subscribers()
    by_code = Counter(s["referred_by"] for s in subs if s.get("referred_by"))
    ql = q.strip().lower()
    out = []
    for s in subs:
        if ql and ql not in s["email"].lower():
            continue
        out.append({**{k: s.get(k) for k in _SUB_PUBLIC}, "active": bool(s["active"]), "confirmed": bool(s.get("confirmed_at")),
                    "referrals": by_code.get(s.get("ref_code") or "", 0) if s.get("ref_code") else 0})
    return out


# ───────────────────────── 구독자 ─────────────────────────

@router.get("/subscribers")
def list_subscribers(q: str = "") -> dict:
    rows = _sub_rows(q)
    all_rows = _sub_rows() if q.strip() else rows
    rc = referral.counts()
    return {"subscribers": rows, "total": len(all_rows), "active": sum(1 for r in all_rows if r["active"]),
            "referred": rc["referred"], "rewarded": rc["rewarded"], "reward_at": referral.REWARD_AT,
            "pending": len(db.pending_confirmations()), "smtp_ok": mailer.is_configured()}


@router.get("/subscribers/csv")
def subscribers_csv(request: Request) -> Response:
    df = pd.DataFrame(_sub_rows(), columns=[*_SUB_PUBLIC, "confirmed", "referrals"])
    body = db.csv_safe(df).to_csv(index=False).encode("utf-8-sig")
    log_action(request, "구독자 CSV 내려받기", f"{len(df)}명")  # 개인정보(이메일) 일괄 반출은 누가 언제 했는지 남긴다
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="subscribers.csv"'})


@router.post("/subscribers")
def add_subscriber(request: Request, body: dict[str, Any]) -> dict:
    """관리자가 직접 넣은 주소는 확인된 것으로(confirmed=True)."""
    email = (body.get("email") or "").strip()
    if not db.EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 형식을 확인해 주세요.")
    db.subscribe(email, confirmed=True)
    log_action(request, "구독자 추가", email)
    return {"ok": True}


@router.put("/subscribers/{email}")
def set_active(email: str, request: Request, body: dict[str, Any]) -> dict:
    email = email.strip().lower()
    if not any(s["email"] == email for s in db.subscribers()):
        raise HTTPException(404, "구독자가 없습니다")
    db.set_subscriber_active(email, bool(body.get("active")))
    log_action(request, "구독자 활성 상태 저장", f"{email}={bool(body.get('active'))}")
    return {"ok": True}


@router.put("/subscribers")
def set_active_many(request: Request, body: dict[str, Any]) -> dict:
    """여러 명 한 번에 — {rows: [{email, active}]} (화면의 '활성 상태 저장')."""
    known = {s["email"] for s in db.subscribers()}
    n = 0
    for r in body.get("rows") or []:
        email = str(r.get("email") or "").strip().lower()
        if email in known:
            db.set_subscriber_active(email, bool(r.get("active")))
            n += 1
    log_action(request, "구독자 활성 상태 저장", f"{n}명")
    return {"ok": True, "count": n}


@router.post("/subscribers/confirm-mails")
def resend_confirmations(request: Request) -> dict:
    """확인 대기 구독자에게 확인 메일 다시 보내기."""
    if not mailer.is_configured():
        raise HTTPException(400, ".env에 SMTP를 설정하면 보낼 수 있습니다")
    pending = db.pending_confirmations()
    sent = sum(bool(mailer.send_confirmation(p["email"], p["confirm_token"])) for p in pending)
    log_action(request, "구독 확인 메일 발송", f"{sent}/{len(pending)}")
    return {"sent": sent, "total": len(pending)}


# ───────────────────────── 뉴스레터 ─────────────────────────

@router.get("/newsletter")
def newsletter() -> dict:
    cfg = mailer.smtp_config()
    issue, notes, subject = jobs.newsletter_content()
    return {
        "smtp": {"configured": mailer.is_configured(), "host": cfg["host"], "port": cfg["port"], "tls": cfg["tls"],
                 "sender": cfg["sender"]},
        "subject": subject, "notes": [note_card(n) for n in notes],
        "issue": {"id": issue["id"], "week": issue["week"], "headline": issue["headline"]} if issue else None,
        "counts": {"notes": len(notes), "subscribers": db.counts()["subscribers"]},
        "html": mailer.build_html(issue, notes, pdf_url=jobs.latest_report_url(), preview=True),
        "preview_url": "/api/admin/newsletter/preview.html",
        "history": db.newsletters(),
        "send_running": "newsletter" in jobs.active(), "jobs": admin_jobs.status(),
    }


@router.get("/newsletter/preview.html")
def newsletter_preview() -> HTMLResponse:
    issue, notes, _ = jobs.newsletter_content()
    return HTMLResponse(mailer.build_html(issue, notes, pdf_url=jobs.latest_report_url(), preview=True))


@router.post("/newsletter/test")
def newsletter_test(request: Request, body: dict[str, Any]) -> dict:
    """테스트 발송 — 한 주소로 지금 바로(동기) 보낸다."""
    to = (body.get("to") or "").strip()
    if not db.EMAIL_RE.match(to):
        raise HTTPException(400, "이메일 형식을 확인해 주세요.")
    if not mailer.is_configured():
        raise HTTPException(400, "SMTP 미설정")
    try:
        res = jobs.run("newsletter", trigger="테스트", only_to=to)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"발송 실패: {str(e)[:200]}")
    log_action(request, "뉴스레터 테스트 발송", to)
    return {"ok": bool(res.get("sent")), "sent": res.get("sent", 0)}


@router.post("/newsletter/send")
def newsletter_send(request: Request) -> dict:
    """전체 발송 — jobs.start('newsletter')."""
    if not mailer.is_configured():
        raise HTTPException(400, "SMTP 미설정")
    started = jobs.start("newsletter", trigger="수동")
    if started:
        log_action(request, "작업 실행", "뉴스레터")
    return {"started": started}


# ───────────────────────── 월 구독 ─────────────────────────

def _member_row(m: dict) -> dict:
    expired = m["expires"] < date.today().isoformat()
    return {**m, "active": bool(m["active"]), "expired": expired,
            "state": "해지" if not m["active"] else ("만료" if expired else "이용 중"),
            "used_today": membership.used_today(m["id"])}


@router.get("/members")
def members() -> dict:
    return {"members": [_member_row(m) for m in membership.all_members()], "active_count": membership.active_count()}


@router.post("/members")
def issue_member(request: Request, body: dict[str, Any]) -> dict:
    """코드 발급 — 응답에 한 번만 실린다. 다시 볼 수 없다."""
    email = (body.get("email") or "").strip()
    if not db.EMAIL_RE.match(email):
        raise HTTPException(400, "이메일 형식을 확인해 주세요.")
    try:
        months = int(body.get("months") or 1)
    except (TypeError, ValueError):
        raise HTTPException(400, "개월은 1~12 사이 정수입니다")
    if not 1 <= months <= 12:
        raise HTTPException(400, "개월은 1~12 사이 정수입니다")
    memo = str(body.get("memo") or "").strip()[:200]
    code = membership.issue(email, months, memo)
    log_action(request, "월 구독 코드 발급", f"{email} {months}개월")
    return {"email": email, "code": code, "months": months}


def _find_member(member_id: int) -> dict:
    m = next((m for m in membership.all_members() if m["id"] == member_id), None)
    if not m:
        raise HTTPException(404, "월 구독자가 없습니다")
    return m


@router.post("/members/{member_id}/extend")
def extend_member(member_id: int, request: Request, body: dict[str, Any] | None = None) -> dict:
    m = _find_member(member_id)
    months = int((body or {}).get("months") or 1)
    if not 1 <= months <= 12:
        raise HTTPException(400, "개월은 1~12 사이 정수입니다")
    membership.extend(member_id, months)
    log_action(request, "월 구독 연장", m["email"])
    return {"ok": True, "member": _member_row(_find_member(member_id))}


@router.put("/members/{member_id}")
def set_member_active(member_id: int, request: Request, body: dict[str, Any]) -> dict:
    m = _find_member(member_id)
    active = bool(body.get("active"))
    membership.set_active(member_id, active)
    log_action(request, "월 구독 상태 변경", f"{m['email']}={active}")
    return {"ok": True, "member": _member_row(_find_member(member_id))}


# ───────────────────────── Teams 웹훅 ─────────────────────────

def _hook_row(w: dict) -> dict:
    return {"id": w["id"], "name": w["name"], "url_short": w["url"][:60] + "…", "enabled": w.get("enabled", True)}


@router.get("/webhooks")
def webhooks() -> dict:
    return {"webhooks": [_hook_row(w) for w in settings_store.load()["webhooks"]],
            "allowed_hosts": list(settings_store.WEBHOOK_HOSTS)}


@router.post("/webhooks")
def add_webhook(request: Request, body: dict[str, Any]) -> dict:
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not (name and settings_store.webhook_url_ok(url)):
        raise HTTPException(400, "이름과 Teams 웹훅 주소(https://…webhook.office.com 등)를 입력하세요.")
    settings_store.add_webhook(name, url)
    log_action(request, "웹훅 추가", name)
    return {"ok": True, "webhooks": [_hook_row(w) for w in settings_store.load()["webhooks"]]}


def _find_hook(hook_id: str) -> dict:
    w = next((w for w in settings_store.load()["webhooks"] if w["id"] == hook_id), None)
    if not w:
        raise HTTPException(404, "웹훅이 없습니다")
    return w


@router.put("/webhooks/{hook_id}")
def update_webhook(hook_id: str, request: Request, body: dict[str, Any]) -> dict:
    w = _find_hook(hook_id)
    fields: dict[str, Any] = {}
    if "enabled" in body:
        fields["enabled"] = bool(body["enabled"])
    if body.get("name"):
        fields["name"] = str(body["name"]).strip()
    if body.get("url"):
        if not settings_store.webhook_url_ok(str(body["url"])):
            raise HTTPException(400, "Teams 웹훅 주소만 등록할 수 있습니다.")
        fields["url"] = str(body["url"]).strip()
    if not fields:
        raise HTTPException(400, "바꿀 값이 없습니다")
    settings_store.update_webhook(hook_id, **fields)
    if "enabled" in fields:
        log_action(request, "웹훅 사용 변경", f"{w['name']}={fields['enabled']}")
    else:
        log_action(request, "웹훅 수정", w["name"])
    return {"ok": True, "webhook": _hook_row(_find_hook(hook_id))}


@router.delete("/webhooks/{hook_id}")
def delete_webhook(hook_id: str, request: Request) -> dict:
    w = _find_hook(hook_id)
    settings_store.delete_webhook(hook_id)
    log_action(request, "웹훅 삭제", w["name"])
    return {"ok": True}


@router.post("/webhooks/{hook_id}/test")
def test_webhook(hook_id: str) -> dict:
    w = _find_hook(hook_id)
    ok, msg = notify.post(w["url"], notify.build_test_card(), retries=0)
    return {"ok": ok, "name": w["name"], "message": msg}


# ───────────────────────── Teams 발송 ─────────────────────────

@router.get("/teams")
def teams() -> dict:
    issue, notes = jobs.teams_content()
    return {"issue": {"id": issue["id"], "week": issue["week"], "headline": issue["headline"]} if issue else None,
            "notes": [note_card(n) for n in notes], "count": len(notes),
            "card": notify.build_card(issue, notes, mailer.site_url(), jobs.latest_report_url()),
            "webhooks": [_hook_row(w) for w in settings_store.load()["webhooks"]],
            "send_running": "teams" in jobs.active(), "jobs": admin_jobs.status(),
            "run_logs": admin_jobs.run_log_rows("teams", 20)}


@router.post("/teams/send")
def teams_send(request: Request) -> dict:
    started = jobs.start("teams", trigger="수동")
    if started:
        log_action(request, "작업 실행", "Teams 발송")
    return {"started": started}


# ───────────────────────── 문의 ─────────────────────────

@router.get("/contacts")
def contacts() -> dict:
    rows = [{k: c.get(k) for k in ("id", "created_at", "name", "email", "company", "message")} for c in db.contacts()]
    return {"contacts": rows, "count": len(rows)}
