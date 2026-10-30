"""참여 기록·선택 프로필 (/api/engage, /api/profile).

- POST /api/engage: 화면에서 일어나는 가벼운 기록만 받는다 (kind 허용 목록). 퀴즈·투표·테스트 결과처럼
  서버가 검증해야 하는 기록은 각 기능의 API 가 직접 남긴다. 하루 400건 상한은 engage.record 가 적용한다.
- POST /api/profile: 성별·연령대·국가·시·도 (선택). 참여 통계·지도에만 쓰고, 만 14세 이상 동의가 없으면 받지 않는다.
Streamlit 판 app/play_ui.py(share·track_share_visit·profile_form), streamlit_app.py(?ref), app/dialogs.py(subscribe_open).
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Body, HTTPException

from api.deps import Caller, CallerDep
from pipeline import engage, referral

router = APIRouter(tags=["engage"])

# 화면이 직접 남길 수 있는 종류 — 그 밖의 kind 는 거부한다 (통계를 오염시키지 못하게)
KINDS = {"share", "share_visit", "subscribe_open", "ref_visit", "member_request_open", "try_click",  # try_click: 홈 맛보기 클릭 (어느 것이 잘 먹히는지)
         "page_view"}  # page_view: 화면 이동 — 방문 시간대·이동 경로·재방문 패턴 분석용 (관리 > 참여 분석 > 방문 패턴)
# page_view 의 경로는 사이트 안 경로만, 쿼리(?t= 확인 토큰·?link= 연결 토큰·?k= 추천 열쇠 등)는 버린다 — 토큰이 기록에 남지 않게
_PATH_RE = re.compile(r"^/[A-Za-z0-9/_-]{0,60}$")
CONTENTS = {"today", "type_test", "terms", "diagnosis", "notes", "note_detail", "lab", "letter", "refer", "about",
            "home_hero", "home_cta", "header", "sticky_bar"}


def _str(v, n: int = 200) -> str:
    return str(v)[:n] if isinstance(v, (str, int, float)) else ""


@router.post("/engage")
def record(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    kind = _str(payload.get("kind"), 40)
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="기록할 수 없는 종류입니다.")
    item, value = _str(payload.get("item")), _str(payload.get("value"))
    extra = payload.get("extra")
    if extra is not None and not isinstance(extra, dict):
        extra = None
    if kind == "page_view":
        if c.is_admin:
            return {"ok": True}  # 관리자 자신의 이동은 방문 패턴을 흐리므로 남기지 않는다
        item = item.split("?", 1)[0].split("#", 1)[0].rstrip("/") or "/"
        if not _PATH_RE.match(item) or item.startswith("/admin"):
            return {"ok": True}
        value, extra = "", None  # 경로 외에는 받지 않는다
    elif kind == "ref_visit":  # 추천 링크(?ref=)로 온 방문 — 코드 형식이 맞을 때만
        if not referral.valid_code(item):
            raise HTTPException(status_code=400, detail="추천 코드 형식이 아닙니다.")
        if any(r["item"] == item for r in engage.mine("ref_visit", c.visitor)):
            return {"ok": True}  # 같은 방문자의 같은 코드는 한 번만
    elif kind == "share" and not value.startswith("/"):
        value = ""  # 공유 주소는 사이트 안 경로만
    if extra and len(str(extra)) > 2000:
        extra = None
    engage.record(kind, item, value, extra, visitor=c.visitor)
    return {"ok": True}


@router.get("/profile")
def profile(c: Caller = CallerDep) -> dict:
    me = engage.profile(c.visitor)
    return {"profile": {k: me[k] for k in ("gender", "age", "country", "region")} if me else None,
            "genders": engage.GENDERS, "ages": engage.AGES, "countries": list(engage.COUNTRIES),
            "regions": list(engage.KR_REGIONS)}


@router.post("/profile")
def save_profile(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    if payload.get("agree") is not True:
        raise HTTPException(status_code=400, detail="만 14세 이상이며 수집·이용에 동의해야 저장할 수 있습니다.")
    g, a = _str(payload.get("gender"), 20), _str(payload.get("age"), 20)
    country, region = _str(payload.get("country"), 40), _str(payload.get("region"), 20)
    if g not in engage.GENDERS or a not in engage.AGES or country not in engage.COUNTRIES:
        raise HTTPException(status_code=400, detail="보기에 있는 값만 고를 수 있습니다.")
    if region in ("", "-"):
        region = ""
    elif region not in engage.KR_REGIONS:
        raise HTTPException(status_code=400, detail="보기에 있는 시·도만 고를 수 있습니다.")
    engage.save_profile(c.visitor, g, a, country, region)
    return {"ok": True}
