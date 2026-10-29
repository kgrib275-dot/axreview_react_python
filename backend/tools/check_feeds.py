r"""후보 수집처 점검 — config/sources_candidates.yaml 의 RSS 주소를 실제로 읽어 본다.

실행:  venv\Scripts\python tools\check_feeds.py            (기본: 후보 파일)
       venv\Scripts\python tools\check_feeds.py config\sources.yaml   (기존 소스 점검)
출력:  각 소스의 상태(OK/빈 피드/오류)·글 수·가장 최근 글 날짜, 끝에 sources.yaml에 붙여 넣을 valid 블록.
       결과 파일: data/feed_check.yaml
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
UA = "Mozilla/5.0 (compatible; AXReview feed check; +https://github.com/)"
KEEP = ("name", "group", "type", "published_within_hours", "site", "url")


def latest(entries) -> str:
    best = None
    for e in entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if t:
            d = datetime(*t[:6], tzinfo=timezone.utc)
            best = d if not best or d > best else best
    return best.strftime("%Y-%m-%d") if best else "-"


def check(src: dict, client: httpx.Client) -> tuple[str, int, str]:
    try:
        r = client.get(src["url"], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}", 0, "-"
    if r.status_code != 200:
        return f"HTTP {r.status_code}", 0, "-"
    f = feedparser.parse(r.content)
    if not f.entries:
        return "EMPTY (RSS 아님/비어 있음)", 0, "-"
    return "OK", len(f.entries), latest(f.entries)


def main() -> None:
    path = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "config/sources_candidates.yaml")
    sources = [s for s in yaml.safe_load(path.read_text(encoding="utf-8"))["sources"] if s.get("type") == "rss"]
    print(f"{len(sources)}곳 점검: {path.name}\n")
    valid, report = [], []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for s in sources:
            status, n, last = check(s, client)
            print(f"{'✅' if status == 'OK' else '❌'} {s['name']:<34} {status:<24} 글 {n:>3}  최근 {last}")
            report.append({"name": s["name"], "url": s["url"], "status": status, "entries": n, "latest": last})
            if status == "OK":
                valid.append({k: s[k] for k in KEEP if k in s})
            time.sleep(0.3)
    out = ROOT / "data" / "feed_check.yaml"
    out.write_text(yaml.safe_dump({"checked_at": datetime.now().isoformat(timespec="seconds"), "report": report,
                                   "valid": valid}, allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    print(f"\nOK {len(valid)} / {len(sources)}  → {out}  의 valid: 블록을 config/sources.yaml 의 sources: 아래에 붙여 넣으세요.")


if __name__ == "__main__":
    main()
