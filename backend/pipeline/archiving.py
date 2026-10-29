"""데일리 브리핑용 일별 아카이브 (AI_NEWS pipeline/archiving.py 기반).

KST 기준 지난 날짜의 수집 기사를 소스별·카테고리별로 집계해 한 번만 확정 저장한다.
오늘은 진행 중이라 저장하지 않고 화면에서 같은 함수로 실시간 집계한다. 카테고리는
기사에 걸린 키워드의 분류(AX Strategy / Implementation / Enablement)를 쓴다.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import db

SOURCE_TOP_N = 3
CATEGORY_TOP_N = 5
TOP_N = 5


def _keyword_categories() -> dict[str, str]:
    return {k["keyword"]: k["category"] for k in db.list_keywords() if k["category"]}


def _item(a: dict, cats: list[str]) -> dict:
    return {"title": a["title"], "url": a["url"], "source": a["source"], "score": a.get("llm_score"),
            "published_at": a.get("published_at") or "", "categories": cats, "summary": a.get("summary_ko") or "",
            "url_hash": a["url_hash"], "status": a.get("status")}


def build_content(articles: list[dict]) -> dict:
    kw_cat = _keyword_categories()
    scored = []
    for a in articles:
        cats = sorted({kw_cat[k] for k in json.loads(a.get("matched_kw") or "[]") if k in kw_cat})
        scored.append((a, cats))
    scored.sort(key=lambda p: p[0].get("llm_score") or 0, reverse=True)

    source_counts: dict[str, int] = {}
    source_groups: dict[str, list] = {}
    cat_counts: dict[str, int] = {}
    cat_groups: dict[str, list] = {}
    for a, cats in scored:
        source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1
        source_groups.setdefault(a["source"], []).append((a, cats))
        for c in cats:
            cat_counts[c] = cat_counts.get(c, 0) + 1
            cat_groups.setdefault(c, []).append((a, cats))
    return {
        "source_counts": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
        "source_top_news": {s: [_item(a, c) for a, c in g[:SOURCE_TOP_N]] for s, g in source_groups.items()},
        "category_counts": cat_counts,
        "category_news": {c: [_item(a, cs) for a, cs in g[:CATEGORY_TOP_N]] for c, g in cat_groups.items()},
        "top_articles": [_item(a, c) for a, c in scored[:TOP_N]],
        "total_count": len(scored),
        "avg_score": round(sum(a.get("llm_score") or 0 for a, _ in scored) / len(scored), 1) if scored else 0,
    }


def archive_pending() -> list[str]:
    """기사가 있는 지난 날짜 중 아직 확정 안 된 날짜를 모두 확정한다(최초 실행 시 소급)."""
    today = datetime.now(db.KST).strftime("%Y-%m-%d")
    pending = sorted(db.article_dates() - set(db.archived_dates()) - {today})
    done = []
    for d in pending:
        articles = db.articles_on(d)
        if articles and db.insert_archive(d, build_content(articles)):
            done.append(d)
    return done
