"""공유 미리보기·결과 카드 이미지 (1200×630) — 유형 16장, 자가진단 단계 4장.

카카오톡·LinkedIn은 링크의 og:image를 미리보기로 쓰므로 결과마다 다른 이미지를 준다(app/web.py의 /s/… 주소).
같은 이미지를 '결과 카드 이미지 받기'로도 내려 LinkedIn 피드에 올릴 수 있게 한다.
내용(유형 이름·한 줄 설명)이 바뀌면 다시 만든다:  python -m app.og_cards
"""
from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "og"

# 자가진단 단계 (app_pages/diagnosis.py LEVELS와 같은 이름·색)
DIAG_LEVELS = [("탐색", "#8C9BB5", "AX 첫걸음 — 경영 과제 3개부터 고르세요"), ("실험", "#5BC2F5", "파일럿이 돌기 시작한 조직"),
               ("확산", "#2E9BEA", "성공 사례를 전사로 넓히는 중"), ("내재화", "#0ca30c", "AI가 일하는 방식에 스며든 조직")]

_CSS = """
*{box-sizing:border-box;margin:0}
body{width:1200px;height:630px;overflow:hidden;font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#E8EEF8;
  background:radial-gradient(900px 500px at 85% 20%,rgba(10,111,214,.55),transparent 60%),
             radial-gradient(700px 420px at 0% 100%,rgba(46,155,234,.25),transparent 60%),#050B18;}
.grid{position:absolute;inset:0;background-image:linear-gradient(rgba(91,194,245,.06) 1px,transparent 1px),
  linear-gradient(90deg,rgba(91,194,245,.06) 1px,transparent 1px);background-size:48px 48px}
.wrap{position:absolute;left:80px;top:70px;right:80px}
.k{font:700 22px/1 'Consolas',monospace;letter-spacing:4px;color:#5BC2F5}
.emo{font-size:150px;line-height:1;position:absolute;right:90px;top:120px;
  font-family:'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji',sans-serif}
h1{font-size:72px;font-weight:900;line-height:1.15;margin:26px 0 10px;max-width:820px}
.code{font:800 34px/1 'Consolas',monospace;letter-spacing:6px;color:#A9D6FF}
.line{font-size:30px;line-height:1.5;color:#B5C2D8;margin-top:26px;max-width:860px}
.foot{position:absolute;left:80px;right:80px;bottom:56px;display:flex;justify-content:space-between;align-items:center}
.cta{font-size:24px;font-weight:700;padding:12px 26px;border-radius:999px;background:#0A6FD6;color:#fff}
.brand{font-weight:900;font-size:26px;letter-spacing:1px}.brand b{color:#5BC2F5}
.score{font-size:150px;font-weight:900;line-height:1;margin-top:18px}
.lv{font-size:46px;font-weight:900;margin-top:6px}
"""


def _page(body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{_CSS}</style></head><body><div class='grid'></div>{body}</body></html>"


def type_html(code: str) -> str:
    from app import ax_types
    emoji, name, line, *_ = ax_types.TYPES[code]
    return _page(f"""<div class="wrap"><div class="k">AX LEADER TYPE</div><h1>{escape(name)}</h1>
<div class="code">{escape(code)}</div><div class="line">{escape(line)}</div></div><div class="emo">{emoji}</div>
<div class="foot"><span class="cta">나는 어떤 AX 리더? 12문항 테스트 →</span><span class="brand">AX <b>REVIEW</b></span></div>""")


def diag_html(i: int) -> str:
    name, color, line = DIAG_LEVELS[i]
    return _page(f"""<div class="wrap"><div class="k">AX READINESS SELF-CHECK</div>
<div class="lv" style="color:{color};margin-top:34px">● {escape(name)} 단계</div><h1 style="margin-top:12px">우리 조직의 AX 준비도</h1>
<div class="line">{escape(line)}</div></div>
<div class="foot"><span class="cta">12문항 · 3분 자가진단 →</span><span class="brand">AX <b>REVIEW</b></span></div>""")


def type_path(code: str) -> Path:
    return OUT / f"type-{code}.png"


def diag_path(i: int) -> Path:
    return OUT / f"diag-{i}.png"


def make_all() -> list[Path]:
    """Edge(Playwright)로 렌더링한다 — 이모지·한글 글꼴이 시스템 그대로 나온다 (app/og_meta.make_image와 같은 방식)."""
    from playwright.sync_api import sync_playwright

    from app import ax_types
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(type_path(c), type_html(c)) for c in ax_types.TYPES] + [(diag_path(i), diag_html(i)) for i in range(len(DIAG_LEVELS))]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        for path, html in jobs:
            page.set_content(html)
            page.wait_for_timeout(150)
            page.screenshot(path=str(path))
        browser.close()
    return [p for p, _ in jobs]


if __name__ == "__main__":
    print(len(make_all()), "장 →", OUT)
