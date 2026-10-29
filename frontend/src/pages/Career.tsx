// AX 커리어 유형 (/career) — 10문항 × 보기 4개, 한 번에 한 문항. 6가지 유형 중 1·2순위와 직무·역량·학습 경로 (backend app/ax_tests.py).
// 공유 링크(?c=유형)로 들어오면 친구 결과를 먼저 보여 준다.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import ProfileForm, { ShareReveal, useShareVisit } from "../components/ProfileForm";
import { Alert, useLoad } from "../components/ui";
import "./MoreTests.css";

type Brief = { code: string; emoji: string; name: string; line: string };
type CareerData = { questions: { q: string; options: string[] }[]; types: Brief[] };
type CareerCard = Brief & {
  roles: string[]; skills: string[]; path: string[]; second: Brief; partner: Brief;
  scores?: (Brief & { pct: number })[]; share_pct: number | null; recommended_notes: NoteCardData[];
  share: { url: string; title: string; text: string };
};

export default function Career() {
  useShareVisit("career");
  const [params, setParams] = useSearchParams();
  const shared = (params.get("c") || "").toUpperCase();
  const { data, error, loading } = useLoad(() => get<CareerData>("career"), []);
  const friend = useLoad(() => (shared ? get<CareerCard>(`career/${shared}`) : Promise.resolve(null)), [shared]);
  const [picks, setPicks] = useState<number[]>([]);
  const [res, setRes] = useState<CareerCard | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;
  if (error || !data) return <Alert kind="err">{error || "테스트를 불러오지 못했습니다."}</Alert>;
  const total = data.questions.length;
  const step = picks.length;

  const pick = (i: number) => {
    const next = [...picks, i];
    setPicks(next);
    if (next.length === total) {
      post<CareerCard>("career/result", { picks: next }).then(setRes).catch((e) => setErr((e as ApiError).message));
    }
  };
  const retry = () => { setPicks([]); setRes(null); setErr(null); };

  const header = (
    <>
      <div className="eyebrow">AX Career Type</div>
      <h2 className="sec-h">AI 시대, <span className="grad">나에게 맞는 일</span>은?</h2>
      <p className="sec-p" style={{ maxWidth: 720 }}>10문항, 1분이면 끝. 전략가·빌더·데이터 탐험가·현장 운영가·변화 촉진자·거버넌스 수호자 6가지 AX 커리어 유형 중 내 유형과 어울리는 직무, 키울 역량, 학습 경로를 알려 드립니다.</p>
    </>
  );

  if (shared && friend.data && step === 0 && !res) {
    return (
      <div className="mt-page">
        {header}
        <Alert kind="info">👥 친구가 공유한 결과예요. 나는 어떤 유형인지 바로 해 보세요!</Alert>
        <Card c={friend.data} />
        <button className="btn primary block" onClick={() => { params.delete("c"); setParams(params, { replace: true }); }}>나도 테스트하기 →</button>
      </div>
    );
  }

  return (
    <div className="mt-page">
      {header}
      {step < total && (
        <>
          <div className="progress"><div className="bar"><div className="fil" style={{ width: `${(step / total) * 100}%` }} /></div><span>{step + 1} / {total}</span></div>
          <div className="box mt-q">
            <div className="ax-q">Q{step + 1}. {data.questions[step].q}</div>
            <div className="mt-choices">
              {data.questions[step].options.map((o, i) => <button key={o} type="button" className="btn mt-opt" onClick={() => pick(i)}>{o}</button>)}
            </div>
          </div>
          {step > 0 && <button className="btn sm ghost" type="button" style={{ marginTop: 10 }} onClick={() => setPicks(picks.slice(0, -1))}>← 이전 문항</button>}
        </>
      )}
      {step === total && err && <><Alert kind="err">{err}</Alert><button className="btn" onClick={retry}>↻ 다시 하기</button></>}
      {step === total && !err && !res && <div className="page-loading">결과를 만드는 중…</div>}
      {res && (
        <>
          <Card c={res} />
          <ShareReveal content="career" path={res.share.url} title={res.share.title} text={res.share.text} image="/app/static/og.png" />
          <button className="btn" style={{ marginTop: 10 }} onClick={retry}>↻ 다시 하기</button>
          <ProfileForm source="career" />
          <SubscribeCTA source="career" headline={`${res.name}에게 맞는 AX 노트를 매주 받아 보세요`} sub="내 커리어 방향에 맞는 사례를 월요일 아침 3분 요약으로 보내 드립니다." />
          {res.recommended_notes.length > 0 && (
            <>
              <div className="eyebrow" style={{ marginTop: 20 }}>For {res.name}</div>
              <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>이 유형에게 <span className="grad">추천하는 노트</span></h3>
              <div className="grid">{res.recommended_notes.map((n) => <NoteCard key={n.id} n={n} />)}</div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function Card({ c }: { c: CareerCard }) {
  return (
    <>
      <div className="mt-card">
        <div className="mt-emoji">{c.emoji}</div>
        <div className="mt-kicker">AX 커리어 유형</div>
        <h2>{c.name}</h2>
        <p className="mt-line">{c.line}</p>
        {c.share_pct !== null && <div className="mt-rare">전체 참여자 중 <b>{c.share_pct}%</b>가 이 유형</div>}
        {c.scores && (
          <div className="mt-bars">
            {c.scores.map((s) => (
              <div className="mt-bar" key={s.code}>
                <span className={s.code === c.code ? "on" : ""}>{s.emoji} {s.name}</span>
                <div className="trk"><div className="fil" style={{ width: `${s.pct}%` }} /></div>
                <b>{s.pct}</b>
              </div>
            ))}
          </div>
        )}
        <div className="mt-grid">
          <div><span>어울리는 직무</span><b>{c.roles.join(" · ")}</b></div>
          <div><span>키울 역량</span><b>{c.skills.join(" · ")}</b></div>
          {c.scores && <div><span>2순위 유형</span><b>{c.second.emoji} {c.second.name}</b></div>}
          {(!c.scores || c.partner.code !== c.second.code) && <div><span>함께하면 좋은 동료</span><b>{c.partner.emoji} {c.partner.name}</b></div>}
        </div>
      </div>
      <div className="box mt-next">
        <h3>{c.name}의 <span className="grad">학습 경로 3단계</span></h3>
        <ol>{c.path.map((t) => <li key={t}>{t}</li>)}</ol>
      </div>
    </>
  );
}
