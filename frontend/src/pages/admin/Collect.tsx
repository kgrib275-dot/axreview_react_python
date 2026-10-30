// 수집 설정 — 소스 on/off(그룹별), 키워드 규칙 편집, 수집 테스트(미리보기·선택 소스 실제 수집) (app_pages/admin/collect_settings.py).
import { useEffect, useState } from "react";
import { Alert, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, Check, DataTable, Multi, Row, asArray, bool, isObj, num, pick, str, useAct, useRemembered } from "./common";
import { JobStatus, LogView, StartJob, toLine } from "./JobRunner";
import { CATEGORIES } from "./Review";

const SECTIONS = ["소스 on/off", "키워드", "수집 테스트"];

function Sources() {
  const { data, error, reload } = useLoad(() => A.get<unknown>("sources"), []);
  const act = useAct();
  const sources = asArray(data, "sources", "items");
  const [on, setOn] = useState<Set<string>>(new Set());
  useEffect(() => {
    const enabledList = isObj(data) ? asArray<string>(pick(data, "enabled", "enabled_sources")) : [];
    setOn(new Set(enabledList.length ? enabledList.map(String) : sources.filter((s) => bool(pick(s, "enabled", "active"))).map((s) => str(s.name))));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  const groups = Array.from(new Set(sources.map((s) => str(s.group))));
  const toggle = (n: string, v: boolean) => setOn((s) => { const x = new Set(s); v ? x.add(n) : x.delete(n); return x; });
  return (
    <div>
      {error && <Alert kind="err">{error}</Alert>}
      {groups.map((g) => {
        const list = sources.filter((s) => str(s.group) === g);
        const allOn = list.every((s) => on.has(str(s.name)));
        return (
          <div key={g} className="box sm">
            <div className="btn-row" style={{ marginBottom: 6 }}>
              <b>{g || "(그룹 없음)"}</b>
              <span className="caption">{list.filter((s) => on.has(str(s.name))).length} / {list.length}</span>
              <button className="btn sm ghost" onClick={() => list.forEach((s) => toggle(str(s.name), !allOn))}>{allOn ? "모두 끄기" : "모두 켜기"}</button>
            </div>
            <DataTable
              rows={list.map((s) => ({ 사용: str(s.name), 소스: str(s.name), 유형: str(s.type), "기간(시간)": num(s.published_within_hours, 24), URL: str(s.url) }))}
              render={{ 사용: (v) => <input type="checkbox" checked={on.has(str(v))} onChange={(e) => toggle(str(v), e.target.checked)} /> }}
            />
          </div>
        );
      })}
      <div className="btn-row" style={{ marginTop: 10 }}>
        <span className="caption">{on.size} / {sources.length}개 사용</span>
        <button className="btn primary" onClick={async () => { await act(() => A.put("sources", { enabled: Array.from(on) }), "소스 설정을 저장했습니다."); reload(); }}>💾 저장</button>
      </div>
    </div>
  );
}

type Kw = { keyword: string; aliases: string; mode: string; weight: number; active: boolean; category: string };
function Keywords() {
  const { data, error, reload } = useLoad(() => A.get<unknown>("keywords"), []);
  const act = useAct();
  const [rows, setRows] = useState<Kw[]>([]);
  useEffect(() => {
    setRows(asArray(data, "keywords", "items", "rules").map((k) => ({
      keyword: str(k.keyword), aliases: Array.isArray(k.aliases) ? k.aliases.join(", ") : str(k.aliases), mode: str(k.mode) || "include",
      weight: num(k.weight, 1), active: k.active === undefined ? true : bool(k.active), category: str(k.category),
    })));
  }, [data]);
  const upd = (i: number, p: Partial<Kw>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...p } : x)));
  const save = async () => {
    const body = rows.filter((r) => r.keyword.trim()).map((r) => ({ keyword: r.keyword.trim(), aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean), mode: r.mode, weight: r.weight || 1, active: r.active, category: r.category }));
    await act(() => A.put("keywords", { keywords: body }), "키워드를 저장했습니다.");
    reload();
  };
  return (
    <div>
      <p className="caption">include 키워드 중 하나 이상이 제목·발췌에 있어야 후보가 되고, exclude가 걸리면 버립니다. 별칭은 쉼표로 구분합니다.</p>
      {error && <Alert kind="err">{error}</Alert>}
      <div className="table-wrap tall">
        <table className="table">
          <thead><tr><th>사용</th><th>키워드</th><th style={{ width: "32%" }}>별칭</th><th>모드</th><th>가중치</th><th>카테고리</th><th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><input type="checkbox" checked={r.active} onChange={(e) => upd(i, { active: e.target.checked })} /></td>
                <td><input type="text" value={r.keyword} onChange={(e) => upd(i, { keyword: e.target.value })} /></td>
                <td><input type="text" value={r.aliases} onChange={(e) => upd(i, { aliases: e.target.value })} /></td>
                <td><select value={r.mode} onChange={(e) => upd(i, { mode: e.target.value })}><option>include</option><option>exclude</option></select></td>
                <td><input type="number" min={0.1} max={5} step={0.5} value={r.weight} onChange={(e) => upd(i, { weight: Number(e.target.value) })} /></td>
                <td><select value={r.category} onChange={(e) => upd(i, { category: e.target.value })}><option value="">(없음)</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></td>
                <td><button className="btn sm ghost" onClick={() => setRows((x) => x.filter((_, j) => j !== i))}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="btn-row" style={{ marginTop: 10 }}>
        <button className="btn" onClick={() => setRows((r) => [...r, { keyword: "", aliases: "", mode: "include", weight: 1, active: true, category: "" }])}>＋ 행 추가</button>
        <button className="btn primary" onClick={save}>💾 키워드 저장</button>
      </div>
    </div>
  );
}

function TestCollect() {
  const { data } = useLoad(() => A.get<unknown>("sources"), []);
  const act = useAct();
  const names = asArray(data, "sources", "items").map((s) => str(s.name));
  const [picked, setPicked] = useState<string[]>([]);
  useEffect(() => { if (names.length && !picked.length) setPicked(names.slice(0, 1)); }, [names.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Row | null>(null);
  const run = async () => {
    setBusy(true);
    setRes((await act(() => A.post<Row>("sources/test", { names: picked }))) || null);
    setBusy(false);
  };
  const items = asArray(res?.items ?? res?.rows);
  const errors = res && isObj(res.errors) ? (res.errors as Record<string, unknown>) : {};
  const passed = items.filter((i) => bool(pick(i, "passed", "통과"))).length;
  const log = asArray(res?.log ?? res?.lines).map(toLine);
  return (
    <div>
      <p className="caption">DB에 저장하지 않고 소스를 수집해 봅니다. 키워드 필터 통과 여부도 함께 보여 줍니다.</p>
      <Multi options={names} value={picked} onChange={setPicked} />
      <div className="row2" style={{ marginTop: 10 }}>
        <button className="btn primary" disabled={!picked.length || busy} onClick={run}>🔍 {busy ? "수집 중…" : "미리보기"}</button>
        <StartJob kind="collect" text="선택 소스 실제 수집" kwargs={{ only_sources: picked }} disabled={!picked.length} />
      </div>
      {res && (
        <div style={{ marginTop: 10 }}>
          {Object.entries(errors).map(([n, e]) => <Alert key={n} kind="err">{n}: {str(e)}</Alert>)}
          <Alert kind="ok">{items.length}건 수집 · 키워드 통과 {passed}건</Alert>
          <DataTable rows={items.map((i) => ({ 통과: bool(pick(i, "passed", "통과")), 소스: str(pick(i, "source", "소스")), 제목: str(pick(i, "title", "제목")), 발행: str(pick(i, "published_at", "발행")).slice(0, 16).replace("T", " "), URL: str(pick(i, "url", "URL")) }))} tall />
          {log.length > 0 && <><p className="caption">실행 로그</p><LogView lines={log} /></>}
        </div>
      )}
      <JobStatus />
    </div>
  );
}

export default function Collect() {
  const [sec, setSec] = useRemembered("sec", SECTIONS[0]);
  return (
    <div>
      <AdminHead title="수집 설정" note="소스 목록 자체(URL·그룹)는 config/sources.yaml에서 관리합니다." />
      <Tabs items={SECTIONS} value={sec} onChange={setSec} />
      {sec === "소스 on/off" && <Sources />}
      {sec === "키워드" && <Keywords />}
      {sec === "수집 테스트" && <TestCollect />}
    </div>
  );
}
