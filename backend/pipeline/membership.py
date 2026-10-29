"""월 구독 (AX 질문하기 추가 이용권).

결제는 사이트 밖에서 한다: 방문자가 '월 구독 신청'을 남기면(문의함에 [월 구독 신청]으로 들어감) 담당자가
결제를 확인한 뒤 관리 > 구독·발송 > 월 구독에서 코드를 발급해 메일로 보낸다. 방문자는 질문하기에서 코드를 넣는다.

- 코드는 해시만 저장한다 (DB가 새어도 코드를 쓸 수 없게). 발급 화면에서 한 번만 보여 준다.
- 질문 수는 구독 단위로 센다 (engagements kind='ask', item='m:<id>') — 기기·브라우저가 달라도 한도를 나눠 쓴다.
- 이 표는 이메일이 있어 Databricks로 보내지 않는다 (pipeline/warehouse.py TABLES에 없음).
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime, timedelta

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, code_hash TEXT NOT NULL UNIQUE,
  expires TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, memo TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
"""
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 헷갈리는 0/O, 1/I 제외


_ready: set[str] = set()


def _conn():
    conn = db.connect()
    if str(db.DB_PATH) not in _ready:  # 스키마 확인은 DB 파일당 한 번
        conn.executescript(SCHEMA)
        _ready.add(str(db.DB_PATH))
    return conn


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().replace(" ", "").encode()).hexdigest()


def _today() -> date:
    return datetime.now(db.KST).date()


def issue(email: str, months: int = 1, memo: str = "") -> str:
    """새 구독 코드를 만들고 코드 원문을 돌려준다 (저장은 해시만)."""
    code = "AXR-" + "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(3))
    expires = (_today() + timedelta(days=30 * months)).isoformat()
    conn = _conn()
    try:
        conn.execute("INSERT INTO members (email, code_hash, expires, memo, created_at) VALUES (?,?,?,?,?)",
                     (email.strip(), _hash(code), expires, memo.strip(), datetime.now(db.KST).isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()
    return code


def redeem(code: str) -> dict | None:
    """코드가 맞고 기간이 남았으면 구독 정보를 돌려준다."""
    if not code or len(code) > 40:
        return None
    conn = _conn()
    try:
        r = conn.execute("SELECT id, expires FROM members WHERE code_hash=? AND active=1", (_hash(code),)).fetchone()
    finally:
        conn.close()
    return dict(r) if r and r["expires"] >= _today().isoformat() else None


def get(member_id: int | None) -> dict | None:
    """세션에 저장된 구독이 아직 유효한지 매번 다시 확인한다 (만료·해지 즉시 반영)."""
    if not member_id:
        return None
    conn = _conn()
    try:
        r = conn.execute("SELECT id, expires FROM members WHERE id=? AND active=1", (int(member_id),)).fetchone()
    finally:
        conn.close()
    return dict(r) if r and r["expires"] >= _today().isoformat() else None


def ask_item(member_id: int) -> str:
    return f"m:{int(member_id)}"


def used_today(member_id: int) -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM engagements WHERE kind='ask' AND item=? AND created_at >= ?",
                            (ask_item(member_id), _today().isoformat())).fetchone()[0]
    finally:
        conn.close()


def all_members() -> list[dict]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id, email, expires, active, memo, created_at FROM members ORDER BY id DESC")]
    finally:
        conn.close()


def extend(member_id: int, months: int = 1) -> None:
    """남은 기간 뒤로(이미 끝났으면 오늘부터) 늘린다."""
    conn = _conn()
    try:
        r = conn.execute("SELECT expires FROM members WHERE id=?", (member_id,)).fetchone()
        if r:
            start = max(date.fromisoformat(r["expires"]), _today())
            conn.execute("UPDATE members SET expires=?, active=1 WHERE id=?",
                         ((start + timedelta(days=30 * months)).isoformat(), member_id))
            conn.commit()
    finally:
        conn.close()


def set_active(member_id: int, active: bool) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE members SET active=? WHERE id=?", (int(active), member_id))
        conn.commit()
    finally:
        conn.close()


def active_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM members WHERE active=1 AND expires >= ?",
                            (_today().isoformat(),)).fetchone()[0]
    finally:
        conn.close()
