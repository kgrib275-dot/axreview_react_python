"""관리 > 주간 PDF 리포트 — 게시 흐름 목록·통계·미리보기 HTML·PDF 생성(jobs.start report) (app_pages/admin/report.py)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from api.common import note_card
from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import db, jobs, mailer, report_pdf

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"], dependencies=[Depends(require_admin)])


def _find(issue_id: int) -> dict:
    it = next((i for i in db.issues("published") if i["id"] == issue_id), None)
    if not it:
        raise HTTPException(404, "게시된 주간 흐름이 없습니다")
    return it


def _row(issue: dict) -> dict:
    issue, notes, stats = jobs.report_content(issue)
    path = report_pdf.report_path(issue)
    exists = path.exists()
    return {"id": issue["id"], "week": issue["week"], "headline_em": issue["headline_em"], "headline": issue["headline"],
            "range": issue["range"], "notes": len(notes), "stats": stats, "pdf_exists": exists,
            "pdf_url": report_pdf.report_url(mailer.site_url(), issue) if exists else None,
            "pdf_file": path.name if exists else None,
            "pdf_bytes": path.stat().st_size if exists else None,
            "download_url": f"/api/admin/reports/{issue['id']}/pdf" if exists else None,
            "preview_url": f"/api/admin/reports/{issue['id']}/html"}


@router.get("")
def list_reports() -> dict:
    """게시된 주간 흐름 최신순 + 각 PDF 상태."""
    published = db.issues("published")[::-1]
    return {"reports": [_row(i) for i in published], "report_running": "report" in jobs.active(),
            "jobs": admin_jobs.status(), "run_logs": admin_jobs.run_log_rows("report", 20)}


@router.get("/{issue_id}")
def get_report(issue_id: int) -> dict:
    issue = _find(issue_id)
    _, notes, stats = jobs.report_content(issue)
    return {**_row(issue), "note_list": [note_card(n) for n in notes]}


@router.get("/{issue_id}/html")
def preview_html(issue_id: int) -> HTMLResponse:
    """리포트 미리보기 (iframe srcdoc 용)."""
    issue = _find(issue_id)
    issue, notes, stats = jobs.report_content(issue)
    if not notes:
        raise HTTPException(404, "이 주에 게시된 노트가 없어 리포트를 만들 수 없습니다.")
    return HTMLResponse(report_pdf.full_html(report_pdf.build_deck_html(issue, notes, stats)))


@router.get("/{issue_id}/pdf")
def download_pdf(issue_id: int) -> FileResponse:
    issue = _find(issue_id)
    path = report_pdf.report_path(issue)
    if not path.exists():
        raise HTTPException(404, "아직 만든 PDF 가 없습니다")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/{issue_id}")
def make_pdf(issue_id: int, request: Request) -> dict:
    """PDF 만들기/다시 만들기 — jobs.start('report', issue_id)."""
    issue = _find(issue_id)
    _, notes, _ = jobs.report_content(issue)
    if not notes:
        raise HTTPException(400, "이 주에 게시된 노트가 없어 리포트를 만들 수 없습니다.")
    started = jobs.start("report", trigger="수동", issue_id=issue_id)
    if started:
        log_action(request, "PDF 생성", issue["week"])
    return {"started": started}
