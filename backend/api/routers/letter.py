"""뉴스레터 미리보기 (/api/letter) — 구독하면 받게 될 메일을 그대로, 지난 호도 함께.

Streamlit 판 app_pages/letter.py 를 옮겼다 (mailer.build_html preview=True, 5분 캐시).
"""
from __future__ import annotations

import time
from datetime import date, timedelta

from fastapi import APIRouter

from pipeline import db, jobs, mailer

router = APIRouter(tags=["letter"])

_cache: dict = {}


def _letters() -> list[dict]:
    """[{label, html}] — 다음 호(다음 발송될 내용) + 지난 호(게시된 주간 흐름과 그 주 노트)."""
    out = []
    issue, notes, _ = jobs.newsletter_content()
    if issue or notes:
        out.append({"label": f"다음 호 · {issue['week'] if issue else '새 노트'}",
                    "html": mailer.build_html(issue, notes, pdf_url=jobs.latest_report_url(), preview=True)})
    for it in reversed(db.issues("published")[:-1] if issue else db.issues("published")):
        start = it.get("week_start")
        if not start:
            continue
        end = (date.fromisoformat(start) + timedelta(days=6)).isoformat()
        out.append({"label": f"지난 호 · {it['week']}",
                    "html": mailer.build_html(it, db.notes_published_between(start, end)[:10], preview=True)})
    return out


@router.get("/letter")
def letter() -> dict:
    now = time.time()
    hit = _cache.get("letters")
    if not (hit and now - hit[0] < 300):
        hit = (now, _letters())
        _cache["letters"] = hit
    return {"letters": hit[1]}
