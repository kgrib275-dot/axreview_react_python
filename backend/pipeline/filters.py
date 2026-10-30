from __future__ import annotations

import re
from functools import lru_cache

from .models import Item, KeywordRule

# 2026-10-30 키워드 보강과 함께 바꾼 매칭 규칙
# 1) 영어 단어는 단어 경계로 맞춘다 — 예전엔 단순 포함 검사라 "AX"가 tax·max·relax 에, "RAG"가 average·storage 에,
#    "ROI"가 android 에 걸려 관련 없는 기사가 대량으로 통과했다. 짧은 약어(5자 이하·대문자)는 앞뒤 모두,
#    긴 단어는 앞만 경계로 본다 (agent → agents·agentic 처럼 뒤에 붙는 꼴은 살린다).
# 2) 한글은 조사가 붙으므로 그대로 포함 검사.
# 3) 제외 규칙은 '제목'에만 적용 — 본문 발췌에 '영업익'·'코인'이 한 번 스친 AI 도입 기사까지 버려졌다.
# 4) needs_ai 규칙(업종·직무처럼 넓은 단어)은 같은 글에 AI 단어가 함께 있을 때만 통과 — 금융·보험·물류 전문지의
#    일반 기사가 'bank' 'supply chain' 만으로 들어오지 않게.
_HANGUL = re.compile(r"[가-힣]")

# 'AI 단어' — needs_ai 규칙이 통과하려면 이 중 하나, 또는 needs_ai 가 아닌 포함 규칙 하나가 같은 글에 있어야 한다
AI_ANCHORS = ("AI", "A.I.", "인공지능", "머신러닝", "machine learning", "딥러닝", "deep learning", "neural network", "신경망",
              "LLM", "GPT", "ChatGPT", "챗GPT", "생성형", "generative", "agentic", "에이전트", "AI agent", "copilot", "코파일럿",
              "chatbot", "챗봇", "foundation model", "언어모델", "language model", "Gemini", "Claude", "OpenAI", "Anthropic",
              "제미나이", "클로드", "앤트로픽", "오픈AI", "Copilot", "Llama", "Mistral", "Hugging Face", "허깅페이스")


@lru_cache(maxsize=4096)
def _matcher(needle: str):
    n = needle.strip()
    if not n:
        return None
    if _HANGUL.search(n):
        low = n.lower()
        return lambda text, low=low: low in text
    esc = re.escape(n.lower())
    short = len(n) <= 5 or n.isupper()
    pat = rf"(?<![a-z0-9]){esc}(?![a-z0-9])" if short else rf"(?<![a-z0-9]){esc}"
    rx = re.compile(pat)
    return lambda text, rx=rx: rx.search(text) is not None


def _hit(text: str, needle: str) -> bool:
    m = _matcher(needle)
    return bool(m and m(text))


def _text_of(item: Item) -> str:
    return f"{item.title} {item.excerpt}".lower()


def _rule_hits(text: str, rule: KeywordRule) -> bool:
    return any(_hit(text, n) for n in (rule.keyword, *rule.aliases))


def _has_ai(text: str) -> bool:
    return any(_hit(text, a) for a in AI_ANCHORS)


def apply_keyword_filter(items: list[Item], rules: list[KeywordRule]) -> list[Item]:
    include_rules = [r for r in rules if r.mode == "include"]
    exclude_rules = [r for r in rules if r.mode == "exclude"]

    kept = []
    for item in items:
        text = _text_of(item)
        title = item.title.lower()
        if any(_rule_hits(title, r) for r in exclude_rules):
            continue

        hits = [r for r in include_rules if _rule_hits(text, r)]
        core = [r for r in hits if not r.needs_ai]
        # 넓은 단어(needs_ai)만 걸렸으면 '제목'에 AI 단어가 있어야 한다 — 본문 발췌에 AI 가 한 번 스친 실적·인사 기사까지 들어왔다
        matched_rules = hits if (core or _has_ai(title)) else []
        if include_rules and not matched_rules:
            continue

        item.matched_kw = [r.keyword for r in matched_rules]
        item.kw_score = sum(r.weight for r in matched_rules)
        kept.append(item)
    return kept
