// 개인정보 처리방침 — 기재사항 입력, 새 버전 공지(중요 변경·시행일·요약), 공지한 버전(시행 전 거두기), 스냅샷 미리보기 (app_pages/admin/privacy_settings.py).
import { useEffect, useState } from "react";
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Check, Expander, Field, Generic, Row, addDays, asArray, bool, isObj, num, pick, str, today, useAct } from "./common";

const FIELDS: [keyof Settings, string, string?][] = [
  ["operator", "개인정보처리자(운영자) 명칭 *", "예) OO팀 AX Review 운영"],
  ["officer_name", "개인정보 보호책임자 성명 또는 직책 *"], ["officer_dept", "보호책임자 부서"],
  ["officer_email", "보호책임자 이메일 *"], ["officer_phone", "보호책임자 전화 (선택)"],
  ["request_dept", "열람청구 접수·처리 부서 (비우면 보호책임자와 같음)"],
  ["smtp_vendor", "메일 발송 위탁 업체 (SMTP)", "예) Microsoft 365, 사내 메일 서버"], ["smtp_country", "메일 업체 처리 국가"], ["databricks_region", "Databricks 저장 지역(국가)"],
];
type Settings = { operator: string; officer_name: string; officer_dept: string; officer_email: string; officer_phone: string; request_dept: string; smtp_vendor: string; smtp_country: string; databricks_region: string; admin_measures: string };
const EMPTY: Settings = { operator: "", officer_name: "", officer_dept: "", officer_email: "", officer_phone: "", request_dept: "", smtp_vendor: "", smtp_country: "", databricks_region: "", admin_measures: "" };

export default function PrivacySettings() {
  const { data, error, reload } = useLoad(() => A.get<Row>("privacy"), []);
  const act = useAct();
  const d = data || {};
  const versions = asArray(pick(d, "versions"));
  const missing = asArray<string>(pick(d, "missing", "need")).map(String);
  const current = isObj(d.current) ? (d.current as Row) : null;
  const upcoming = asArray(pick(d, "upcoming"));
  const outdated = bool(pick(d, "outdated"));
  const noticeDays = num(pick(d, "notice_days"), 7);
  const majorDays = num(pick(d, "major_notice_days"), 30);
  const first = versions.length === 0;
  const [s, setS] = useState<Settings>(EMPTY);
  useEffect(() => {
    const src = isObj(d.settings) ? (d.settings as Row) : {};
    setS({ ...EMPTY, ...Object.fromEntries(Object.keys(EMPTY).map((k) => [k, str(src[k])])) } as Settings);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps
  const [pub, setPub] = useState({ major: false, eff: today(), summary: "" });
  useEffect(() => setPub({ major: false, eff: first ? today() : addDays(today(), noticeDays), summary: first ? "개인정보 처리방침 제정" : "" }), [first, noticeDays]);

  return (
    <div>
      <AdminHead title="개인정보 처리방침" note="개인정보 보호법 제30조 기재사항 중 운영자가 정하는 값을 넣고, 버전을 공지합니다. 처리 항목·보유 기간·위탁·국외 이전은 켜져 있는 기능에서 자동으로 만들어집니다. 시행 전 담당 부서(법무·개인정보) 검토를 받으세요." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="지금 시행 중" v={current ? str(current.effective_date) : "없음"} />
        <Metric k="시행 예정" v={upcoming.length || versions.filter((v) => str(v.status) === "시행 예정").length} />
        <Metric k="공지한 버전" v={versions.length} />
      </div>
      {missing.length ? <Alert kind="err">⚖ 비어 있는 필수 기재사항: {missing.join(", ")}</Alert>
        : first ? <Alert kind="warn">📢 아직 공지한 처리방침이 없습니다 — 아래 '새 버전 공지'로 첫 처리방침을 게시하세요 (첫 게시는 오늘 바로 시행 가능).</Alert>
        : outdated ? <Alert kind="warn">📢 기능·설정이 가장 최근 공지와 다릅니다 (예: SMTP·Databricks를 켬, 위탁 업체 변경) — 새 버전을 공지하세요.</Alert>
        : <Alert kind="ok">✓ 가장 최근 공지가 지금 기능·설정과 같습니다.</Alert>}

      <h3>1. 기재사항</h3>
      <Field label={FIELDS[0][1]}><input type="text" maxLength={100} placeholder={FIELDS[0][2]} value={s.operator} onChange={(e) => setS({ ...s, operator: e.target.value })} /></Field>
      <div className="row2">
        {FIELDS.slice(1, 5).map(([k, l, p]) => <Field key={k} label={l}><input type="text" maxLength={120} placeholder={p} value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })} /></Field>)}
      </div>
      <Field label={FIELDS[5][1]}><input type="text" maxLength={100} value={s.request_dept} onChange={(e) => setS({ ...s, request_dept: e.target.value })} /></Field>
      <div className="row3">
        {FIELDS.slice(6).map(([k, l, p]) => <Field key={k} label={l}><input type="text" maxLength={80} placeholder={p} value={s[k]} onChange={(e) => setS({ ...s, [k]: e.target.value })} /></Field>)}
      </div>
      <Field label="관리적 보호조치 (실제로 하는 것만 — 예: 내부관리계획 수립, 취급자 교육)"><textarea rows={3} maxLength={500} value={s.admin_measures} onChange={(e) => setS({ ...s, admin_measures: e.target.value })} /></Field>
      <button className="btn primary" onClick={async () => {
        const body = Object.fromEntries(Object.entries(s).map(([k, v]) => [k, v.trim()]));
        body.smtp_country = body.smtp_country || "대한민국";
        body.databricks_region = body.databricks_region || "미국";
        await act(() => A.put("privacy", body), "저장했습니다. 공개 화면에 반영하려면 새 버전을 공지하세요.");
        reload();
      }}>저장</button>

      <h3 style={{ marginTop: 22 }}>2. 새 버전 공지</h3>
      <p className="caption">공지하면 지금 내용이 이 버전으로 고정됩니다. {first ? "첫 게시는 오늘 바로 시행할 수 있습니다." : `시행일은 공지일로부터 ${noticeDays}일 뒤(정보주체 권리에 중요한 변경은 ${majorDays}일 뒤) 이후로 정하세요.`}</p>
      <div className="row2">
        <div>
          <Check label="중요한 변경 (수집 항목 추가·목적 변경·제3자 제공·국외 이전 추가 등)" checked={pub.major} disabled={first} onChange={(v) => setPub({ ...pub, major: v })} />
          <div style={{ height: 8 }} />
          <Field label="시행일"><input type="date" min={today()} value={pub.eff} onChange={(e) => setPub({ ...pub, eff: e.target.value })} /></Field>
        </div>
        <Field label="변경 요약 (공개 화면 공지·버전 선택에 표시)"><input type="text" maxLength={200} value={pub.summary} onChange={(e) => setPub({ ...pub, summary: e.target.value })} /></Field>
      </div>
      <button className="btn primary" disabled={missing.length > 0 || !pub.eff} onClick={async () => {
        await act(() => A.post("privacy/publish", { effective_date: pub.eff, summary: pub.summary.trim(), major: pub.major }), "공지했습니다.");
        reload();
      }}>이 내용으로 공지</button>

      <h3 style={{ marginTop: 22 }}>3. 공지한 버전</h3>
      {first && <p className="caption">아직 없습니다.</p>}
      {versions.map((v) => (
        <div key={str(v.id)} className="list-row">
          <div className="grow">
            <b>{str(v.effective_date)} 시행</b> · {str(v.status)} · 공지 {str(v.announced_at).replace("T", " ").slice(0, 19)}
            {str(v.summary) && <div className="caption">{str(v.summary)}</div>}
          </div>
          {str(v.status) === "시행 예정" && (
            <button className="btn sm" onClick={async () => { if (!window.confirm("이 공지를 거둘까요?")) return; await act(() => A.del(`privacy/versions/${v.id}`), "공지를 거뒀습니다."); reload(); }}>↩ 공지 거두기</button>
          )}
        </div>
      ))}

      <Expander title="지금 공지하면 게시될 내용 미리 보기">
        {d.snapshot !== undefined ? <Generic value={d.snapshot} /> : <p className="caption">스냅샷이 없습니다.</p>}
      </Expander>
    </div>
  );
}
