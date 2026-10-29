// 홈 (/) — Streamlit 판 app_pages/home.py 이식.
// 히어로(숫자 카운트업) → 급상승 키워드 띠 → For you → 처음이라면 3가지 → 이번 주 흐름 → 리더가 알아야 할 3가지
// → 쌓이는 노트(카테고리 내비 + 최신 9편, 60초마다 새로 받아 새 카드는 빛남) → 소스 → 뉴스레터 CTA.
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get, track } from "../api";
import { useDialogs } from "../components/Dialogs";
import NoteCard, { NoteCardData } from "../components/NoteCard";
import { SectionHead, useLoad } from "../components/ui";
import "./Home.css";
import TryIt from "./TryIt";

export const CATEGORIES = ["AX Strategy", "AX Implementation", "AX Enablement"];

type Issue = { id?: number; week: string; range: string; headline_em: string; headline: string; body_html: string; editor_note_html?: string; pdf_url?: string };
type Home = {
  issue: Issue | null;
  issues: { week: string; headline_em: string; headline_short: string }[];
  leader3: { id: number; title: string; category: string; point: string }[];
  stance: string;
  for_you: { url: string; kicker: string; title: string }[];
  ticker: { head: string; rows: { keyword: string; cur: number; prev: number; rising: boolean }[] } | null;
  latest_notes: NoteCardData[];
  counts: { notes: number; articles_week: number; sources: number };
  sources: Record<string, { name: string; url: string }[]>;
};

/** 숫자 카운트업 — 화면에 들어오면 0에서 목표까지 1.1초 동안 오른다 (app/fx.py ⑤와 같은 곡선). */
export function CountUp({ to }: { to: number }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let raf = 0;
    const run = () => {
      if (reduce) { el.textContent = to.toLocaleString("ko-KR"); return; }
      const t0 = performance.now(), dur = 1100;
      const step = (t: number) => {
        const p = Math.min(1, (t - t0) / dur);
        el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))).toLocaleString("ko-KR");
        if (p < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    };
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { run(); io.disconnect(); } }), { threshold: 0.12 });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to]);
  return <b ref={ref} data-to={to}>{to.toLocaleString("ko-KR")}</b>;
}

/** 공유 링크(?s=1)로 들어온 방문을 세션당 한 번 기록한다 (app/play_ui.track_share_visit). */
export function useShareVisit(content: string) {
  const [params] = useSearchParams();
  useEffect(() => {
    if (params.get("s") !== "1") return;
    const key = `_sv_${content}`;
    try {
      if (sessionStorage.getItem(key)) return;
      sessionStorage.setItem(key, "1");
    } catch { /* 저장소가 막혀도 기록은 한다 */ }
    track("share_visit", content);
  }, [params, content]);
}

/** 소스 목록 — 그룹별 펼침 상자 (홈 '어디서 찾아 읽나'). */
export function SourceGroups({ sources }: { sources: Record<string, { name: string; url: string }[]> }) {
  return (
    <div className="src-grid">
      {Object.entries(sources).map(([group, items]) => (
        <details key={group} className="expander">
          <summary><b>{group}</b> · {items.length}곳</summary>
          <ul className="body src-list">
            {items.map((s) => <li key={s.name}><a href={s.url} target="_blank" rel="noopener">{s.name} ↗</a></li>)}
          </ul>
        </details>
      ))}
    </div>
  );
}

/** 내부 주소면 Link, 아니면 a. */
function Go({ href, className, children }: { href: string; className?: string; children: React.ReactNode }) {
  if (href.startsWith("/")) return <Link to={href} className={className}>{children}</Link>;
  return <a href={href} className={className}>{children}</a>;
}

function Ticker({ t }: { t: Home["ticker"] }) {
  if (!t) return null;
  const rows = (t.rows || []).filter((r) => r.rising).length ? t.rows.filter((r) => r.rising) : t.rows || [];
  if (!rows.length) return null;
  const items = rows.slice(0, 12);
  const render = (dup: string) => items.map((r, i) => (
    <Link key={dup + i} to="/lab">
      <i className={r.rising ? "up" : ""}>{r.rising ? "▲" : "●"}</i>{r.keyword}<b>{r.cur}</b>
      {r.rising && <em>{r.prev}→{r.cur}</em>}
    </Link>
  ));
  return (
    <div className="ticker" aria-label={t.head}>
      <span className="ticker-h">{t.head}</span>
      <div className="ticker-track"><div className="ticker-run">{render("a")}{render("b")}</div></div>
    </div>
  );
}

/** 최신 노트 9편 — 60초마다 다시 받아 새로 생긴 카드는 잠깐 빛난다. 카테고리 수도 여기서 센다. */
function LatestNotes({ initial, onCounts }: { initial: NoteCardData[]; onCounts: (c: Record<string, number>, total: number) => void }) {
  const [notes, setNotes] = useState<NoteCardData[]>(initial);
  const [fresh, setFresh] = useState<Set<number>>(new Set());
  const known = useRef<Set<number> | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await get<{ notes: NoteCardData[] }>("notes?sort=latest");
        if (!alive || !r?.notes) return;
        const all = r.notes;
        const counts: Record<string, number> = {};
        for (const n of all) counts[n.category] = (counts[n.category] || 0) + 1;
        onCounts(counts, all.length);
        const latest = all.slice(0, 9);
        const ids = latest.map((n) => n.id);
        if (known.current) {
          const nf = new Set(ids.filter((i) => !known.current!.has(i)));
          if (nf.size) {
            setFresh(nf);
            window.setTimeout(() => alive && setFresh(new Set()), 5000);
          }
        }
        known.current = new Set(ids);
        setNotes(latest);
      } catch { /* 다음 주기에 다시 */ }
    };
    load();
    const t = window.setInterval(load, 60_000);
    return () => { alive = false; window.clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <div className="grid">
      {notes.map((n) => <NoteCard key={n.id} n={n} fresh={fresh.has(n.id)} />)}
    </div>
  );
}

export default function HomePage() {
  const { openSubscribe, openContact } = useDialogs();
  const { data, error } = useLoad(() => get<Home>("home"));
  const [catCounts, setCatCounts] = useState<Record<string, number> | null>(null);
  const [total, setTotal] = useState<number | null>(null);
  useShareVisit("home");

  if (error) return <div className="alert err">{error}</div>;
  if (!data) return <div className="page-loading">불러오는 중…</div>;

  const issue = data.issue || { week: "", range: "", headline_em: "", headline: "첫 주간 흐름을 준비 중입니다", body_html: "" };
  const counts = data.counts || { notes: 0, articles_week: 0, sources: 0 };
  const issues = data.issues || [];
  const nNotes = total ?? counts.notes;
  const nSources = counts.sources ?? Object.values(data.sources || {}).reduce((a, v) => a + v.length, 0);

  return (
    <>
      {/* ---------- 히어로 ---------- */}
      <section className="hero">
        <div className="hero-by" aria-hidden="true" />
        <h1 className="hero-h1"><span className="grad">AX Review</span></h1>
        <p className="hero-lead">기업의 AX를 위한 필수 지식</p>
        <p className="hero-sub">경영진과 AX 실무자에게 필요한 자료를 찾고, 정리하고, 쌓아 둡니다.</p>
        <div className="hero-stats">
          <div><CountUp to={counts.notes} /><span>쌓인 노트</span></div>
          <div><CountUp to={counts.articles_week} /><span>최근 7일 검토 기사</span></div>
          <div><CountUp to={nSources} /><span>수집 소스</span></div>
        </div>
        <div className="hero-btns">
          <button className="btn primary" onClick={() => openSubscribe("home_hero")}>이메일 리스트 구독하기 →</button>
          <button className="btn ghost" onClick={openContact}>AX 담당자에게 문의하기</button>
        </div>
      </section>

      <Ticker t={data.ticker} />

      {/* ---------- For you ---------- */}
      {data.for_you?.length > 0 && (
        <>
          <div className="eyebrow">For you</div>
          <div className="start foryou">
            {data.for_you.slice(0, 4).map((c) => (
              <Go key={c.url + c.title} href={c.url}><span className="n">{c.kicker}</span><b>{c.title}</b><em>보기 →</em></Go>
            ))}
          </div>
        </>
      )}

      {/* ---------- 처음 오셨나요 ---------- */}
      <div className="eyebrow">Start here</div>
      <h3 className="sec-h" style={{ fontSize: "1.35rem", marginBottom: 12 }}>처음이라면 <span className="grad">이 3가지</span>만 보세요</h3>
      <div className="start">
        <a href="#this-week"><span className="n">01 · 1분</span><b>이번 주 AX 흐름</b>
          <span>한 주의 AX 소식을 한 줄 헤드라인과 노트로 묶었습니다. 아래로 내리면 바로 보입니다.</span><em>매주 월요일 갱신</em></a>
        <Link to="/type"><span className="n">02 · 1분</span><b>나는 어떤 AX 리더?</b>
          <span>12문항으로 16가지 AX 리더 유형 중 내 유형과 찰떡 동료를 알려 드립니다.</span><em>결과 공유하기 ↗</em></Link>
        <Link to="/today"><span className="n">03 · 30초</span><b>오늘의 AX 퀴즈·예측</b>
          <span>실제 수집 데이터로 만든 3문제와 '내일의 키워드' 투표. 매일 새로 나옵니다.</span><em>🔥 연속 참여 기록</em></Link>
      </div>

      {/* ---------- 1분 안에 해 보기 (각 페이지 인터랙션 맛보기) ---------- */}
      <TryIt />

      {/* ---------- 이번 주 흐름 ---------- */}
      <div id="this-week" />
      <section className="week">
        <div>
          <div className="eyebrow">This Week · {issue.week} · {issue.range}</div>
          <h2 className="sec-h">이번 주 <span className="grad">AX 흐름</span></h2>
          <h3 className="week-title">{issue.headline_em && <span>{issue.headline_em} </span>}{issue.headline}</h3>
          <p className="week-body" dangerouslySetInnerHTML={{ __html: issue.body_html || "" }} />
          {issue.editor_note_html && (
            <div className="ednote"><i>EDITOR'S NOTE</i><span dangerouslySetInnerHTML={{ __html: issue.editor_note_html }} /></div>
          )}
          {issue.pdf_url && <a className="btn" style={{ marginTop: 14 }} href={issue.pdf_url} download>📄 이번 호 PDF 리포트 받기</a>}
        </div>
        <div className="flow">
          <span className="flow-h">흐름의 이동</span>
          <ol>
            {issues.slice(-5).map((x, i, arr) => (
              <li key={x.week + i} className={i === arr.length - 1 ? "now" : ""}>
                <b>{x.week}</b>{`${x.headline_em || ""} ${x.headline_short || ""}`.trim()}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ---------- 리더가 알아야 할 3가지 ---------- */}
      {data.leader3?.length > 0 && (
        <div className="l3">
          <div className="eyebrow">Leader's 3</div>
          <h3 className="sec-h" style={{ fontSize: "1.35rem", marginBottom: 2 }}>리더가 이번 주 <span className="grad">알아야 할 3가지</span></h3>
          <p className="sec-p" style={{ margin: 0 }}>{data.stance}</p>
          <div className="l3-grid">
            {data.leader3.map((t, i) => (
              <Link key={t.id} className="l3-card" to={`/notes?id=${t.id}`}>
                <span className="l3-n">{i + 1}</span>
                <b className="t">{t.point}</b>
                <span className="src">{t.category} · {(t.title || "").slice(0, 60)}</span>
              </Link>
            ))}
          </div>
          <Link to="/letter" className="more" style={{ display: "inline-block", marginTop: 12 }}>✉ 이 내용이 매주 메일로 옵니다 · 메일 미리 보기 →</Link>
        </div>
      )}

      {/* ---------- 노트 ---------- */}
      <div style={{ marginTop: 36 }} />
      <SectionHead
        eyebrow="Latest Notes" title="쌓이는" grad="노트"
        p={<>원문을 깊게 읽고 요약·핵심 포인트·현업 실행·AX 적용까지 정리한 글입니다. 노트 {nNotes}편.</>}
        right={<Link className="more" to="/notes">전체 보기 →</Link>}
      />
      <nav className="cat-nav">
        {CATEGORIES.map((c) => (
          <Link key={c} to={`/notes?cat=${encodeURIComponent(c)}`}>
            <b><span>AX </span>{c.slice(3)}</b><i>{catCounts ? catCounts[c] || 0 : "·"}</i>
          </Link>
        ))}
      </nav>
      <LatestNotes initial={data.latest_notes || []} onCounts={(c, t) => { setCatCounts(c); setTotal(t); }} />

      {/* ---------- 소스 ---------- */}
      <section className="sources">
        <div className="eyebrow">Sources</div>
        <h2 className="sec-h">어디서 <span className="grad">찾아 읽나</span></h2>
        <p className="sec-p" style={{ marginBottom: 18 }}>
          아래 {nSources}곳을 훑어 후보를 고르고, 원문을 깊게 읽은 것만 노트로 남깁니다. 기사보다 당사자가 직접 쓰거나 말한 원문을 먼저 봅니다.
        </p>
        <SourceGroups sources={data.sources || {}} />
      </section>

      {/* ---------- 뉴스레터 CTA ---------- */}
      <section className="cta">
        <div>
          <div className="eyebrow" style={{ color: "#CFE9FF" }}>Newsletter</div>
          <h2 className="sec-h" style={{ color: "#fff" }}>새 노트가 쌓이면<br />메일로 받아 보세요</h2>
          <p className="sec-p">읽은 자료 중 AX 관점에서 중요한 것만 골라 정리해 보내 드립니다.</p>
        </div>
        <button className="btn cta-btn" onClick={() => openSubscribe("home_cta")}>뉴스레터 구독 →</button>
      </section>
    </>
  );
}
