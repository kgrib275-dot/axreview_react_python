// 배치 작업 실행 — 시작 버튼(POST jobs/{kind}), 진행 중이면 2초마다 GET jobs/status 로 로그 버퍼를 받아 터미널처럼 보여 준다.
// Streamlit 판 app/admin_ui.py 의 start_job · job_status · log_view · run_log_table 을 옮겼다.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, DataTable, Expander, Generic, Row, asArray, isObj, num, pick, str, useToast } from "./common";

export const KIND_LABELS: Record<string, string> = {
  collect: "수집", draft: "노트 초안", weekly: "주간 흐름", newsletter: "뉴스레터",
  vectorize: "벡터화", teams: "Teams 발송", report: "주간 PDF", warehouse: "Databricks 적재", preview: "수집 미리보기",
};
export const label = (kind: string) => KIND_LABELS[kind] || kind;

export type Line = { tm: string; lv: string; msg: string };
type Status = {
  active: Record<string, string>; // kind → 시작 시각
  logs: Record<string, Line[]>; // kind → joblog 버퍼
  last: { kind: string; ended: string; lines: Line[] } | null; // 마지막으로 끝난 작업
};

/** 로그 한 줄 — [tm, lv, msg] 배열이든 {time, level, msg} 객체든 받는다. */
export function toLine(x: unknown): Line {
  if (Array.isArray(x)) return { tm: str(x[0]), lv: str(x[1]) || "INFO", msg: str(x[2]) };
  if (isObj(x)) return { tm: str(pick(x, "tm", "time", "ts", "at")), lv: str(pick(x, "lv", "level")) || "INFO", msg: str(pick(x, "msg", "message", "text")) };
  return { tm: "", lv: "INFO", msg: str(x) };
}

function normalize(raw: unknown): Status {
  const o = isObj(raw) ? raw : {};
  const active: Record<string, string> = {};
  const a = pick(o, "active", "running");
  if (Array.isArray(a)) a.forEach((x) => (isObj(x) ? (active[str(x.kind)] = str(pick(x, "since", "started", "started_at"))) : (active[str(x)] = "")));
  else if (isObj(a)) Object.entries(a).forEach(([k, v]) => (active[k] = isObj(v) ? str(pick(v, "since", "started", "started_at")) : str(v)));
  const logs: Record<string, Line[]> = {};
  const l = pick(o, "logs", "joblog", "buffer", "lines");
  if (isObj(l)) Object.entries(l).forEach(([k, v]) => (logs[k] = asArray(v).map(toLine)));
  let last: Status["last"] = null;
  const lf = pick(o, "last", "last_finished");
  if (Array.isArray(lf) && lf.length) last = { kind: str(lf[0]), ended: str(lf[1]), lines: asArray(pick(o, "last_lines")).map(toLine) };
  else if (isObj(lf)) {
    const lines = asArray(pick(lf, "lines", "log", "logs")).map(toLine);
    last = { kind: str(lf.kind), ended: str(pick(lf, "ended", "ended_at", "finished", "finished_at", "at")), lines };
  }
  if (last && !last.lines.length && logs[last.kind]) last.lines = logs[last.kind];
  return { active, logs, last };
}

type Ctx = {
  status: Status;
  refresh: () => Promise<void>;
  start: (kind: string, kwargs?: Row) => Promise<boolean>;
  finished: number; // 작업이 끝날 때마다 +1 — 페이지가 다시 불러오는 신호
  isActive: (kind: string) => boolean;
};
const JobsCtx = createContext<Ctx>({ status: { active: {}, logs: {}, last: null }, refresh: async () => undefined, start: async () => false, finished: 0, isActive: () => false });

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>({ active: {}, logs: {}, last: null });
  const [finished, setFinished] = useState(0);
  const wasActive = useRef(false);
  const armed = useRef(0); // 방금 시작한 뒤 몇 번은 활성 목록이 비어도 계속 폴링
  const toast = useToast();

  const refresh = useCallback(async () => {
    try {
      const s = normalize(await A.get("jobs/status"));
      const nowActive = Object.keys(s.active).length > 0;
      if (wasActive.current && !nowActive) setFinished((n) => n + 1);
      wasActive.current = nowActive;
      setStatus(s);
    } catch {
      /* 403 은 common 이 처리, 나머지는 다음 폴링에서 다시 */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const active = Object.keys(status.active).length > 0;
  useEffect(() => {
    if (!active && armed.current <= 0) return;
    const t = window.setInterval(() => {
      if (!wasActive.current) armed.current -= 1;
      refresh();
    }, 2000);
    return () => window.clearInterval(t);
  }, [active, refresh, finished]);

  const start = useCallback(
    async (kind: string, kwargs: Row = {}) => {
      try {
        const r = await A.post<Row>(`jobs/${kind}`, kwargs);
        if (isObj(r) && (r.started === false || r.ok === false)) {
          toast("이미 같은 작업이 진행 중입니다.");
          return false;
        }
        toast(`${label(kind)} 작업을 시작했습니다.`, "ok");
        armed.current = 3;
        wasActive.current = true;
        setStatus((s) => ({ ...s, active: { ...s.active, [kind]: new Date().toISOString().slice(11, 19) } }));
        window.setTimeout(refresh, 300);
        return true;
      } catch (e) {
        toast((e as Error).message, "err");
        return false;
      }
    },
    [refresh, toast],
  );

  const value = useMemo<Ctx>(() => ({ status, refresh, start, finished, isActive: (k) => k in status.active }), [status, refresh, start, finished]);
  return <JobsCtx.Provider value={value}>{children}</JobsCtx.Provider>;
}
export const useJobs = () => useContext(JobsCtx);

/** 작업 시작 버튼 — 같은 작업이 돌고 있으면 비활성. */
export function StartJob({ kind, text, primary, kwargs, disabled, block, onStarted }: {
  kind: string; text?: string; primary?: boolean; kwargs?: Row; disabled?: boolean; block?: boolean; onStarted?: () => void;
}) {
  const { start, isActive } = useJobs();
  return (
    <button
      className={`btn ${primary ? "primary" : ""} ${block ? "block" : ""}`}
      disabled={disabled || isActive(kind)}
      onClick={async () => (await start(kind, kwargs)) && onStarted?.()}
    >
      {isActive(kind) ? "진행 중…" : text || `${label(kind)} 실행`}
    </button>
  );
}

/** 터미널 스타일 로그 — column-reverse 라 스크롤이 항상 최신 줄(맨 아래)에 머문다. */
export function LogView({ lines, live }: { lines: Line[]; live?: boolean }) {
  return (
    <div className="joblog">
      <div>
        {lines.length === 0 && <div className="empty">로그를 기다리는 중…</div>}
        {lines.map((l, i) => (
          <div key={i} className={`ln ${l.lv}`}>
            <span className="tm">{l.tm}</span>
            <span className="lv">{l.lv.slice(0, 4)}</span>
            <span className="msg">{l.msg}</span>
          </div>
        ))}
        {live && <div className="ln"><span className="cursor" /></div>}
      </div>
    </div>
  );
}

/** 진행 중 작업 + 실행 로그, 없으면 '마지막 실행 로그' 펼침. */
export function JobStatus({ only }: { only?: string[] }) {
  const { status } = useJobs();
  const kinds = Object.keys(status.active).filter((k) => !only || only.includes(k));
  if (kinds.length) {
    return (
      <div>
        {kinds.map((k) => (
          <div key={k}>
            <Alert kind="info">⏳ {label(k)} 작업 진행 중{status.active[k] && ` (시작 ${status.active[k]})`}</Alert>
            <LogView lines={status.logs[k] || []} live />
          </div>
        ))}
      </div>
    );
  }
  const last = status.last;
  if (!last || (only && !only.includes(last.kind))) return null;
  return (
    <Expander title={`▣ 마지막 실행 로그 · ${label(last.kind)}${last.ended ? ` (종료 ${last.ended})` : ""}`}>
      <LogView lines={last.lines} />
    </Expander>
  );
}

/** run_logs 요약 문구 (admin_ui._summary). */
export function summary(kind: string, result: Row): string {
  if (!result || !Object.keys(result).length) return "";
  const n = (k: string) => num(result[k]);
  const len = (k: string) => asArray(result[k]).length;
  switch (kind) {
    case "collect": {
      let s = `수집 ${n("collected")} → 신규 ${n("new")} → 키워드 통과 ${n("filtered")} (채점 ${n("scored")}, 재채점 ${n("rescored")})`;
      const se = result.source_errors;
      if (se && (Array.isArray(se) ? se.length : isObj(se) && Object.keys(se).length)) s += ` · 실패 소스 ${Array.isArray(se) ? se.length : Object.keys(se as Row).length}`;
      return s;
    }
    case "draft": return `대상 ${n("targets")} · 초안 ${len("created")} · 실패 ${len("failed")}`;
    case "weekly": return `${str(result.week)} · 노트 ${str(result.notes)}편 · ${result.published ? "게시" : "초안"}`;
    case "newsletter":
    case "teams": return `발송 ${n("sent")} · 실패 ${len("failed")}`;
    case "vectorize":
      return Object.entries(result).filter(([, v]) => isObj(v)).map(([t, v]) => `${t === "notes" ? "노트" : "기사"} ${str((v as Row).embedded)}/${str((v as Row).pending)}`).join(" · ");
    case "report": return `${str(result.file)} · ${str(result.pages)}쪽`;
    case "warehouse": {
      const tables = isObj(result.tables) ? (result.tables as Record<string, Row>) : {};
      const parts = Object.entries(tables).filter(([, v]) => num(v.upserted) || num(v.deleted)).map(([t, v]) => `${t} ${num(v.upserted)}${num(v.deleted) ? `(-${num(v.deleted)})` : ""}`);
      let s = parts.join(" · ") || "바뀐 행 없음";
      if (len("failed")) s += ` · 실패 ${asArray(result.failed).map(String).join(", ")}`;
      return `${str(result.target)} ← ${s}`;
    }
    default: return "";
  }
}

function parseResult(r: unknown): Row {
  if (isObj(r)) return r;
  if (typeof r === "string" && r.trim()) {
    try {
      const j = JSON.parse(r);
      return isObj(j) ? j : {};
    } catch {
      return {};
    }
  }
  return {};
}

/** 배치 실행 기록 표 — rows 를 주면 그대로, 없으면 GET jobs/logs 로 가져온다. */
export function RunLogTable({ kind, limit = 50, rows: given }: { kind?: string; limit?: number; rows?: Row[] }) {
  const { finished } = useJobs();
  const { data, error } = useLoad(async () => (given ? given : asArray(await A.get(`jobs/logs?limit=${limit}${kind ? `&kind=${kind}` : ""}`), "logs", "run_logs", "rows")), [kind, limit, given, finished]);
  const logs = (data || []).filter((r) => !kind || r.kind === kind).slice(0, limit);
  if (error) return <Alert kind="err">{error}</Alert>;
  if (!logs.length) return <p className="caption">실행 기록이 없습니다.</p>;
  const view = logs.map((r) => {
    const result = parseResult(r.result);
    return {
      시작: str(r.started_at).replace("T", " ").slice(0, 19),
      작업: label(str(r.kind)),
      트리거: str(r.trigger),
      결과: r.ok ? "성공" : "주의",
      요약: str(r.message) || summary(str(r.kind), result),
    };
  });
  const first = parseResult(logs[0].result);
  return (
    <div>
      <DataTable rows={view} />
      <Expander title="최근 실행 상세 (JSON)">
        <Generic value={Object.keys(first).length ? first : { message: str(logs[0].message) }} />
      </Expander>
    </div>
  );
}
