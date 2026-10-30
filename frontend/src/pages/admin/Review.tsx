// 노트 검토 — 검토 대기/게시됨/반려됨/직접 작성. 편집 폼 + 게시·저장·반려·삭제 (app_pages/admin/review.py).
import { useState } from "react";
import { Alert, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, Expander, Field, Multi, Row, asArray, splitCsv, str, useAct, useRemembered } from "./common";
import { useJobs } from "./JobRunner";

export const CATEGORIES = ["AX Strategy", "AX Implementation", "AX Enablement"];
export const KINDS = ["아티클", "포스트", "리포트", "대담"];
export const AUDIENCES = ["CEO", "CFO", "CHRO", "CIO·CTO", "CISO", "AX 추진", "현업 리더"];
const VIEWS = ["검토 대기", "게시됨", "반려됨", "직접 작성"];
const STATUS: Record<string, string> = { "검토 대기": "draft", 게시됨: "published", 반려됨: "rejected" };

type Form = { title: string; category: string; kind: string; source: string; url: string; audiences: string[]; tags: string; summary: string; body: string };
const fromNote = (n: Row): Form => ({
  title: str(n.title), category: CATEGORIES.includes(str(n.category)) ? str(n.category) : CATEGORIES[1],
  kind: KINDS.includes(str(n.kind)) ? str(n.kind) : KINDS[0], source: str(n.source), url: str(n.url),
  audiences: (Array.isArray(n.audiences) ? n.audiences.map(String) : splitCsv(str(n.audiences))).filter((a) => AUDIENCES.includes(a)),
  tags: Array.isArray(n.tags) ? n.tags.join(", ") : str(n.tags), summary: str(n.summary), body: str(n.body),
});
const toPayload = (f: Form) => ({
  title: f.title.trim(), category: f.category, kind: f.kind, source: f.source.trim(), url: f.url.trim(),
  audiences: f.audiences.join(","),
  tags: splitCsv(f.tags).map((t) => t.replace(/^#/, "")).join(","),
  summary: f.summary.trim(), body: f.body.trim() || `### 요약\n${f.summary.trim()}`,
});

/** 노트 편집 폼 — 제출 버튼마다 action 을 넘긴다. */
function NoteForm({ note, onSubmit }: { note: Row | null; onSubmit: (action: "publish" | "save" | "reject", data: ReturnType<typeof toPayload>) => Promise<void> }) {
  const [f, setF] = useState<Form>(fromNote(note || {}));
  const [err, setErr] = useState("");
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  const go = (action: "publish" | "save" | "reject") => {
    if (action !== "reject" && !(f.title.trim() && f.summary.trim())) return setErr("제목과 카드 요약은 필수입니다.");
    setErr("");
    onSubmit(action, toPayload(f));
  };
  return (
    <div>
      <Field label="제목"><input type="text" value={f.title} onChange={set("title")} /></Field>
      <div className="row3">
        <Field label="카테고리"><select value={f.category} onChange={set("category")}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="유형"><select value={f.kind} onChange={set("kind")}>{KINDS.map((c) => <option key={c}>{c}</option>)}</select></Field>
        <Field label="출처"><input type="text" value={f.source} onChange={set("source")} /></Field>
      </div>
      <Field label="원문 URL"><input type="text" value={f.url} onChange={set("url")} /></Field>
      <div className="row2">
        <Field label="대상 독자"><Multi options={AUDIENCES} value={f.audiences} onChange={(v) => setF({ ...f, audiences: v })} /></Field>
        <Field label="태그 (쉼표 구분)"><input type="text" value={f.tags} onChange={set("tags")} /></Field>
      </div>
      <Field label="카드 요약"><textarea rows={4} value={f.summary} onChange={set("summary")} /></Field>
      <Field label="본문 (Markdown)"><textarea rows={14} value={f.body} onChange={set("body")} /></Field>
      {err && <Alert kind="err">{err}</Alert>}
      <div className="row3">
        <button className="btn primary" onClick={() => go("publish")}>📤 게시</button>
        <button className="btn" onClick={() => go("save")}>💾 저장</button>
        {note?.id !== undefined && (
          <button className="btn" onClick={() => go("reject")}>⛔ {note.status === "draft" ? "반려" : "게시 내리기"}</button>
        )}
      </div>
    </div>
  );
}

export default function Review() {
  const [view, setView] = useRemembered("view", VIEWS[0]);
  const { finished } = useJobs();
  const status = STATUS[view];
  const { data, error, reload } = useLoad(async () => (status ? asArray(await A.get(`notes?status=${status}`), "notes", "items") : []), [status, finished]);
  const act = useAct();
  const items = data || [];

  const apply = async (id: unknown, action: "publish" | "save" | "reject", payload: ReturnType<typeof toPayload>) => {
    const msg = { publish: "게시했습니다.", save: "저장했습니다.", reject: "반려했습니다." }[action];
    await act(async () => {
      if (id === undefined || id === null) {
        await A.post("notes", { ...payload, status: action === "publish" ? "published" : "draft" }); // 직접 작성 (계약 밖 — 가정)
        return;
      }
      await A.put(`notes/${id}`, action === "reject" ? { ...payload, status: "rejected" } : payload);
      if (action === "publish") await A.post(`notes/${id}/publish`);
    }, msg);
    reload();
  };
  const remove = async (n: Row) => {
    if (!window.confirm(`'${str(n.title)}' 노트를 삭제할까요?`)) return;
    await act(() => A.del(`notes/${n.id}`), "삭제했습니다.");
    reload();
  };

  return (
    <div>
      <AdminHead title="노트 검토" note="AI가 쓴 초안을 고치고 게시합니다. 게시한 노트만 사이트에 보입니다." />
      <Tabs items={VIEWS} value={view} onChange={setView} />
      {error && <Alert kind="err">{error}</Alert>}
      {view === "직접 작성" ? (
        <NoteForm key="new" note={null} onSubmit={(a, p) => apply(null, a, p)} />
      ) : (
        <div>
          <p className="caption">{items.length}편</p>
          {!items.length && !error && (
            <Alert kind="info">해당하는 노트가 없습니다.{status === "draft" && " 대시보드에서 '노트 초안 생성'을 실행해 보세요."}</Alert>
          )}
          {items.map((n) => (
            <Expander
              key={str(n.id)}
              title={<span><b>{str(n.title)}</b><br /><span className="caption">{str(n.category)} · {str(n.source)} · {str(n.published)}</span></span>}
            >
              <div className="btn-row" style={{ marginBottom: 12 }}>
                <a className="btn sm" href={`/notes?id=${str(n.id)}`} target="_blank" rel="noreferrer">👁 사이트 미리보기</a>
                {str(n.url) && <a className="btn sm" href={str(n.url)} target="_blank" rel="noreferrer">↗ 원문</a>}
                <button className="btn sm" onClick={() => remove(n)}>🗑 삭제</button>
              </div>
              <NoteForm note={n} onSubmit={(a, p) => apply(n.id, a, p)} />
            </Expander>
          ))}
        </div>
      )}
    </div>
  );
}
