"""외부 URL 가져오기 안전장치 (SSRF 방지) — 기사 원문처럼 피드가 준 주소를 서버가 직접 받을 때 쓴다.

- http(s)만 허용, 호스트를 IP로 풀어 사설·루프백·링크로컬·예약 대역이면 막는다 (127.0.0.1의 관리 화면,
  사내망, 클라우드 메타데이터 169.254.169.254 등).
- 리다이렉트는 직접 따라가며 단계마다 다시 검사하고, 응답은 max_bytes까지만 읽는다.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; AXReviewBot/1.0)"}


class BlockedURL(httpx.HTTPError):
    pass


def is_public_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            return False
    return True


def get(url: str, timeout: float = 20, max_bytes: int = 3_000_000, max_redirects: int = 5) -> httpx.Response:
    """검사를 통과한 주소만 GET. 본문은 max_bytes에서 자른다."""
    for _ in range(max_redirects + 1):
        if not is_public_http_url(url):
            raise BlockedURL(f"허용되지 않는 주소: {url[:120]}")
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=False, headers=UA) as resp:
            if resp.is_redirect:
                url = urljoin(url, resp.headers.get("location", ""))
                continue
            body = b""
            for chunk in resp.iter_bytes():
                body += chunk
                if len(body) >= max_bytes:
                    break
            resp.raise_for_status()
            return httpx.Response(resp.status_code, headers=resp.headers, content=body[:max_bytes], request=resp.request)
    raise BlockedURL("리다이렉트가 너무 많습니다")
