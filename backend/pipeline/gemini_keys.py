"""Gemini API 키 풀 — 여러 키(각각 다른 프로젝트)를 병렬로 나눠 쓴다.

무료 등급은 '프로젝트·모델별 하루 요청 수'가 작다(2026-10-27 실측: gemini-2.5-flash 20회/일,
키 6개는 서로 다른 프로젝트라 한도도 따로). AI_NEWS처럼 한 키를 실패할 때까지 쓰면 앞쪽 키부터
차례로 소진되고 나머지는 논다. 그래서 프로세스 전체가 (키, 모델)별 상태를 공유하며
  - 호출마다 정상 키를 라운드로빈으로 배정하고
  - 401(무효 키)은 모든 모델에서 제외,
  - 429 하루 한도(PerDay)는 그 모델만 자정까지, 분당 한도는 60초 동안 쉬게 한다.
병렬 작업 수는 healthy_count(model)로 정한다 — 키 하나에 동시 요청이 몰리지 않게.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta

_lock = threading.Lock()
_invalid: dict[str, str] = {}  # key -> 오류
_state: dict[tuple[str, str], dict] = {}  # (model, key) -> {"status", "until", "calls", "last_error"}
_cursor = 0
_LABELS = {"ok": "정상", "daily": "오늘 한도 소진", "minute": "분당 제한 대기"}


def all_keys() -> list[str]:
    return [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]


def client(key: str):
    """SDK 자체 재시도를 끈 클라이언트 — 429면 같은 키로 기다리지 말고 바로 다른 키로 넘긴다.
    반환값은 호출하는 동안 지역 변수로 잡아 둬야 한다(가비지 수집되면 연결이 닫힘, 실측)."""
    from google import genai
    from google.genai import types
    return genai.Client(api_key=key, http_options=types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=1)))


def _entry(model: str, key: str) -> dict:
    return _state.setdefault((model, key), {"status": "ok", "until": 0.0, "calls": 0, "last_error": ""})


def _available(model: str, key: str, now: float) -> bool:
    if key in _invalid:
        return False
    e = _entry(model, key)
    if e["status"] != "ok" and now < e["until"]:
        return False
    e["status"] = "ok"  # 쉬는 시간이 지나면 복귀
    return True


def healthy_keys(model: str) -> list[str]:
    """지금 이 모델에 쓸 수 있는 키 — 라운드로빈 시작점부터 (호출마다 시작점이 한 칸씩 이동)."""
    global _cursor
    keys = all_keys()
    if not keys:
        return []
    now = time.time()
    with _lock:
        # 정상 키만 놓고 돌려야 고르게 나뉜다 — 전체 키 기준으로 돌리면 소진 키 바로 다음
        # 키에 호출이 몰린다(시뮬레이션으로 확인).
        healthy = [k for k in keys if _available(model, k, now)]
        if not healthy:
            return []
        start = _cursor % len(healthy)
        _cursor += 1
        return healthy[start:] + healthy[:start]


def healthy_count(model: str) -> int:
    now = time.time()
    with _lock:
        return sum(_available(model, k, now) for k in all_keys())


def _next_quota_reset() -> float:
    """Gemini 일일 한도가 풀리는 시각 = 미국 태평양 시간 자정 (한국 16~17시, 서머타임에 따라). 한국 자정까지 쉬면
    오후에 풀린 한도를 반나절 동안 못 쓴다."""
    from zoneinfo import ZoneInfo
    pt = datetime.now(ZoneInfo("America/Los_Angeles"))
    return datetime.combine(pt.date() + timedelta(days=1), datetime.min.time(), tzinfo=pt.tzinfo).timestamp()


def report_success(model: str, key: str) -> None:
    with _lock:
        _entry(model, key)["calls"] += 1


def report_error(model: str, key: str, exc: Exception) -> str:
    """오류를 분류(invalid/daily/minute/other)해 키를 쉬게 한다."""
    msg = str(exc)
    with _lock:
        e = _entry(model, key)
        e["last_error"] = msg[:200]
        if msg.startswith("401") or "API key not valid" in msg or "API_KEY_INVALID" in msg:
            _invalid[key] = msg[:200]
            return "invalid"
        if msg.startswith("429") or "RESOURCE_EXHAUSTED" in msg:
            if "PerDay" in msg:
                e["status"], e["until"] = "daily", _next_quota_reset()
                return "daily"
            e["status"], e["until"] = "minute", time.time() + 60
            return "minute"
    return "other"


def exhausted_today(model: str) -> bool:
    """모든 키가 무효이거나 오늘 한도를 다 썼으면 True (기다려도 소용없음)."""
    keys = all_keys()
    now = time.time()
    with _lock:
        return bool(keys) and all(
            k in _invalid or (_entry(model, k)["status"] == "daily" and now < _entry(model, k)["until"])
            for k in keys
        )


def status_rows(models: list[str]) -> list[dict]:
    """관리 화면용 (키 값은 끝 4자리만)."""
    now = time.time()
    rows = []
    with _lock:
        for i, k in enumerate(all_keys()):
            row = {"키": f"#{i} …{k[-4:]}"}
            calls = 0
            for m in models:
                if k in _invalid:
                    row[m] = "무효 키"
                else:
                    _available(m, k, now)
                    row[m] = _LABELS[_entry(m, k)["status"]]
                calls += _entry(m, k)["calls"]
            row["이번 실행 호출 수"] = calls
            rows.append(row)
    return rows
