"""운영 경보 — 작업 실패·경고, 백업 실패를 Teams 웹훅과 경보 메일로 알린다.

- Teams: 관리 > 구독·발송 > Teams에 등록한 웹훅 중 사용 중인 것 전부
- 메일: .env의 ALERT_EMAIL (SMTP 설정이 있을 때)
같은 내용은 하루 한 번만 보낸다(DB 기록) — 한도 소진처럼 수집 때마다 반복되는 경고가 쏟아지지 않게.
어느 쪽도 설정되지 않았으면 로그에만 남긴다. 경보 실패가 작업을 막지 않는다.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

from . import db

log = logging.getLogger("axreview.alerts")
LABELS = {"collect": "수집", "draft": "노트 초안", "weekly": "주간 흐름", "newsletter": "뉴스레터", "vectorize": "벡터화",
          "report": "주간 PDF", "teams": "Teams 발송", "warehouse": "Databricks 적재"}


def _once_today(key: str) -> bool:
    conn = db.connect()
    try:
        with conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schedule_claims (slot TEXT PRIMARY KEY, claimed_at TEXT NOT NULL)")
            return conn.execute("INSERT OR IGNORE INTO schedule_claims (slot, claimed_at) VALUES (?, ?)",
                                (f"alert:{key}@{datetime.now():%Y-%m-%d}", datetime.now().isoformat(timespec="seconds"))).rowcount == 1
    finally:
        conn.close()


def notify(title: str, body: str, key: str | None = None) -> None:
    """Teams·메일로 알린다. key가 같으면 하루 한 번만."""
    log.warning("[경보] %s — %s", title, body)
    if os.environ.get("AXREVIEW_DB"):
        return  # 시험용 DB로 돌 때는 보내지 않는다
    try:
        if not _once_today(key or title):
            return
        from . import mailer, notify as teams, settings_store
        site = mailer.site_url()
        for w in settings_store.load()["webhooks"]:
            if w.get("enabled", True):
                teams.post(w["url"], teams.build_alert_card(title, body, site), retries=0)
        to = os.environ.get("ALERT_EMAIL", "").strip()
        if to and mailer.is_configured():
            html = f"<p><b>{_esc(title)}</b></p><p>{_esc(body)}</p><p><a href='{site}/admin-ops'>운영 점검 열기</a></p>"
            mailer.send([(to, "")], f"[AX Review 경보] {title}", lambda _t: html)
    except Exception:  # noqa: BLE001 - 경보 실패가 본 작업을 막지 않게
        log.exception("경보 전송 실패")


def _esc(s: str) -> str:
    from html import escape
    return escape(s)


def job_failed(kind: str, trigger: str, message: str) -> None:
    notify(f"{LABELS.get(kind, kind)} 실패", f"{trigger} 실행 · {message or '자세한 내용은 관리 > 대시보드 작업 기록'}", key=f"fail:{kind}")


def job_warning(kind: str, message: str) -> None:
    notify(f"{LABELS.get(kind, kind)} 경고", message, key=f"warn:{kind}")
