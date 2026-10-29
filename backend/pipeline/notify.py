"""Teams 웹훅 발송 (AI_NEWS pipeline/notify.py 기반).

Teams Workflows(Power Automate) 웹훅 형식의 Adaptive Card로 주간 AX 흐름과 새 노트를
보낸다. 웹훅 목록은 관리 > 구독·발송 > Teams에서 관리한다(data/settings.json).
"""
from __future__ import annotations

from datetime import datetime

import httpx

_MAX_NOTES = 8


def _wrap(card: dict) -> dict:
    """구버전 O365 커넥터(MessageCard)는 퇴역했으므로 Workflows 형식으로 감싼다."""
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def _strip_bold(text: str) -> str:
    return text.replace("**", "")


def build_card(issue: dict | None, notes: list[dict], site_url: str, pdf_url: str | None = None) -> dict:
    body: list = [
        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "color": "Accent",
         "text": "AX REVIEW", "wrap": True},
    ]
    if issue:
        body += [
            {"type": "TextBlock", "isSubtle": True, "size": "Small", "spacing": "Small",
             "text": f"THIS WEEK · {issue['week']} · {issue['range']}", "wrap": True},
            {"type": "TextBlock", "weight": "Bolder", "size": "Large", "spacing": "Small", "wrap": True,
             "text": f"{issue['headline_em']} {issue['headline']}".strip()},
            {"type": "TextBlock", "wrap": True, "spacing": "Small", "text": _strip_bold(issue["body"])},
        ]
    if notes:
        body.append({"type": "TextBlock", "weight": "Bolder", "spacing": "Large", "separator": True,
                     "text": f"새 노트 {len(notes)}편", "wrap": True})
        for n in notes[:_MAX_NOTES]:
            body += [
                {"type": "TextBlock", "wrap": True, "spacing": "Medium", "weight": "Bolder",
                 "text": f"[{n['title']}]({site_url}/notes?id={n['id']})"},
                {"type": "TextBlock", "wrap": True, "spacing": "None", "size": "Small", "isSubtle": True,
                 "text": f"{n['category']} · {n['source']}"},
                {"type": "TextBlock", "wrap": True, "spacing": "Small", "size": "Small", "text": n["summary"]},
            ]
        if len(notes) > _MAX_NOTES:
            body.append({"type": "TextBlock", "isSubtle": True, "size": "Small", "wrap": True,
                         "text": f"※ {len(notes)}편 중 {_MAX_NOTES}편만 표시 — 나머지는 사이트에서 확인하세요."})
    actions = [{"type": "Action.OpenUrl", "title": "AX Review 열기", "url": f"{site_url}/"}]
    if pdf_url:
        actions.append({"type": "Action.OpenUrl", "title": "주간 리포트 PDF", "url": pdf_url})
    return _wrap({"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                  "version": "1.2", "body": body, "actions": actions})


def build_test_card() -> dict:
    return _wrap({
        "type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.2",
        "body": [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": "✅ AX Review 연결 테스트", "wrap": True},
            {"type": "TextBlock", "text": "Teams 웹훅이 정상적으로 연결됐습니다.", "wrap": True},
            {"type": "TextBlock", "size": "Small", "isSubtle": True, "wrap": True,
             "text": f"시각: {datetime.now():%Y-%m-%d %H:%M:%S}"},
        ],
    })


def build_alert_card(title: str, body: str, site_url: str) -> dict:
    """운영 경보 카드 (pipeline/alerts.py)."""
    return _wrap({
        "type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "version": "1.2",
        "body": [
            {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "color": "Attention", "text": f"⚠️ {title}", "wrap": True},
            {"type": "TextBlock", "text": body, "wrap": True},
            {"type": "TextBlock", "size": "Small", "isSubtle": True, "wrap": True, "text": f"시각: {datetime.now():%Y-%m-%d %H:%M}"},
        ],
        "actions": [{"type": "Action.OpenUrl", "title": "운영 점검 열기", "url": f"{site_url.rstrip('/')}/admin-ops"}],
    })


def post(url: str, payload: dict, retries: int = 2) -> tuple[bool, str]:
    from . import settings_store
    if not settings_store.webhook_url_ok(url):
        return False, "허용되지 않는 웹훅 주소"
    last = ""
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            return True, f"HTTP {resp.status_code}"
        except httpx.HTTPError as e:
            last = str(e)[:200]
            if attempt < retries:
                import time
                time.sleep(2 ** attempt)
    return False, last
