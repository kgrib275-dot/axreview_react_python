// 주간 흐름 — 편집 관점(lens), AI 생성, 직접 작성, 호별 편집(에디터 코멘트·리더 3가지 직접 고르기) (app_pages/admin/issues.py).
import { useEffect, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, AdminHead, Expander, Field, Multi, Row, addDays, asArray, isObj, pick, splitCsv, str, today, useAct, weekBounds, weekLabel } from "./common";
import { JobStatus, useJobs } from "./JobRunner";
import { AUDIENCES } from "./Review";

function LensForm() {
  const { data, error, reload } = useLoad(() => A.get<Row>("lens"), []);
  const act = useAct();
  const [f, setF] = useState({ stance: "", focus: "", industries: "", audience: "" });
  useEffect(() => {
    const lz = data && isObj(data.lens) ? (data.lens as Row) : data || {};
    setF({ stance: str(lz.stance), focus: asArray<string>(lz.focus).join(", ") || str(lz.focus), industries: asArray<string>(lz.industries).join(", ") || str(lz.industries), audience: str(lz.audience) });
  }, [data]);
  const save = async () => {
    await act(() => A.put("lens", { stance: f.stance.trim(), focus: splitCsv(f.focus).slice(0, 20), industries: splitCsv(f.industries).slice(0, 20), audience: f.audience }), "저장했습니다. 홈·메일에 바로 반영됩니다.");
    reload();
  };
  return (
    <Expander title="👁 편집 관점 — '리더가 알아야 할 3가지'를 고르는 기준">
      <p className="caption">
        AI를 쓰지 않고 규칙으로 고릅니다: 관심 주제어 일치 +2, 업종 일치 +1.5, 주 독자 일치 +1 → 점수 높은 순(같으면 최신), 분야가 겹치지 않게 3편.
        관심 주제어는 홈·메일 본문에서 색으로 강조됩니다. 호마다 직접 고를 수도 있습니다(아래 목록).
      </p>
      {error && <Alert kind="err">{error}</Alert>}
      <Field label="관점 한 문장 (3가지 위에 표시)"><input type="text" maxLength={120} value={f.stance} onChange={(e) => setF({ ...f, stance: e.target.value })} /></Field>
      <div className="row2">
        <Field label="관심 주제어 (쉼표)"><input type="text" value={f.focus} onChange={(e) => setF({ ...f, focus: e.target.value })} /></Field>
        <Field label="우리 업종 (쉼표)"><input type="text" value={f.industries} onChange={(e) => setF({ ...f, industries: e.target.value })} /></Field>
      </div>
      <Field label="주 독자">
        <select value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}>
          <option value="">(없음)</option>
          {AUDIENCES.map((a) => <option key={a}>{a}</option>)}
        </select>
      </Field>
      <button className="btn primary" onClick={save}>관점 저장</button>
    </Expander>
  );
}

type IssueFields = { week: string; range: string; headline_em: string; headline: string; body: string; editor_note: string; picks: string[] };

function IssueEditor({ it, pool, auto, onDone }: { it: Row; pool: Row[]; auto: Row[]; onDone: () => void }) {
  const labels = Object.fromEntries(pool.map((n) => [str(n.id), `#${str(n.id)} ${str(n.title).slice(0, 60)}`]));
  const curPicks = (Array.isArray(it.picks) ? it.picks.map(String) : splitCsv(str(it.picks))).filter((p) => p in labels);
  const [f, setF] = useState<IssueFields>({ week: str(it.week), range: str(it.range), headline_em: str(it.headline_em), headline: str(it.headline), body: str(it.body), editor_note: str(it.editor_note), picks: curPicks });
  const act = useAct();
  const set = (k: keyof IssueFields) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const payload = () => ({ ...f, editor_note: f.editor_note.trim(), picks: f.picks.join(",") });
  const save = async (status: "published" | "draft") => {
    await act(() => A.put(`issues/${it.id}`, { ...payload(), status }), status === "published" ? "게시했습니다. '주간 PDF 리포트'에서 PDF를 만들 수 있습니다." : "초안으로 돌렸습니다.");
    onDone();
  };
  const remove = async () => {
    if (!window.confirm(`${f.week} 주간 흐름을 삭제할까요?`)) return;
    await act(() => A.del(`issues/${it.id}`), "삭제했습니다.");
    onDone();
  };
  return (
    <div>
      <div className="row2">
        <Field label="주차"><input type="text" value={f.week} onChange={set("week")} /></Field>
        <Field label="기간"><input type="text" value={f.range} onChange={set("range")} /></Field>
      </div>
      <Field label="강조 문구"><input type="text" value={f.headline_em} onChange={set("headline_em")} /></Field>
      <Field label="헤드라인"><input type="text" value={f.headline} onChange={set("headline")} /></Field>
      <Field label="본문 (**굵게** = 형광펜 강조)"><textarea rows={6} value={f.body} onChange={set("body")} /></Field>
      <Field label="에디터 코멘트 (선택 · 사람이 쓰는 관점 한두 줄, 본문 아래·메일에 표시)">
        <textarea rows={3} maxLength={600} value={f.editor_note} onChange={set("editor_note")} placeholder="예) 이번 주는 **에이전트 비용 관리**가 핵심입니다. 우리 콜센터 PoC에 바로 적용해 볼 만합니다." />
      </Field>
      <Field label="리더 3가지 직접 고르기 (비우면 관점 점수로 자동)">
        <Multi options={Object.keys(labels)} labels={labels} value={f.picks} max={3} onChange={(v) => setF({ ...f, picks: v })} />
      </Field>
      {!f.picks.length && auto.length > 0 && (
        <p className="caption">자동 선정: {auto.map((t) => str(pick(t, "point", "title")).slice(0, 30)).join(" / ")}</p>
      )}
      <div className="row3">
        <button className="btn primary" onClick={() => save("published")}>{it.status === "draft" ? "게시" : "저장"}</button>
        <button className="btn" onClick={() => save("draft")}>초안으로</button>
        <button className="btn" onClick={remove}>삭제</button>
      </div>
    </div>
  );
}

export default function Issues() {
  const { finished, refresh, isActive } = useJobs();
  const act = useAct();
  const { data, error, reload } = useLoad(() => A.get<unknown>("issues"), [finished]);
  const issues = asArray(data, "issues", "items");
  const candidates = isObj(data) && isObj(data.candidates) ? (data.candidates as Record<string, unknown>) : {};
  const autos = isObj(data) && isObj(data.auto) ? (data.auto as Record<string, unknown>) : {};
  const [target, setTarget] = useState(addDays(today(), -7));
  const [mon, sun] = weekBounds(target);
  const [nmon, nsun] = weekBounds(today());
  const [nf, setNf] = useState({ week: weekLabel(nmon), range: `${nmon.replace(/-/g, ".")} – ${nsun.slice(5).replace("-", ".")}`, headline_em: "", headline: "", body: "" });
  const [nerr, setNerr] = useState("");

  const createIssue = async () => {
    if (!(nf.week.trim() && nf.headline.trim())) return setNerr("주차와 헤드라인은 필수입니다.");
    setNerr("");
    await act(() => A.post("issues", { week: nf.week.trim(), range: nf.range.trim(), headline_em: nf.headline_em.trim(), headline: nf.headline.trim(), body: nf.body.trim() }), "게시했습니다.");
    setNf({ ...nf, headline_em: "", headline: "", body: "" });
    reload();
  };

  return (
    <div>
      <AdminHead title="주간 흐름" note="홈의 '이번 주 AX 흐름'은 가장 최근에 게시된 항목이고, 최근 5개가 '흐름의 이동'에 보입니다." />
      <JobStatus />
      <LensForm />
      <div className="box sm">
        <div className="title">AI로 주간 흐름 쓰기</div>
        <div className="inline">
          <div className="field narrow">
            <label>대상 주 (그 주의 아무 날짜)</label>
            <input type="date" value={target} onChange={(e) => e.target.value && setTarget(e.target.value)} />
          </div>
          <span className="caption">{weekLabel(mon)} · {mon} ~ {sun}</span>
          <button className="btn primary" disabled={isActive("weekly")} onClick={async () => {
            // 계약: POST issues/generate {target_day} 가 weekly 작업을 시작한다. 그 뒤 작업 상태를 바로 갱신한다.
            const r = await act(() => A.post("issues/generate", { target_day: target, auto_publish: false }), "주간 흐름 초안 생성을 시작했습니다.");
            if (r !== undefined) refresh();
          }}>✨ 초안 생성</button>
        </div>
      </div>
      <Expander title="직접 작성">
        <div className="row2">
          <Field label="주차"><input type="text" value={nf.week} onChange={(e) => setNf({ ...nf, week: e.target.value })} /></Field>
          <Field label="기간"><input type="text" value={nf.range} onChange={(e) => setNf({ ...nf, range: e.target.value })} /></Field>
        </div>
        <Field label="강조 문구"><input type="text" value={nf.headline_em} onChange={(e) => setNf({ ...nf, headline_em: e.target.value })} /></Field>
        <Field label="헤드라인"><input type="text" value={nf.headline} onChange={(e) => setNf({ ...nf, headline: e.target.value })} /></Field>
        <Field label="본문 (**굵게** 지원)"><textarea rows={6} value={nf.body} onChange={(e) => setNf({ ...nf, body: e.target.value })} /></Field>
        {nerr && <Alert kind="err">{nerr}</Alert>}
        <button className="btn primary" onClick={createIssue}>게시</button>
      </Expander>

      <h3 style={{ margin: "18px 0 8px" }}>목록</h3>
      {error && <Alert kind="err">{error}</Alert>}
      {!issues.length && !error && <p className="caption">아직 주간 흐름이 없습니다.</p>}
      {issues.map((it) => {
        const id = str(it.id);
        const pool = asArray(pick(it, "pool", "candidates", "notes") ?? candidates[id]);
        const auto = asArray(pick(it, "auto", "leader3", "auto_leader3") ?? autos[id]);
        return (
          <Expander key={id} title={`[${it.status === "draft" ? "초안" : "게시"}] ${str(it.week)} · ${str(it.headline_em)} ${str(it.headline)}`}>
            <IssueEditor it={it} pool={pool} auto={auto} onDone={reload} />
          </Expander>
        );
      })}
    </div>
  );
}
