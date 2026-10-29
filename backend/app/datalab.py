"""AX 데이터 랩 — 수집 데이터를 직접 만져 보는 인터랙티브 화면 (공개 페이지 /lab).

1) 탐색 대시보드: KPI·키워드 네트워크·상세 패널(추이·급상승)·파이프라인·스트림·히트맵.
   기사 목록을 통째로 넘기고 브라우저에서 다시 집계하므로, 기간(전체/30일/7일)·소스 그룹·키워드 선택·
   타임랩스(날짜 슬라이더)가 모든 차트에 한꺼번에 적용된다.
2) 지식 지도: 노트·기사 임베딩을 2차원으로 펼친 의미 지도(pipeline/knowledge.py). 확대·이동·검색.

st.html 스크립트에 태그 모양 문자열이 있으면 Streamlit이 버리므로(실측) 자체 문서인 st.iframe을 쓴다.
기사 제목 같은 외부 문자열은 화면에 넣을 때 textContent로만 넣는다.

색: 카테고리 3색은 dataviz 검증기로 확인(어두운 배경 #0B1730, all-pairs, 2026-10-28 PASS).
히트맵은 파랑 한 가지 색의 명도 단계(값이 작을수록 배경에 가깝게). 분류 없는 점은 중립 회색.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from pipeline import db, jobs, knowledge

CATEGORY_COLORS = {"AX Strategy": "#2E9BEA", "AX Implementation": "#d95926", "AX Enablement": "#199e70"}
MAX_DAYS = 45  # 대시보드 날짜 축 길이 (이보다 오래된 기사는 첫날에 모은다)


def build_data() -> dict:
    conn = db.connect()
    try:
        arts = [dict(r) for r in conn.execute(
            "SELECT title, url, source, llm_score, published_at, collected_at, matched_kw FROM articles")]
        notes_published = conn.execute("SELECT COUNT(*) FROM notes WHERE status='published'").fetchone()[0]
        notes_all = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        runs = [json.loads(r[0]) for r in conn.execute(
            "SELECT result FROM run_logs WHERE kind='collect' AND ok=1 AND result IS NOT NULL")]
    finally:
        conn.close()

    cats = {k["keyword"]: k["category"] for k in db.list_keywords() if k["category"] in CATEGORY_COLORS}
    groups_of = {s["name"]: s.get("group", "기타") for s in jobs.config()["sources"]}

    rows, totals = [], {}
    for a in arts:
        kws = sorted({k for k in json.loads(a["matched_kw"] or "[]") if k in cats})
        day = knowledge._day(a)
        if not kws or not day:
            continue
        for k in kws:
            totals[k] = totals.get(k, 0) + 1
        rows.append((a, kws, day))
    kw_order = sorted(totals, key=totals.get, reverse=True)
    kw_idx = {k: i for i, k in enumerate(kw_order)}
    group_order = sorted({groups_of.get(a["source"], "기타") for a, _, _ in rows},
                         key=lambda g: -sum(1 for a, _, _ in rows if groups_of.get(a["source"], "기타") == g))
    g_idx = {g: i for i, g in enumerate(group_order)}

    today = datetime.now(db.KST).date()
    # 드문 옛 기사 몇 건 때문에 축이 길어지지 않게, 하위 2% 날짜부터 시작한다 (그 전 기사는 첫날에 모음).
    ordered = sorted(d for _, _, d in rows) or [today]
    first = max(ordered[len(ordered) * 2 // 100], today - timedelta(days=MAX_DAYS - 1))
    days = [(first + timedelta(days=i)).isoformat() for i in range((today - first).days + 1)]

    packed = [{"t": a["title"], "u": a["url"], "s": a["source"], "g": g_idx[groups_of.get(a["source"], "기타")],
               "sc": a["llm_score"] or 0, "d": (a["published_at"] or a["collected_at"] or "")[:16].replace("T", " "),
               "y": max(0, (d - first).days), "k": [kw_idx[k] for k in kws]} for a, kws, d in rows]
    pairs = sum(len(r["k"]) * (len(r["k"]) - 1) // 2 > 0 for r in packed)

    funnel = [
        ("수집한 원문", sum(r.get("collected", 0) for r in runs)),
        ("중복 제거 후", sum(r.get("new", 0) for r in runs)),
        ("키워드 통과·저장", len(arts)),
        ("AX 점수 4점 이상", sum(1 for a in arts if (a["llm_score"] or 0) >= 4)),
        ("노트 초안", notes_all),
        ("게시된 노트", notes_published),
    ]
    if funnel[0][1] < funnel[2][1]:  # 수집 기록이 쌓이기 전 기사 — 원문 단계는 뺀다
        funnel = funnel[2:]

    return {
        "kpi": [("수집 기사", len(arts)), ("AX 키워드", len(kw_order)), ("복수 키워드 기사", pairs),
                ("수집 소스", len({a["source"] for a in arts})), ("게시 노트", notes_published)],
        "cats": CATEGORY_COLORS,
        "kws": [{"id": k, "cat": cats[k]} for k in kw_order],
        "groups": group_order, "days": days, "arts": packed, "funnel": funnel,
        "trendMinDays": knowledge.MIN_TREND_DAYS,
        "asof": datetime.now(db.KST).strftime("%Y-%m-%d %H:%M"),
    }


def _embed(template: str, data: dict) -> str:
    return template.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))


def page_html(data: dict) -> str:
    return _embed(_HTML, data)


def map_html(data: dict) -> str:
    return _embed(_MAP_HTML, {**data, "cats": CATEGORY_COLORS})


_BASE_CSS = r"""
:root{
  color-scheme:dark;
  --bg:#050B18; --surface:#0B1730; --surface-2:#0F1F3D; --line:#16274A; --line-2:#22375f;
  --ink:#E8EEF8; --ink-2:#B5C2D8; --muted:#8C9BB5; --accent:#2E9BEA; --accent-2:#5BC2F5;
  --f-display:"Archivo","IBM Plex Sans KR",system-ui,sans-serif; --f-mono:"IBM Plex Mono",ui-monospace,monospace;
  --f-body:"IBM Plex Sans KR",system-ui,sans-serif;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--f-body);font-size:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:16px;padding:18px;position:relative;overflow:hidden}
.card h3{margin:0 0 4px;font-family:var(--f-display);font-weight:800;font-size:1.05rem;letter-spacing:-.01em}
.card .sub{color:var(--muted);font-size:.9rem;margin:0 0 12px}
.eyebrow{font-size:0.88rem;font-weight:700;color:var(--accent-2)}
.eyebrow::before{content:"";display:inline-block;width:7px;height:7px;border-radius:2px;background:currentColor;margin-right:7px;vertical-align:1px}
.lbl{font-size:.88rem;font-weight:600;color:var(--accent-2);margin-top:4px}
.seg{display:inline-flex;border:1px solid var(--line-2);border-radius:999px;overflow:hidden;background:var(--surface-2)}
.seg button{all:unset;cursor:pointer;padding:6px 12px;font-size:.9rem;color:var(--ink-2)}
.seg button.on{background:linear-gradient(135deg,#0A6FD6,#2E9BEA);color:#fff}
.seg button:focus-visible{outline:2px solid var(--accent-2);outline-offset:-2px}
.chip{display:inline-flex;align-items:center;gap:8px;border:1px solid var(--line-2);border-radius:999px;padding:5px 6px 5px 12px;
  font-size:.9rem;background:var(--surface-2)}
.chip button{all:unset;cursor:pointer;color:var(--muted);padding:0 5px;font-size:1rem;line-height:1}
.chip button:hover,.chip button:focus-visible{color:var(--ink)}
.hint{color:var(--muted);font-size:.9rem}
.legend{display:flex;gap:12px;flex-wrap:wrap}
.legend span,.legend button{display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);font-size:.9rem}
.legend button{all:unset;cursor:pointer;display:inline-flex;align-items:center;gap:6px;color:var(--ink-2);font-size:.9rem;
  padding:3px 8px;border-radius:999px;border:1px solid transparent}
.legend button.off{opacity:.4;text-decoration:line-through}
.legend button:focus-visible{border-color:var(--accent-2)}
.legend i{width:10px;height:10px;border-radius:50%;display:inline-block}
#tip{position:fixed;pointer-events:none;z-index:9;background:#050B18ee;border:1px solid var(--line-2);border-radius:10px;
  padding:8px 10px;font-size:.9rem;max-width:300px;opacity:0;transition:opacity .12s;backdrop-filter:blur(6px)}
#tip b{display:block;font-size:1rem;color:var(--ink)}
#tip .k{display:flex;align-items:center;gap:6px;color:var(--ink-2)}
#tip .k i{width:12px;height:2px;border-radius:1px;display:inline-block;flex:none}
#tip .p{color:var(--muted);margin-top:4px;line-height:1.45}
.foot{color:var(--muted);font-size:.84rem;text-align:right}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""

_HEAD = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100,800&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>""" + _BASE_CSS

_COMMON_JS = r"""
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const fmt = n => n.toLocaleString('ko-KR');
const tip = document.getElementById('tip');
function showTip(x, y, value, label, color, extra) {
  tip.replaceChildren(el('b', null, value));
  const k = el('div', 'k'); if (color) { const i = el('i'); i.style.background = color; k.append(i); }
  k.append(document.createTextNode(label)); tip.append(k);
  if (extra) tip.append(el('div', 'p', extra));
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(8, Math.min(x + 14, innerWidth - w - 8)) + 'px';
  tip.style.top = (y - h - 12 < 8 ? y + 18 : y - h - 12) + 'px';
  tip.style.opacity = 1;
}
const hideTip = () => tip.style.opacity = 0;
const safeUrl = u => /^(https?:\/\/|\/(?!\/))/i.test(u || '') ? u : '#';  // javascript: 같은 주소 차단
function openUrl(u) {  // iframe(srcdoc) 안이라 상대 주소는 부모 사이트 기준으로 바꾼다
  if (safeUrl(u) === '#') return;
  let url = u; try { url = new URL(u, parent.location.origin).href; } catch (e) {}
  window.open(url, '_blank', 'noopener');
}
"""

# ───────────────────────── 1) 탐색 대시보드 ─────────────────────────

_HTML = _HEAD + r"""
.wrap{display:grid;gap:14px;padding:2px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi b{display:block;font-family:var(--f-display);font-weight:800;font-size:1.9rem;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:.9rem}

.filter{display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--surface);border:1px solid var(--line);
  border-radius:14px;padding:10px 12px}
.filter .sp{flex:1}
.tl{display:flex;align-items:center;gap:8px;flex:1 1 280px;min-width:240px}
.tl button{all:unset;cursor:pointer;width:30px;height:30px;border-radius:50%;display:grid;place-items:center;
  background:linear-gradient(135deg,#0A6FD6,#2E9BEA);color:#fff;font-size:.9rem;flex:none}
.tl button:focus-visible{outline:2px solid var(--accent-2);outline-offset:2px}
.tl input{flex:1;accent-color:#2E9BEA;min-width:80px}
.tl output{font-family:var(--f-mono);font-size:.88rem;color:var(--ink-2);min-width:7.5em;text-align:right}

.net-row{display:grid;grid-template-columns:minmax(0,1.75fr) minmax(0,1fr);gap:14px}
#net{width:100%;height:520px;display:block;border-radius:12px;cursor:grab;touch-action:none;
  background:radial-gradient(600px circle at 50% 45%,rgba(10,111,214,.16),transparent 70%)}
#net.dragging{cursor:grabbing}
.panel{display:flex;flex-direction:column;min-height:0}
.panel .big{font-family:var(--f-display);font-weight:800;font-size:1.5rem;margin:2px 0}
.panel .meta{color:var(--muted);font-size:.9rem;margin-bottom:10px}
.bars{display:grid;gap:6px;margin:8px 0 14px}
.bar{display:grid;grid-template-columns:minmax(0,9em) 1fr 52px 2.6em;align-items:center;gap:8px;font-size:.9rem;cursor:pointer;
  border-radius:6px;padding:2px 4px}
.bar:hover,.bar:focus-visible{background:var(--surface-2);outline:none}
.bar .lab{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-2)}
.bar .lab em{font-style:normal;font-size:.8rem;color:#fab219;margin-left:4px}
.bar .trk{height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden}
.bar .fil{height:100%;border-radius:4px;transition:width .5s cubic-bezier(.2,.8,.2,1)}
.bar .val{text-align:right;font-family:var(--f-mono);color:var(--ink)}
.bar svg{display:block}
.rise{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 12px}
.rise button{all:unset;cursor:pointer;font-size:.88rem;padding:4px 9px;border-radius:999px;border:1px solid rgba(250,178,25,.45);
  color:#fde2a6;background:rgba(250,178,25,.08)}
.rise button:focus-visible{outline:2px solid var(--accent-2)}
.list{display:grid;gap:8px;overflow:auto;max-height:250px;padding-right:4px}
.item{display:block;text-decoration:none;color:var(--ink);background:var(--surface-2);border:1px solid transparent;border-radius:10px;
  padding:9px 11px;transition:border-color .2s,transform .2s}
.item:hover,.item:focus-visible{border-color:var(--accent);transform:translateX(2px);outline:none}
.item .t{font-size:.92rem;line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.item .m{color:var(--muted);font-size:.84rem;margin-top:4px}
.score{display:inline-block;min-width:1.6em;text-align:center;border-radius:6px;padding:0 5px;margin-right:6px;
  background:rgba(46,155,234,.16);color:var(--accent-2);font-family:var(--f-mono)}

.row2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px}
.funnel{display:grid;gap:9px}
.fstep{display:grid;grid-template-columns:minmax(0,9em) 1fr;gap:10px;align-items:center}
.fstep .lab{font-size:.9rem;color:var(--ink-2)}
.fstep .trk{position:relative;height:26px;display:flex;align-items:center}
.fstep .fil{flex:none;height:100%;border-radius:0 4px 4px 0;background:var(--accent);width:0;transition:width .9s cubic-bezier(.2,.8,.2,1)}
.fstep .num{margin-left:8px;font-family:var(--f-mono);font-size:.9rem;color:var(--ink);white-space:nowrap;pointer-events:none}
.fstep .num em{font-style:normal;color:var(--muted);margin-left:6px}
.fstep .num.in{position:absolute;left:10px;margin:0;color:#050B18;font-weight:600}
.fstep .num.in em{color:#0B1730}
.daily{margin-top:16px}
.daily svg{width:100%;height:90px;display:block}

.heat{overflow-x:auto}
.heat table{border-collapse:separate;border-spacing:2px;width:100%;font-size:.88rem}
.heat th{font-weight:400;color:var(--muted);text-align:left;padding:2px 6px;white-space:nowrap}
.heat thead th{max-width:7em;overflow:hidden;text-overflow:ellipsis;font-size:.84rem;cursor:pointer;border-radius:4px}
.heat thead th:hover,.heat thead th:focus-visible{color:var(--ink);outline:none;background:var(--surface-2)}
.heat thead th.on{color:var(--ink);font-weight:600;box-shadow:inset 0 -2px 0 var(--accent-2)}
.heat td{height:26px;min-width:34px;border-radius:4px;text-align:center;font-family:var(--f-mono);cursor:pointer;
  outline:2px solid transparent;outline-offset:-2px}
.heat td:hover,.heat td:focus-visible{outline-color:var(--ink)}
.heat tr.on th{color:var(--ink);font-weight:600}
.heat tr.dim td{opacity:.3}
.heat td.dimc{opacity:.3}
.scale{display:flex;align-items:center;gap:8px;margin-top:10px;color:var(--muted);font-size:.84rem}
.scale i{display:block;width:120px;height:8px;border-radius:4px}

.stream-box{height:300px;overflow:hidden;position:relative;-webkit-mask-image:linear-gradient(transparent,#000 12%,#000 88%,transparent)}
.stream{display:grid;gap:6px;will-change:transform}
.srow{display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:10px;align-items:baseline;text-decoration:none;color:var(--ink);
  font-size:.9rem;padding:6px 8px;border-radius:8px;border-left:2px solid var(--line-2)}
.srow:hover,.srow:focus-visible{background:var(--surface-2);outline:none}
.srow .d{font-family:var(--f-mono);color:var(--muted);font-size:.84rem}
.srow .s{color:var(--accent-2);font-size:.88rem;white-space:nowrap;max-width:9em;overflow:hidden;text-overflow:ellipsis}
.srow .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.live{display:inline-flex;align-items:center;gap:6px;font-size:.84rem;color:var(--muted);float:right}
.live i{width:7px;height:7px;border-radius:50%;background:#0ca30c;animation:pulse 1.8s infinite}
@keyframes pulse{50%{opacity:.35}}  /* 투명도만 바꾼다 — 그림자 애니메이션은 매 프레임 다시 그린다 */
details.tbl{margin-top:10px;color:var(--muted);font-size:.9rem}
details.tbl summary{cursor:pointer}
details.tbl table{width:100%;border-collapse:collapse;margin-top:6px}
details.tbl td,details.tbl th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;color:var(--ink-2)}
.empty{color:var(--muted);font-size:.92rem;padding:20px 0;text-align:center}

@media (max-width:820px){
  .kpis{grid-template-columns:repeat(3,1fr)}
  .net-row,.row2{grid-template-columns:1fr}
  #net{height:420px}
}
@media (max-width:480px){
  .kpis{grid-template-columns:repeat(2,1fr)}
  .kpi b{font-size:1.5rem}
  .kpi:last-child{grid-column:span 2}
  #net{height:360px}
  .bar{grid-template-columns:minmax(0,7em) 1fr 44px 2.4em}
}
</style></head>
<body>
<div class="wrap">
  <div class="kpis" id="kpis"></div>

  <div class="filter" id="filter" role="toolbar" aria-label="필터">
    <div class="seg" id="period" role="group" aria-label="기간"></div>
    <div class="tl" title="타임랩스: 날짜를 끝까지 재생하며 키워드가 자라는 모습을 봅니다">
      <button type="button" id="play" aria-label="타임랩스 재생">▶</button>
      <input type="range" id="cut" min="0" value="0" aria-label="기준 날짜">
      <output id="cutv"></output>
    </div>
    <div id="chips" style="display:flex;gap:8px;flex-wrap:wrap"></div>
    <span class="sp"></span>
    <div class="legend" id="legend"></div>
  </div>

  <div class="net-row">
    <div class="card">
      <div class="eyebrow">함께 나온 키워드</div>
      <h3>AX 키워드 네트워크</h3>
      <p class="sub">같은 기사에 함께 나온 키워드끼리 연결됩니다. 원 크기는 기사 수, 선 굵기는 함께 나온 횟수. 끌어서 움직이고, 눌러서 고르세요.</p>
      <canvas id="net" role="img" aria-label="AX 키워드 공출현 네트워크"></canvas>
      <details class="tbl"><summary>표로 보기</summary><table id="net-table"></table></details>
    </div>
    <div class="card panel" id="panel" aria-live="polite"></div>
  </div>

  <div class="row2">
    <div class="card">
      <div class="eyebrow">수집 과정</div>
      <h3>데이터 파이프라인</h3>
      <p class="sub">원문이 노트가 되기까지 단계별로 남는 양 (누적)</p>
      <div class="funnel" id="funnel"></div>
      <div class="daily">
        <div class="lbl">날짜별 수집 기사 <span class="hint" id="daily-sub"></span></div>
        <svg id="daily" role="img" aria-label="날짜별 기사 수 막대"></svg>
      </div>
    </div>
    <div class="card">
      <span class="live"><i></i>LIVE</span>
      <div class="eyebrow">실시간 수집</div>
      <h3>최신 수집 스트림</h3>
      <p class="sub" id="stream-sub"></p>
      <div class="stream-box" id="stream-box"><div class="stream" id="stream"></div></div>
    </div>
  </div>

  <div class="card">
    <div class="eyebrow">출처별 주제</div>
    <h3>키워드 × 소스 그룹</h3>
    <p class="sub">어떤 출처에서 어떤 주제가 많이 잡히는지 (기사 수). 열 이름을 누르면 그 소스 그룹으로 전체가 좁혀집니다.</p>
    <div class="heat" id="heat"></div>
    <div class="scale"><span>적음</span><i id="scale"></i><span>많음</span></div>
  </div>
  <div class="foot" id="foot"></div>
</div>
<div id="tip" role="tooltip"></div>

<script>
const D = __DATA__;
""" + _COMMON_JS + r"""
const KW = D.kws, NK = KW.length, ND = D.days.length;
const catColor = c => D.cats[c] || '#8C9BB5';
const kwColor = i => catColor(KW[i].cat);
const S = { kw: null, group: null, period: 0, cut: ND - 1, playing: false };  // period: 0=전체, 그 외 일수
let A = null;  // 현재 필터로 다시 센 집계

/* ── 집계 (필터가 바뀔 때마다 전부 다시 센다) ── */
function aggregate() {
  const lo = S.period ? Math.max(0, S.cut - S.period + 1) : 0, hi = S.cut;
  const arts = D.arts.filter(a => a.y >= lo && a.y <= hi && (S.group == null || a.g === S.group));
  const count = new Array(NK).fill(0), links = new Map(), heat = D.kws.map(() => new Array(D.groups.length).fill(0));
  const series = D.kws.map(() => new Array(ND).fill(0)), daily = new Array(ND).fill(0);
  D.arts.forEach(a => {  // 추이는 기간과 무관하게 기준일까지 전체 (그룹 필터는 적용)
    if (a.y > hi || (S.group != null && a.g !== S.group)) return;
    daily[a.y]++; a.k.forEach(k => series[k][a.y]++);
  });
  arts.forEach(a => {
    a.k.forEach((k, i) => {
      count[k]++; heat[k][a.g]++;
      for (let j = i + 1; j < a.k.length; j++) { const key = k < a.k[j] ? k + '-' + a.k[j] : a.k[j] + '-' + k; links.set(key, (links.get(key) || 0) + 1); }
    });
  });
  const span = daily.slice(0, hi + 1).filter(Boolean).length, win = Math.max(1, Math.min(7, Math.floor(span / 2)));
  const ready = span >= D.trendMinDays;
  const trend = series.map(s => { const upto = s.slice(0, hi + 1), cur = upto.slice(-win).reduce((x, y) => x + y, 0),
    prev = upto.slice(-2 * win, -win).reduce((x, y) => x + y, 0); return { cur, prev, rate: (cur - prev) / (prev + 2) }; });
  const rising = ready ? trend.map((t, i) => ({ i, ...t })).filter(t => t.cur >= 3 && t.rate >= .5).sort((p, q) => q.rate - p.rate).slice(0, 6) : [];
  A = { lo, hi, arts, count, links: [...links].map(([k, w]) => { const [a, b] = k.split('-').map(Number); return { a, b, w }; }),
        heat, series, daily, span, win, ready, trend, rising };
}

/* ── KPI ── */
const kpis = document.getElementById('kpis');
D.kpi.forEach(([label, v]) => {
  const box = el('div', 'kpi'); const b = el('b', null, REDUCED ? fmt(v) : '0'); box.append(b, el('span', null, label)); kpis.append(box);
  if (!REDUCED) { const t0 = performance.now(); const step = t => { const p = Math.min(1, (t - t0) / 1200);
    b.textContent = fmt(Math.round(v * (1 - Math.pow(1 - p, 3)))); if (p < 1) requestAnimationFrame(step); }; requestAnimationFrame(step); }
});

/* ── 필터 줄 ── */
const periodBox = document.getElementById('period');
[[0, '전체'], [30, '30일'], [7, '7일']].forEach(([v, label]) => {
  const b = el('button', null, label); b.type = 'button'; b.dataset.v = v; b.onclick = () => { S.period = v; update(); }; periodBox.append(b);
});
const cut = document.getElementById('cut'), cutv = document.getElementById('cutv'), play = document.getElementById('play');
cut.max = ND - 1; cut.value = ND - 1;
cut.oninput = () => { stopPlay(); S.cut = +cut.value; update(); };
let timer = null;
function stopPlay() { if (timer) clearInterval(timer); timer = null; S.playing = false; play.textContent = '▶'; play.setAttribute('aria-label', '타임랩스 재생'); }
play.onclick = () => {
  if (timer) return stopPlay();
  S.playing = true; play.textContent = '❚❚'; play.setAttribute('aria-label', '타임랩스 멈춤');
  if (S.cut >= ND - 1) S.cut = 0;
  update();
  timer = setInterval(() => { if (S.cut >= ND - 1) return stopPlay(); S.cut++; update(); },
                    REDUCED ? 1200 : Math.max(250, Math.min(700, 8000 / ND)));  // 전체 재생이 8초 안팎
};
const legend = document.getElementById('legend');
Object.entries(D.cats).forEach(([c, col]) => { const s = el('span'); const i = el('i'); i.style.background = col; s.append(i, document.createTextNode(c)); legend.append(s); });

function renderFilter() {
  [...periodBox.children].forEach(b => b.classList.toggle('on', +b.dataset.v === S.period));
  cut.value = S.cut; cutv.textContent = D.days[S.cut] + (S.cut === ND - 1 ? ' (오늘)' : '');
  const chips = document.getElementById('chips'); chips.replaceChildren();
  const chip = (dot, label, clear) => { const c = el('span', 'chip'); if (dot) { const i = el('i'); i.style.cssText = `width:8px;height:8px;border-radius:50%;background:${dot}`; c.append(i); }
    const x = el('button', null, '×'); x.setAttribute('aria-label', `${label} 선택 해제`); x.onclick = clear; c.append(document.createTextNode(label), x); chips.append(c); };
  if (S.kw != null) chip(kwColor(S.kw), KW[S.kw].id, () => select(null));
  if (S.group != null) chip(null, D.groups[S.group], () => { S.group = null; update(); });
  if (S.kw == null && S.group == null) chips.append(el('span', 'hint', '키워드·소스 그룹을 누르면 전체가 좁혀집니다'));
}

/* ── 상세 패널 ── */
function spark(series, color) {  // 기준일까지 최근 14일 추이
  const s = series.slice(Math.max(0, A.hi - 13), A.hi + 1), max = Math.max(1, ...s), w = 52, h = 18;
  const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('width', w); svg.setAttribute('height', h); svg.setAttribute('aria-hidden', 'true');
  const pts = s.map((v, i) => `${(i / Math.max(1, s.length - 1) * (w - 4) + 2).toFixed(1)},${(h - 2 - v / max * (h - 4)).toFixed(1)}`).join(' ');
  const pl = document.createElementNS(ns, 'polyline'); pl.setAttribute('points', pts); pl.setAttribute('fill', 'none');
  pl.setAttribute('stroke', color); pl.setAttribute('stroke-width', '1.5'); pl.setAttribute('stroke-linejoin', 'round'); svg.append(pl);
  return svg;
}
function barRow(i, v, max, onClick, withSpark) {
  const r = el('div', 'bar'); r.tabIndex = 0; r.setAttribute('role', 'button');
  const lab = el('span', 'lab', KW[i].id);
  if (A.rising.some(x => x.i === i)) lab.append(el('em', null, '▲급상승'));
  const trk = el('div', 'trk'), fil = el('div', 'fil'); fil.style.background = kwColor(i); fil.style.width = '0%'; trk.append(fil);
  r.append(lab, trk, withSpark ? spark(A.series[i], kwColor(i)) : el('span'), el('span', 'val', fmt(v)));
  requestAnimationFrame(() => requestAnimationFrame(() => fil.style.width = (v ? Math.max(3, v / max * 100) : 0) + '%'));
  r.onclick = onClick; r.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } };
  return r;
}
function articleItem(a) {
  const it = el('a', 'item'); it.href = safeUrl(a.u); it.target = '_blank'; it.rel = 'noopener noreferrer';
  it.append(el('div', 't', a.t));
  const m = el('div', 'm'); m.append(el('span', 'score', String(a.sc)), document.createTextNode(`${a.s} · ${a.d}`)); it.append(m);
  return it;
}
function neighbors(i) {
  return A.links.filter(l => l.a === i || l.b === i).map(l => ({ i: l.a === i ? l.b : l.a, w: l.w })).sort((p, q) => q.w - p.w);
}
function renderPanel() {
  const p = document.getElementById('panel'); p.replaceChildren();
  if (S.kw == null) {
    p.append(el('div', 'eyebrow', '한눈에 보기'), el('div', 'big', '많이 잡힌 키워드'));
    p.append(el('div', 'meta', `기사 ${fmt(A.arts.length)}건 · ${A.lo === 0 ? '처음' : D.days[A.lo]} ~ ${D.days[A.hi]}`));
    p.append(el('div', 'lbl', '급상승 키워드'));
    const rise = el('div', 'rise');
    if (A.rising.length) A.rising.forEach(t => { const b = el('button', null, `▲ ${KW[t.i].id} ${t.prev} → ${t.cur}`); b.type = 'button';
      b.title = `최근 ${A.win}일 ${t.cur}건, 그 전 ${A.win}일 ${t.prev}건`; b.onclick = () => select(t.i); rise.append(b); });
    else rise.append(el('span', 'hint', A.ready ? '지금은 눈에 띄게 늘어난 키워드가 없습니다' :
      `데이터 축적 중 — 기사가 있는 날이 ${D.trendMinDays}일 이상 쌓이면 판정합니다 (현재 ${A.span}일)`));
    p.append(rise);
    const order = [...Array(NK).keys()].sort((x, y) => A.count[y] - A.count[x]).filter(i => A.count[i]).slice(0, 10);
    p.append(el('div', 'lbl', '키워드별 기사 수 · 최근 14일 추이'));
    const bars = el('div', 'bars'); const max = order.length ? A.count[order[0]] : 1;
    order.forEach(i => bars.append(barRow(i, A.count[i], max, () => select(i), true)));
    if (!order.length) bars.append(el('div', 'empty', '이 조건에 맞는 기사가 없습니다'));
    p.append(bars);
    return;
  }
  const i = S.kw, nb = neighbors(i), t = A.trend[i];
  p.append(el('div', 'eyebrow', KW[i].cat), el('div', 'big', KW[i].id));
  p.append(el('div', 'meta', `기사 ${fmt(A.count[i])}건 · 연결된 키워드 ${nb.length}개 · 최근 ${A.win}일 ${t.cur}건 (그 전 ${t.prev}건)`));
  if (nb.length) {
    p.append(el('div', 'lbl', '함께 나온 키워드'));
    const bars = el('div', 'bars'); const max = nb[0].w;
    nb.slice(0, 6).forEach(x => bars.append(barRow(x.i, x.w, max, () => select(x.i), false)));
    p.append(bars);
  }
  p.append(el('div', 'lbl', 'AX 점수 높은 기사'));
  const list = el('div', 'list'); list.style.marginTop = '8px';
  const top = A.arts.filter(a => a.k.includes(i)).sort((x, y) => y.sc - x.sc || (y.d > x.d ? 1 : -1)).slice(0, 8);
  top.forEach(a => list.append(articleItem(a)));
  if (!top.length) list.append(el('div', 'empty', '이 조건에 맞는 기사가 없습니다'));
  p.append(list);
}

/* ── 네트워크 (자체 force 시뮬레이션) ── */
const cv = document.getElementById('net'), ctx = cv.getContext('2d');
let W = 0, H = 0, DPR = 1;
const N = KW.map((k, i) => { const a = i / NK * Math.PI * 2; return { i, id: k.id, cat: k.cat, r: 0, tr: 8, x: Math.cos(a) * 120, y: Math.sin(a) * 120, vx: 0, vy: 0 }; });
let L = [], particles = [], adj = {}, maxW = 1;
function rebuildGraph() {
  const maxN = Math.max(1, ...A.count);
  N.forEach(n => n.tr = A.count[n.i] ? 9 + Math.sqrt(A.count[n.i] / maxN) * 30 : 4);
  maxW = Math.max(1, ...A.links.map(l => l.w));
  L = A.links.map(l => ({ ...l, s: N[l.a], t: N[l.b] }));
  adj = {}; L.forEach(l => { (adj[l.a] ||= new Set()).add(l.b); (adj[l.b] ||= new Set()).add(l.a); });
  particles = L.flatMap(l => Array.from({ length: Math.min(3, Math.ceil(l.w / maxW * 3)) }, () => ({ l, p: Math.random(), sp: .002 + Math.random() * .003 })));
  alpha = Math.max(alpha, .35);
  if (typeof kick === 'function') kick();
}
let hover = null, drag = null, alpha = 1;
const view = { s: 1, cx: 0, cy: 0 };  // 그래프 전체가 캔버스에 꽉 차게 맞추는 변환 (노드 크기·글자는 그대로)
const X = n => (n.x - view.cx) * view.s + W / 2, Y = n => (n.y - view.cy) * view.s + H / 2;
function fit(snap) {
  if (W < 80) return;
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  N.forEach(n => { x0 = Math.min(x0, n.x); x1 = Math.max(x1, n.x); y0 = Math.min(y0, n.y); y1 = Math.max(y1, n.y); });
  const pad = 70, s = Math.min((W - pad * 2) / Math.max(1, x1 - x0), (H - pad * 2) / Math.max(1, y1 - y0), 2.4), k = snap ? 1 : .08;
  view.s += (s - view.s) * k; view.cx += ((x0 + x1) / 2 - view.cx) * k; view.cy += ((y0 + y1) / 2 - view.cy) * k;
}
function resize() {
  DPR = Math.min(2, devicePixelRatio || 1); const r = cv.getBoundingClientRect(); W = r.width; H = r.height;
  cv.width = W * DPR; cv.height = H * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0); alpha = Math.max(alpha, .5);
}
function tick() {
  const k = alpha;
  N.forEach(n => n.r += (n.tr - n.r) * .15);
  for (let i = 0; i < NK; i++) for (let j = i + 1; j < NK; j++) {
    const a = N[i], b = N[j]; let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || .01; const d = Math.sqrt(d2);
    const min = a.r + b.r + 40; const f = (6000 / d2 + (d < min ? (min - d) * .1 : 0)) * k;
    dx /= d; dy /= d; a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
  }
  L.forEach(l => { const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1;
    const rest = 90 + (l.s.r + l.t.r), f = (d - rest) * .01 * (.4 + l.w / maxW) * k;
    l.s.vx += dx / d * f; l.s.vy += dy / d * f; l.t.vx -= dx / d * f; l.t.vy -= dy / d * f; });
  N.forEach(n => {
    n.vx -= n.x * .006 * k; n.vy -= n.y * .006 * k;
    if (n === drag) { n.vx = n.vy = 0; return; }
    n.vx *= .78; n.vy *= .78; n.x += n.vx; n.y += n.vy;
  });
  alpha = Math.max(.02, alpha * .985);
}
function draw() {
  ctx.clearRect(0, 0, W, H); if (!drag) fit(false);
  const f = S.kw != null ? S.kw : hover, fs = f != null ? new Set([f, ...(adj[f] || [])]) : null;
  L.forEach(l => {
    const on = !fs || l.a === f || l.b === f;
    ctx.strokeStyle = on && fs ? kwColor(f) : '#5BC2F5';
    ctx.globalAlpha = on ? (fs ? .75 : .14 + .4 * l.w / maxW) : .04;
    ctx.lineWidth = .6 + 3.4 * l.w / maxW;
    ctx.beginPath(); ctx.moveTo(X(l.s), Y(l.s)); ctx.lineTo(X(l.t), Y(l.t)); ctx.stroke();
  });
  if (!REDUCED) particles.forEach(q => {
    q.p = (q.p + q.sp) % 1; const l = q.l; if (fs && l.a !== f && l.b !== f) return;
    ctx.globalAlpha = .9; ctx.fillStyle = '#CFE9FF';
    ctx.beginPath(); ctx.arc(X(l.s) + (X(l.t) - X(l.s)) * q.p, Y(l.s) + (Y(l.t) - Y(l.s)) * q.p, 1.6, 0, 7); ctx.fill();
  });
  N.forEach(n => {
    const empty = !A.count[n.i], on = (!fs || fs.has(n.i)) && !empty, col = kwColor(n.i), x = X(n), y = Y(n);
    ctx.globalAlpha = on ? 1 : .16;
    if (n.i === f) { ctx.shadowColor = col; ctx.shadowBlur = 28; }
    ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, n.r, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    ctx.lineWidth = 2; ctx.strokeStyle = '#0B1730'; ctx.stroke();  // 겹칠 때 구분되는 배경색 테두리
    if (n.i === S.kw) { ctx.strokeStyle = '#E8EEF8'; ctx.beginPath(); ctx.arc(x, y, n.r + 5, 0, 7); ctx.stroke(); }
    ctx.globalAlpha = on ? 1 : .28; ctx.fillStyle = '#E8EEF8';
    ctx.font = `${n.r > 22 ? 700 : 600} ${n.r > 22 ? 13 : 11.5}px "IBM Plex Sans KR",system-ui`;
    ctx.textAlign = 'center'; ctx.textBaseline = 'top'; ctx.fillText(n.id, x, y + n.r + 5);
  });
  ctx.globalAlpha = 1;
}
// 자리를 잡은 뒤에는 힘 계산(키워드 수의 제곱)을 멈추고 흐름 입자만 초당 20번 그린다. 화면 밖·숨은 탭이면 멈춘다
// (예전엔 늘 60fps로 힘 계산까지 돌아 가만히 둬도 CPU 데스크톱 18%·휴대폰 62%).
let running = false, onScreen = true, lastDraw = 0;
// 휴대폰·터치 기기: 자리를 잡으면 연결망은 멈춘다(흐름 입자 없이 한 장) — 건드리면 다시 움직인다. 기사 흐름은 초당 30프레임.
const LITE = matchMedia('(pointer: coarse)').matches || innerWidth < 760;
const settled = () => !drag && alpha < .03 && N.every(n => Math.abs(n.vx) + Math.abs(n.vy) < .05 && Math.abs(n.tr - n.r) < .2);
function loop(t = 0) {
  if (document.hidden || !onScreen) { running = false; return; }
  const still = settled();
  if (!still) { tick(); draw(); lastDraw = t; }
  else if (LITE) { draw(); running = false; return; }
  else if (t - lastDraw > 100) { draw(); lastDraw = t; }  // 자리 잡은 뒤에는 흐름 입자만 초당 10번
  requestAnimationFrame(loop);
}
function kick() { if (!running) { running = true; requestAnimationFrame(loop); } }
new IntersectionObserver(es => { onScreen = es[0].isIntersecting; if (onScreen) kick(); }).observe(cv);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { kick(); kickStream(); } });
function pick(ev) {
  const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let best = null, bd = 1e9;
  N.forEach(n => { if (!A.count[n.i]) return; const d = Math.hypot(X(n) - mx, Y(n) - my); if (d < Math.max(n.r + 8, 18) && d < bd) { best = n; bd = d; } });
  return { n: best, x: (mx - W / 2) / view.s + view.cx, y: (my - H / 2) / view.s + view.cy };
}
let downAt = null;
cv.addEventListener('pointerdown', e => { const p = pick(e); downAt = [e.clientX, e.clientY]; if (p.n) { drag = p.n; cv.setPointerCapture(e.pointerId); cv.classList.add('dragging'); } });
cv.addEventListener('pointermove', e => {
  const p = pick(e);
  if (drag) { drag.x = p.x; drag.y = p.y; alpha = Math.max(alpha, .3); }
  kick();
  hover = drag ? drag.i : p.n ? p.n.i : null;
  cv.style.cursor = p.n ? 'pointer' : 'grab';
  if (p.n && !drag) showTip(e.clientX, e.clientY, `${fmt(A.count[p.n.i])}건`, `${p.n.id} · 연결 ${(adj[p.n.i] || new Set()).size}`, kwColor(p.n.i));
  else hideTip();
});
cv.addEventListener('pointerup', e => {
  if (!downAt) return;  // 누름 한 번에 한 번만 처리한다 (포인터 캡처 중 pointerup이 두 번 오는 경우가 있음, 실측)
  const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5;
  downAt = null;
  if (!moved) { const p = pick(e); select(p.n ? (p.n.i === S.kw ? null : p.n.i) : null); }
  drag = null; cv.classList.remove('dragging');
});
cv.addEventListener('pointerleave', () => { hover = null; hideTip(); kick(); });

function renderNetTable() {
  const t = document.getElementById('net-table'); t.replaceChildren(); const h = el('tr');
  ['키워드', '분류', '기사 수', '가장 많이 함께 나온 키워드'].forEach(x => h.append(el('th', null, x))); t.append(h);
  [...Array(NK).keys()].sort((x, y) => A.count[y] - A.count[x]).forEach(i => { const r = el('tr'); const nb = neighbors(i)[0];
    [KW[i].id, KW[i].cat, fmt(A.count[i]), nb ? `${KW[nb.i].id} (${nb.w})` : '-'].forEach(x => r.append(el('td', null, x))); t.append(r); });
}

/* ── 퍼널 + 날짜별 막대 ── */
function renderFunnel() {
  const f = document.getElementById('funnel'); const max = Math.max(1, D.funnel[0][1]);
  D.funnel.forEach(([label, v], i) => {
    const s = el('div', 'fstep'); const trk = el('div', 'trk'), fil = el('div', 'fil'), num = el('div', 'num');
    num.append(document.createTextNode(fmt(v)));
    if (i) { const prev = D.funnel[i - 1][1]; num.append(el('em', null, prev ? `${(v / prev * 100).toFixed(v / prev < .1 ? 1 : 0)}%` : '')); }
    if (v / max > .78) num.classList.add('in');
    trk.append(fil, num); s.append(el('span', 'lab', label), trk); f.append(s);
    trk.onpointermove = e => showTip(e.clientX, e.clientY, `${fmt(v)}건`, `${label} · 처음 대비 ${(v / max * 100).toFixed(1)}%`, '#2E9BEA');
    trk.onpointerleave = hideTip;
    setTimeout(() => fil.style.width = Math.max(1.5, v / max * 100) + '%', REDUCED ? 0 : 120 + i * 140);
  });
}
function renderDaily() {
  const svg = document.getElementById('daily'), ns = 'http://www.w3.org/2000/svg'; svg.replaceChildren();
  const w = svg.clientWidth || 400, h = 90, n = ND, gap = 2, bw = Math.max(2, (w - gap * (n - 1)) / n), max = Math.max(1, ...A.daily);
  document.getElementById('daily-sub').textContent = `· ${D.days[0]} ~ ${D.days[ND - 1]}`;
  A.daily.forEach((v, i) => {
    const x = i * (bw + gap), bh = v ? Math.max(2, v / max * (h - 16)) : 0, inWin = i >= A.lo && i <= A.hi;
    const hit = document.createElementNS(ns, 'rect');  // 막대보다 넓은 투명 영역이 마우스를 받는다
    hit.setAttribute('x', x); hit.setAttribute('y', 0); hit.setAttribute('width', bw + gap); hit.setAttribute('height', h); hit.setAttribute('fill', 'transparent');
    const r = document.createElementNS(ns, 'rect');
    r.setAttribute('x', x); r.setAttribute('y', h - bh); r.setAttribute('width', bw); r.setAttribute('height', bh); r.setAttribute('rx', Math.min(4, bw / 2));
    r.setAttribute('fill', '#2E9BEA'); r.setAttribute('opacity', inWin ? 1 : .25);
    hit.onpointermove = e => showTip(e.clientX, e.clientY, `${fmt(v)}건`, D.days[i], '#2E9BEA');
    hit.onpointerleave = hideTip; hit.onclick = () => { stopPlay(); S.cut = i; update(); }; hit.style.cursor = 'pointer';
    svg.append(r, hit);
  });
  if (S.cut < ND - 1) { const x = S.cut * (bw + gap) + bw / 2, ln = document.createElementNS(ns, 'line');
    ln.setAttribute('x1', x); ln.setAttribute('x2', x); ln.setAttribute('y1', 0); ln.setAttribute('y2', h); ln.setAttribute('stroke', '#E8EEF8'); ln.setAttribute('stroke-width', 1); svg.append(ln); }
}

/* ── 히트맵 ── */
const RAMP = [[15, 31, 61], [16, 66, 129], [28, 92, 171], [42, 120, 214], [85, 152, 231], [158, 197, 244]];
function heatColor(t) {  // 파랑 한 색 단계: 0 = 배경 쪽, 1 = 밝은 파랑
  const x = Math.min(.9999, Math.max(0, t)) * (RAMP.length - 1), i = Math.floor(x), f = x - i;
  const c = RAMP[i].map((v, k) => Math.round(v + (RAMP[i + 1][k] - v) * f)); return `rgb(${c})`;
}
function renderHeat() {
  const box = document.getElementById('heat'); box.replaceChildren();
  const rows = [...Array(NK).keys()].sort((x, y) => A.count[y] - A.count[x]).filter(i => A.count[i]).slice(0, 12);
  if (!rows.length) { box.append(el('div', 'empty', '이 조건에 맞는 기사가 없습니다')); return; }
  const max = Math.max(1, ...rows.flatMap(i => A.heat[i]));
  const t = el('table'), hr = el('tr'); hr.append(el('th'));
  D.groups.forEach((g, gi) => { const th = el('th', S.group === gi ? 'on' : '', g); th.title = `${g} — 눌러서 이 소스 그룹만 보기`; th.tabIndex = 0;
    const act = () => { S.group = S.group === gi ? null : gi; update(); };
    th.onclick = act; th.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); act(); } }; hr.append(th); });
  const thead = el('thead'); thead.append(hr); t.append(thead);
  const tb = el('tbody');
  rows.forEach(i => {
    const tr = el('tr'); if (S.kw != null) tr.className = i === S.kw ? 'on' : 'dim';
    const h = el('th', null, KW[i].id); h.style.borderLeft = `3px solid ${kwColor(i)}`; tr.append(h);
    D.groups.forEach((g, gi) => {
      const val = A.heat[i][gi], td = el('td', S.group != null && S.group !== gi ? 'dimc' : '', val ? String(val) : ''), s = Math.sqrt(val / max);
      td.style.background = val ? heatColor(.12 + s * .88) : 'var(--surface-2)';
      td.style.color = s > .62 ? '#050B18' : '#E8EEF8'; td.tabIndex = 0;
      const show = e => { const r = td.getBoundingClientRect(); showTip(e.clientX || r.right, e.clientY || r.top, `${fmt(val)}건`, `${KW[i].id} · ${g}`, heatColor(.12 + s * .88)); };
      td.onpointermove = show; td.onfocus = show; td.onpointerleave = hideTip; td.onblur = hideTip;
      td.onclick = () => select(i === S.kw ? null : i);
      tr.append(td);
    });
    tb.append(tr);
  });
  t.append(tb); box.append(t);
  document.getElementById('scale').style.background = `linear-gradient(90deg,${[0, .25, .5, .75, 1].map(x => heatColor(.12 + x * .88)).join(',')})`;
}

/* ── 스트림 (자동 스크롤, 마우스 올리면 멈춤) ── */
let sy = 0, paused = false;
function renderStream() {
  const s = document.getElementById('stream'); s.replaceChildren();
  const rows = A.arts.filter(a => S.kw == null || a.k.includes(S.kw)).sort((x, y) => (y.d > x.d ? 1 : -1)).slice(0, 40);
  document.getElementById('stream-sub').textContent = (S.kw != null ? `'${KW[S.kw].id}' ` : '') + `기사 ${rows.length}건 · 마우스를 올리면 멈춥니다`;
  const make = a => { const r = el('a', 'srow'); r.href = safeUrl(a.u); r.target = '_blank'; r.rel = 'noopener noreferrer';
    r.style.borderLeftColor = a.k.length ? kwColor(a.k[0]) : 'var(--line-2)';
    r.append(el('span', 'd', a.d.slice(5)), el('span', 's', a.s), el('span', 't', a.t)); return r; };
  rows.forEach(a => s.append(make(a)));
  if (!rows.length) s.append(el('div', 'empty', '이 조건에 맞는 기사가 없습니다'));
  if (!REDUCED && rows.length > 8) rows.forEach(a => { const r = make(a); r.tabIndex = -1; r.setAttribute('aria-hidden', 'true'); s.append(r); });  // 이어 붙여 끊김 없이 돈다
  sy = 0; streamHalf = 0;
  if (typeof kickStream === 'function') kickStream();
}
const sbox = document.getElementById('stream-box');
sbox.addEventListener('pointerenter', () => paused = true); sbox.addEventListener('pointerleave', () => paused = false);
sbox.addEventListener('focusin', () => paused = true); sbox.addEventListener('focusout', () => paused = false);
// 기사 흐름: 높이는 목록을 새로 그릴 때만 잰다(매 프레임 scrollHeight 를 읽으면 레이아웃을 다시 계산한다), 화면 밖·숨은 탭이면 멈춘다
let streamHalf = 0, streamOn = true, streamRunning = false, streamTick = false;
function streamLoop() {
  const s = document.getElementById('stream');
  if (document.hidden || !streamOn || REDUCED || s.children.length <= 16) { streamRunning = false; return; }
  if (!streamHalf) streamHalf = s.scrollHeight / 2;
  streamTick = !streamTick;
  if (!paused && (!LITE || streamTick)) { sy += LITE ? .7 : .35; if (sy >= streamHalf) sy -= streamHalf; s.style.transform = `translateY(${-sy}px)`; }
  requestAnimationFrame(streamLoop);
}
function kickStream() { if (!streamRunning) { streamRunning = true; requestAnimationFrame(streamLoop); } }
new IntersectionObserver(es => { streamOn = es[0].isIntersecting; if (streamOn) kickStream(); }).observe(sbox);

/* ── 갱신 ── */
function select(i) { S.kw = i; update(); }
function update() {
  aggregate(); rebuildGraph();
  renderFilter(); renderPanel(); renderHeat(); renderDaily(); renderNetTable();
  if (!S.playing) renderStream();
}

document.getElementById('foot').textContent = `기준 ${D.asof} KST · 키워드가 걸린 기사 기준 · 5분마다 갱신`;
aggregate(); rebuildGraph(); N.forEach(n => n.r = n.tr);
renderFilter(); renderPanel(); renderNetTable(); renderFunnel(); renderHeat(); renderStream();
resize(); renderDaily();
addEventListener('resize', () => { resize(); renderDaily(); streamHalf = 0; kick(); });
for (let i = 0; i < 220; i++) tick();  // 처음부터 자리 잡힌 모양으로 시작
fit(true);
kick(); kickStream();
</script>
</body></html>
"""

# ───────────────────────── 2) 지식 지도 ─────────────────────────

_MAP_HTML = _HEAD + r"""
.mapcard{padding:14px}
.bar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px}
.bar input[type=search]{all:unset;flex:1 1 220px;min-width:160px;background:var(--surface-2);border:1px solid var(--line-2);border-radius:999px;
  padding:7px 14px;font-size:.92rem;color:var(--ink)}
.bar input[type=search]:focus-visible{border-color:var(--accent-2)}
.zoom{display:inline-flex;gap:4px}
.zoom button{all:unset;cursor:pointer;width:30px;height:30px;border-radius:8px;display:grid;place-items:center;background:var(--surface-2);
  border:1px solid var(--line-2);color:var(--ink-2);font-size:1.02rem}
.zoom button:hover,.zoom button:focus-visible{color:var(--ink);border-color:var(--accent-2)}
#map{width:100%;height:600px;display:block;border-radius:12px;cursor:grab;touch-action:none;
  background:radial-gradient(800px circle at 50% 50%,rgba(10,111,214,.14),transparent 70%)}
#map.dragging{cursor:grabbing}
.stat{color:var(--muted);font-size:.88rem;font-family:var(--f-mono)}
details.tbl{margin-top:10px;color:var(--muted);font-size:.9rem}
details.tbl summary{cursor:pointer}
details.tbl ul{margin:6px 0 0;padding-left:18px;color:var(--ink-2);line-height:1.7}
@media (max-width:820px){#map{height:460px}}
@media (max-width:480px){#map{height:380px}}
</style></head>
<body>
<div class="card mapcard">
  <div class="bar">
    <div class="seg" id="types" role="group" aria-label="보기"></div>
    <input type="search" id="q" placeholder="제목·키워드로 찾기 (예: 보안, 제조, ROI)" aria-label="지식 지도 검색">
    <div class="zoom"><button type="button" id="zin" aria-label="확대">+</button><button type="button" id="zout" aria-label="축소">−</button>
      <button type="button" id="zfit" aria-label="전체 보기">⤢</button></div>
  </div>
  <div class="bar"><div class="legend" id="legend"></div><span class="stat" id="stat" style="margin-left:auto"></span></div>
  <canvas id="map" role="img" aria-label="노트와 기사를 뜻이 가까운 것끼리 모은 지식 지도"></canvas>
  <details class="tbl"><summary>무리 목록으로 보기</summary><ul id="clist"></ul></details>
</div>
<div id="tip" role="tooltip"></div>
<script>
const D = __DATA__;
""" + _COMMON_JS + r"""
const P = D.points, C = D.clusters;
const color = c => D.cats[c] || '#8C9BB5';
const S = { type: 'all', q: '', off: new Set(), hover: null };
const cv = document.getElementById('map'), ctx = cv.getContext('2d');
let W = 0, H = 0, DPR = 1, intro = REDUCED ? 1 : 0;
const view = { s: 1, ox: 0, oy: 0 };
let bounds = { x0: -1, x1: 1, y0: -1, y1: 1 };
if (P.length) { bounds = { x0: Math.min(...P.map(p => p.x)), x1: Math.max(...P.map(p => p.x)), y0: Math.min(...P.map(p => p.y)), y1: Math.max(...P.map(p => p.y)) }; }
const SX = p => (p.x * intro) * view.s + view.ox, SY = p => (p.y * intro) * view.s + view.oy;

function fitView() {
  const pad = 40, s = Math.min((W - pad * 2) / Math.max(.01, bounds.x1 - bounds.x0), (H - pad * 2) / Math.max(.01, bounds.y1 - bounds.y0));
  view.s = s; view.ox = W / 2 - (bounds.x0 + bounds.x1) / 2 * s; view.oy = H / 2 - (bounds.y0 + bounds.y1) / 2 * s;
}
function resize() { DPR = Math.min(2, devicePixelRatio || 1); const r = cv.getBoundingClientRect(); W = r.width; H = r.height;
  cv.width = W * DPR; cv.height = H * DPR; ctx.setTransform(DPR, 0, 0, DPR, 0, 0); fitView(); }

function visible(p) { return (S.type === 'all' || p.type === S.type) && !S.off.has(p.cat || '기타'); }
function matches(p) { if (!S.q) return true; const q = S.q.toLowerCase(); return p.t.toLowerCase().includes(q) || p.kw.some(k => k.toLowerCase().includes(q)); }

function draw() {
  ctx.clearRect(0, 0, W, H);
  const hc = S.hover ? S.hover.c : null;
  // 무리 영역(옅은 원)
  if (intro > .95) C.forEach((c, j) => {
    const pts = P.filter(p => p.c === j && visible(p)); if (!pts.length) return;
    const cx = c.x * view.s + view.ox, cy = c.y * view.s + view.oy;
    const r = Math.min(260, Math.sqrt(pts.reduce((s, p) => s + (p.x - c.x) ** 2 + (p.y - c.y) ** 2, 0) / pts.length) * view.s * 1.4 + 18);
    ctx.globalAlpha = hc === j ? .14 : .035; ctx.fillStyle = '#5BC2F5'; ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7); ctx.fill();
  });
  // 기사 → 노트 순서로 그려 노트가 위에 오게 한다
  ['article', 'note'].forEach(type => P.forEach(p => {
    if (p.type !== type || !visible(p)) return;
    const on = matches(p) && (hc == null || p.c === hc), x = SX(p), y = SY(p);
    if (x < -10 || y < -10 || x > W + 10 || y > H + 10) return;
    const r = p.type === 'note' ? 7 : 2.2 + p.sc * .7;
    ctx.globalAlpha = on ? (p.type === 'note' ? 1 : .85) : (S.q ? .08 : .22);
    ctx.fillStyle = color(p.cat); ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = '#0B1730'; ctx.stroke();  // 겹침 구분용 배경색 테두리
    if (p.type === 'note') { ctx.lineWidth = 1.5; ctx.strokeStyle = '#E8EEF8'; ctx.beginPath(); ctx.arc(x, y, r + 3, 0, 7); ctx.stroke(); }
  }));
  if (S.hover) { const x = SX(S.hover), y = SY(S.hover); ctx.globalAlpha = 1; ctx.strokeStyle = '#E8EEF8'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, (S.hover.type === 'note' ? 7 : 4) + 6, 0, 7); ctx.stroke(); }
  // 무리 이름표 — 큰 무리부터, 앞서 그린 이름표와 겹치면 건너뛴다 (확대하면 다시 보인다)
  const placed = [];
  if (intro > .95) C.map((c, j) => ({ c, j })).sort((p, q) => (q.j === hc) - (p.j === hc) || q.c.n - p.c.n).forEach(({ c, j }) => {
    const cx = c.x * view.s + view.ox, cy = c.y * view.s + view.oy; if (cx < 0 || cy < 0 || cx > W || cy > H) return;
    ctx.font = '600 12px "IBM Plex Sans KR",system-ui';
    const label = `${c.name} · ${c.n}`, w = ctx.measureText(label).width + 16;
    const box = [cx - w / 2 - 4, cy - 15, cx + w / 2 + 4, cy + 15];
    if (placed.some(o => box[0] < o[2] && box[2] > o[0] && box[1] < o[3] && box[3] > o[1])) return;
    placed.push(box);
    ctx.globalAlpha = hc == null || hc === j ? .95 : .45;
    ctx.fillStyle = '#050B18cc'; ctx.beginPath(); ctx.roundRect(cx - w / 2, cy - 11, w, 22, 11); ctx.fill();
    ctx.strokeStyle = '#22375f'; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = '#E8EEF8'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, cx, cy);
  });
  ctx.globalAlpha = 1;
}
function frame() { if (intro < 1) { intro = Math.min(1, intro + .035); } draw(); if (intro < 1) requestAnimationFrame(frame); }
const redraw = () => requestAnimationFrame(draw);

function nearest(mx, my) {
  let best = null, bd = 16;
  P.forEach(p => { if (!visible(p) || !matches(p)) return; const d = Math.hypot(SX(p) - mx, SY(p) - my); if (d < bd) { bd = d; best = p; } });
  return best;
}
function zoomAt(mx, my, f) { const s = Math.max(view.s * .3, Math.min(view.s * f, 4000));
  view.ox = mx - (mx - view.ox) * (s / view.s); view.oy = my - (my - view.oy) * (s / view.s); view.s = s; redraw(); }

const ptrs = new Map(); let dragFrom = null, pinch = null, moved = false;
cv.addEventListener('pointerdown', e => { cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]); moved = false;
  if (ptrs.size === 1) { dragFrom = [e.clientX, e.clientY, view.ox, view.oy]; cv.classList.add('dragging'); }
  if (ptrs.size === 2) { const [a, b] = [...ptrs.values()]; pinch = Math.hypot(a[0] - b[0], a[1] - b[1]); } });
cv.addEventListener('pointermove', e => {
  const r = cv.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  if (ptrs.has(e.pointerId)) ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  if (ptrs.size === 2 && pinch) { const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    zoomAt((a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top, d / pinch); pinch = d; moved = true; return; }
  if (dragFrom) { const dx = e.clientX - dragFrom[0], dy = e.clientY - dragFrom[1]; if (Math.hypot(dx, dy) > 4) moved = true;
    view.ox = dragFrom[2] + dx; view.oy = dragFrom[3] + dy; hideTip(); redraw(); return; }
  const p = nearest(mx, my);
  if (p !== S.hover) { S.hover = p; redraw(); }
  cv.style.cursor = p ? 'pointer' : 'grab';
  if (p) showTip(e.clientX, e.clientY, p.type === 'note' ? '노트' : `기사 · AX ${p.sc}점`, `${p.t}`, color(p.cat),
                 `${p.s} · ${p.d}${p.sum ? ' — ' + p.sum : ''}`);
  else hideTip();
});
const endPtr = e => { ptrs.delete(e.pointerId); if (ptrs.size < 2) pinch = null;
  if (!ptrs.size) { if (!moved) { const r = cv.getBoundingClientRect(); const p = nearest(e.clientX - r.left, e.clientY - r.top); if (p) openUrl(p.u); }
    dragFrom = null; cv.classList.remove('dragging'); } };
cv.addEventListener('pointerup', endPtr); cv.addEventListener('pointercancel', endPtr);
cv.addEventListener('pointerleave', () => { if (!ptrs.size) { S.hover = null; hideTip(); redraw(); } });
cv.addEventListener('wheel', e => { e.preventDefault(); const r = cv.getBoundingClientRect(); zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * .0015)); }, { passive: false });
document.getElementById('zin').onclick = () => zoomAt(W / 2, H / 2, 1.4);
document.getElementById('zout').onclick = () => zoomAt(W / 2, H / 2, 1 / 1.4);
document.getElementById('zfit').onclick = () => { fitView(); redraw(); };

const types = document.getElementById('types');
[['all', '전체'], ['note', '노트만'], ['article', '기사만']].forEach(([v, label]) => { const b = el('button', null, label); b.type = 'button';
  b.onclick = () => { S.type = v; renderControls(); redraw(); }; b.dataset.v = v; types.append(b); });
document.getElementById('q').oninput = e => { S.q = e.target.value.trim(); renderControls(); redraw(); };
function renderControls() {
  [...types.children].forEach(b => b.classList.toggle('on', b.dataset.v === S.type));
  const lg = document.getElementById('legend'); lg.replaceChildren();
  [...Object.keys(D.cats), '기타'].forEach(c => { const b = el('button', S.off.has(c) ? 'off' : ''); b.type = 'button';
    b.setAttribute('aria-pressed', String(!S.off.has(c))); const i = el('i'); i.style.background = color(c === '기타' ? '' : c);
    b.append(i, document.createTextNode(c)); b.onclick = () => { S.off.has(c) ? S.off.delete(c) : S.off.add(c); renderControls(); redraw(); }; lg.append(b); });
  const shown = P.filter(p => visible(p) && matches(p));
  document.getElementById('stat').textContent = `노트 ${shown.filter(p => p.type === 'note').length} · 기사 ${shown.filter(p => p.type === 'article').length}` +
    (S.q ? ` · '${S.q}' 검색` : '') + ' · 큰 원 = 노트';
}
const cl = document.getElementById('clist');
C.map((c, j) => ({ c, j })).sort((a, b) => b.c.n - a.c.n).forEach(({ c, j }) => {
  const li = el('li', null, `${c.name} — ${c.n}건: `);
  P.filter(p => p.c === j).sort((a, b) => (b.type === 'note') - (a.type === 'note') || b.sc - a.sc).slice(0, 3)
    .forEach((p, k) => { const a = el('a', null, p.t); a.href = '#'; a.style.color = 'var(--accent-2)'; a.onclick = ev => { ev.preventDefault(); openUrl(p.u); };
      if (k) li.append(document.createTextNode(' / ')); li.append(a); });
  cl.append(li);
});
renderControls(); resize(); addEventListener('resize', () => { resize(); redraw(); });
if (!P.length) { ctx.fillStyle = '#8C9BB5'; ctx.font = '14px system-ui'; ctx.textAlign = 'center'; ctx.fillText('임베딩된 노트·기사가 아직 없습니다', W / 2, H / 2); }
else frame();
</script>
</body></html>
"""
