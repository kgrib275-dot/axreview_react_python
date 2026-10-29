"""관리 > Databricks 적재 — 연결 설정 상태·자동 적재 토글·연결 테스트·적재 시작·테이블 현황(2분 캐시)·적재 기록 (app_pages/admin/warehouse.py).

토큰 등 .env 값은 끝 4자리만 보여 준다 (원본과 같음).
"""
from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers import admin_jobs
from api.routers.admin_jobs import log_action
from pipeline import jobs, settings_store, warehouse

router = APIRouter(prefix="/admin/warehouse", tags=["admin-warehouse"], dependencies=[Depends(require_admin)])

_STATUS_TTL = 120  # 전체 행 해시 비교라 무겁다 — 2분 캐시
_lock = threading.Lock()
_status_cache: tuple[float, list[dict]] | None = None


def _status(refresh: bool = False) -> list[dict]:
    global _status_cache
    with _lock:
        if not refresh and _status_cache and time.time() - _status_cache[0] < _STATUS_TTL:
            return _status_cache[1]
    rows = warehouse.status()
    with _lock:
        _status_cache = (time.time(), rows)
    return rows


@router.get("")
def get_warehouse(refresh: int = 0) -> dict:
    """refresh=1 이면 테이블 현황을 다시 센다 (화면의 '다시 세기')."""
    cfg = warehouse.settings()
    problems = warehouse.problems(cfg)
    return {
        "target": warehouse.target(), "configured": not problems, "problems": problems,
        "connection": {"host": cfg["host"], "http_path": cfg["http_path"], "token_tail": cfg["token"][-4:] if cfg["token"] else ""}
        if not problems else None,
        "auto_sync": settings_store.load()["warehouse"]["auto_sync"],
        "tables": _status(bool(refresh)),
        "last_synced": warehouse.last_synced(),
        "sync_running": "warehouse" in jobs.active(), "jobs": admin_jobs.status(),
        "run_logs": admin_jobs.run_log_rows("warehouse", 20),
    }


@router.post("/test")
def test_connection() -> dict:
    """Databricks 접속 시험 (Warehouse 가 꺼져 있으면 수십 초)."""
    if warehouse.problems():
        raise HTTPException(400, "연결 설정이 없습니다: " + " · ".join(warehouse.problems()))
    try:
        info = warehouse.test_connection()
    except Exception as e:  # noqa: BLE001 - 화면에 그대로 보여 준다
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
    return {"ok": True, **info}


@router.post("/sync")
def sync(request: Request, body: dict[str, Any] | None = None) -> dict:
    """적재 시작 — jobs.start('warehouse', full=…)."""
    if warehouse.problems():
        raise HTTPException(400, "연결 설정이 없습니다: " + " · ".join(warehouse.problems()))
    global _status_cache
    full = bool((body or {}).get("full"))
    started = jobs.start("warehouse", trigger="수동", full=full)
    if started:
        log_action(request, "작업 실행", "Databricks 전체 다시 적재" if full else "Databricks 적재")
        with _lock:
            _status_cache = None
    return {"started": started, "full": full}


@router.put("/auto")
def set_auto(request: Request, body: dict[str, Any]) -> dict:
    on = bool(body.get("on"))
    settings_store.save_section("warehouse", {"auto_sync": on})
    log_action(request, "자동 적재", "켜짐" if on else "꺼짐")
    return {"ok": True, "auto_sync": on}


@router.post("/reset")
def reset(request: Request, body: dict[str, Any] | None = None) -> dict:
    """적재 기억(warehouse_sync)을 지운다 — 다음 적재 때 전부 다시 보낸다. {tables: [...]} 로 일부만 가능."""
    global _status_cache
    wanted = (body or {}).get("tables") or []
    bad = [t for t in wanted if t not in warehouse.TABLES]
    if bad:
        raise HTTPException(400, f"없는 테이블: {', '.join(map(str, bad))}")
    tables = list(wanted) or None
    warehouse.reset_state(tables)
    with _lock:
        _status_cache = None
    log_action(request, "Databricks 적재 상태 초기화", ", ".join(tables) if tables else "전체")
    return {"ok": True, "tables": tables or list(warehouse.TABLES)}
