"""라우터 공용 — 노트 카드 직렬화, 마크다운 → HTML, 쿼리 문자열 목록 파싱."""
from __future__ import annotations

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


__all__ = ["md_html", "note_card", "csv_list"]
