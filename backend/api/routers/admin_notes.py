"""관리 > 노트 검토 — 초안·게시·반려 목록, 편집·저장·게시·반려·삭제, 직접 작성 (app_pages/admin/review.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.common import md_html
from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import db, jobs, llm

router = APIRouter(prefix="/admin/notes", tags=["admin-notes"], dependencies=[Depends(require_admin)])

_STATUSES = ("draft", "published", "rejected")


def _clean(body: dict[str, Any], require: bool = True) -> dict:
    """review.py note_form 과 같은 정리 — 제목·요약 필수, 태그 '#' 제거, 본문 비면 요약으로."""
    title = (body.get("title") or "").strip()
    summary = (body.get("summary") or "").strip()
    if require and not (title and summary):
        raise HTTPException(400, "제목과 카드 요약은 필수입니다.")
    category = body.get("category") or llm.CATEGORIES[1]
    kind = body.get("kind") or llm.KINDS[0]
    if category not in llm.CATEGORIES or kind not in llm.KINDS:
        raise HTTPException(400, "카테고리·유형 값을 확인해 주세요.")
    aud = body.get("audiences") or []
    if isinstance(aud, str):
        aud = [a.strip() for a in aud.split(",")]
    tags = body.get("tags") or ""
    if isinstance(tags, list):
        tags = ",".join(tags)
    out = {
        "title": title, "category": category, "kind": kind, "source": (body.get("source") or "").strip(),
        "url": (body.get("url") or "").strip(), "audiences": ",".join(a for a in aud if a in llm.AUDIENCES),
        "tags": ",".join(t.strip().lstrip("#") for t in tags.split(",") if t.strip()),
        "summary": summary, "body": (body.get("body") or "").strip() or f"### 요약\n{summary}",
    }
    if body.get("published"):
        out["published"] = str(body["published"])[:10]
    return out


def _full(n: dict) -> dict:
    n = dict(n)
    n.pop("embedding", None)
    n["audiences_list"] = [a for a in (n.get("audiences") or "").split(",") if a]
    n["tags_list"] = [t for t in (n.get("tags") or "").split(",") if t]
    return n


@router.get("")
def list_notes(status: str = "draft") -> dict:
    if status not in _STATUSES:
        raise HTTPException(400, "status 는 draft·published·rejected 중 하나입니다")
    items = [_full(n) for n in db.notes(status)]
    return {"status": status, "notes": items, "count": len(items),
            "meta": {"categories": llm.CATEGORIES, "kinds": llm.KINDS, "audiences": llm.AUDIENCES},
            "counts": {s: len(db.notes(s)) for s in _STATUSES}}


@router.get("/{note_id}")
def get_note(note_id: int) -> dict:
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    n = _full(n)
    n["body_html"] = md_html(n.get("body") or "")
    return {"note": n}


@router.post("")
def create_note(request: Request, body: dict[str, Any]) -> dict:
    """직접 작성. body.publish=true 면 바로 게시(+벡터화 시작)."""
    data = _clean(body)
    publish = bool(body.get("publish"))
    note_id = db.add_note(**data, status="published" if publish else "draft")
    log_action(request, "노트 게시" if publish else "노트 저장", data["title"])
    if publish:
        jobs.start("vectorize", trigger="게시")
    return {"id": note_id, "status": "published" if publish else "draft"}


@router.put("/{note_id}")
def save_note(note_id: int, request: Request, body: dict[str, Any]) -> dict:
    """저장 (상태 유지). body.status 로 'draft'/'rejected' 전환(반려·게시 내리기)도 가능 — 게시는 /publish."""
    if not db.note(note_id):
        raise HTTPException(404, "노트가 없습니다")
    status = body.get("status")
    if status is not None and status not in ("draft", "rejected"):
        raise HTTPException(400, "status 는 draft 또는 rejected 만 바꿀 수 있습니다 (게시는 /publish)")
    data = _clean(body, require=status is None)
    if status is None:
        db.update_note(note_id, **data)
        log_action(request, "노트 저장", data["title"])
    else:
        if data["title"]:
            db.update_note(note_id, **data)
        db.update_note(note_id, status=status)
        log_action(request, "노트 반려", data["title"] or str(note_id))
    return {"ok": True, "note": _full(db.note(note_id))}


@router.post("/{note_id}/publish")
def publish_note(note_id: int, request: Request, body: dict[str, Any] | None = None) -> dict:
    """편집 내용(있으면)을 저장하고 게시 → 벡터화 작업 시작."""
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    if body and body.get("title"):
        db.update_note(note_id, **_clean(body))
    db.publish_note(note_id)
    log_action(request, "노트 게시", (body or {}).get("title") or n["title"])
    started = jobs.start("vectorize", trigger="게시")
    return {"ok": True, "vectorize_started": started, "note": _full(db.note(note_id))}


@router.delete("/{note_id}")
def delete_note(note_id: int, request: Request) -> dict:
    n = db.note(note_id)
    if not n:
        raise HTTPException(404, "노트가 없습니다")
    db.delete_note(note_id)
    log_action(request, "노트 삭제", n["title"])
    if n.get("article_hash"):
        db.set_article_status(n["article_hash"], "skipped")  # 원문 기사는 건너뜀으로 되돌린다
    return {"ok": True}
