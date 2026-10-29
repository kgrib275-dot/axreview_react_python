// AI 활용 습관 진단 (/habit) — 10문항 × 4단계, 한 번에 한 문항. 5개 영역 점수·단계·다음에 해 볼 3가지 (backend app/ax_tests.py).
import { useEffect, useMemo, useState } from "react";
import { ApiError, get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import ProfileForm, { ShareReveal, useShareVisit } from "../components/ProfileForm";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import "./MoreTests.css";

type HabitData = { scale: string[]; dims: { key: string; name: string; desc: string }[]; questions: { dim: string; q: string }[] };
type HabitResult = {
  score: number; level: number; emoji: string; name: string; line: string; next: string[];
  dims: { key: string; name: string; score: number }[]; strong_name: string; weak_name: string;
  top_pct: number | null; participants: number; recommended_notes: NoteCardData[];
  share: { url: string; title: string; text: string };
};

export default function Habit() {
  useShareVisit("habit");
  const { data, error, loading } = useLoad(() => get<HabitData>("habit"), []);
  // 답은 방문자 상태(hab_answers)에 저장 — 다른 페이지에 다녀와도 이어서 풀고, 다 풀었으면 결과를 다시 보여 준다
  const { state, setState } = useMe();
  const answers = useMemo(() => (Array.isArray(state.hab_answers) ? (state.hab_answers as number[]) : []), [state.hab_answers]);
  const [res, setRes] = useState<HabitResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const total0 = data?.questions.length ?? 0;
  const key = answers.join(",");
  useEffect(() => {
    if (!total0 || answers.length !== total0) { setRes(null); return; }
    let alive = true;
    setErr(null);
    post<HabitResult>("habit/result", { answers }).then((r) => alive && setRes(r)).catch((e) => alive && setErr((e as ApiError).message));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, total0]);

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;
  if (error || !data) return <Alert kind="err">{error || "진단을 불러오지 못했습니다."}</Alert>;
  const total = data.questions.length;
  const step = answers.length;
  const dimName = (k: string) => data.dims.find((d) => d.key === k)?.name || "";

  const pick = (v: number) => setState({ hab_answers: [...answers.slice(0, total), v].slice(0, total) });
  const retry = () => { setState({ hab_answers: [] }); setRes(null); setErr(null); };

  return (
    <div className="mt-page">
      <div className="eyebrow">AI Habit Check</div>
      <h2 className="sec-h">나는 AI를 <span className="grad">얼마나 잘 쓰고</span> 있을까?</h2>
      <p className="sec-p" style={{ maxWidth: 720 }}>10문항, 1분이면 끝. 사용 빈도·질문력·검증·자동화·공유 5개 영역으로 내 AI 활용 습관을 점검하고, 내 답에 맞춰 다음에 해 볼 3가지를 알려 드립니다.</p>

      {step < total && (
        <>
          <div className="progress"><div className="bar"><div className="fil" style={{ width: `${(step / total) * 100}%` }} /></div><span>{step + 1} / {total}</span></div>
          <div className="box mt-q">
            <div className="mt-dim">{dimName(data.questions[step].dim)}</div>
            <div className="ax-q">Q{step + 1}. {data.questions[step].q}</div>
            <div className="mt-scale">
              {data.scale.map((label, v) => <button key={label} type="button" className="btn mt-opt" onClick={() => pick(v)}>{label}</button>)}
            </div>
          </div>
          {step > 0 && <button className="btn sm ghost" type="button" style={{ marginTop: 10 }} onClick={() => setState({ hab_answers: answers.slice(0, -1) })}>← 이전 문항</button>}
        </>
      )}

      {step === total && err && <><Alert kind="err">{err}</Alert><button className="btn" onClick={retry}>↻ 다시 하기</button></>}
      {step === total && !err && !res && <div className="page-loading">결과를 만드는 중…</div>}
      {res && (
        <>
          <div className="mt-card">
            <div className="mt-emoji">{res.emoji}</div>
            <div className="mt-kicker">AI 활용 단계</div>
            <h2>{res.name} <span className="mt-score">{res.score}점</span></h2>
            <p className="mt-line">{res.line}</p>
            {res.top_pct !== null && res.participants >= 5 && <div className="mt-rare">참여자 {res.participants.toLocaleString("ko-KR")}명 중 <b>상위 {res.top_pct}%</b></div>}
            <div className="mt-bars">
              {res.dims.map((d) => (
                <div className="mt-bar" key={d.key}>
                  <span className={d.name === res.strong_name ? "on" : d.name === res.weak_name ? "weak" : ""}>{d.name}</span>
                  <div className="trk"><div className="fil" style={{ width: `${d.score}%` }} /></div>
                  <b>{d.score}</b>
                </div>
              ))}
            </div>
            <div className="mt-grid">
              <div><span>강점</span><b>{res.strong_name}</b></div>
              <div><span>먼저 키울 영역</span><b>{res.weak_name}</b></div>
            </div>
          </div>
          <div className="box mt-next">
            <h3>내 답에 맞춘 <span className="grad">다음에 해 볼 3가지</span></h3>
            <ol>{res.next.map((t) => <li key={t}>{t}</li>)}</ol>
          </div>
          <ShareReveal content="habit" path={res.share.url} title={res.share.title} text={res.share.text} image="/app/static/og.png" />
          <button className="btn" style={{ marginTop: 10 }} onClick={retry}>↻ 다시 하기</button>
          <ProfileForm source="habit" />
          <SubscribeCTA source="habit" headline="AI 활용 사례를 매주 3분으로 받아 보세요" sub="다른 회사가 AI를 실제로 어떻게 쓰는지, 월요일 아침 메일로 보내 드립니다." />
          {res.recommended_notes.length > 0 && (
            <>
              <div className="eyebrow" style={{ marginTop: 20 }}>Next read</div>
              <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>이 단계에 <span className="grad">추천하는 노트</span></h3>
              <div className="grid">{res.recommended_notes.map((n) => <NoteCard key={n.id} n={n} />)}</div>
            </>
          )}
        </>
      )}
    </div>
  );
}
