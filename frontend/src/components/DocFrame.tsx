// HTML 문서를 iframe srcdoc 으로 띄우는 조각 — 참여 지도(/today)·데이터 랩(/lab)이 쓴다.
// 높이: 문서가 postMessage 로 {height} (또는 숫자)를 보내면 그 값, 아니면 같은 출처(srcdoc)라 직접 재고, 둘 다 안 되면 fallback.
import { useEffect, useRef, useState } from "react";

type Props = { html: string; title: string; fallback?: number; minHeight?: number; className?: string };

export default function DocFrame({ html, title, fallback = 1400, minHeight = 240, className = "" }: Props) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState<number>(fallback);

  // 문서 안에서 보낸 높이 (window.parent.postMessage({height: n}) 또는 postMessage(n))
  useEffect(() => {
    const onMsg = (e: MessageEvent) => {
      if (!ref.current || e.source !== ref.current.contentWindow) return;
      const d = e.data as unknown;
      const h = typeof d === "number" ? d : (d && typeof d === "object" && "height" in d ? Number((d as { height: unknown }).height) : NaN);
      if (Number.isFinite(h) && h > 0) setHeight(Math.max(minHeight, Math.ceil(h)));
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
  }, [minHeight]);

  // srcdoc 은 같은 출처라 문서 높이를 직접 잴 수 있다 — 글꼴·스크립트가 늦게 그려지므로 몇 번 다시 잰다.
  const measure = () => {
    try {
      const doc = ref.current?.contentDocument;
      if (!doc?.body) return;
      const h = Math.max(doc.body.scrollHeight, doc.documentElement?.scrollHeight || 0);
      if (h > 0) setHeight(Math.max(minHeight, h));
    } catch {
      /* 다른 출처면 건드리지 않는다 */
    }
  };
  useEffect(() => {
    setHeight(fallback);
    const timers = [300, 1000, 2500].map((ms) => window.setTimeout(measure, ms));
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [html]);

  return (
    <iframe ref={ref} className={`doc-frame ${className}`} title={title} srcDoc={html} style={{ height }} onLoad={measure}
      sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox" loading="lazy" />
  );
}
