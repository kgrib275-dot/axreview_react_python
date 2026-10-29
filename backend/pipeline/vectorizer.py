"""노트·기사 임베딩과 의미 검색 (AI_NEWS pipeline/vectorizer.py 기반).

AI_NEWS는 기사만 벡터화했지만, AX Review는 게시 노트가 핵심 자산이라 노트를 먼저
벡터화하고, AX 점수 3점 이상 기사도 함께 벡터화해 "AX 질문하기"의 근거로 쓴다.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from . import db, gemini_keys

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768
# 기사는 시의성이 있어 최근 N일만 검색한다(AI_NEWS와 같은 방침). 노트는 기간 제한 없음.
ARTICLE_RECENCY_DAYS = 90


def has_api_keys() -> bool:
    return bool(gemini_keys.all_keys())


def embed_text(text: str) -> list[float] | None:
    """키가 없거나 모든 키가 실패하면 None (예외를 던지지 않는다 — 검색이 실패해도
    화면은 단어 검색으로 계속 동작해야 한다)."""
    text = (text or "").strip()
    if not text:
        return None
    from google.genai import types

    for key in gemini_keys.healthy_keys(EMBEDDING_MODEL):
        client = gemini_keys.client(key)  # 지역 변수로 잡아 둬야 호출 전에 닫히지 않는다
        try:
            resp = client.models.embed_content(
                model=EMBEDDING_MODEL, contents=text[:8000],
                config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIM),
            )
            gemini_keys.report_success(EMBEDDING_MODEL, key)
            return list(resp.embeddings[0].values)
        except Exception as e:  # noqa: BLE001 - 다음 키로
            gemini_keys.report_error(EMBEDDING_MODEL, key, e)
    return None


def _note_text(n: dict) -> str:
    return f"{n['title']}\n{n['summary']}\n{n['tags']}\n{(n.get('body') or '')[:3000]}"


def _article_text(a: dict) -> str:
    return f"{a['title']}\n{a.get('summary_ko') or a.get('excerpt') or ''}"


def vectorize(limit: int = 200) -> dict:
    """임베딩이 없는 게시 노트와 3점 이상 기사를 최대 limit건 벡터화한다."""
    result = {}
    remaining = limit
    for table, to_text in (("notes", _note_text), ("articles", _article_text)):
        rows = db.missing_embeddings(table, remaining)
        workers = max(1, min(5, gemini_keys.healthy_count(EMBEDDING_MODEL)))
        with ThreadPoolExecutor(max_workers=workers) as ex:  # 정상 키 수만큼 병렬
            vectors = list(ex.map(lambda r: embed_text(to_text(r)), rows))
        done = 0
        for r, vec in zip(rows, vectors):
            if vec:
                db.set_embedding(table, r["id"] if table == "notes" else r["url_hash"], vec)
                done += 1
        result[table] = {"pending": len(rows), "embedded": done}
        remaining -= len(rows)
        if remaining <= 0:
            break
    return result


def search(query: str, table: str = "notes", top_k: int = 5) -> list[dict]:
    """질의와 가까운 순으로 top_k건. 각 행에 similarity(코사인, 1에 가까울수록 유사)를 붙인다."""
    vec = embed_text(query)
    if not vec:
        return []
    rows, mat = _matrix(table)
    if not rows:
        return []
    import numpy as np
    q = np.asarray(vec, dtype=np.float32)
    sims = mat @ (q / (np.linalg.norm(q) or 1.0))
    top = np.argsort(-sims)[:top_k]
    return [{**rows[i], "similarity": float(sims[i])} for i in top]


_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def _matrix(table: str):
    """(행 목록, 정규화한 임베딩 행렬). 행 수·최근 시각이 같으면 메모리 사본을 쓴다 — 질의마다 수천 개의 JSON 벡터를
    다시 읽고 파이썬으로 코사인을 계산하던 것을 없앤다. 10분이 지나면 새로 읽는다(임베딩 재생성 반영)."""
    import time
    import numpy as np
    since = ARTICLE_RECENCY_DAYS if table == "articles" else None
    sig = db.embedding_signature(table, since)
    with _CACHE_LOCK:
        hit = _CACHE.get(table)
        if hit and hit[0] == sig and time.time() - hit[1] < 600:
            return hit[2], hit[3]
    rows = db.embedded_rows(table, since_days=since)
    if not rows:
        return [], None
    mat = np.asarray([r.pop("embedding") for r in rows], dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    mat = mat / np.where(norms == 0, 1.0, norms)
    with _CACHE_LOCK:
        _CACHE[table] = (sig, time.time(), rows, mat)
    return rows, mat
