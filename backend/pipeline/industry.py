"""업종 분류 — 노트를 제조·컨택센터·금융 등으로 묶는다 (규칙 기반, 노트 제목·태그·요약·본문의 단어로).

노트 목록의 '업종' 필터와 업종별 뉴스레터(구독할 때 고른 업종의 노트를 먼저 보냄)에 쓴다.
단어를 고치면 바로 반영된다 (DB에 저장하지 않고 그때그때 판정).
"""
from __future__ import annotations

import re

# 업종 → 판정 단어 (영문은 대소문자 무시). 수집 키워드(config/keywords.yaml)의 제조 AI·컨택센터 별칭을 포함한다.
INDUSTRIES: dict[str, list[str]] = {
    "제조": ["제조", "공장", "스마트팩토리", "smart factory", "manufactur", "예지보전", "predictive maintenance", "생산 라인",
           "공정", "설비", "품질 검사"],  # supply chain·factory는 소프트웨어 공급망·'토큰 팩토리'와 겹쳐 뺀다
    "컨택센터": ["컨택센터", "콜센터", "contact center", "call center", "고객센터", "상담", "customer service", "고객 응대", "voicebot", "챗봇"],
    "금융": ["금융", "은행", "보험", "증권", "카드사", "핀테크", "fintech", "bank", "insurance", "세금", "결제", "자산 관리",
           "wealth", "자산운용"],  # '투자'는 ROI·예산 이야기와 겹쳐 뺀다
    "유통·커머스": ["유통", "리테일", "retail", "커머스", "commerce", "이커머스", "쇼핑", "물류", "logistics"],
    "공공": ["공공기관", "정부", "지자체", "공공 부문", "public sector", "government"],
    "의료·헬스케어": ["의료", "병원", "헬스케어", "healthcare", "제약", "pharma"],
}
NAMES = list(INDUSTRIES)
_RES = {k: re.compile("|".join(re.escape(w) for w in ws), re.I) for k, ws in INDUSTRIES.items()}


_memo: dict[tuple, list[str]] = {}


def of(note: dict, min_hits: int = 2) -> list[str]:
    """노트가 속한 업종들. 제목·태그·요약에 한 번이면 바로, 본문에만 있으면 min_hits번 이상 나와야 한다 (지나가는 언급 제외).
    노트 목록 요청마다 본문 전체에 정규식을 돌리지 않게 같은 내용이면 기억해 둔 결과를 쓴다."""
    head = f"{note.get('title', '')} {note.get('tags', '')} {note.get('summary', '')}"
    body = note.get("body", "") or ""
    key = (head, hash(body), min_hits)
    hit = _memo.get(key)
    if hit is None:
        hit = [k for k, rx in _RES.items() if rx.search(head) or len(rx.findall(body)) >= min_hits]
        if len(_memo) > 5000:
            _memo.clear()
        _memo[key] = hit
    return list(hit)


def filter_notes(notes: list[dict], wanted: list[str]) -> list[dict]:
    if not wanted:
        return notes
    want = set(wanted)
    return [n for n in notes if want & set(of(n))]


def parse(raw: str | None) -> list[str]:
    """구독자 업종 문자열('제조,금융') → 알려진 업종만."""
    return [x for x in (raw or "").split(",") if x in INDUSTRIES]
