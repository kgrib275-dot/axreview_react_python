from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..models import Item

_USER_AGENT = "AiAxRadar/1.0 (AI news aggregator; read-only)"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_API_BASE = "https://oauth.reddit.com"


async def _get_access_token(client_id: str, client_secret: str, http_client: httpx.AsyncClient) -> str | None:
    """Reddit의 client_credentials(앱 전용) OAuth 토큰을 발급받는다 — 사용자 계정
    아이디/비밀번호 없이 공개 데이터 읽기 권한만 받는 방식이라, 개인/회사 Reddit
    계정 자격증명을 저장할 필요가 없다. 비인증 www.reddit.com 엔드포인트는 이 서버
    IP에서 403으로 막혀 있었는데, oauth.reddit.com은 이 인증만 있으면 막히지 않는다."""
    try:
        resp = await http_client.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        return resp.json().get("access_token")
    except Exception:
        return None


async def collect_reddit(
    source_cfg: dict, http_client: httpx.AsyncClient, client_id: str = "", client_secret: str = "",
) -> list[Item]:
    subreddits = source_cfg.get("subreddits", [])
    if not subreddits or not client_id or not client_secret:
        return []

    token = await _get_access_token(client_id, client_secret, http_client)
    if not token:
        return []

    multi = "+".join(subreddits)
    resp = await http_client.get(
        f"{_API_BASE}/r/{multi}/new",
        params={"limit": source_cfg.get("limit", 25)},
        headers={"User-Agent": _USER_AGENT, "Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data = resp.json()

    min_score = source_cfg.get("min_score", 0)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=source_cfg.get("published_within_hours", 24))

    items = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        if post.get("score", 0) < min_score:
            continue
        created = datetime.fromtimestamp(post["created_utc"], tz=timezone.utc)
        if created < cutoff:
            continue
        url = post.get("url") or f"https://www.reddit.com{post.get('permalink', '')}"
        items.append(Item(
            title=post.get("title", ""),
            url=url,
            source=source_cfg.get("name", "Reddit"),
            source_type="reddit",
            published_at=created,
            excerpt=(post.get("selftext") or "")[:300],
        ))
    return items
