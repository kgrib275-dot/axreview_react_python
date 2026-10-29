"""배치 작업 실행 로그 — 관리 화면 진행 상태 아래에 실시간으로 보여 준다.

작업 스레드(job-<kind>)가 남긴 logging 기록을 작업별 메모리 버퍼에 모은다. 작업 안에서 병렬로 도는
풀 스레드(채점·초안·임베딩)는 이름으로 작업을 알 수 없어서, 그때 돌고 있는 작업 모두에 붙인다.
버퍼는 다음 실행이 시작될 때까지 남겨 '마지막 실행 로그'로 볼 수 있다. URL의 key=… 값은 가린다.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import datetime

MAX_LINES = 400
_lock = threading.Lock()
_buffers: dict[str, deque] = {}
_running: set[str] = set()
_finished: dict[str, str] = {}  # kind -> 종료 시각
_SECRET_RE = re.compile(r"((?:key|token|secret)=)[^&\s\"']+", re.I)
_HTTP_RE = re.compile(r'HTTP Request: (\w+) (https?://[^\s?]+)\S* "HTTP/[\d.]+ (\d+[^"]*)"')
_QUIET = ("google_genai.models", "urllib3", "thrift", "databricks.sql")  # 너무 잘거나 내부적인 로거


def begin(kind: str) -> None:
    with _lock:
        _buffers[kind] = deque(maxlen=MAX_LINES)
        _running.add(kind)
        _finished.pop(kind, None)


def end(kind: str) -> None:
    with _lock:
        _running.discard(kind)
        _finished[kind] = datetime.now().strftime("%H:%M:%S")


def lines(kind: str) -> list[tuple[str, str, str]]:
    """[(시각, 레벨, 메시지)]."""
    with _lock:
        return list(_buffers.get(kind, ()))


def last_finished() -> tuple[str, str] | None:
    """가장 최근에 끝난 (작업, 종료 시각)."""
    with _lock:
        if not _finished:
            return None
        kind = max(_finished, key=_finished.get)
        return kind, _finished[kind]


def _message(record: logging.LogRecord) -> str:
    msg = record.getMessage()
    m = _HTTP_RE.search(msg)
    if m:  # httpx 요청 로그는 '메서드 주소 → 상태'로 줄인다 (쿼리 문자열 제외)
        msg = f"{m.group(1)} {m.group(2)} → {m.group(3)}"
    if record.exc_info and record.exc_info[1]:
        msg += f" ({type(record.exc_info[1]).__name__}: {record.exc_info[1]})"
    return _SECRET_RE.sub(r"\1***", msg)[:400]


class _Handler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(_QUIET):
            return
        name = threading.current_thread().name
        with _lock:
            kinds = [name[4:]] if name.startswith("job-") and name[4:] in _running else list(_running)
            if not kinds:
                return
            line = (datetime.fromtimestamp(record.created).strftime("%H:%M:%S"), record.levelname, _message(record))
            for k in kinds:
                _buffers.setdefault(k, deque(maxlen=MAX_LINES)).append(line)


_handler = _Handler(level=logging.INFO)


def install() -> None:
    root = logging.getLogger()
    if _handler not in root.handlers:
        root.addHandler(_handler)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
