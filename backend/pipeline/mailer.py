"""뉴스레터 메일 발송 (SMTP). 접속 정보는 .env의 SMTP_* 값을 쓴다."""
from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from html import escape

from . import editorial


def smtp_config() -> dict:
    return {
        "host": os.environ.get("SMTP_HOST", ""),
        "port": int(os.environ.get("SMTP_PORT", "587") or 587),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASS", ""),
        "sender": os.environ.get("SMTP_FROM", "") or os.environ.get("SMTP_USER", ""),
        "tls": os.environ.get("SMTP_TLS", "starttls").lower(),  # starttls / ssl / none
    }


def is_configured() -> bool:
    cfg = smtp_config()
    return bool(cfg["host"] and cfg["sender"])


def site_url() -> str:
    return os.environ.get("SITE_URL", "http://localhost:5002").rstrip("/")


def leader_block(issue: dict | None, notes: list[dict], base: str) -> str:
    """'리더가 알아야 할 3가지' + 에디터 코멘트 (pipeline/editorial.py, 규칙 기반)."""
    three = editorial.leader_three(notes, (issue or {}).get("picks", ""))
    if not three:
        return ""
    lz = editorial.lens()
    rows = "".join(f"""
  <tr><td style="padding:12px 0;border-top:1px solid #16274A;vertical-align:top;width:34px">
    <div style="width:26px;height:26px;border-radius:50%;background:#0A6FD6;color:#fff;font:700 13px/26px sans-serif;text-align:center">{i}</div></td>
  <td style="padding:12px 0;border-top:1px solid #16274A">
    <a href="{base}/notes?id={t['id']}" style="text-decoration:none;font-size:15px;font-weight:700;line-height:1.5;color:#FFFFFF">{escape(t['point'])}</a>
    <div style="font-size:12px;color:#8C9BB5;margin-top:3px">{escape(t['title'][:70])}</div>
  </td></tr>""" for i, t in enumerate(three, 1))
    note = (issue or {}).get("editor_note", "").strip()
    note_html = f"""
<tr><td style="padding:6px 32px 4px">
  <div style="border-left:3px solid #5BC2F5;background:#0B1730;border-radius:0 10px 10px 0;padding:12px 16px">
    <div style="font:11px monospace;letter-spacing:1.5px;color:#5BC2F5">EDITOR'S NOTE</div>
    <div style="margin-top:6px;font-size:14px;line-height:1.75;color:#E8EEF8">{editorial.highlight(note, mail=True)}</div>
  </div></td></tr>""" if note else ""
    return f"""{note_html}
<tr><td style="padding:22px 32px 2px">
  <div style="font:12px monospace;letter-spacing:2px;color:#5BC2F5">LEADER'S 3</div>
  <h3 style="margin:6px 0 2px;font-size:17px;color:#E8EEF8">리더가 이번 주 알아야 할 3가지</h3>
  <div style="font-size:12px;color:#8C9BB5">{escape(lz.get('stance', ''))}</div>
  <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:8px">{rows}</table>
</td></tr>"""


def _card(base: str, n: dict) -> str:
    return f"""
<tr><td style="padding:10px 32px">
  <a href="{base}/notes?id={n['id']}" style="display:block;text-decoration:none;border:1px solid #16274A;border-radius:12px;padding:16px 18px;background:#0B1730">
    <div style="font:11px monospace;color:#5BC2F5">{escape(n['category'])} · {escape(n['kind'])}</div>
    <div style="margin:6px 0;font-size:15px;font-weight:700;line-height:1.5;color:#E8EEF8">{escape(n['title'])}</div>
    <div style="font-size:13px;line-height:1.7;color:#B5C2D8">{escape(n['summary'])}</div>
  </a>
</td></tr>"""


def build_html(issue: dict | None, notes: list[dict], unsubscribe_token: str = "",
               pdf_url: str | None = None, preview: bool = False, industries: list[str] | None = None,
               refer_key: str = "") -> str:
    """preview=True: 사이트 안 미리보기 — 링크를 새 탭으로 연다(미리보기 틀 안에서 사이트가 열리지 않게).
    industries: 구독자가 고른 업종 — 그 업종 노트를 'OO 사례'로 먼저 싣고, 나머지 새 노트는 3편까지만."""
    from . import industry
    base = site_url()
    issue_html = ""
    if issue:
        issue_html = f"""
<tr><td style="padding:28px 32px 8px">
  <div style="font:12px monospace;letter-spacing:2px;color:#5BC2F5">THIS WEEK · {escape(issue['week'])} · {escape(issue['range'])}</div>
  <h2 style="margin:10px 0 12px;font-size:20px;line-height:1.5;color:#E8EEF8">
    <span style="color:#5BC2F5">{escape(issue['headline_em'])}</span> {escape(issue['headline'])}</h2>
  <p style="margin:0;font-size:14px;line-height:1.8;color:#B5C2D8">{editorial.highlight(issue['body'], mail=True)}</p>
</td></tr>"""
    issue_html += leader_block(issue, notes, base)
    head = lambda t: f'<tr><td style="padding:24px 32px 4px;font:12px monospace;letter-spacing:2px;color:#8C9BB5">{escape(t)}</td></tr>'  # noqa: E731
    mine = industry.filter_notes(notes, industries) if industries else []
    if mine:
        rest = [n for n in notes if n not in mine][:3]
        cards = (head(f"{' · '.join(industries)} 사례") + "".join(_card(base, n) for n in mine)
                 + (head("그 밖의 새 노트") + "".join(_card(base, n) for n in rest) if rest else ""))
    else:
        cards = head("NEW NOTES") + "".join(_card(base, n) for n in notes)
    unsub = f"{base}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else f"{base}/"
    # 내 추천 링크: 본인만 받는 메일에만 (주소에 해지 토큰이 들어가므로 미리보기·공개 화면에는 견본 주소)
    refer_url = f"{base}/refer?k={refer_key}" if refer_key else f"{base}/letter"
    refer = f"""
<tr><td style="padding:18px 32px 0">
  <div style="border:1px dashed #2E9BEA;border-radius:12px;padding:14px 18px;font-size:13px;line-height:1.7;color:#B5C2D8">
    <b style="color:#E8EEF8">친구 3명을 초대하면 지난 호 주간 PDF 전체가 열립니다.</b><br>
    <a href="{refer_url}" style="color:#5BC2F5">내 추천 링크 받기 · 추천 현황 보기 →</a></div></td></tr>"""
    pdf_link = f'<a href="{pdf_url}" style="color:#5BC2F5">주간 리포트 PDF</a> · ' if pdf_url else ""
    head = '<head><base target="_blank"></head>' if preview else ""
    return f"""<!doctype html><html>{head}<body style="margin:0;background:#050B18;font-family:'Malgun Gothic',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#050B18"><tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%">
<tr><td style="padding:28px 32px;background:linear-gradient(120deg,#0A2A5A,#0A6FD6);border-radius:0 0 18px 18px">
  <div style="font-size:22px;font-weight:800;color:#fff">AX <span style="color:#5BC2F5">REVIEW</span></div>
  <div style="font-size:12px;color:#CFE9FF;margin-top:4px">기업의 AX를 위한 필수 지식</div>
</td></tr>
{issue_html}
{cards}
{refer}
<tr><td style="padding:24px 32px 36px;font-size:12px;color:#8C9BB5;line-height:1.7">
  <a href="{base}/" style="color:#5BC2F5">사이트에서 보기</a> · {pdf_link}
  <a href="{unsub}" style="color:#8C9BB5">구독 해지</a><br>© AX Review
</td></tr>
</table></td></tr></table></body></html>"""


def confirm_html(confirm_token: str) -> str:
    base = site_url()
    return f"""<!doctype html><html><body style="margin:0;background:#050B18;font-family:'Malgun Gothic',sans-serif;color:#E8EEF8">
<div style="max-width:560px;margin:0 auto;padding:36px 28px">
  <div style="font-size:22px;font-weight:800">AX <span style="color:#5BC2F5">REVIEW</span></div>
  <h2 style="font-size:19px;margin:22px 0 10px">구독 신청을 확인해 주세요</h2>
  <p style="color:#B5C2D8;line-height:1.7;font-size:14px">아래 버튼을 누르면 구독이 완료됩니다. 직접 신청하지 않았다면 이 메일을 무시하세요 — 아무것도 발송되지 않습니다.</p>
  <p style="margin:26px 0"><a href="{base}/confirm?t={confirm_token}" style="background:#0A6FD6;color:#fff;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">구독 확인하기</a></p>
  <p style="color:#8C9BB5;font-size:12px">확인하지 않은 신청은 7일 뒤 자동으로 지워집니다.</p>
</div></body></html>"""


def send_confirmation(email: str, confirm_token: str) -> bool:
    """구독 확인 메일. SMTP가 없으면 False (관리 > 구독·발송에서 나중에 다시 보낼 수 있다)."""
    if not is_configured():
        return False
    ok, _ = send([(email, "")], "[AX Review] 구독 신청을 확인해 주세요", lambda _t: confirm_html(confirm_token))
    return ok == 1


def send(recipients: list[tuple[str, str]], subject: str, html_for, on_sent=None) -> tuple[int, list[str]]:
    """recipients: (email, unsubscribe_token) 목록. html_for(token) -> 본문.
    (성공 건수, 실패 주소 목록)을 반환한다. 연결은 한 번 열어 재사용한다."""
    cfg = smtp_config()
    if not is_configured():
        raise RuntimeError("SMTP 설정이 없습니다 (.env의 SMTP_HOST / SMTP_FROM)")
    smtp_cls = smtplib.SMTP_SSL if cfg["tls"] == "ssl" else smtplib.SMTP
    ok, failed = 0, []
    with smtp_cls(cfg["host"], cfg["port"], timeout=30) as server:
        if cfg["tls"] == "starttls":
            server.starttls()
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        for email, token in recipients:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = formataddr(("AX Review", cfg["sender"]))
            msg["To"] = email
            msg.attach(MIMEText(html_for(token), "html", "utf-8"))
            try:
                server.sendmail(cfg["sender"], [email], msg.as_string())
                ok += 1
                if on_sent:
                    on_sent(email)  # 수신자별 기록 — 중간에 끊겨 다시 보낼 때 이미 받은 사람은 건너뛴다
            except smtplib.SMTPServerDisconnected:
                failed.extend(e for e, _ in recipients[recipients.index((email, token)):])
                break  # 연결이 끊기면 나머지는 실패로 두고 다음 실행에서 이어 보낸다
            except (smtplib.SMTPException, OSError):
                failed.append(email)
    return ok, failed
