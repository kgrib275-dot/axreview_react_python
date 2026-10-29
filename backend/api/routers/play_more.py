"""AX 테스트 추가 2종 — AI 활용 습관 진단(/api/habit)·AX 커리어 유형(/api/career).

문항·규칙은 app/ax_tests.py. 답을 받아 서버에서 채점하고 결과를 참여 기록으로 남긴다 (직전과 같은 결과는 한 번만 — engage.record_result).
"""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from api.deps import Caller, CallerDep
from api.common import cached
from api.routers.play import STATS_TTL, _recs
from app import ax_tests as X
from pipeline import engage

router = APIRouter(tags=["play"])


# ───────────────────────── AI 활용 습관 진단 ─────────────────────────

@router.get("/habit")
def habit() -> dict:
    return {"scale": X.HABIT_SCALE,
            "dims": [{"key": k, "name": n, "desc": d} for k, n, d in X.HABIT_DIMS],
            "questions": [{"dim": d, "q": q} for d, q in X.HABIT_QUESTIONS],
            "levels": [{"min": lo, "emoji": e, "name": n, "line": line} for lo, e, n, line in X.HABIT_LEVELS]}


def _habit_card(r: dict) -> dict:
    lo, emoji, name, line = X.HABIT_LEVELS[r["level"]]
    names = {k: n for k, n, _ in X.HABIT_DIMS}
    hist = cached("play:habit_hist", lambda: engage.value_hist("habit"), STATS_TTL)
    total = sum(hist.values())
    top = round(sum(n for s, n in hist.items() if s > r["score"]) / total * 100) if total else None  # 나보다 높은 사람 비율
    return {
        **r, "emoji": emoji, "name": name, "line": line,
        "dims": [{"key": k, "name": names[k], "score": r["dims"][k]} for k, *_ in X.HABIT_DIMS],
        "strong_name": names[r["strong"]], "weak_name": names[r["weak"]],
        "top_pct": max(1, top) if top is not None else None, "participants": total,
        "recommended_notes": _recs(X.HABIT_CATEGORY[r["level"]]),
        "share": {"url": f"/s/h?l={r['level']}&score={r['score']}",
                  "title": f"내 AI 활용 습관은 {emoji} {name} 단계 ({r['score']}점) — AI 활용 습관 진단",
                  "text": f"AI 활용 습관 진단 결과 저는 {emoji} '{name}' 단계, {r['score']}점이었습니다. "
                          f"강점은 {names[r['strong']]}. 10문항·1분이면 됩니다 — 여러분은 몇 점인가요?"},
    }


@router.post("/habit/result")
def habit_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    answers = payload.get("answers")
    n = len(X.HABIT_QUESTIONS)
    if (not isinstance(answers, list) or len(answers) != n
            or any(not isinstance(a, int) or isinstance(a, bool) or not 0 <= a <= 3 for a in answers)):
        raise HTTPException(status_code=400, detail=f"{n}문항 모두 답해 주세요.")
    r = X.habit_score(answers)
    extra = r["dims"]
    engage.record_result("habit", X.HABIT_LEVELS[r["level"]][2], str(r["score"]), extra, visitor=c.visitor)
    return _habit_card(r)


# ───────────────────────── AX 커리어 유형 ─────────────────────────

def _type_brief(code: str) -> dict:
    e, name, line, *_ = X.CAREER_TYPES[code]
    return {"code": code, "emoji": e, "name": name, "line": line}


@router.get("/career")
def career() -> dict:
    return {"questions": [{"q": q, "options": [t for t, _ in opts]} for q, opts in X.CAREER_QUESTIONS],
            "types": [_type_brief(k) for k in X.CAREER_ORDER]}


def _career_card(r: dict) -> dict:
    e, name, line, roles, skills, path, partner, cat = X.CAREER_TYPES[r["code"]]
    dist = cached("play:career_dist", lambda: engage.item_counts("career"), STATS_TTL)
    total = sum(dist.values())
    return {
        **_type_brief(r["code"]), "roles": roles, "skills": skills, "path": path,
        "second": _type_brief(r["second"]), "partner": _type_brief(partner),
        "scores": [{**_type_brief(k), "pct": r["pct"][k]} for k in sorted(X.CAREER_ORDER, key=lambda k: -r["pct"][k])],
        # 몇 명뿐이면 비율이 의미 없다. 분포는 30초 캐시라 방금 낸 내 결과가 없을 수 있어 나 자신은 적어도 1명으로 센다
        "share_pct": max(1, round(max(1, dist.get(r["code"], 0)) / total * 100)) if total >= 5 else None,
        "recommended_notes": _recs(cat),
        "share": {"url": f"/s/c/{r['code']}",
                  "title": f"나는 {e} {name} — AX 커리어 유형",
                  "text": f"AX 커리어 유형 테스트를 해 봤더니 저는 {e} '{name}'이었습니다. {line}. "
                          f"10문항이면 됩니다 — 여러분은 어떤 유형인가요?"},
    }


@router.post("/career/result")
def career_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    picks = payload.get("picks")
    n = len(X.CAREER_QUESTIONS)
    if (not isinstance(picks, list) or len(picks) != n
            or any(not isinstance(p, int) or isinstance(p, bool) or not 0 <= p <= 3 for p in picks)):
        raise HTTPException(status_code=400, detail=f"{n}문항 모두 답해 주세요.")
    r = X.career_score(picks)
    extra = r["pct"]
    engage.record_result("career", r["code"], r["second"], extra, visitor=c.visitor)
    return _career_card(r)


@router.get("/career/{code}")
def career_type(code: str) -> dict:
    """공유 링크로 들어온 친구 결과 — 유형 소개만 (점수 없음)."""
    code = code.upper()
    if code not in X.CAREER_TYPES:
        raise HTTPException(status_code=404, detail="없는 유형입니다.")
    card = _career_card({"code": code, "second": X.CAREER_TYPES[code][6], "pct": {k: 0 for k in X.CAREER_ORDER}})
    card.pop("scores")
    return card
