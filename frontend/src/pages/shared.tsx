// 여러 페이지가 함께 쓰는 작은 조각 — 홈(Home.tsx)에서 옮김. 노트·소개 페이지가 이것 때문에 홈 코드·홈 CSS 까지 받지 않게.
import { useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { track } from "../api";

export const CATEGORIES = ["AX Strategy", "AX Implementation", "AX Enablement"];

/** 숫자 카운트업 — 화면에 들어오면 0에서 목표까지 1.1초 동안 오른다 (app/fx.py ⑤와 같은 곡선). */
export function CountUp({ to }: { to: number }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const run = () => {
      if (reduce) { el.textContent = to.toLocaleString("ko-KR"); return; }
      const t0 = performance.now(), dur = 1100;
      const step = (t: number) => {
        const p = Math.min(1, (t - t0) / dur);
        el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))).toLocaleString("ko-KR");
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { run(); io.disconnect(); } }), { threshold: 0.12 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to]);
  return <b ref={ref} data-to={to}>{to.toLocaleString("ko-KR")}</b>;
}

/** 공유 링크(?s=1)로 들어온 방문 기록 — 세션마다 한 번. */
export function useShareVisit(content: string) {
  const [params] = useSearchParams();
  useEffect(() => {
    if (params.get("s") !== "1") return;
    const key = `_sv_${content}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch { /* 저장소가 막혀도 기록은 한다 */ }
    track("share_visit", content);
  }, [params, content]);
}
