// AI 모델 설정 — 글을 쓰는 AI(채점·노트 초안·주간 흐름·브리핑·질문하기)를 Gemini 또는 Claude 로 고른다 (backend api/routers/admin_llm.py).
// Claude 는 모델 선택 + API 키 입력(서버에만 저장, 화면에는 앞뒤 몇 글자만) + 연결 시험. 임베딩(의미 검색)은 늘 Gemini.
import { useEffect, useRef, useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, useAct } from "./common";

type Model = { id: string; name: string; desc: string };
type State = {
  provider: "gemini" | "claude"; active: "gemini" | "claude"; claude_model: string; models: Model[];
  claude_key: { set: boolean; masked: string; source: "admin" | "env" | "" };
  gemini: { keys: number; model: string }; uses: string[]; gemini_only: string[];
};

export default function Llm() {
  const act = useAct();
  const { data, error, setData } = useLoad(() => A.get<State>("llm"), []);
  const [provider, setProvider] = useState<"gemini" | "claude">("gemini");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [test, setTest] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // 처음 불러올 때만 서버 값으로 채운다 — 예전엔 '키 저장'·'키 지우기' 뒤 화면을 새로 그리면서
  // 위에서 고른 AI·모델(아직 저장 전)을 서버 값(Gemini)으로 덮어써, 고른 내용이 사라졌다 (2026-10-29)
  const inited = useRef(false);
  useEffect(() => {
    if (data && !inited.current) { inited.current = true; setProvider(data.provider); setModel(data.claude_model); }
  }, [data]);
  if (error) return <Alert kind="err">{error}</Alert>;
  if (!data) return <div className="page-loading">불러오는 중…</div>;

  const save = async () => {
    const r = await act(() => A.put<State>("llm", { provider, claude_model: model }), "저장했습니다. 다음 작업·질문부터 바로 적용됩니다.");
    if (r) setData(r);
  };
  const saveKey = async () => {
    const r = await act(() => A.put<State>("llm/key", { key: key.trim() }), "Claude API 키를 저장했습니다.");
    if (r) { setData(r); setKey(""); }
  };
  const removeKey = async () => {
    if (!window.confirm("저장된 Claude API 키를 지울까요? Claude 를 쓰고 있었다면 Gemini 로 돌아갑니다.")) return;
    const r = await act(() => A.del<State>("llm/key"), "Claude API 키를 지웠습니다.");
    if (r) setData(r);
  };
  const runTest = async () => {
    setBusy(true); setTest(null);
    const r = await act(() => A.post<{ model: string; answer: string; tokens: { input: number; output: number } }>("llm/test", {}));
    if (r) setTest(`✅ ${r.model} 응답: "${r.answer}" · 토큰 입력 ${r.tokens.input} / 출력 ${r.tokens.output}`);
    setBusy(false);
  };
  const ks = data.claude_key;
  const dirty = provider !== data.provider || (provider === "claude" && model !== data.claude_model);

  return (
    <div>
      <AdminHead title="AI 모델 설정" note="글을 쓰는 AI를 Gemini 또는 Claude 중에서 고릅니다. 바꾸면 다음 작업·질문부터 바로 적용됩니다." />
      <div className="metrics">
        <Metric k="지금 쓰는 AI" v={data.active === "claude" ? "Claude" : "Gemini"} />
        <Metric k="Claude 모델" v={data.models.find((m) => m.id === data.claude_model)?.name || data.claude_model} />
        <Metric k="Claude 키" v={ks.set ? (ks.source === "env" ? ".env" : "저장됨") : "없음"} />
        <Metric k="Gemini 키" v={`${data.gemini.keys}개`} />
      </div>
      {data.provider === "claude" && data.active !== "claude" && <Alert kind="warn">Claude 를 골랐지만 키가 없어 지금은 Gemini 로 동작합니다.</Alert>}

      <div className="box" style={{ marginTop: 14 }}>
        <h3 style={{ margin: "0 0 10px" }}>1. 사용할 AI</h3>
        <div className="btn-row">
          {(["gemini", "claude"] as const).map((p) => (
            <button key={p} type="button" className={`pill ${provider === p ? "on" : ""}`} onClick={() => setProvider(p)}>
              {p === "gemini" ? `Gemini (${data.gemini.model})` : "Claude"}
            </button>
          ))}
        </div>
        <p className="caption" style={{ marginTop: 8 }}>적용 대상: {data.uses.join(" · ")}. {data.gemini_only.join(", ")}은 Claude 에 같은 기능이 없어 늘 Gemini 를 씁니다.</p>
        {provider === "claude" && (
          <div style={{ marginTop: 12 }}>
            <label className="caption">Claude 모델</label>
            <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
              {data.models.map((m) => (
                <label key={m.id} className="check" style={{ alignItems: "flex-start" }}>
                  <input type="radio" name="claude-model" checked={model === m.id} onChange={() => setModel(m.id)} />
                  <span><b>{m.name}</b> <code>{m.id}</code><br /><span className="caption">{m.desc}</span></span>
                </label>
              ))}
            </div>
          </div>
        )}
        <button className="btn primary" style={{ marginTop: 12 }} disabled={provider === "claude" && !ks.set} onClick={save}>저장</button>
        {provider === "claude" && !ks.set && <span className="caption" style={{ marginLeft: 10 }}>아래에서 Claude API 키를 먼저 넣어 주세요.</span>}
        {dirty && (provider !== "claude" || ks.set) && <span className="caption" style={{ marginLeft: 10, color: "var(--warn-ink)" }}>● 바꾼 내용이 아직 저장되지 않았습니다 — '저장'을 눌러야 적용됩니다.</span>}
      </div>

      <div className="box" style={{ marginTop: 14 }}>
        <h3 style={{ margin: "0 0 10px" }}>2. Claude API 키</h3>
        {ks.set
          ? <p className="caption">현재 키: <code>{ks.masked}</code> ({ks.source === "env" ? ".env 의 ANTHROPIC_API_KEY" : "관리 화면에서 저장"})</p>
          : <p className="caption">저장된 키가 없습니다. console.anthropic.com 에서 만든 키(sk-ant-…)를 넣어 주세요.</p>}
        {/* .field 는 세로 배치라 flex-basis 가 높이로 먹는다 — 가로 줄로 따로 둔다 */}
        <div style={{ display: "flex", flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
          <input className="input" type="password" autoComplete="off" placeholder="sk-ant-..." value={key} onChange={(e) => setKey(e.target.value)}
            style={{ flex: "1 1 280px", minWidth: 0, height: 40 }} />
          <button className="btn" disabled={!key.trim()} onClick={saveKey}>{ks.set ? "키 바꾸기" : "키 저장"}</button>
          {ks.source === "admin" && <button className="btn" onClick={removeKey}>🗑 키 지우기</button>}
        </div>
        <p className="caption">키는 서버(웹으로 열리지 않는 data 폴더)에만 저장되고, 화면·기록에는 앞뒤 몇 글자만 보입니다.</p>
        <button className="btn" disabled={!ks.set || busy} onClick={runTest}>{busy ? "시험 중…" : "🔌 연결 시험 (짧은 요청 1회)"}</button>
        {test && <Alert kind="ok">{test}</Alert>}
      </div>
    </div>
  );
}
