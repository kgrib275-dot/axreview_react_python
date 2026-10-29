// 참여 분석 — 기간·예시 데이터 토글, 숫자, 탭(일별 추이·구독 유입·유형 비교·퀴즈·용어 퀴즈·예측 투표·참여 지도), CSV (app_pages/admin/engagement.py).
// 집계는 GET admin/engagement 가 전부 돌려준다고 보고, 알려진 키는 전용 표시, 모르는 키는 범용 표로 그린다.
import { useState } from "react";
import { get } from "../../api";
import { Alert, Metric, Tabs, useLoad } from "../../components/ui";
import { A, AdminHead, Bar, Bars, Check, CsvButton, DataTable, Expander, Generic, HBars, Row, Seg, asArray, bool, isObj, num, pick, qs, str, useAct } from "./common";

const TABS = ["일별 추이", "구독 유입", "유형 비교", "퀴즈", "용어 퀴즈", "예측 투표", "참여 지도"];
const BY: Record<string, string> = { age: "연령대", gender: "성별", country: "국가", region: "시·도" };
const sec = (d: Row, ...keys: string[]) => { const v = pick(d, ...keys); return isObj(v) ? v : {}; };

/** 행 라벨 × 열 라벨 교차표 ({row: {col: v}}) → 표. */
function Cross({ obj, suffix = "" }: { obj: unknown; suffix?: string }) {
  if (!isObj(obj)) return <p className="caption">데이터 없음</p>;
  const rows = Object.entries(obj).filter(([, v]) => isObj(v)) as [string, Row][];
  if (!rows.length) return <Generic value={obj} />;
  const cols = Array.from(new Set(rows.flatMap(([, v]) => Object.keys(v))));
  return <DataTable rows={rows.map(([k, v]) => ({ " ": k, ...Object.fromEntries(cols.map((c) => [c, v[c] === undefined ? "" : `${str(v[c])}${suffix}`])) }))} cols={[" ", ...cols]} />;
}
/** {라벨: 수} → 가로 막대. */
const toItems = (v: unknown): [string, number][] => (isObj(v) ? Object.entries(v).map(([k, x]) => [k, num(x)]) : asArray(v).map((r) => [str(pick(r, "label", "name", "유형", "용어", "key")), num(pick(r, "count", "n", "value", "수"))]));

export default function Engagement() {
  const [days, setDays] = useState(14);
  const [sample, setSample] = useState(false);
  const [tab, setTab] = useState(TABS[0]);
  const [by, setBy] = useState("age");
  const act = useAct();
  const { data, error, reload } = useLoad(() => A.get<Row>(`engagement${qs({ days, sample: sample ? 1 : "", by })}`), [days, sample, by]);
  const d = data || {};
  const m = sec(d, "metrics", "summary");
  const kinds = sec(d, "kinds", "counts");
  const n = (...k: string[]) => num(pick(m, ...k) ?? pick(kinds, ...k));
  const sampleCount = num(pick(d, "sample_count"));
  const sampleOnMap = bool(pick(d, "sample_on_map"));
  const daily = asArray(pick(d, "daily", "daily_activity"));
  const funnel = asArray(pick(d, "funnel", "funnel_by_source", "subscribe"));
  const types = sec(d, "types", "type_test");
  const quiz = sec(d, "quiz");
  const term = sec(d, "term", "term_quiz");
  const polls = asArray(pick(d, "polls", "poll"));
  const known = new Set(["metrics", "summary", "kinds", "counts", "sample_count", "sample_on_map", "daily", "daily_activity", "funnel", "funnel_by_source", "subscribe", "types", "type_test", "quiz", "term", "term_quiz", "polls", "poll", "retention", "visitors", "empty", "days", "sample"]);
  const unknown = Object.fromEntries(Object.entries(d).filter(([k]) => !known.has(k)));
  const dailySeries = daily.length ? ["참여자", "유형 테스트", "퀴즈 응답", "투표"].filter((s) => s in daily[0]) : [];
  const empty = pick(d, "empty") === true || (!daily.length && n("visitors") === 0 && !Object.keys(kinds).length);

  const map = useLoad(async () => (tab === "참여 지도" ? get<string>(`/api/map/html${qs({ days, sample: sample ? 1 : "" })}`) : null), [tab, days, sample]);

  return (
    <div>
      <AdminHead title="참여 분석" note="AX 리더 유형 테스트·오늘의 퀴즈·예측 투표·공유·구독 유입을 기간·성별·연령대·지역으로 비교합니다. 방문자는 익명 쿠키 값으로만 구분하고, 성별·연령대·지역은 참여자가 직접 고른 경우에만 있습니다." />
      <Expander title={`🧪 예시(가상) 데이터 · 현재 ${sampleCount}건`}>
        <p className="caption">지도·화면 시연용 가상 참여입니다. 방문자 값이 's:'로 시작해 실제 통계·'전체 참여자 중 N%'·Databricks 적재에는 섞이지 않습니다. 공개 지도에 보일 때는 '예시 데이터 포함' 배지가 함께 표시됩니다.</p>
        <Check label="공개 참여 지도(/today)에 예시 데이터 보이기" checked={sampleOnMap} onChange={async (v) => { await act(() => A.put("engagement/sample-on-map", { on: v }), v ? "공개 지도에 예시 데이터를 보입니다." : "공개 지도에서 예시 데이터를 숨깁니다."); reload(); }} />
        <div className="row2" style={{ marginTop: 10 }}>
          <button className="btn" onClick={async () => { const r = await act(() => A.post<Row>("engagement/sample", { action: "seed" })); if (r) { act(async () => undefined, `예시 참여 ${str(pick(r, "n", "count", "inserted"))}건을 넣었습니다.`); reload(); } }}>📈 예시 데이터 넣기 (180명 · 14일)</button>
          <button className="btn" onClick={async () => { if (!window.confirm("예시 데이터를 모두 지울까요?")) return; await act(() => A.post("engagement/sample", { action: "clear" }), "예시 데이터를 지웠습니다."); reload(); }}>🗑 예시 데이터 모두 지우기</button>
        </div>
      </Expander>
      <div className="inline" style={{ margin: "12px 0" }}>
        <Seg items={[7, 14, 30, 90]} value={days} onChange={setDays} fmt={(v) => `최근 ${v}일`} />
        <Check label="예시 데이터 포함해 보기" checked={sample} onChange={setSample} />
        <CsvButton name={`axreview_engagement_${days}d.csv`} label="참여 기록 내려받기 (CSV, 방문자 값 제외)" fetchText={() => A.get<string>(`engagement/csv${qs({ days, sample: sample ? 1 : "" })}`).then((t) => (typeof t === "string" ? t : JSON.stringify(t)))} />
      </div>
      {error && <Alert kind="err">{error}</Alert>}
      <div className="metrics">
        <Metric k="참여 방문자" v={n("visitors", "participants")} />
        <Metric k="재참여율" v={`${str(pick(m, "retention_rate", "retention") ?? pick(sec(d, "retention"), "rate") ?? 0)}%`} />
        <Metric k="유형 테스트" v={n("type_test")} />
        <Metric k="퀴즈 응답" v={n("quiz")} />
        <Metric k="용어 퀴즈" v={n("term_quiz")} />
        <Metric k="예측 투표" v={n("poll")} />
        <Metric k="공유 → 유입" v={`${n("share")} → ${n("share_visit")}`} />
        <Metric k="구독 완료" v={n("subscribe")} />
      </div>
      {empty && data && <Alert kind="info">아직 이 기간의 참여 기록이 없습니다. /type, /today 에서 참여가 생기면 여기에 쌓입니다.</Alert>}

      <Tabs items={TABS} value={tab} onChange={setTab} />
      {tab === "일별 추이" && (daily.length ? (
        <div>
          <Bars rows={daily} labelKey={"날짜" in daily[0] ? "날짜" : "day"} series={dailySeries.length ? dailySeries : Object.keys(daily[0]).filter((k) => typeof daily[0][k] === "number")} />
          <DataTable rows={daily} />
        </div>
      ) : <p className="caption">데이터 없음</p>)}
      {tab === "구독 유입" && (
        <div>
          <p className="caption">구독 창을 연 위치별로 실제 구독까지 이어진 비율입니다. 전환율이 높은 위치에 구독 유도를 더 두세요.</p>
          <DataTable rows={funnel} render={{ "전환율(%)": (v) => <Bar v={num(v)} label={`${num(v).toFixed(1)}%`} /> }} />
        </div>
      )}
      {tab === "유형 비교" && (Object.keys(types).length ? (
        <div>
          <HBars items={toItems(pick(types, "counts", "by_type", "types")).sort((a, b) => b[1] - a[1])} />
          <div style={{ margin: "12px 0" }}><Seg items={Object.keys(BY)} value={by} onChange={setBy} fmt={(v) => BY[v]} /></div>
          <p className="caption">열 기준 비율(%) — 같은 연령대(성별·지역) 안에서 각 유형이 차지하는 비중</p>
          <Cross obj={(() => { const ct = pick(types, "crosstab", "by"); return isObj(ct) && isObj(ct[by]) ? ct[by] : ct; })()} />
          {pick(types, "axes", "axes_avg") !== undefined && (
            <div style={{ marginTop: 10 }}>
              <p className="caption">축별 평균 — 왼쪽 성향 비율(%)</p>
              <Generic value={pick(types, "axes", "axes_avg")} />
            </div>
          )}
        </div>
      ) : <p className="caption">데이터 없음</p>)}
      {tab === "퀴즈" && (Object.keys(quiz).length ? (
        <div>
          <DataTable rows={asArray(pick(quiz, "per_question", "questions", "per"))} render={{ 정답률: (v) => <Bar v={num(v)} label={`${num(v).toFixed(1)}%`} /> }} />
          <p className="caption" style={{ marginTop: 10 }}>연령대·성별별 정답률(%)</p>
          <Cross obj={pick(quiz, "by_age_gender", "pivot")} />
          <p className="caption" style={{ marginTop: 10 }}>연속 참여일 분포 (방문자 수)</p>
          <HBars items={toItems(pick(quiz, "streaks")).sort((a, b) => num(a[0]) - num(b[0]))} />
        </div>
      ) : <p className="caption">데이터 없음</p>)}
      {tab === "용어 퀴즈" && (Object.keys(term).length ? (
        <div>
          <p className="caption">트랙 × 연령대 평균 점수</p>
          <Cross obj={pick(term, "by_track_age", "pivot")} />
          <p className="caption" style={{ marginTop: 10 }}>가장 많이 틀린 용어 — 노트·뉴스레터에서 풀어 설명할 후보</p>
          <HBars items={toItems(pick(term, "missed", "wrong")).sort((a, b) => b[1] - a[1]).slice(0, 12)} />
        </div>
      ) : <p className="caption">데이터 없음</p>)}
      {tab === "예측 투표" && <DataTable rows={polls} />}
      {tab === "참여 지도" && (map.error ? <Alert kind="err">{map.error}</Alert> : map.data ? <iframe className="adm-frame" title="참여 지도" srcDoc={map.data} style={{ height: 620 }} /> : <p className="caption">지도를 불러오는 중…</p>)}

      {Object.keys(unknown).length > 0 && (
        <Expander title="그 밖의 집계">
          <Generic value={unknown} />
        </Expander>
      )}
    </div>
  );
}
