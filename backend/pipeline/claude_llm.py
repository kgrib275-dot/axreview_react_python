"""Claude(Anthropic) 호출 — 관리 > AI 모델 설정에서 'Claude'를 고르면 Gemini 대신 쓰인다.

쓰는 곳: 수집 기사 채점, 노트 초안, 주간 흐름, 데일리 브리핑 종합, AX 질문하기(도구 검색·웹 검색).
임베딩(의미 검색·벡터화)은 Claude 에 같은 기능이 없어 공급자와 상관없이 Gemini 를 쓴다.

- API 키: 관리 화면에서 넣으면 data/llm_keys.json(웹으로 열리지 않는 폴더, git 제외)에 저장, 화면에는 앞뒤 몇 글자만.
  없으면 .env 의 ANTHROPIC_API_KEY.
- 모델: claude-opus-5-5(기본)·claude-sonnet-5-5·claude-haiku-5-5·claude-fable-5-1. 생각(thinking)은 모델 기본(adaptive)에 맡기고
  작업마다 effort 로 깊이를 정한다 (채점 low, 나머지 medium).
- 안전 분류기가 거절하면(stop_reason=refusal) 같은 요청을 다른 모델이 이어받도록 서버 측 fallbacks="default" 를 켠다
  (Haiku 는 미지원이라 끈다). 끝까지 거절이면 빈 답 → 호출부가 실패로 처리한다.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import threading
from pathlib import Path

from . import settings_store
from .db import ROOT

log = logging.getLogger(__name__)

# (모델 ID, 화면 이름, 설명) — 위가 기본
MODELS = [
    ("claude-opus-5-5", "Claude Opus 5.5", "기본 · 균형 (입력 $4 / 출력 $20 per 1M 토큰)"),
    ("claude-sonnet-5-5", "Claude Sonnet 5.5", "빠르고 저렴 ($2 / $10)"),
    ("claude-haiku-5-5", "Claude Haiku 5.5", "가장 저렴 · 단순 작업 ($0.10 / $0.50)"),
    ("claude-fable-5-1", "Claude Fable 5.1", "최고 성능 · 가장 비쌈 ($10 / $50)"),
]
MODEL_IDS = [m for m, _, _ in MODELS]
_FALLBACK_OK = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1"}  # 서버 측 fallbacks="default" 지원
_DYNAMIC_WEB = {"claude-opus-5-5", "claude-sonnet-5-5"}  # web_search_20260209 지원 (그 밖은 기본판 20250305)
_FALLBACK_BETA = "server-side-fallback-2026-07-01"

KEY_FILE = ROOT / "data" / "llm_keys.json"
_lock = threading.Lock()


class ClaudeError(Exception):
    """Claude 호출 실패 (키 없음·인증·한도·거절 등) — 화면에 보여 줄 짧은 문구."""


# ───────────────────────── 설정·키 ─────────────────────────

def provider() -> str:
    """'gemini' 또는 'claude' (관리 > AI 모델 설정). Claude 를 골랐어도 키가 없으면 gemini 로 동작한다."""
    cfg = settings_store.load().get("llm") or {}
    return "claude" if cfg.get("provider") == "claude" and api_key() else "gemini"


def model() -> str:
    m = (settings_store.load().get("llm") or {}).get("claude_model") or MODEL_IDS[0]
    return m if m in MODEL_IDS else MODEL_IDS[0]


def _read_keys() -> dict:
    try:
        return json.loads(Path(KEY_FILE).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def api_key() -> str:
    return (_read_keys().get("anthropic") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()


def key_source() -> str:
    if (_read_keys().get("anthropic") or "").strip():
        return "admin"
    return "env" if os.environ.get("ANTHROPIC_API_KEY", "").strip() else ""


def masked_key() -> str:
    k = api_key()
    return f"{k[:10]}…{k[-4:]}" if len(k) > 16 else ("설정됨" if k else "")


def save_key(key: str | None) -> None:
    """관리 화면에서 넣은 키 저장 (None 이면 지움). 임시 파일에 쓰고 바꿔 끼운다."""
    with _lock:
        data = _read_keys()
        if key:
            data["anthropic"] = key.strip()
        else:
            data.pop("anthropic", None)
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = KEY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, KEY_FILE)
    _clients.clear()


# ───────────────────────── 호출 ─────────────────────────

_clients: dict[str, object] = {}


def _client():
    import anthropic
    key = api_key()
    if not key:
        raise ClaudeError("Claude API 키가 없습니다 — 관리 > AI 모델 설정에서 넣어 주세요.")
    c = _clients.get(key)
    if c is None:
        # 429·5xx·연결 오류는 SDK 가 자동으로 다시 시도한다 (2회). 멈춘 요청이 작업 스레드를 붙잡지 않게 시간 제한.
        c = _clients[key] = anthropic.Anthropic(api_key=key, timeout=180.0, max_retries=2)
    return c


def _request(m: str, effort: str, max_tokens: int, system: str, messages: list, tools: list | None = None):
    """한 번 호출 (스트리밍으로 받아 긴 응답도 시간 초과 없이). 응답 메시지를 돌려준다."""
    import anthropic
    kw: dict = {"model": m, "max_tokens": max_tokens, "system": system, "messages": messages,
                "output_config": {"effort": effort}}
    if tools:
        kw["tools"] = tools
    if m in _FALLBACK_OK:
        kw.update(betas=[_FALLBACK_BETA], fallbacks="default")
    try:
        with _client().beta.messages.stream(**kw) as stream:
            return stream.get_final_message()
    except anthropic.AuthenticationError as e:
        raise ClaudeError("Claude API 키가 올바르지 않습니다.") from e
    except anthropic.PermissionDeniedError as e:
        raise ClaudeError("이 키로는 이 모델을 쓸 수 없습니다.") from e
    except anthropic.NotFoundError as e:
        raise ClaudeError(f"모델을 찾을 수 없습니다: {m}") from e
    except anthropic.RateLimitError as e:
        raise ClaudeError("Claude 사용 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요.") from e
    except anthropic.BadRequestError as e:
        raise ClaudeError(f"Claude 요청 오류: {str(e.message)[:200]}") from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(f"Claude 서버 오류 ({e.status_code}). 잠시 후 다시 시도해 주세요.") from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError("Claude 에 연결하지 못했습니다 (네트워크).") from e


def _text(msg) -> str:
    if msg.stop_reason == "refusal":
        log.warning("Claude 가 요청을 거절했습니다: %s", getattr(getattr(msg, "stop_details", None), "category", None))
        return ""
    return "".join(b.text for b in msg.content if b.type == "text").strip()


def generate(prompt: str, json_mode: bool = False, effort: str = "medium", max_tokens: int = 32000) -> str:
    """한 번 묻고 답 받기 (채점·노트 초안·주간 흐름·브리핑). json_mode 면 JSON 만 돌려 달라고 지시한다."""
    system = "너는 AX Review 의 편집 도우미다."
    if json_mode:
        system += " 요청한 JSON 하나만 출력하라. 설명·마크다운 코드블록 없이 JSON 자체만."
    msg = _request(model(), effort, max_tokens, system, [{"role": "user", "content": prompt}])
    text = _text(msg)
    if not text:
        raise ClaudeError("Claude 가 답을 만들지 못했습니다 (거절 또는 빈 응답).")
    if msg.stop_reason == "max_tokens":
        log.warning("Claude 응답이 max_tokens(%d)에서 잘렸습니다", max_tokens)
    return text


# ── 질문하기: 도구 검색 (search_notes·search_articles·weekly_flows) ──

def _tool_specs(funcs) -> list[dict]:
    """agent_chat 의 파이썬 함수 → Claude 도구 정의 (이름·설명·입력 스키마)."""
    import typing
    out = []
    for f in funcs:
        hints = typing.get_type_hints(f)
        props = {}
        for name, p in inspect.signature(f).parameters.items():
            t = hints.get(name, str)
            props[name] = {"type": "integer" if t is int else "number" if t is float else "string"}
        doc = inspect.getdoc(f) or ""
        out.append({"name": f.__name__, "description": doc[:1000],
                    "input_schema": {"type": "object", "properties": props, "additionalProperties": False}})
    return out


ASK_MAX_TOKENS = 4000      # 질문하기 답 한 번의 출력 상한 (생각 포함) — 공개 기능이라 한 질문의 비용을 묶는다
TOOL_RESULT_CHARS = 15000  # 도구 결과 한 건을 모델에 넘기는 최대 글자 수


def chat(system: str, history: list[dict], message: str, funcs=None, web_search: bool = False,
         max_rounds: int = 4) -> str:
    """질문하기 대화. funcs(파이썬 함수)를 도구로 주고, 모델이 부르면 실행해 결과를 돌려주는 걸 반복한다.
    web_search 면 Anthropic 서버의 웹 검색 도구를 쓴다 (실행은 서버가 하므로 루프가 필요 없다)."""
    m = model()
    tools: list[dict] = []
    by_name = {}
    if funcs:
        tools += _tool_specs(funcs)
        by_name = {f.__name__: f for f in funcs}
    if web_search:
        tools.append({"type": "web_search_20260209" if m in _DYNAMIC_WEB else "web_search_20250305",
                      "name": "web_search", "max_uses": 2})
    messages: list = [{"role": "user" if t["role"] == "user" else "assistant", "content": t["content"]}
                      for t in history if t.get("content")]
    messages.append({"role": "user", "content": message})
    msg = None
    for _ in range(max_rounds):
        msg = _request(m, "medium", ASK_MAX_TOKENS, system, messages, tools or None)
        if msg.stop_reason == "pause_turn":  # 서버 도구(웹 검색)가 길어져 잠시 멈춤 — 이어서 보낸다
            messages.append({"role": "assistant", "content": msg.content})
            continue
        uses = [b for b in msg.content if b.type == "tool_use"]
        if msg.stop_reason != "tool_use" or not uses:
            break
        messages.append({"role": "assistant", "content": msg.content})  # 생각 블록까지 그대로 돌려준다
        results = []
        for b in uses:
            f = by_name.get(b.name)
            try:
                if f is None:
                    raise ValueError(f"없는 도구: {b.name}")
                args = b.input if isinstance(b.input, dict) else {}
                allowed = inspect.signature(f).parameters  # 함수가 받는 인자만 넘긴다 (모르는 인자는 버림)
                out = f(**{k: v for k, v in args.items() if k in allowed})
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)[:TOOL_RESULT_CHARS]})
            except Exception as e:  # noqa: BLE001 - 도구 실패는 모델에게 알려 다른 길을 찾게 한다
                log.warning("질문하기 도구 %s 실패: %s", b.name, e)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": f"오류: {e}", "is_error": True})
        messages.append({"role": "user", "content": results})  # 여러 결과는 한 메시지에
    return _text(msg) if msg is not None else ""


def test() -> dict:
    """관리 화면 '연결 시험' — 아주 짧은 요청 한 번."""
    msg = _request(model(), "low", 2000, "짧게 답하라.", [{"role": "user", "content": "'연결 성공'이라고만 답해."}])
    return {"model": msg.model, "answer": _text(msg)[:100],
            "tokens": {"input": msg.usage.input_tokens, "output": msg.usage.output_tokens}}
