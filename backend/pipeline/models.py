from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Item:
    title: str
    url: str
    source: str
    source_type: str
    published_at: datetime
    excerpt: str = ""
    url_hash: str = ""
    matched_kw: list[str] = field(default_factory=list)
    kw_score: float = 0.0
    summary_ko: str = ""
    llm_score: int = 0


@dataclass
class KeywordRule:
    keyword: str
    aliases: list[str]
    mode: str
    weight: float
    category: str = ""
    needs_ai: bool = False  # 업종·직무처럼 넓은 단어 — AI 관련 단어와 같은 글에 함께 나올 때만 통과 (2026-10-30)
