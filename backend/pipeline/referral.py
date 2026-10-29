"""구독자 추천 링크 (?ref=코드) — 친구 3명이 구독하면 지난 호 주간 PDF 전체 아카이브가 열린다.

- ref_code: 남에게 보여 줘도 되는 짧은 코드 (추천 링크에 들어감)
- ref_key: 구독자 본인만 아는 값 (확인 시 생성, 해지 토큰과 별도) — '내 추천 현황'(/refer?k=) 페이지 열쇠.
  지난 호 PDF는 이 화면에서 7일짜리 서명 링크로만 준다 (app/web.py) — 링크가 퍼져도 열쇠는 드러나지 않는다.
- 같은 사람이 자기 링크로 구독하거나, 이미 구독 중인 주소는 추천으로 세지 않는다 (db.subscribe가 새 주소일 때만 기록).
"""
from __future__ import annotations

import re
import secrets

from . import db

REWARD_AT = 3
_CODE_RE = re.compile(r"^[a-z0-9]{6,12}$")
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def valid_code(code: str | None) -> bool:
    return bool(code) and bool(_CODE_RE.match(code))


def ensure_code(email: str) -> str:
    conn = db.connect()
    try:
        r = conn.execute("SELECT ref_code FROM subscribers WHERE email=?", (email,)).fetchone()
        if r and r["ref_code"]:
            return r["ref_code"]
        while True:
            code = secrets.token_hex(4)
            if not conn.execute("SELECT 1 FROM subscribers WHERE ref_code=?", (code,)).fetchone():
                break
        conn.execute("UPDATE subscribers SET ref_code=? WHERE email=?", (code, email))
        conn.commit()
        return code
    finally:
        conn.close()


def by_token(token: str) -> dict | None:
    """구독자 본인 화면용 — (이메일 일부, 추천 코드, 추천 수, 보상 여부)."""
    if not token or not _TOKEN_RE.match(token):
        return None
    conn = db.connect()
    try:
        r = conn.execute("SELECT email, ref_code, active FROM subscribers WHERE ref_key=? AND confirmed_at IS NOT NULL",
                         (token,)).fetchone()
        if not r or not r["active"]:
            return None
        code = r["ref_code"] or ensure_code(r["email"])
        n = conn.execute("SELECT COUNT(*) FROM subscribers WHERE referred_by=? AND active=1 AND confirmed_at IS NOT NULL",
                         (code,)).fetchone()[0]
    finally:
        conn.close()
    local, _, domain = r["email"].partition("@")
    return {"email": f"{local[:2]}***@{domain}", "code": code, "count": n, "unlocked": n >= REWARD_AT, "token": token}


def pdf_link(name: str, days: int = 7) -> str:
    """지난 호 PDF 서명 링크 (만료 포함) — 보상을 받은 구독자 화면에서만 만든다."""
    import time
    exp = int(time.time()) + days * 86400
    return f"/r/{name}?exp={exp}&sig={_pdf_sig(name, exp)}"


def _pdf_sig(name: str, exp: int) -> str:
    import hashlib
    import hmac
    from . import engage
    return hmac.new(engage._secret(), f"pdf:{name}:{exp}".encode(), hashlib.sha256).hexdigest()[:24]


def pdf_link_ok(name: str, exp: str, sig: str) -> bool:
    import hmac
    import time
    return exp.isdigit() and int(exp) >= time.time() and hmac.compare_digest(sig or "", _pdf_sig(name, int(exp)))


def counts() -> dict:
    """관리 화면용 — 추천으로 들어온 구독자 수, 보상 받은 구독자 수."""
    conn = db.connect()
    try:
        referred = conn.execute("SELECT COUNT(*) FROM subscribers WHERE referred_by != '' AND active=1 AND confirmed_at IS NOT NULL").fetchone()[0]
        rewarded = conn.execute("SELECT COUNT(*) FROM (SELECT referred_by FROM subscribers WHERE referred_by != '' AND active=1 "
                                "AND confirmed_at IS NOT NULL "
                                "GROUP BY referred_by HAVING COUNT(*) >= ?)", (REWARD_AT,)).fetchone()[0]
    finally:
        conn.close()
    return {"referred": referred, "rewarded": rewarded}
