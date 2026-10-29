// Databricks 적재 — 연결 설정 상태, 연결 테스트, 지금 적재/전체 다시 적재, 자동 적재 토글, 테이블 상태, 적재 기록 (app_pages/admin/warehouse.py).
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Check, DataTable, Row, asArray, bool, isObj, pick, str, useAct } from "./common";
import { JobStatus, RunLogTable, StartJob, useJobs } from "./JobRunner";

export default function Warehouse() {
  const { finished } = useJobs();
  const act = useAct();
  const { data, error, reload, loading } = useLoad(() => A.get<Row>("warehouse"), [finished]);
  const d = data || {};
  const problems = asArray<string>(pick(d, "problems", "issues")).map(String);
  const configured = pick(d, "configured") !== undefined ? bool(d.configured) : problems.length === 0;
  const auto = bool(pick(d, "auto_sync", "auto"));
  const cfg = isObj(d.settings) ? (d.settings as Row) : d;
  const status = asArray(pick(d, "status", "tables"));

  return (
    <div>
      <AdminHead title="Databricks 적재" note="앱은 로컬 DB(SQLite)로 돌고, 바뀐 데이터만 Databricks Delta 테이블로 MERGE합니다. 구독자·문의(이메일)·접속 기록(IP)은 개인정보라 적재하지 않고, 임베딩 열은 용량이 커서 뺍니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="대상" v={<span style={{ fontSize: "1rem" }}>{str(d.target) || "-"}</span>} />
        <Metric k="연결 설정" v={configured ? "준비됨" : "미설정"} />
      </div>
      {!configured ? (
        <div>
          <Alert kind="warn">🔑 `.env`에 Databricks 연결 정보를 넣고 앱을 다시 시작하세요: {problems.join(" · ")}</Alert>
          <pre className="code">{`DATABRICKS_SERVER_HOSTNAME=adb-xxxxxxxx.xx.azuredatabricks.net
DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/xxxxxxxxxxxxxxxx
DATABRICKS_TOKEN=dapi...
# 선택 (기본값 workspace / axreview)
DATABRICKS_CATALOG=workspace
DATABRICKS_SCHEMA=axreview`}</pre>
        </div>
      ) : (
        <p className="caption">호스트 <code>{str(cfg.host)}</code> · 경로 <code>{str(cfg.http_path)}</code> · 토큰 …{str(pick(cfg, "token_tail", "token")).slice(-4)}</p>
      )}
      <div style={{ margin: "10px 0" }}>
        <Check label="수집·노트 초안·주간 흐름·뉴스레터 작업이 끝나면 자동 적재" checked={auto} disabled={!configured} onChange={async (v) => { await act(() => A.put("warehouse/auto", { on: v }), v ? "자동 적재를 켰습니다." : "자동 적재를 껐습니다."); reload(); }} />
      </div>
      <div className="btn-row">
        <button className="btn" disabled={!configured} onClick={async () => {
          const r = await act(() => A.post<Row>("warehouse/test"));
          if (r) act(async () => undefined, `접속 성공 · 사용자 ${str(r.user)} · DBSQL ${str(r.version)} · 스키마 ${bool(r.schema_exists) ? "있음" : "없음 (첫 적재 때 만듭니다)"}`);
        }}>🔌 연결 테스트</button>
        {configured && <StartJob kind="warehouse" text="지금 적재" primary />}
        {configured && <StartJob kind="warehouse" text="전체 다시 적재" kwargs={{ full: true }} />}
      </div>
      <p className="caption">Warehouse가 꺼져 있으면 접속에 수십 초 걸립니다.</p>
      <JobStatus only={["warehouse"]} />

      <div className="btn-row" style={{ margin: "16px 0 8px" }}>
        <h3 style={{ margin: 0 }}>테이블</h3>
        <button className="btn sm" disabled={loading} onClick={async () => { await act(() => A.post("warehouse/reset")); reload(); }}>🔄 다시 세기</button>
      </div>
      <DataTable rows={status} />
      <p className="caption">'적재 대기'는 마지막 적재 뒤 로컬에서 새로 생기거나 바뀌거나 지워진 행 수입니다. Databricks 쪽 테이블을 지웠다면 '전체 다시 적재'로 모두 다시 보내세요.</p>
      {d.last_synced !== undefined && <p className="caption">마지막 적재 {str(d.last_synced)}</p>}

      <h3 style={{ margin: "18px 0 8px" }}>적재 기록</h3>
      <RunLogTable kind="warehouse" limit={20} />
    </div>
  );
}
