"""구독 이메일 도메인 확인 — 오타·없는 도메인이면 신청 전에 알려 준다.

- 자주 쓰는 메일 도메인과 한두 글자 다르면(gmial.com, naver.con) 고칠 주소를 제안한다.
- DNS 에 메일 서버(MX)나 주소(A/AAAA)가 없는 도메인은 받을 수 없는 주소로 본다.
- DNS 가 응답하지 않거나 느리면(사내망 등) 막지 않는다 — 확인 메일 링크가 최종 확인이다.
"""
from __future__ import annotations

import difflib
import threading
import time

COMMON = ["gmail.com", "naver.com", "daum.net", "hanmail.net", "kakao.com", "nate.com", "outlook.com", "hotmail.com",
          "live.com", "yahoo.com", "icloud.com", "me.com", "korea.kr"]
_TLD_FIX = {"con": "com", "cmo": "com", "ocm": "com", "comm": "com", "co": "com", "nte": "net", "ner": "net", "met": "net"}

_cache: dict[str, tuple[float, bool]] = {}
_lock = threading.Lock()
_TTL = 86400


def suggest(domain: str) -> str | None:
    """자주 쓰는 도메인의 오타로 보이면 고친 도메인."""
    d = domain.lower()
    if d in COMMON:
        return None
    m = difflib.get_close_matches(d, COMMON, n=1, cutoff=0.8)
    if m:
        return m[0]
    head, _, tld = d.rpartition(".")
    if head and tld in _TLD_FIX and f"{head}.{_TLD_FIX[tld]}" in COMMON:
        return f"{head}.{_TLD_FIX[tld]}"
    return None


def _resolvable(domain: str) -> bool:
    import dns.exception
    import dns.resolver

    r = dns.resolver.Resolver()
    r.lifetime = 3.0
    try:
        r.resolve(domain, "MX")
        return True
    except dns.resolver.NXDOMAIN:
        return False
    except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        pass  # MX 가 없으면 A/AAAA 로 받는 도메인도 있다 (RFC 5321)
    except dns.exception.DNSException:
        return True  # 시간 초과 등 — 판단할 수 없으면 막지 않는다
    for rtype in ("A", "AAAA"):
        try:
            r.resolve(domain, rtype)
            return True
        except dns.resolver.NXDOMAIN:
            return False
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            continue
        except dns.exception.DNSException:
            return True
    return False


def domain_ok(domain: str) -> bool:
    d = domain.lower()
    if d in COMMON:
        return True
    hit = _cache.get(d)
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    ok = _resolvable(d)
    with _lock:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[d] = (time.monotonic(), ok)
    return ok


def problem(email: str, typo_ok: bool = False) -> dict | None:
    """받을 수 없어 보이는 주소면 {message, suggest(고친 주소|None)}, 괜찮으면 None.

    오타 제안은 실제로 있는 도메인(mate.com 등)일 수도 있어 typo_ok=True(화면의 '입력한 주소 그대로')면 건너뛴다.
    없는 도메인은 그대로 막는다."""
    local, _, domain = email.rpartition("@")
    fix = None if typo_ok else suggest(domain)
    if fix:
        return {"message": f"'{domain}' 이(가) 맞나요? 혹시 '{fix}' 인가요?", "suggest": f"{local}@{fix}"}
    if not domain_ok(domain):
        return {"message": f"'{domain}' 은(는) 메일을 받을 수 없는 도메인입니다. 주소를 다시 확인해 주세요.", "suggest": None}
    return None
