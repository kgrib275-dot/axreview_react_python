// 홈 '1분 안에 해 보기' — 각 페이지 인터랙션의 맛보기 (backend api/routers/try_it.py).
// 화면에 보일 때 불러온다(첫 화면 속도 그대로). 원래 페이지의 인터랙션은 그대로 두고, 여기서는 입구만 만든다.
// 퀴즈 1번은 홈에서 바로 풀 수 있고 오늘의 AX 와 같은 기록을 쓴다. 클릭은 try_click 으로 남겨 관리 > 참여 분석에서 본다.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, get, post, track } from "../api";

type Mine = { choice: string; correct: boolean; answer: string; why: string; stats: { n: number; rate: number } };
type TryData = {
  quiz: { day: string; q: string; sub?: string; options: string[]; left: number; mine?: Mine } | null;
  tests: { url: string; kind: string; emoji: string; name: string; line: string; time: string; count: number | null; mine?: string | null }[];
  spark: { keyword: string; series: number[]; cur: number; rising: boolean }[];
  ask: string[];
  people: { today: number; month: number; top: { country: string; n: number }[]; sample: boolean };
};

export default function TryIt() {
  const ref = useRef<HTMLDivElement>(null);
  const [data, setData] = useState<TryData | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const load = () => get<TryData>("home/try").then(setData).catch(() => undefined);
    if (!("IntersectionObserver" in window)) { load(); return; }
    const io = new IntersectionObserver((es) => { if (es[0].isIntersecting) { io.disconnect(); load(); } }, { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section ref={ref} className="tryit">
      <div className="eyebrow">Try it</div>
      <h3 className="sec-h" style={{ fontSize: "1.35rem", marginBottom: 12 }}><span className="grad">1분 안에</span> 해 보기</h3>
      {!data ? <div className="try-skel" aria-hidden="true" /> : (
        <div className="try-grid">
          {data.quiz && <QuizTile quiz={data.quiz} />}
          <div className="try-tile try-tests">
            <div className="try-h"><span>AX 테스트 5종</span><Link to="/type" onClick={() => track("try_click", "tests_all")}>전체 →</Link></div>
            {data.tests.map((t) => (
              <Link key={t.url} to={t.url} className="try-test" onClick={() => track("try_click", `test:${t.kind}`)}>
                <i>{t.emoji}</i>
                <span><b>{t.name}</b><small>{t.mine ? `내 결과: ${t.mine}` : t.line}</small></span>
                <em>{t.mine ? "다시 →" : t.count ? `${t.count.toLocaleString("ko-KR")}명` : t.time}</em>
              </Link>
            ))}
          </div>
          {data.spark.length > 0 && (
            <Link to="/lab" className="try-tile try-spark" onClick={() => track("try_click", "lab")}>
              <div className="try-h"><span>지금 뜨는 키워드 · 7일</span><em>데이터 랩 →</em></div>
              {data.spark.map((s) => (
                <div className="spark-row" key={s.keyword}>
                  <span>{s.rising ? "▲ " : ""}{s.keyword}</span><Spark values={s.series} /><b>{s.cur}</b>
                </div>
              ))}
            </Link>
          )}
          <Link to="/today#map" className="try-tile try-people" onClick={() => track("try_click", "map")}>
            <div className="try-h"><span>어디서 참여하고 있을까?</span><em>참여 지도 →</em></div>
            {/* 오늘 참여가 아직 없으면 최근 30일 수로 — '0명'이 첫 화면에 보이지 않게 */}
            <div className="people-big">
              <b>{(data.people.today || data.people.month).toLocaleString("ko-KR")}</b>
              <span>명이 {data.people.today ? "오늘" : "최근 30일"} 참여{data.people.sample ? " (예시 포함)" : ""}</span>
            </div>
            {data.people.top.length > 0 && (
              <div className="people-top">
                {data.people.top.map((c) => {
                  const max = data.people.top[0].n || 1;
                  return <div key={c.country}><span>{c.country}</span><div className="trk"><div className="fil" style={{ width: `${(c.n / max) * 100}%` }} /></div></div>;
                })}
              </div>
            )}
          </Link>
          <div className="try-tile try-ask">
            <div className="try-h"><span>AX 질문하기 · 이렇게 물어보세요</span></div>
            <div className="ask-list">
              {data.ask.map((q) => (
                <Link key={q} to={`/ask?q=${encodeURIComponent(q)}`} className="ask-chip" onClick={() => track("try_click", "ask")}>💬 {q}</Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function QuizTile({ quiz }: { quiz: NonNullable<TryData["quiz"]> }) {
  const [mine, setMine] = useState<Mine | undefined>(quiz.mine);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const answer = async (choice: string) => {
    if (busy || mine) return;
    setBusy(true);
    track("try_click", "quiz");
    try {
      setMine(await post<Mine>("today/quiz", { day: quiz.day, i: 0, choice }));
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="try-tile try-quiz">
      <div className="try-h"><span>오늘의 AX 퀴즈 · 1/3</span><Link to="/today">오늘의 AX →</Link></div>
      <p className="try-q">{quiz.q}</p>
      <div className="try-opts">
        {quiz.options.map((o) => {
          const cls = mine ? (o === mine.answer ? "right" : o === mine.choice ? "wrong" : "") : "";
          return <button key={o} type="button" className={`btn sm ${cls}`} disabled={busy || !!mine} onClick={() => answer(o)}>{o}</button>;
        })}
      </div>
      {err && <p className="caption">{err}</p>}
      {mine && (
        <p className="try-res">
          {mine.correct ? "✅ 정답!" : `❌ 정답은 '${mine.answer}'`} · 참여자 정답률 {mine.stats.rate}%{" "}
          <Link to="/today">나머지 {quiz.left}문제 풀기 →</Link>
        </p>
      )}
    </div>
  );
}

function Spark({ values }: { values: number[] }) {
  const w = 90, h = 24, max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / Math.max(1, values.length - 1)) * w},${h - (v / max) * (h - 3) - 1.5}`).join(" ");
  return <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true"><polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" /></svg>;
}
