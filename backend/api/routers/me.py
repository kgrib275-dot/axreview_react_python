"""방문자 — 내 정보·화면 선택값 유지·내 기록 지우기 (/api/me).

Streamlit 판 streamlit_app.py(방문자 쿠키)와 app/state_keep.py(visitor_state 테이블)를 옮겼다.
- 허용 키만 저장한다 (노트 필터·용어 사전 검색·자가진단 문항·유형 테스트·용어 퀴즈 진행·월 구독·구독 여부·업종·약한 영역).
- 고른 값이 없는 새 방문(봇 포함)은 저장하지 않는다 — 빈 행이 쌓이지 않게.
- 질문하기 대화 내용은 개인적인 글이라 저장하지 않는다.
- 월 구독(member_id)은 저장만 하고 유효성은 매번 membership.get 으로 다시 확인한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Request, Response

from api.deps import COOKIE, COOKIE_MAX_AGE, Caller, CallerDep
from pipeline import agent_chat, db, engage, membership, privacy, settings_store

router = APIRouter(tags=["me"])

WIDGET_KEYS = {"q", "semantic", "cats", "kinds", "inds", "sort", "term_q"}  # 노트 필터·용어 사전 검색
WIDGET_PREFIXES = ("dq_",)  # 자가진단 문항
STATE_KEYS = {"axt_step", "axt_answers", "axt_recorded",  # 유형 테스트 진행·결과
              "term_track", "term_i", "term_picks", "term_qs", "term_seen", "term_recorded",  # 용어 퀴즈 진행
              "member_id",  # 월 구독 (다음 방문에 코드를 다시 넣지 않게, 유효성은 매번 다시 확인)
              "car_picks", "hab_answers",  # AX 커리어 유형·AI 활용 습관 진단 진행 (다른 페이지에 다녀와도 이어서)
              "subscribed", "sub_pending", "pref_inds", "diag_weak"}  # 구독 완료·확인 대기(신청한 주소)·고른 업종·자가진단 약한 영역 (개인화)
MAX_BYTES = 200_000

_SQL = "CREATE TABLE IF NOT EXISTS visitor_state (visitor TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)"
_ready: list = []  # 테이블 확인은 프로세스당 한 번


SERVER_ONLY = {"member_id"}  # 화면(PUT /me/state)이 바꿀 수 없는 키 — 서버가 확인한 뒤에만 쓴다 (/ask/redeem)


def kept(key: str) -> bool:
    return key in WIDGET_KEYS or key in STATE_KEYS or key.startswith(WIDGET_PREFIXES)


def _conn():
    conn = db.connect()
    if not _ready:
        conn.execute(_SQL)
        _ready.append(True)
    return conn


def load_state(visitor: str) -> dict:
    conn = _conn()
    try:
        row = conn.execute("SELECT data FROM visitor_state WHERE visitor=?", (visitor,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        data = json.loads(row["data"])
    except ValueError:
        return {}
    return {k: v for k, v in data.items() if kept(k)} if isinstance(data, dict) else {}


def save_state(visitor: str, changes: dict) -> dict:
    """허용 키만 기존 값에 합쳐 저장한다. 값이 null 이면 그 키를 지운다. 빈 스냅샷은 저장하지 않는다."""
    conn = _conn()
    conn.isolation_level = None
    try:
        # 읽고-합치고-쓰기를 한 쓰기 트랜잭션으로 — 같은 방문자의 저장 두 개가 겹쳐도 한쪽 값이 사라지지 않게
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT data FROM visitor_state WHERE visitor=?", (visitor,)).fetchone()
        snap = {}
        if row:
            try:
                snap = {k: v for k, v in json.loads(row["data"]).items() if kept(k)}
            except ValueError:
                snap = {}
        for k, v in changes.items():
            if not kept(k):
                continue
            if v is None:
                snap.pop(k, None)
                continue
            try:
                json.dumps(v)
            except (TypeError, ValueError):
                continue
            snap[k] = v
        # 고른 값이 없는 새 방문(봇 포함)은 저장하지 않는다 — 빈 행이 쌓이지 않게.
        if visitor and (snap or row):
            data = json.dumps(snap, ensure_ascii=False)
            if len(data) < MAX_BYTES:
                conn.execute("INSERT INTO visitor_state (visitor, data, updated_at) VALUES (?,?,?) "
                             "ON CONFLICT(visitor) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                             (visitor, data, datetime.now().isoformat(timespec="seconds")))
        conn.execute("COMMIT")
        return snap
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def member_of(visitor: str, state: dict | None = None) -> dict | None:
    """저장된 member_id 가 아직 유효한지 매번 다시 확인한다. 만료·해지면 저장값도 지운다."""
    state = load_state(visitor) if state is None else state
    mid = state.get("member_id")
    m = membership.get(mid) if isinstance(mid, int) or (isinstance(mid, str) and mid.isdigit()) else None
    if mid and not m:
        save_state(visitor, {"member_id": None})
    return m


@router.get("/me")
def me(c: Caller = CallerDep) -> dict:
    cfg = settings_store.load()["ask"]
    state = load_state(c.visitor)
    m = member_of(c.visitor, state)
    if not m:
        state.pop("member_id", None)
    member = None
    if m:
        member = {"id": m["id"], "expires": m["expires"], "quota": int(cfg["member_daily"]),
                  "used": membership.used_today(m["id"])}
    return {
        # 쿠키 원값은 돌려주지 않는다 (HttpOnly 쿠키를 화면 스크립트로 읽을 수 있게 되므로) — 구분용 짧은 해시만
        "visitor": hashlib.sha256(c.visitor.encode()).hexdigest()[:12], "is_admin": c.is_admin, "member": member, "state": state,
        "privacy_active": privacy.active(),
        "ask_enabled": bool(cfg["enabled"]) and agent_chat.has_api_keys(),
        "kakao_key": os.environ.get("KAKAO_JS_KEY", ""),  # 카카오 JavaScript 키는 공개 키(도메인 등록으로 보호)
        "site_url": os.environ.get("SITE_URL", "").rstrip("/"),
    }


@router.put("/me/state")
def put_state(changes: dict = Body(...), c: Caller = CallerDep) -> dict:
    if not isinstance(changes, dict):
        return {"ok": False}
    # member_id 를 화면이 직접 쓰면 번호만 바꿔 남의 월 구독(하루 30회)을 쓸 수 있었다 (2026-10-29 점검)
    save_state(c.visitor, {k: v for k, v in changes.items() if k not in SERVER_ONLY})
    return {"ok": True}


@router.delete("/me")
def erase(request: Request, response: Response, c: Caller = CallerDep) -> dict:
    """'내 기록 지우기' — 참여 기록·통계 프로필·화면 선택값을 지우고 새 방문자로 시작한다 (새 쿠키)."""
    n = engage.erase_visitor(c.visitor)
    fresh = engage.sign_cookie(uuid.uuid4().hex)
    response.set_cookie(COOKIE, fresh, max_age=COOKIE_MAX_AGE, samesite="lax", httponly=True,
                        secure=request.url.scheme == "https" or c.proxied, path="/")
    return {"erased": n}
