"""관리 > 참여 분석 — 일별 추이·구독 유입·유형 비교·퀴즈·용어 퀴즈·예측 투표·참여 지도 집계, CSV, 예시 데이터 (app_pages/admin/engagement.py).

집계는 원본처럼 1분 캐시한다 (기간·예시 포함 여부별). 예시 데이터를 넣거나 지우면 캐시를 비운다.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from app import ax_tests, ax_types, geo_map
from pipeline import db, engage, settings_store

router = APIRouter(prefix="/admin/engagement", tags=["admin-engagement"], dependencies=[Depends(require_admin)])

_DAYS = (7, 14, 30, 90)
_TTL = 60
_lock = threading.Lock()
_cache: dict[tuple, tuple[float, Any]] = {}
_BY = {"age": "연령대", "gender": "성별", "country": "국가", "region": "시·도"}


def _cached(key: tuple, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
    val = fn()
    with _lock:
        now = time.time()
        for k in [k for k, (t, _) in _cache.items() if now - t >= _TTL]:  # 만료된 집계는 버린다 (메모리가 계속 늘지 않게)
            _cache.pop(k, None)
        _cache[key] = (now, val)
    return val


def _clear() -> None:
    with _lock:
        _cache.clear()


def _load(days: int, with_sample: bool) -> pd.DataFrame:
    """기간 안 참여 기록 + 프로필 열."""
    rows = engage.rows(since_days=days, include_sample=with_sample)
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["kind", "item", "value", "extra", "visitor", "created_at"])
    df["day"] = df["created_at"].str[:10]
    df["correct"] = [json.loads(x or "{}").get("correct", 0) if k == "quiz" else 0 for k, x in zip(df["kind"], df["extra"])]
    pf = pd.DataFrame.from_dict(engage.profiles(with_sample), orient="index")
    for col in ("gender", "age", "country", "region"):
        df[col] = (df["visitor"].map(pf[col]) if col in pf else pd.Series(index=df.index, dtype=object)).replace("", None).fillna("미응답")
    return df


def _frame(days: int, with_sample: bool) -> pd.DataFrame:
    return _cached(("df", days, with_sample), lambda: _load(days, with_sample))


def _table(df: pd.DataFrame) -> dict:
    """pivot/crosstab 결과를 {index: [...], columns: [...], rows: [[...]]} 로 (NaN → None)."""
    df = df.astype(object).where(pd.notna(df), None)
    return {"index": [str(i) for i in df.index], "columns": [str(c) for c in df.columns], "rows": df.values.tolist()}


def _type_tab(df: pd.DataFrame) -> dict:
    t = df[df["kind"] == "type_test"].copy()
    if t.empty:
        return {"empty": True}
    t["유형"] = t["item"].map(lambda c: f"{ax_types.TYPES[c][0]} {ax_types.TYPES[c][1]} ({c})" if c in ax_types.TYPES else c)
    counts = t["유형"].value_counts()
    crosstab = {by: _table(pd.crosstab(t["유형"], t[by], normalize="columns").mul(100).round(1)) for by in _BY}
    axes = [json.loads(x or "{}").get("axes", []) for x in t["extra"]]
    avg = {}
    if axes and axes[0]:
        avg = {f"{a[3]} ↔ {a[4]}": round(sum(r[i][2] / max(1, r[i][2] + r[i][3]) for r in axes if len(r) > i) / len(axes) * 100)
               for i, a in enumerate(ax_types.AXES)}
    return {"empty": False, "counts": [{"type": k, "n": int(v)} for k, v in counts.items()],
            "crosstab": crosstab, "by_labels": _BY, "axes_avg": avg}


def _quiz_tab(df: pd.DataFrame) -> dict:
    q = df[df["kind"] == "quiz"].copy()
    if q.empty:
        return {"empty": True}
    per = q.groupby("item").agg(responses=("correct", "size"), rate=("correct", "mean")).reset_index()
    per["rate"] = (per["rate"] * 100).round(1)
    per = per.sort_values("item", ascending=False)
    pivot = q.pivot_table(index="age", columns="gender", values="correct", aggfunc="mean").mul(100).round(1)
    visitors = tuple(sorted(q["visitor"].unique()))
    # 캐시 키에 방문자 수천 명 목록을 통째로 넣지 않는다 (키마다 수백 KB) — 개수와 해시로
    streaks = Counter(_cached(("streaks", len(visitors), hash(visitors)), lambda: engage.streaks(visitors)).values())
    return {"empty": False,
            "per_question": [{"item": r["item"], "responses": int(r["responses"]), "rate": float(r["rate"])} for r in per.to_dict("records")],
            "age_gender": _table(pivot),
            "streaks": [{"days": int(k), "visitors": int(v)} for k, v in sorted(streaks.items())]}


def _term_tab(df: pd.DataFrame) -> dict:
    tq = df[df["kind"] == "term_quiz"].copy()
    if tq.empty:
        return {"empty": True}
    tq["score"] = pd.to_numeric(tq["value"], errors="coerce")
    tq["track"] = tq["item"].map({"ai": "AI 기술 편", "ax": "AX 비즈니스 편"}).fillna(tq["item"])
    missed = Counter(t for x in tq["extra"] for t in json.loads(x or "{}").get("wrong", []))
    return {"empty": False,
            "track_age": _table(tq.pivot_table(index="track", columns="age", values="score", aggfunc="mean").round(1)),
            "missed": [{"term": t, "n": n} for t, n in missed.most_common(12)]}


# 참여 기록 종류 → 화면 이름 (새 종류가 생기면 여기에 없어도 '전체 현황'에 코드 그대로 나온다)
KIND_LABELS = {
    "type_test": "AX 리더 유형 테스트", "career": "AX 커리어 유형", "habit": "AI 활용 습관 진단", "term_quiz": "AI·AX 용어 퀴즈",
    "diagnosis": "AX 준비도 자가진단", "quiz": "오늘의 퀴즈 응답", "poll": "예측 투표", "try_click": "홈 맛보기 클릭",
    "ask": "AX 질문하기", "semantic": "의미 검색", "share": "결과 공유", "share_visit": "공유 링크로 유입",
    "subscribe_open": "구독 창 열기", "subscribe": "구독 신청", "subscribe_confirm": "구독 확인 완료", "ref_visit": "추천 링크로 유입",
    "member_request_open": "월 구독 신청 창 열기", "member_request": "월 구독 신청", "member_on": "월 구독 코드 등록",
    "subscribe_try": "구독 시도(남용 제한 집계)", "confirm_try": "구독 확인 시도(남용 제한 집계)", "unsub_try": "해지 시도(남용 제한 집계)",
    "contact_try": "문의 시도(남용 제한 집계)", "member_try": "월 구독 시도(남용 제한 집계)", "refer_try": "추천 현황 조회(남용 제한 집계)",
}
TRY_LABELS = {"quiz": "오늘의 퀴즈 1번 풀기", "tests_all": "AX 테스트 전체 보기", "lab": "키워드 추세 → 데이터 랩", "map": "참여 현황 → 참여 지도",
              "ask": "질문하기 예시 질문"}
ACCESS_LABELS = {"view": "페이지 보기", "note_view": "노트 상세 보기", "semantic": "의미 검색", "ask": "AX 질문하기", "confirm_mail": "구독 확인 메일 발송", "제한 기록": "남용 제한 기록"}


def _all_tab(df: pd.DataFrame, days: int, with_sample: bool) -> dict:
    """기록되는 모든 종류 — 기간 안 건수·방문자 수·오늘, 전체 누적 (참여 기록) + 서버 접속 기록(action 별)."""
    today = engage.today().isoformat()
    period = {k: (int(len(g)), int(g["visitor"].nunique()), int((g["day"] == today).sum())) for k, g in df.groupby("kind")} if not df.empty else {}
    conn = engage._conn()
    try:
        cond = "" if with_sample else " WHERE visitor NOT LIKE ?"
        total = dict(conn.execute(f"SELECT kind, COUNT(*) FROM engagements{cond} GROUP BY kind",
                                  () if with_sample else (engage.SAMPLE + "%",)).fetchall())
        since = (pd.Timestamp.now() - pd.Timedelta(days=days)).isoformat(timespec="seconds")
        acc = conn.execute("SELECT action, COUNT(*), COUNT(DISTINCT ip) FROM access_logs WHERE created_at >= ? GROUP BY action ORDER BY 2 DESC",
                           (since,)).fetchall()
    finally:
        conn.close()
    kinds = sorted(set(period) | set(total), key=lambda k: (-period.get(k, (0,))[0], -total.get(k, 0)))
    rows = [{"구분": KIND_LABELS.get(k, k), "코드": k, f"최근 {days}일": period.get(k, (0, 0, 0))[0], "방문자": period.get(k, (0, 0, 0))[1],
             "오늘": period.get(k, (0, 0, 0))[2], "전체 누적": int(total.get(k, 0))} for k in kinds]
    access = [{"구분": ACCESS_LABELS.get(a) or KIND_LABELS.get(a, a), "코드": a, f"최근 {days}일": int(n), "IP 수": int(ip)} for a, n, ip in acc]
    return {"engagements": rows, "access": access}


def _try_tab(df: pd.DataFrame) -> dict:
    t = df[df["kind"] == "try_click"].copy()
    if t.empty:
        return {"empty": True}
    names = {f"test:{kind}": f"테스트 카드 · {KIND_LABELS.get(kind, kind)}" for kind in KIND_LABELS}

    def label(item: str) -> str:
        return TRY_LABELS.get(item) or names.get(item) or item
    by = t.groupby("item").agg(clicks=("visitor", "size"), visitors=("visitor", "nunique")).reset_index().sort_values("clicks", ascending=False)
    daily = t.groupby("day").size().sort_index()
    return {"empty": False,
            "items": [{"맛보기": label(r["item"]), "클릭": int(r["clicks"]), "방문자": int(r["visitors"])} for r in by.to_dict("records")],
            "daily": [{"날짜": d, "클릭": int(n)} for d, n in daily.items()]}


def _habit_tab(df: pd.DataFrame) -> dict:
    h = df[df["kind"] == "habit"].copy()
    if h.empty:
        return {"empty": True}
    h["score"] = pd.to_numeric(h["value"], errors="coerce")
    levels = h["item"].value_counts()
    order = [n for _, _, n, _ in ax_tests.HABIT_LEVELS]
    dims = pd.DataFrame([json.loads(x or "{}") for x in h["extra"]])
    names = {k: n for k, n, _ in ax_tests.HABIT_DIMS}
    return {"empty": False, "n": int(len(h)), "avg": round(float(h["score"].mean()), 1),
            "levels": [{"단계": lv, "참여": int(levels.get(lv, 0))} for lv in order],
            "dims": [{"영역": names.get(k, k), "평균 점수": round(float(dims[k].mean()), 1)} for k in names if k in dims],
            "by_age": _table(h.pivot_table(index="age", values="score", aggfunc="mean").round(1))}


def _career_tab(df: pd.DataFrame) -> dict:
    c = df[df["kind"] == "career"].copy()
    if c.empty:
        return {"empty": True}
    label = lambda k: f"{ax_tests.CAREER_TYPES[k][0]} {ax_tests.CAREER_TYPES[k][1]}" if k in ax_tests.CAREER_TYPES else k  # noqa: E731
    c["유형"] = c["item"].map(label)
    c["2순위"] = c["value"].map(label)
    first, second = c["유형"].value_counts(), c["2순위"].value_counts()
    order = sorted(set(first.index) | set(second.index), key=lambda k: (-int(first.get(k, 0)), -int(second.get(k, 0))))
    return {"empty": False, "n": int(len(c)),
            "types": [{"유형": k, "1순위": int(first.get(k, 0)), "2순위": int(second.get(k, 0))} for k in order],
            "by_age": _table(pd.crosstab(c["유형"], c["age"], normalize="columns").mul(100).round(1))}


def _diag_tab(df: pd.DataFrame) -> dict:
    d = df[df["kind"] == "diagnosis"].copy()
    if d.empty:
        return {"empty": True}
    d["score"] = pd.to_numeric(d["value"], errors="coerce")
    weak = d["item"].value_counts()
    areas = pd.DataFrame([json.loads(x or "{}") for x in d["extra"]])
    return {"empty": False, "n": int(len(d)), "avg": round(float(d["score"].mean()), 1),
            "weakest": [{"가장 약한 영역": k, "참여": int(v)} for k, v in weak.items()],
            "areas": [{"영역": k, "평균 점수": round(float(areas[k].mean()), 1)} for k in areas.columns]}


def _poll_tab(df: pd.DataFrame) -> list[dict]:
    out = []
    for d in sorted(set(df.loc[df["kind"] == "poll", "item"]), reverse=True):
        res = _cached(("poll_result", d), lambda d=d: engage.poll_result(d))
        votes = _cached(("poll_votes", d), lambda d=d: engage.poll_votes(d))
        total = sum(votes.values())
        winner = (res or {}).get("winner")
        out.append({"day": d, "votes": total, "crowd": votes.most_common(1)[0][0] if votes else "-",
                    "winner": winner or "집계 전",
                    "hit": "-" if not winner else ("O" if res["crowd"] == winner else "X"),
                    "hit_rate": round(votes[winner] / max(1, total) * 100, 1) if winner else None})
    return out


@router.get("")
def engagement(days: int = 14, sample: int = 0) -> dict:
    if days not in _DAYS:
        raise HTTPException(400, f"days 는 {', '.join(map(str, _DAYS))} 중 하나입니다")
    with_sample = bool(sample)
    df = _frame(days, with_sample)
    ret = _cached(("retention", days), lambda: engage.retention(days))
    kinds = Counter(df["kind"])
    return {
        "days": days, "with_sample": with_sample, "empty": df.empty,
        "sample": {"count": engage.sample_count(), "on_map": settings_store.load()["engage"]["sample_on_map"]},
        "summary": {"visitors": int(df["visitor"].nunique()), "retention": ret, "type_test": kinds["type_test"],
                    "quiz": kinds["quiz"], "term_quiz": kinds["term_quiz"], "poll": kinds["poll"],
                    "share": kinds["share"], "share_visit": kinds["share_visit"], "subscribe": kinds["subscribe"],
                    "career": kinds["career"], "habit": kinds["habit"], "diagnosis": kinds["diagnosis"], "try_click": kinds["try_click"],
                    "ask": kinds["ask"]},
        "all": _cached(("all", days, with_sample), lambda: _all_tab(df, days, with_sample)),
        "try": _try_tab(df), "habit": _habit_tab(df), "career": _career_tab(df), "diag": _diag_tab(df),
        "daily": _cached(("daily", days), lambda: engage.daily_activity(days)),
        "funnel": _cached(("funnel", days), lambda: engage.funnel_by_source(days)),
        "type": _type_tab(df), "quiz": _quiz_tab(df), "term": _term_tab(df), "poll": _poll_tab(df),
        "map": _cached(("map", days, with_sample), lambda: engage.map_data(days, include_sample=with_sample)),
        "map_html_url": f"/api/admin/engagement/map.html?days={days}&sample={int(with_sample)}",
    }


@router.get("/map.html")
def map_html(days: int = 14, sample: int = 0) -> HTMLResponse:
    """참여 지도 HTML 문서 (iframe srcdoc 용) — 개별 칸 포함 관리자용."""
    if days not in _DAYS:
        raise HTTPException(400, f"days 는 {', '.join(map(str, _DAYS))} 중 하나입니다")
    data = _cached(("map", days, bool(sample)), lambda: engage.map_data(days, include_sample=bool(sample)))
    return HTMLResponse(geo_map.html(data))


@router.get("/csv")
def csv(days: int = 14, sample: int = 0) -> Response:
    """참여 기록 CSV (방문자 값 제외, 수식 주입 방지)."""
    if days not in _DAYS:
        raise HTTPException(400, f"days 는 {', '.join(map(str, _DAYS))} 중 하나입니다")
    df = _frame(days, bool(sample))
    body = db.csv_safe(df.drop(columns=["visitor"])).to_csv(index=False).encode("utf-8-sig")
    return Response(body, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="axreview_engagement_{days}d.csv"'})


@router.post("/sample")
def sample(request: Request, body: dict[str, Any]) -> dict:
    action = body.get("action")
    if action == "seed":
        n = engage.seed_sample()
        log_action(request, "예시 데이터 넣기", f"{n}건")
    elif action == "clear":
        n = engage.clear_sample()
        log_action(request, "예시 데이터 지우기", f"{n}건")
    else:
        raise HTTPException(400, "action 은 seed 또는 clear 입니다")
    _clear()
    return {"ok": True, "action": action, "n": n, "count": engage.sample_count()}


@router.put("/sample-on-map")
def sample_on_map(request: Request, body: dict[str, Any]) -> dict:
    cfg = settings_store.load()["engage"]
    on = bool(body.get("on"))
    settings_store.save_section("engage", {**cfg, "sample_on_map": on})
    log_action(request, "공개 지도 예시 데이터", "표시" if on else "숨김")
    _clear()
    return {"ok": True, "on": on}
