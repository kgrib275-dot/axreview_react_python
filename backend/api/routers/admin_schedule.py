"""관리 > 배치 스케줄 — settings_store 의 collection·drafting·vectorize(매일 여러 시각) / weekly·newsletter·teams(주 1회) 구역 (app_pages/admin/schedule.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import settings_store

router = APIRouter(prefix="/admin/schedule", tags=["admin-schedule"], dependencies=[Depends(require_admin)])

DAILY = {"collection": "1. 수집", "drafting": "2. 노트 초안 생성", "vectorize": "5. 벡터화"}
WEEKLY = {"weekly": "3. 주간 흐름", "newsletter": "4. 뉴스레터 발송", "teams": "6. Teams 발송"}
_DESC = {
    "collection": "활성 소스 수집 → 중복 제거 → 키워드 필터 → Gemini 채점",
    "drafting": "점수 높은 대기 기사의 원문을 읽고 초안을 씁니다. 수집 30분 뒤 정도가 적당합니다.",
    "vectorize": "새 게시 노트·기사를 임베딩해 의미 검색과 'AX 질문하기'에 반영합니다. 수집·초안 뒤로 잡으세요.",
    "weekly": "지난주(월~일) 게시 노트로 '이번 주 AX 흐름'을 씁니다.",
    "newsletter": "최신 주간 흐름과 지난 발송 이후 새 노트를 활성 구독자에게 보냅니다. 주간 흐름 이후로 잡으세요.",
    "teams": "최신 주간 흐름과 지난 Teams 발송 이후 새 노트를 등록된 채널에 카드로 보냅니다.",
}


def _view() -> dict:
    cfg = settings_store.load()
    return {"daily": {k: {**cfg[k], "title": t, "desc": _DESC[k]} for k, t in DAILY.items()},
            "weekly": {k: {**cfg[k], "title": t, "desc": _DESC[k]} for k, t in WEEKLY.items()},
            "weekdays": settings_store.WEEKDAYS}


@router.get("")
def get_schedule() -> dict:
    return _view()


@router.put("")
def put_schedule(request: Request, body: dict[str, Any]) -> dict:
    """{구역 키: {enabled, times:[…] | 'HH:MM / HH:MM', per_run?, min_score?, weekday?, time?, auto_publish?}, …} — 준 구역만 저장."""
    cfg = settings_store.load()
    saved = []
    for key, val in body.items():
        if key not in DAILY and key not in WEEKLY:
            raise HTTPException(400, f"없는 스케줄 구역입니다: {key}")
        if not isinstance(val, dict):
            raise HTTPException(400, f"{key} 는 객체여야 합니다")
        c = cfg[key]
        enabled = bool(val.get("enabled", c["enabled"]))
        if key in DAILY:
            raw = val.get("times", c["times"])
            times, bad = settings_store.parse_times(" / ".join(raw) if isinstance(raw, list) else str(raw))
            if bad:
                raise HTTPException(400, f"잘못된 시각: {', '.join(bad)}")
            new = {**c, "enabled": enabled, "times": times}
            if key == "drafting":
                try:
                    new["per_run"] = min(30, max(1, int(val.get("per_run", c["per_run"]))))
                    new["min_score"] = min(5, max(1, int(val.get("min_score", c["min_score"]))))
                except (TypeError, ValueError):
                    raise HTTPException(400, "회당 최대 건수·최소 점수는 정수여야 합니다")
            detail = f"{DAILY[key]}: {'켜짐' if enabled else '꺼짐'} {times}"
        else:
            time_ = str(val.get("time", c["time"])).strip()
            if not settings_store.TIME_RE.match(time_):
                raise HTTPException(400, "시각은 HH:MM 형식이어야 합니다.")
            try:
                weekday = int(val.get("weekday", c["weekday"]))
            except (TypeError, ValueError):
                raise HTTPException(400, "요일은 0(월)~6(일) 입니다")
            if not 0 <= weekday <= 6:
                raise HTTPException(400, "요일은 0(월)~6(일) 입니다")
            new = {**c, "enabled": enabled, "weekday": weekday, "time": time_}
            if key == "weekly":
                new["auto_publish"] = bool(val.get("auto_publish", c["auto_publish"]))
            detail = f"{WEEKLY[key]}: {'켜짐' if enabled else '꺼짐'} {settings_store.WEEKDAYS[weekday]} {time_}"
        settings_store.save_section(key, new)
        log_action(request, "스케줄 저장", detail)
        saved.append(key)
    return {"ok": True, "saved": saved, **_view()}
