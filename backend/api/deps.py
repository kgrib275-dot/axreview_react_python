"""공용 의존성 — 방문자 식별(서명 쿠키), 접속 IP, 관리자 판정, 남용 제한.

Streamlit 판의 streamlit_app.py / pipeline.settings_store / pipeline.engage 의 규칙을 그대로 옮겼다.
- 방문자: 쿠키 axv = 무작위 값.서명. 없거나 위조면 새 값을 만들어 응답에 심는다 (1년, 방문마다 연장).
- 관리자: 로컬(127.0.0.1) 직접 접속 또는 등록 IP, 또는 .env ADMIN_TOKEN 과 같은 X-Admin-Token 헤더.
- 공개 주소(Tailscale Funnel)는 로컬 프록시를 거치므로 X-Forwarded-For 의 마지막 값만 믿는다 (settings_store.client_ip).
"""
from __future__ import annotations

import hmac
import os
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response

from pipeline import engage, settings_store

COOKIE = "axv"
COOKIE_MAX_AGE = 365 * 24 * 3600

# X-Admin-Token 을 틀리게 보낸 IP 별 실패 시각 — 10분에 10번 넘으면 그 IP 는 창이 지날 때까지 429.
# 토큰이 길어 추측은 어렵지만, 공개 주소로 열려 있으니 무제한 시도는 막는다. 프로세스 메모리면 충분하다(재시작하면 비워짐).
_TOKEN_FAIL_LIMIT, _TOKEN_FAIL_WINDOW = 10, 600
_token_fails: dict[str, list[float]] = {}
_token_lock = threading.Lock()


def _recent_token_fails(ip: str) -> list[float]:
    now = time.time()
    with _token_lock:
        kept = [t for t in _token_fails.get(ip, ()) if now - t < _TOKEN_FAIL_WINDOW]
        if kept:
            _token_fails[ip] = kept
        else:
            _token_fails.pop(ip, None)
        if len(_token_fails) > 10000:  # 흩뿌려진 IP 로 메모리가 자라지 않게
            _token_fails.clear()
        return kept


def _token_blocked(ip: str) -> bool:
    return len(_recent_token_fails(ip)) >= _TOKEN_FAIL_LIMIT


def _count_token_fail(request: Request, ip: str) -> None:
    if getattr(request.state, "token_fail_counted", False):
        return  # caller()와 require_admin 이 같은 요청에서 둘 다 is_admin 을 불러도 한 번만
    request.state.token_fail_counted = True
    with _token_lock:
        _token_fails.setdefault(ip, []).append(time.time())


@dataclass
class Caller:
    visitor: str          # 'c:<무작위>' 또는 'i:<IP 해시>'
    raw: str              # 쿠키의 무작위 값
    ip: str | None
    proxied: bool
    is_admin: bool
    new_cookie: str | None  # 응답에 심을 값 (None이면 그대로)


def _client_ip(request: Request) -> tuple[str | None, bool]:
    raw = request.client.host if request.client else None
    headers = {k: v for k, v in request.headers.items()}
    return settings_store.client_ip(raw, headers)


def is_admin(request: Request) -> bool:
    token = os.environ.get("ADMIN_TOKEN", "").strip()
    given = request.headers.get("x-admin-token", "")
    if token and given:
        ip = _client_ip(request)[0] or "?"
        if _token_blocked(ip):
            return False
        if hmac.compare_digest(given.encode(), token.encode()):  # 시간차로 토큰을 추측하지 못하게
            return True
        _count_token_fail(request, ip)  # 헤더를 보냈는데 틀린 경우만 센다 — 로컬·등록 IP 의 헤더 없는 요청은 실패가 아니다
    raw = request.client.host if request.client else None
    return settings_store.is_admin_request(raw, {k: v for k, v in request.headers.items()})


def caller(request: Request, response: Response) -> Caller:
    """모든 공개 API가 쓰는 의존성. 쿠키가 없거나 위조면 새로 만들어 심는다."""
    ip, proxied = _client_ip(request)
    raw, resign = engage.check_cookie(request.cookies.get(COOKIE))
    new_cookie = None
    if not raw:
        raw, resign = uuid.uuid4().hex, True
    if resign or request.headers.get("x-refresh-cookie"):
        new_cookie = engage.sign_cookie(raw)
    if new_cookie:  # HttpOnly: 화면 JS 는 읽지 않는다 — 스크립트로 훔쳐 월 구독을 가로채지 못하게
        response.set_cookie(COOKIE, new_cookie, max_age=COOKIE_MAX_AGE, samesite="lax", httponly=True,
                            secure=request.url.scheme == "https" or proxied, path="/")
    return Caller(visitor=engage.visitor_id(raw, ip), raw=raw, ip=ip, proxied=proxied, is_admin=is_admin(request),
                  new_cookie=new_cookie)


def require_admin(request: Request) -> None:
    if request.headers.get("x-admin-token") and _token_blocked(_client_ip(request)[0] or "?"):
        raise HTTPException(status_code=429, detail="관리 토큰 오류가 잦아 잠시 차단되었습니다. 10분 뒤 다시 시도해 주세요.")
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="관리자만 쓸 수 있습니다")


AdminDep = Depends(require_admin)
CallerDep = Depends(caller)


def throttle(kind: str, c: Caller, per_visitor: int = 3, per_ip: int = 10, minutes: int = 60) -> None:
    """남용 제한 — 방문자 기준 + IP 기준 (engage.attempt). 넘으면 429."""
    if not engage.attempt(kind, c.visitor, c.ip, per_visitor, per_ip, minutes):
        raise HTTPException(status_code=429, detail="잠시 후 다시 시도해 주세요.")
