from __future__ import annotations

from .models import Item, KeywordRule


def _text_of(item: Item) -> str:
    return f"{item.title} {item.excerpt}".lower()


def _rule_hits(text: str, rule: KeywordRule) -> bool:
    needles = [rule.keyword.lower(), *[a.lower() for a in rule.aliases]]
    return any(n in text for n in needles)


def apply_keyword_filter(items: list[Item], rules: list[KeywordRule]) -> list[Item]:
    include_rules = [r for r in rules if r.mode == "include"]
    exclude_rules = [r for r in rules if r.mode == "exclude"]

    kept = []
    for item in items:
        text = _text_of(item)
        if any(_rule_hits(text, r) for r in exclude_rules):
            continue

        matched = [r.keyword for r in include_rules if _rule_hits(text, r)]
        if include_rules and not matched:
            continue

        item.matched_kw = matched
        item.kw_score = sum(r.weight for r in include_rules if r.keyword in matched)
        kept.append(item)
    return kept
