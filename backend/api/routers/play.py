"""AX 테스트 — 리더 유형 테스트·용어 퀴즈·준비도 자가진단 (/api/type, /api/terms, /api/diagnosis).

Streamlit 판 app_pages/ax_type.py·terms.py·diagnosis.py 와 app/ax_types.py·glossary.py 를 옮겼다.
- 유형·진단은 규칙 기반이라 답을 받아 서버에서 채점하고 결과를 기록한다 (같은 답은 한 번만).
- 용어 퀴즈는 정답을 숨긴 문제를 내고(seed 로 같은 문제를 다시 만든다), 답은 서버에서 확인한다.
- 자가진단 답은 서버에 저장하지 않고 결과 링크(?a=코드)에만 담긴다. 집계용 기록은 영역 점수뿐이다.
"""
from __future__ import annotations

import re
import secrets
from statistics import mean

from fastapi import APIRouter, Body, HTTPException, Query

from api.common import note_card
from api.deps import Caller, CallerDep
from api.routers import me as me_state
from app import ax_types as T
from app import glossary as G
from app import og_cards
from pipeline import db, engage

router = APIRouter(tags=["play"])

TERM_N = 10
_SEED_RE = re.compile(r"^[0-9a-f]{8,32}$")


def _recorded(kind: str, visitor: str, item: str, extra: dict | None) -> bool:
    """같은 방문자가 같은 결과를 이미 남겼는지 (새로고침·재요청으로 통계를 부풀리지 않게)."""
    import json
    rows = engage.mine(kind, visitor)
    if not rows:
        return False
    last = rows[-1]
    return last["item"] == item and (last["extra"] or "") == (json.dumps(extra, ensure_ascii=False) if extra is not None else "")


def _recs(cat: str, k: int = 3) -> list[dict]:
    return [note_card(n) for n in db.notes() if n["category"] == cat][:k]


# ───────────────────────── AX 리더 유형 테스트 ─────────────────────────

def _distribution() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in engage.rows("type_test"):
        out[r["item"]] = out.get(r["item"], 0) + 1
    return out


def _type_card(code: str, axes: list | None) -> dict:
    emoji, name, line, partner, cat = T.TYPES[code]
    dist = _distribution()
    total = sum(dist.values())
    pe, pn, *_ = T.TYPES[partner]
    axes_out = []
    for i, (l, r, label, l_text, r_text) in enumerate(T.AXES):
        if axes:
            lc, rc = axes[i][2], axes[i][3]
        else:
            lc, rc = (3, 0) if code[i] == l else (0, 3)
        axes_out.append([l, r, lc, rc])
    watch = T.WATCH[code[0]] if code[0] == "S" else T.WATCH[code[1]]
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:8]
    return {
        "code": code, "emoji": emoji, "name": name, "line": line, "category": cat, "axes": axes_out,
        "share_pct": round(dist.get(code, 0) / total * 100) if total else None,
        "strengths": [T.STRENGTH[ch] for ch in code], "watch": watch,
        "buddy": {"code": partner, "emoji": pe, "name": pn},
        "recommended_notes": _recs(cat),
        "distribution": {"total": total, "top": [{"code": k, "emoji": T.TYPES[k][0], "name": T.TYPES[k][1], "n": n,
                                                  "pct": round(n / total * 100)} for k, n in top if k in T.TYPES]},
        "share": {"url": f"/s/t/{code}", "title": f"나는 {name} ({code}) — AX 리더 유형 테스트",
                  "text": f"AX 리더 유형 테스트를 해 봤더니 저는 {emoji} '{name}'({code})이었습니다. {line}. "
                          f"12문항이면 됩니다 — 여러분은 어떤 유형인가요?", "image": f"/app/static/og/type-{code}.png"},
    }


@router.get("/type")
def type_meta() -> dict:
    return {
        "axes": [{"l": l, "r": r, "label": label, "l_text": lt, "r_text": rt} for l, r, label, lt, rt in T.AXES],
        "questions": [{"q": q, "a": list(a), "b": list(b)} for q, a, b in T.QUESTIONS],
        "types": {k: {"emoji": v[0], "name": v[1], "line": v[2], "buddy": v[3], "category": v[4]} for k, v in T.TYPES.items()},
        "strength": T.STRENGTH, "watch": T.WATCH,
    }


@router.get("/type/{code}")
def type_shared(code: str) -> dict:
    """공유 링크(?t=코드)로 들어온 친구 결과 — 기록하지 않는다."""
    code = code.upper()
    if code not in T.TYPES:
        raise HTTPException(status_code=404, detail="없는 유형입니다.")
    return _type_card(code, None)


@router.post("/type/result")
def type_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    answers = payload.get("answers")
    if not isinstance(answers, list) or len(answers) != len(T.QUESTIONS):
        raise HTTPException(status_code=400, detail=f"{len(T.QUESTIONS)}문항 모두 답해 주세요.")
    for a, (_, (_, ca), (_, cb)) in zip(answers, T.QUESTIONS):
        if a not in (ca, cb):
            raise HTTPException(status_code=400, detail="보기에 없는 답입니다.")
    code, axes = T.score(answers)
    extra = {"axes": [[l, r, lc, rc] for l, r, lc, rc in axes]}
    if not _recorded("type_test", c.visitor, code, extra):
        engage.record("type_test", code, extra=extra, visitor=c.visitor)
    me_state.save_state(c.visitor, {"axt_answers": answers, "axt_step": len(answers), "axt_recorded": code + "".join(answers)})
    return _type_card(code, axes)


# ───────────────────────── AI·AX 용어 퀴즈 ─────────────────────────

def _questions(track: str, seed: str) -> list[dict]:
    return G.questions(track, TERM_N, seed=f"terms:{track}:{seed}")


def _track(v) -> str:
    if v not in G.TRACKS:
        raise HTTPException(status_code=400, detail="트랙은 ai 또는 ax 입니다.")
    return v


def _seed(v) -> str:
    if not isinstance(v, str) or not _SEED_RE.match(v):
        raise HTTPException(status_code=400, detail="문제 세트(seed)가 필요합니다.")
    return v


def _track_stats() -> dict[str, dict]:
    rows = engage.rows("term_quiz")
    out = {}
    for key in G.TRACKS:
        scores = [int(r["value"]) for r in rows if r["item"] == key and r["value"].isdigit()]
        out[key] = {"n": len(scores), "avg": round(mean(scores)) if scores else None, "terms": len(G.TERMS[key])}
    return out


@router.get("/terms")
def terms(track: str | None = None, seed: str | None = None, q: str = Query("", max_length=100)) -> dict:
    """트랙 정보·용어 사전은 늘, track 을 주면 그 트랙의 문제(정답 숨김)도 함께. seed 를 주면 같은 문제를 다시 만든다."""
    out = {
        "tracks": {k: {"emoji": e, "title": t, "desc": d} for k, (e, t, d) in G.TRACKS.items()},
        "levels": [{"min": m, "emoji": e, "name": n} for m, e, n in G.LEVELS],
        "dictionary": {k: [list(t) for t in v if not q or q.lower() in f"{t[0]} {t[1]} {t[2]}".lower()] for k, v in G.TERMS.items()},
        "stats": _track_stats(), "n": TERM_N,
    }
    if track:
        track = _track(track)
        seed = _seed(seed) if seed else secrets.token_hex(8)
        qs = _questions(track, seed)
        out["track"] = track
        out["seed"] = seed
        out["questions"] = [{"i": i, "format": i % G.FORMATS, "q": x["q"], "prompt": x["prompt"], "options": x["options"]}
                            for i, x in enumerate(qs)]
    return out


@router.post("/terms/answer")
def terms_answer(payload: dict = Body(...)) -> dict:
    track, seed, i, pick = _track(payload.get("track")), _seed(payload.get("seed")), payload.get("i"), payload.get("pick")
    qs = _questions(track, seed)
    if not isinstance(i, int) or isinstance(i, bool) or not 0 <= i < len(qs):
        raise HTTPException(status_code=400, detail="없는 문항입니다.")
    item = qs[i]
    if pick not in item["options"]:
        raise HTTPException(status_code=400, detail="보기 중에서 골라 주세요.")
    return {"correct": pick == item["answer"], "answer": item["answer"],
            "explain": {"term": item["term"], "define": item["define"], "hint": item["hint"]}}


@router.post("/terms/result")
def terms_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    track, seed, picks = _track(payload.get("track")), _seed(payload.get("seed")), payload.get("picks")
    qs = _questions(track, seed)
    if not isinstance(picks, list) or len(picks) != len(qs) or any(p not in q["options"] for p, q in zip(picks, qs)):
        raise HTTPException(status_code=400, detail=f"{len(qs)}문항 모두 답해 주세요.")
    right = sum(p == q["answer"] for p, q in zip(picks, qs))
    pct = round(right / len(qs) * 100)
    wrong = [q for p, q in zip(picks, qs) if p != q["answer"]]
    extra = {"wrong": [q["term"] for q in wrong]}
    if not _recorded("term_quiz", c.visitor, track, extra) or payload.get("force") is True:
        engage.record("term_quiz", track, str(pct), extra, visitor=c.visitor)
    scores = [int(r["value"]) for r in engage.rows("term_quiz") if r["item"] == track and r["value"].isdigit()]
    better = sum(s < pct for s in scores) / len(scores) * 100 if scores else 0
    emoji, lv = G.level(pct)
    me_state.save_state(c.visitor, {"term_track": track, "term_i": len(qs), "term_picks": picks, "term_recorded": f"{track}:{seed}"})
    return {
        "score": pct, "right": right, "n": len(qs), "level": [emoji, lv], "track_label": G.TRACKS[track][1],
        "wrong": [q["term"] for q in wrong],
        "review": [{"term": q["term"], "define": q["define"], "hint": q["hint"]} for q in wrong],
        "stats": {"n": len(scores), "avg": round(mean(scores)) if scores else None, "top_pct": max(1, round(100 - better))},
        "share": {"url": f"/s/terms?track={track}&score={pct}", "title": f"AI·AX 용어 퀴즈 {pct}점 ({lv}) — 너는 몇 점?",
                  "text": f"AI·AX 용어 퀴즈 {pct}점({lv}). 업무에서 바로 쓰는 용어들인데, 몇 점 나오시나요?"},
    }


# ───────────────────────── AX 준비도 자가진단 ─────────────────────────

AREAS = {
    "AX Strategy": ("전략", [
        "AI 전환 목표와 우선순위가 경영 전략에 명시되어 있다",
        "AX 성과를 재무 지표(ROI·비용 절감·매출)로 측정한다",
        "AI 거버넌스(위험·책임·윤리) 원칙과 의사결정 체계가 있다",
        "직무·조직 재설계 계획에 AI 도입이 반영되어 있다",
    ]),
    "AX Implementation": ("실행", [
        "실제 업무에서 운영 중인 AI 사례가 있다",
        "파일럿을 전사 확산으로 옮기는 절차(검증·예산·운영 이관)가 있다",
        "AI 에이전트·자동화가 업무 시스템(ERP·CRM 등)과 연결되어 있다",
        "현업 부서가 직접 AI 과제를 제안하고 주도한다",
    ]),
    "AX Enablement": ("기반", [
        "AI가 쓸 수 있게 데이터가 정리·통합되어 있다",
        "생성형 AI 사용 보안 정책(정보 유출 방지 등)이 시행 중이다",
        "임직원 AI 리터러시 교육이 정기적으로 운영된다",
        "AI 서비스를 안전하게 배포·모니터링하는 기반(MLOps·LLMOps)이 있다",
    ]),
}
SCALE = ["아직 없음", "검토 중", "일부 적용", "전사 정착"]
LEVELS = [(25, "탐색", "#8C9BB5"), (50, "실험", "#5BC2F5"), (75, "확산", "#2E9BEA"), (101, "내재화", "#0ca30c")]
NEXT = {
    "AX Strategy": ["AX로 풀 경영 과제 3개를 고르고 담당 임원을 정하세요.",
                    "과제별 성과 지표(KPI)와 측정 주기를 정해 분기마다 점검하세요.",
                    "거버넌스 위원회와 위험 등급별 승인 절차를 문서로 만드세요.",
                    "AI 성과를 사업 계획·예산과 연결해 매년 갱신하세요."],
    "AX Implementation": ["반복 업무 한 곳을 골라 4주짜리 파일럿을 돌려 보세요.",
                          "파일럿 성공 기준과 확산 예산을 미리 정해 두세요.",
                          "에이전트를 업무 시스템과 연결하고 사람 검토 단계(휴먼인더루프)를 두세요.",
                          "현업이 과제를 제안·운영하는 사내 AX 프로그램으로 넓히세요."],
    "AX Enablement": ["핵심 데이터의 위치·담당자·품질을 목록으로 정리하세요.",
                      "생성형 AI 사용 지침과 정보 유출 방지 도구부터 갖추세요.",
                      "직무별 AI 리터러시 교육을 정기 과정으로 만드세요.",
                      "모델·프롬프트 배포와 모니터링을 표준 플랫폼으로 묶으세요."],
}
KEYS = [(cat, i) for cat, (_, qs) in AREAS.items() for i in range(len(qs))]


def level(score: float) -> tuple[str, str]:
    return next((name, color) for limit, name, color in LEVELS if score < limit)


@router.get("/diagnosis")
def diagnosis_meta() -> dict:
    return {"areas": {cat: [label, qs] for cat, (label, qs) in AREAS.items()}, "scale": SCALE,
            "levels": [[limit, name, color] for limit, name, color in LEVELS], "next": NEXT}


@router.post("/diagnosis/result")
def diagnosis_result(payload: dict = Body(...), c: Caller = CallerDep) -> dict:
    raw = payload.get("answers")
    if isinstance(raw, str) and re.fullmatch(f"[0-{len(SCALE) - 1}]{{{len(KEYS)}}}", raw):
        raw = [int(ch) for ch in raw]  # 공유 링크의 ?a=코드 그대로
    if not isinstance(raw, list) or len(raw) != len(KEYS):
        raise HTTPException(status_code=400, detail=f"{len(KEYS)}문항의 답(0~{len(SCALE) - 1} 또는 null)이 필요합니다.")
    answers: dict[tuple[str, int], int | None] = {}
    for key, v in zip(KEYS, raw):
        if v is None:
            answers[key] = None
        elif isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(SCALE):
            answers[key] = v
        else:
            raise HTTPException(status_code=400, detail="답은 0~3 또는 null 이어야 합니다.")
    done = sum(v is not None for v in answers.values())
    scores = {cat: sum(answers[(cat, i)] or 0 for i in range(len(qs))) / (3 * len(qs)) * 100 for cat, (_, qs) in AREAS.items()}
    total = sum(scores.values()) / len(scores)
    code = "".join(str(answers[k]) if answers[k] is not None else "0" for k in KEYS)
    name, color = level(total)
    weakest = min(scores, key=scores.get) if done else None
    next_steps = {cat: {"label": AREAS[cat][0], "score": round(scores[cat]), "level": level(scores[cat])[0],
                        "color": level(scores[cat])[1], "step": NEXT[cat][min(3, int(scores[cat] // 25))]} for cat in AREAS}
    if weakest:
        me_state.save_state(c.visitor, {"diag_weak": weakest})  # 홈 '나를 위한 추천'에 쓴다 (개인화)
    extra = {cat: round(v) for cat, v in scores.items()}
    if done == len(KEYS) and not _recorded("diagnosis", c.visitor, weakest, extra):
        engage.record("diagnosis", weakest, f"{total:.0f}", extra, visitor=c.visitor)
    report = "\n".join(
        [f"AX 준비도 자가진단 결과 — 종합 {total:.0f}점 ({name} 단계)", ""]
        + [f"[{AREAS[cat][0]}] {scores[cat]:.0f}점 ({level(scores[cat])[0]}) — 다음 단계: {NEXT[cat][min(3, int(scores[cat] // 25))]}" for cat in AREAS]
        + ["", "문항별 응답"]
        + [f"- {AREAS[cat][1][i]}: {SCALE[answers[(cat, i)]] if answers[(cat, i)] is not None else '미응답'}" for cat, i in KEYS])
    lvl = min(3, int(total // 25))  # app/web.py diag_level 과 같은 기준
    return {
        "code": code, "done": done, "scores": {cat: round(v, 1) for cat, v in scores.items()}, "total": round(total, 1),
        "level": [name, color], "weakest": weakest, "next_steps": next_steps,
        "recommended": _recs(weakest) if weakest else [], "report_txt": report,
        "share": {"url": f"/s/d?a={code}", "image": f"/app/static/og/diag-{lvl}.png", "title": f"우리 조직 AX 준비도: {name} 단계",
                  "text": f"AX 준비도 자가진단 결과 우리 조직은 '{name}' 단계({total:.0f}점)입니다. 12문항·3분이면 됩니다.",
                  "level_line": og_cards.DIAG_LEVELS[lvl][2]},
    }
