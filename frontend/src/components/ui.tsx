// 작은 공용 조각 — 섹션 제목, 안내 상자, 알림, 대화상자 틀, 탭.
import { useEffect, useState } from "react";

export function Eyebrow({ children }: { children: React.ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}

export function SectionHead({ eyebrow, title, grad, p, right }: { eyebrow?: string; title: string; grad?: string; p?: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="sec-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h2 className="sec-h">
          {title} {grad && <span className="grad">{grad}</span>}
        </h2>
        {p && <p className="sec-p">{p}</p>}
      </div>
      {right}
    </div>
  );
}

export function Guide({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div className="guide">
      <div className="guide-h">👀 {title}</div>
      <ol>
        {items.map(([h, d]) => (
          <li key={h}>
            <b>{h}</b>
            <span>{d}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function Alert({ kind = "info", children }: { kind?: "info" | "ok" | "warn" | "err"; children: React.ReactNode }) {
  return <div className={`alert ${kind}`}>{children}</div>;
}

export function Dialog({ title, onClose, wide, children }: { title: string; onClose: () => void; wide?: boolean; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="dlg-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dlg ${wide ? "wide" : ""}`} role="dialog" aria-label={title}>
        <div className="dlg-h">
          <h3>{title}</h3>
          <button className="x" aria-label="닫기" onClick={onClose}>×</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Tabs({ items, value, onChange }: { items: string[]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t} role="tab" className={t === value ? "on" : ""} onClick={() => onChange(t)}>{t}</button>
      ))}
    </div>
  );
}

export function Metric({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="metric">
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}

/** 불러오기 패턴 — 로딩·오류·데이터를 한 번에. */
export function useLoad<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    loader().then((d) => alive && (setData(d), setError(null))).catch((e) => alive && setError(e.message)).finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, loading, reload: () => setTick((t) => t + 1), setData };
}
