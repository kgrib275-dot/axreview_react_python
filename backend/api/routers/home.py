"""홈 (/api/home) — 이번 주 흐름·리더 3가지·나를 위한 추천·급상승 띠·최신 노트·수치·소스.

Streamlit 판 app_pages/home.py 를 옮겼다. 본문 강조(editorial.highlight)는 이스케이프된 HTML 이다.
"""
from __future__ import annotations

import time
from datetime import date

from fastapi import APIRouter

from api.common import note_card
from api.deps import Caller, CallerDep
from api.routers import me as me_state
from api.routers.site import counts, source_groups
from app import ax_types
from pipeline import db, editorial, engage, industry, jobs, knowledge, report_pdf
from pipeline.llm import CATEGORIES

router = APIRouter(tags=["home"])

_cache: dict = {}

def _trends() -> dict:
    """급상승 키워드 — 10분 캐시 (기사 전체를 매번 세지 않게)."""
    now = time.time()
    hit = _cache.get("trends")
    if hit and now - hit[0] < 600:
        return hit[1]
    t = knowledge.trends()
    _cache["trends"] = (now, t)
    return t

def ticker() -> dict | None:
    t = _trends()
    rows = [r for r in t["rows"] if r["rising"]] or t["rows"]
    if not rows:
        return None
    head = "급상승 키워드" if any(r["rising"] for r in rows) else f"최근 {t['window']}일 많이 잡힌 키워드"
    return {"head": head, "rows": [{"keyword": r["keyword"], "cur": r["cur"], "prev": r["prev"], "rising": bool(r["rising"]),
                                   "category": r["category"]} for r in rows[:12]]}

def for_you(visitor: str, notes: list[dict]) -> list[dict]:
    """나를 위한 추천 — 이미 이 방문자에게서 받은 정보(연속 참여·진단·유형·업종)로만 만든다."""
    cards = []
    state = me_state.load_state(visitor)
    streak = engage.streak(visitor)
    today_done = len({r["item"] for r in engage.mine("quiz", visitor, engage.today().isoformat() + ":")})
    if streak or today_done:
        left = engage.QUIZ_PER_DAY - today_done
        cards.append({"url": "/today", "kicker": f"🔥 연속 {max(streak, 1)}일째",
                      "title": "오늘 퀴즈 완료 ✓" if left <= 0 else f"오늘 퀴즈 {left}문제 남음"})
    weak = state.get("diag_weak")
    if weak in CATEGORIES:
        n = sum(x["category"] == weak for x in notes)
        cards.append({"url": f"/notes?cat={weak.replace(' ', '+')}", "kicker": "진단에서 가장 약했던 영역", "title": f"{weak} 노트 {n}편"})
    answers = state.get("axt_answers") or []
    if isinstance(answers, list) and len(answers) == len(ax_types.QUESTIONS) and all(isinstance(a, str) for a in answers):
        code, _ = ax_types.score(answers)
        if code in ax_types.TYPES:
            emoji, name, _, _, cat = ax_types.TYPES[code]
            cards.append({"url": f"/notes?cat={cat.replace(' ', '+')}", "kicker": f"{emoji} {name}에게 맞는", "title": f"{cat} 노트"})
    pref = state.get("pref_inds") or []
    for ind in (pref if isinstance(pref, list) else [])[:2]:
        if ind in industry.NAMES:
            cards.append({"url": f"/notes?ind={ind}", "kicker": "구독할 때 고른 업종",
                          "title": f"{ind} 사례 {len(industry.filter_notes(notes, [ind]))}편"})
    return cards[:4]

_SHARED_TTL = 30  # 모든 방문자에게 같은 부분은 30초 캐시 — 가장 많이 열리는 화면이라 동시 접속 때 효과가 크다


@router.get("/home")
def home(c: Caller = CallerDep) -> dict:
    now = time.time()
    hit = _cache.get("home")
    if not hit or now - hit[0] > _SHARED_TTL:
        hit = (now, _shared())
        _cache["home"] = hit
    shared = hit[1]
    out = {k: v for k, v in shared.items() if k != "_notes"}
    out["for_you"] = for_you(c.visitor, shared["_notes"])  # 방문자마다 다른 부분만 매번 계산
    return out


def _shared() -> dict:
    issues = db.issues()
    notes = db.notes()
    current = issues[-1] if issues else {"week": "", "range": "", "headline_em": "", "headline": "첫 주간 흐름을 준비 중입니다",
                                         "body": "", "editor_note": ""}
    note = (current.get("editor_note") or "").strip()
    pdf = report_pdf.report_path(current) if current.get("id") else None
    issue = {
        "id": current.get("id"), "week": current["week"], "range": current["range"], "headline_em": current["headline_em"],
        "headline": current["headline"], "body_html": editorial.highlight(current["body"]),  # **강조** → 형광펜, 관점 주제어 → 색
        "editor_note_html": editorial.highlight(note) if note else "",
        "pdf_url": f"/r/{pdf.name}" if pdf and pdf.exists() else None,
    }
    flow = [{"week": x["week"], "headline_em": x["headline_em"],
             # 흐름 목록에는 콜론 앞 핵심 문구만 보여 준다.
             "headline_short": (x["headline_em"] + " " + x["headline"].split(":")[0]).strip(), "now": i == len(issues) - 1}
            for i, x in enumerate(issues[-5:])]

    # 리더가 이번 주 알아야 할 3가지 — 이번 호 주의 노트에서 관점 점수로 고른다 (pipeline/editorial.py)
    pool = []
    if current.get("week_start"):
        monday, sunday = jobs.week_bounds(date.fromisoformat(current["week_start"]))
        pool = db.notes_published_between(monday.isoformat(), sunday.isoformat())
    three = editorial.leader_three(pool or notes[:10], current.get("picks", ""))
    leader3 = [{"id": t["id"], "title": t["title"], "category": t["category"], "point": t["point"]} for t in three]

    cat_counts = {cat: sum(n["category"] == cat for n in notes) for cat in CATEGORIES}
    return {
        "issue": issue, "issues": flow, "leader3": leader3, "stance": editorial.lens().get("stance", ""),
        "ticker": ticker(), "_notes": notes,  # _notes: 방문자별 for_you 계산용 (응답에서는 뺀다)
        "latest_notes": [note_card(n) for n in notes[:9]],
        "counts": {**counts(), "categories": cat_counts}, "sources": source_groups(),
    }

