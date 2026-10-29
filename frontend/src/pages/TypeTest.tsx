// AX 리더 유형 테스트 (/type) — 12문항, 한 번에 한 문항. 결과는 ?t=코드 링크로 공유된다.
// 진행 상태(axt_step, axt_answers)는 방문자 상태에 남아 다음 방문에도 이어진다.
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import ProfileForm, { ShareReveal, useShareVisit } from "../components/ProfileForm";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import "./TypeTest.css";

type Axis = [string, string, string, string, string]; // (왼쪽 글자, 오른쪽 글자, 축 이름, 왼쪽 라벨, 오른쪽 라벨)
type TypeInfo = { emoji: string; name: string; line: string; buddy: string; category: string };
type Choice = string | [string, string] | { text?: string; label?: string; code: string };
type TypeData = { axes: Axis[]; questions: { q: string; a: Choice; b: Choice }[]; types: Record<string, TypeInfo>; strength: Record<string, string>; watch: Record<string, string> };
type Result = {
  code: string; axes: [string, string, number, number][]; share_pct?: number | null; strengths?: string | string[]; watch?: string;
  buddy?: string | { code?: string; emoji?: string; name?: string }; recommended_notes?: NoteCardData[];
  share?: { url: string; title?: string; text?: string; image?: string };
};

/** 축 — 서버는 {l, r, label, l_text, r_text} 로 보낸다. 화면은 [왼쪽 글자, 오른쪽 글자, 이름, 왼쪽 라벨, 오른쪽 라벨] 로 쓴다. */
type AxisIn = Axis | { l: string; r: string; label?: string; l_text?: string; r_text?: string };
function normAxis(a: AxisIn): Axis {
  return Array.isArray(a) ? a : [a.l, a.r, a.label ?? "", a.l_text ?? a.l, a.r_text ?? a.r];
}

/** 보기 한쪽 — 서버가 [글, 글자]·{text, code}·문자열 중 어느 모양으로 보내도 받는다. */
function choice(c: Choice, fallbackCode: string): { text: string; code: string } {
  if (Array.isArray(c)) return { text: String(c[0]), code: String(c[1] ?? fallbackCode) };
  if (c && typeof c === "object") return { text: String(c.text ?? c.label ?? ""), code: String(c.code ?? fallbackCode) };
  return { text: String(c), code: fallbackCode };
}

export default function TypeTest() {
  useShareVisit("type_test");
  const { state, setState } = useMe();
  const [params, setParams] = useSearchParams();
  const { data, error, loading } = useLoad<TypeData>(
    () => get<TypeData & { axes: AxisIn[] }>("type").then((d) => ({ ...d, axes: (d.axes || []).map(normAxis) })), []);
  const step = Math.max(0, Number(state.axt_step) || 0);
  const answers = useMemo(() => (Array.isArray(state.axt_answers) ? (state.axt_answers as string[]) : []), [state.axt_answers]);
  const total = data?.questions?.length ?? 12;
  const shared = params.get("t") || "";

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;
  if (error || !data) return <Alert kind="err">{error || "유형 테스트를 불러오지 못했습니다."}</Alert>;

  const header = (
    <>
      <div className="eyebrow">AX Leader Type</div>
      <h2 className="sec-h">나는 어떤 <span className="grad">AX 리더</span>일까?</h2>
      <p className="sec-p" style={{ maxWidth: 720 }}>12문항, 1분이면 끝. MBTI처럼 4가지 축으로 16가지 AX 리더 유형 중 내 유형을 알려 드립니다. 결과를 동료에게 공유하고 찰떡 동료 유형도 확인해 보세요.</p>
    </>
  );

  // ---------- 공유 링크로 들어온 경우: 친구 결과 먼저 ----------
  if (shared && data.types[shared] && step === 0 && answers.length === 0) {
    return (
      <div className="type-page">
        {header}
        <Alert kind="info">👥 친구가 공유한 결과예요. 나는 어떤 유형인지 바로 해 보세요!</Alert>
        <TypeCard code={shared} data={data} axes={null} sharePct={null} />
        <button className="btn primary block" onClick={() => { params.delete("t"); setParams(params, { replace: true }); }}>나도 테스트하기 →</button>
      </div>
    );
  }

  // ---------- 문항 ----------
  if (step < total) {
    const item = data.questions[step];
    const axis = data.axes[step % data.axes.length];
    const a = choice(item.a, axis?.[0] ?? "");
    const b = choice(item.b, axis?.[1] ?? "");
    const pick = (code: string) => setState({ axt_answers: [...answers.slice(0, step), code], axt_step: step + 1 });
    return (
      <div className="type-page">
        {header}
        <div className="progress"><div className="bar"><div className="fil" style={{ width: `${(step / total) * 100}%` }} /></div><span>{step + 1} / {total}</span></div>
        <div className="box axt-q">
          <div className="ax-q">Q{step + 1}. {item.q}</div>
          <div className="row2">
            <button className="btn axt-opt" type="button" onClick={() => pick(a.code)}>{a.text}</button>
            <button className="btn axt-opt" type="button" onClick={() => pick(b.code)}>{b.text}</button>
          </div>
        </div>
        {step > 0 && <button className="btn sm ghost" type="button" style={{ marginTop: 10 }} onClick={() => setState({ axt_answers: answers.slice(0, step - 1), axt_step: step - 1 })}>← 이전 문항</button>}
      </div>
    );
  }

  return (
    <div className="type-page">
      {header}
      <ResultView data={data} answers={answers.slice(0, total)} onRetry={() => setState({ axt_step: 0, axt_answers: [] })} />
    </div>
  );
}

function ResultView({ data, answers, onRetry }: { data: TypeData; answers: string[]; onRetry: () => void }) {
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const key = answers.join("");
  useEffect(() => {
    let alive = true;
    setRes(null);
    setErr(null);
    post<Result>("type/result", { answers }).then((r) => alive && setRes(r)).catch((e) => alive && setErr((e as ApiError).message));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (err) return <><Alert kind="err">{err}</Alert><button className="btn" onClick={onRetry}>↻ 다시 하기</button></>;
  if (!res) return <div className="page-loading">결과를 만드는 중…</div>;
  const t = data.types[res.code] || { emoji: "✨", name: res.code, line: "", buddy: "", category: "" };
  const share = res.share || { url: `/s/t/${res.code}` };
  return (
    <>
      <TypeCard code={res.code} data={data} axes={res.axes} sharePct={res.share_pct ?? null} strengths={res.strengths} watch={res.watch} buddy={res.buddy} />
      <ShareReveal content="type_test" path={share.url} title={share.title || `나는 ${t.name} (${res.code}) — AX 리더 유형 테스트`}
        text={share.text || `AX 리더 유형 테스트를 해 봤더니 저는 ${t.emoji} '${t.name}'(${res.code})이었습니다. ${t.line}. 12문항이면 됩니다 — 여러분은 어떤 유형인가요?`}
        image={share.image || `/app/static/og/type-${res.code}.png`} />
      <button className="btn" style={{ marginTop: 10 }} onClick={onRetry}>↻ 다시 하기</button>
      <ProfileForm source="type_test" />
      <SubscribeCTA source="type_test" headline={`${t.name}에게 맞는 AX 노트를 매주 받아 보세요`} sub="내 유형이 놓치기 쉬운 주제까지, 월요일 아침 3분 요약으로 보내 드립니다." />
      {!!res.recommended_notes?.length && (
        <>
          <div className="eyebrow" style={{ marginTop: 20 }}>For {res.code}</div>
          <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>이 유형에게 <span className="grad">추천하는 노트</span></h3>
          <div className="grid">{res.recommended_notes.map((n) => <NoteCard key={n.id} n={n} />)}</div>
        </>
      )}
    </>
  );
}

/** 결과 카드 — 이모지·이름·한 줄·축 막대·강점/조심할 점/찰떡 동료. axes 가 없으면(공유 결과) 글자 쪽 75% 로 그린다. */
function TypeCard({ code, data, axes, sharePct, strengths, watch, buddy }: {
  code: string; data: TypeData; axes: [string, string, number, number][] | null; sharePct: number | null;
  strengths?: string | string[]; watch?: string; buddy?: Result["buddy"];
}) {
  const t = data.types[code] || { emoji: "✨", name: code, line: "", buddy: "", category: "" };
  const strengthText = Array.isArray(strengths) ? strengths.join(" · ") : strengths || code.split("").map((c) => data.strength?.[c] || "").filter(Boolean).join(" · ");
  const watchText = watch || (code[0] === "S" ? data.watch?.[code[0]] : data.watch?.[code[1]]) || "";
  const buddyCode = typeof buddy === "string" ? buddy : buddy?.code || t.buddy;
  const bt = data.types[buddyCode] || (typeof buddy === "object" && buddy ? { emoji: buddy.emoji || "", name: buddy.name || "" } : { emoji: "", name: buddyCode });
  return (
    <div className="ax-type">
      <div className="ax-emoji">{t.emoji}</div>
      <div className="ax-code">{code}</div>
      <h2>{t.name}</h2>
      <p className="ax-line">{t.line}</p>
      {sharePct !== null && sharePct !== undefined && <div className="ax-rare">전체 참여자 중 <b>{Math.round(sharePct)}%</b>가 이 유형</div>}
      <div className="ax-axes">
        {data.axes.map((ax, i) => {
          const [l, r, , ll, rl] = ax;
          let pct: number;
          if (axes && axes[i]) {
            const lc = Number(axes[i][2]) || 0, rc = Number(axes[i][3]) || 0;
            pct = Math.round((lc / Math.max(1, lc + rc)) * 100);
          } else pct = code[i] === l ? 75 : 25;
          return (
            <div className="ax-axis" key={l + r}>
              <span className={code[i] === l ? "on" : ""}>{ll}</span>
              <div className="trk"><div className="fil" style={{ width: `${pct}%` }} /></div>
              <span className={code[i] === r ? "on" : ""}>{rl}</span>
            </div>
          );
        })}
      </div>
      <div className="ax-grid">
        <div><span>강점</span><b>{strengthText}</b></div>
        <div><span>조심할 점</span><b>{watchText}</b></div>
        <div><span>찰떡 동료</span><b>{bt.emoji} {bt.name} ({buddyCode})</b></div>
      </div>
    </div>
  );
}
