"""주간 AX 리포트 PDF (AI_NEWS pipeline/report_pdf.py의 카드덱 방식, 블루 계열 색).

표지(이번 주 AX 흐름 + 통계) → 노트 카드(한 장에 한 편) → 마무리(이번 주 점검 질문)
순서의 1080×1080 정사각 페이지. 화면 미리보기와 PDF가 같은 HTML을 쓴다.
PDF는 data/reports/에 저장하고 /r/<파일> 주소(app/web.py)로 내보낸다 — 최신 호는 누구나, 지난 호는 추천 보상을 받은 구독자만.
"""
from __future__ import annotations

import re
from html import escape

from .db import ROOT

PAGE_PX = 1080
REPORT_DIR = ROOT / "data" / "reports"

DECK_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&family=Archivo:wght@800;900&display=swap');
.deck { font-family:'Noto Sans KR','Malgun Gothic',sans-serif; color:#E8EEF8; }
.deck .page { width:1080px; height:1080px; box-sizing:border-box; position:relative; overflow:hidden;
  page-break-after:always; margin:0 auto 18px; border-radius:28px; background:#050B18; }
.deck .page:last-child { page-break-after:avoid; margin-bottom:0; }
.brand { font-family:'Archivo',sans-serif; font-weight:900; font-size:26px; letter-spacing:.5px; }
.brand span { color:#5BC2F5; } .brand small { font-family:'Noto Sans KR'; font-size:15px; color:#8C9BB5; margin-left:10px; }
.eyebrow { font-family:monospace; font-size:17px; letter-spacing:3px; color:#5BC2F5; text-transform:uppercase; }
.deck .cover { padding:72px 70px 60px; display:flex; flex-direction:column;
  background:radial-gradient(700px circle at 85% 10%, rgba(91,194,245,.25), transparent 60%),
             linear-gradient(150deg,#050B18 0%,#0A2A5A 55%,#0A6FD6 100%); }
.cover h1 { font-size:var(--h1, 58px); line-height:1.25; font-weight:900; margin:26px 0 22px; letter-spacing:-1px; }
.cover h1 em { font-style:normal; color:#5BC2F5; }
.cover .body { font-size:22px; line-height:1.75; color:#D3E6FA; }
.cover .body strong { color:#fff; }
.cover .stats { display:flex; gap:16px; margin-top:auto; }
.cover .stat { flex:1; background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.2); border-radius:22px; padding:22px; }
.cover .stat b { display:block; font-size:40px; font-weight:900; } .cover .stat span { font-size:17px; color:#CFE9FF; }
.deck .card { padding:64px 70px 56px; display:flex; flex-direction:column;
  background:linear-gradient(180deg,#0F1F3D 0%,#0B1730 100%); }
.card .top { display:flex; justify-content:space-between; align-items:center; }
.card .rank { font-family:'Archivo'; font-size:64px; font-weight:900; color:#2E9BEA; line-height:1; }
.badge { display:inline-block; font-family:monospace; font-size:17px; color:#5BC2F5; border:1px solid rgba(91,194,245,.45);
  border-radius:8px; padding:4px 12px; margin-right:8px; }
.card h2 { font-size:40px; line-height:1.4; font-weight:900; margin:26px 0 12px; }
.card .src { font-size:18px; color:#8C9BB5; margin-bottom:26px; }
.card .summary { font-size:23px; line-height:1.8; color:#B5C2D8; }
.card .points { margin-top:26px; padding:22px 26px; border-radius:18px; background:rgba(10,111,214,.14); border:1px solid #16274A; }
.card .points li { font-size:19px; line-height:1.65; color:#D3E6FA; margin:6px 0; }
.card .aud { margin-top:auto; display:flex; gap:10px; flex-wrap:wrap; }
.card .aud span { font-size:17px; padding:6px 14px; border-radius:999px; background:rgba(10,111,214,.25); color:#A9D6FF; }
.deck .end { padding:72px 70px; display:flex; flex-direction:column; background:linear-gradient(160deg,#0B1730,#050B18); }
.end h2 { font-size:46px; font-weight:900; margin:26px 0 30px; }
.end ol { margin:0; padding-left:30px; } .end li { font-size:24px; line-height:1.7; color:#D3E6FA; margin:14px 0; }
.end .foot { margin-top:auto; font-size:17px; color:#8C9BB5; }
.pageno { position:absolute; right:40px; bottom:30px; font-family:monospace; font-size:15px; color:#8C9BB5; }
"""

_CHECKLIST = [
    "이번 주 사례 중 우리 업무에 바로 옮길 수 있는 것은 무엇인가?",
    "그 업무의 현재 처리 시간·오류율을 측정하고 있는가?",
    "에이전트에 줄 권한·승인 지점·중단 기준이 정해져 있는가?",
    "필요한 데이터의 위치·품질·접근 권한을 확인했는가?",
    "2~6주 파일럿의 성공 기준과 확산 조건을 합의했는가?",
]


def _bold(text: str) -> str:
    parts = escape(text).split("**")
    return "".join(p if i % 2 == 0 else f"<strong>{p}</strong>" for i, p in enumerate(parts))


def _points(body: str, n: int = 3) -> list[str]:
    """노트 본문의 '핵심 포인트' 불릿을 앞에서 n개 뽑는다."""
    m = re.search(r"###\s*핵심 포인트(.*?)(?:\n###|\Z)", body or "", re.S)
    if not m:
        return []
    items = [re.sub(r"^\s*[-*]\s*", "", ln).replace("**", "").strip() for ln in m.group(1).splitlines()
             if re.match(r"^\s*[-*]\s+", ln)]
    return [i[:140] + ("…" if len(i) > 140 else "") for i in items[:n]]


def build_deck_html(issue: dict | None, notes: list[dict], stats: dict) -> str:
    total = len(notes) + 2
    title = f"<em>{escape(issue['headline_em'])}</em> {escape(issue['headline'])}" if issue else "이번 주 AX 노트"
    week = f"{escape(issue['week'])} · {escape(issue['range'])}" if issue else ""
    # 헤드라인이 길면 글자를 줄여 본문·통계가 표지 안에 들어가게 한다.
    head_len = len(f"{issue['headline_em']} {issue['headline']}") if issue else 10
    h1_size = 58 if head_len <= 32 else 48 if head_len <= 50 else 40
    pages = [f"""
<section class="page cover" style="--h1:{h1_size}px">
  <div class="brand">AX <span>REVIEW</span><small>주간 AX 리포트</small></div>
  <div class="eyebrow" style="margin-top:46px">This Week · {week}</div>
  <h1>{title}</h1>
  <div class="body">{_bold(issue['body']) if issue else ''}</div>
  <div class="stats">
    <div class="stat"><b>{stats.get('notes', len(notes))}</b><span>이번 주 노트</span></div>
    <div class="stat"><b>{stats.get('collected', 0)}</b><span>검토한 기사</span></div>
    <div class="stat"><b>{stats.get('sources', 0)}</b><span>수집 소스</span></div>
  </div>
  <div class="pageno">1 / {total}</div>
</section>"""]
    for i, n in enumerate(notes, start=1):
        points = "".join(f"<li>{escape(p)}</li>" for p in _points(n.get("body", "")))
        aud = "".join(f"<span>{escape(a)}</span>" for a in n["audiences"].split(",") if a)
        pages.append(f"""
<section class="page card">
  <div class="top"><div><span class="badge">{escape(n['category'])}</span><span class="badge">{escape(n['kind'])}</span></div>
    <div class="rank">{i:02d}</div></div>
  <h2>{escape(n['title'])}</h2>
  <div class="src">{escape(n['source'])} · {n['published'].replace('-', '.')}</div>
  <div class="summary">{escape(n['summary'])}</div>
  {f'<ul class="points">{points}</ul>' if points else ''}
  <div class="aud">{aud}</div>
  <div class="pageno">{i + 1} / {total}</div>
</section>""")
    checklist = "".join(f"<li>{escape(c)}</li>" for c in _CHECKLIST)
    pages.append(f"""
<section class="page end">
  <div class="brand">AX <span>REVIEW</span></div>
  <div class="eyebrow" style="margin-top:46px">Checklist</div>
  <h2>이번 주 점검 질문</h2>
  <ol>{checklist}</ol>
  <div class="foot">© AX Review · 노트 원문과 전체 목록은 사이트에서 볼 수 있습니다.</div>
  <div class="pageno">{total} / {total}</div>
</section>""")
    return f"<div class='deck'>{''.join(pages)}</div>"


def full_html(deck: str) -> str:
    return f'<!doctype html><meta charset="utf-8"><style>body{{margin:0;background:#050B18}}{DECK_CSS}</style>{deck}'


def render_pdf(html: str) -> bytes:
    """Playwright로 PDF를 만든다. 번들 Chromium이 없으면 PC에 설치된 Edge를 쓴다.

    Windows의 Streamlit(Tornado)은 SelectorEventLoop 정책을 강제하는데 Playwright 동기
    API는 Proactor가 필요하다 — 호출하는 동안만 정책을 바꾼다(AI_NEWS/hana_p 실측)."""
    import asyncio
    import sys

    from playwright.sync_api import sync_playwright

    old = None
    if sys.platform == "win32":
        old = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:  # noqa: BLE001 - 번들 브라우저 미설치
                browser = p.chromium.launch(channel="msedge")
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            pdf = page.pdf(width=f"{PAGE_PX}px", height=f"{PAGE_PX}px", print_background=True,
                           margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
            browser.close()
            return pdf
    finally:
        if old is not None:
            asyncio.set_event_loop_policy(old)


def report_filename(issue: dict | None) -> str:
    key = issue.get("week_start") or f"issue{issue['id']}" if issue else "latest"
    return f"axreview_{key}.pdf"


def report_path(issue: dict | None):
    return REPORT_DIR / report_filename(issue)


def report_url(site_url: str, issue: dict | None) -> str:
    return f"{site_url.rstrip('/')}/r/{report_filename(issue)}"
