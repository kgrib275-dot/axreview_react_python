"""관리 > AI 모델 설정 — 글을 쓰는 AI(채점·노트 초안·주간 흐름·브리핑·질문하기)를 Gemini 또는 Claude 로 고른다.

Claude: 모델 선택 + API 키 입력(서버 data/llm_keys.json 에 저장, 화면에는 앞뒤 몇 글자만) + 연결 시험.
임베딩(의미 검색·벡터화)은 공급자와 상관없이 Gemini (pipeline/claude_llm.py 설명 참고).
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import require_admin
from api.routers.admin_jobs import log_action
from pipeline import claude_llm, gemini_keys, jobs, settings_store

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"], dependencies=[Depends(require_admin)])

_KEY_RE = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,200}$")


def _state() -> dict:
    cfg = settings_store.load()["llm"]
    return {
        "provider": cfg.get("provider", "gemini"),          # 고른 값
        "active": claude_llm.provider(),                     # 실제로 쓰이는 값 (Claude 를 골랐어도 키가 없으면 gemini)
        "claude_model": claude_llm.model(),
        "models": [{"id": m, "name": n, "desc": d} for m, n, d in claude_llm.MODELS],
        "claude_key": {"set": bool(claude_llm.api_key()), "masked": claude_llm.masked_key(), "source": claude_llm.key_source()},
        "gemini": {"keys": len(gemini_keys.all_keys()), "model": jobs._model(jobs.config())},
        "uses": ["수집 기사 채점", "노트 초안", "주간 흐름", "데일리 브리핑 종합", "AX 질문하기(도구 검색·웹 검색)"],
        "gemini_only": ["의미 검색·벡터화(임베딩)"],
    }


@router.get("")
def get_llm() -> dict:
    return _state()


@router.put("")
def put_llm(request: Request, body: dict[str, Any]) -> dict:
    cfg = dict(settings_store.load()["llm"])
    provider = body.get("provider", cfg.get("provider"))
    model = body.get("claude_model", cfg.get("claude_model"))
    if provider not in ("gemini", "claude"):
        raise HTTPException(400, "공급자는 gemini 또는 claude 입니다.")
    if model not in claude_llm.MODEL_IDS:
        raise HTTPException(400, "목록에 있는 Claude 모델만 고를 수 있습니다.")
    if provider == "claude" and not claude_llm.api_key():
        raise HTTPException(400, "Claude API 키를 먼저 넣어 주세요.")
    settings_store.save_section("llm", {**cfg, "provider": provider, "claude_model": model})
    log_action(request, "AI 모델 설정", f"{provider} · {model}")
    return {"ok": True, **_state()}


@router.put("/key")
def put_key(request: Request, body: dict[str, Any]) -> dict:
    key = str(body.get("key") or "").strip()
    if not _KEY_RE.match(key):
        raise HTTPException(400, "Claude API 키 형식이 아닙니다 (sk-ant- 로 시작).")
    claude_llm.save_key(key)
    log_action(request, "Claude API 키 저장", claude_llm.masked_key())  # 키 전체는 남기지 않는다
    return {"ok": True, **_state()}


@router.delete("/key")
def delete_key(request: Request) -> dict:
    claude_llm.save_key(None)
    cfg = dict(settings_store.load()["llm"])
    if cfg.get("provider") == "claude" and not claude_llm.api_key():
        settings_store.save_section("llm", {**cfg, "provider": "gemini"})  # 키가 없으면 Gemini 로 돌려 둔다
    log_action(request, "Claude API 키 삭제")
    return {"ok": True, **_state()}


@router.post("/test")
def test(request: Request, body: dict[str, Any] | None = None) -> dict:
    """연결 시험 — 고른 Claude 모델로 아주 짧은 요청 한 번 (토큰 수십 개)."""
    if not claude_llm.api_key():
        raise HTTPException(400, "Claude API 키가 없습니다.")
    try:
        r = claude_llm.test()
    except claude_llm.ClaudeError as e:
        raise HTTPException(400, str(e)) from e
    log_action(request, "Claude 연결 시험", r["model"])
    return {"ok": True, **r}
