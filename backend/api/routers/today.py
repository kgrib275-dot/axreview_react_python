"""오늘의 AX (/api/today) — 매일 바뀌는 3문항 퀴즈 + 내일 키워드 예측 투표 + 연속 참여 + 오늘의 용어 + 참여 지도.

Streamlit 판 app_pages/today.py 를 옮겼다. 정답·해설은 답한 문항에만 내려 준다.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException

from api.deps import Caller, CallerDep
from app import geo_map, glossary
from pipeline import db, engage, settings_store

router = APIRouter(tags=["today"])

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_cache: dict = {}


def _cached(key: str, fn, ttl: int):
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def quiz_of(day_iso: str) -> list[dict]:
    """그날 문제는 하루 내내 같으므로 한 번만 만든다 (수집 데이터 조회가 매번 돌지 않게)."""
    return _cached(f"quiz:{day_iso}", lambda: engage.daily_quiz(date.fromisoformat(day_iso)), 3600)


def map_html() -> str:
    """공개 지도 — 묶은 값만 (재식별 방지). 2분 캐시."""
    sample = settings_store.load()["engage"]["sample_on_map"]
    return _cached(f"map:{sample}", lambda: geo_map.html(engage.map_public(include_sample=sample)), 120)


def _mine(q: dict, picked: str, stats: dict, i: int) -> dict:
    s = stats.get(i, {"n": 0, "correct": 0, "choices": {}})
    return {"choice": picked, "correct": picked == q["answer"], "answer": q["answer"], "why": q["why"],
            "stats": {"n": s["n"], "rate": round(s["correct"] / s["n"] * 100) if s["n"] else 0,
                      "choices": {o: int(s["choices"].get(o, 0)) for o in q["options"]}}}


def _poll_block(day_iso: str, visitor: str) -> dict:
    poll = engage.daily_poll(date.fromisoformat(day_iso))
    out = {"day": poll["day"], "question": poll["question"], "options": poll["options"], "target_day": poll["target_day"]}
    mine = engage.mine("poll", visitor, day_iso)
    mine = [r for r in mine if r["item"] == day_iso]
    if mine:
        votes = engage.poll_votes(day_iso)
        out["mine"] = mine[0]["value"]
        out["counts"] = {o: int(votes.get(o, 0)) for o in poll["options"]}
        out["total"] = int(sum(votes.values()))
    return out


@router.get("/today")
def today(d: str | None = None, c: Caller = CallerDep) -> dict:
    day = engage.today()
    d_iso = day.isoformat()
    if d and not _DAY_RE.match(d):
        raise HTTPException(status_code=400, detail="날짜 형식이 아닙니다.")
    me = c.visitor
    now = datetime.now(db.KST)
    left = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=db.KST) - now
    tk, (term, define, hint) = glossary.term_of_day(d_iso)

    quiz = quiz_of(d_iso)
    done = {r["item"]: r for r in engage.mine("quiz", me, d_iso + ":")}
    stats = engage.quiz_stats(d_iso) if done else {}
    items, score = [], 0
    for i, q in enumerate(quiz):
        key = f"{d_iso}:{i}"
        item = {"i": i, "q": q["q"], "sub": q["sub"], "options": q["options"], "url": q.get("url")}
        if key in done:
            item["mine"] = _mine(q, done[key]["value"], stats, i)
            score += item["mine"]["correct"]
        items.append(item)
    answered = sum(f"{d_iso}:{i}" in done for i in range(len(quiz)))
    streak = engage.streak(me)

    yesterday = None
    res = engage.poll_result((day - timedelta(days=1)).isoformat())
    if res and res["winner"]:
        my_vote = next((r["value"] for r in engage.mine("poll", me, res["day"]) if r["item"] == res["day"]), None)
        yesterday = {"day": res["day"], "question": res["question"], "winner": res["winner"],
                     "actual": {k: int(v) for k, v in res["actual"].items()}, "crowd": res["crowd"], "mine": my_vote,
                     "band": bool(res["band"]), "hit": my_vote == res["winner"] if my_vote else None}

    n = len(quiz)
    return {
        "day": d_iso, "shared_day": d if d and d != d_iso else None,
        "term": {"track": tk, "track_label": glossary.TRACKS[tk][1], "term": term, "define": define, "hint": hint},
        "quiz": items, "score": score, "done": bool(quiz) and answered == n, "answered": answered, "streak": streak,
        "left": {"hours": left.seconds // 3600, "minutes": left.seconds % 3600 // 60},
        "poll": _poll_block(d_iso, me), "yesterday": yesterday,
        "share": {"url": f"/s/q?d={d_iso}&score={score}&n={n}", "title": f"오늘의 AX 퀴즈 {score}/{n} — 너도 풀어 봐",
                  "text": f"오늘의 AX 퀴즈 {score}/{n} 정답. 실제 수집 데이터로 매일 새로 나오는 3문제입니다."} if quiz and answered == n else None,
        "map_html": map_html(),
    }


@router.post("/today/quiz")
def answer_quiz(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    d_iso = engage.today().isoformat()
    if payload.get("day") != d_iso:
        raise HTTPException(status_code=400, detail="오늘 문제만 답할 수 있습니다.")
    i, choice = payload.get("i"), payload.get("choice")
    quiz = quiz_of(d_iso)
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(quiz):
        raise HTTPException(status_code=400, detail="없는 문항입니다.")
    q = quiz[i]
    if not isinstance(choice, str) or choice not in q["options"]:
        raise HTTPException(status_code=400, detail="보기 중에서 골라 주세요.")
    key = f"{d_iso}:{i}"
    if any(r["item"] == key for r in engage.mine("quiz", c.visitor, key)):
        raise HTTPException(status_code=400, detail="이미 답한 문항입니다.")
    engage.record("quiz", key, choice, {"correct": int(choice == q["answer"])}, visitor=c.visitor)
    return _mine(q, choice, engage.quiz_stats(d_iso), i)


@router.post("/today/poll")
def vote(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    d_iso = engage.today().isoformat()
    if payload.get("day") != d_iso:
        raise HTTPException(status_code=400, detail="오늘 투표만 할 수 있습니다.")
    poll = engage.daily_poll(engage.today())
    choice = payload.get("choice")
    if not isinstance(choice, str) or choice not in poll["options"]:
        raise HTTPException(status_code=400, detail="보기 중에서 골라 주세요.")
    if any(r["item"] == d_iso for r in engage.mine("poll", c.visitor, d_iso)):
        raise HTTPException(status_code=400, detail="이미 투표했습니다.")
    engage.record("poll", d_iso, choice, visitor=c.visitor)
    votes = engage.poll_votes(d_iso)
    return {"counts": {o: int(votes.get(o, 0)) for o in poll["options"]}, "mine": choice, "total": int(sum(votes.values()))}
