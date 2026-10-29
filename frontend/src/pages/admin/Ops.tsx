// 운영 점검 — 🔴 바로 조치 · 🟡 확인 필요 · 🟢 정상 숫자 + 상태순 표 + '지금 백업' (app_pages/admin/ops.py; 점검 자체는 백엔드가 한다).
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, DataTable, Row, asArray, str, useAct } from "./common";

const OK = "🟢", WARN = "🟡", BAD = "🔴";
const ORDER: Record<string, number> = { [BAD]: 0, [WARN]: 1, [OK]: 2 };
const statusOf = (r: Row) => str(r["상태"] ?? r.status);

export default function Ops() {
  const { data, error, loading, reload } = useLoad(() => A.get<unknown>("ops"), []);
  const act = useAct();
  const rows = asArray(data, "rows", "items", "checks").map((r) => ({
    상태: statusOf(r), 분야: str(r["분야"] ?? r.area), 항목: str(r["항목"] ?? r.item), 현재: str(r["현재"] ?? r.detail), 조치: str(r["조치"] ?? r.action),
  }));
  const sorted = [...rows].sort((a, b) => (ORDER[a.상태] ?? 3) - (ORDER[b.상태] ?? 3));
  const count = (s: string) => rows.filter((r) => r.상태 === s).length;
  return (
    <div>
      <AdminHead title="운영 점검" note="공개 운영에 필요한 항목을 자동으로 확인합니다. 🔴 바로 조치 · 🟡 확인 필요 · 🟢 정상" />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics" style={{ alignItems: "flex-end" }}>
        <Metric k="바로 조치" v={count(BAD)} />
        <Metric k="확인 필요" v={count(WARN)} />
        <Metric k="정상" v={count(OK)} />
        <button className="btn" onClick={async () => { const r = await act(() => A.post<Row>("ops/backup")); if (r) { act(async () => undefined, `백업했습니다: ${str(r.name ?? r.file ?? r.path)}`); reload(); } }}>💾 지금 백업</button>
        <button className="btn ghost" disabled={loading} onClick={reload}>{loading ? "점검 중…" : "다시 점검"}</button>
      </div>
      <DataTable rows={sorted} cols={["상태", "분야", "항목", "현재", "조치"]} />
    </div>
  );
}
