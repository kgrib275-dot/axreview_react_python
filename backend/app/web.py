"""검색 엔진·메신저 미리보기용 서버 렌더링 페이지 (api/main.py가 API·SPA보다 앞에 등록한다).

React 화면은 브라우저에서 그려져 검색 엔진·메신저 미리보기가 내용을 못 읽는다. 그래서:
- /n/{id}, /n/          노트 본문을 서버에서 HTML로 — 구글·네이버 색인용 (같은 도메인, 항상 DB 최신)
- /sitemap.xml, /robots.txt
- /s/t/{유형}, /s/d?a=, /s/q?…, /s/terms?…   결과별 공유 주소 — 결과마다 다른 og:image·제목을 주고 사람은 앱으로 보낸다
- /r/{파일}.pdf          주간 PDF — 최신 호는 누구나, 지난 호는 추천 보상을 받은 구독자만 (pipeline/referral.py)
모든 값은 이스케이프하고, 주소 값은 정규식으로 거른다.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from html import escape
from urllib.parse import quote, urlencode

from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from pipeline import db

_TYPE_RE = re.compile(r"^[SC][TP][WF][DI]$")
_DIAG_RE = re.compile(r"^[0-3]{12}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _site(request: Request) -> str:
    return (os.environ.get("SITE_URL") or str(request.base_url)).rstrip("/")


# ───────────────────────── 노트 본문 (마크다운 일부만) ─────────────────────────

def _inline(text: str) -> str:
    parts = escape(text).split("**")
    return "".join(p if i % 2 == 0 else f"<strong>{p}</strong>" for i, p in enumerate(parts))


def md_html(body: str) -> str:
    """노트 본문 형식(### 제목, -/*/1. 목록, **굵게**, 문단)만 HTML로 바꾼다."""
    out, items, kind, para = [], [], "", []

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + f"</{kind}>")
            items.clear()
        kind = ""

    for raw in (body or "").splitlines():
        line = raw.strip()
        m = re.match(r"^(?:[-*]|(\d+)\.)\s+(.+)$", line)
        if line.startswith("#"):
            flush_para(); flush_list()
            out.append(f"<h2>{_inline(line.lstrip('#').strip())}</h2>")
        elif m:
            flush_para()
            k = "ol" if m.group(1) else "ul"
            if kind and kind != k:
                flush_list()
            kind = k
            items.append(m.group(2))
        elif not line:
            flush_para(); flush_list()
        else:
            flush_list()
            para.append(line)
    flush_para(); flush_list()
    return "\n".join(out)


_STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#050B18;color:#E8EEF8;font:17px/1.8 'IBM Plex Sans KR','Malgun Gothic',sans-serif}
a{color:#5BC2F5}header,main,footer{max-width:780px;margin:0 auto;padding:0 20px}
header{display:flex;justify-content:space-between;align-items:center;padding-top:22px;padding-bottom:22px;border-bottom:1px solid #16274A}
.logo{font-weight:900;font-size:20px;color:#E8EEF8;text-decoration:none}.logo b{color:#2E9BEA}
.btn{display:inline-block;background:#0A6FD6;color:#fff;text-decoration:none;font-weight:700;padding:9px 18px;border-radius:999px;font-size:15px}
.meta{font:700 15px/1.5 inherit;color:#8FD0FF;margin:34px 0 6px}
h1{font-size:30px;line-height:1.4;margin:6px 0 14px}h2{font-size:21px;margin:34px 0 8px;color:#CFE9FF}
.sum{color:#C9D4E6;border-left:3px solid #2E9BEA;padding:4px 0 4px 16px}
li{margin:4px 0}strong{color:#fff}
.src{margin:30px 0;padding:16px 18px;border:1px solid #16274A;border-radius:12px;background:#0B1730;font-size:15px}
.list a{display:block;padding:14px 0;border-bottom:1px solid #16274A;text-decoration:none;color:#E8EEF8}
.list small{display:block;color:#A0AEC6;font-size:15px}
footer{color:#A0AEC6;font-size:15px;padding-top:30px;padding-bottom:40px}
"""


def _page(title: str, desc: str, canonical: str, body: str, og_image: str, extra_head: str = "") -> HTMLResponse:
    t, d = escape(title), escape(desc)
    return HTMLResponse(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{t}</title>
<meta name="description" content="{d}"><link rel="canonical" href="{escape(canonical)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="AX Review"><meta property="og:locale" content="ko_KR">
<meta property="og:title" content="{t}"><meta property="og:description" content="{d}"><meta property="og:url" content="{escape(canonical)}">
<meta property="og:image" content="{escape(og_image)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{t}"><meta name="twitter:description" content="{d}">
<meta name="twitter:image" content="{escape(og_image)}">{extra_head}
<style>{_STYLE}</style></head><body>
<header><a class="logo" href="/">AX <b>REVIEW</b></a><a class="btn" href="/letter">뉴스레터 미리 보기</a></header>
<main>{body}</main><footer>© {datetime.now():%Y} AX Review · 기업 AX를 위해 읽은 자료를 정리한 노트입니다.</footer></body></html>""",
                        headers={"Cache-Control": "public, max-age=300"})


def note_page(request: Request) -> Response:
    try:
        n = db.note(int(request.path_params["id"]))
    except (TypeError, ValueError):
        n = None
    if not n or n.get("status") != "published":
        return HTMLResponse("<h1>노트를 찾을 수 없습니다</h1><a href='/n/'>노트 목록</a>", status_code=404)
    site = _site(request)
    url = f"{site}/n/{n['id']}"
    ld = ('{"@context":"https://schema.org","@type":"Article","headline":%s,"datePublished":"%s","inLanguage":"ko",'
          '"publisher":{"@type":"Organization","name":"AX Review"},"mainEntityOfPage":"%s"}') % (
        _json_str(n["title"]), escape(n["published"]), escape(url))
    tags = " · ".join(t for t in (n.get("tags") or "").split(",") if t)
    body = f"""<div class="meta">{escape(n['category'])} · {escape(n['kind'])} · {escape(n['published'])}</div>
<h1>{escape(n['title'])}</h1><p class="sum">{_inline(n['summary'])}</p>
{md_html(n['body'])}
<div class="src">원문: <a href="{escape(n['url'])}" rel="nofollow noopener" target="_blank">{escape(n['source'] or n['url'])}</a>
{f'<br>태그: {escape(tags)}' if tags else ''}</div>
<p><a class="btn" href="/notes?id={n['id']}">AX Review에서 이어 보기 →</a> &nbsp; <a href="/n/">전체 노트</a></p>"""
    return _page(f"{n['title']} | AX Review", n["summary"][:150], url, body, f"{site}/app/static/og.png",
                 f'<script type="application/ld+json">{ld}</script>')


def _json_str(s: str) -> str:
    import json
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def note_index(request: Request) -> Response:
    site = _site(request)
    notes = db.notes("published")
    items = "".join(f"<a href='/n/{n['id']}'>{escape(n['title'])}<small>{escape(n['category'])} · {escape(n['published'])}</small></a>"
                    for n in notes)
    body = f"<div class='meta'>NOTES · {len(notes)}</div><h1>AX 노트 전체</h1><div class='list'>{items}</div>"
    return _page("AX 노트 전체 | AX Review", "기업 AI 전환(AX) 아티클·리포트를 요약·실행 단계·적용 점검까지 정리한 노트 목록",
                 f"{site}/n/", body, f"{site}/app/static/og.png")


def sitemap(request: Request) -> Response:
    site = _site(request)
    urls = [(f"{site}/", None), (f"{site}/n/", None), (f"{site}/letter", None), (f"{site}/about", None),
            (f"{site}/type", None), (f"{site}/diagnosis", None), (f"{site}/terms", None),
            (f"{site}/habit", None), (f"{site}/career", None)]
    urls += [(f"{site}/n/{n['id']}", n["published"]) for n in db.notes("published")]
    xml = "".join(f"<url><loc>{escape(u)}</loc>" + (f"<lastmod>{escape(d)}</lastmod>" if d else "") + "</url>" for u, d in urls)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>',
                    media_type="application/xml")


def robots(request: Request) -> Response:
    return PlainTextResponse("User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /_stcore/\nDisallow: /r/\nDisallow: /refer\nDisallow: /unsubscribe\nDisallow: /confirm\n"
                             f"Sitemap: {_site(request)}/sitemap.xml\n")


# ───────────────────────── 결과 공유 주소 ─────────────────────────

def _share(request: Request, title: str, desc: str, image: str, target: str) -> Response:
    """메신저·SNS 미리보기용 HTML. 사람은 바로 앱 화면(target)으로 넘어간다 (?s=1 = 공유 유입 기록)."""
    site = _site(request)
    dest = f"{site}{target}"
    head = (f'<meta http-equiv="refresh" content="0;url={escape(dest)}">'
            f"<script>location.replace({_json_str(dest)})</script>")
    body = f"<h1>{escape(title)}</h1><p>{escape(desc)}</p><p><a class='btn' href='{escape(dest)}'>결과 보고 나도 해 보기 →</a></p>"
    return _page(title, desc, f"{site}{request.url.path}" + (f"?{request.url.query}" if request.url.query else ""), body,
                 f"{site}/app/static/{image}", head)


def share_type(request: Request) -> Response:
    from app import ax_types
    code = request.path_params["code"].upper()
    if not _TYPE_RE.match(code):
        return RedirectResponse("/type")
    emoji, name, line, *_ = ax_types.TYPES[code]
    return _share(request, f"나는 {emoji} {name} ({code}) — AX 리더 유형 테스트", f"{line}. 12문항으로 16가지 AX 리더 유형 중 내 유형을 알아보세요.",
                  f"og/type-{code}.png", f"/type?{urlencode({'t': code, 's': 1})}")


def diag_level(code: str) -> int:
    """자가진단 응답 코드(12자리 0~3) → 단계 0~3 (app_pages/diagnosis.py: 영역 평균 = 전체 평균, 25점 단위)."""
    total = sum(int(c) for c in code) / (3 * len(code)) * 100
    return min(3, int(total // 25))


def share_diag(request: Request) -> Response:
    from app import og_cards
    code = request.query_params.get("a", "")
    if not _DIAG_RE.match(code):
        return RedirectResponse("/diagnosis")
    i = diag_level(code)
    name, _, line = og_cards.DIAG_LEVELS[i]
    return _share(request, f"우리 조직 AX 준비도: {name} 단계 — AX 준비도 자가진단", f"{line}. 12문항·3분이면 우리 조직 단계와 다음 할 일이 나옵니다.",
                  f"og/diag-{i}.png", f"/diagnosis?{urlencode({'a': code, 's': 1})}")


def share_quiz(request: Request) -> Response:
    q = request.query_params
    d, score, n = q.get("d", ""), q.get("score", ""), q.get("n", "3")
    if not (_DAY_RE.match(d) and score.isdigit() and n.isdigit() and int(score) <= int(n) <= 10):
        return RedirectResponse("/today")
    return _share(request, f"오늘의 AX 퀴즈 {score}/{n} 정답 — 너도 풀어 봐", "실제 수집 데이터로 만든 3문제와 내일의 키워드 예측. 매일 새로 나옵니다.",
                  "og.png", f"/today?{urlencode({'d': d, 's': 1})}")


def share_terms(request: Request) -> Response:
    q = request.query_params
    track, score = q.get("track", ""), q.get("score", "")
    if track not in ("ai", "ax") or not score.isdigit() or int(score) > 100:
        return RedirectResponse("/terms")
    label = "AI 기술 편" if track == "ai" else "AX 비즈니스 편"
    return _share(request, f"AI·AX 용어 퀴즈 {label} {score}점 — 너는 몇 점?", "업무에서 바로 쓰는 AI·AX 용어 퀴즈. 틀린 용어는 복습 카드로 남습니다.",
                  "og.png", f"/terms?{urlencode({'track': track, 'score': score, 's': 1})}")


def share_habit(request: Request) -> Response:
    from app import ax_tests
    q = request.query_params
    lv, score = q.get("l", ""), q.get("score", "")
    if not (lv.isdigit() and int(lv) < len(ax_tests.HABIT_LEVELS) and score.isdigit() and int(score) <= 100):
        return RedirectResponse("/habit")
    _, emoji, name, line = ax_tests.HABIT_LEVELS[int(lv)]
    return _share(request, f"내 AI 활용 습관은 {emoji} {name} 단계 ({score}점) — AI 활용 습관 진단",
                  f"{line} 10문항·1분이면 내 단계와 다음에 해 볼 3가지가 나옵니다.", "og.png", f"/habit?{urlencode({'s': 1})}")


def share_career(request: Request) -> Response:
    from app import ax_tests
    code = request.path_params["code"].upper()
    if code not in ax_tests.CAREER_TYPES:
        return RedirectResponse("/career")
    emoji, name, line, *_ = ax_tests.CAREER_TYPES[code]
    return _share(request, f"나는 {emoji} {name} — AX 커리어 유형", f"{line}. 10문항으로 6가지 AX 커리어 유형 중 내 유형과 학습 경로를 알아보세요.",
                  "og.png", f"/career?{urlencode({'c': code, 's': 1})}")


# ───────────────────────── 주간 PDF ─────────────────────────

def report_pdf(request: Request) -> Response:
    from pipeline import referral, report_pdf as rp
    name = request.path_params["name"]
    if not re.match(r"^axreview_[A-Za-z0-9-]{1,24}\.pdf$", name) or not (rp.REPORT_DIR / name).exists():
        return PlainTextResponse("없는 리포트입니다", status_code=404)
    published = db.issues("published")
    latest = rp.report_filename(published[-1]) if published else None
    q = request.query_params
    if name != latest and not referral.pdf_link_ok(name, q.get("exp", ""), q.get("sig", "")):
        return HTMLResponse("<meta charset='utf-8'><p>지난 호 PDF는 친구 3명을 구독에 초대하면 열립니다. "
                            "<a href='/letter'>뉴스레터 미리 보기</a></p>", status_code=403)
    return FileResponse(rp.REPORT_DIR / name, media_type="application/pdf",
                        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})


ROUTES = [
    Route("/n/", note_index), Route("/n/{id:int}", note_page),
    Route("/sitemap.xml", sitemap), Route("/robots.txt", robots),
    Route("/s/t/{code}", share_type), Route("/s/d", share_diag), Route("/s/q", share_quiz), Route("/s/terms", share_terms),
    Route("/s/h", share_habit), Route("/s/c/{code}", share_career),
    Route("/r/{name}", report_pdf),
]
