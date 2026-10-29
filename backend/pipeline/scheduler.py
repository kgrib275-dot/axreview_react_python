"""앱 내부 배치 스케줄러 (AI_NEWS scheduler.py와 같은 구조).

Streamlit 프로세스가 떠 있는 동안 30초마다 설정을 읽어, 등록된 시각이 되면 작업을
시작한다. 같은 분에 두 번 돌지 않도록 마지막 실행 분을 data/scheduler_last_fired.json에
남긴다(재시작해도 유지).
"""
from __future__ import annotations

import json
import os
import logging
import threading
import time
from datetime import datetime, timedelta

from . import alerts, db, jobs, settings_store
from .db import ROOT

_POLL_SECONDS = 30
_LAST_FIRED_FILE = ROOT / "data" / "scheduler_last_fired.json"
_lock = threading.Lock()
_started = False
logger = logging.getLogger("axreview.scheduler")


def _load_last_fired() -> dict:
    try:
        return json.loads(_LAST_FIRED_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_last_fired = _load_last_fired()


def _claim(key: str, minute_key: str) -> bool:
    """여러 서버 프로세스(개발·공개)가 같은 DB를 쓰면 스케줄러도 여러 개 돈다 — DB에 먼저 기록한 한 곳만 실행한다.
    (2026-10-28 실측: 프로세스 3개가 같은 분에 수집을 3번 돌렸다)"""
    conn = db.connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schedule_claims (slot TEXT PRIMARY KEY, claimed_at TEXT NOT NULL)")
            conn.execute("DELETE FROM schedule_claims WHERE claimed_at < ?", ((datetime.now() - timedelta(days=7)).isoformat(),))
            cur = conn.execute("INSERT OR IGNORE INTO schedule_claims (slot, claimed_at) VALUES (?, ?)",
                               (f"{key}@{minute_key}", datetime.now().isoformat(timespec="seconds")))
            return cur.rowcount == 1
    finally:
        conn.close()


def _fire_once(key: str, now: datetime) -> bool:
    """이번 분에 아직 실행하지 않았으면 기록하고 True (프로세스 안에서도, 프로세스끼리도 한 번)."""
    minute_key = now.strftime("%Y-%m-%d %H:%M")
    with _lock:
        if _last_fired.get(key) == minute_key or not _claim(key, minute_key):
            return False
        _last_fired[key] = minute_key
        _LAST_FIRED_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LAST_FIRED_FILE.write_text(json.dumps(_last_fired), encoding="utf-8")
        return True


def due_jobs(cfg: dict, now: datetime) -> list[str]:
    """지금 시각에 돌아야 할 작업 종류 목록 (테스트하기 쉽게 분리)."""
    hhmm = now.strftime("%H:%M")
    due = []
    for kind, key in (("collect", "collection"), ("draft", "drafting"), ("vectorize", "vectorize")):
        if cfg[key]["enabled"] and hhmm in cfg[key]["times"]:
            due.append(kind)
    for kind in ("weekly", "newsletter", "teams"):
        c = cfg[kind]
        if c["enabled"] and now.weekday() == int(c["weekday"]) and hhmm == c["time"]:
            due.append(kind)
    return due


def missed_weekly(cfg: dict, now: datetime) -> list[str]:
    """이번 주 예정 시각이 지났는데 이번 주 성공 기록이 없는 주간 작업 (PC가 꺼져 있었거나 앱이 내려가 있던 경우)."""
    out = []
    monday = (now - timedelta(days=now.weekday())).date()
    for kind in ("weekly", "newsletter", "teams"):
        c = cfg[kind]
        if not c["enabled"]:
            continue
        hh, mm = map(int, c["time"].split(":"))
        due_at = datetime.combine(monday + timedelta(days=int(c["weekday"])), datetime.min.time()).replace(hour=hh, minute=mm)
        if due_at + timedelta(minutes=5) <= now and not db.ran_ok_since(kind, due_at - timedelta(minutes=1)):
            out.append(kind)
    return out


def _tick() -> None:
    now = datetime.now()
    try:
        cfg = settings_store.load()
    except Exception:
        logger.exception("설정 읽기 실패")
        return
    db.set_meta("scheduler_tick", now.isoformat(timespec="seconds"))
    for kind in due_jobs(cfg, now):
        if _fire_once(kind, now):
            logger.info("스케줄 실행: %s", kind)
            jobs.start(kind, trigger="자동")
    # 놓친 주간 작업은 하루 한 번만 다시 시도한다 (실패가 반복될 때 계속 돌지 않게)
    for kind in missed_weekly(cfg, now):
        if _claim(f"catchup-{kind}", now.strftime("%Y-%m-%d")):
            logger.warning("놓친 주간 작업 따라잡기: %s", kind)
            jobs.start(kind, trigger="자동(놓친 작업)")


def _archive_housekeeping() -> None:
    """지난 날짜 기사 아카이브 확정 (AI_NEWS와 같은 상시 작업 — 시각 등록 없이 매 tick)."""
    from . import archiving
    try:
        done = archiving.archive_pending()
        if done:
            logger.info("데일리 아카이브 확정: %s", ", ".join(done))
    except Exception:
        logger.exception("아카이브 확정 오류")


def _purge_housekeeping() -> None:
    """하루 한 번(프로세스·재시작과 무관하게 DB에 기록): 보관 기간이 지난 기록 삭제 → 통계 갱신 → 백업."""
    global _purged_on
    today = datetime.now().date()
    if _purged_on == today:
        return
    _purged_on = today
    if not _claim("housekeeping", today.isoformat()):
        return  # 오늘 다른 프로세스(또는 재시작 전의 이 프로세스)가 이미 했다
    try:
        for name, n in db.purge_expired().items():
            if n:
                logger.info("보관 기간 지난 %s %d건 삭제", name, n)
    except Exception:
        logger.exception("보관 기간 정리 오류")
    try:
        db.optimize()
    except Exception:
        logger.exception("DB 통계 갱신 오류")
    try:
        p = db.backup(keep=14)
        logger.info("DB 백업: %s", p.name if p else "건너뜀 (오늘 백업 있음 또는 시험용 DB)")
    except Exception:
        logger.exception("DB 백업 오류")
        alerts.notify("DB 백업 실패", "data/logs 로그를 확인하세요.")


_purged_on = None


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception:
            logger.exception("스케줄러 tick 오류")
        _archive_housekeeping()
        _purge_housekeeping()
        time.sleep(_POLL_SECONDS)


def start_scheduler_thread() -> None:
    """앱 프로세스당 1회만 스레드를 시작한다 (Streamlit 재실행에도 중복 방지).
    AXREVIEW_SCHEDULER=1인 프로세스(start-public이 설정)만 시작한다 — 개발 서버·시험 서버가 같은 DB로 배치를 또 돌리지 않게.
    AXREVIEW_NO_SCHEDULER=1이면 어떤 경우에도 시작하지 않는다."""
    global _started
    if os.environ.get("AXREVIEW_NO_SCHEDULER") == "1" or os.environ.get("AXREVIEW_SCHEDULER") != "1":
        return
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, daemon=True, name="axreview-scheduler").start()
