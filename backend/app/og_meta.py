"""링크 공유 미리보기(제목·설명·썸네일).

카톡·Teams·슬랙 미리보기는 자바스크립트를 실행하지 않고 첫 HTML의 <meta>만 읽는다.
React 빌드(frontend/dist/index.html)를 내보낼 때마다 render()가 페이지별 제목·설명·썸네일을 넣는다
(api/main.py 의 SPA 응답). 파일에 써 두지 않으므로 npm run build 로 dist 를 다시 만들어도 빠지지 않는다.

    python -m app.og_meta   # 썸네일(static/og.png) 다시 만들기
"""
from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
OG_IMAGE = ROOT / "static" / "og.png"
INDEX = ROOT.parent / "frontend" / "dist" / "index.html"  # React 빌드 결과

# 링크 공유 미리보기(카카오톡·LinkedIn·슬랙 등)의 제목·설명. 카카오톡은 30자, 설명은 2줄 안팎만 보이므로 앞쪽에 핵심을 둔다.
TITLE = "AX Review — 기업 AI 전환 사례, 매주 3분 요약"
DESCRIPTION = ("AI 에이전트·데이터·현장 도입 사례를 읽고 요약·실행 단계·적용 점검까지 정리합니다. "
               "업종별 사례와 리더가 알아야 할 3가지를 매주 무료 뉴스레터로 받아 보세요.")
_START, _END = "<!-- axreview-og -->", "<!-- /axreview-og -->"

# 페이지별 공유 미리보기 — (제목, 설명, 썸네일). 썸네일 None 이면 static/og.png.
# 노트 상세(/n/…)·결과 공유(/s/…)는 app/web.py 가 따로 만든다.
PAGES: dict[str, tuple[str, str, str | None]] = {
    "/notes": ("AX 노트 — 기업 AI 전환 사례 모음 | AX Review",
               "AI 에이전트·데이터·현장 도입 사례를 요약·실행 단계·적용 점검으로 정리한 노트. 업종·분류별로 찾아보세요.", None),
    "/today": ("오늘의 AX — 1분 퀴즈와 오늘의 용어 | AX Review",
               "매일 바뀌는 AX 퀴즈와 예측, 오늘의 용어로 기업 AI 전환 감각을 하루 1분씩 쌓아 보세요.", None),
    "/lab": ("AX 데이터 랩 — 숫자로 보는 기업 AI 전환 | AX Review",
             "수집한 기사·노트에서 뽑은 키워드 흐름, 업종·지역별 AI 전환 움직임을 차트와 지도로 봅니다.", None),
    "/ask": ("AX 질문하기 — 쌓인 노트로 답하는 AI | AX Review",
             "기업 AX 고민을 물어보면 AX Review에 쌓인 노트와 사례를 근거로 답합니다. 무료로 3번 써 보세요.", None),
    "/about": ("AX Review 소개 | AX Review",
               "경영진과 AX 실무자를 위해 기업 AI 전환 자료를 찾고, 정리하고, 쌓아 두는 노트입니다.", None),
    "/type": ("AX 리더 유형 테스트 — 나는 어떤 AX 리더일까? | AX Review",
              "12문항으로 알아보는 16가지 AX 리더 유형. 나의 강점과 함께 일하기 좋은 유형을 확인해 보세요.", None),
    "/terms": ("AI·AX 용어 퀴즈 — 몇 개나 알고 있을까? | AX Review",
               "에이전트, RAG, 파인튜닝… 기업 AI 전환에서 꼭 나오는 용어를 퀴즈로 점검해 보세요.", None),
    "/diagnosis": ("AX 준비도 자가진단 — 우리 회사는 몇 단계? | AX Review",
                   "전략·실행·기반 12문항에 답하면 우리 조직의 AX 준비 단계와 다음 할 일을 알려 드립니다.", None),
    "/habit": ("AI 활용 습관 진단 — 나는 AI를 얼마나 잘 쓰고 있을까? | AX Review",
               "10문항으로 사용 빈도·질문력·검증·자동화·공유 5개 영역을 점검하고, 내 단계와 다음에 해 볼 3가지를 알려 드립니다.", None),
    "/career": ("AX 커리어 유형 — AI 시대, 나에게 맞는 일은? | AX Review",
                "10문항으로 6가지 AX 커리어 유형 중 내 유형과 어울리는 직무·역량·학습 경로를 알려 드립니다.", None),
    "/letter": ("AX Review 뉴스레터 미리보기 | AX Review",
                "매주 AX 흐름을 한 줄로 묶고 리더가 알아야 할 3가지를 정리해 보내 드립니다. 무료 구독.", None),
    "/privacy": ("개인정보 처리방침 | AX Review", "AX Review 개인정보 처리방침.", None),
}


NOINDEX = {"admin", "confirm", "unsubscribe", "refer"}


def page_meta(path: str) -> tuple[str, str, str | None]:
    path = "/" + path.strip("/")
    return PAGES.get(path, (TITLE, DESCRIPTION, None))


def _block(site_url: str, path: str = "/") -> str:
    site = site_url.rstrip("/")
    title, desc, image = page_meta(path)
    img = f"{site}{image or '/app/static/og.png'}"
    known = path.strip("/") in {p.strip("/") for p in PAGES}
    url = site + ("/" + path.strip("/") if known else "/")
    t, d = escape(title), escape(desc)
    first = path.strip("/").split("/")[0]
    # canonical 은 페이지가 분명한 경로(홈·PAGES)에만 — 모르는 경로(404 등)에 홈을 canonical 로 주면 검색 엔진이 혼동한다
    canonical = f'<link rel="canonical" href="{escape(url)}" />' if known or not first else ""
    # 개인 화면·확인 링크는 색인하지 않는다 (robots.txt 와 같은 목록)
    robots = '<meta name="robots" content="noindex" />' if first in NOINDEX else ""
    return f"""{_START}
    <meta name="description" content="{d}" />
    {canonical}{robots}
    <meta name="theme-color" content="#050B18" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="AX Review" />
    <meta property="og:locale" content="ko_KR" />
    <meta property="og:title" content="{t}" />
    <meta property="og:description" content="{d}" />
    <meta property="og:url" content="{escape(url)}" />
    <meta property="og:image" content="{img}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="AX Review" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{t}" />
    <meta name="twitter:description" content="{d}" />
    <meta name="twitter:image" content="{img}" />
    {_END}"""


def render(html: str, path: str = "/", site_url: str | None = None) -> str:
    """React index.html 에 이 페이지의 제목·공유 메타를 넣어 돌려준다 (파일은 건드리지 않음)."""
    site_url = site_url or os.environ.get("SITE_URL", "http://localhost:5002")
    new = re.sub(re.escape(_START) + r".*?" + re.escape(_END) + r"\s*", "", html, flags=re.S)
    new = re.sub(r'\s*<meta name="(description|theme-color)"[^>]*>', "", new)  # 블록에 다시 넣는다
    new = re.sub(r"<title>.*?</title>", f"<title>{escape(page_meta(path)[0])}</title>", new, count=1, flags=re.S)
    new = new.replace('<html lang="en">', '<html lang="ko">', 1)
    return new.replace("</head>", f"{_block(site_url, path)}\n  </head>", 1)


OG_HTML = """<!doctype html><meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100,900&family=Noto+Sans+KR:wght@500;700;900&display=swap');
body{margin:0;width:1200px;height:630px;overflow:hidden;font-family:'Noto Sans KR',sans-serif;color:#E8EEF8;
  background:radial-gradient(520px circle at 82% 45%,rgba(10,111,214,.55),transparent 65%),
             linear-gradient(120deg,#050B18 0%,#07152E 55%,#0A2A5A 100%);}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(91,194,245,.06) 1px,transparent 1px),
  linear-gradient(90deg,rgba(91,194,245,.06) 1px,transparent 1px);background-size:48px 48px;
  -webkit-mask-image:linear-gradient(90deg,transparent,#000 70%);}
.net{position:absolute;right:-40px;top:0;width:640px;height:630px;opacity:.85}
.net svg{width:100%;height:100%}
.wrap{position:absolute;left:80px;top:70px;width:760px}
.by{font-family:monospace;font-size:22px;letter-spacing:3px;color:#8C9BB5}
h1{font-family:'Archivo',sans-serif;font-stretch:118%;font-weight:900;font-size:112px;line-height:1;margin:20px 0 26px;white-space:nowrap;
  background:linear-gradient(100deg,#5BC2F5 5%,#CFE9FF 45%,#2E9BEA 95%);-webkit-background-clip:text;color:transparent}
.lead{font-size:38px;font-weight:900;margin-bottom:14px}
.sub{font-size:24px;color:#B5C2D8;line-height:1.55}
.chips{position:absolute;left:80px;bottom:52px;display:flex;gap:12px}
.chips span{font-size:20px;font-weight:700;padding:8px 18px;border-radius:999px;border:1px solid rgba(91,194,245,.45);color:#A9D6FF;
  background:rgba(10,111,214,.18)}
.brand{position:absolute;right:70px;bottom:60px;font-weight:900;font-size:24px;letter-spacing:1px;color:#fff}
.brand b{color:#5BC2F5}
</style>
<div class="grid"></div>
<div class="net">NETWORK_SVG</div>
<div class="wrap"><div class="by">&nbsp;</div><h1>AX Review</h1>
<div class="lead">기업의 AX를 위한 필수 지식</div>
<div class="sub">읽고, 정리하고, 쌓습니다.<br>매주 AX 흐름을 한 줄로 묶어 드립니다.</div></div>
<div class="chips"><span>AX Strategy</span><span>AX Implementation</span><span>AX Enablement</span></div>
<div class="brand">AX <b>REVIEW</b></div>
"""


def make_image() -> Path:
    """1200×630 썸네일을 Playwright로 렌더링한다 (Edge 채널 폴백은 report_pdf와 같은 방식)."""
    from playwright.sync_api import sync_playwright

    # set_content 페이지(about:blank)에서는 file:// 이미지가 막혀서 SVG를 그대로 넣는다(실측).
    net = (ROOT / "static" / "network.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # noqa: BLE001 - 번들 브라우저 미설치
            browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.set_content(OG_HTML.replace("NETWORK_SVG", net), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(OG_IMAGE))
        browser.close()
    return OG_IMAGE


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("thumbnail:", make_image())
