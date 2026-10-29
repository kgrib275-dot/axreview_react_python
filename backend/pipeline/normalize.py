from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip().lower())
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, urlencode(query), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
