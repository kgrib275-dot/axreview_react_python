"""참여 세계 지도 — 국가별 색 농도(참여 수) + 국내 시·도 원, 콘텐츠·성별·연령대 필터, 나라 클릭 시 상세.

지도 라이브러리(d3·topojson)와 국경 데이터(world-atlas)는 static/vendor에 두고 사이트에서 직접 내려준다
(외부 CDN 스크립트가 사이트 권한으로 실행되는 위험 제거, 사내망 차단 대비). 못 받으면 국가별 표만 보여 준다.
공개 페이지는 engage.map_public()으로 서버에서 묶은 값만 받는다 (참여 한 건씩의 행을 내려보내지 않는다). 색은 파랑 한 가지 색의 명도 단계(sequential), 0건은 배경색.
"""
from __future__ import annotations

import json

from app.datalab import _BASE_CSS, _COMMON_JS

def html(data: dict) -> str:
    from app import ax_types
    payload = {**data, "typeNames": {k: f"{v[0]} {v[1]}" for k, v in ax_types.TYPES.items()}}
    return _HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))


_HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans+KR:wght@400;600;700&display=swap" rel="stylesheet">
<style>""" + _BASE_CSS + r"""
.wrap{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(0,1fr);gap:14px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px}
select{all:unset;background:var(--surface-2);border:1px solid var(--line-2);border-radius:999px;padding:6px 12px;font-size:.78rem;color:var(--ink);cursor:pointer}
select:focus-visible{border-color:var(--accent-2)}
#svg{width:100%;height:430px;display:block;border-radius:12px;background:#07122A;cursor:grab;touch-action:none}
.country{stroke:#0B1730;stroke-width:.6;transition:fill .25s;vector-effect:non-scaling-stroke}
.country:hover{stroke:#E8EEF8;stroke-width:1}
.country.sel{stroke:#E8EEF8;stroke-width:1.4}
.dot{fill:#5BC2F5;fill-opacity:.8;stroke:#E8EEF8;stroke-opacity:.7;stroke-width:1.2;vector-effect:non-scaling-stroke}
.dot:hover{fill-opacity:1;stroke:#E8EEF8}
.zoom{display:inline-flex;gap:4px;margin-left:auto}
.sample{font-size:.72rem;color:#fde2a6;border:1px solid rgba(250,178,25,.5);border-radius:999px;padding:4px 10px;background:rgba(250,178,25,.08)}
.zoom button{all:unset;cursor:pointer;padding:5px 10px;border-radius:8px;background:var(--surface-2);border:1px solid var(--line-2);color:var(--ink-2);font-size:.76rem}
.zoom button:hover,.zoom button:focus-visible{color:var(--ink);border-color:var(--accent-2)}
.panel h4{margin:0 0 2px;font-size:1.2rem}
.panel .meta{color:var(--muted);font-size:.78rem;margin-bottom:12px}
.rows{display:grid;gap:6px;margin:6px 0 14px}
.row{display:grid;grid-template-columns:minmax(0,8em) 1fr 3em;gap:8px;align-items:center;font-size:.78rem;color:var(--ink-2)}
.row .trk{height:8px;border-radius:4px;background:var(--surface-2);overflow:hidden}
.row .fil{height:100%;background:#2E9BEA;border-radius:4px;transition:width .4s}
.row b{text-align:right;font-family:var(--f-mono);color:var(--ink)}
.empty{color:var(--muted);font-size:.84rem;padding:30px 0;text-align:center;line-height:1.7}
.scale{display:flex;align-items:center;gap:8px;margin-top:8px;color:var(--muted);font-size:.72rem}
.scale i{display:block;width:110px;height:8px;border-radius:4px}
table.fb{width:100%;border-collapse:collapse;font-size:.8rem} table.fb td{padding:5px 6px;border-bottom:1px solid var(--line);color:var(--ink-2)}
@media (max-width:820px){.wrap{grid-template-columns:1fr} #svg{height:340px}}
</style></head><body>
<div class="wrap">
  <div class="card">
    <div class="bar" role="toolbar" aria-label="필터">
      <select id="fk" aria-label="콘텐츠"><option value="">모든 참여</option><option value="type_test">유형 테스트</option>
        <option value="quiz">퀴즈</option><option value="term_quiz">용어 퀴즈</option><option value="poll">예측 투표</option><option value="share">공유</option><option value="share_visit">공유 유입</option></select>
      <select id="fg" aria-label="성별"></select><select id="fa" aria-label="연령대"></select>
      <span class="sample" id="sample" hidden></span>
      <div class="zoom"><button type="button" id="zk">대한민국 확대</button><button type="button" id="zw">전체</button></div>
    </div>
    <svg id="svg" role="img" aria-label="국가별 참여 지도"></svg>
    <div class="scale"><span>적음</span><i id="scale"></i><span>많음</span><span class="hint" id="total" style="margin-left:auto"></span></div>
  </div>
  <div class="card panel" id="panel" aria-live="polite"></div>
</div>
<div id="tip" role="tooltip"></div>
<script src="/app/static/vendor/d3-7.9.0.min.js"></script>
<script src="/app/static/vendor/topojson-client-3.1.0.min.js"></script>
<script>
const D = __DATA__;
""" + _COMMON_JS + r"""
const S = { k: '', g: '', a: '', sel: null };
if (D.sample) { const b = document.getElementById('sample'); b.hidden = false;
  b.textContent = '예시 데이터 ' + fmt(D.sample) + '건 포함'; b.title = '화면 시연용 가상 참여가 함께 표시되고 있습니다 (관리 > 참여 분석에서 끄기)'; }
const fill = (sel, opts, label) => { const o = document.createElement('option'); o.value = ''; o.textContent = label; sel.append(o);
  opts.forEach(v => { const x = document.createElement('option'); x.value = v; x.textContent = v; sel.append(x); }); };
fill(document.getElementById('fg'), D.genders, '모든 성별'); fill(document.getElementById('fa'), D.ages, '모든 연령대');
['fk', 'fg', 'fa'].forEach(id => document.getElementById(id).onchange = e => { S[{ fk: 'k', fg: 'g', fa: 'a' }[id]] = e.target.value; render(); });
const nameOf = Object.fromEntries(Object.entries(D.countries).map(([n, c]) => [c, n]));
const RAMP = [[22, 52, 104], [28, 92, 171], [42, 120, 214], [85, 152, 231], [158, 197, 244]];
const heat = t => { const x = Math.min(.9999, Math.max(0, t)) * (RAMP.length - 1), i = Math.floor(x), f = x - i;
  return `rgb(${RAMP[i].map((v, k) => Math.round(v + (RAMP[i + 1][k] - v) * f))})`; };
document.getElementById('scale').style.background = `linear-gradient(90deg,${[0, .25, .5, .75, 1].map(heat).join(',')})`;
const rows = () => (D.rows || []).filter(r => (!S.k || r.k === S.k) && (!S.g || r.g === S.g) && (!S.a || r.a === S.a));
// 공개 모드: 서버가 나라별로 미리 묶은 값만 받는다(적은 칸은 '기타(소수)'). 한 사람을 알아볼 수 있는 교차 필터는 끈다.
const PUB = !!D.public;
if (PUB) { document.getElementById('fg').hidden = true; document.getElementById('fa').hidden = true; }
const merge = list => list.reduce((m, v) => { m.n += v.n; m.ok += v.ok; m.okn += v.okn;
  ['a', 'g', 't', 'r'].forEach(k => Object.entries(v[k] || {}).forEach(([x, n]) => { m[k][x] = (m[k][x] || 0) + n; })); return m; },
  { n: 0, ok: 0, okn: 0, a: {}, g: {}, t: {}, r: {} });
function view() {
  if (PUB) {
    const A = D.agg[S.k] || {};
    return { byC: Object.fromEntries(Object.entries(A).map(([c, v]) => [c, v.n])), total: merge(Object.values(A)).n,
             panel: sel => sel ? A[sel] : merge(Object.values(A)), kr: (A['410'] || {}).r || {} };
  }
  const R = rows();
  const W = sub => sub.reduce((s, r) => s + (r.n || 1), 0);  // 행 = 같은 칸 묶음, n = 건수
  const sum = sub => ({ n: W(sub), okn: W(sub.filter(r => r.ok != null)), ok: W(sub.filter(r => r.ok)),
    a: count(sub, 'a'), g: count(sub, 'g'), t: count(sub.filter(r => r.t), 't'), r: count(sub, 'r') });
  return { byC: count(R, 'c'), total: W(R), panel: sel => sum(sel ? R.filter(r => r.c === sel) : R),
           kr: count(R.filter(r => r.c === '410' && r.r), 'r') };
}

function bars(title, counts) {
  const box = document.createDocumentFragment(); box.append(el('div', 'lbl', title));
  const wrap = el('div', 'rows'), entries = Object.entries(counts).sort((a, b) => b[1] - a[1]), max = Math.max(1, ...entries.map(e => e[1]));
  if (!entries.length) wrap.append(el('div', 'hint', '데이터 없음'));
  entries.slice(0, 6).forEach(([k, v]) => { const r = el('div', 'row'); const t = el('div', 'trk'), f = el('div', 'fil'); f.style.width = (v / max * 100) + '%'; t.append(f);
    r.append(el('span', null, k), t, el('b', null, fmt(v))); wrap.append(r); });
  box.append(wrap); return box;
}
const count = (arr, key) => arr.reduce((m, r) => { const v = typeof key === 'function' ? key(r) : r[key]; if (v) m[v] = (m[v] || 0) + (r.n || 1); return m; }, {});
function renderPanel(V) {
  const p = document.getElementById('panel'); p.replaceChildren();
  const P = V.panel(S.sel) || { n: 0 };
  p.append(el('div', 'eyebrow', S.sel ? 'Country' : 'Overview'), el('h4', null, S.sel ? nameOf[S.sel] : '전체 참여'));
  const acc = P.okn ? Math.round(P.ok / P.okn * 100) : null;
  p.append(el('div', 'meta', `참여 ${fmt(P.n)}건` + (acc != null ? ` · 퀴즈 정답률 ${acc}%` : '') + (S.sel ? ' · 다시 누르면 전체' : ' · 나라를 눌러 보세요')));
  if (!P.n) { p.append(el('div', 'empty', '아직 이 조건의 참여가 없습니다.\n테스트나 퀴즈 결과 화면에서 "참여 통계에 보태기"를 하면 여기에 나타나요.')); return; }
  p.append(bars('연령대', P.a), bars('성별', P.g));
  const types = Object.fromEntries(Object.entries(P.t || {}).map(([k, v]) => [D.typeNames[k] || k, v]));
  if (Object.keys(types).length) p.append(bars('AX 리더 유형', types));
  if (S.sel === '410') p.append(bars('국내 시·도', P.r));
  if (PUB) p.append(el('div', 'hint', '개인을 알아볼 수 없게 3건 미만인 칸은 기타(소수)로 묶어 보여 줍니다.'));
}

const HAS_D3 = !!(window.d3 && window.topojson);  // CDN을 못 받으면 표로 대신한다
const svg = HAS_D3 ? d3.select('#svg') : null, g = HAS_D3 ? svg.append('g') : null;
let projection, path, world = null, zoom;
function render() {
  const V = view(), byC = V.byC, max = Math.max(1, ...Object.values(byC));
  document.getElementById('total').textContent = `참여 ${fmt(V.total)}건 · 통계 참여자 ${fmt(D.profiles)}명`;
  renderPanel(V);
  if (!world) return renderFallback(byC);
  g.selectAll('path.country').attr('fill', d => byC[d.id] ? heat(.15 + .85 * Math.sqrt(byC[d.id] / max)) : '#0F1F3D')
    .classed('sel', d => d.id === S.sel);
  const kr = Object.fromEntries(Object.entries(V.kr).filter(([k]) => D.regions[k])), kmax = Math.max(1, ...Object.values(kr));
  const dots = g.selectAll('circle.dot').data(Object.entries(kr), d => d[0]);
  dots.exit().remove();
  dots.enter().append('circle').attr('class', 'dot').merge(dots)
    .attr('cx', d => projection([D.regions[d[0]][1], D.regions[d[0]][0]])[0]).attr('cy', d => projection([D.regions[d[0]][1], D.regions[d[0]][0]])[1])
    .attr('r', d => (1.2 + 3.5 * Math.sqrt(d[1] / kmax)) / (zoomK || 1) * 2)
    .on('pointermove', (e, d) => showTip(e.clientX, e.clientY, `${fmt(d[1])}건`, `대한민국 · ${d[0]}`, '#5BC2F5'))
    .on('pointerleave', hideTip);
}
let zoomK = 1;
function renderFallback(byC) {
  const p = document.getElementById('svg'); p.style.display = 'none';
  const host = p.parentElement; let t = host.querySelector('table.fb'); if (!t) { t = el('table', 'fb'); host.insertBefore(t, p); }
  t.replaceChildren(); const es = Object.entries(byC).sort((a, b) => b[1] - a[1]);
  if (!es.length) { const tr = el('tr'); tr.append(el('td', null, '지도를 불러오지 못했고, 아직 참여 데이터도 없습니다.')); t.append(tr); }
  es.forEach(([c, v]) => { const tr = el('tr'); tr.append(el('td', null, nameOf[c] || c), el('td', null, fmt(v) + '건')); tr.onclick = () => { S.sel = S.sel === c ? null : c; render(); }; t.append(tr); });
}
function draw() {
  const box = document.getElementById('svg').getBoundingClientRect(), W = box.width, H = box.height;
  projection = d3.geoNaturalEarth1().fitExtent([[8, 8], [W - 8, H - 8]], { type: 'Sphere' }); path = d3.geoPath(projection);
  g.selectAll('*').remove();
  g.append('path').datum({ type: 'Sphere' }).attr('d', path).attr('fill', '#07122A');
  g.selectAll('path.country').data(world.features).join('path').attr('class', 'country').attr('d', path)
    .on('pointermove', (e, d) => { const n = view().byC[d.id] || 0; showTip(e.clientX, e.clientY, `${fmt(n)}건`, nameOf[d.id] || d.properties.name, '#2E9BEA'); })
    .on('pointerleave', hideTip)
    .on('click', (e, d) => { S.sel = S.sel === d.id ? null : d.id; render(); });
  zoom = d3.zoom().scaleExtent([1, 40]).on('zoom', e => { zoomK = e.transform.k; g.attr('transform', e.transform);
    render(); });
  svg.call(zoom);
  render();
}
function zoomTo(lon, lat, k) {
  const [x, y] = projection([lon, lat]), box = document.getElementById('svg').getBoundingClientRect();
  svg.transition().duration(REDUCED ? 0 : 900).call(zoom.transform, d3.zoomIdentity.translate(box.width / 2 - x * k, box.height / 2 - y * k).scale(k));
}
document.getElementById('zk').onclick = () => world && zoomTo(127.8, 36.3, 14);
document.getElementById('zw').onclick = () => world && svg.transition().duration(REDUCED ? 0 : 700).call(zoom.transform, d3.zoomIdentity);

if (!HAS_D3) { render(); }
else fetch('/app/static/vendor/world-atlas-2.0.2-countries-110m.json').then(r => r.json()).then(t => {
  world = topojson.feature(t, t.objects.countries); draw(); addEventListener('resize', draw);
}).catch(() => render());
</script></body></html>
"""
