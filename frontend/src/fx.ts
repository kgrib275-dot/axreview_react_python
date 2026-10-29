// 화면 인터랙션 — Streamlit 판(v1) app/fx.py 를 옮김 (원본 사이트 fx.js·sphere.js 성격).
//   ① 커서 스포트라이트  ② 카드 3D 기울기 + 마우스 위치 광택  ③ 스크롤 등장(순차)
//   ④ 상단 스크롤 진행 바 + 헤더 스크롤 상태  ⑥ 히어로 3D 구체 네트워크 캔버스
// (⑤ 숫자 카운트업은 Home.tsx 의 CountUp 이 한다.)
// React 가 화면을 바꿔도 동작하도록 이벤트 위임 + MutationObserver 로 새 요소를 잡는다.
// prefers-reduced-motion 이면 움직임을 끄고, 터치 기기(pointer: coarse)는 기울기·스포트라이트를 끈다.
import "./styles/fx.css";

const SEL = ".card,.sec-head,.week-title,.week-body,.flow,.cat-nav a,.hero-lead,.hero-sub,.hero-stats,.cta-card,.site-foot";

export function startFx(): void {
  const w = window as unknown as { __axfx?: boolean };
  if (w.__axfx) return;
  w.__axfx = true;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = matchMedia("(pointer: fine)").matches;
  const doc = document;

  // ① 스포트라이트 + ④ 진행 바
  const spot = doc.createElement("div"); spot.id = "ax-spot"; doc.body.appendChild(spot);
  const bar = doc.createElement("div"); bar.id = "ax-progress"; doc.body.appendChild(bar);
  if (fine && !reduce) {
    addEventListener("pointermove", (e) => {
      spot.style.setProperty("--px", e.clientX + "px"); spot.style.setProperty("--py", e.clientY + "px");
    }, { passive: true });
  }
  const onScroll = () => {
    const el = doc.scrollingElement || doc.documentElement;
    const max = el.scrollHeight - el.clientHeight, y = el.scrollTop;
    bar.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
    doc.querySelector(".hdr")?.classList.toggle("ax-scrolled", y > 12);
  };
  addEventListener("scroll", onScroll, { passive: true });

  // ② 카드 기울기 (이벤트 위임)
  doc.addEventListener("pointermove", (e) => {
    const c = (e.target as Element | null)?.closest?.("a.card") as HTMLElement | null;
    if (!c) return;
    const r = c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    c.style.setProperty("--mx", x + "px"); c.style.setProperty("--my", y + "px");
    if (fine && !reduce) {
      c.classList.add("ax-tilting");
      c.style.transform = `perspective(700px) rotateX(${(y / r.height - 0.5) * -7}deg) rotateY(${(x / r.width - 0.5) * 9}deg) translateY(-3px)`;
    }
  }, { passive: true });
  doc.addEventListener("pointerout", (e) => {
    const c = (e.target as Element | null)?.closest?.("a.card") as HTMLElement | null;
    if (c && !c.contains(e.relatedTarget as Node | null)) { c.style.transform = ""; c.classList.remove("ax-tilting"); }
  });

  // ③ 등장
  const io = new IntersectionObserver((entries) => entries.forEach((en) => {
    if (!en.isIntersecting) return;
    en.target.classList.add("ax-in"); en.target.classList.remove("ax-rv");
    io.unobserve(en.target);
  }), { threshold: 0.12 });
  const scan = () => {
    if (!reduce) {
      const groups = new Map<Element | null, number>();
      doc.querySelectorAll<HTMLElement>(SEL).forEach((el) => {
        if (el.classList.contains("ax-rv") || el.classList.contains("ax-in")) return;
        const p = el.parentElement, i = groups.get(p) || 0; groups.set(p, i + 1);
        el.style.setProperty("--d", String(Math.min(i, 8)));
        el.classList.add("ax-rv"); io.observe(el);
      });
    }
    initSphere();
  };
  // 관찰이 실패해도 내용이 숨겨진 채로 남지 않게
  setInterval(() => doc.querySelectorAll(".ax-rv").forEach((el) => {
    if (el.getBoundingClientRect().top < innerHeight) { el.classList.add("ax-in"); el.classList.remove("ax-rv"); }
  }), 1500);
  let pending = false;
  new MutationObserver(() => {
    if (pending) return; pending = true;
    requestAnimationFrame(() => { pending = false; scan(); });
  }).observe(doc.body, { childList: true, subtree: true });

  // ⑥ 3D 구체 네트워크 — 피보나치 구 위 점들이 회전하고 가까운 점끼리 이어진다. 마우스를 따라 기울어진다.
  let tx = 0, ty = 0;
  if (fine && !reduce) addEventListener("pointermove", (e) => { tx = (e.clientY / innerHeight - 0.5) * 0.6; ty = (e.clientX / innerWidth - 0.5) * 0.8; }, { passive: true });
  function initSphere() {
    const hero = doc.querySelector<HTMLElement>(".hero");
    if (!hero || hero.querySelector("canvas.ax-sphere")) return;
    const cv = doc.createElement("canvas"); cv.className = "ax-sphere"; cv.setAttribute("aria-hidden", "true");
    hero.prepend(cv); hero.classList.add("ax-has-canvas");
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const N = innerWidth < 760 ? 110 : 180, pts: [number, number, number][] = [];
    for (let i = 0; i < N; i++) {
      const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = Math.PI * (3 - Math.sqrt(5)) * i;
      pts.push([Math.cos(th) * r, y, Math.sin(th) * r]);
    }
    let rx = 0.35, ry = 0, visible = true, raf = 0;
    new IntersectionObserver((es) => { visible = es[0].isIntersecting; if (visible && !raf) raf = requestAnimationFrame(draw); }).observe(cv);
    function draw() {
      raf = 0;
      if (!cv.isConnected || !ctx) return;
      const dpr = Math.min(2, devicePixelRatio || 1), w = cv.clientWidth, h = cv.clientHeight;
      if (cv.width !== w * dpr) { cv.width = w * dpr; cv.height = h * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, w, h);
      if (!reduce) { ry += 0.0026; rx += (tx + 0.35 - rx) * 0.03; }
      const R = Math.min(w, h) * 0.42, cx = w / 2, cy = h / 2, cX = Math.cos(rx), sX = Math.sin(rx),
        cY = Math.cos(ry + ty), sY = Math.sin(ry + ty), P: [number, number, number][] = [];
      for (const [x, y, z] of pts) {
        const x1 = x * cY + z * sY, z1 = -x * sY + z * cY, y1 = y * cX - z1 * sX, z2 = y * sX + z1 * cX;
        const s = 2.4 / (2.4 + z2); P.push([cx + x1 * R * s, cy + y1 * R * s, z2]);
      }
      ctx.lineWidth = 0.7;
      const lim = (R * 0.26) ** 2;
      for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
        const dx = P[i][0] - P[j][0], dy = P[i][1] - P[j][1], d = dx * dx + dy * dy;
        if (d < lim) {
          const a = (1 - d / lim) * (0.35 - (P[i][2] + P[j][2]) * 0.12);
          if (a > 0) { ctx.strokeStyle = `rgba(46,155,234,${a})`; ctx.beginPath(); ctx.moveTo(P[i][0], P[i][1]); ctx.lineTo(P[j][0], P[j][1]); ctx.stroke(); }
        }
      }
      for (const [x, y, z] of P) {
        const a = 0.25 + (1 - z) * 0.38;
        ctx.fillStyle = z < -0.3 ? `rgba(91,194,245,${a})` : `rgba(46,155,234,${a})`;
        ctx.beginPath(); ctx.arc(x, y, z < -0.3 ? 2.2 : 1.5, 0, 6.283); ctx.fill();
      }
      if (visible && !reduce && !doc.hidden) raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    doc.addEventListener("visibilitychange", () => { if (!doc.hidden && visible && !raf) raf = requestAnimationFrame(draw); });
  }

  scan(); onScroll();
}
