"""관리 > 운영 점검 — 공개 운영에 필요한 항목을 자동으로 점검한 행 목록 + 지금 백업 (app_pages/admin/ops.py).

포트는 FastAPI 판 기준: 개발 5002, 공개(start-public.ps1) 5012~ . 건강 확인은 /robots.txt (app/web.py).
"""
from __future__ import annotations

import ctypes
import os
import shutil
import socket
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import db, engage, gemini_keys, jobs, mailer, membership, privacy, scheduler, settings_store, warehouse

router = APIRouter(prefix="/admin/ops", tags=["admin-ops"], dependencies=[Depends(require_admin)])

OK, WARN, BAD = "ok", "warn", "bad"
_ICON = {OK: "🟢", WARN: "🟡", BAD: "🔴"}
DEV_PORT = 5002
PUBLIC_PORTS = list(range(5012, 5020))


def _free_ram_gb() -> float | None:
    class MEM(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    try:
        m = MEM(); m.dwLength = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / 1024 ** 3
    except Exception:  # noqa: BLE001 - 윈도우가 아니면 건너뛴다
        return None


def _listening(port: int) -> bool:
    # 윈도우는 닫힌 포트에 HTTP로 붙으면 거절까지 수 초가 걸려(실측) 짧은 소켓 검사로 먼저 거른다.
    with socket.socket() as sk:
        sk.settimeout(.15)
        return sk.connect_ex(("127.0.0.1", port)) == 0


def _healthy(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/robots.txt", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def _rows() -> list[dict]:
    rows: list[dict] = []

    def add(area: str, item: str, status: str, detail: str, action: str = "") -> None:
        rows.append({"status": status, "icon": _ICON[status], "area": area, "item": item, "detail": detail, "action": action})

    cfg = settings_store.load()
    conn = db.connect()
    try:
        # ---------- 공개 서버 ----------
        ports = [DEV_PORT, *PUBLIC_PORTS]
        with ThreadPoolExecutor(len(ports)) as pool:
            listening = [p for p, ok in zip(ports, pool.map(_listening, ports)) if ok]
        public = next((p for p in listening if p != DEV_PORT and _healthy(p)), None)
        add("공개", "공개 서버 (start-public)", OK if public else BAD,
            f"127.0.0.1:{public} 응답" if public else f"{PUBLIC_PORTS[0]}~{PUBLIC_PORTS[-1]}에서 응답 없음",
            "" if public else "start-public.bat 실행 — 창을 닫거나 PC가 절전되면 공개 주소가 멈춥니다")
        add("공개", "동시에 떠 있는 서버", OK if len(listening) <= 1 else WARN,
            f"{len(listening)}개 ({', '.join(map(str, listening)) or '-'})",
            "" if len(listening) <= 1 else f"개발 서버({DEV_PORT})는 배치를 돌리지 않지만 같은 DB를 씁니다 — 쓰지 않으면 끄세요")
        tick = db.get_meta("scheduler_tick")
        tick_age = (datetime.now() - datetime.fromisoformat(tick)).total_seconds() if tick else None
        add("배치", "스케줄러 동작", OK if tick_age is not None and tick_age < 120 else BAD,
            f"마지막 확인 {tick} ({int(tick_age)}초 전)" if tick else "기록 없음",
            "" if tick_age is not None and tick_age < 120 else "공개 서버(start-public)에서만 돕니다 — 공개 서버가 떠 있는지 확인")
        missed = scheduler.missed_weekly(cfg, datetime.now())
        add("배치", "놓친 주간 작업", OK if not missed else WARN, ", ".join(missed) or "없음",
            "스케줄러가 하루 한 번 다시 시도합니다 (관리 > 대시보드에서 바로 실행 가능)" if missed else "")
        add("공개", "PC 절전·재부팅", WARN, "이 PC가 서버입니다",
            "전원 옵션에서 '절전 안 함', 재부팅 후 start-public.bat 다시 실행 (Funnel 창이 닫히면 공개 주소도 꺼짐)")
        site = mailer.site_url()
        add("공개", "SITE_URL (메일 링크 주소)", OK if site.startswith("https://") else WARN, site,
            "" if site.startswith("https://") else "공개 주소로 실행하면 자동 설정됩니다 (start-public)")

        # ---------- 배치 ----------
        on = [n for k, n in (("collection", "수집"), ("drafting", "초안"), ("weekly", "주간 흐름"), ("newsletter", "뉴스레터"),
                             ("vectorize", "벡터화"), ("teams", "Teams")) if cfg[k]["enabled"]]
        add("배치", "자동 스케줄", OK if "수집" in on else WARN, ", ".join(on) or "모두 꺼짐",
            "" if "수집" in on else "관리 > 배치 스케줄에서 수집을 켜야 트렌드·퀴즈가 매일 바뀝니다")
        last = conn.execute("SELECT started_at, ok FROM run_logs WHERE kind='collect' ORDER BY id DESC LIMIT 1").fetchone()
        if last:
            age = datetime.now() - datetime.fromisoformat(last["started_at"])
            add("배치", "마지막 수집", OK if last["ok"] and age < timedelta(days=1) else WARN,
                f"{last['started_at']} · {'성공' if last['ok'] else '일부 실패'}", "" if age < timedelta(days=1) else "하루 넘게 수집이 없습니다")
        fails = conn.execute("SELECT COUNT(*) FROM run_logs WHERE ok=0 AND started_at >= ?",
                             ((datetime.now() - timedelta(days=1)).isoformat(),)).fetchone()[0]
        add("배치", "최근 24시간 실패 작업", OK if not fails else WARN, f"{fails}건", "관리 > 대시보드 실행 기록 확인" if fails else "")

        # ---------- AI ----------
        model = jobs.config()["pipeline"]["gemini"].get("model", "gemini-2.5-flash")
        keys = len(gemini_keys.all_keys())
        healthy = gemini_keys.healthy_count(model)
        add("AI", "Gemini 키", BAD if not keys else (WARN if gemini_keys.exhausted_today(model) else OK),
            f"{keys}개 중 정상 {healthy}개 (무료 등급: 키당 하루 약 20회)",
            "한도 소진 시 질문하기는 관련 자료 목록으로 대신 답합니다. 사용량이 늘면 유료 등급 검토" if keys else ".env에 GEMINI_API_KEYS")
        ask = cfg["ask"]
        add("AI", "질문하기 한도", OK if ask.get("global_daily", 40) <= 60 else WARN,
            f"무료 {ask['free_daily']}회 · 월 구독 {ask['member_daily']}회 · 무료 IP {ask['per_ip_daily']}회 · "
            f"전체 {ask.get('global_daily', 40)}회 / 일 · 활성 월 구독 {membership.active_count()}명",
            "" if ask.get("global_daily", 40) <= 60 else "질문 1건에 Gemini 1~3회 — 무료 키 한도(키당 하루 약 20회)에 비해 큽니다")
        unscored = len(db.unscored_articles(14))
        add("AI", "미채점 기사 (14일)", OK if unscored < 50 else (WARN if unscored < 300 else BAD), f"{unscored}건",
            "" if unscored < 50 else "Gemini 한도 소진 — 다음 수집 때 한 요청에 묶어 다시 채점합니다. 계속 쌓이면 키 추가·유료 등급 검토")

        # ---------- 발송 ----------
        subs = conn.execute("SELECT COUNT(*) FROM subscribers WHERE active=1 AND confirmed_at IS NOT NULL").fetchone()[0]
        add("발송", "SMTP (뉴스레터)", OK if mailer.is_configured() else (BAD if subs else WARN),
            f"{'설정됨' if mailer.is_configured() else '미설정'} · 활성 구독자 {subs}명",
            "" if mailer.is_configured() else ".env SMTP_* 설정 — 구독을 받는데 메일을 보낼 수 없는 상태")
        pend = len(db.pending_confirmations())
        add("발송", "구독 이중 확인", OK if mailer.is_configured() else WARN, f"사용 중 · 확인 대기 {pend}명",
            "" if mailer.is_configured() else "SMTP가 없어 확인 메일을 못 보냅니다 — 설정 후 관리 > 구독·발송 > '확인 메일 보내기'")
        alert_ok = bool([w for w in cfg["webhooks"] if w.get("enabled", True)]) or bool(os.environ.get("ALERT_EMAIL") and mailer.is_configured())
        add("발송", "장애 경보 통로", OK if alert_ok else WARN, "Teams 웹훅·ALERT_EMAIL" if alert_ok else "없음",
            "" if alert_ok else "작업 실패·백업 실패를 받으려면 Teams 웹훅을 등록하거나 .env에 ALERT_EMAIL(+SMTP)을 넣으세요")
        add("발송", "Teams 웹훅", OK if cfg["webhooks"] else WARN, f"{len(cfg['webhooks'])}개", "" if cfg["webhooks"] else "관리 > 구독·발송")

        # ---------- 데이터 ----------
        b = db.last_backup()
        fresh = b and datetime.now() - datetime.fromisoformat(b[0]) < timedelta(hours=36)
        bad = list(db.BACKUP_DIR.glob("*.bad")) if db.BACKUP_DIR.exists() else []
        add("데이터", "DB 자동 백업", BAD if bad else (OK if fresh else BAD),
            (f"무결성 검사 실패 백업 {len(bad)}개 · " if bad else "") + (f"마지막 {b[0]} · {b[1] // 1024}KB (무결성 검사 통과)" if b else "백업 없음"),
            "DB 파일 상태를 확인하세요 (README '백업·복원')" if bad else ("" if fresh else "아래 '지금 백업' — 이후 매일 자동 (data/backups, 14일치)"))
        add("데이터", "백업 보관 위치", WARN, "같은 PC의 data/backups", "PC 고장에 대비해 주 1회 다른 저장소(사내 드라이브 등)로 복사 권장")
        db_mb = db.DB_PATH.stat().st_size / 1024 ** 2
        add("데이터", "DB 크기", OK if db_mb < 500 else WARN, f"{db_mb:.1f}MB")
        sample = engage.sample_count()
        show = cfg["engage"]["sample_on_map"]
        add("데이터", "예시(가상) 참여 데이터", OK if not sample else (WARN if show else OK),
            f"{sample}건 · 공개 지도 {'표시' if show else '숨김'}", "정식 오픈 전 '참여 분석 > 예시 데이터 모두 지우기' 권장" if sample else "")
        add("데이터", "Databricks 적재", OK if warehouse.is_configured() else WARN, f"마지막 {warehouse.last_synced()}",
            "Trade_IQ와 같은 개인 계정 토큰 사용 중 — 회사 공용 계정·전용 토큰으로 바꾸는 것을 권장")

        # ---------- 보안·개인정보 ----------
        add("보안", "오류 상세 숨김", OK, "처리되지 않은 오류는 일반 문구만 응답 (api/main.py — 공개 사용자에게 경로·소스 비노출)")
        admins = cfg["admin_ips"]
        add("보안", "공개 주소 관리자 IP", OK if not admins else WARN, f"{len(admins)}개 등록",
            "회사 공용 IP를 등록하면 같은 망 전체가 관리자 — 꼭 필요한 개인 IP만" if admins else "공개 주소에서는 관리 메뉴 숨김")
        add("보안", "관리 API 토큰", OK if os.environ.get("ADMIN_TOKEN", "").strip() else WARN,
            "설정됨" if os.environ.get("ADMIN_TOKEN", "").strip() else "없음 — 로컬·등록 IP 판정만 사용",
            "" if os.environ.get("ADMIN_TOKEN", "").strip() else "원격에서 관리 화면을 쓰려면 .env ADMIN_TOKEN")
        add("보안", "접속 기록(IP) 보관", OK, "90일 후 자동 삭제")
        need = privacy.missing()
        add("보안", "개인정보 처리방침 필수 기재사항", BAD if need else OK, ("빠짐: " + ", ".join(need)) if need else "모두 입력됨",
            "관리 > 개인정보 처리방침에서 입력 (시행 전 담당 부서 검토)" if need else "")
        pv = privacy.current()
        add("보안", "개인정보 처리방침 공지", BAD if not pv else (WARN if privacy.outdated() else OK),
            f"{pv['effective_date']} 시행본 · 공지 {len(privacy.versions())}개" if pv else "공지한 버전 없음 (초안 표시 중)",
            "관리 > 개인정보 처리방침에서 공지" if not pv else ("기능·설정이 최근 공지와 다름 — 새 버전 공지" if privacy.outdated() else ""))

        # ---------- 서버 자원 ----------
        disk = shutil.disk_usage(db.ROOT)
        add("자원", "디스크 여유", OK if disk.free > 5 * 1024 ** 3 else BAD, f"{disk.free / 1024 ** 3:.0f}GB")
        ram = _free_ram_gb()
        if ram is not None:
            add("자원", "메모리 여유", OK if ram > 2 else WARN, f"{ram:.1f}GB", "" if ram > 2 else "다른 프로그램을 닫거나 개발 서버를 끄세요")
        logs = sorted((db.ROOT / "data" / "logs").glob("axreview-*.log"))
        add("자원", "로그 파일", OK if logs else WARN, " · ".join(f"{p.name} {p.stat().st_size // 1024}KB" for p in logs) or "아직 없음",
            "서버(포트)별 · 5MB × 5개 순환 보관")
    finally:
        conn.close()
    order = {BAD: 0, WARN: 1, OK: 2}
    rows.sort(key=lambda r: order[r["status"]])  # 안정 정렬 — 같은 상태 안에서는 점검 순서 유지
    return rows


@router.get("")
def ops() -> dict:
    rows = _rows()
    return {"rows": rows, "counts": {s: sum(1 for r in rows if r["status"] == s) for s in (BAD, WARN, OK)},
            "checked_at": datetime.now().isoformat(timespec="seconds")}


@router.post("/backup")
def backup(request: Request) -> dict:
    try:
        p = db.backup(force=True)
    except RuntimeError as e:  # 무결성 검사 실패
        raise HTTPException(500, str(e))
    if not p:
        raise HTTPException(400, "백업을 만들지 못했습니다")
    log_action(request, "DB 백업", p.name)
    return {"ok": True, "file": p.name, "bytes": p.stat().st_size}
