"""AX 질문하기 (/api/ask, /api/ask/usage, /api/ask/web, /api/ask/link, /api/ask/link/confirm, /api/ask/request, /api/ask/redeem,
/api/membership/request).

Streamlit 판 app_pages/ask.py·app/dialogs.py(membership_request)·pipeline/agent_chat.py 를 옮겼다.
- 한도는 '구독자당 횟수제'다 (2026-10-30): 뉴스레터 구독자가 구독 확인 때 free_credits 회를 받고, 다 쓰면 '충전 요청' →
  관리자가 승인·충전(관리 > 구독·발송 > 구독자)한 만큼 쓴다. 하루 단위로 되살아나지 않는다 (subscribers.ask_credits/ask_used).
  구독자가 아닌 브라우저는 질문할 수 없다 (usage.linked=False, POST /ask 는 403).
- 브라우저↔구독자 연결: 구독 확인을 누른 브라우저는 그때 이어진다 (subscribe.py). 다른 브라우저는 /ask/link 로 구독 주소에
  연결 메일을 받아 /ask/link/confirm 으로 잇는다 (링크를 연 것만으로는 잇지 않는다 — 메일 보안 검사기 대비).
- 월 구독(코드, pipeline/membership.py)은 그대로 하루 member_daily 회. 관리자는 무제한. per_ip_daily·global_daily 는 남용 상한.
- 차감은 QUOTA_LOCK 안에서 LLM 을 부르기 '전에' 하고(동시 요청으로 한도를 넘지 못하게), LLM 이 실패하면 돌려준다. IP당 동시 4건.
- 질문 원문은 서버에 남기지 않는다 (access_logs 에는 길이만).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re

from fastapi import APIRouter, Body, HTTPException

from api.deps import Caller, CallerDep, throttle
from api.routers import me as me_state
from api.routers.subscribe import _email, _mask, _may_mail
from pipeline import agent_chat, alerts, db, engage, mailer, membership, settings_store

router = APIRouter(tags=["ask"])
log = logging.getLogger("axreview.ask")

MAX_QUESTION = 500
MAX_TURN = 4000
HISTORY_TURNS = 6  # 최근 3턴만 (비용·길이 제한)
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
NOT_LINKED = "AX 질문하기는 뉴스레터 구독자에게 제공됩니다. 무료로 구독한 뒤(또는 이미 구독 중이라면 구독한 이메일로 이 브라우저를 연결한 뒤) 질문해 주세요."


def _cfg() -> dict:
    return settings_store.load()["ask"]


def _enabled(cfg: dict) -> bool:
    return bool(cfg["enabled"]) and agent_chat.has_api_keys()


def _subscriber(c: Caller) -> dict | None:
    """이 브라우저에 이어진 구독자. 아직 횟수를 받은 적이 없으면(횟수제 전 구독자·관리자가 직접 넣은 주소) 지금 무료 횟수를 준다."""
    s = db.subscriber_by_visitor(c.visitor)
    if s and not s["ask_credits"] and not s["ask_used"] and db.ensure_ask_credits(s["email"]):
        s = db.subscriber_ask(s["email"])
    return s


def usage(c: Caller, cfg: dict, member: dict | None, sub: dict | None) -> dict:
    """(한도, 쓴 수, 한도 넘음, 전체 사용 수) — DB 기록 기준. 월 구독은 오늘 기준, 구독자는 누적 횟수 기준."""
    total = db.access_count_today_all("ask")
    ip_hit = db.access_count_today(c.ip, "ask") >= int(cfg["per_ip_daily"])
    if member:
        q, u = int(cfg["member_daily"]), membership.used_today(member["id"])
        over = u >= q
    elif sub:
        q, u = int(sub["ask_credits"]), int(sub["ask_used"])
        over = u >= q or ip_hit
    else:
        q, u, over = 0, 0, True  # 구독자가 아니면 질문할 수 없다
    global_hit = total >= int(cfg.get("global_daily", 40))
    return {"quota": q, "used": u, "limit_hit": not c.is_admin and (over or global_hit), "used_all": total,
            "global_hit": global_hit and not c.is_admin, "linked": bool(sub), "email_masked": _mask(sub["email"]) if sub else "",
            # 충전 요청을 남겼고 아직 충전되지 않은 상태(충전하면 ask_requested_at 이 지워진다)
            "requested": bool(sub and sub.get("ask_requested_at") and u >= q and not member)}


def _member(c: Caller) -> dict | None:
    return me_state.member_of(c.visitor)


@router.get("/ask/usage")
def ask_usage(c: Caller = CallerDep) -> dict:
    cfg = _cfg()
    member = _member(c)
    u = usage(c, cfg, member, _subscriber(c))
    return {"enabled": _enabled(cfg), "quota": u["quota"], "used": u["used"], "limit_hit": u["limit_hit"],
            "linked": u["linked"], "email_masked": u["email_masked"], "requested": u["requested"],
            "member": {"id": member["id"], "expires": member["expires"]} if member else None, "is_admin": c.is_admin,
            "free_credits": int(cfg.get("free_credits", 3)), "member_daily": int(cfg["member_daily"]),
            "plan_price": cfg.get("plan_price") or "", "global_hit": u["global_hit"], "web_search": bool(cfg.get("web_search")),
            "examples": ["제조 현장에 AI 에이전트를 도입한 사례 알려줘", "에이전트 운영 거버넌스는 어떻게 설계해?",
                         "이번 주 AX 흐름을 3줄로 요약해줘", "금융권 AX 노트만 모아줘"]}


def _history(raw) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for t in raw:
        if isinstance(t, dict) and t.get("role") in ("user", "assistant") and isinstance(t.get("content"), str) and t["content"].strip():
            out.append({"role": t["role"], "content": t["content"][:MAX_TURN]})
    return out[-HISTORY_TURNS:]


def _question(payload: dict) -> str:
    q = payload.get("question")
    if not isinstance(q, str) or not q.strip():
        raise HTTPException(status_code=400, detail="질문을 입력해 주세요.")
    if len(q) > MAX_QUESTION:
        raise HTTPException(status_code=400, detail=f"질문은 {MAX_QUESTION}자까지입니다.")
    return q.strip()


def _reserve(c: Caller, cfg: dict, member: dict | None, detail: str) -> str | None:
    """질문 한 번 쓰기 — 한도를 다시 확인하고 LLM 을 부르기 '전에' 기록·차감한다. 쓸 수 없으면 403/429/409.
    구독자 횟수를 차감했으면 그 이메일을 돌려준다 (실패 시 _done 이 돌려줄 수 있게)."""
    if not _enabled(cfg):
        raise HTTPException(status_code=503, detail="지금은 질문하기를 사용할 수 없습니다.")
    sub = None if (c.is_admin or member) else _subscriber(c)
    if not (c.is_admin or member or sub):
        raise HTTPException(status_code=403, detail=NOT_LINKED)
    with agent_chat.QUOTA_LOCK:
        # 동시에 답을 만드는 질문: 방문자당 1개, IP당 IP_INFLIGHT_MAX 개 — 회사처럼 여러 명이 한 공인 IP를 써도 한 명 때문에 막히지 않게
        if not c.is_admin and (c.visitor in agent_chat.INFLIGHT or _ip_busy.get(c.ip, 0) >= IP_INFLIGHT_MAX):
            raise HTTPException(status_code=409, detail="앞선 질문의 답을 만드는 중입니다. 잠시 후 다시 물어 주세요.")
        if usage(c, cfg, member, sub)["limit_hit"]:
            raise HTTPException(status_code=429, detail="질문 한도에 도달했습니다.")
        if sub and not db.ask_consume(sub["email"]):  # 조건부 UPDATE — 두 프로세스가 동시에 와도 한도를 넘지 못한다
            raise HTTPException(status_code=429, detail="질문 한도에 도달했습니다.")
        db.record_access(c.ip, "AX 질문하기", "ask", detail)  # 질문 원문은 남기지 않는다
        engage.record("ask", membership.ask_item(member["id"]) if member else "", visitor=c.visitor)
        agent_chat.INFLIGHT.add(c.visitor)
        _ip_busy[c.ip] = _ip_busy.get(c.ip, 0) + 1
    return sub["email"] if sub else None


IP_INFLIGHT_MAX = 4
_ip_busy: dict = {}


def _done(c: Caller, refund: str | None = None) -> None:
    """진행 중 표시를 지운다. refund 에 이메일이 있으면 차감한 1회를 돌려준다 (LLM 호출 실패)."""
    with agent_chat.QUOTA_LOCK:
        agent_chat.INFLIGHT.discard(c.visitor)
        n = _ip_busy.get(c.ip, 0) - 1
        if n > 0:
            _ip_busy[c.ip] = n
        else:
            _ip_busy.pop(c.ip, None)
    if refund:
        db.ask_refund(refund)


@router.post("/ask")
def ask(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    cfg = _cfg()
    question = _question(payload)
    history = _history(payload.get("history"))
    member = _member(c)
    charged = _reserve(c, cfg, member, f"{len(question)}자")
    site = os.environ.get("SITE_URL", "").rstrip("/")
    ok = False
    try:
        notes, articles = agent_chat.retrieve(question)
        context = agent_chat.build_context(notes, articles, site) if (notes or articles) else ""
        answer = agent_chat.clean_answer(agent_chat.ask(history, question, context))
        ok = not agent_chat.is_failure(answer)  # Gemini 한도 소진 등은 LLM 실패 — 횟수를 돌려준다
    finally:
        _done(c, refund=None if ok else charged)
    sources = (
        [{"title": n["title"], "url": f"{site}/notes?id={n['id']}", "kind": "노트", "sim": round(float(n["similarity"]), 3)} for n in notes]
        + [{"title": a["title"], "url": a["url"], "kind": a["source"], "sim": round(float(a["similarity"]), 3)} for a in articles]
    )
    fallback = False
    if not ok:  # 찾은 근거로 대신 답한다 (토큰 없음)
        answer, sources = agent_chat.fallback_answer(question, notes, articles)
        fallback = True
    return {"answer": answer, "sources": sources, "weak": not agent_chat.is_sufficient(notes, articles), "fallback": fallback}


@router.post("/ask/web")
def ask_web(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """근거가 약했던 답변을 웹 검색으로 다시 — 설정에서 켜져 있을 때만."""
    cfg = _cfg()
    if not cfg.get("web_search"):
        raise HTTPException(status_code=403, detail="웹 검색 보완이 꺼져 있습니다.")
    question = _question(payload)
    history = _history(payload.get("history"))
    member = _member(c)
    charged = _reserve(c, cfg, member, "web")
    ok = False
    try:
        answer = agent_chat.clean_answer(agent_chat.ask_with_web_search(history, question))
        ok = not agent_chat.is_failure(answer)
    finally:
        _done(c, refund=None if ok else charged)
    if not ok:
        return {"answer": answer, "fallback": True}
    return {"answer": answer + "\n\n*웹 검색 기반 답변입니다.*", "fallback": False}


# ───────────────────────── 구독자 연결 · 충전 요청 ─────────────────────────

@router.post("/ask/link")
def ask_link(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """구독한 주소로 '질문하기 연결' 메일을 보낸다. 구독 중인 주소인지 응답으로 알려 주지 않는다 (존재 여부 비노출)."""
    email = _email(payload.get("email")).lower()
    # 방문자당 시간 3번, IP당 하루 20번 — throttle 은 창이 하나라 IP 쪽은 따로 센다
    if db.access_count_since(c.ip, "ask_link_try", 24 * 60) >= 20:
        raise HTTPException(status_code=429, detail="잠시 후 다시 시도해 주세요.")
    throttle("ask_link_try", c, per_visitor=3, per_ip=20, minutes=60)
    token = db.issue_link_token(email)  # 활성·확인된 구독자가 아니면 None
    if token and mailer.is_configured() and _may_mail(email, "ask_link_mail", "질문하기 연결 메일"):
        try:
            mailer.send([(email, "")], "[AX Review] 질문하기 연결", lambda _t: mailer.ask_link_html(token))
        except Exception:  # noqa: BLE001 - SMTP 오류를 응답으로 드러내면 구독 여부가 새므로 삼킨다 (서버 로그에만)
            log.exception("질문하기 연결 메일 실패")
    engage.record("ask_link_mail", visitor=c.visitor)
    return {"ok": True, "message": "구독 중인 주소라면 연결 메일을 보냈습니다. 메일의 '질문하기 연결하기'를 눌러 주세요 (1시간 안에)."}


@router.post("/ask/link/confirm")
def ask_link_confirm(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """연결 메일의 토큰으로 이 브라우저를 구독자에 잇는다 — 화면의 버튼(POST)으로만."""
    t = payload.get("t")
    if not isinstance(t, str) or not _TOKEN_RE.match(t):
        raise HTTPException(status_code=400, detail="연결 메일의 '질문하기 연결하기' 링크로 들어와 주세요.")
    throttle("ask_link_confirm", c, per_visitor=10, per_ip=30)
    email = db.consume_link_token(t, c.visitor)
    if not email:
        raise HTTPException(status_code=400, detail="링크가 만료됐거나 이미 쓴 링크입니다. 질문하기 화면에서 연결 메일을 다시 요청해 주세요.")
    db.ensure_ask_credits(email)
    engage.record("ask_link", visitor=c.visitor)
    me_state.save_state(c.visitor, {"subscribed": True, "sub_pending": None})
    return {"ok": True, "email_masked": _mask(email)}


@router.post("/ask/request")
def ask_request(c: Caller = CallerDep) -> dict:
    """'충전 요청하기' — 구독자에 요청 시각을 남기고 관리자에게 알린다 (Teams·경보 메일, 구독자당 하루 한 번)."""
    sub = _subscriber(c)
    if not sub:
        raise HTTPException(status_code=403, detail=NOT_LINKED)
    throttle("ask_request_try", c, per_visitor=5, per_ip=20)
    if db.ask_request(sub["email"]):  # 이미 요청해 둔 상태면 다시 알리지 않는다
        engage.record("ask_request", visitor=c.visitor)
        masked = _mask(sub["email"])
        alerts.notify("질문 충전 요청", f"질문 충전 요청: {masked} — 관리 > 구독·발송 > 구독자에서 충전해 주세요.",
                      key=f"ask_request:{hashlib.sha256(sub['email'].encode()).hexdigest()[:16]}")
    return {"ok": True, "requested": True, "message": "요청했습니다. 충전되면 메일로 알려 드립니다."}


@router.post("/ask/redeem")
def redeem(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip() or len(code) > 40:
        raise HTTPException(status_code=400, detail="구독 코드를 입력해 주세요.")
    if not engage.attempt("member_try", c.visitor, c.ip, per_visitor=5, per_ip=10):  # 코드 맞히기 시도 방지
        raise HTTPException(status_code=429, detail="잠시 후 다시 시도해 주세요.")
    m = membership.redeem(code.strip())
    if not m:
        raise HTTPException(status_code=400, detail="코드를 확인해 주세요. 기간이 끝났다면 담당자에게 연장을 요청해 주세요.")
    me_state.save_state(c.visitor, {"member_id": m["id"]})
    engage.record("member_on", visitor=c.visitor)
    cfg = _cfg()
    return {"expires": m["expires"], "quota": int(cfg["member_daily"]), "id": m["id"]}


@router.post("/membership/request")
def membership_request(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    """결제는 사이트 밖에서 — 신청을 문의함에 남기면 담당자가 안내하고 코드를 보낸다."""
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="개인정보 수집·이용에 동의해야 신청할 수 있습니다.")
    name = str(payload.get("name") or "").strip()[:100]
    email = str(payload.get("email") or "").strip()[:254]
    company = str(payload.get("company") or "").strip()[:100]
    if not name:
        raise HTTPException(status_code=400, detail="이름을 입력해 주세요.")
    if not db.EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="이메일 주소 형식을 확인해 주세요.")
    throttle("contact_try", c, per_visitor=3, per_ip=10)
    engage.record("member_request", visitor=c.visitor)
    db.add_contact(name, email, company, "[월 구독 신청] AX 질문하기 월 구독을 신청합니다.")
    return {"ok": True, "message": "신청이 접수됐습니다. 담당자가 메일로 안내해 드릴게요."}
