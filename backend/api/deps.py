"""공용 의존성 — 방문자 식별(서명 쿠키), 접속 IP, 관리자 판정, 남용 제한.

Streamlit 판의 streamlit_app.py / pipeline.settings_store / pipeline.engage 의 규칙을 그대로 옮겼다.
- 방문자: 쿠키 axv = 무작위 값.서명. 없거나 위조면 새 값을 만들어 응답에 심는다 (1년, 방문마다 연장).
- 관리자: 로컬(127.0.0.1) 직접 접속 또는 등록 IP, 또는 .env ADMIN_TOKEN 과 같은 X-Admin-Token 헤더.
- 공개 주소(Tailscale Funnel)는 로컬 프록시를 거치므로 X-Forwarded-For 의 마지막 값만 믿는다 (settings_store.client_ip).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, Response

from pipeline import engage, settings_store

COOKIE = "axv"
COOKIE_MAX_AGE = 365 * 24 * 3600


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
    if token and request.headers.get("x-admin-token", "") == token:
        return True
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
    if new_cookie:
        response.set_cookie(COOKIE, new_cookie, max_age=COOKIE_MAX_AGE, samesite="lax", httponly=False,
                            secure=request.url.scheme == "https" or proxied, path="/")
    return Caller(visitor=engage.visitor_id(raw, ip), raw=raw, ip=ip, proxied=proxied, is_admin=is_admin(request),
                  new_cookie=new_cookie)


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="관리자만 쓸 수 있습니다")


AdminDep = Depends(require_admin)
CallerDep = Depends(caller)


def throttle(kind: str, c: Caller, per_visitor: int = 3, per_ip: int = 10, minutes: int = 60) -> None:
    """남용 제한 — 방문자 기준 + IP 기준 (engage.attempt). 넘으면 429."""
    if not engage.attempt(kind, c.visitor, c.ip, per_visitor, per_ip, minutes):
        raise HTTPException(status_code=429, detail="잠시 후 다시 시도해 주세요.")
