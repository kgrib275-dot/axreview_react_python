"""관리 화면에서 바꾸는 운영 설정 (data/settings.json).

AI_NEWS는 설정마다 JSON 파일을 따로 뒀지만, 여기서는 한 파일에 섹션으로 모은다.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from copy import deepcopy

from .db import ROOT

SETTINGS_FILE = ROOT / "data" / "settings.json"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

DEFAULTS = {
    "enabled_sources": None,  # None = config/sources.yaml의 전체 소스
    # 무료 Gemini는 키당 하루 약 20회 — 수집(채점)은 하루 3~4번이면 충분하다. 17:30은 한도가 풀린(태평양 자정) 뒤.
    "collection": {"enabled": False, "times": ["08:00", "11:00", "14:00", "17:30"]},
    "drafting": {"enabled": False, "times": ["07:30", "13:30"], "per_run": 5, "min_score": 4},
    "weekly": {"enabled": False, "weekday": 0, "time": "08:00", "auto_publish": False},
    "newsletter": {"enabled": False, "weekday": 0, "time": "09:00"},
    "vectorize": {"enabled": False, "times": ["08:00", "14:00"]},
    "teams": {"enabled": False, "weekday": 0, "time": "09:30"},
    "webhooks": [],  # [{"id", "name", "url", "enabled"}]
    # 공개 'AX 질문하기' — 인터넷에 공개되므로 Gemini 호출 남용을 막는 한도를 둔다.
    # free_credits: 뉴스레터 구독자가 가입(확인) 때 한 번 받는 무료 질문 횟수 — 다 쓰면 관리자가 충전(관리 > 구독·발송 > 구독자).
    # free_daily: 예전 '무료 방문자 하루 질문 수' — 구독자 횟수제로 바뀌어 한도에는 더 쓰지 않는다 (저장된 설정 호환용으로만 남김).
    # member_daily: 월 구독자(코드) 하루 질문 수 (pipeline/membership.py).
    # per_ip_daily는 구독 횟수제 밖의 남용 상한 (쿠키를 지워도 IP 로 묶임, 월 구독자 제외), global_daily 는 전체 합계.
    "ask": {"enabled": True, "free_credits": 3, "free_daily": 3, "member_daily": 30, "per_ip_daily": 10, "global_daily": 40,
            "web_search": True, "plan_price": ""},
    # 편집 관점 (pipeline/editorial.py) — '리더가 알아야 할 3가지' 선정과 본문 색 강조에 쓴다.
    "lens": {"stance": "현업 리더가 이번 주 바로 움직일 수 있는 것만 고릅니다.",
             "focus": ["에이전트", "보안", "거버넌스", "데이터", "비용", "온톨로지"],
             "industries": ["제조", "금융", "고객센터", "IT 서비스"], "audience": "현업 리더"},
    "admin_ips": [],
    # AI 모델 (관리 > AI 모델 설정) — provider: gemini|claude. Claude 키는 data/llm_keys.json (pipeline/claude_llm.py)
    "llm": {"provider": "gemini", "claude_model": "claude-opus-5-5"},
    "warehouse": {"auto_sync": True},
    "engage": {"sample_on_map": True},  # 공개 참여 지도에 예시(가상) 데이터를 함께 보여 줄지 (배지로 표시)  # Databricks 설정이 있으면 수집·초안·주간 흐름·발송 뒤 자동 적재
}

_lock = threading.RLock()
_cache: dict = {}  # 파일 경로 → (mtime_ns, size, 저장된 dict) — 요청마다(관리자 판정) 파일을 읽고 파싱하지 않게


def _saved(strict: bool = False) -> dict:
    """settings.json 내용. 바뀌지 않았으면 메모리 사본을 쓴다.

    쓰는 도중의 파일(다른 프로세스)을 읽어 깨진 JSON 이 나오면 마지막으로 제대로 읽은 값을 쓴다 — 예전엔 기본값으로
    떨어져 스케줄이 꺼진 것처럼 보이거나, 저장할 때 관리자 IP·웹훅이 지워질 수 있었다. strict 면 그 대신 예외."""
    key = str(SETTINGS_FILE)
    try:
        st = SETTINGS_FILE.stat()
    except FileNotFoundError:
        return {}
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    for attempt in range(3):
        try:
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if not isinstance(saved, dict):
                raise ValueError("settings.json 이 객체가 아닙니다")
            _cache[key] = (st.st_mtime_ns, st.st_size, saved)
            return saved
        except (json.JSONDecodeError, ValueError, OSError):
            time.sleep(0.05 * (attempt + 1))
            try:
                st = SETTINGS_FILE.stat()
            except FileNotFoundError:
                return {}
    if strict:
        raise RuntimeError("settings.json 을 읽지 못했습니다 — 저장을 멈춥니다 (다른 설정을 덮어쓰지 않게)")
    return hit[2] if hit else {}


_merged: dict = {}


def load() -> dict:
    """기본값 + 저장값. 요청마다 3~7번 불려 매번 합치고 깊은 복사하던 것을 파일이 바뀔 때만 합친다.
    부르는 쪽이 고쳐도 원본이 바뀌지 않게 돌려줄 때는 복사본 (구역 단위 얕은 복사 + 목록 복사)."""
    saved = _saved()
    if _merged.get("src") is not saved:
        cfg = deepcopy(DEFAULTS)
        for key, val in deepcopy(saved).items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(val)
            else:
                cfg[key] = val
        _merged.update(src=saved, cfg=cfg)
    return deepcopy(_merged["cfg"])


def _write(cfg: dict) -> None:
    """임시 파일에 쓴 뒤 바꿔 끼운다 — 읽는 쪽이 반쯤 쓰인 파일을 보지 않게."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_name(f"{SETTINGS_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(tmp, SETTINGS_FILE)
            return
        except PermissionError:  # Windows: 다른 프로세스가 마침 읽는 중
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, SETTINGS_FILE)


def save_section(key: str, value) -> None:
    with _lock:
        _saved(strict=True)  # 못 읽으면 저장하지 않는다
        cfg = load()
        cfg[key] = value
        _write(cfg)


def update_section(key: str, fn) -> None:
    """읽고-바꾸고-저장을 한 잠금 안에서 — 두 요청이 동시에 목록에 추가해도 한쪽이 사라지지 않게."""
    with _lock:
        save_section(key, fn(deepcopy(load()[key])))


def enabled_sources(all_names: list[str]) -> list[str]:
    names = load()["enabled_sources"]
    return all_names if names is None else [n for n in names if n in all_names]


def parse_times(raw: str) -> tuple[list[str], list[str]]:
    """'/'로 구분된 HH:MM 문자열을 파싱한다. (유효한 시각 목록, 잘못된 입력 목록)을 반환."""
    valid, invalid = [], []
    for part in raw.split("/"):
        t = part.strip()
        if not t:
            continue
        if TIME_RE.match(t):
            if t not in valid:
                valid.append(t)
        else:
            invalid.append(t)
    return sorted(valid), invalid


# ───────────── 관리자 IP (AI_NEWS와 같은 방식) ─────────────

LOCAL_IPS = {None, "", "127.0.0.1", "::1", "localhost"}


def add_admin_ip(label: str, ip: str) -> None:
    update_section("admin_ips", lambda admins: admins + [{"id": uuid.uuid4().hex, "label": label, "ip": ip}])


def delete_admin_ip(admin_id: str) -> None:
    update_section("admin_ips", lambda admins: [a for a in admins if a["id"] != admin_id])


def is_admin_ip(ip: str | None) -> bool:
    """로컬 접속은 항상 관리자다. 원격은 등록된 IP만 통과한다 — AI_NEWS는 목록이 비면
    누구나 통과시켰지만, 사내망에 띄우는 사이트라 원격 부트스트랩은 막았다."""
    if ip in LOCAL_IPS:
        return True
    return any(a["ip"] == ip for a in load()["admin_ips"])


_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-forwarded-host", "tailscale-funnel-request")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def client_ip(ip: str | None, headers: dict[str, str]) -> tuple[str | None, bool]:
    """(실제 접속자 IP, 프록시 경유 여부).

    Tailscale Funnel로 공개하면 모든 요청이 로컬 프록시(127.0.0.1)에서 들어온다. 그대로
    is_admin_ip에 넣으면 인터넷의 누구나 관리자가 되므로, 프록시 헤더가 있거나 Host가
    localhost가 아니면 원격 요청으로 보고 X-Forwarded-For의 마지막 IP(프록시가 붙인 값)를 쓴다.
    """
    lower = {k.lower(): v for k, v in headers.items()}
    raw_host = lower.get("host", "")
    # "[::1]:4002" 같은 IPv6 표기는 대괄호까지가 호스트다.
    host = raw_host[: raw_host.find("]") + 1] if raw_host.startswith("[") else raw_host.rsplit(":", 1)[0]
    if ip and ip not in _LOOPBACK:
        # 로컬 프록시를 거치지 않고 직접 붙은 요청(같은 네트워크 등) — 보낸 헤더는 위조할 수 있으니 실제 접속 IP만 쓴다.
        return ip, True
    proxied = any(h in lower for h in _PROXY_HEADERS) or host not in _LOCAL_HOSTS
    if not proxied:
        return ip, False
    # 접속자가 보낸 X-Forwarded-For 뒤에 프록시가 실제 IP를 덧붙이므로 마지막 값만 믿는다 (앞쪽은 위조 가능).
    forwarded = lower.get("x-forwarded-for", "").split(",")[-1].strip()
    return forwarded or None, True


def is_admin_request(ip: str | None, headers: dict[str, str]) -> bool:
    real_ip, proxied = client_ip(ip, headers)
    if proxied:
        # 프록시 경유 요청은 "로컬"로 취급하지 않는다 — 등록된 IP만 관리자.
        return bool(real_ip) and any(a["ip"] == real_ip for a in load()["admin_ips"])
    return is_admin_ip(real_ip)


# ───────────── Teams 웹훅 (AI_NEWS settings_store와 같은 방식) ─────────────

WEBHOOK_HOSTS = (".webhook.office.com", ".logic.azure.com", ".powerplatform.com", ".powerautomate.com")


def webhook_url_ok(url: str) -> bool:
    """Teams(Power Automate·Logic Apps) 웹훅 주소만 허용 — 임의 주소로 서버가 요청을 보내지 않게."""
    from urllib.parse import urlsplit
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host.endswith(h) for h in WEBHOOK_HOSTS)


def add_webhook(name: str, url: str) -> None:
    if not webhook_url_ok(url):
        raise ValueError("Teams 웹훅 주소(https://…webhook.office.com 등)만 등록할 수 있습니다.")
    update_section("webhooks", lambda hooks: hooks + [{"id": uuid.uuid4().hex, "name": name, "url": url, "enabled": True}])


def update_webhook(webhook_id: str, **fields) -> None:
    def change(hooks):
        for w in hooks:
            if w["id"] == webhook_id:
                w.update(fields)
        return hooks
    update_section("webhooks", change)


def delete_webhook(webhook_id: str) -> None:
    update_section("webhooks", lambda hooks: [w for w in hooks if w["id"] != webhook_id])
