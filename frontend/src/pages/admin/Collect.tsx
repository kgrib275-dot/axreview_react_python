// 수집 설정 — 소스 on/off(그룹별), 키워드 규칙 편집, 수집 테스트(미리보기·선택 소스 실제 수집) (app_pages/admin/collect_settings.py).
import { useEffect, useRef, useState } from "react";
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
        {/* 전체 켜기·끄기 — 화면 값만 바꾼다. 저장 버튼을 눌러야 반영 (실수로 모든 소스가 꺼지지 않게) */}
        <button className="btn sm ghost" disabled={!sources.length || on.size === sources.length} onClick={() => setOn(new Set(sources.map((s) => str(s.name))))}>전체 켜기</button>
        <button className="btn sm ghost" disabled={!on.size} onClick={() => setOn(new Set())}>전체 끄기</button>
        <button className="btn primary" onClick={async () => { await act(() => A.put("sources", { enabled: Array.from(on) }), "소스 설정을 저장했습니다."); reload(); }}>💾 저장</button>
      </div>
    </div>
  );
}

// needs_ai: 업종·직무처럼 넓은 단어는 AI 관련 단어와 같은 글에 함께 나올 때만 통과 (백엔드 필터 규칙, 없으면 false)
type Kw = { keyword: string; aliases: string; mode: string; weight: number; active: boolean; category: string; needs_ai: boolean };
function Keywords() {
  const { data, error, reload } = useLoad(() => A.get<unknown>("keywords"), []);
  const act = useAct();
  const [rows, setRows] = useState<Kw[]>([]);
  useEffect(() => {
    setRows(asArray(data, "keywords", "items", "rules").map((k) => ({
      keyword: str(k.keyword), aliases: Array.isArray(k.aliases) ? k.aliases.join(", ") : str(k.aliases), mode: str(k.mode) || "include",
      weight: num(k.weight, 1), active: k.active === undefined ? true : bool(k.active), category: str(k.category), needs_ai: bool(k.needs_ai),
    })));
  }, [data]);
  const upd = (i: number, p: Partial<Kw>) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...p } : x)));
  const save = async () => {
    const body = rows.filter((r) => r.keyword.trim()).map((r) => ({ keyword: r.keyword.trim(), aliases: r.aliases.split(",").map((a) => a.trim()).filter(Boolean), mode: r.mode, weight: r.weight || 1, active: r.active, category: r.category, needs_ai: r.needs_ai }));
    await act(() => A.put("keywords", { keywords: body }), "키워드를 저장했습니다.");
    reload();
  };
  return (
    <div>
      <p className="caption">include 키워드 중 하나 이상이 제목·발췌에 있어야 후보가 되고, exclude가 걸리면 버립니다. 별칭은 쉼표로 구분합니다.</p>
      <p className="caption">「AI 단어 동반 필요」를 체크하면 업종·직무처럼 넓은 단어는 AI 관련 단어와 같은 글에 함께 나올 때만 통과합니다.</p>
      {error && <Alert kind="err">{error}</Alert>}
      {/* 지금 켜진 규칙 수 — 저장 전 편집 중인 값 기준 */}
      <div className="btn-row" style={{ margin: "4px 0 6px" }}>
        <span className="badge">사용 중 include {rows.filter((r) => r.active && r.mode === "include").length}</span>
        <span className="badge">사용 중 exclude {rows.filter((r) => r.active && r.mode === "exclude").length}</span>
        <span className="badge">AI 단어 동반 필요 {rows.filter((r) => r.active && r.needs_ai).length}</span>
        <span className="caption">전체 {rows.length}행</span>
      </div>
      <div className="table-wrap tall">
        <table className="table">
          <thead><tr><th>사용</th><th>키워드</th><th style={{ width: "32%" }}>별칭</th><th>모드</th><th>가중치</th><th>카테고리</th><th title="체크하면 AI 관련 단어와 같은 글에 함께 나올 때만 통과">AI 단어 동반 필요</th><th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td><input type="checkbox" checked={r.active} onChange={(e) => upd(i, { active: e.target.checked })} /></td>
                <td><input type="text" value={r.keyword} onChange={(e) => upd(i, { keyword: e.target.value })} /></td>
                <td><input type="text" value={r.aliases} onChange={(e) => upd(i, { aliases: e.target.value })} /></td>
                <td><select value={r.mode} onChange={(e) => upd(i, { mode: e.target.value })}><option>include</option><option>exclude</option></select></td>
                <td><input type="number" min={0.1} max={5} step={0.5} value={r.weight} onChange={(e) => upd(i, { weight: Number(e.target.value) })} /></td>
                <td><select value={r.category} onChange={(e) => upd(i, { category: e.target.value })}><option value="">(없음)</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></td>
                <td style={{ textAlign: "center" }}><input type="checkbox" checked={r.needs_ai} onChange={(e) => upd(i, { needs_ai: e.target.checked })} aria-label="AI 단어 동반 필요" /></td>
                <td><button className="btn sm ghost" onClick={() => setRows((x) => x.filter((_, j) => j !== i))}>✕</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="btn-row" style={{ marginTop: 10 }}>
        <button className="btn" onClick={() => setRows((r) => [...r, { keyword: "", aliases: "", mode: "include", weight: 1, active: true, category: "", needs_ai: false }])}>＋ 행 추가</button>
        <button className="btn primary" onClick={save}>💾 키워드 저장</button>
      </div>
    </div>
  );
}

/** 이 화면에 그 키로 기억한 값이 아직 없는지 (useRemembered 와 같은 키 규칙). */
const localStorageMissing = (key: string) => {
  try { return localStorage.getItem(`axreview-adm:${window.location.pathname}:${key}`) === null; } catch { return true; }
};

function TestCollect() {
  const { data } = useLoad(() => A.get<unknown>("sources"), []);
  const act = useAct();
  const srcs = asArray(data, "sources", "items");
  const names = srcs.map((s) => str(s.name));
  const groups = Array.from(new Set(srcs.map((s) => str(s.group))));
  // 고른 소스는 F5 해도 남게 기억 — 처음(기억한 값이 아예 없을 때)만 예전처럼 첫 소스를 골라 둔다
  const [stored, setPicked] = useRemembered<string[]>("test-picked", []);
  const firstVisit = useRef(localStorageMissing("test-picked"));
  useEffect(() => { if (names.length && firstVisit.current && !stored.length) { firstVisit.current = false; setPicked(names.slice(0, 1)); } }, [names.length]); // eslint-disable-line react-hooks/exhaustive-deps
  // sources.yaml 에서 빠진 소스 이름이 기억에 남아 있으면 버린다
  const picked = names.length ? stored.filter((n) => names.includes(n)) : stored;
  const setGroup = (list: string[], v: string[]) => setPicked([...picked.filter((n) => !list.includes(n)), ...v]);
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
      <div className="btn-row" style={{ margin: "4px 0" }}>
        <span className="caption">{picked.length} / {names.length}개 선택</span>
        <button className="btn sm ghost" disabled={!names.length || picked.length === names.length} onClick={() => setPicked(names)}>전체 선택</button>
        <button className="btn sm ghost" disabled={!picked.length} onClick={() => setPicked([])}>전체 해제</button>
      </div>
      {groups.length > 1 ? groups.map((g) => {
        const list = srcs.filter((s) => str(s.group) === g).map((s) => str(s.name));
        const n = list.filter((x) => picked.includes(x)).length;
        return (
          <div key={g} className="pick-grp">
            <div className="btn-row">
              <b>{g || "(그룹 없음)"}</b>
              <span className="caption">{n} / {list.length}</span>
              <button className="btn sm ghost" onClick={() => setGroup(list, n === list.length ? [] : list)}>{n === list.length ? "그룹 해제" : "그룹 전체 선택"}</button>
            </div>
            <Multi options={list} value={picked.filter((x) => list.includes(x))} onChange={(v) => setGroup(list, v)} />
          </div>
        );
      }) : <Multi options={names} value={picked} onChange={setPicked} />}
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
