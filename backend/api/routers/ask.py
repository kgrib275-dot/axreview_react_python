"""AX 질문하기 (/api/ask, /api/ask/usage, /api/ask/web, /api/ask/redeem, /api/membership/request).

Streamlit 판 app_pages/ask.py·app/dialogs.py(membership_request)·pipeline/agent_chat.py 를 옮겼다.
- 한도는 DB 기록으로 센다 — 무료: 방문자당 free_daily회(+IP 한도), 월 구독: 구독 단위로 member_daily회, 전체 global_daily회.
- 한도 확인과 사용 기록은 QUOTA_LOCK 안에서 Gemini 를 부르기 '전에' 한다 (동시 요청으로 한도를 넘지 못하게). IP당 동시 1건.
- 질문 원문은 서버에 남기지 않는다 (access_logs 에는 길이만).
- 월 구독(member_id)은 visitor_state 에 저장하고 매번 membership.get 으로 다시 확인한다.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Body, HTTPException

from api.deps import Caller, CallerDep, throttle
from api.routers import me as me_state
from pipeline import agent_chat, db, engage, membership, settings_store

router = APIRouter(tags=["ask"])

MAX_QUESTION = 500
MAX_TURN = 4000
HISTORY_TURNS = 6  # 최근 3턴만 (비용·길이 제한)


def _cfg() -> dict:
    return settings_store.load()["ask"]


def _enabled(cfg: dict) -> bool:
    return bool(cfg["enabled"]) and agent_chat.has_api_keys()


def usage(c: Caller, cfg: dict, member: dict | None) -> dict:
    """(한도, 오늘 쓴 수, 한도 넘음, 전체 사용 수) — DB 기록 기준."""
    total = db.access_count_today_all("ask")
    if member:
        q, u = int(cfg["member_daily"]), membership.used_today(member["id"])
        over = u >= q
    else:
        q, u = int(cfg["free_daily"]), engage.count_today("ask", c.visitor)
        over = u >= q or db.access_count_today(c.ip, "ask") >= int(cfg["per_ip_daily"])
    global_hit = total >= int(cfg.get("global_daily", 40))
    return {"quota": q, "used": u, "limit_hit": not c.is_admin and (over or global_hit), "used_all": total,
            "global_hit": global_hit and not c.is_admin}


def _member(c: Caller) -> dict | None:
    return me_state.member_of(c.visitor)


@router.get("/ask/usage")
def ask_usage(c: Caller = CallerDep) -> dict:
    cfg = _cfg()
    member = _member(c)
    u = usage(c, cfg, member)
    return {"enabled": _enabled(cfg), "quota": u["quota"], "used": u["used"], "limit_hit": u["limit_hit"],
            "member": {"id": member["id"], "expires": member["expires"]} if member else None, "is_admin": c.is_admin,
            "free_daily": int(cfg["free_daily"]), "member_daily": int(cfg["member_daily"]),
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


def _reserve(c: Caller, cfg: dict, member: dict | None, detail: str) -> None:
    """질문 한 번 쓰기 — 한도를 다시 확인하고 Gemini 를 부르기 '전에' 기록한다. 쓸 수 없으면 429/409."""
    if not _enabled(cfg):
        raise HTTPException(status_code=503, detail="지금은 질문하기를 사용할 수 없습니다.")
    with agent_chat.QUOTA_LOCK:
        # 동시에 답을 만드는 질문: 방문자당 1개, IP당 IP_INFLIGHT_MAX 개 — 회사처럼 여러 명이 한 공인 IP를 써도 한 명 때문에 막히지 않게
        if not c.is_admin and (c.visitor in agent_chat.INFLIGHT or _ip_busy.get(c.ip, 0) >= IP_INFLIGHT_MAX):
            raise HTTPException(status_code=409, detail="앞선 질문의 답을 만드는 중입니다. 잠시 후 다시 물어 주세요.")
        if usage(c, cfg, member)["limit_hit"]:
            raise HTTPException(status_code=429, detail="질문 한도에 도달했습니다.")
        db.record_access(c.ip, "AX 질문하기", "ask", detail)  # 질문 원문은 남기지 않는다
        engage.record("ask", membership.ask_item(member["id"]) if member else "", visitor=c.visitor)
        agent_chat.INFLIGHT.add(c.visitor)
        _ip_busy[c.ip] = _ip_busy.get(c.ip, 0) + 1


IP_INFLIGHT_MAX = 4
_ip_busy: dict = {}


def _done(c: Caller) -> None:
    with agent_chat.QUOTA_LOCK:
        agent_chat.INFLIGHT.discard(c.visitor)
        n = _ip_busy.get(c.ip, 0) - 1
        if n > 0:
            _ip_busy[c.ip] = n
        else:
            _ip_busy.pop(c.ip, None)


@router.post("/ask")
def ask(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    cfg = _cfg()
    question = _question(payload)
    history = _history(payload.get("history"))
    member = _member(c)
    _reserve(c, cfg, member, f"{len(question)}자")
    site = os.environ.get("SITE_URL", "").rstrip("/")
    try:
        notes, articles = agent_chat.retrieve(question)
        context = agent_chat.build_context(notes, articles, site) if (notes or articles) else ""
        answer = agent_chat.clean_answer(agent_chat.ask(history, question, context))
    finally:
        _done(c)
    sources = (
        [{"title": n["title"], "url": f"{site}/notes?id={n['id']}", "kind": "노트", "sim": round(float(n["similarity"]), 3)} for n in notes]
        + [{"title": a["title"], "url": a["url"], "kind": a["source"], "sim": round(float(a["similarity"]), 3)} for a in articles]
    )
    fallback = False
    if agent_chat.is_failure(answer):  # Gemini 한도 소진 등 — 찾은 근거로 대신 답한다 (토큰 없음)
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
    _reserve(c, cfg, member, "web")
    try:
        answer = agent_chat.clean_answer(agent_chat.ask_with_web_search(history, question))
    finally:
        _done(c)
    if agent_chat.is_failure(answer):
        return {"answer": answer, "fallback": True}
    return {"answer": answer + "\n\n*웹 검색 기반 답변입니다.*", "fallback": False}


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
