"""Gemini 호출. 키 로테이션(GeminiKeyPool)은 AI_NEWS 그대로이고, 프롬프트는 AX Review용이다."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import gemini_keys

log = logging.getLogger(__name__)

CATEGORIES = ["AX Strategy", "AX Implementation", "AX Enablement"]
KINDS = ["아티클", "포스트", "리포트", "대담"]
AUDIENCES = ["CEO", "CFO", "CHRO", "CIO·CTO", "CISO", "AX 추진", "현업 리더"]


class AllKeysExhausted(Exception):
    pass


class GeminiKeyPool:
    """키 배정·상태는 gemini_keys(프로세스 공유)가 맡는다 — 병렬 작업 여러 개가 같은 풀을 써도
    정상 키에 라운드로빈으로 나뉘고, 소진·무효 키는 함께 건너뛴다."""

    def __init__(self, keys: list[str], client_factory=gemini_keys.client):
        if not keys:
            raise ValueError("GeminiKeyPool requires at least one API key")
        self.client_factory = client_factory

    def workers(self, model: str, cap: int = 5) -> int:
        """병렬 작업 수 = 이 모델에 쓸 수 있는 키 수 (키 하나에 동시 요청이 몰리지 않게)."""
        return max(1, min(cap, gemini_keys.healthy_count(model)))

    def generate(self, model: str, prompt: str, json_mode: bool = False,
                 rounds: int = 3, backoff_seconds: float = 20.0, thinking_budget: int | None = None) -> str:
        """thinking_budget=0: 2.5 계열의 '생각' 토큰을 끈다 — 채점처럼 판단이 단순한 일에서 토큰을 크게 줄인다."""
        last_exc = None
        config: dict | None = {"response_mime_type": "application/json"} if json_mode else None
        if thinking_budget is not None:
            config = {**(config or {}), "thinking_config": {"thinking_budget": thinking_budget}}
        for rnd in range(rounds):
            if gemini_keys.exhausted_today(model):
                break  # 모든 키가 오늘 한도 소진·무효 — 기다려도 소용없다
            if rnd:
                time.sleep(backoff_seconds * rnd)  # 분당 제한만 걸린 경우
            for key in gemini_keys.healthy_keys(model):
                client = self.client_factory(key)
                try:
                    resp = client.models.generate_content(model=model, contents=prompt, config=config)
                    gemini_keys.report_success(model, key)
                    return resp.text
                except Exception as exc:  # noqa: BLE001 - any provider error should rotate
                    last_exc = exc
                    gemini_keys.report_error(model, key, exc)
            log.warning("Gemini 정상 키 모두 실패 (%d/%d회차): %s", rnd + 1, rounds, str(last_exc)[:120])
        raise AllKeysExhausted(f"no usable Gemini key for {model}") from last_exc


def pool_from_env() -> GeminiKeyPool | None:
    keys = [k.strip() for k in os.environ.get("GEMINI_API_KEYS", "").split(",") if k.strip()]
    return GeminiKeyPool(keys) if keys else None


def _parse_json(raw: str, kind: type):
    pattern = r"\[.*\]" if kind is list else r"\{.*\}"
    match = re.search(pattern, raw, re.DOTALL)
    data = json.loads(match.group(0) if match else raw)
    if not isinstance(data, kind):
        raise TypeError(f"expected {kind.__name__}")
    return data


# ───────────────────────── 1) 수집 기사 AX 관련도 채점 ─────────────────────────

SCORE_PROMPT = """너는 기업 AI 전환(AX)을 다루는 큐레이션 매체의 에디터다.
독자는 기업 경영진과 AX 실무자이고, 관심사는 AI 전략·투자·조직, 업무·현장 도입 사례,
에이전트 운영, 데이터 기반, 보안·거버넌스다. 단순 모델 출시·주가·연예·소비자 제품 소식은 낮게 본다.

아래 기사 각각(i=번호, t=제목, e=발췌)에 대해
- k: 한국어 한 문장 요약, 60자 이내 (없는 내용 지어내지 말 것)
- s: AX 독자에게 '깊게 읽고 노트로 남길 가치' 1~5점 (5=기업 도입 사례·수치·운영 방식이 구체적)
를 매겨 모든 기사에 대해 [{{"i": 0, "s": 3, "k": "..."}}] JSON 배열로만 답하라.

기사 목록:
{articles_json}
"""


EXCERPT_CHARS = 240  # 채점용 발췌 길이 — 제목과 첫 두세 문장이면 관련도 판단에 충분하다


def _score_batch(batch, pool: GeminiKeyPool, model: str) -> int:
    # URL(평균 100자 안팎)을 입력·출력에 두 번 싣지 않고 번호로 주고받는다.
    articles_json = json.dumps(
        [{"i": n, "t": it.title, "e": " ".join(it.excerpt.split())[:EXCERPT_CHARS]} for n, it in enumerate(batch)],
        ensure_ascii=False, separators=(",", ":"))
    try:
        raw = pool.generate(model, SCORE_PROMPT.format(articles_json=articles_json), json_mode=True, thinking_budget=0)
        by_i = {int(r["i"]): r for r in _parse_json(raw, list) if str(r.get("i", "")).isdigit()}
    except AllKeysExhausted:
        return 0  # 남은 기사는 다음 수집 채점 요청에 함께 실린다 (jobs.pending_items)
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        # 배치 하나가 깨져도 나머지는 계속 처리한다 (AI_NEWS와 같은 방침).
        log.warning("Gemini 채점 배치 파싱 실패 (%d건 건너뜀): %s", len(batch), e)
        return 0
    scored = 0
    for n, it in enumerate(batch):
        r = by_i.get(n)
        if r:
            it.summary_ko = str(r.get("k", ""))
            it.llm_score = max(0, min(5, int(r.get("s", 0) or 0)))
            scored += 1
    log.info("채점 묶음 완료: %d/%d건", scored, len(batch))
    return scored


def score_items(items, pool: GeminiKeyPool, model: str, batch_size: int = 150) -> int:
    """items(Item 목록)에 summary_ko/llm_score를 채운다. 채점된 건수를 반환. 모든 키가 소진되면 AllKeysExhausted.

    무료 등급은 요청 '횟수'가 하루 20회 안팎이라, 수집 한 번의 기사를 요청 한 번에 묶는다(batch_size건까지).
    그보다 많을 때만 나눠서 정상 키 수만큼 병렬로 보낸다."""
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    if not batches:
        return 0
    with ThreadPoolExecutor(max_workers=pool.workers(model)) as ex:
        scored = sum(ex.map(lambda b: _score_batch(b, pool, model), batches))
    if not scored and gemini_keys.exhausted_today(model):
        raise AllKeysExhausted(f"no usable Gemini key for {model}")
    return scored


# ───────────────────────── 2) 노트 초안 작성 ─────────────────────────

NOTE_PROMPT = """너는 AX Review의 에디터다. 아래 원문을 깊게 읽고, 기업 경영진과 AX 실무자를 위한
노트를 한국어로 쓴다. 원문에 없는 수치·사실·인용을 만들어 내지 말 것. 원문 정보가 부족하면 부족한
대로 짧게 쓰고, 추정은 '~로 보입니다'처럼 구분한다. 존댓말(~습니다)로 쓴다.

JSON 객체 하나로만 답하라:
{{
  "title": "영문 핵심어구: 한국어 명사구 한 줄 (콜론 뒤 45자 이내, '~하는 방식/구조/이유'처럼 끝내고 마침표·'~합니다' 금지. 예: 'Agentic AI for Fab Utilities: 인텔이 팹 설비 이상을 에이전트로 진단하는 방식')",
  "category": {categories} 중 하나,
  "kind": {kinds} 중 하나,
  "audiences": {audiences} 중 2~3개 배열,
  "tags": 짧은 한국어 태그 2~3개 배열 (# 없이),
  "summary": "카드용 요약 3~4문장. 누가 무엇을 했고 결과(수치)가 무엇인지 쓰고, 마지막 문장은 '~를 붙였습니다'로 노트에 덧붙인 실행안을 말한다. '본 노트는'으로 시작하지 말 것",
  "body": "마크다운 본문. 반드시 다음 소제목을 순서대로: '### 요약', '### 핵심 포인트'(- 불릿 3~5개), '### 기술·운영 디테일', '### 현업 실행'(번호 단계와 주 단위 일정), '### AX 적용'(우리 회사가 적용할 때 점검할 것)"
}}

출처: {source}
제목: {title}
URL: {url}
원문:
{text}
"""


def write_note(article: dict, text: str, pool: GeminiKeyPool, model: str) -> dict:
    prompt = NOTE_PROMPT.format(
        categories=json.dumps(CATEGORIES, ensure_ascii=False), kinds=json.dumps(KINDS, ensure_ascii=False),
        audiences=json.dumps(AUDIENCES, ensure_ascii=False),
        source=article["source"], title=article["title"], url=article["url"], text=text,
    )
    data = _parse_json(pool.generate(model, prompt, json_mode=True), dict)
    category = data.get("category") if data.get("category") in CATEGORIES else CATEGORIES[1]
    kind = data.get("kind") if data.get("kind") in KINDS else KINDS[0]
    return {
        "title": str(data.get("title") or article["title"]).strip(),
        "category": category,
        "kind": kind,
        "audiences": ",".join(a for a in data.get("audiences", []) if a in AUDIENCES),
        "tags": ",".join(str(t).lstrip("#").strip() for t in data.get("tags", []) if str(t).strip()),
        "summary": str(data.get("summary", "")).strip(),
        "body": str(data.get("body", "")).strip(),
    }


# ───────────────────────── 3) 주간 AX 흐름 ─────────────────────────

WEEKLY_PROMPT = """너는 AX Review의 편집장이다. 이번 주({range}) 게시된 노트들을 읽고
'이번 주 AX 흐름'을 쓴다. 노트 목록에 없는 사실을 만들지 말 것. 존댓말(~습니다)로 쓴다.
{prev}
JSON 객체 하나로만 답하라:
{{
  "headline_em": "흐름을 요약하는 앞 구절 (강조 표시됨, 15자 내외)",
  "headline": "이어지는 뒷 구절: 콜론 뒤에 어떤 산업·기업군이 무엇을 시작했는지",
  "body": "4~5문장. 지난주 대비 관심이 어디서 어디로 옮겨 갔는지, 대표 사례 묶음, 반대 신호까지. 핵심 구절 2개는 **굵게**"
}}

노트 목록:
{notes_json}
"""


def write_weekly(notes: list[dict], range_: str, prev_headline: str, pool: GeminiKeyPool, model: str) -> dict:
    prev = f"지난주 흐름은 '{prev_headline}'였다. 이와 비교해 무엇이 이동했는지 드러내라.\n" if prev_headline else ""
    notes_json = json.dumps(
        [{"title": n["title"], "category": n["category"], "summary": n["summary"]} for n in notes],
        ensure_ascii=False,
    )
    data = _parse_json(
        pool.generate(model, WEEKLY_PROMPT.format(range=range_, prev=prev, notes_json=notes_json), json_mode=True),
        dict,
    )
    return {
        # 제목 줄에는 굵게 표시가 필요 없다 — 모델이 붙인 ** 를 지운다(실측).
        "headline_em": str(data.get("headline_em", "")).replace("**", "").strip(),
        # 모델이 앞 구절과 이어 쓰며 콜론으로 시작하는 경우가 있다(실측) — 앞 구두점 제거.
        "headline": str(data.get("headline", "")).replace("**", "").strip().lstrip(":·- ").strip(),
        "body": str(data.get("body", "")).strip(),
    }
