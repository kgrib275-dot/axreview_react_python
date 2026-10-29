"""노트 목록·상세 (/api/notes, /api/notes/{id}).

Streamlit 판 app_pages/notes.py 를 옮겼다.
- 의미 검색은 질의마다 임베딩 API 를 부른다 — 질의 200자, 방문자당 하루 40회(engagements 'semantic' 기록)로 남용을 막는다.
  (Streamlit 판은 세션당 40회였다 — API 에는 세션이 없어 방문자·하루 기준으로 바꿨다.)
- 초안·반려 노트는 관리자 미리보기로만 열린다.
"""
from __future__ import annotations

import os
import re
import time

from fastapi import APIRouter, HTTPException, Query, Request

from api.common import csv_list, md_html, note_card
from api.deps import Caller, CallerDep
from pipeline import db, industry, knowledge, vectorizer
from pipeline.llm import CATEGORIES

router = APIRouter(tags=["notes"])

SEMANTIC_MAX_CHARS = 200
SEMANTIC_PER_DAY = 40
MIN_SIMILARITY = 0.6

_sem_cache: dict[str, tuple[float, list[dict]]] = {}  # 같은 질의는 10분 동안 다시 임베딩하지 않는다
_rel_cache: dict[int, tuple[float, list[dict]]] = {}

def _cached(cache: dict, key, fn, ttl: int = 600, max_entries: int = 200):
    now = time.time()
    hit = cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    if len(cache) >= max_entries:
        cache.pop(next(iter(cache)))
    cache[key] = (now, val)
    return val

def _meta(notes: list[dict]) -> dict:
    return {"categories": list(CATEGORIES), "kinds": sorted({n["kind"] for n in notes}), "industries": industry.NAMES}

@router.get("/notes")
def list_notes(q: str = Query("", max_length=500), semantic: str = "", cats: str | None = None, kinds: str | None = None,
               inds: str | None = None, sort: str = "latest", c: Caller = CallerDep) -> dict:
    notes = db.notes()
    q = q.strip()
    want_sem = semantic in ("1", "true", "on")
    cat_f = [x for x in csv_list(cats) if x in CATEGORIES]
    kind_f = csv_list(kinds)
    ind_f = [x for x in csv_list(inds) if x in industry.NAMES]
    semantic_note = None

    def match(n: dict, use_text: bool) -> bool:
        text = f"{n['title']} {n['summary']} {n['tags']} {n['source']}".lower()
        return ((not use_text or not q or q.lower() in text)
                and (not cat_f or n["category"] in cat_f)
                and (not kind_f or n["kind"] in kind_f)
                and (not ind_f or bool(set(ind_f) & set(industry.of(n)))))

    used_semantic = False
    if q and want_sem:
        from pipeline import engage
        cached = _sem_cache.get(q.lower())
        fresh = not (cached and time.time() - cached[0] < 600)
        if len(q) > SEMANTIC_MAX_CHARS or (fresh and engage.count_today("semantic", c.visitor) >= SEMANTIC_PER_DAY):
            semantic_note = f"의미 검색 한도(질의 {SEMANTIC_MAX_CHARS}자 · 하루 {SEMANTIC_PER_DAY}회)를 넘어 단어 검색으로 찾았습니다."
        else:
            if fresh:
                engage.record("semantic", visitor=c.visitor)  # 질의 내용은 남기지 않는다
            ranked = _cached(_sem_cache, q.lower(), lambda: vectorizer.search(q, "notes", top_k=30))
            if ranked:
                used_semantic = True
                hits = [n for n in ranked if match(n, use_text=False) and n["similarity"] >= MIN_SIMILARITY]
            else:
                semantic_note = "의미 검색을 쓸 수 없어 단어 검색으로 찾았습니다."
    if not used_semantic:
        hits = [n for n in notes if match(n, use_text=True)]
    views = db.note_view_counts()
    if sort == "popular" and not used_semantic:
        hits.sort(key=lambda n: (views.get(n["id"], 0), n["published"]), reverse=True)
    out = []
    for n in hits:
        card = note_card(n, views=views.get(n["id"], 0))
        if used_semantic:
            card["similarity"] = round(float(n["similarity"]), 4)
        out.append(card)
    res = {"notes": out, "meta": _meta(notes), "count": len(out), "semantic_used": used_semantic}
    if semantic_note:
        res["semantic_note"] = semantic_note
    return res

def _body_html(body: str) -> tuple[str, list[str]]:
    """본문 → HTML. '### 제목' 은 목차용 h3(id=sec-n) 로 바꾼다 (md_html 은 모든 제목을 h2 로 낸다)."""
    headings = [h.strip() for h in re.findall(r"^###\s+(.+)$", body or "", flags=re.M)]
    html = md_html(body)
    i = -1

    def h3(m: re.Match) -> str:
        nonlocal i
        i += 1
        return f"<h3 id='sec-{i}'>{m.group(1)}</h3>"

    return re.sub(r"<h2>(.*?)</h2>", h3, html), headings

@router.get("/notes/{note_id}")
def note_detail(note_id: str, request: Request, c: Caller = CallerDep) -> dict:
    n = db.note(int(note_id)) if re.fullmatch(r"[0-9]{1,9}", note_id) else None  # 숫자가 아니면 422 대신 404
    if n and n["status"] != "published" and not c.is_admin:
        n = None  # 초안·반려 노트는 관리자 미리보기로만
    if not n:
        raise HTTPException(status_code=404, detail="없는 노트입니다.")
    body_html, toc = _body_html(n["body"])
    note = {k: v for k, v in n.items() if k != "embedding"}
    note.update({"body_html": body_html, "toc": toc, "industries": industry.of(n),
                 "minutes": max(1, round(len(n["body"] or "") / 600)),
                 "tag_list": [t for t in (n["tags"] or "").split(",") if t],
                 "audience_list": [a for a in (n["audiences"] or "").split(",") if a]})
    prev = nxt = None
    related: list[dict] = []
    if n["status"] == "published":
        db.record_access(c.ip, "노트", "note_view", str(n["id"]))
        order = db.notes()
        pos = next((i for i, x in enumerate(order) if x["id"] == n["id"]), None)
        if pos is not None:  # 이전(더 오래된)·다음(더 새로운) 노트 — 게시일 순
            older = order[pos + 1] if pos + 1 < len(order) else None
            newer = order[pos - 1] if pos > 0 else None
            prev = {"id": older["id"], "title": older["title"]} if older else None
            nxt = {"id": newer["id"], "title": newer["title"]} if newer else None
        related = [note_card(r, similarity=round(float(r.get("similarity", 0)), 4))
                   for r in _cached(_rel_cache, n["id"], lambda: knowledge.related_notes(n["id"], k=3))]
    site = (os.environ.get("SITE_URL") or str(request.base_url)).rstrip("/")
    return {"note": note, "prev": prev, "next": nxt, "related": related, "share_url": f"{site}/notes?id={n['id']}"}

