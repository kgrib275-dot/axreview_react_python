// 구독·문의·월 구독 신청 대화상자 + 열기 함수를 주는 컨텍스트 (Layout 이 감싼다).
// 수집 시점 고지(항목·목적·보유·거부권)와 만 14세 동의는 Streamlit 판 app/dialogs.py 와 같다.
import { createContext, useCallback, useContext, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, post, track } from "../api";
import { useMe } from "../me";
import { Alert, Dialog } from "./ui";

export const INDUSTRIES = ["제조", "컨택센터", "금융", "유통·커머스", "공공", "의료·헬스케어"];
const BENEFITS: [string, string, string][] = [
  ["🗓️", "매주 월요일 3분", "한 주의 AX 흐름을 한 줄 헤드라인과 노트 5편으로"],
  ["🧭", "실행까지", "요약에서 끝나지 않고 현업 실행 단계·적용 점검 포인트"],
  ["📎", "주간 PDF 리포트", "회의 자료로 바로 쓰는 정사각 카드 리포트 링크"],
];

type Ctx = { openSubscribe: (source: string) => void; openContact: () => void; openMembership: () => void };
const DlgCtx = createContext<Ctx>({ openSubscribe: () => undefined, openContact: () => undefined, openMembership: () => undefined });
export const useDialogs = () => useContext(DlgCtx);

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const [sub, setSub] = useState<string | null>(null);
  const [contact, setContact] = useState(false);
  const [member, setMember] = useState(false);
  const openSubscribe = useCallback((source: string) => {
    track("subscribe_open", source);
    setSub(source);
  }, []);
  const openContact = useCallback(() => setContact(true), []);
  const openMembership = useCallback(() => {
    track("member_request_open");
    setMember(true);
  }, []);
  return (
    <DlgCtx.Provider value={{ openSubscribe, openContact, openMembership }}>
      {children}
      {sub && <SubscribeDialog source={sub} onClose={() => setSub(null)} />}
      {contact && <ContactDialog onClose={() => setContact(false)} />}
      {member && <MembershipDialog onClose={() => setMember(false)} />}
    </DlgCtx.Provider>
  );
}

function SubscribeDialog({ source, onClose }: { source: string; onClose: () => void }) {
  const { state, setState } = useMe();
  const [email, setEmail] = useState("");
  const [inds, setInds] = useState<string[]>([]);
  const [agree, setAgree] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agree) return setMsg({ kind: "err", text: "만 14세 이상이며 개인정보 수집·이용에 동의해야 구독할 수 있습니다." });
    setBusy(true);
    try {
      const r = await post<{ message: string }>("subscribe", { email: email.trim(), industries: inds, agree, source, ref: state.ref || "" });
      setMsg({ kind: "ok", text: r.message });
      setState({ subscribed: true, pref_inds: inds });
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog title="매주 한 호, 메일로 받아 보세요" onClose={onClose}>
      <div style={{ display: "grid", gap: 8, margin: "2px 0 8px" }}>
        {BENEFITS.map(([i, t, d]) => (
          <div key={t} style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
            <span style={{ fontSize: "1.2rem" }}>{i}</span>
            <div><b style={{ fontSize: ".92rem" }}>{t}</b><div className="caption">{d}</div></div>
          </div>
        ))}
      </div>
      <Link to="/letter" onClick={onClose} className="more">✉ 받게 될 메일 미리 보기 →</Link>
      <form onSubmit={submit} style={{ marginTop: 12 }}>
        <div className="field"><label>이메일</label><input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" maxLength={254} /></div>
        <div className="field">
          <label>우리 업종 사례를 먼저 받기 (선택)</label>
          <div className="btn-row">
            {INDUSTRIES.map((n) => (
              <button type="button" key={n} className={`pill ${inds.includes(n) ? "on" : ""}`} onClick={() => setInds((s) => (s.includes(n) ? s.filter((x) => x !== n) : [...s, n]))}>{n}</button>
            ))}
          </div>
        </div>
        <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이메일(필수), 관심 업종(선택) · 목적: 주간 뉴스레터 발송·구독 확인 · 보유: 구독 해지 시까지(해지 후 30일 이내 파기) · 동의를 거부할 수 있으며, 거부하면 구독할 수 없습니다. 메일은 발송 업체에 위탁해 보냅니다. <Link to="/privacy" onClick={onClose}>개인정보 처리방침</Link></p>
        <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> 만 14세 이상이며 개인정보 수집·이용에 동의합니다 (필수)</label>
        <button className="btn primary block" style={{ marginTop: 12 }} disabled={busy}>무료로 구독하기 →</button>
      </form>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </Dialog>
  );
}

function ContactDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ name: "", email: "", company: "", message: "", agree: false });
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await post("contact", f);
      setMsg({ kind: "ok", text: "문의가 접수됐습니다. 확인 후 답장 드리겠습니다." });
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    }
  };
  return (
    <Dialog title="AX 담당자에게 문의하기" onClose={onClose} wide>
      <p className="caption">AX 전략, 데이터·온톨로지 기반 의사결정, 현장 적용에 대한 문의를 남겨 주세요. 확인 후 답장 드립니다.</p>
      <form onSubmit={submit}>
        <div className="row2">
          <div className="field"><label>이름</label><input type="text" required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="field"><label>이메일</label><input type="email" required maxLength={254} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        </div>
        <div className="field"><label>부서 · 직책 (선택)</label><input type="text" maxLength={100} value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></div>
        <div className="field"><label>내용</label><textarea required rows={5} maxLength={5000} value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></div>
        <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이름·이메일·문의 내용(필수), 부서·직책(선택) · 목적: 문의 확인 및 답변 · 보유: 접수 후 12개월 · 동의를 거부할 수 있으며, 거부하면 문의를 접수할 수 없습니다. <Link to="/privacy" onClick={onClose}>개인정보 처리방침</Link></p>
        <label className="check"><input type="checkbox" checked={f.agree} onChange={(e) => setF({ ...f, agree: e.target.checked })} /> 만 14세 이상이며 개인정보 수집·이용에 동의합니다 (필수)</label>
        <button className="btn primary block" style={{ marginTop: 12 }}>보내기 →</button>
      </form>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </Dialog>
  );
}

function MembershipDialog({ onClose }: { onClose: () => void }) {
  const [f, setF] = useState({ name: "", email: "", company: "", agree: false });
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await post("membership/request", f);
      setMsg({ kind: "ok", text: "신청이 접수됐습니다. 담당자가 메일로 안내해 드릴게요." });
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    }
  };
  return (
    <Dialog title="AX 질문하기 월 구독 신청" onClose={onClose}>
      <ul style={{ margin: "0 0 10px", paddingLeft: 18, color: "var(--ink-2)", fontSize: ".9rem" }}>
        <li>하루 <b>30회</b>까지 질문 (무료는 3회)</li>
        <li>기간: 30일 · 가격·결제 방법은 담당자가 메일로 안내</li>
        <li>결제 확인 후 <b>구독 코드</b>를 메일로 보내 드리면, 질문하기 화면에 넣어 바로 씁니다</li>
      </ul>
      <form onSubmit={submit}>
        <div className="row2">
          <div className="field"><label>이름</label><input type="text" required maxLength={100} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></div>
          <div className="field"><label>이메일</label><input type="email" required maxLength={254} value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></div>
        </div>
        <div className="field"><label>부서 · 직책 (선택)</label><input type="text" maxLength={100} value={f.company} onChange={(e) => setF({ ...f, company: e.target.value })} /></div>
        <p className="caption"><b>개인정보 수집·이용 안내</b> · 항목: 이름·이메일(필수), 부서·직책(선택) · 목적: 월 구독 안내·구독 코드 발송 · 보유: 신청 정보 12개월, 이용 정보 종료 후 6개월 · 동의를 거부할 수 있으며, 거부하면 신청할 수 없습니다. <Link to="/privacy" onClick={onClose}>개인정보 처리방침</Link></p>
        <label className="check"><input type="checkbox" checked={f.agree} onChange={(e) => setF({ ...f, agree: e.target.checked })} /> 만 14세 이상이며 개인정보 수집·이용에 동의합니다 (필수)</label>
        <button className="btn primary block" style={{ marginTop: 12 }}>신청하기 →</button>
      </form>
      {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
    </Dialog>
  );
}

/** 결과·콘텐츠 끝의 구독 유도 카드. */
export function SubscribeCTA({ source, headline, sub, button = "무료로 구독하기 →" }: { source: string; headline: string; sub: string; button?: string }) {
  const { state } = useMe();
  const { openSubscribe } = useDialogs();
  if (state.subscribed) return <Alert kind="ok">구독 중입니다. 다음 호에서 만나요!</Alert>;
  return (
    <div className="cta-card">
      <span className="ic">📬</span>
      <div><b>{headline}</b><small>{sub}</small></div>
      <button className="btn primary" onClick={() => openSubscribe(source)}>{button}</button>
    </div>
  );
}
