// 오늘의 AX (/today) — 매일 바뀌는 3문항 퀴즈 + 내일 키워드 예측 투표 + 연속 참여(스트릭) + 참여 지도.
// 퀴즈·투표에 답하면 POST 응답으로 그 부분만 바꾼다 (참여 지도 iframe 은 다시 그리지 않는다 — st.fragment 와 같은 효과).
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import DocFrame from "../components/DocFrame";
import ProfileForm, { ShareReveal, useShareVisit } from "../components/ProfileForm";
import { Alert, useLoad } from "../components/ui";
import "./Today.css";

type Mine = { choice: string; correct: boolean | number; answer: string; why: string; stats: { n: number; rate: number; choices: Record<string, number> } };
type Quiz = { i: number; q: string; sub: string; options: string[]; url?: string; mine?: Mine | null };
type Poll = { day: string; question: string; options: string[]; mine?: string | null; counts?: Record<string, number>; target_day?: string };
type Yesterday = { question: string; winner: string; actual?: Record<string, number>; crowd?: string; mine?: string | null; band?: boolean } | null;
type TodayData = {
  day: string; term?: { track: string; track_label: string; term: string; define: string; hint: string } | null;
  quiz: Quiz[]; score: number; done: boolean; streak: number; poll?: Poll | null; yesterday?: Yesterday; map_url?: string;
};

/** 다음 문제(한국 시간 자정)까지 남은 시간. */
function leftUntilMidnightKST(): { h: number; m: number } {
  const kst = Date.now() + 9 * 3600 * 1000;
  const left = 86400 * 1000 - (kst % (86400 * 1000));
  return { h: Math.floor(left / 3600000), m: Math.floor((left % 3600000) / 60000) };
}

export default function Today() {
  useShareVisit("today");
  const [params] = useSearchParams();
  const d = params.get("d") || "";
  const { data, error, loading, setData } = useLoad<TodayData>(() => get<TodayData>(`today${d ? `?d=${encodeURIComponent(d)}` : ""}`), [d]);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [left, setLeft] = useState(leftUntilMidnightKST);
  useEffect(() => {
    const t = window.setInterval(() => setLeft(leftUntilMidnightKST()), 30000);
    return () => window.clearInterval(t);
  }, []);

  const quiz = useMemo(() => data?.quiz ?? [], [data]);
  const answered = quiz.filter((q) => q.mine).length;
  const score = quiz.filter((q) => q.mine && Number(q.mine.correct) > 0).length;
  const streak = data?.streak ?? 0;
  const poll = data?.poll ?? null;
  const dayLabel = (data?.day || "").replace(/-/g, ".");

  const answer = async (q: Quiz, choice: string) => {
    if (!data || busy) return;
    setBusy(`q${q.i}`);
    setMsg(null);
    try {
      const mine = await post<Mine>("today/quiz", { day: data.day, i: q.i, choice });
      setData({ ...data, quiz: data.quiz.map((x) => (x.i === q.i ? { ...x, mine } : x)) });
    } catch (e) {
      setMsg((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };
  const vote = async (choice: string) => {
    if (!data || !poll || busy) return;
    setBusy("poll");
    setMsg(null);
    try {
      const r = await post<{ counts: Record<string, number> }>("today/poll", { day: data.day, choice });
      setData({ ...data, poll: { ...poll, mine: choice, counts: r.counts || {} } });
    } catch (e) {
      setMsg((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="today-page">
      <div className="eyebrow">오늘의 AX{dayLabel && ` · ${dayLabel}`}</div>
      <h2 className="sec-h">오늘의 <span className="grad">AX 퀴즈 · 예측</span></h2>
      <p className="sec-p" style={{ maxWidth: 720 }}>매일 새 문제 3개와 '내일의 키워드' 예측 투표가 올라옵니다. 모든 문제는 AX Review가 실제로 수집한 데이터에서 나옵니다.</p>
      <div className="today-stats">
        <div><b>🔥 {streak}일</b><span>연속 참여</span></div>
        <div><b>⏳ {left.h}시간 {left.m}분</b><span>다음 문제까지</span></div>
      </div>

      {/* 퀴즈 자리를 미리 잡아 둔다 — 내용이 오면서 아래 지도 구역이 밀려 화면이 흔들리지 않게 (CLS 0.35) */}
      {loading && !data && <div className="page-loading" style={{ minHeight: 900 }}>불러오는 중…</div>}
      {error && <Alert kind="err">{error}</Alert>}

      {data?.term && (
        <a className="tod" href="/terms">
          <div>
            <span className="k">📘 오늘의 용어 · {data.term.track_label}</span>
            <b>{data.term.term}</b>
            <p>{data.term.define} — 💡 {data.term.hint}</p>
          </div>
          <em>용어 퀴즈 풀기 →</em>
        </a>
      )}

      {data?.yesterday?.winner && <YesterdayBox r={data.yesterday} />}

      {msg && <Alert kind="warn">{msg}</Alert>}

      {quiz.map((q, idx) => (
        <div className="box quiz-card" key={q.i}>
          <div className="ax-q">Q{idx + 1}. {q.q}</div>
          <div className="quiz-sub">{q.sub}</div>
          {q.mine ? (
            <AnsweredQuiz q={q} mine={q.mine} />
          ) : (
            <div className="opt-row" style={{ gridTemplateColumns: `repeat(${Math.max(1, q.options.length)}, minmax(0,1fr))` }}>
              {q.options.map((o) => (
                <button key={o} className="btn opt" type="button" disabled={busy === `q${q.i}`} onClick={() => answer(q, o)}>{o}</button>
              ))}
            </div>
          )}
        </div>
      ))}

      {quiz.length > 0 && answered === quiz.length && (
        <>
          <div className="quiz-done">
            <b>오늘 {score}/{quiz.length} 정답</b>
            <span>내일 새 문제가 올라옵니다. 연속 참여 🔥{Math.max(streak, 1)}일째!</span>
          </div>
          <ShareReveal content="today" path="/s/q" params={{ d: data?.day || "", score, n: quiz.length }}
            title={`오늘의 AX 퀴즈 ${score}/${quiz.length} — 너도 풀어 봐`}
            text={`오늘의 AX 퀴즈 ${score}/${quiz.length} 정답. 실제 수집 데이터로 매일 새로 나오는 3문제입니다.`} />
        </>
      )}

      {poll && (
        <>
          <div className="eyebrow" style={{ marginTop: 22 }}>내일의 키워드 예측</div>
          <h3 className="sec-h" style={{ fontSize: "1.35rem" }}>🔮 {poll.question}</h3>
          <p className="caption" style={{ margin: "-6px 0 8px" }}>{poll.target_day || "내일"}에 발행된 기사 기준으로 내일 정답을 공개합니다.</p>
          {poll.mine ? (
            <PollResult poll={poll} />
          ) : (
            <div className="opt-row" style={{ gridTemplateColumns: `repeat(${Math.max(1, poll.options.length)}, minmax(0,1fr))` }}>
              {poll.options.map((o) => (
                <button key={o} className="btn opt" type="button" disabled={busy === "poll"} onClick={() => vote(o)}>{o}</button>
              ))}
            </div>
          )}
        </>
      )}

      {(answered > 0 || poll?.mine) && (
        <>
          <ProfileForm source="today" />
          <SubscribeCTA source="today" headline="내일 정답과 새 문제, 놓치지 마세요" sub="매주 월요일, 한 주의 AX 흐름과 퀴즈에 나온 기사 해설을 메일로 보내 드립니다." />
        </>
      )}

      <div className="space" id="map" />
      <div className="eyebrow">참여 지도</div>
      <h3 className="sec-h" style={{ fontSize: "1.35rem" }}>어디서 <span className="grad">참여하고 있을까?</span></h3>
      <p className="caption" style={{ margin: "-6px 0 8px" }}>참여 통계에 보태 주신 분들의 국가·지역·연령대 기준입니다. 나라를 누르면 성별·연령대·유형 분포가 나옵니다.</p>
      <LazyMap />
    </div>
  );
}

/** 참여 지도 — 화면에 가까워지면 /api/map/html 을 따로 불러온다 (오늘의 AX 응답에 싣지 않음, 브라우저 캐시 2분). */
function LazyMap() {
  const ref = useRef<HTMLDivElement>(null);
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const load = () => fetch("/api/map/html", { credentials: "same-origin" }).then((r) => (r.ok ? r.text() : Promise.reject())).then(setHtml).catch(() => setErr(true));
    if (!("IntersectionObserver" in window) || window.location.hash === "#map") { load(); return; }
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { io.disconnect(); load(); } }, { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ minHeight: 560 }}>
      {html ? <><MapFrame html={html} /><JumpToHash /></> : <p className="caption">{err ? "참여 지도를 불러오지 못했습니다." : "참여 지도를 불러오는 중…"}</p>}
    </div>
  );
}

/** 지도 iframe 은 html 문자열이 같으면 다시 그리지 않는다. */
function MapFrame({ html }: { html: string }) {
  return useMemo(() => <DocFrame html={html} title="참여 지도" fallback={560} />, [html]);
}

function AnsweredQuiz({ q, mine }: { q: Quiz; mine: Mine }) {
  const s = mine.stats || { n: 0, rate: 0, choices: {} };
  const n = Math.max(1, s.n || 0);
  const ok = Number(mine.correct) > 0;
  const rate = s.rate !== undefined ? s.rate : 0;
  const internal = (q.url || "").startsWith("/");
  return (
    <>
      {q.options.map((o) => {
        const pct = Math.round(((s.choices?.[o] || 0) / n) * 100);
        return (
          <div key={o} className={`qopt ${o === mine.answer ? "ans" : ""} ${o === mine.choice ? "mine" : ""}`}>
            <span>{o === mine.answer ? "✅" : o === mine.choice ? "❌" : "·"} {o}</span>
            <div className="trk"><div className="fil" style={{ width: `${pct}%` }} /></div>
            <b>{pct}%</b>
          </div>
        );
      })}
      <div className="qmeta">{ok ? "정답!" : "오답"} · 참여자 {s.n || 0}명 중 {Math.round(rate)}%가 맞혔어요 · {mine.why}</div>
      {q.url && (
        <a className="more" href={q.url} target={internal ? "_self" : "_blank"} rel="noopener">{internal ? "관련 노트 보기" : "기사 원문 보기"} ↗</a>
      )}
    </>
  );
}

function PollResult({ poll }: { poll: Poll }) {
  const counts = poll.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + (Number(b) || 0), 0);
  return (
    <>
      {poll.options.map((o) => {
        const pct = Math.round(((counts[o] || 0) / Math.max(1, total)) * 100);
        return (
          <div key={o} className={`qopt ${o === poll.mine ? "mine" : ""}`}>
            <span>{o === poll.mine ? "🗳️" : "·"} {o}</span>
            <div className="trk"><div className="fil" style={{ width: `${pct}%` }} /></div>
            <b>{pct}%</b>
          </div>
        );
      })}
      <div className="qmeta">투표 {total}명 · 내일 이 페이지에서 결과를 확인하세요</div>
    </>
  );
}

function YesterdayBox({ r }: { r: NonNullable<Yesterday> }) {
  const hit = r.mine === r.winner ? "🎯 적중!" : r.mine ? `아쉽게도 '${r.mine}'를 골랐어요` : "어제는 참여하지 않았어요";
  const crowd = r.crowd ? `참여자 다수는 '${r.crowd}'` : "참여자 없음";
  const n = r.actual?.[r.winner];
  const count = r.band || n === undefined ? "" : ` (${n}건)`;
  return (
    <div className="poll-res">
      <span>어제의 예측 · {r.question}</span>
      <b>정답: {r.winner}{count}</b>
      <em>{crowd} · {hit}</em>
    </div>
  );
}

/** 홈 맛보기의 '참여 지도 →'(/today#map) — 페이지를 그린 뒤 그 위치로 옮긴다 (Layout 이 경로가 바뀌면 맨 위로 올리므로). */
function JumpToHash() {
  useEffect(() => {
    if (window.location.hash !== "#map") return;
    const t = setTimeout(() => document.getElementById("map")?.scrollIntoView({ block: "start" }), 300);
    return () => clearTimeout(t);
  }, []);
  return null;
}
