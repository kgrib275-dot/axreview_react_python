"""라우터 공용 — 노트 카드 직렬화, 마크다운 → HTML, 쿼리 문자열 목록 파싱, 공유 캐시."""
from __future__ import annotations

import threading
import time

from app.web import md_html  # 노트 본문 형식(### 제목, 목록, **굵게**)만 HTML 로 — 이스케이프 포함
from pipeline import industry

CARD_KEYS = ("id", "title", "category", "kind", "summary", "published", "source", "tags", "audiences", "url")


def note_card(n: dict, **extra) -> dict:
    out = {k: n.get(k) for k in CARD_KEYS}
    out["industries"] = industry.of(n)
    out.update(extra)
    return out


def csv_list(raw: str | None) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


_cache: dict = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def cached(key: str, fn, ttl: float):
    """모든 방문자가 같은 값을 ttl 초 동안 나눠 쓴다.

    만료된 순간 동시에 들어온 요청이 모두 같은 계산을 하지 않게 한 요청만 다시 계산한다 (1만 명 복사본 실측: 오늘의 AX
    빈 캐시 + 동시 20명 → 24초). 그동안 다른 요청은 직전 값이 있으면 그걸 바로 받고, 없으면(처음) 계산이 끝나길 기다린다."""
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < ttl:
        return hit[1]
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    if hit and not lock.acquire(blocking=False):
        return hit[1]  # 다른 요청이 다시 계산하는 중 — 직전 값
    if not hit:
        lock.acquire()
    try:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        val = fn()
        _cache[key] = (time.monotonic(), val)
        return val
    finally:
        lock.release()


__all__ = ["md_html", "note_card", "csv_list", "cached"]
