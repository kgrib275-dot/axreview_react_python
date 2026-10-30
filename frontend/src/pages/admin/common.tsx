// 관리 화면 공용 조각 — 관리 API 래퍼(403 → 토큰 입력), 토스트, 제목, 범용 표, 작은 막대 차트, CSV 내려받기.
// 백엔드 응답 모양이 조금 달라도 깨지지 않도록 "객체 배열이면 표, 객체면 키-값" 식으로 범용 렌더링한다.
import { Fragment, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, del, get, post, put } from "../../api";

export type Row = Record<string, unknown>;

// ---------- 관리 API ----------
let forbidden: () => void = () => undefined;
/** 403 이 오면 AdminApp 이 토큰 입력 화면을 띄우도록 등록한다. */
export const onForbidden = (fn: () => void) => {
  forbidden = fn;
};
async function wrap<T>(p: Promise<T>): Promise<T> {
  try {
    return await p;
  } catch (e) {
    if (e instanceof ApiError && e.status === 403) forbidden();
    throw e;
  }
}
/** `/api/admin/...` 전용 — 경로 앞의 admin/ 을 붙여 준다. */
export const A = {
  get: <T = unknown>(p: string) => wrap(get<T>("admin/" + p)),
  post: <T = unknown>(p: string, json?: unknown) => wrap(post<T>("admin/" + p, json)),
  put: <T = unknown>(p: string, json?: unknown) => wrap(put<T>("admin/" + p, json)),
  del: <T = unknown>(p: string, json?: unknown) => wrap(del<T>("admin/" + p, json)),
};
/** 쿼리스트링 — 빈 값은 뺀다. */
export const qs = (o: Record<string, unknown>) => {
  const s = Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== null && v !== "" && v !== false)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join("&");
  return s ? `?${s}` : "";
};

// ---------- 응답 모양 보정 ----------
export const isObj = (v: unknown): v is Row => !!v && typeof v === "object" && !Array.isArray(v);
/** 배열이면 그대로, 객체면 지정한 키(없으면 첫 배열 값)를 꺼낸다. */
export function asArray<T = Row>(v: unknown, ...keys: string[]): T[] {
  if (Array.isArray(v)) return v as T[];
  if (isObj(v)) {
    for (const k of keys) if (Array.isArray(v[k])) return v[k] as T[];
    const first = Object.values(v).find(Array.isArray);
    if (first) return first as T[];
  }
  return [];
}
/** 여러 후보 키 중 처음 있는 값. */
export function pick<T = unknown>(o: unknown, ...keys: string[]): T | undefined {
  if (!isObj(o)) return undefined;
  for (const k of keys) if (o[k] !== undefined && o[k] !== null) return o[k] as T;
  return undefined;
}
export const num = (v: unknown, d = 0) => (typeof v === "number" ? v : Number(v) || d);
export const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));
export const bool = (v: unknown) => v === true || v === 1 || v === "1" || v === "true";
export const splitCsv = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
export const today = () => new Date().toISOString().slice(0, 10);
export const addDays = (d: string, n: number) => {
  const t = new Date(d + "T00:00:00");
  t.setDate(t.getDate() + n);
  return t.toISOString().slice(0, 10);
};
/** 그 날이 속한 주의 월~일 (ISO 날짜). */
export function weekBounds(d: string): [string, string] {
  const t = new Date(d + "T00:00:00");
  const wd = (t.getDay() + 6) % 7; // 월=0
  const mon = addDays(d, -wd);
  return [mon, addDays(mon, 6)];
}
/** Streamlit 판 jobs.week_label 과 같은 꼴: 'YYYY년 M월 N주'. */
export function weekLabel(monday: string) {
  const t = new Date(monday + "T00:00:00");
  const n = Math.floor((t.getDate() - 1) / 7) + 1;
  return `${t.getFullYear()}년 ${t.getMonth() + 1}월 ${n}주`;
}

// ---------- 토스트 ----------
type Toast = { id: number; msg: string; kind: "info" | "ok" | "err" };
const ToastCtx = createContext<(msg: string, kind?: Toast["kind"]) => void>(() => undefined);
/** 새로고침(F5)해도 남는 화면 상태 — 탭·기간·필터·검색어·쪽 번호·보기 개수 등. 이 브라우저(관리자)에만 기억한다
 *  (localStorage, 화면 경로 + key — 관리자마다 따로). 문자열·숫자·배열·객체 모두 JSON 으로 저장. 2026-10-30 */
export function useRemembered<T>(key: string, initial: T): [T, (v: T | ((p: T) => T)) => void] {
  const k = `axreview-adm:${window.location.pathname}:${key}`;
  const read = (): T => {
    try {
      const raw = localStorage.getItem(k);
      if (raw === null) return initial;
      try {
        const parsed = JSON.parse(raw);
        // 저장된 모양이 지금 기대하는 모양과 다르면(예전 버전 값) 기본값
        if (Array.isArray(initial) !== Array.isArray(parsed) || (typeof initial !== "object" && typeof parsed !== typeof initial)) return initial;
        return parsed as T;
      } catch {
        return (typeof initial === "string" ? raw : initial) as T;  // 예전엔 문자열을 JSON 없이 저장했다
      }
    } catch { return initial; }
  };
  // 키가 바뀌면(예: 노트 검토의 탭별 필터) 그 키에 기억한 값을 다시 읽는다 — 앞 탭의 값이 따라오지 않게
  const [st, setSt] = useState<{ k: string; v: T }>(() => ({ k, v: read() }));
  const v = st.k === k ? st.v : read();
  if (st.k !== k) setSt({ k, v });
  const set = useCallback((nv: T | ((p: T) => T)) => {
    setSt((cur) => {
      const next = typeof nv === "function" ? (nv as (p: T) => T)(cur.v) : nv;
      try { localStorage.setItem(cur.k, JSON.stringify(next)); } catch { /* 사생활 보호 모드 */ }
      return { k: cur.k, v: next };
    });
  }, []);
  return [v, set];
}

/** 게시판 쪽 나누기 — 보기 개수·쪽 번호를 기억하고(F5 유지), 필터(sig)가 바뀌면 1쪽으로. 쪽이 줄면 마지막 쪽으로 맞춘다. */
export function usePaged<T>(key: string, rows: T[], sig: string, defaultSize = 20) {
  const [size, setSize] = useRemembered<number>(`${key}-size`, defaultSize);
  const [page, setPage] = useRemembered<number>(`${key}-page`, 1);
  const lastSig = useRef(sig);
  useEffect(() => {
    if (lastSig.current !== sig) { lastSig.current = sig; setPage(1); }  // 처음 그릴 때(F5 직후)는 기억한 쪽을 그대로 둔다
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps
  const pages = Math.max(1, Math.ceil(rows.length / size));
  const cur = Math.min(Math.max(1, page), pages);
  const shown = rows.slice((cur - 1) * size, cur * size);
  const info = `${rows.length}건${rows.length ? ` · ${(cur - 1) * size + 1}–${Math.min(cur * size, rows.length)}` : ""}`;
  const sizeSel = (
    <select className="pg-size" value={size} onChange={(e) => { setSize(Number(e.target.value)); setPage(1); }} aria-label="보기 개수">
      {[10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}개씩</option>)}
    </select>
  );
  const nums = [...new Set([1, pages, cur - 2, cur - 1, cur, cur + 1, cur + 2].filter((n) => n >= 1 && n <= pages))].sort((a, b) => a - b);
  const pager = pages > 1 ? (
    <nav className="pg-nav" aria-label="쪽 넘김">
      <button type="button" className="btn sm" disabled={cur <= 1} onClick={() => setPage(cur - 1)}>‹ 이전</button>
      {nums.map((n, i) => (
        <Fragment key={n}>
          {i > 0 && n - nums[i - 1] > 1 && <span className="caption">…</span>}
          <button type="button" className={`btn sm${n === cur ? " primary" : ""}`} onClick={() => setPage(n)} aria-current={n === cur ? "page" : undefined}>{n}</button>
        </Fragment>
      ))}
      <button type="button" className="btn sm" disabled={cur >= pages} onClick={() => setPage(cur + 1)}>다음 ›</button>
    </nav>
  ) : null;
  return { shown, info, sizeSel, pager, page: cur, pages };
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const toast = useCallback((msg: string, kind: Toast["kind"] = "info") => {
    const id = Date.now() + Math.random();
    setItems((l) => [...l, { id, msg, kind }]);
    window.setTimeout(() => setItems((l) => l.filter((t) => t.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={toast}>
      {children}
      <div className="toasts">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);
/** 동작 실행 패턴 — 성공 토스트, 실패 시 오류 토스트. 결과를 돌려주고 실패하면 undefined. */
export function useAct() {
  const toast = useToast();
  return useCallback(
    async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
      try {
        const r = await fn();
        if (ok) toast(ok, "ok");
        return r;
      } catch (e) {
        toast((e as Error).message || "실패했습니다.", "err");
        return undefined;
      }
    },
    [toast],
  );
}

// ---------- 머리글·조각 ----------
export function AdminHead({ title, note, right }: { title: string; note?: string; right?: React.ReactNode }) {
  return (
    <div className="sec-head adm-head">
      <div>
        <div className="eyebrow">Admin</div>
        <h2 className="sec-h">{title}</h2>
        {note && <span className="caption">{note}</span>}
      </div>
      {right}
    </div>
  );
}
export function Expander({ title, open, children }: { title: React.ReactNode; open?: boolean; children: React.ReactNode }) {
  return (
    <details className="expander" open={open}>
      <summary>{title}</summary>
      <div className="body">{children}</div>
    </details>
  );
}
export function Field({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`field ${className || ""}`}>
      <label>{label}</label>
      {children}
    </div>
  );
}
export function Check({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="chk">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}
export function Seg<T extends string | number>({ items, value, onChange, fmt }: { items: T[]; value: T; onChange: (v: T) => void; fmt?: (v: T) => string }) {
  return (
    <div className="seg">
      {items.map((it) => (
        <button key={String(it)} className={it === value ? "on" : ""} onClick={() => onChange(it)}>{fmt ? fmt(it) : String(it)}</button>
      ))}
    </div>
  );
}
/** 다중 선택 — 칩을 눌러 고른다 (max 를 넘으면 더 못 고름). */
export function Multi({ options, value, onChange, max, labels }: { options: string[]; value: string[]; onChange: (v: string[]) => void; max?: number; labels?: Record<string, string> }) {
  const toggle = (o: string) => {
    if (value.includes(o)) onChange(value.filter((x) => x !== o));
    else if (!max || value.length < max) onChange([...value, o]);
  };
  return (
    <div className="multi">
      {options.length === 0 && <span className="caption">선택할 항목이 없습니다.</span>}
      {options.map((o) => (
        <label key={o} className={value.includes(o) ? "on" : ""}>
          <input type="checkbox" checked={value.includes(o)} onChange={() => toggle(o)} style={{ display: "none" }} />
          {labels?.[o] ?? o}
        </label>
      ))}
    </div>
  );
}
export function Badge({ color, children }: { color: "green" | "red" | "orange" | "blue"; children: React.ReactNode }) {
  return <span className={`badge ${color}`}>{children}</span>;
}

// ---------- 값 표시 ----------
const URL_RE = /^https?:\/\/\S+$/;
export function fmt(v: unknown): React.ReactNode {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "✓" : "–";
  if (typeof v === "number") return Number.isInteger(v) ? v : Math.round(v * 1000) / 1000;
  if (typeof v === "string") {
    if (URL_RE.test(v)) return <a href={v} target="_blank" rel="noreferrer">열기</a>;
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(v)) return v.slice(0, 19).replace("T", " ");
    return v;
  }
  if (Array.isArray(v) && v.every((x) => typeof x !== "object")) return v.join(", ");
  return <code style={{ fontSize: ".78rem" }}>{JSON.stringify(v)}</code>;
}

/** 객체 배열 → 표. cols 로 열 순서를 정하고, 없으면 나오는 순서대로. render 로 열별 표시를 바꾼다. */
export function DataTable({ rows, cols, labels, render, empty = "데이터 없음", tall, selected, onToggle, rowKey, onAll }: {
  rows: Row[];
  cols?: string[];
  labels?: Record<string, string>;
  render?: Record<string, (v: unknown, row: Row, i: number) => React.ReactNode>;
  empty?: string;
  tall?: boolean;
  selected?: Set<string>;
  onToggle?: (key: string) => void;
  onAll?: (keys: string[]) => void;
  rowKey?: (row: Row, i: number) => string;
}) {
  const columns = useMemo(() => {
    if (cols) return cols;
    const seen: string[] = [];
    rows.forEach((r) => Object.keys(r).forEach((k) => !seen.includes(k) && seen.push(k)));
    return seen;
  }, [rows, cols]);
  if (!rows.length) return <p className="caption">{empty}</p>;
  const keyOf = (r: Row, i: number) => (rowKey ? rowKey(r, i) : String(i));
  const allKeys = rows.map(keyOf);
  const allOn = selected && allKeys.every((k) => selected.has(k));
  return (
    <div className={`table-wrap ${tall ? "tall" : ""}`}>
      <table className="table">
        <thead>
          <tr>
            {selected && (
              <th style={{ width: 28 }}>
                <input type="checkbox" checked={!!allOn} onChange={() => onAll?.(allOn ? [] : allKeys)} />
              </th>
            )}
            {columns.map((c) => <th key={c}>{labels?.[c] ?? c}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => {
            const k = keyOf(r, i);
            const on = selected?.has(k);
            return (
              <tr key={k} className={`${on ? "sel" : ""} ${onToggle ? "click" : ""}`} onClick={onToggle ? () => onToggle(k) : undefined}>
                {selected && (
                  <td onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={!!on} onChange={() => onToggle?.(k)} />
                  </td>
                )}
                {columns.map((c) => (
                  <td key={c} className={typeof r[c] === "number" ? "num" : ""}>
                    {render?.[c] ? render[c](r[c], r, i) : fmt(r[c])}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
/** 키-값 표 (객체 하나). */
export function KV({ obj }: { obj: Row }) {
  return (
    <div className="kv">
      {Object.entries(obj).map(([k, v]) => (
        <Fragment key={k}>
          <span className="k">{k}</span>
          <span>{isObj(v) || (Array.isArray(v) && v.some(isObj)) ? <Generic value={v} /> : fmt(v)}</span>
        </Fragment>
      ))}
    </div>
  );
}
/** 어떤 JSON 이든 — 객체 배열은 표, 객체는 키-값, 나머지는 글자. 모르는 응답을 보여 줄 때. */
export function Generic({ value, depth = 0 }: { value: unknown; depth?: number }) {
  if (Array.isArray(value)) {
    if (value.length && value.every(isObj)) return <DataTable rows={value as Row[]} />;
    return <span>{value.length ? value.map(String).join(", ") : "없음"}</span>;
  }
  if (isObj(value)) {
    const flat = Object.entries(value).filter(([, v]) => !isObj(v) && !(Array.isArray(v) && v.some(isObj)));
    const nested = Object.entries(value).filter(([, v]) => isObj(v) || (Array.isArray(v) && v.some(isObj)));
    return (
      <div className="json-sec">
        {flat.length > 0 && <KV obj={Object.fromEntries(flat)} />}
        {nested.map(([k, v]) => (
          <div key={k} className="json-sec">
            {depth === 0 ? <h4>{k}</h4> : <b style={{ fontSize: ".84rem" }}>{k}</b>}
            <Generic value={v} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  return <span>{fmt(value)}</span>;
}
/** 0~max 진행 막대 (점수·전환율 열). */
export function Bar({ v, max = 100, label }: { v: number; max?: number; label?: string }) {
  return (
    <span className="score">
      <span className="progress"><i style={{ width: `${Math.min(100, (v / max) * 100)}%` }} /></span>
      {label ?? v}
    </span>
  );
}

// ---------- 막대 차트 (라이브러리 없음) ----------
// 테마 토큰 — 다크에서는 예전 값(#2E9BEA·#5BC2F5·#C9D3E3·#0A6FD6·#fab219·#9be39b) 그대로
const COLORS = ["var(--accent)", "var(--accent-2)", "var(--silver)", "var(--accent-deep)", "var(--warn-ink)", "var(--ok-ink)"];
/** 묶음 세로 막대 — rows 의 labelKey 가 x축, series 가 각 막대. */
export function Bars({ rows, labelKey, series, height = 240 }: { rows: Row[]; labelKey: string; series: string[]; height?: number }) {
  const max = Math.max(1, ...rows.flatMap((r) => series.map((s) => num(r[s]))));
  if (!rows.length) return <p className="caption">데이터 없음</p>;
  const step = Math.max(1, Math.ceil(rows.length / 14)); // 라벨은 14개쯤만
  return (
    <div>
      <div className="bars" style={{ height }}>
        {rows.map((r, i) => (
          <div key={i} className="grp" title={`${str(r[labelKey])}: ${series.map((s) => `${s} ${num(r[s])}`).join(" · ")}`}>
            {series.map((s, j) => <i key={s} style={{ height: `${(num(r[s]) / max) * 100}%`, background: COLORS[j % COLORS.length] }} />)}
            {i % step === 0 && <span className="lbl">{str(r[labelKey]).slice(5)}</span>}
          </div>
        ))}
      </div>
      <div className="bars-legend">
        {series.map((s, j) => <span key={s}><i style={{ background: COLORS[j % COLORS.length] }} />{s}</span>)}
      </div>
    </div>
  );
}
/** 가로 막대 — [라벨, 값] 목록. */
export function HBars({ items }: { items: [string, number][] }) {
  const max = Math.max(1, ...items.map(([, v]) => v));
  if (!items.length) return <p className="caption">데이터 없음</p>;
  return (
    <div className="hbars">
      {items.map(([k, v], i) => (
        <Fragment key={k + i}>
          <span>{k}</span>
          <span className="bar"><i style={{ width: `${(v / max) * 100}%` }} /></span>
          <span className="n">{v}</span>
        </Fragment>
      ))}
    </div>
  );
}

// ---------- CSV ----------
export function downloadBlob(name: string, content: string | Blob, type = "text/csv") {
  const blob = content instanceof Blob ? content : new Blob(["﻿" + content], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function rowsToCsv(rows: Row[], cols?: string[]) {
  const columns = cols || Array.from(new Set(rows.flatMap((r) => Object.keys(r))));
  const esc = (v: unknown) => {
    let s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    if (/^[=+\-@]/.test(s)) s = "'" + s; // 수식 주입 방지 (db.csv_safe 와 같은 역할)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.join(","), ...rows.map((r) => columns.map((c) => esc(r[c])).join(","))].join("\n");
}
export function CsvButton({ name, rows, cols, label = "CSV 받기", fetchText }: { name: string; rows?: Row[]; cols?: string[]; label?: string; fetchText?: () => Promise<string> }) {
  const act = useAct();
  return (
    <button
      className="btn sm"
      onClick={() => act(async () => downloadBlob(name, fetchText ? await fetchText() : rowsToCsv(rows || [], cols)))}
    >
      ⬇ {label}
    </button>
  );
}
