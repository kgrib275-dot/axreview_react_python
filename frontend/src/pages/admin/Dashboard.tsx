// 대시보드 — 숫자, Gemini/SMTP/배치 배지, Gemini 키 상태, 작업 실행 버튼, 실행 기록 (app_pages/admin/dashboard.py).
import { Alert, Metric, useLoad } from "../../components/ui";
import { A, AdminHead, Badge, DataTable, Expander, Row, asArray, bool, isObj, num, pick, str } from "./common";
import { JobStatus, RunLogTable, StartJob, useJobs } from "./JobRunner";

const COUNT_LABELS: Record<string, string> = {
  articles: "수집 기사", candidates: "초안 후보 (3점↑)", drafts: "검토 대기 초안", published: "게시 노트", subscribers: "활성 구독자",
};
const JOBS: [string, string, boolean, (cfg: Row) => string][] = [
  ["collect", "수집 실행", true, () => "활성 소스 수집 → 중복 제거 → 키워드 필터 → AX 관련도 채점"],
  ["draft", "노트 초안 생성", false, (s) => `${str(s.min_score) || "3"}점 이상 후보 중 상위 ${str(s.per_run) || "?"}건의 원문을 읽고 초안 작성`],
  ["weekly", "지난주 흐름 생성", false, () => "지난주 게시 노트로 '이번 주 AX 흐름' 작성"],
  ["newsletter", "뉴스레터 발송", false, () => "최신 주간 흐름 + 새 노트를 활성 구독자에게 발송"],
  ["vectorize", "벡터화", false, () => "게시 노트·기사 임베딩 (의미 검색·질문하기)"],
  ["report", "주간 PDF 만들기", false, () => "최신 주간 흐름으로 PDF 리포트 생성"],
  ["teams", "Teams 발송", false, () => "최신 흐름 + 새 노트를 Teams 채널에 카드로"],
];

export default function Dashboard() {
  const { finished } = useJobs();
  const { data, error, reload } = useLoad(() => A.get<Row>("dashboard"), [finished]);
  const d = data || {};
  const counts = isObj(d.counts) ? d.counts : {};
  const gemini = pick<unknown>(d, "gemini", "gemini_keys");
  const geminiRows = asArray(gemini, "rows", "keys", "status");
  const geminiOk = pick<unknown>(d, "gemini_ok", "llm_ok") ?? (isObj(gemini) ? pick(gemini, "configured", "ok") : geminiRows.length > 0);
  const smtpOk = bool(pick(d, "smtp_ok", "smtp", "mailer"));
  const scheduleOn = asArray<string | Row>(pick(d, "schedule_on", "schedules", "enabled_jobs")).map((x) => (isObj(x) ? str(pick(x, "label", "name", "kind")) : String(x)));
  const schedule = isObj(d.schedule) ? (d.schedule as Record<string, Row>) : {};
  const drafting = isObj(schedule.drafting) ? schedule.drafting : isObj(d.drafting) ? (d.drafting as Row) : {};
  const runLogs = pick<unknown>(d, "run_logs", "logs");

  return (
    <div>
      <AdminHead title="대시보드" note="수집 → 노트 초안 → 검토·게시 → 주간 흐름 → 뉴스레터 순서로 운영합니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        {Object.keys(COUNT_LABELS).filter((k) => k in counts).map((k) => <Metric key={k} k={COUNT_LABELS[k]} v={num(counts[k])} />)}
        {Object.entries(counts).filter(([k]) => !(k in COUNT_LABELS)).map(([k, v]) => <Metric key={k} k={k} v={str(v)} />)}
      </div>
      <div className="badges">
        {geminiOk !== undefined && (
          <Badge color={bool(geminiOk) ? "green" : "red"}>🤖 {bool(geminiOk) ? "Gemini 연결됨" : "Gemini 키 없음 — 채점·초안 불가"}</Badge>
        )}
        {pick(d, "smtp_ok", "smtp", "mailer") !== undefined && (
          <Badge color={smtpOk ? "green" : "orange"}>✉ {smtpOk ? "SMTP 설정됨" : "SMTP 미설정 — 뉴스레터 발송 불가"}</Badge>
        )}
        <Badge color="blue">🕒 자동 배치: {scheduleOn.length ? scheduleOn.join(", ") : "꺼짐"}</Badge>
      </div>

      <Expander title="🔑 Gemini 키 상태 (키별로 병렬 배정)">
        <p className="caption">
          키마다 다른 프로젝트라 하루 한도도 따로입니다. 작업은 정상 키 수만큼 병렬로 나눠 돌고, 한도를 다 쓴 키는 그 모델에서만 자정까지 쉽니다.
          상태는 이 앱이 실제로 호출하며 알게 된 값입니다.
        </p>
        <DataTable rows={geminiRows} empty="등록된 키가 없습니다." />
      </Expander>

      <h3 style={{ margin: "18px 0 8px" }}>지금 실행</h3>
      <JobStatus />
      <div className="jobs-grid">
        {JOBS.map(([kind, text, primary, desc]) => (
          <div key={kind}>
            <StartJob kind={kind} text={text} primary={primary} block onStarted={reload} />
            <div className="caption">{desc(drafting)}</div>
          </div>
        ))}
      </div>

      <h3 style={{ margin: "18px 0 8px" }}>실행 기록</h3>
      <RunLogTable rows={runLogs !== undefined ? asArray(runLogs) : undefined} />
    </div>
  );
}
