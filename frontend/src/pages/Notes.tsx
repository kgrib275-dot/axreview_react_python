// 노트 (/notes) — Streamlit 판 app_pages/notes.py + app/note_ui.py 이식.
// ?id= 가 있으면 상세, 없으면 목록. 필터(q·semantic·cats·kinds·inds·sort)는 방문자 상태(useMe)에 저장돼 다음 방문에도 그대로다.
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { get } from "../api";
import { INDUSTRIES, SubscribeCTA } from "../components/Dialogs";
import NoteCard, { NoteCardData, useBookmarks } from "../components/NoteCard";
import ShareBar from "../components/ShareBar";
import { Alert, Guide, useLoad } from "../components/ui";
import { useMe } from "../me";
import { CATEGORIES, useShareVisit } from "./shared";
import "./Notes.css";

type ListRes = {
  notes: NoteCardData[];
  meta?: { categories?: string[]; kinds?: string[]; industries?: string[] };
  semantic_note?: string;
};
type Detail = {
  note: NoteCardData & { body_html: string; toc?: string[]; url?: string; status?: string; body?: string };
  prev?: { id: number; title: string } | null;
  next?: { id: number; title: string } | null;
  related?: NoteCardData[];
  share_url?: string;
};

const SORTS: [string, string][] = [["latest", "최신순"], ["popular", "인기순"]];

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** 브라우저 탭·북마크·공유 제목. 화면을 떠나면 이전 제목으로 되돌린다 (SPA 라 서버가 넣은 <title>이 그대로 남지 않게). */
function useTitle(title: string | undefined) {
  useEffect(() => {
    if (!title) return;
    const prev = document.title;
    document.title = title;
    return () => { document.title = prev; };
  }, [title]);
}

export default function NotesPage() {
  const [params] = useSearchParams();
  const id = params.get("id");
  useShareVisit("note");
  return id && /^[0-9]{1,9}$/.test(id) ? <NoteDetail id={id} /> : <NoteList />;
}

/* ====================== 상세 ====================== */
function NoteDetail({ id }: { id: string }) {
  const { data, error, loading } = useLoad(() => get<Detail>(`notes/${id}`), [id]);
  const bodyRef = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const [pendingJump, setPendingJump] = useState<string | null>(null);
  useTitle(data?.note.title ? `${data.note.title} — AX Review` : undefined);

  useEffect(() => { window.scrollTo(0, 0); setMore(false); }, [id]);
  useEffect(() => {
    if (more && pendingJump) { jumpTo(bodyRef.current, pendingJump); setPendingJump(null); }
  }, [more, pendingJump]);

  if (error) return (
    <>
      <Link className="more" to="/notes">← 노트 목록</Link>
      <Alert kind="warn">{error}</Alert>
    </>
  );
  if (loading || !data) return <div className="page-loading">불러오는 중…</div>;
  const n = data.note;
  const tags = (n.tags || "").split(",").filter(Boolean).map((t) => `#${t}`).join(" ");
  const audiences = (n.audiences || "").split(",").filter(Boolean);
  // 읽는 시간: 본문 글자 수 / 600 (원본은 마크다운 길이 기준)
  const textLen = (n.body || n.body_html || "").replace(/<[^>]+>/g, "").length;
  const minutes = Math.max(1, Math.round(textLen / 600));
  const toc = n.toc || [];
  // 긴 노트는 '요약·핵심 포인트'만 먼저 보이고 나머지(기술·운영 디테일·현업 실행·AX 적용)는 '자세히 보기'로 편다 — 3분 안에 핵심
  const html = n.body_html || "";
  const cut = textLen > 1500 ? nthIndex(html, "<h3", 3) : -1;
  const head = cut > 0 && !more ? html.slice(0, cut) : html;
  const restTitles = cut > 0 ? toc.slice(2) : [];
  const headMin = Math.max(1, Math.round(head.replace(/<[^>]+>/g, "").length / 600));

  const jump = (want: string) => {
    if (cut > 0 && !more && restTitles.some((t) => t === want)) { setMore(true); setPendingJump(want); return; }
    jumpTo(bodyRef.current, want);
  };

  return (
    <>
      <Link className="more" to="/notes">← 노트 목록</Link>
      {n.status && n.status !== "published" && <Alert kind="warn">게시 전 초안 미리보기입니다. 관리 &gt; 노트 검토에서 게시할 수 있습니다.</Alert>}
      <div className="meta detail-meta">
        <span className="badge">{n.category}</span><span className="kind">{n.kind}</span>
      </div>
      <h1 className="detail-h">{n.title}</h1>
      <div className="src" style={{ color: "var(--muted)", fontSize: ".85rem" }}>
        {n.source} · {(n.published || "").replace(/-/g, ".")} · {tags}
      </div>
      {audiences.length > 0 && <div className="aud" style={{ marginTop: 10 }}>{audiences.map((a) => <span key={a}>{a}</span>)}</div>}

      {/* 목차 칩 + 읽는 시간 (note_ui.detail_bar) */}
      <div className="nt-bar">
        <span className="nt-read">{cut > 0 ? `핵심 ${headMin}분 · 전체 ${minutes}분` : `약 ${minutes}분 읽기`}</span>
        {toc.map((h) => <button key={h} type="button" className="toc" onClick={() => jump(h)}>{h}</button>)}
      </div>
      <ShareBar content="note" url={data.share_url} title={n.title} />
      <hr className="divider" />
      <div ref={bodyRef} className="note-body" dangerouslySetInnerHTML={{ __html: head }} />
      {cut > 0 && !more && (
        <button type="button" className="btn block" style={{ marginTop: 12 }} onClick={() => setMore(true)}>
          자세히 보기 — {restTitles.join(" · ")} (+{Math.max(1, minutes - headMin)}분)
        </button>
      )}
      {n.url && <a className="btn" href={n.url} target="_blank" rel="noopener" style={{ marginTop: 14 }}>↗ 원문 보기</a>}

      {(data.prev || data.next) && (
        <div className="note-nav">
          {data.prev && <Link className="nav-prev" to={`/notes?id=${data.prev.id}`}><span>← 이전 노트</span><b>{data.prev.title}</b></Link>}
          {data.next && <Link className="nav-next" to={`/notes?id=${data.next.id}`}><span>다음 노트 →</span><b>{data.next.title}</b></Link>}
        </div>
      )}

      {data.related && data.related.length > 0 && (
        <>
          <div className="eyebrow" style={{ marginTop: 28 }}>관련 노트</div>
          <h3 className="sec-h" style={{ fontSize: "1.3rem" }}>이 노트와 <span className="grad">가까운 노트</span></h3>
          <div className="grid">{data.related.map((r) => <NoteCard key={r.id} n={r} />)}</div>
        </>
      )}
      <hr className="divider" />
      <SubscribeCTA source="note_detail" headline="이런 노트를 매주 받아 보세요" sub="한 주의 노트 5편과 AX 흐름 요약을 월요일 아침 메일로 보내 드립니다." />
    </>
  );
}

/* ====================== 목록 ====================== */
function NoteList() {
  const { me, state, setState } = useMe();
  const [params] = useSearchParams();
  const [bm, toggleBm] = useBookmarks();
  const [only, setOnly] = useState(false);
  useTitle("AX 노트 — AX Review");

  // 필터 값: 방문자 상태 → 없으면 기본값. 업종 기본값은 구독할 때 고른 업종(pref_inds).
  const q = typeof state.q === "string" ? state.q : "";
  const semantic = state.semantic === true;
  const cats = asList(state.cats);
  const kinds = asList(state.kinds);
  const inds = state.inds === undefined ? asList(state.pref_inds).filter((x) => INDUSTRIES.includes(x)) : asList(state.inds);
  const sort = state.sort === "popular" || state.sort === "인기순" ? "popular" : "latest";

  // 주소의 ?cat= / ?ind= 는 그 값으로 필터를 맞춘다 (홈 카테고리 내비·For you 카드에서 들어올 때)
  const cat = params.get("cat"), ind = params.get("ind");
  useEffect(() => {
    if (!me) return; // 방문자 상태를 받기 전에 바꾸면 서버 스냅샷이 덮어쓴다
    if (cat && CATEGORIES.includes(cat)) setState({ cats: [cat] });
    if (ind && INDUSTRIES.includes(ind)) setState({ inds: [ind] });
  }, [me, cat, ind, setState]);

  // 검색어 입력은 잠깐 모아서 저장·조회한다
  const [qLocal, setQLocal] = useState(q);
  const seeded = useRef(false);
  useEffect(() => {
    if (me && !seeded.current) { seeded.current = true; setQLocal(q); }
  }, [me, q]);
  useEffect(() => {
    const t = window.setTimeout(() => { if (qLocal !== q) setState({ q: qLocal }); }, 350);
    return () => window.clearTimeout(t);
  }, [qLocal, q, setState]);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (semantic) p.set("semantic", "1");
    if (cats.length) p.set("cats", cats.join(","));
    if (kinds.length) p.set("kinds", kinds.join(","));
    if (inds.length) p.set("inds", inds.join(","));
    p.set("sort", sort);
    return p.toString();
  }, [q, semantic, cats.join(","), kinds.join(","), inds.join(","), sort]); // eslint-disable-line react-hooks/exhaustive-deps

  const { data, error, loading } = useLoad(() => get<ListRes>(`notes?${query}`), [query]);
  // 유형 목록은 필터 없이 받은 첫 결과의 meta 를 기억한다 (필터를 걸어도 알약이 줄지 않게)
  const [meta, setMeta] = useState<{ kinds: string[]; industries: string[]; total: number } | null>(null);
  useEffect(() => {
    if (!data) return;
    setMeta((m) => {
      const kindsAll = data.meta?.kinds?.length ? data.meta.kinds : Array.from(new Set(data.notes.map((n) => n.kind))).sort();
      const indsAll = data.meta?.industries?.length ? data.meta.industries : INDUSTRIES;
      const unfiltered = !q && !cats.length && !kinds.length && !inds.length;
      if (!m || unfiltered) return { kinds: kindsAll, industries: indsAll, total: unfiltered ? data.notes.length : m?.total ?? data.notes.length };
      return { ...m, kinds: m.kinds.length ? m.kinds : kindsAll };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const toggle = (key: "cats" | "kinds" | "inds", cur: string[], v: string) =>
    setState({ [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });

  const hits = data?.notes || [];
  const shown = only ? hits.filter((n) => bm.has(n.id)) : hits;
  const semanticOn = !!q && semantic && hits.length > 0 && hits.some((n) => n.similarity !== undefined);
  const tail = semanticOn ? " · 뜻이 가까운 순" : sort === "popular" ? " · 조회 많은 순" : "";

  return (
    <>
      <div className="eyebrow">노트</div>
      <h2 className="sec-h">모든 <span className="grad">노트</span></h2>
      <p className="sec-p" style={{ marginBottom: 12 }}>노트 {meta?.total ?? hits.length}편. 카테고리·유형·키워드로 찾아보세요.</p>
      <Guide title="노트 보는 법" items={[
        ["검색·필터", "단어로 찾거나 '의미 검색'을 켜면 문장으로 물어도 뜻이 가까운 노트를 찾습니다."],
        ["☆ 북마크", "카드 오른쪽 위 ☆로 저장하고 '북마크만 보기'로 모아 봅니다."],
        ["카드 열기", "노트마다 요약 → 핵심 포인트 → 현업 실행 → AX 적용 순서로 읽으면 됩니다."],
      ]} />

      <div className="note-filters">
        <div className="field f-q">
          <label htmlFor="note-q">검색</label>
          <input id="note-q" type="text" value={qLocal} onChange={(e) => setQLocal(e.target.value)} maxLength={200}
            placeholder="제목·요약·태그 검색, 또는 '의미 검색'으로 문장 질문" />
        </div>
        <label className="check f-sem" title="단어가 달라도 뜻이 가까운 노트를 찾습니다 (Gemini 임베딩).">
          <input type="checkbox" checked={semantic} onChange={(e) => setState({ semantic: e.target.checked })} /> 의미 검색
        </label>
        <div className="field">
          <label>카테고리</label>
          <div className="btn-row">
            {CATEGORIES.map((c) => <button key={c} type="button" className={`pill ${cats.includes(c) ? "on" : ""}`} onClick={() => toggle("cats", cats, c)}>{c}</button>)}
          </div>
        </div>
        <div className="field">
          <label>유형</label>
          <div className="btn-row">
            {(meta?.kinds || []).map((k) => <button key={k} type="button" className={`pill ${kinds.includes(k) ? "on" : ""}`} onClick={() => toggle("kinds", kinds, k)}>{k}</button>)}
          </div>
        </div>
        <div className="field">
          <label title="노트 제목·태그·요약·본문의 업종 단어로 분류합니다 (pipeline/industry.py).">업종</label>
          <div className="btn-row">
            {(meta?.industries || INDUSTRIES).map((k) => <button key={k} type="button" className={`pill ${inds.includes(k) ? "on" : ""}`} onClick={() => toggle("inds", inds, k)}>{k}</button>)}
          </div>
        </div>
        <div className="field">
          <label>정렬</label>
          <div className="seg">
            {SORTS.map(([v, l]) => <button key={v} type="button" className={sort === v ? "on" : ""} onClick={() => setState({ sort: v })}>{l}</button>)}
          </div>
        </div>
      </div>

      {data?.semantic_note && <p className="caption">{data.semantic_note}</p>}
      {error && <Alert kind="err">{error}</Alert>}
      <p className="caption">{loading && !data ? "찾는 중…" : `${hits.length}편${tail}`}</p>

      {/* 북마크만 보기 (note_ui.bookmarks) */}
      <div className="bm-bar">
        <button type="button" className={only ? "on" : ""} onClick={() => setOnly((o) => !o)}>{only ? "★ 북마크만 보는 중" : "☆ 북마크만 보기"}</button>
        <span>{bm.size ? `북마크 ${bm.size}편 (이 브라우저에 저장)` : "카드의 ☆를 눌러 북마크하세요"}</span>
      </div>

      {shown.length > 0 ? (
        <div className="grid" style={{ marginTop: 12 }}>
          {shown.map((n) => <NoteCard key={n.id} n={n} bookmarked={bm.has(n.id)} onBookmark={toggleBm} />)}
        </div>
      ) : only ? (
        <div className="bm-empty">북마크한 노트가 없습니다. 카드 오른쪽 위 ☆를 눌러 저장하세요.</div>
      ) : data ? (
        <Alert kind="info">조건에 맞는 노트가 없습니다.</Alert>
      ) : null}
    </>
  );
}

function nthIndex(s: string, sub: string, n: number): number {
  let i = -1;
  for (let k = 0; k < n; k++) { i = s.indexOf(sub, i + 1); if (i < 0) return -1; }
  return i;
}

function jumpTo(root: HTMLElement | null, want: string) {
  const hs = root?.querySelectorAll("h3") || [];
  const h = Array.from(hs).find((x) => (x.textContent || "").trim().startsWith(want));
  h?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}
