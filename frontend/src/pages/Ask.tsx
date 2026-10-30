// AX 질문하기 (/ask) — 노트·수집 기사를 근거로 답하는 채팅. 대화는 브라우저 sessionStorage 에만 남고 서버에는 저장하지 않는다.
// 한도는 서버 기록으로 센다 ('대화 지우기'·새로고침으로 초기화되지 않음).
// 횟수제: 뉴스레터 구독자만 — 구독 확인 때 무료 횟수(free_credits)를 받고, 다 쓰면 '충전 요청' → 관리자가 충전. 구독자가 아니면(linked=false)
// 구독하거나, 이미 구독 중이면 구독 주소로 연결 메일을 받아 이 브라우저를 잇는다 (?link=토큰 → 버튼을 눌러야 확정, 메일 검사기 대비).
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { SubscribeCTA, useDialogs } from "../components/Dialogs";
import { Alert, Guide, useLoad } from "../components/ui";
import { useMe } from "../me";
import "./Ask.css";

type Source = { title: string; url: string; kind: string; sim: number };
type Turn = { role: "user" | "assistant"; content: string; sources?: Source[]; weak?: boolean };
type Usage = { enabled: boolean; quota: number; used: number; limit_hit: boolean; linked: boolean; email_masked?: string; requested?: boolean; member?: { expires?: string } | null; is_admin: boolean; free_credits: number; member_daily: number; plan_price?: string; global_hit?: boolean; web_search?: boolean };

const HKEY = "axreview-ask-history";
const EXAMPLES = ["제조 현장에 AI 에이전트를 도입한 사례 알려줘", "에이전트 운영 거버넌스는 어떻게 설계해?", "이번 주 AX 흐름을 3줄로 요약해줘", "금융권 AX 노트만 모아줘"];

function loadHistory(): Turn[] {
  try { const h = JSON.parse(sessionStorage.getItem(HKEY) || "[]"); return Array.isArray(h) ? h : []; } catch { return []; }
}

export default function Ask() {
  const { me, reload: reloadMe } = useMe();
  const { openMembership, openSubscribe } = useDialogs();
  const { data: usage, error, loading, reload, setData } = useLoad<Usage>(() => get<Usage>("ask/usage"), []);
  const [history, setHistory] = useState<Turn[]>(() => loadHistory());
  // 홈 맛보기의 예시 질문(?q=)은 입력칸에 채워만 둔다 — 질문 한도를 쓰는 전송은 본인이 누른다
  const [q, setQ] = useState(() => (new URLSearchParams(window.location.search).get("q") || "").slice(0, 500));
  const [busy, setBusy] = useState<"ask" | "web" | null>(null);
  const [warn, setWarn] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null); // 답을 기다리는 중인 질문
  // 연결 메일의 토큰(?link=) — 자동으로 확정하지 않고 버튼을 눌러야 보낸다
  const [linkToken, setLinkToken] = useState(() => { const t = new URLSearchParams(window.location.search).get("link") || ""; return /^[0-9a-f]{32}$/.test(t) ? t : ""; });
  const [linkMsg, setLinkMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [reqBusy, setReqBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try { sessionStorage.setItem(HKEY, JSON.stringify(history)); } catch { /* 저장 못 해도 진행 */ }
  }, [history]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [history.length, pending]);

  if (loading && !usage) return <div className="page-loading">불러오는 중…</div>;

  const limitHit = !!usage?.limit_hit;
  const member = usage?.member || me?.member || null;
  const isAdmin = !!usage?.is_admin;
  const quota = usage?.quota ?? 0, used = usage?.used ?? 0;
  const linked = !!usage?.linked;

  const stripLink = () => {
    const u = new URL(window.location.href);
    u.searchParams.delete("link");
    window.history.replaceState(null, "", u.pathname + (u.search || "") + u.hash);
    setLinkToken("");
  };
  const confirmLink = async () => {
    setLinkMsg(null);
    try {
      const r = await post<{ ok: boolean; email_masked: string }>("ask/link/confirm", { t: linkToken });
      setLinkMsg({ kind: "ok", text: `${r.email_masked} 구독자로 연결됐습니다.` });
      stripLink();
      reload(); reloadMe();
    } catch (e) {
      setLinkMsg({ kind: "err", text: (e as ApiError).message });
    }
  };
  const requestCredits = async () => {
    if (reqBusy) return;
    setReqBusy(true);
    try {
      await post("ask/request");
      setData(usage ? { ...usage, requested: true } : usage);
      reload();
    } catch (e) {
      setWarn((e as ApiError).message);
    } finally {
      setReqBusy(false);
    }
  };

  const send = async (question: string) => {
    const text = question.trim().slice(0, 500);
    if (!text || busy || limitHit) return;
    setWarn(null);
    setBusy("ask");
    setPending(text);
    setQ("");
    try {
      const r = await post<{ answer: string; sources?: Source[]; weak?: boolean }>("ask", { question: text, history: history.map((t) => ({ role: t.role, content: t.content })).slice(-6) });
      setHistory((h) => [...h, { role: "user", content: text }, { role: "assistant", content: r.answer, sources: r.sources || [], weak: !!r.weak }]);
      setData(usage ? { ...usage, used: used + 1, limit_hit: !isAdmin && used + 1 >= quota } : usage);
      reload();
    } catch (e) {
      const err = e as ApiError;
      setWarn(err.status === 429 ? "질문 한도에 도달했습니다." : err.status === 409 ? "앞선 질문의 답을 만드는 중입니다. 잠시 후 다시 물어 주세요." : err.message);
      if (err.status === 429) reload();
    } finally {
      setBusy(null);
      setPending(null);
    }
  };

  const webSearch = async (i: number) => {
    const question = history[i - 1]?.content;
    if (!question || busy) return;
    setWarn(null);
    setBusy("web");
    try {
      const r = await post<{ answer: string }>("ask/web", { question, history: history.slice(0, i - 1).map((t) => ({ role: t.role, content: t.content })) });
      setHistory((h) => [...h, { role: "assistant", content: r.answer }]);  // '웹 검색 기반' 문구는 서버가 붙인다
      reload();
    } catch (e) {
      const err = e as ApiError;
      setWarn(err.status === 429 ? "질문 한도에 도달했습니다." : err.message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="ask-page">
      <div className="eyebrow">AX 질문하기</div>
      <h2 className="sec-h">AX <span className="grad">질문하기</span></h2>
      <p className="sec-p">AX Review에 쌓인 노트와 수집 기사를 근거로 답합니다. 답변의 링크로 원문 노트를 확인하세요.</p>
      <Guide title="이렇게 물어보세요" items={[
        ["사례", "'제조 현장 AI 에이전트 도입 사례 알려줘'처럼 업종·주제를 넣으면 근거 노트를 붙여 답합니다."],
        ["목록·기간", "'이번 달 AX Strategy 노트만 모아줘'처럼 조건을 주면 정확한 목록을 찾습니다."],
        ["근거 확인", "답 아래 '근거 자료'를 펼치면 참고한 노트·기사로 바로 갈 수 있습니다."],
      ]} />
      <p className="caption">질문과 대화 일부는 답변 생성을 위해 Google(미국, Gemini API)로 전송되며 이 사이트에는 저장되지 않습니다. 이름·연락처 같은 개인정보는 입력하지 마세요. <Link to="/privacy">개인정보 처리방침</Link></p>

      {error && <Alert kind="err">{error}</Alert>}
      {usage && !usage.enabled && <Alert kind="info">ℹ️ 지금은 질문하기를 사용할 수 없습니다.</Alert>}

      {usage?.enabled && (
        <>
          {linkToken && (
            <div className="box ask-upsell">
              <p><b>이 브라우저를 구독자로 연결</b><br />메일의 링크로 들어왔습니다. 아래 버튼을 누르면 이 브라우저가 구독한 주소와 이어져 남은 질문 횟수를 씁니다.</p>
              <div className="btn-row">
                <button className="btn primary" type="button" onClick={confirmLink}>🔗 연결하기</button>
                <button className="btn" type="button" onClick={stripLink}>취소</button>
              </div>
            </div>
          )}
          {linkMsg && <Alert kind={linkMsg.kind}>{linkMsg.text}</Alert>}

          {!history.length && !limitHit && (
            <>
              <p className="caption">예시 질문</p>
              <div className="btn-row" style={{ marginBottom: 14 }}>
                {EXAMPLES.map((ex) => <button key={ex} className="btn sm" type="button" disabled={!!busy} onClick={() => send(ex)}>💬 {ex}</button>)}
              </div>
            </>
          )}

          <div className="chat">
            {history.map((t, i) => (
              <div key={i} className={`msg ${t.role}`}>
                <span className="av">{t.role === "user" ? "👤" : "✦"}</span>
                <div className="bubble">
                  <Markdown text={t.content} />
                  {!!t.sources?.length && (
                    <details className="expander">
                      <summary>📖 근거 자료</summary>
                      <ul className="body srcs">
                        {t.sources.map((s, k) => <li key={k}><a href={s.url} target="_blank" rel="noopener">{s.title}</a> · {s.kind} · 유사도 {Number(s.sim).toFixed(2)}</li>)}
                      </ul>
                    </details>
                  )}
                  {t.weak && i === history.length - 1 && usage.web_search !== false && !limitHit && (
                    <button className="btn sm" type="button" disabled={!!busy} onClick={() => webSearch(i)}>{busy === "web" ? "웹을 검색하는 중..." : "🌐 웹 검색으로 다시 답하기"}</button>
                  )}
                </div>
              </div>
            ))}
            {pending && (
              <>
                <div className="msg user"><span className="av">👤</span><div className="bubble">{pending}</div></div>
                <div className="msg assistant"><span className="av">✦</span><div className="bubble muted">관련 노트를 찾고 답을 쓰는 중...</div></div>
              </>
            )}
            <div ref={endRef} />
          </div>

          {warn && <Alert kind="warn">{warn}</Alert>}

          <form className="chat-in" onSubmit={(e) => { e.preventDefault(); send(q); }}>
            <textarea value={q} maxLength={500} rows={2} placeholder="AX에 대해 물어보세요" disabled={limitHit || !!busy}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(q); } }} />
            <div className="chat-in-r">
              <span className="caption">{q.length}/500</span>
              <button className="btn primary" disabled={limitHit || !!busy || !q.trim()}>보내기</button>
            </div>
          </form>

          {isAdmin ? (
            <p className="caption">관리자는 질문 한도 없이 사용합니다.</p>
          ) : member ? (
            <p className="caption">⭐ 월 구독 · 오늘 {Math.max(quota - used, 0)}/{quota}회 남음 · {member.expires}까지</p>
          ) : linked && !limitHit ? (
            <p className="caption">남은 질문 {Math.max(quota - used, 0)}/{quota}회 · {usage.email_masked}</p>
          ) : null}

          {limitHit && usage.global_hit ? (
            <p className="caption">오늘 전체 질문 한도에 도달했습니다. 내일 다시 이용해 주세요.</p>
          ) : limitHit && member ? (
            <p className="caption">오늘 질문을 모두 썼습니다. 내일 다시 이용해 주세요.</p>
          ) : !isAdmin && !linked ? (
            <div className="box ask-upsell">
              <p><b>AX 질문하기는 뉴스레터 구독자에게 무료 {usage.free_credits}회(이후 관리자 충전) 제공됩니다.</b><br />구독은 무료이고, 확인 메일의 버튼을 누르면 이 브라우저에서 바로 질문할 수 있습니다.</p>
              <button className="btn primary" type="button" onClick={() => openSubscribe("ask")}>✉️ 무료로 구독하기</button>
              <details className="expander" style={{ marginTop: 10 }}>
                <summary>이미 구독 중이라면 구독한 이메일로 이 브라우저를 연결</summary>
                <div className="body"><LinkForm /></div>
              </details>
            </div>
          ) : limitHit && linked ? (
            <div className="box ask-upsell">
              <p><b>질문 횟수를 모두 썼습니다.</b> ({used}/{quota}회 · {usage.email_masked})<br />관리자 승인 후 충전됩니다. 충전되면 메일로 알려 드립니다.</p>
              {usage.requested ? (
                <button className="btn" type="button" disabled>요청됨 · 충전되면 메일로 알려 드립니다</button>
              ) : (
                <button className="btn primary" type="button" disabled={reqBusy} onClick={requestCredits}>{reqBusy ? "요청하는 중..." : "🔋 충전 요청하기"}</button>
              )}
            </div>
          ) : null}
          {!member && !isAdmin && (
            <details className="expander">
              <summary>월 구독 코드가 있나요?</summary>
              <div className="body">
                <RedeemForm onDone={() => { reload(); reloadMe(); }} memberDaily={usage.member_daily} />
                <p className="caption" style={{ marginTop: 8 }}>월 구독(하루 {usage.member_daily}회)은 담당자 안내 후 코드로 적용됩니다. <button className="btn sm" type="button" onClick={openMembership}>🏅 월 구독 신청하기</button></p>
              </div>
            </details>
          )}

          {history.length > 0 && (
            <button className="btn sm" type="button" style={{ marginTop: 12 }} onClick={() => { setHistory([]); setWarn(null); }}>🧹 대화 지우기</button>
          )}

          {/* 첫 답을 본 뒤에만 — 쓸모를 느낀 다음에 구독을 권한다 (대화 목록 밖, 한 번만) */}
          {history.some((t) => t.role === "assistant") && (
            <>
              <hr className="divider" />
              <SubscribeCTA source="ask" headline="이런 사례를 매주 메일로 받아 보세요" sub="질문의 근거가 된 노트 같은 기업 AX 사례 5편과 한 주의 흐름 요약을 월요일 아침 메일로 보내 드립니다." />
            </>
          )}
        </>
      )}
    </div>
  );
}

/** 구독한 이메일로 연결 메일 받기 — 응답은 구독 여부와 무관하게 같은 문구 (존재 여부 비노출). */
function LinkForm() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setMsg(null); setBusy(true);
    try {
      const r = await post<{ message: string }>("ask/link", { email: email.trim() });
      setMsg({ kind: "ok", text: r.message });
      setEmail("");
    } catch (err) {
      const er = err as ApiError;
      setMsg(er.status === 429 ? { kind: "warn", text: "잠시 후 다시 시도해 주세요." } : { kind: "err", text: er.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="redeem" onSubmit={submit}>
      <div className="field" style={{ flex: 1, marginBottom: 0 }}>
        <label>구독한 이메일</label>
        <input type="email" value={email} maxLength={254} placeholder="you@company.com" onChange={(e) => setEmail(e.target.value)} />
      </div>
      <button className="btn" disabled={busy || !email.trim()}>{busy ? "보내는 중..." : "연결 메일 받기"}</button>
      {msg && <div style={{ flexBasis: "100%" }}><Alert kind={msg.kind}>{msg.text}</Alert></div>}
    </form>
  );
}

function RedeemForm({ onDone, memberDaily }: { onDone: () => void; memberDaily: number }) {
  const { setState } = useMe();
  const [code, setCode] = useState("");
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMsg(null);
    try {
      const r = await post<{ expires: string; quota?: number; id?: number }>("ask/redeem", { code: code.trim() });
      // member_id 는 서버가 코드 확인 뒤 저장한다 (화면이 직접 쓰지 않음)
      setMsg({ kind: "ok", text: `월 구독이 적용됐습니다. ${r.expires}까지 하루 ${r.quota ?? memberDaily}회` });
      setCode("");
      onDone();
    } catch (err) {
      const er = err as ApiError;
      setMsg(er.status === 429 ? { kind: "warn", text: "잠시 후 다시 시도해 주세요." } : { kind: "err", text: "코드를 확인해 주세요. 기간이 끝났다면 담당자에게 연장을 요청해 주세요." });
    }
  };
  return (
    <form className="redeem" onSubmit={submit}>
      <div className="field" style={{ flex: 1, marginBottom: 0 }}>
        <label>구독 코드</label>
        <input type="text" value={code} maxLength={40} placeholder="AXR-XXXX-XXXX-XXXX" onChange={(e) => setCode(e.target.value)} />
      </div>
      <button className="btn" disabled={!code.trim()}>적용</button>
      {msg && <div style={{ flexBasis: "100%" }}><Alert kind={msg.kind}>{msg.text}</Alert></div>}
    </form>
  );
}

/** 답변용 작은 마크다운 — 문단·목록·굵게·기울임·링크·코드만 (외부 라이브러리 없음). */
function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  const lines = text.split(/\r?\n/);
  let list: { ordered: boolean; items: string[] } | null = null;
  let para: string[] = [];
  const flushPara = () => { if (para.length) { blocks.push(<p key={blocks.length}>{inline(para.join(" "))}</p>); para = []; } };
  const flushList = () => {
    if (!list) return;
    const items = list.items.map((it, k) => <li key={k}>{inline(it)}</li>);
    blocks.push(list.ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    list = null;
  };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const m = /^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/.exec(line);
    const h = /^\s*(#{1,4})\s+(.*)$/.exec(line);
    if (m) {
      flushPara();
      const ordered = !!m[1];
      if (!list || list.ordered !== ordered) { flushList(); list = { ordered, items: [] }; }
      list.items.push(m[2]);
    } else if (h) {
      flushPara(); flushList();
      blocks.push(<p key={blocks.length}><b>{inline(h[2])}</b></p>);
    } else if (!line.trim()) {
      flushPara(); flushList();
    } else {
      if (list) flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return <div className="md">{blocks}</div>;
}

function inline(s: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|\*[^*\n]+\*)/g;
  let last = 0, k = 0;
  for (let m = re.exec(s); m; m = re.exec(s)) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**")) out.push(<b key={k++}>{t.slice(2, -2)}</b>);
    else if (t.startsWith("`")) out.push(<code key={k++}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(t);
      const href = lm?.[2] || "";
      // 사이트 안 경로(/notes…)와 http(s)만 링크로. '//evil.com'·'/\evil.com' 처럼 다른 사이트로 가는 경로는 막는다
      const internal = /^\/(?![/\\])/.test(href);
      const safe = internal || /^https?:\/\//i.test(href);
      out.push(safe ? <a key={k++} href={href} target={internal ? "_self" : "_blank"} rel="noopener noreferrer">{lm?.[1]}</a> : lm?.[1]);
    } else out.push(<i key={k++}>{t.slice(1, -1)}</i>);
    last = m.index + t.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
