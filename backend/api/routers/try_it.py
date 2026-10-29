"""홈 '1분 안에 해 보기' 맛보기 (/api/home/try) — 각 페이지 인터랙션의 입구.

- 오늘의 퀴즈 1번 문제 (홈에서 바로 풀면 오늘의 AX 와 같은 기록 — today.answer_quiz)
- AX 테스트 5종: 참여자 수(실제 참여만, 5명 이상일 때) + 내가 이미 해 본 결과
- 급상승 키워드 추세선 (홈 띠와 같은 knowledge.trends)
- 참여 현황: 오늘 참여한 사람 수 + 많이 참여한 나라 3곳 (공개 지도와 같은 재식별 방지 기준 K_MIN)
- 질문하기 예시 질문
모든 방문자에게 같은 부분은 60초 캐시, 방문자별 부분(내 결과·내 퀴즈 답)만 매번 계산한다.
"""
from __future__ import annotations

from fastapi import APIRouter

from api.common import cached
from api.deps import Caller, CallerDep
from api.routers import today as today_api
from api.routers.home import _trends
from app import ax_tests as X
from app import ax_types as T
from pipeline import engage, settings_store

router = APIRouter(tags=["home"])

ASK_EXAMPLES = ["우리 회사 AI 에이전트 도입, 어디서부터 시작해야 하나요?",
                "생성형 AI 보안 가이드라인에는 무엇을 넣어야 하나요?",
                "제조 현장에서 AI로 효과를 본 사례를 알려 주세요."]

# (경로, 기록 종류, 이모지, 이름, 한 줄, 걸리는 시간)
TESTS = [("/type", "type_test", "🧩", "AX 리더 유형", "16가지 리더 유형 중 나는?", "1분"),
         ("/career", "career", "🧭", "AX 커리어 유형", "AI 시대, 나에게 맞는 일은?", "1분"),
         ("/habit", "habit", "⚙️", "AI 활용 습관 진단", "나는 AI를 얼마나 잘 쓸까?", "1분"),
         ("/terms", "term_quiz", "📚", "AI·AX 용어 퀴즈", "업무 용어 10문제, 몇 점?", "2분"),
         ("/diagnosis", "diagnosis", "☑", "AX 준비도 자가진단", "우리 조직은 몇 단계?", "3분")]
MIN_SHOW = 5  # 참여자 수는 이 이상일 때만 보여 준다 (몇 명뿐이면 숫자가 오히려 썰렁하다)


def _shared() -> dict:
    conn = engage._conn()
    try:
        counts = {kind: conn.execute("SELECT COUNT(DISTINCT visitor) FROM engagements WHERE kind=? AND visitor NOT LIKE ?",
                                     (kind, engage.SAMPLE + "%")).fetchone()[0] for _, kind, *_ in TESTS}
        sample = settings_store.load()["engage"]["sample_on_map"]
        cond = "" if sample else " AND e.visitor NOT LIKE ?"
        args: tuple = () if sample else (engage.SAMPLE + "%",)
        today_n = conn.execute(f"SELECT COUNT(DISTINCT e.visitor) FROM engagements e WHERE e.created_at >= ?{cond}",
                               (engage.today().isoformat(), *args)).fetchone()[0]
        month_n = conn.execute(f"SELECT COUNT(DISTINCT e.visitor) FROM engagements e WHERE e.created_at >= date('now', '-30 day'){cond}",
                               args).fetchone()[0]
        rows = conn.execute(
            "SELECT p.country, COUNT(DISTINCT e.visitor) n FROM engagements e JOIN profiles p ON p.visitor = e.visitor "
            f"WHERE e.created_at >= date('now', '-30 day') AND p.country != ''{cond} GROUP BY p.country ORDER BY n DESC",
            args).fetchall()
    finally:
        conn.close()
    top = [{"country": r[0], "n": r[1]} for r in rows if r[1] >= engage.K_MIN][:3]
    t = _trends()
    spark = [{"keyword": r["keyword"], "series": r["series"][-7:], "cur": r["cur"], "rising": r["rising"]}
             for r in (t.get("rows") or [])[:3]]
    return {"counts": counts, "today_people": today_n, "month_people": month_n, "top_countries": top, "sample": bool(sample), "spark": spark}


def _mine(c: Caller) -> dict[str, str]:
    """이미 해 본 테스트의 내 결과 한 줄."""
    out: dict[str, str] = {}
    last = lambda kind: (engage.mine(kind, c.visitor) or [None])[-1]  # noqa: E731
    if (r := last("type_test")) and r["item"] in T.TYPES:
        e, name, *_ = T.TYPES[r["item"]]
        out["type_test"] = f"{e} {name}"
    if (r := last("career")) and r["item"] in X.CAREER_TYPES:
        e, name, *_ = X.CAREER_TYPES[r["item"]]
        out["career"] = f"{e} {name}"
    if r := last("habit"):
        out["habit"] = f"{r['item']} · {r['value']}점"
    if r := last("term_quiz"):
        out["term_quiz"] = f"{'AI 기술' if r['item'] == 'ai' else 'AX 비즈니스'} 편 {r['value']}점"
    if (r := last("diagnosis")) and str(r["value"]).isdigit():
        from api.routers.play import level
        out["diagnosis"] = f"{level(int(r['value']))[0]} 단계 · {r['value']}점"
    return out


@router.get("/home/try")
def try_it(c: Caller = CallerDep) -> dict:
    shared = cached("home:try", _shared, 60)
    d_iso = engage.today().isoformat()
    quiz = today_api.quiz_of(d_iso)
    q0 = None
    if quiz:
        q = quiz[0]
        q0 = {"day": d_iso, "q": q["q"], "sub": q.get("sub", ""), "options": q["options"], "left": len(quiz) - 1}
        done = [r for r in engage.mine("quiz", c.visitor, f"{d_iso}:0") if r["item"] == f"{d_iso}:0"]
        if done:  # 이미 풀었으면 결과까지 (오늘의 AX 에서 풀었어도 같다)
            q0["mine"] = today_api._mine(q, done[0]["value"], today_api.quiz_stats(d_iso), 0)
    mine = _mine(c)
    tests = [{"url": url, "kind": kind, "emoji": e, "name": name, "line": line, "time": tm,
              "count": shared["counts"][kind] if shared["counts"][kind] >= MIN_SHOW else None, "mine": mine.get(kind)}
             for url, kind, e, name, line, tm in TESTS]
    return {"quiz": q0, "tests": tests, "spark": shared["spark"], "ask": ASK_EXAMPLES,
            "people": {"today": shared["today_people"], "month": shared["month_people"], "top": shared["top_countries"], "sample": shared["sample"]}}
