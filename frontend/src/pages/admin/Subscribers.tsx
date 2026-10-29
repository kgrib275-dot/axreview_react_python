// 구독·발송 — 구독자 / 뉴스레터 / 월 구독 / Teams / 문의 (app_pages/admin/subscribers.py).
import { useEffect, useState } from "react";
import { Alert, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, CsvButton, DataTable, Expander, Field, Generic, Row, asArray, bool, isObj, num, pick, str, today, useAct } from "./common";
import { JobStatus, RunLogTable, StartJob, useJobs } from "./JobRunner";

const SECTIONS = ["구독자", "뉴스레터", "월 구독", "Teams", "문의"];
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function SubscribersTab() {
  const { data, error, reload } = useLoad(() => A.get<unknown>("subscribers"), []);
  const act = useAct();
  const subs = asArray(data, "subscribers", "items");
  const pending = isObj(data) ? asArray(pick(data, "pending", "pending_confirmations")) : [];
  const counts = isObj(data) && isObj(data.counts) ? (data.counts as Row) : isObj(data) && isObj(data.referral) ? (data.referral as Row) : {};
  const smtp = isObj(data) ? pick(data, "smtp_ok", "smtp_configured") : undefined;
  const [q, setQ] = useState("");
  const [email, setEmail] = useState("");
  const [active, setActive] = useState<Record<string, boolean>>({});
  useEffect(() => setActive(Object.fromEntries(subs.map((s) => [str(s.email), bool(s.active)]))), [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const byCode: Record<string, number> = {};
  subs.forEach((s) => { const r = str(s.referred_by); if (r) byCode[r] = (byCode[r] || 0) + 1; });
  const view = subs.filter((s) => !q.trim() || str(s.email).toLowerCase().includes(q.trim().toLowerCase())).map((s) => ({
    이메일: str(s.email), 구독일: str(s.created_at).slice(0, 19).replace("T", " "), 활성: str(s.email), 업종: Array.isArray(s.industries) ? s.industries.join(", ") : str(s.industries),
    확인: !!s.confirmed_at || bool(s.confirmed), "추천 수": num(pick(s, "referrals", "referral_count")) || byCode[str(s.ref_code)] || 0,
  }));
  const csvRows = subs.map((s) => { const { token, ...rest } = s; void token; return rest; });
  const activeCount = Object.values(active).filter(Boolean).length;
  return (
    <div>
      {error && <Alert kind="err">{error}</Alert>}
      {pending.length > 0 && (
        <div className="list-row">
          <b className="grow">확인 대기 {pending.length}명 — 확인 메일의 링크를 눌러야 발송 대상이 됩니다. 7일이 지나면 자동 삭제됩니다.</b>
          <button className="btn sm" disabled={smtp === false} title={smtp === false ? ".env에 SMTP를 설정하면 보낼 수 있습니다" : undefined} onClick={async () => {
            const r = await act(() => A.post<Row>("subscribers/confirm-mails"));
            if (r) act(async () => undefined, `${str(pick(r, "sent", "ok"))}/${str(pick(r, "total", "pending")) || pending.length}명에게 보냈습니다.`);
          }}>📨 확인 메일 보내기</button>
        </div>
      )}
      <p className="caption">
        전체 {subs.length} · 활성 {activeCount} · 추천으로 구독 {num(counts.referred)} · 보상({str(counts.reward_at) || "?"}명) 달성 {num(counts.rewarded)}
      </p>
      <Field label="이메일 찾기"><input type="text" placeholder="일부만 입력해도 됩니다" value={q} onChange={(e) => setQ(e.target.value)} /></Field>
      <DataTable rows={view} cols={["이메일", "구독일", "활성", "업종", "추천 수", "확인"]} tall
        render={{ 활성: (v) => <input type="checkbox" checked={!!active[str(v)]} onChange={(e) => setActive({ ...active, [str(v)]: e.target.checked })} /> }} />
      <div className="btn-row" style={{ margin: "10px 0" }}>
        <button className="btn primary" onClick={async () => {
          const changed = subs.filter((s) => active[str(s.email)] !== undefined && active[str(s.email)] !== bool(s.active));
          await act(async () => { for (const s of changed) await A.put(`subscribers/${encodeURIComponent(str(s.email))}`, { active: active[str(s.email)] }); }, `저장했습니다. (${changed.length}명 변경)`);
          reload();
        }}>💾 활성 상태 저장</button>
        <CsvButton name="subscribers.csv" rows={csvRows} />
      </div>
      <div className="inline">
        <Field label="구독자 직접 추가"><input type="text" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <button className="btn" onClick={async () => {
          if (!EMAIL_RE.test(email.trim())) return act(async () => { throw new Error("이메일 형식을 확인해 주세요."); });
          await act(() => A.post("subscribers", { email: email.trim() }), "추가했습니다.");
          setEmail(""); reload();
        }}>추가</button>
      </div>
    </div>
  );
}

function NewsletterTab() {
  const { finished } = useJobs();
  const { data, error } = useLoad(() => A.get<Row>("newsletter"), [finished]);
  const act = useAct();
  const d = data || {};
  const smtp = isObj(d.smtp) ? (d.smtp as Row) : {};
  const configured = pick(d, "smtp_ok", "configured") !== undefined ? bool(pick(d, "smtp_ok", "configured")) : bool(smtp.configured);
  const [to, setTo] = useState("");
  const html = str(pick(d, "html", "preview", "preview_html"));
  const history = asArray(pick(d, "history", "newsletters", "sent"));
  return (
    <div>
      {error && <Alert kind="err">{error}</Alert>}
      {configured ? (
        <Alert kind="ok">✉ SMTP {str(smtp.host)}:{str(smtp.port)} ({str(smtp.tls)}) · 발신 {str(smtp.sender)}</Alert>
      ) : (
        <Alert kind="warn"><b>SMTP 미설정</b> — .env에 SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TLS(starttls/ssl/none)를 넣으면 발송할 수 있습니다. 메일 링크 주소는 SITE_URL을 씁니다.</Alert>
      )}
      <p><b>다음 발송 제목</b> · {str(d.subject)}<br /><span className="caption">새 노트 {Array.isArray(d.notes) ? d.notes.length : num(pick(d, "notes", "note_count"))}편 · 활성 구독자 {num(pick(d, "subscribers", "recipients") ?? pick(isObj(d.counts) ? d.counts : {}, "subscribers"))}명</span></p>
      <div className="inline" style={{ marginBottom: 10 }}>
        <Field label="테스트 수신 주소"><input type="text" placeholder="me@company.com" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
        <button className="btn" disabled={!configured || !to.trim()} onClick={() => act(() => A.post("newsletter/test", { to: to.trim() }), `${to.trim()}로 보냈습니다.`)}>📨 테스트 발송</button>
        <StartJob kind="newsletter" text="전체 발송" primary disabled={!configured} />
      </div>
      <JobStatus only={["newsletter"]} />
      <Expander title="메일 미리보기" open>
        {html ? <iframe className="adm-frame" title="메일 미리보기" srcDoc={html} style={{ height: 720 }} /> : <p className="caption">미리보기가 없습니다.</p>}
      </Expander>
      <h3 style={{ margin: "16px 0 8px" }}>발송 기록</h3>
      <DataTable rows={history} cols={history.length ? ["sent_at", "subject", "recipients", "failed", "trigger"].filter((c) => c in history[0]) : undefined} />
    </div>
  );
}

function MembersTab() {
  const { data, error, reload } = useLoad(() => A.get<unknown>("members"), []);
  const act = useAct();
  const members = asArray(data, "members", "items");
  const [f, setF] = useState({ email: "", months: 1, memo: "" });
  const [issued, setIssued] = useState<{ who: string; code: string } | null>(null);
  const t = today();
  return (
    <div>
      <p className="caption">AX 질문하기 추가 이용권. 결제는 사이트 밖에서 확인하고, 여기서 코드를 발급해 신청자에게 메일로 보냅니다. 신청은 '문의'에 [월 구독 신청]으로 들어옵니다. 코드는 발급 직후 한 번만 보입니다.</p>
      {error && <Alert kind="err">{error}</Alert>}
      <div className="inline" style={{ margin: "10px 0" }}>
        <Field label="이메일"><input type="text" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="개월" className="narrow"><input type="number" min={1} max={12} value={f.months} style={{ width: 80 }} onChange={(e) => setF({ ...f, months: Number(e.target.value) })} /></Field>
        <Field label="메모 (결제 확인 등)"><input type="text" maxLength={200} value={f.memo} onChange={(e) => setF({ ...f, memo: e.target.value })} /></Field>
        <button className="btn primary" onClick={async () => {
          if (!EMAIL_RE.test(f.email.trim())) return act(async () => { throw new Error("이메일 형식을 확인해 주세요."); });
          const r = await act(() => A.post<Row>("members", { email: f.email.trim(), months: f.months, memo: f.memo }));
          if (r) { setIssued({ who: f.email.trim(), code: str(r.code) }); setF({ email: "", months: 1, memo: "" }); reload(); }
        }}>코드 발급</button>
      </div>
      {issued && (
        <Alert kind="ok">
          🔑 {issued.who} 코드 — 지금 복사해 보내 주세요. 다시 볼 수 없습니다.
          <div className="code-block" style={{ margin: "8px 0" }}>{issued.code}</div>
          <button className="btn sm" onClick={() => setIssued(null)}>확인했습니다</button>
        </Alert>
      )}
      {members.map((m) => {
        const expired = str(m.expires) < t;
        const state = !bool(m.active) ? "해지" : expired ? "만료" : "이용 중";
        return (
          <div key={str(m.id)} className="list-row">
            <div className="grow">
              <b>{str(m.email)}</b> · {state} · {str(m.expires)}까지 · 오늘 {num(pick(m, "used_today", "used"))}회
              {str(m.memo) && <div className="caption">{str(m.memo)}</div>}
            </div>
            <button className="btn sm" onClick={async () => { await act(() => A.post(`members/${m.id}/extend`, { months: 1 }), "1개월 연장했습니다."); reload(); }}>+1개월</button>
            <button className="btn sm" onClick={async () => { await act(() => A.put(`members/${m.id}`, { active: !bool(m.active) }), bool(m.active) ? "해지했습니다." : "다시 사용합니다."); reload(); }}>{bool(m.active) ? "해지" : "다시 사용"}</button>
          </div>
        );
      })}
      {!members.length && !error && <Alert kind="info">아직 월 구독자가 없습니다.</Alert>}
    </div>
  );
}

function TeamsTab() {
  const { finished } = useJobs();
  const hooks = useLoad(() => A.get<unknown>("webhooks"), []);
  const teams = useLoad(() => A.get<Row>("teams"), [finished]);
  const act = useAct();
  const list = asArray(hooks.data, "webhooks", "items");
  const [f, setF] = useState({ name: "", url: "" });
  const t = teams.data || {};
  const issue = isObj(t.issue) ? (t.issue as Row) : null;
  const noteCount = Array.isArray(t.notes) ? t.notes.length : num(pick(t, "notes", "note_count"));
  return (
    <div>
      <p className="caption">Teams 채널 &gt; 워크플로 &gt; '웹후크 요청을 받으면 채널에 게시' 템플릿으로 만든 URL을 등록하세요.</p>
      {hooks.error && <Alert kind="err">{hooks.error}</Alert>}
      {list.map((w) => {
        const on = w.enabled === undefined ? true : bool(w.enabled);
        return (
          <div key={str(w.id)} className="list-row">
            <div className="grow"><b>{str(w.name)}</b><br /><code>{str(w.url).slice(0, 60)}…</code></div>
            <label className="chk"><input type="checkbox" checked={on} onChange={async (e) => { await act(() => A.put(`webhooks/${w.id}`, { enabled: e.target.checked }), "저장했습니다."); hooks.reload(); }} />사용</label>
            <button className="btn sm" onClick={async () => { const r = await act(() => A.post<Row>(`webhooks/${w.id}/test`)); if (r) act(async () => { if (r.ok === false) throw new Error(`${str(w.name)}: ${str(pick(r, "msg", "message"))}`); }, `${str(w.name)}: ${str(pick(r, "msg", "message")) || "보냈습니다"}`); }}>📨 테스트</button>
            <button className="btn sm" onClick={async () => { if (!window.confirm(`'${str(w.name)}' 웹훅을 삭제할까요?`)) return; await act(() => A.del(`webhooks/${w.id}`), "삭제했습니다."); hooks.reload(); }}>🗑 삭제</button>
          </div>
        );
      })}
      <div className="inline" style={{ margin: "10px 0" }}>
        <Field label="채널 이름" className="narrow"><input type="text" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="웹훅 URL"><input type="text" value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></Field>
        <button className="btn" onClick={async () => {
          if (!(f.name.trim() && /^https:\/\/\S+$/.test(f.url.trim()))) return act(async () => { throw new Error("이름과 https:// 로 시작하는 URL을 입력하세요."); });
          await act(() => A.post("webhooks", { name: f.name.trim(), url: f.url.trim() }), "추가했습니다.");
          setF({ name: "", url: "" }); hooks.reload();
        }}>추가</button>
      </div>
      {teams.error && <Alert kind="err">{teams.error}</Alert>}
      <p><b>다음 발송 내용</b> · {issue ? `${str(issue.week)} 주간 흐름 · ` : ""}새 노트 {noteCount}편 (지난 Teams 발송 이후)</p>
      <StartJob kind="teams" text="지금 Teams로 발송" primary disabled={!list.length} />
      <JobStatus only={["teams"]} />
      <Expander title="카드 JSON 미리보기">
        {t.card !== undefined ? <pre className="code">{JSON.stringify(t.card, null, 2)}</pre> : <Generic value={t} />}
      </Expander>
      <h3 style={{ margin: "16px 0 8px" }}>Teams 발송 기록</h3>
      <RunLogTable kind="teams" limit={20} />
    </div>
  );
}

function ContactsTab() {
  const { data, error } = useLoad(() => A.get<unknown>("contacts"), []);
  const rows = asArray(data, "contacts", "items");
  return (
    <div>
      {error && <Alert kind="err">{error}</Alert>}
      <DataTable rows={rows} cols={rows.length ? ["created_at", "name", "email", "company", "message"].filter((c) => c in rows[0]) : undefined} />
    </div>
  );
}

export default function Subscribers() {
  const [sec, setSec] = useState(SECTIONS[0]);
  return (
    <div>
      <AdminHead title="구독·발송" />
      <Tabs items={SECTIONS} value={sec} onChange={setSec} />
      {sec === "구독자" && <SubscribersTab />}
      {sec === "뉴스레터" && <NewsletterTab />}
      {sec === "월 구독" && <MembersTab />}
      {sec === "Teams" && <TeamsTab />}
      {sec === "문의" && <ContactsTab />}
    </div>
  );
}
