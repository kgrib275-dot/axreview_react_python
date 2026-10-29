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
