// 수집 기사 — 기간·상태·최소 점수·검색 필터, 행 선택 → 초안 생성 / 건너뛰기 / 대기로 되돌리기 (app_pages/admin/articles.py).
import { useMemo, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, AdminHead, Bar, DataTable, Row, asArray, num, pick, qs, str, useAct, usePaged, useRemembered } from "./common";
import { JobStatus, useJobs } from "./JobRunner";

const STATUS_LABEL: Record<string, string> = { new: "대기", drafted: "초안됨", skipped: "건너뜀" };
const hashOf = (a: Row) => str(pick(a, "url_hash", "hash", "id"));

export default function Articles() {
  const [days, setDays] = useRemembered<number>("days", 7);
  // 필터·검색은 F5 해도 남는다 (useRemembered — 이 브라우저에만)
  const [status, setStatus] = useRemembered<string[]>("status", ["new"]);
  const [minScore, setMinScore] = useRemembered<number>("min", 3);
  const [q, setQ] = useRemembered<string>("q", "");
  const [qApplied, setQApplied] = useRemembered<string>("qa", "");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const { finished, start, isActive } = useJobs();
  const act = useAct();
  const { data, error, reload } = useLoad(async () => asArray(await A.get(`articles${qs({ days, q: qApplied, min_score: minScore })}`), "articles", "items", "rows"), [days, qApplied, minScore, finished]);

  const rows = useMemo(() => {
    const all = data || [];
    const ql = q.trim().toLowerCase();
    return all.filter((a) => (!status.length || status.includes(str(a.status))) && num(pick(a, "llm_score", "score")) >= minScore
      && (!ql || `${str(a.title)} ${str(pick(a, "summary_ko", "summary"))} ${str(a.source)}`.toLowerCase().includes(ql)));
  }, [data, status, minScore, q]);
  const view = rows.map((a) => ({
    점수: num(pick(a, "llm_score", "score")), 제목: str(a.title), 요약: str(pick(a, "summary_ko", "summary")) || str(a.excerpt), 소스: str(a.source),
    키워드: Array.isArray(a.matched_kw) ? a.matched_kw.join(", ") : (() => { try { return JSON.parse(str(a.matched_kw) || "[]").join(", "); } catch { return str(a.matched_kw); } })(),
    발행: str(a.published_at).slice(0, 16).replace("T", " "), 상태: STATUS_LABEL[str(a.status)] || str(a.status), URL: str(a.url), _h: hashOf(a),
  }));
  const pg = usePaged("articles", view, `${days}|${status.join(",")}|${minScore}|${q}`, 50);
  const selected = Array.from(sel).filter((h) => rows.some((a) => hashOf(a) === h));
  const setStatuses = async (s: string) => {
    await act(async () => { for (const h of selected) await A.put(`articles/${h}/status`, { status: s }); }, `${selected.length}건을 ${STATUS_LABEL[s]}(으)로 바꿨습니다.`);
    setSel(new Set());
    reload();
  };

  return (
    <div>
      <AdminHead title="수집 기사" note="키워드 필터를 통과한 기사입니다. 점수는 Gemini가 매긴 AX 노트 가치(1~5)입니다." />
      <JobStatus />
      <div className="inline" style={{ margin: "10px 0" }}>
        <div className="field narrow">
          <label>기간</label>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[1, 3, 7, 30, 90].map((d) => <option key={d} value={d}>최근 {d}일</option>)}</select>
        </div>
        <div className="field narrow">
          <label>상태</label>
          <div className="pills">
            {Object.entries(STATUS_LABEL).map(([k, l]) => (
              <button key={k} className={`pill ${status.includes(k) ? "on" : ""}`} onClick={() => setStatus(status.includes(k) ? status.filter((x) => x !== k) : [...status, k])}>{l}</button>
            ))}
          </div>
        </div>
        <div className="field narrow">
          <label>최소 점수 {minScore}</label>
          <input type="range" min={0} max={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} />
        </div>
        <div className="field">
          <label>검색</label>
          <input type="text" placeholder="제목·요약·소스" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setQApplied(q)} onBlur={() => setQApplied(q)} />
        </div>
      </div>
      {error && <Alert kind="err">{error}</Alert>}
      <div className="board-bar"><p className="caption" style={{ margin: 0 }}>{pg.info} · 행을 선택하고 아래 버튼으로 초안을 만들거나 건너뛰세요.</p><span className="sp" />{pg.sizeSel}</div>
      <DataTable
        rows={pg.shown} cols={["점수", "제목", "요약", "소스", "키워드", "발행", "상태", "URL"]} tall
        render={{ 점수: (v) => <Bar v={num(v)} max={5} label={String(num(v))} />, 요약: (v) => <span className="trunc" title={str(v)}>{str(v)}</span>, 제목: (v) => <span className="trunc" style={{ maxWidth: 300 }} title={str(v)}>{str(v)}</span> }}
        rowKey={(r) => str(r._h)} selected={sel} onToggle={(k) => setSel((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; })} onAll={(ks) => setSel(new Set(ks))}
      />
      {pg.pager}
      <div className="btn-row" style={{ marginTop: 12 }}>
        <button className="btn primary" disabled={!selected.length || isActive("draft")} onClick={async () => { if (await start("draft", { hashes: selected })) setSel(new Set()); }}>📝 선택 {selected.length}건 초안 생성</button>
        <button className="btn" disabled={!selected.length} onClick={() => setStatuses("skipped")}>⏭ 선택 {selected.length}건 건너뛰기</button>
        <button className="btn" disabled={!selected.length} onClick={() => setStatuses("new")}>↩ 선택 {selected.length}건 대기로 되돌리기</button>
      </div>
    </div>
  );
}
