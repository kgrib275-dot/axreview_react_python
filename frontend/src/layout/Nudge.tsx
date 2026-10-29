// 하단 구독 띠 — 화면의 35%를 내리거나 25초가 지나면 올라온다. 닫으면 7일, 누르면 1일 동안 다시 띄우지 않는다 (localStorage).
import { useEffect, useState } from "react";

const KEY = "axreview-nudge-until";

export default function Nudge({ onSubscribe }: { onSubscribe: () => void }) {
  const [show, setShow] = useState(false);
  const [hidden, setHidden] = useState(() => {
    try { return Date.now() < (+localStorage.getItem(KEY)! || 0); } catch { return false; }
  });
  useEffect(() => {
    if (hidden) return;
    const t = window.setTimeout(() => setShow(true), 25000);
    const onScroll = () => {
      const el = document.scrollingElement!;
      if (el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight) > 0.35) setShow(true);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => { window.clearTimeout(t); window.removeEventListener("scroll", onScroll); };
  }, [hidden]);
  const hide = (days: number) => {
    try { localStorage.setItem(KEY, String(Date.now() + days * 864e5)); } catch { /* 사생활 보호 모드 */ }
    setHidden(true);
  };
  if (hidden) return null;
  return (
    <div id="ax-nudge" className={show ? "show" : ""} role="region" aria-label="구독 안내">
      <div className="t">📬 매주 월요일 3분, 한 주의 AX 흐름을 메일로<small>노트 5편 + 주간 PDF 리포트 · 언제든 해지</small></div>
      <button className="go" type="button" onClick={() => { onSubscribe(); hide(1); }}>무료 구독</button>
      <button className="x" type="button" aria-label="닫기" onClick={() => hide(7)}>×</button>
    </div>
  );
}
