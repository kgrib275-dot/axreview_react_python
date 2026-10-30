"""관리 > 관리자·접속 — 관리자 IP 등록·삭제, 접속 기록(관리 작업·질문하기·페이지 조회·전체), 관리자 행동 기록 (app_pages/admin/access.py)."""
from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import _client_ip, require_admin
from api.routers.admin_jobs import log_action
from pipeline import db, settings_store

router = APIRouter(prefix="/admin", tags=["admin-access"], dependencies=[Depends(require_admin)])

_VIEWS = ("admin", "ask", "view", "all")


def _logs(view: str, limit: int) -> list[dict]:
    rows = db.access_logs(limit)
    if view == "admin":
        rows = [r for r in rows if r["action"] not in ("view", "ask")]
    elif view == "ask":
        rows = [r for r in rows if r["action"] == "ask"]
    elif view == "view":
        rows = [r for r in rows if r["action"] == "view"]
    return [{k: r.get(k) for k in ("id", "created_at", "ip", "page", "action", "detail")} for r in rows]


@router.get("/admin-ips")
def admin_ips(request: Request) -> dict:
    ip, proxied = _client_ip(request)
    return {"admin_ips": settings_store.load()["admin_ips"], "my_ip": ip or "", "proxied": proxied}


@router.post("/admin-ips")
def add_admin_ip(request: Request, body: dict[str, Any]) -> dict:
    label = (body.get("label") or "").strip()[:60]
    ip = (body.get("ip") or "").strip()[:64]
    if not (label and ip):
        raise HTTPException(400, "이름과 IP 를 입력하세요")
    try:
        ip = str(ipaddress.ip_address(ip))  # 오타·CIDR·호스트명은 등록해도 영원히 맞지 않는다 — 정규화된 표기로 저장
    except ValueError:
        raise HTTPException(400, "IP 주소 형식이 아닙니다 (예: 203.0.113.5, 2001:db8::1)")
    settings_store.add_admin_ip(label, ip)
    log_action(request, "관리자 IP 추가", f"{label} {ip}")
    return {"ok": True, "admin_ips": settings_store.load()["admin_ips"]}


@router.delete("/admin-ips/{admin_id}")
def delete_admin_ip(admin_id: str, request: Request) -> dict:
    a = next((a for a in settings_store.load()["admin_ips"] if a["id"] == admin_id), None)
    if not a:
        raise HTTPException(404, "등록된 IP 가 없습니다")
    settings_store.delete_admin_ip(admin_id)
    log_action(request, "관리자 IP 삭제", f"{a['label']} {a['ip']}")
    return {"ok": True, "admin_ips": settings_store.load()["admin_ips"]}


@router.get("/access-logs")
def access_logs(request: Request, view: str = "all", limit: int = 2000) -> dict:
    """view: admin(관리 작업) · ask(질문하기) · view(페이지 조회) · all."""
    if view not in _VIEWS:
        raise HTTPException(400, "view 는 admin·ask·view·all 중 하나입니다")
    log_action(request, "접속 기록 조회", view)  # IP 가 담긴 기록을 누가 봤는지 남긴다 (기록 전에 남겨 이번 조회도 목록에 보인다)
    rows = _logs(view, max(1, min(limit, 5000)))
    return {"view": view, "logs": rows, "count": len(rows), "unique_ips": len({r["ip"] for r in rows})}


@router.get("/actions")
def actions(request: Request, limit: int = 2000) -> dict:
    """관리자 행동 기록 (log_action 이 남긴 것) — access-logs?view=admin 과 같다."""
    log_action(request, "접속 기록 조회", "actions")
    rows = _logs("admin", max(1, min(limit, 5000)))
    return {"actions": rows, "count": len(rows), "unique_ips": len({r["ip"] for r in rows})}
