"""뉴스레터 속 링크 (/m/{device}) — 메일은 JS 를 못 돌리니 모든 상호작용은 사이트로 보내는 링크다 (pipeline/mailer.py).

링크를 연 것만으로는 아무것도 바꾸지 않는다 — 메일 보안 검사기·미리보기가 링크를 미리 열어 보므로, 여기서는
(1) 어느 장치가 눌렸는지 센다 (engagements kind=mail_click, item=장치, value=발송일)
(2) 구독자와 이 브라우저(방문자 쿠키)를 잇는다 (subscribers.visitor — 다음 호 개인 블록용)
(3) to 로 302 — 사이트 안 경로만. 화면이 한 번 더 눌러 답을 확정한다 (/today?mq=…, /today?mp=…, /terms?mt=…).
모르는 토큰·해지한 구독자·빈 토큰(미리보기)은 아무것도 기록하지 않고 보내기만 한다. 관리자 인증 없음(공개), /api 접두어 없음.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from api.deps import Caller, CallerDep, plant_cookie
from pipeline import db, engage, mailer

root_router = APIRouter(tags=["mail"])  # api/main.py 가 접두어 없이 등록한다 — 메일 주소를 짧게 ({base}/m/quiz?…)

_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TO_RE = re.compile(r"^/(?![/\\])[^\r\n]{0,500}$")  # 사이트 안 경로만 — '//evil' '/\evil' 같은 외부 이동 차단


@root_router.get("/m/{device}", include_in_schema=False)
def mail_click(device: str, request: Request, t: str = Query(""), to: str = Query(""), s: str = Query(""),
               c: Caller = CallerDep) -> RedirectResponse:
    target = to if _TO_RE.match(to) else "/"
    if device in mailer.DEVICES and _TOKEN_RE.match(t):
        sub = db.subscriber_by_token(t)
        if sub and sub["active"]:
            # value = 발송일 (메일이 가진 s) — 관리 화면이 newsletters.sent_at 날짜별로 묶어 장치별 클릭률을 낸다
            engage.record("mail_click", device, s if _DAY_RE.match(s) else engage.today().isoformat(), visitor=c.visitor)
            db.link_subscriber_visitor(c.visitor, token=t)  # 쿠키 방문자만, 이미 이어져 있으면 그대로
    resp = RedirectResponse(target, status_code=302)
    plant_cookie(resp, request, c)  # 새 브라우저면 여기서 쿠키가 심겨야 사이트에서 같은 방문자로 이어진다
    return resp
