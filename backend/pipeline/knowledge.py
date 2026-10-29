"""저장된 임베딩·키워드로 만드는 지식 기능 — Gemini를 새로 부르지 않는다.

- related_notes: 노트 상세의 '가까운 노트' (임베딩 코사인, 없으면 같은 카테고리·태그)
- knowledge_map: 노트·기사 임베딩을 PCA로 2차원에 펼치고 k-means로 무리를 나눠 이름(가장 흔한 키워드)을 붙인다
- trends: 키워드별 일별 기사 수와 '급상승' 판정 (홈 띠·데이터 랩 공용)
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import date, datetime, timedelta

import numpy as np

from . import db

CATEGORIES = ("AX Strategy", "AX Implementation", "AX Enablement")
MIN_TREND_DAYS = 6  # 기사가 있는 날이 이보다 적으면 급상승을 판정하지 않는다 (비교할 과거가 없음)


def _unit(vectors: list[list[float]]) -> np.ndarray:
    m = np.asarray(vectors, dtype=np.float32)
    return m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-9)


# ───────────────────────── 가까운 노트 ─────────────────────────

def related_notes(note_id: int, k: int = 4) -> list[dict]:
    rows = db.embedded_rows("notes")
    me = next((r for r in rows if r["id"] == note_id), None)
    others = [r for r in rows if r["id"] != note_id]
    if me and others:
        sims = _unit([r["embedding"] for r in others]) @ _unit([me["embedding"]])[0]
        order = np.argsort(-sims)[:k]
        return [{**{x: y for x, y in others[i].items() if x != "embedding"}, "similarity": float(sims[i])} for i in order]
    # 임베딩이 없으면 같은 카테고리 + 겹치는 태그 수로 고른다.
    base = db.note(note_id)
    if not base:
        return []
    tags = {t for t in base["tags"].split(",") if t}
    pool = [n for n in db.notes() if n["id"] != note_id]
    pool.sort(key=lambda n: (n["category"] == base["category"], len(tags & set(n["tags"].split(","))), n["published"]),
              reverse=True)
    return pool[:k]


# ───────────────────────── 지식 지도 ─────────────────────────

def _kmeans(x: np.ndarray, k: int, iters: int = 30, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    centers = x[rng.choice(len(x), size=k, replace=False)]
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        labels = np.argmin(((x[:, None, :] - centers[None, :, :]) ** 2).sum(-1), axis=1)
        new = np.array([x[labels == j].mean(0) if (labels == j).any() else centers[j] for j in range(k)])
        if np.allclose(new, centers):
            break
        centers = new
    return labels


def knowledge_map(max_articles: int = 600) -> dict:
    kw_cat = {k["keyword"]: k["category"] for k in db.list_keywords() if k["category"] in CATEGORIES}
    notes = db.embedded_rows("notes")
    arts = sorted(db.embedded_rows("articles"), key=lambda a: a["collected_at"] or "", reverse=True)[:max_articles]
    points, vecs = [], []
    for n in notes:
        points.append({"type": "note", "t": n["title"], "s": n["source"], "cat": n["category"], "sc": 5,
                       "u": f"/notes?id={n['id']}", "sum": n["summary"][:160],
                       "kw": [t for t in n["tags"].split(",") if t][:3], "d": n["published"]})
        vecs.append(n["embedding"])
    for a in arts:
        kws = json.loads(a["matched_kw"] or "[]")
        cat = next((kw_cat[k] for k in kws if k in kw_cat), "")
        points.append({"type": "article", "t": a["title"], "s": a["source"], "cat": cat, "sc": a["llm_score"] or 0,
                       "u": a["url"], "sum": (a["summary_ko"] or a["excerpt"] or "")[:160], "kw": kws[:3],
                       "d": (a["published_at"] or "")[:10]})
        vecs.append(a["embedding"])
    if len(points) < 3:
        return {"points": points, "clusters": []}

    x = _unit(vecs)
    xc = x - x.mean(0)
    # PCA: 공분산 대신 SVD (768차원이라도 수백 건이면 바로 끝난다)
    _, _, vt = np.linalg.svd(xc, full_matrices=False)
    xy = xc @ vt[:2].T
    xy = (xy - xy.mean(0)) / np.maximum(xy.std(0), 1e-9)  # 축마다 같은 퍼짐으로
    xy = np.sign(xy) * np.abs(xy) ** 0.6  # 멀리 떨어진 무리 하나 때문에 나머지가 한쪽에 뭉치지 않게 바깥을 당긴다

    k = max(2, min(8, len(points) // 40))
    labels = _kmeans(xc @ vt[:20].T, k)  # 상위 20개 성분 공간에서 묶는다
    total = Counter(kw for p in points for kw in p["kw"])
    clusters = []
    for j in range(k):
        idx = np.where(labels == j)[0]
        if not len(idx):
            continue
        inside = Counter(kw for i in idx for kw in points[i]["kw"])
        # 이 무리에 '특히' 많은 키워드로 이름을 붙인다 (어디에나 많은 키워드는 lift가 낮다).
        lift = {kw: (c / len(idx)) / (total[kw] / len(points)) * math.log1p(c) for kw, c in inside.items() if c >= 2}
        name = sorted(lift, key=lift.get, reverse=True)[:2] or [c for c, _ in inside.most_common(1)]
        clusters.append({"x": float(xy[idx, 0].mean()), "y": float(xy[idx, 1].mean()), "n": int(len(idx)),
                         "name": " · ".join(name) or "기타"})
    for p, (px, py), lb in zip(points, xy, labels):
        p["x"], p["y"], p["c"] = round(float(px), 4), round(float(py), 4), int(lb)
    return {"points": points, "clusters": clusters}


# ───────────────────────── 트렌드 ─────────────────────────

def _day(a: dict) -> date | None:
    raw = a.get("published_at") or a.get("collected_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return (dt.astimezone(db.KST) if dt.tzinfo else dt).date()


def rising(series: list[int], window: int) -> tuple[int, int, float]:
    """(최근 창 합계, 그 전 창 합계, 증가율). 증가율은 (최근-이전)/(이전+2) — 작은 수에 과민하지 않게."""
    cur, prev = sum(series[-window:]), sum(series[-2 * window:-window])
    return cur, prev, (cur - prev) / (prev + 2)


def trends(days: int = 14) -> dict:
    """키워드별 최근 days일 일별 기사 수와 급상승 키워드."""
    kw_cat = {k["keyword"]: k["category"] for k in db.list_keywords() if k["category"] in CATEGORIES}
    today = datetime.now(db.KST).date()
    axis = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    pos = {d: i for i, d in enumerate(axis)}
    series: dict[str, list[int]] = {k: [0] * days for k in kw_cat}
    for a in db.articles(days + 1):
        d = _day(a)
        if d in pos:
            for k in set(json.loads(a["matched_kw"] or "[]")):
                if k in series:
                    series[k][pos[d]] += 1
    span = sum(1 for i in range(days) if any(s[i] for s in series.values()))  # 기사가 있는 날 수
    window = max(1, min(7, span // 2))
    rows = []
    for k, s in series.items():
        cur, prev, rate = rising(s, window)
        if cur:
            rows.append({"keyword": k, "category": kw_cat[k], "series": s, "cur": cur, "prev": prev, "rate": rate,
                         "rising": span >= MIN_TREND_DAYS and cur >= 3 and rate >= .5})
    rows.sort(key=lambda r: (-r["rising"], -r["rate"], -r["cur"]))
    return {"days": [d.isoformat() for d in axis], "window": window, "span": span, "rows": rows,
            "ready": span >= MIN_TREND_DAYS}
