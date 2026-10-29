// 관리자·접속 — 관리자 IP 추가/삭제, 접속 기록(관리 작업·질문하기·페이지 조회·전체), 관리자 행동 기록 (app_pages/admin/access.py).
import { useEffect, useState } from "react";
import { Alert, Metric, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, DataTable, Field, Row, asArray, isObj, pick, str, useAct } from "./common";

const VIEWS = ["관리 작업", "질문하기", "페이지 조회", "전체"];

export default function Access() {
  const ips = useLoad(() => A.get<unknown>("admin-ips"), []);
  const logs = useLoad(() => A.get<unknown>("access-logs?limit=2000"), []);
  const actions = useLoad(() => A.get<unknown>("actions"), []);
  const act = useAct();
  const list = asArray(ips.data, "ips", "admin_ips", "items");
  const myIp = isObj(ips.data) ? str(pick(ips.data, "my_ip", "client_ip")) : "";
  const [f, setF] = useState({ label: "", ip: "" });
  useEffect(() => { if (myIp && !f.ip) setF((x) => ({ ...x, ip: myIp })); }, [myIp]); // eslint-disable-line react-hooks/exhaustive-deps
  const [view, setView] = useState(VIEWS[0]);
  const all = asArray(logs.data, "logs", "items");
  const rows = all.filter((r) => {
    const a = str(r.action);
    return view === "전체" || (view === "관리 작업" ? !["view", "ask"].includes(a) : view === "질문하기" ? a === "ask" : a === "view");
  });
  const actionRows = asArray(actions.data, "actions", "items");

  return (
    <div>
      <AdminHead title="관리자·접속" note="이 PC에서 localhost로 접속하면 항상 관리자입니다. 공개 주소·원격 접속은 IP를 등록해야 관리 메뉴가 보입니다." />
      <h3>관리자 IP</h3>
      <p className="caption">내 IP: {myIp || "로컬"} · 공개 주소(Funnel)로 접속할 때는 이 IP를 등록해야 관리 메뉴가 보입니다.</p>
      {ips.error && <Alert kind="err">{ips.error}</Alert>}
      {list.map((a) => (
        <div key={str(a.id)} className="list-row">
          <div className="grow"><b>{str(a.label)}</b> · <code>{str(a.ip)}</code></div>
          <button className="btn sm" onClick={async () => {
            if (!window.confirm(`${str(a.label)} (${str(a.ip)}) 를 삭제할까요?`)) return;
            await act(() => A.del(`admin-ips/${a.id}`).catch(() => A.del("admin-ips", { id: a.id })), "삭제했습니다.");
            ips.reload();
          }}>🗑 삭제</button>
        </div>
      ))}
      <div className="inline" style={{ margin: "10px 0 20px" }}>
        <Field label="이름"><input type="text" value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} /></Field>
        <Field label="IP"><input type="text" value={f.ip} onChange={(e) => setF({ ...f, ip: e.target.value })} /></Field>
        <button className="btn" disabled={!(f.label.trim() && f.ip.trim())} onClick={async () => {
          await act(() => A.post("admin-ips", { label: f.label.trim(), ip: f.ip.trim() }), "추가했습니다.");
          setF({ label: "", ip: myIp }); ips.reload();
        }}>추가</button>
      </div>

      <h3>접속 기록</h3>
      <Tabs items={VIEWS} value={view} onChange={setView} />
      {logs.error && <Alert kind="err">{logs.error}</Alert>}
      {rows.length ? (
        <div>
          <div className="metrics">
            <Metric k="최근 기록" v={rows.length} />
            <Metric k="고유 IP" v={new Set(rows.map((r) => str(r.ip))).size} />
          </div>
          <DataTable rows={rows} cols={rows[0] && ["created_at", "ip", "page", "action", "detail"].every((c) => c in rows[0]) ? ["created_at", "ip", "page", "action", "detail"] : undefined} tall />
        </div>
      ) : <p className="caption">기록이 없습니다.</p>}

      <h3 style={{ marginTop: 20 }}>관리자 행동 기록</h3>
      {actions.error && <Alert kind="err">{actions.error}</Alert>}
      <DataTable rows={actionRows as Row[]} tall empty="기록이 없습니다." />
    </div>
  );
}
