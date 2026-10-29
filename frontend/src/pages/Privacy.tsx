// 개인정보 처리방침 (/privacy) — Streamlit 판 app_pages/privacy.py + app/policy_view.py 이식.
// 버전은 ?v=시행일 과 맞추고, 13개 조항은 그 버전에 고정된 content(snapshot JSON)로만 그린다.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { del, get } from "../api";
import { useDialogs } from "../components/Dialogs";
import { Alert, useLoad } from "../components/ui";
import { useMe } from "../me";
import "./Home.css";

type Version = { id?: number; announced_at: string; effective_date: string; summary?: string; status: string };
type Row = Record<string, string | null | undefined>;
type Content = {
  settings?: { operator?: string; admin_measures?: string; officer_name?: string; officer_dept?: string; officer_email?: string; officer_phone?: string; request_dept?: string };
  retention?: unknown;
  records?: Row[];
  entrustments?: Row[];
  overseas?: Row[];
  backup_days?: number;
};
type Privacy = {
  active: boolean;
  versions?: Version[];
  current_date?: string | null;
  upcoming?: Version[];
  selected?: { effective_date: string; announced_at?: string | null; content: Content } | null;
  draft?: Content | null;
  // 관리자용 점검(계약 외, 있으면 보여 준다)
  missing?: string[];
  outdated?: boolean;
};

const BLANK = "(운영자가 입력할 예정)";

function PolicyTable({ rows, cols }: { rows?: Row[]; cols: [string, string][] }) {
  const list = rows || [];
  return (
    <div className="table-wrap" style={{ margin: "10px 0" }}>
      <table className="table">
        <thead><tr>{cols.map(([, l]) => <th key={l}>{l}</th>)}</tr></thead>
        <tbody>
          {list.length ? list.map((r, i) => (
            <tr key={i}>{cols.map(([k]) => <td key={k}>{r[k] || "없음"}</td>)}</tr>
          )) : <tr>{cols.map(([k]) => <td key={k}>없음</td>)}</tr>}
        </tbody>
      </table>
    </div>
  );
}

const H = ({ children }: { children: React.ReactNode }) => <h3 className="sub-h" style={{ fontSize: "1.1rem" }}>{children}</h3>;
const P = ({ children }: { children: React.ReactNode }) => <p className="sec-p" style={{ margin: "6px 0" }}>{children}</p>;
const UL = ({ children }: { children: React.ReactNode }) => <ul className="sec-p" style={{ margin: "6px 0", paddingLeft: 22 }}>{children}</ul>;

/** 처리방침 한 버전 — app/policy_view.render 와 같은 13개 조항. */
function PolicyView({ content, effective, announced }: { content: Content; effective: string; announced?: string | null }) {
  const s = content.settings || {};
  const operator = s.operator || "AX Review 운영자";
  const measures = [
    "관리 화면 접근 제한 — 서버가 있는 PC 또는 등록한 IP에서만 접근",
    "전송 구간 암호화(HTTPS), 서버는 외부에서 직접 접속할 수 없게 내부 주소에만 열어 둠",
    "구독 코드는 복원할 수 없는 해시로, IP 대체 식별값과 쿠키는 서버 비밀값으로 서명·해시 처리",
    "접속 기록 보관과 남용 시도 제한, 오류 화면에 내부 정보 비노출",
    "데이터 백업과 무결성 검사, 보유 기간이 지난 정보 자동 파기",
  ];
  if ((s.admin_measures || "").trim()) measures.unshift(s.admin_measures!.trim());
  const officer = [s.officer_name, s.officer_dept].filter(Boolean).join(" · ") || BLANK;
  const contact = [s.officer_email, s.officer_phone].filter(Boolean).join(" · ") || BLANK;

  return (
    <div className="policy">
      <p className="sec-p" style={{ maxWidth: 780 }}>
        {operator}(이하 '운영자')는 「개인정보 보호법」에 따라 AX Review(이하 '사이트') 이용자의 개인정보를 보호하고 관련 고충을 신속하게 처리하기 위해 다음과 같이 개인정보 처리방침을 둡니다.<br />
        <b>시행일: {effective}</b>{announced ? ` · 공지일: ${announced}` : ""}
      </p>

      <H>제1조 처리하는 개인정보의 항목, 처리 목적, 보유 기간</H>
      <P>운영자는 아래 목적으로만 개인정보를 처리하며, 목적이 바뀌면 별도 동의를 받는 등 필요한 조치를 합니다. 직접 입력하는 정보는 수집할 때 목적·항목·보유 기간과 거부할 권리를 알리고 동의를 받습니다.</P>
      <PolicyTable rows={content.records} cols={[["name", "처리 업무"], ["purpose", "처리 목적"], ["required", "필수 항목"], ["optional", "선택 항목"], ["auto", "자동 생성·수집 항목"], ["keep", "보유 기간"]]} />
      <p className="caption">민감정보·고유식별정보(주민등록번호 등)는 처리하지 않습니다. 결제는 사이트에서 처리하지 않습니다.</p>

      <H>제2조 개인정보의 파기 절차 및 방법</H>
      <UL>
        <li><b>절차</b>: 보유 기간이 지나거나 처리 목적을 이루면 지체 없이 파기합니다. 사이트가 매일 한 번 자동으로 기간이 지난 기록을 지웁니다.</li>
        <li><b>방법</b>: 전자 파일은 복구할 수 없도록 데이터베이스에서 삭제합니다. 장애 대비 백업본은 최대 {content.backup_days ?? 14}일 보관 후 순서대로 삭제되며, 분석용 사본(위탁처)은 다음 적재 때 함께 삭제됩니다. 종이 문서는 만들지 않습니다.</li>
        <li>다른 법령에 따라 보존해야 하는 경우에는 그 기간 동안 따로 분리해 보관합니다.</li>
      </UL>

      <H>제3조 개인정보의 제3자 제공</H>
      <P>운영자는 정보주체의 개인정보를 제3자에게 제공하지 않습니다. 다만 법령에 특별한 규정이 있는 경우에는 그에 따릅니다.</P>

      <H>제4조 개인정보 처리의 위탁</H>
      <P>운영자는 원활한 서비스 제공을 위해 아래와 같이 개인정보 처리 업무를 위탁합니다. 위탁 계약 시 개인정보가 안전하게 관리되도록 필요한 사항을 정하고 감독합니다. 수탁자나 업무가 바뀌면 이 처리방침으로 알립니다.</P>
      <PolicyTable rows={content.entrustments} cols={[["to", "수탁자"], ["work", "위탁 업무"]]} />

      <H>제5조 개인정보의 국외 이전</H>
      <P>위탁·보관을 위해 아래와 같이 개인정보가 국외로 이전됩니다 (「개인정보 보호법」 제28조의8).</P>
      <PolicyTable rows={content.overseas} cols={[["to", "이전받는 자"], ["country", "이전 국가"], ["items", "이전 항목"], ["when", "이전 시기·방법"], ["purpose", "이용 목적·보유 기간"], ["contact", "연락처(개인정보 문의)"], ["refuse", "거부 방법·거부 시 불이익"]]} />

      <H>제6조 정보주체와 법정대리인의 권리·의무 및 행사 방법</H>
      <UL>
        <li>정보주체는 언제든지 개인정보 <b>열람·정정·삭제·처리정지 요구 및 동의 철회</b>를 할 수 있습니다.</li>
        <li>요구는 제11조의 연락처나 이 페이지 아래 <b>'바로 하기'의 문의하기</b>로 할 수 있으며, 운영자는 <b>10일 이내</b>에 조치하고 결과를 알립니다. 법령에 따라 거절하거나 제한하는 경우 그 이유를 알립니다.</li>
        <li>바로 할 수 있는 방법: 구독 해지 = 메일 하단 '구독 해지' · 사이트 이용 기록 = 아래 <b>'내 기록 지우기'</b> · 통계 프로필 = 입력란의 '바꾸기'.</li>
        <li>법정대리인이나 위임을 받은 사람을 통해서도 행사할 수 있으며, 이 경우 위임장을 제출해야 합니다.</li>
        <li>정보주체는 자신의 개인정보를 정확하게 입력해야 하며, 다른 사람의 이메일 등을 입력해서는 안 됩니다.</li>
      </UL>

      <H>제7조 만 14세 미만 아동의 개인정보</H>
      <P>운영자는 만 14세 미만 아동의 개인정보를 받지 않습니다. 정보를 받을 때 만 14세 이상임을 확인하며, 만 14세 미만의 정보가 수집된 것을 알게 되면 즉시 파기합니다.</P>

      <H>제8조 개인정보의 안전성 확보 조치</H>
      <UL>{measures.map((m) => <li key={m}>{m}</li>)}</UL>

      <H>제9조 개인정보 자동 수집 장치(쿠키)의 설치·운영 및 거부</H>
      <UL>
        <li>사이트는 같은 방문자를 알아보기 위해 <b>쿠키(axv, 1년 — 방문할 때마다 연장)</b> 를 씁니다. 연속 참여 기록, 테스트·퀴즈 결과 유지, 이용 한도 계산에 쓰며 이름·이메일과 연결하지 않습니다. 북마크와 안내 띠 닫기 기록은 브라우저 저장소에만 남고 서버로 보내지 않습니다.</li>
        <li><b>거부 방법</b>: 브라우저 설정에서 쿠키를 차단하거나 삭제할 수 있습니다 (예: Chrome·Edge → 설정 → 개인정보 및 보안 → 쿠키 및 사이트 데이터).</li>
        <li><b>거부 시 불이익</b>: 연속 참여 기록과 결과 유지가 되지 않을 수 있으며, 그 밖의 이용에는 제한이 없습니다.</li>
        <li>공유 버튼(카카오톡·LinkedIn)과 번역(EN) 버튼은 누를 때만 해당 서비스로 연결되며, 화면 글꼴은 Google Fonts에서 받아 옵니다.</li>
      </UL>

      <H>제10조 자동화된 결정</H>
      <P>운영자는 정보주체에게 법적 효과나 중대한 영향을 미치는 자동화된 결정을 하지 않습니다. 사이트의 AI는 기사 선별·요약과 질문 답변에만 쓰입니다.</P>

      <H>제11조 개인정보 보호책임자 및 열람청구 접수 부서</H>
      <div className="table-wrap" style={{ margin: "10px 0" }}>
        <table className="table">
          <thead><tr><th>구분</th><th>내용</th></tr></thead>
          <tbody>
            <tr><td>개인정보 보호책임자</td><td>{officer}</td></tr>
            <tr><td>연락처</td><td>{contact}</td></tr>
            <tr><td>열람청구 접수·처리 부서</td><td>{s.request_dept || officer}</td></tr>
          </tbody>
        </table>
      </div>
      <P>개인정보 관련 문의·불만·피해 구제는 위 보호책임자에게 하실 수 있으며, 지체 없이 답변·처리합니다.</P>

      <H>제12조 권익침해 구제 방법</H>
      <P>개인정보 침해로 인한 구제를 받으려면 아래 기관에 분쟁 해결이나 상담을 신청할 수 있습니다.</P>
      <UL>
        <li>개인정보분쟁조정위원회: (국번 없이) 1833-6972 · www.kopico.go.kr</li>
        <li>개인정보침해신고센터(한국인터넷진흥원): (국번 없이) 118 · privacy.kisa.or.kr</li>
        <li>대검찰청: (국번 없이) 1301 · www.spo.go.kr</li>
        <li>경찰청: (국번 없이) 182 · ecrm.police.go.kr</li>
      </UL>

      <H>제13조 개인정보 처리방침의 변경</H>
      <P>이 개인정보 처리방침은 <b>{effective}</b>부터 적용됩니다. 내용이 바뀌면 시행 7일 전(정보주체 권리에 중요한 변경은 30일 전)부터 이 페이지에 공지합니다. 이전 처리방침은 페이지 위의 <b>버전 선택</b>에서 볼 수 있습니다.</P>
    </div>
  );
}

export default function PrivacyPage() {
  const { me, reload } = useMe();
  const { openContact } = useDialogs();
  const [params, setParams] = useSearchParams();
  const want = params.get("v") || "";
  const { data, error, loading } = useLoad(() => get<Privacy>(`privacy${want ? `?v=${encodeURIComponent(want)}` : ""}`), [want]);
  const [erased, setErased] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  if (error) return <Alert kind="err">{error}</Alert>;
  if (loading && !data) return <div className="page-loading">불러오는 중…</div>;
  if (!data) return null;
  if (!data.active) return <Alert kind="info">이 사이트는 개인정보를 처리하지 않습니다.</Alert>;

  const vs = data.versions || [];
  const cur = data.current_date || (vs.length ? vs[vs.length - 1].effective_date : "");
  const selected = data.selected;
  const pick = selected?.effective_date || cur;
  const label = (v: Version) => `${v.effective_date} 시행 · ${v.status}${v.summary ? ` · ${v.summary}` : ""}`;
  const picked = vs.find((v) => v.effective_date === pick);

  const choose = (d: string) => {
    const p = new URLSearchParams(params);
    if (d !== cur) p.set("v", d); else p.delete("v"); // 이 버전으로 바로 오는 주소
    setParams(p, { replace: true });
  };

  const erase = async () => {
    setBusy(true);
    try {
      const r = await del<{ erased: number }>("me");
      setErased(r?.erased ?? 0);
      await reload(); // 새 방문자 값·쿠키로 다시 시작
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="eyebrow">개인정보 처리방침</div>
      <h2 className="sec-h">개인정보 <span className="grad">처리방침</span></h2>

      {me?.is_admin && data.missing?.length ? (
        <Alert kind="err">필수 기재사항이 비어 있습니다: {data.missing.join(", ")} — 관리 &gt; 개인정보 처리방침</Alert>
      ) : me?.is_admin && !vs.length ? (
        <Alert kind="warn">아직 공지한 처리방침이 없어 지금 기능으로 만든 초안을 보여 줍니다 — 관리 &gt; 개인정보 처리방침에서 공지하세요.</Alert>
      ) : me?.is_admin && data.outdated ? (
        <Alert kind="warn">기능·설정이 가장 최근 공지와 다릅니다 — 새 버전을 공지하세요 (관리 &gt; 개인정보 처리방침).</Alert>
      ) : null}

      {[...(data.upcoming || [])].reverse().map((v) => (
        <Alert key={v.effective_date} kind="info">
          📣 <b>개인정보 처리방침 변경 공지</b> · {v.effective_date}부터 새 처리방침이 시행됩니다 (공지 {v.announced_at}){v.summary ? ` — ${v.summary}` : ""}. 아래 '버전 선택'에서 미리 볼 수 있습니다.
        </Alert>
      ))}

      {vs.length ? (
        <>
          <div className="field" style={{ maxWidth: 560, marginTop: 10 }}>
            <label htmlFor="policy-ver">버전 선택</label>
            <select id="policy-ver" value={pick} onChange={(e) => choose(e.target.value)}>
              {vs.map((v) => <option key={v.effective_date} value={v.effective_date}>{label(v)}</option>)}
            </select>
          </div>
          {picked && picked.status !== "시행 중" && (
            <p className="caption">지금 보는 것은 <b>{picked.status}</b> 버전입니다. 지금 시행 중인 처리방침은 {cur} 시행본입니다.</p>
          )}
          {selected && <PolicyView content={selected.content || {}} effective={selected.effective_date} announced={selected.announced_at} />}
        </>
      ) : (
        <PolicyView content={data.draft || selected?.content || {}} effective="공지 예정" />
      )}

      <h3 className="sub-h">바로 하기</h3>
      <div className="cols2">
        <div>
          {erased !== null ? (
            <Alert kind="ok">🗑 {erased}건을 지웠습니다. 새 방문자로 다시 시작합니다.</Alert>
          ) : (
            <button className="btn" onClick={erase} disabled={busy}>🗑 내 기록 지우기 (이 브라우저의 참여 기록·통계 프로필·화면 설정값)</button>
          )}
        </div>
        <div>
          <button className="btn" onClick={openContact}>✉ 문의하기 (열람·정정·삭제·처리정지 요구)</button>
        </div>
      </div>
    </>
  );
}
