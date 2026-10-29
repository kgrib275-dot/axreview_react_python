"""개인정보 처리방침 내용 — 지금 켜져 있는 기능에서 실제로 처리하는 개인정보만 모아 만든다.

개인정보 보호법 제30조·시행령 제31조의 기재사항(처리 목적·항목·보유 기간, 파기, 제3자 제공, 위탁, 국외 이전,
정보주체 권리, 안전성 확보 조치, 자동 수집 장치, 보호책임자, 열람청구 부서, 구제 방법, 변경 사항)을 채우는 데 쓴다.
- 처리하는 개인정보가 하나도 없으면 active()가 False → 처리방침 페이지·링크를 아예 표시하지 않는다.
- 보호책임자·운영자 명칭처럼 코드가 알 수 없는 값은 관리 > 개인정보 처리방침에서 입력한다(missing()이 빈 값을 알려 줌).
- 버전 관리: 관리자가 '공지'하면 그때의 내용(snapshot)을 시행일·공지일과 함께 privacy_versions에 고정해 둔다.
  공개 화면은 날짜별로 골라 볼 수 있고, 기본은 지금 시행 중인 버전. 공지한 뒤 기능이 바뀌면 outdated()가 True.
- 기능을 추가·변경하면 여기의 records()/entrustments()/overseas()도 같이 고친다.
법률 검토를 대신하지 않는다 — 시행 전 담당 부서(법무·개인정보) 검토를 받는다.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime

from . import db, settings_store

DEFAULTS = {
    "operator": "",          # 개인정보처리자 명칭 (사이트 운영 주체)
    "officer_name": "",      # 개인정보 보호책임자 성명 (또는 직책)
    "officer_dept": "",      # 부서
    "officer_email": "",     # 연락처 (이메일)
    "officer_phone": "",     # 연락처 (전화, 선택)
    "request_dept": "",      # 열람청구 접수·처리 부서 (비우면 보호책임자와 같음)
    "smtp_vendor": "",       # 메일 발송 위탁 업체 이름 (SMTP 사업자)
    "smtp_country": "대한민국",  # 그 업체의 처리 국가 (국외면 국외 이전으로 표시)
    "databricks_region": "미국",  # Databricks 저장 지역
    "admin_measures": "",    # 관리적 보호조치(내부관리계획·교육 등) — 실제로 하는 것만
}
REQUIRED = {"operator": "개인정보처리자(운영자) 명칭", "officer_name": "개인정보 보호책임자 성명 또는 직책",
            "officer_email": "보호책임자 연락처(이메일)"}
NOTICE_DAYS, MAJOR_NOTICE_DAYS = 7, 30  # 시행 전 공지 기간 (정보주체 권리에 중요한 변경은 30일)


def settings() -> dict:
    return {**DEFAULTS, **(settings_store.load().get("privacy") or {})}


def missing() -> list[str]:
    s = settings()
    return [label for k, label in REQUIRED.items() if not str(s.get(k, "")).strip()]


def _features() -> dict:
    from . import mailer, warehouse
    cfg = settings_store.load()
    return {
        "ask": cfg["ask"]["enabled"] and bool(os.environ.get("GEMINI_API_KEYS")),
        "smtp": mailer.is_configured(),
        "databricks": warehouse.is_configured(),
        "kakao": bool(os.environ.get("KAKAO_JS_KEY")),
    }


def records() -> list[dict]:
    """처리 업무별 (업무, 목적, 필수 항목, 선택 항목, 자동 생성 항목, 보유 기간)."""
    R = db.RETENTION_DAYS
    f = _features()
    out = [
        {"name": "뉴스레터 구독", "purpose": "주간 뉴스레터 발송, 구독 신청 확인, 업종별 노트 우선 발송, 추천 보상 제공",
         "required": "이메일", "optional": "관심 업종",
         "auto": "신청·확인·해지 일시, 추천 코드, 추천인(추천 링크로 구독한 경우)",
         "keep": f"구독 해지 시까지 (해지 후 {R['unsubscribed']}일 이내 파기) · 확인하지 않은 신청은 {R['unconfirmed']}일 후 파기"},
        {"name": "문의 접수", "purpose": "문의 확인 및 답변", "required": "이름, 이메일, 문의 내용", "optional": "부서·직책",
         "auto": "접수 일시", "keep": f"접수 후 {R['contacts'] // 30}개월"},
    ]
    if f["ask"]:
        out.append({"name": "월 구독 신청·이용 (AX 질문하기)", "purpose": "월 구독 안내, 구독 코드 발급, 하루 이용 한도 관리",
                    "required": "이름, 이메일", "optional": "부서·직책",
                    "auto": "이용 기간, 구독 코드(복원할 수 없는 해시로 저장), 질문 횟수",
                    "keep": f"신청 정보는 접수 후 {R['contacts'] // 30}개월 · 이용 정보는 이용 기간 종료 후 {R['members_expired'] // 30}개월"})
    out += [
        {"name": "서비스 이용 기록 (자동 수집)", "purpose": "부정 이용·과다 호출 방지, 보안 점검, 방문 통계",
         "required": "없음", "optional": "없음", "auto": "접속 IP 주소, 접속 일시, 이용한 페이지, 남용 방지용 시도 기록",
         "keep": f"{R['access_logs']}일"},
        {"name": "참여 기록·화면 설정 (자동 수집)", "purpose": "퀴즈·투표·테스트 결과 제공, 연속 참여 기록, 다음 방문 시 화면 유지, 참여 통계",
         "required": "없음", "optional": "없음",
         "auto": "쿠키 식별값(axv), 퀴즈 답·예측 투표·테스트 결과와 점수, 공유·구독 창 이용 기록, 노트 검색어·필터 등 화면 설정값",
         "keep": f"{R['engagements'] // 30}개월 (화면 설정값은 마지막 방문 후 {R['visitor_state'] // 30}개월)"},
        {"name": "참여 통계 프로필 (선택)", "purpose": "성별·연령대·지역별 참여 통계, 참여 지도(3명 미만 칸은 공개하지 않음)",
         "required": "없음", "optional": "성별, 연령대, 국가, 국내 시·도", "auto": "없음",
         "keep": f"마지막 참여 후 {R['profiles'] // 30}개월 ('바꾸기'로 수정·'내 기록 지우기'로 삭제)"},
    ]
    return out


def entrustments() -> list[dict]:
    """처리 위탁 (수탁자, 위탁 업무) — 켜져 있는 기능만."""
    s, f = settings(), _features()
    out = []
    if f["smtp"]:
        out.append({"to": s["smtp_vendor"] or "메일 발송 서버 운영사 (SMTP)", "work": "구독 확인·뉴스레터 메일 발송"})
    if f["ask"]:
        out.append({"to": "Google LLC (Gemini API)", "work": "AX 질문하기 답변 생성, 노트 의미 검색 (질문·검색어 처리, 저장하지 않음)"})
    if f["databricks"]:
        out.append({"to": "Databricks, Inc.", "work": "서비스 이용 통계 분석용 데이터 보관 (이름·이메일·IP 제외)"})
    out.append({"to": "Tailscale Inc.", "work": "공개 주소 접속 중계 (접속 IP가 지나감)"})
    return out


def overseas() -> list[dict]:
    """국외 이전 (제28조의8) — 위탁·보관으로 국외로 가는 경우. 연락처는 각 사 처리방침 문의처."""
    s, f = settings(), _features()
    out = []
    if f["ask"]:
        out.append({"to": "Google LLC", "country": "미국", "items": "질문·대화 일부, 의미 검색어 (본인이 입력한 내용)",
                    "when": "질문·검색할 때마다 암호화된 네트워크로 전송", "purpose": "답변 생성·검색 (Google 정책에 따른 기간, 이 사이트는 저장하지 않음)",
                    "contact": "https://policies.google.com/privacy", "refuse": "질문하기·의미 검색을 쓰지 않으면 이전되지 않음 (거부 시 해당 기능만 이용 불가)"})
    if f["databricks"]:
        out.append({"to": "Databricks, Inc.", "country": s["databricks_region"], "items": "참여 기록·선택 프로필 (쿠키 식별값 기준, 이름·이메일·IP 제외)",
                    "when": "작업 후 수시, 암호화된 네트워크로 전송", "purpose": "이용 통계 분석, 이 사이트의 보유 기간과 같음",
                    "contact": "https://www.databricks.com/legal/privacynotice", "refuse": "'내 기록 지우기'로 삭제 (다음 적재 때 반영)"})
    out.append({"to": "Tailscale Inc.", "country": "캐나다·미국", "items": "접속 IP 주소, 요청 정보",
                "when": "접속할 때마다 (중계 서버 경유)", "purpose": "공개 주소 접속 중계 (저장 기간은 Tailscale 정책에 따름)",
                "contact": "https://tailscale.com/privacy-policy", "refuse": "거부 시 공개 주소로 접속할 수 없음"})
    if f["smtp"] and s["smtp_country"] and s["smtp_country"] != "대한민국":
        out.append({"to": s["smtp_vendor"] or "메일 발송 업체", "country": s["smtp_country"], "items": "이메일",
                    "when": "메일 발송 시", "purpose": "메일 발송 (업체 정책에 따른 기간)", "contact": "업체 개인정보처리방침",
                    "refuse": "거부 시 구독할 수 없음"})
    return out


def active() -> bool:
    """처리하는 개인정보가 있는지 — 없으면 처리방침 페이지·링크를 표시하지 않는다."""
    return bool(records())


# ───────────────────────── 버전 (공지일·시행일별) ─────────────────────────

_SQL = """CREATE TABLE IF NOT EXISTS privacy_versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, announced_at TEXT NOT NULL, effective_date TEXT NOT NULL UNIQUE,
  summary TEXT NOT NULL DEFAULT '', content TEXT NOT NULL, created_at TEXT NOT NULL)"""


def snapshot() -> dict:
    """지금 기능·설정으로 만든 처리방침 내용 (공지할 때 이대로 고정된다)."""
    s = settings()
    return {"settings": {k: s[k] for k in DEFAULTS}, "records": records(), "entrustments": entrustments(),
            "overseas": overseas(), "retention": dict(db.RETENTION_DAYS), "backup_days": 14}


def _conn():
    conn = db.connect()
    conn.execute(_SQL)
    return conn


def versions() -> list[dict]:
    """공지한 버전 (시행일 최신순). status: 시행 예정 / 시행 중 / 이전."""
    today = date.today().isoformat()
    conn = _conn()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM privacy_versions ORDER BY effective_date DESC")]
    finally:
        conn.close()
    current_found = False
    for r in rows:
        r["content"] = json.loads(r["content"])
        if r["effective_date"] > today:
            r["status"] = "시행 예정"
        elif not current_found:
            r["status"], current_found = "시행 중", True
        else:
            r["status"] = "이전"
    return rows


def current() -> dict | None:
    return next((v for v in versions() if v["status"] == "시행 중"), None)


def upcoming() -> list[dict]:
    return [v for v in versions() if v["status"] == "시행 예정"]


def publish(effective_date: str, summary: str, major: bool = False) -> int:
    """지금 내용을 새 버전으로 공지한다. 시행일은 오늘 + 공지 기간(중요 변경 30일, 그 밖 7일) 이후여야 한다.
    처음 게시(이전 버전 없음)는 바로 시행할 수 있다."""
    if missing():
        raise ValueError("필수 기재사항이 비어 있습니다: " + ", ".join(missing()))
    eff = date.fromisoformat(effective_date)
    first = not versions()
    need = 0 if first else (MAJOR_NOTICE_DAYS if major else NOTICE_DAYS)
    if (eff - date.today()).days < need:
        raise ValueError(f"시행일은 공지일로부터 {need}일 뒤 이후여야 합니다" + (" (중요 변경)" if major else ""))
    conn = _conn()
    try:
        with conn:
            return conn.execute(
                "INSERT INTO privacy_versions (announced_at, effective_date, summary, content, created_at) VALUES (?,?,?,?,?)",
                (date.today().isoformat(), eff.isoformat(), summary.strip() or "개인정보 처리방침 제정" if first else summary.strip(),
                 json.dumps(snapshot(), ensure_ascii=False), datetime.now().isoformat(timespec="seconds"))).lastrowid
    finally:
        conn.close()


def withdraw(version_id: int) -> bool:
    """시행 전인 공지만 거둘 수 있다 (시행했거나 지난 버전은 기록으로 남긴다)."""
    conn = _conn()
    try:
        with conn:
            return conn.execute("DELETE FROM privacy_versions WHERE id = ? AND effective_date > ?",
                                (version_id, date.today().isoformat())).rowcount == 1
    finally:
        conn.close()


def outdated() -> bool:
    """지금 기능·설정이 가장 최근에 공지한 버전과 다르면 True — 새 버전을 공지해야 한다."""
    vs = versions()
    return bool(vs) and vs[0]["content"] != json.loads(json.dumps(snapshot(), ensure_ascii=False))
