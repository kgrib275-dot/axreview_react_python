// AI·AX 용어 퀴즈 (/terms) — 트랙별 10문항, 한 문항씩. 연속 정답 콤보, 레벨, 틀린 용어 복습, 용어 사전.
// 진행 상태(term_track, term_i, term_picks, term_qs, term_seen)와 사전 검색어(term_q)는 방문자 상태에 남는다.
// 정답은 서버가 숨기므로 고를 때마다 POST /api/terms/answer 로 확인하고, 그 결과를 문항에 덧붙여 콤보·결과에 쓴다.
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import ProfileForm, { ShareReveal, useShareVisit } from "../components/ProfileForm";
import { Alert, Tabs, useLoad } from "../components/ui";
import { useMe } from "../me";
import "./Terms.css";

const N = 10;
const LEVELS: [number, string, string][] = [[0, "🌱", "AI 새싹"], [40, "🌿", "AI 입문자"], [60, "🌳", "AI 실무자"], [80, "🚀", "AI 고수"], [100, "👑", "AI 마스터"]];
const FORMAT_Q = ["이 설명에 맞는 용어는?", "의 뜻은?", "이 비유가 가리키는 용어는?"];

function levelOf(pct: number): [string, string] {
  let out: [string, string] = [LEVELS[0][1], LEVELS[0][2]];
  for (const [limit, e, n] of LEVELS) if (pct >= limit) out = [e, n];
  return out;
}

type Track = { emoji: string; title: string; desc: string };
type TrackIn = Track | [string, string, string];
type Entry = [string, string, string] | { term: string; define: string; hint: string };
type Question = {
  i: number; format?: number; q?: string; term?: string; prompt: string; options: string[];
  // 답한 뒤 서버 응답을 덧붙인다
  pick?: string; correct?: boolean; answer?: string; explain?: string | { term?: string; define?: string; hint?: string };
};
type TermsData = { tracks: Record<string, TrackIn>; questions: Question[]; dictionary: Record<string, Entry[]>; stats?: Record<string, { count?: number; avg?: number }> };
type AnswerRes = { correct: boolean; answer: string; explain?: Question["explain"] };
type ResultRes = {
  score: number; level?: string | [string, string] | { emoji?: string; name?: string }; wrong?: string[]; review?: Entry[];
  share?: { url?: string; title?: string; text?: string; image?: string }; count?: number; avg?: number; better?: number;
};

const norm = {
  track: (t: TrackIn): Track => (Array.isArray(t) ? { emoji: t[0], title: t[1], desc: t[2] } : t),
  entry: (e: Entry): { term: string; define: string; hint: string } => (Array.isArray(e) ? { term: e[0], define: e[1], hint: e[2] } : e),
  level: (l: ResultRes["level"], pct: number): [string, string] => {
    if (Array.isArray(l)) return [l[0], l[1]];
    if (l && typeof l === "object") return [l.emoji || levelOf(pct)[0], l.name || levelOf(pct)[1]];
    if (typeof l === "string") return [levelOf(pct)[0], l];
    return levelOf(pct);
  },
};

export default function Terms() {
  useShareVisit("terms");
  const { state, setState } = useMe();
  const [params] = useSearchParams();
  const [tab, setTab] = useState("🎯 퀴즈");
  const [msg, setMsg] = useState<string | null>(null);
  // 트랙 목록·사전은 한 번만 받는다 (?track 은 아무 쪽이나)
  const { data, error, loading } = useLoad<TermsData>(() => get<TermsData>("terms?track=ai"), []);
  const tracks = useMemo(() => Object.fromEntries(Object.entries(data?.tracks || {}).map(([k, v]) => [k, norm.track(v)])) as Record<string, Track>, [data]);
  const dictionary = data?.dictionary || {};

  const track = typeof state.term_track === "string" && tracks[state.term_track] ? state.term_track : "";
  const qs = useMemo(() => (Array.isArray(state.term_qs) ? (state.term_qs as Question[]) : []), [state.term_qs]);
  const i = Math.max(0, Number(state.term_i) || 0);
  const picks = useMemo(() => (Array.isArray(state.term_picks) ? (state.term_picks as string[]) : []), [state.term_picks]);

  const start = async (key: string) => {
    setMsg(null);
    try {
      const r = await get<TermsData>(`terms?track=${encodeURIComponent(key)}`);
      // seed: 서버가 정답을 숨긴 채 같은 문제를 다시 만들어 채점하는 열쇠 — 문항마다 같이 저장해 둔다
      const fresh = (r.questions || []).slice(0, N).map((q, k) => ({ ...q, i: q.i ?? k, seed: (r as { seed?: string }).seed }));
      if (!fresh.length) throw new Error("문제를 받지 못했습니다.");
      setState({ term_track: key, term_i: 0, term_picks: [], term_seen: null, term_qs: fresh });
    } catch (e) {
      setMsg((e as ApiError).message);
    }
  };

  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;

  return (
    <div className="terms-page">
      <div className="eyebrow">용어 퀴즈</div>
      <h2 className="sec-h">AI·AX <span className="grad">용어 퀴즈</span></h2>
      <p className="sec-p" style={{ maxWidth: 720 }}>회의에서 나오는 그 용어, 정확히 알고 있나요? 10문제를 풀고 내 레벨을 확인하세요. 틀린 용어는 끝에서 쉬운 비유로 다시 정리해 드립니다.</p>
      {error && <Alert kind="err">{error}</Alert>}
      <Tabs items={["🎯 퀴즈", "📘 용어 사전"]} value={tab} onChange={setTab} />
      {msg && <Alert kind="warn">{msg}</Alert>}

      {tab === "📘 용어 사전" && <Dictionary tracks={tracks} dictionary={dictionary} />}

      {tab === "🎯 퀴즈" && (
        !track || !qs.length ? (
          <TrackPick tracks={tracks} dictionary={dictionary} stats={data?.stats} shared={[params.get("track") || "", params.get("score") || ""]} onStart={start} />
        ) : i < qs.length ? (
          <AskTerm track={track} tracks={tracks} qs={qs} i={i} picks={picks} seen={state.term_seen}
            onSeen={(q, k) => setState({ term_seen: q.pick ?? null, term_qs: qs.map((x, idx) => (idx === k ? q : x)) })}
            onNext={(pick) => setState({ term_picks: [...picks, pick], term_i: i + 1, term_seen: null })}
            onQuit={() => setState({ term_track: null })} />
        ) : (
          <ResultView track={track} tracks={tracks} qs={qs} picks={picks} onRestart={start} />
        )
      )}
    </div>
  );
}

function TrackPick({ tracks, dictionary, stats, shared, onStart }: {
  tracks: Record<string, Track>; dictionary: Record<string, Entry[]>; stats?: TermsData["stats"]; shared: [string, string]; onStart: (k: string) => void;
}) {
  const [sTrack, sScore] = shared;
  const sharedOk = !!tracks[sTrack] && /^[0-9]{1,3}$/.test(sScore) && Number(sScore) <= 100;
  return (
    <>
      {sharedOk && (() => { const [e, lv] = levelOf(Number(sScore)); return <Alert kind="info">🏁 친구의 {tracks[sTrack].title} 점수는 {sScore}점 ({e} {lv})! 이길 수 있을까요?</Alert>; })()}
      <div className="row2 term-tracks">
        {Object.entries(tracks).map(([key, t]) => {
          const st = stats?.[key];
          const avg = st?.count ? `참여 ${st.count}회 · 평균 ${Math.round(st.avg || 0)}점` : "첫 도전자가 되어 보세요";
          return (
            <div className="box" key={key}>
              <div className="term-track">
                <span>{t.emoji}</span><b>{t.title}</b><p>{t.desc}</p>
                <em>{(dictionary[key] || []).length}개 용어 중 {N}문제 · {avg}</em>
              </div>
              <button className={`btn block ${key === sTrack ? "primary" : ""}`} type="button" onClick={() => onStart(key)}>{t.title} 시작 →</button>
            </div>
          );
        })}
      </div>
    </>
  );
}

function questionText(q: Question): string {
  if (q.q) return q.q;
  const f = Number(q.format) || 0;
  return f === 1 ? `'${q.term || ""}'${FORMAT_Q[1]}` : FORMAT_Q[f] || FORMAT_Q[0];
}

function explainOf(q: Question): { term: string; define: string; hint: string } {
  const e = q.explain;
  if (e && typeof e === "object") return { term: e.term || q.term || q.answer || "", define: e.define || "", hint: e.hint || "" };
  return { term: q.term || q.answer || "", define: typeof e === "string" ? e : "", hint: "" };
}

function AskTerm({ track, tracks, qs, i, picks, seen, onSeen, onNext, onQuit }: {
  track: string; tracks: Record<string, Track>; qs: Question[]; i: number; picks: string[]; seen: unknown;
  onSeen: (q: Question, k: number) => void; onNext: (pick: string) => void; onQuit: () => void;
}) {
  const item = qs[i];
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  let combo = 0;
  for (let k = picks.length - 1; k >= 0; k--) {
    if (qs[k]?.correct !== true) break;
    combo++;
  }
  const t = tracks[track];
  const pick = async (opt: string) => {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await post<AnswerRes>("terms/answer", { track, seed: (item as { seed?: string }).seed, i: item.i ?? i, pick: opt });
      onSeen({ ...item, pick: opt, correct: !!r.correct, answer: r.answer, explain: r.explain }, i);
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  const answered = typeof seen === "string" && item.pick === seen;
  const ex = explainOf(item);
  return (
    <>
      <div className="progress">
        <div className="bar"><div className="fil" style={{ width: `${(i / qs.length) * 100}%` }} /></div>
        <span>{t?.emoji} {t?.title} · {i + 1}/{qs.length}{combo >= 2 && ` · 🔥 ${combo}연속 정답`}</span>
      </div>
      <div className="box term-card">
        <div className="ax-q">{questionText(item)}</div>
        <div className="term-prompt">{item.prompt}</div>
        {err && <Alert kind="err">{err}</Alert>}
        {!answered ? (
          <div className="term-opts">
            {item.options.map((opt, k) => <button key={k} className="btn term-opt" type="button" disabled={busy} onClick={() => pick(opt)}>{opt}</button>)}
          </div>
        ) : (
          <>
            <div className={`term-fb ${item.correct ? "ok" : "no"}`}>
              <b>{item.correct ? "⭕ 정답!" : "❌ 아쉬워요"}</b>
              <div><b>{ex.term}</b>{ex.define && <> — {ex.define}</>}</div>
              {ex.hint && <span>💡 {ex.hint}</span>}
            </div>
            <button className="btn primary block" type="button" onClick={() => onNext(item.pick as string)}>{i + 1 < qs.length ? "다음 문제 →" : "결과 보기 →"}</button>
          </>
        )}
      </div>
      <button className="btn sm ghost" type="button" style={{ marginTop: 10 }} onClick={onQuit}>그만하고 트랙 다시 고르기</button>
    </>
  );
}

function ResultView({ track, tracks, qs, picks, onRestart }: { track: string; tracks: Record<string, Track>; qs: Question[]; picks: string[]; onRestart: (k: string) => void }) {
  const [res, setRes] = useState<ResultRes | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const key = track + picks.join("|");
  useEffect(() => {
    let alive = true;
    setRes(null);
    const seed = (qs[0] as { seed?: string } | undefined)?.seed;
    post<ResultRes>("terms/result", { track, seed, picks }).then((r) => alive && setRes(r)).catch((e) => alive && setErr((e as ApiError).message));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const localRight = qs.filter((q) => q.correct === true).length;
  const pct = res?.score ?? Math.round((localRight / Math.max(1, qs.length)) * 100);
  const right = Math.round((pct / 100) * qs.length);
  const [emoji, lv] = norm.level(res?.level, pct);
  const t = tracks[track];
  const other = track === "ai" ? "ax" : "ai";
  const wrongLocal = qs.filter((q) => q.correct === false).map(explainOf);
  const review = res?.review?.length ? res.review.map(norm.entry) : wrongLocal;
  const share = res?.share || {};
  if (err) return <Alert kind="err">{err}</Alert>;
  return (
    <>
      <div className="ax-type">
        <div className="ax-emoji">{emoji}</div>
        <div className="ax-code">{t?.title}</div>
        <h2>{right} / {qs.length} · {lv}</h2>
        {res?.count ? (
          <p className="ax-line">참여자 {res.count}회 중 <b>상위 {Math.max(1, Math.round(100 - (res.better || 0)))}%</b> · 평균 {Math.round(res.avg || 0)}점</p>
        ) : (
          <p className="ax-line">{pct}점</p>
        )}
      </div>
      <ShareReveal content="terms" path={share.url || "/s/terms"} params={share.url ? {} : { track, score: pct }}
        title={share.title || `AI·AX 용어 퀴즈 ${pct}점 (${lv}) — 너는 몇 점?`}
        text={share.text || `AI·AX 용어 퀴즈 ${pct}점(${lv}). 업무에서 바로 쓰는 용어들인데, 몇 점 나오시나요?`} image={share.image} />
      <div className="row2" style={{ marginTop: 10 }}>
        <button className="btn" type="button" onClick={() => onRestart(track)}>↻ 한 번 더 (새 문제)</button>
        {tracks[other] && <button className="btn" type="button" onClick={() => onRestart(other)}>{tracks[other].emoji} {tracks[other].title} 도전</button>}
      </div>
      {review.length > 0 && (
        <>
          <div className="eyebrow" style={{ marginTop: 18 }}>복습</div>
          <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>틀린 용어 <span className="grad">다시 보기</span></h3>
          <div className="gloss">
            {review.map((e, k) => <div key={k}><b>{e.term}</b><p>{e.define}</p><span>💡 {e.hint}</span></div>)}
          </div>
        </>
      )}
      <ProfileForm source="terms" />
      <SubscribeCTA source="terms" headline="이런 용어가 실제로 어떻게 쓰이는지 매주 받아 보세요" sub="용어가 나온 실제 기업 사례 노트를 월요일 아침 3분 요약으로 보내 드립니다." />
    </>
  );
}

function Dictionary({ tracks, dictionary }: { tracks: Record<string, Track>; dictionary: Record<string, Entry[]> }) {
  const { state, setState } = useMe();
  const q = typeof state.term_q === "string" ? state.term_q : "";
  const needle = q.trim().toLowerCase();
  return (
    <>
      <div className="field">
        <label>용어 찾기</label>
        <input type="text" value={q} placeholder="예: RAG, 거버넌스, 토큰" onChange={(e) => setState({ term_q: e.target.value })} />
      </div>
      {Object.entries(tracks).map(([key, t]) => {
        const items = (dictionary[key] || []).map(norm.entry).filter((e) => !needle || `${e.term} ${e.define} ${e.hint}`.toLowerCase().includes(needle));
        if (!items.length) return null;
        return (
          <div key={key}>
            <h3 className="gloss-h">{t.emoji} {t.title} · {items.length}개</h3>
            <div className="gloss">{items.map((e) => <div key={e.term}><b>{e.term}</b><p>{e.define}</p><span>💡 {e.hint}</span></div>)}</div>
          </div>
        );
      })}
    </>
  );
}
