"""편집 관점 — '리더가 알아야 할 3가지', 에디터 코멘트, 본문 강조. AI 호출 없이 규칙으로만 만든다.

관점(settings.json "lens")은 관리 > 주간 흐름에서 정한다.
- focus: 우리가 특히 보는 주제어. 3가지를 고를 때 가산점, 본문에서 색으로 강조한다.
- industries: 우리 업종. 맞는 노트에 가산점.
- audience: 주 독자. 노트의 대상 독자와 맞으면 가산점.
- stance: 이 뉴스레터의 관점 한 문장. 메일·홈 '리더 3가지' 위에 붙는다.
"""
from __future__ import annotations

import re
from html import escape

from . import settings_store

_SECTION_RE = r"^###\s*{}\s*\n(.*?)(?=^###\s|\Z)"
_ITEM_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+)$", re.M)
_LABEL_RE = re.compile(r"^\*\*\s*(?:\[[^\]]*\]\s*)?(.+?)\s*(?:\([^)]*\))?\s*[:：]?\s*\*\*\s*[:：]?\s*(.*)$")


def lens() -> dict:
    return settings_store.load()["lens"]


def _section(body: str, name: str) -> str:
    m = re.search(_SECTION_RE.format(re.escape(name)), body or "", re.M | re.S)
    return m.group(1).strip() if m else ""


def _first_item(text: str) -> tuple[str, str]:
    """목록 첫 항목을 (굵은 제목, 첫 문장)으로 나눈다. '**1주차: 현황 진단**: 현재 …' → ('현황 진단', '현재 …')."""
    m = _ITEM_RE.search(text)
    if not m:
        return "", ""
    item = m.group(1).strip()
    label, rest = "", item
    lm = _LABEL_RE.match(item)
    if lm:
        label, rest = lm.group(1).strip(), lm.group(2).strip()
        label = re.sub(r"^\d+\s*[-~]?\s*\d*\s*주차\s*[:：]\s*", "", label)
    rest = rest.replace("**", "")
    first = re.split(r"(?<=[다요음함])\.\s", rest, maxsplit=1)[0].strip().rstrip(".")
    label = label.replace("**", "").strip("[]【】 ")
    return label, first[:110] + ("…" if len(first) > 110 else "")


def _short(text: str, n: int = 48) -> str:
    text = text.replace("**", "").strip()
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


def _score(note: dict, lz: dict) -> float:
    text = f"{note['title']} {note.get('tags', '')} {note['summary']}".lower()
    s = sum(2.0 for k in lz["focus"] if k and k.lower() in text)
    s += sum(1.5 for k in lz["industries"] if k and k.lower() in text)
    if lz.get("audience") and lz["audience"] in (note.get("audiences") or ""):
        s += 1.0
    return s


def leader_three(notes: list[dict], picks: str = "") -> list[dict]:
    """이번 호 노트 중 리더가 알아야 할 3가지. 관리자가 고른 노트(picks)가 있으면 그 순서를 따른다.

    고르는 규칙: 관점 점수(주제어·업종·독자) → 최신순, 분야(Strategy/Implementation/Enablement)가 겹치지 않게.
    각 항목의 제목은 핵심 포인트 첫 항목이다. action(현업 실행 첫 단계)·check(AX 적용 첫 항목)도 뽑아 두지만
    화면·메일에는 쓰지 않는다 (2026-10-28 사용자 요청: 카드가 길어져 핵심이 안 보임).
    """
    lz = lens()
    by_id = {n["id"]: n for n in notes}
    chosen = [by_id[int(i)] for i in (picks or "").split(",") if i.strip().isdigit() and int(i) in by_id][:3]
    if len(chosen) < 3:
        rest = sorted((n for n in notes if n not in chosen), key=lambda n: n["published"], reverse=True)
        rest.sort(key=lambda n: -_score(n, lz))  # 안정 정렬 — 점수가 같으면 최신순 유지
        cats = {n["category"] for n in chosen}
        for n in rest:  # 분야가 겹치지 않게 먼저 채우고, 모자라면 겹쳐도 채운다
            if len(chosen) < 3 and n["category"] not in cats:
                chosen.append(n)
                cats.add(n["category"])
        for n in rest:
            if len(chosen) < 3 and n not in chosen:
                chosen.append(n)
    out = []
    for n in chosen:
        point, point_text = _first_item(_section(n["body"], "핵심 포인트"))
        step, step_text = _first_item(_section(n["body"], "현업 실행"))
        check, _ = _first_item(_section(n["body"], "AX 적용"))
        out.append({"id": n["id"], "title": n["title"], "category": n["category"],
                    "point": point or _short(point_text or n["summary"]), "point_text": point_text,
                    "action": " — ".join(x for x in (step, step_text) if x), "check": check})
    return out


def highlight(text: str, mail: bool = False) -> str:
    """본문 강조: **굵게** → 형광펜 강조, 관점 주제어 → 색 강조(주제어마다 처음 한 번만 — 다 칠하면 눈에 안 띈다).

    mail=True면 메일 클라이언트가 class를 지우므로 인라인 스타일을 쓴다.
    """
    parts = escape(text or "").split("**")
    strong = ('<strong style="color:#FFFFFF;background:linear-gradient(transparent 58%,rgba(46,155,234,.45) 58%)">'
              if mail else '<strong class="hl">')
    kw_open = '<b style="color:#5BC2F5;font-weight:700">' if mail else '<b class="kw">'
    kw_close = "</b>"
    words = sorted({k for k in lens()["focus"] if k}, key=len, reverse=True)
    kw_re = re.compile("|".join(re.escape(escape(w)) for w in words)) if words else None
    seen: set[str] = set()

    def mark(m: re.Match) -> str:
        w = m.group(0)
        if w in seen:
            return w
        seen.add(w)
        return f"{kw_open}{w}{kw_close}"

    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(f"{strong}{p}</strong>")
        else:
            out.append(kw_re.sub(mark, p) if kw_re else p)
    return "".join(out)
