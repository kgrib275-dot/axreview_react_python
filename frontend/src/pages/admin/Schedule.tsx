// 배치 스케줄 — 작업별 사용/실행 시각(매일) 또는 요일+시각(주간), 초안 per_run·min_score, 주간 auto_publish (app_pages/admin/schedule.py).
import { useEffect, useState } from "react";
import { Alert, useLoad } from "../../components/ui";
import { A, AdminHead, Check, Field, Row, asArray, bool, isObj, num, str, useAct } from "./common";

const WD = ["월", "화", "수", "목", "금", "토", "일"];
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)$/;
type Def = { key: string; title: string; desc: string; weekly?: boolean; extra?: "draft" | "auto" };
const LEFT: Def[] = [
  { key: "collection", title: "1. 수집", desc: "활성 소스 수집 → 중복 제거 → 키워드 필터 → AI 채점 (관리 > AI 모델 설정)" },
  { key: "drafting", title: "2. 노트 초안 생성", desc: "점수 높은 대기 기사의 원문을 읽고 초안을 씁니다. 수집 30분 뒤 정도가 적당합니다.", extra: "draft" },
  { key: "vectorize", title: "5. 벡터화", desc: "새 게시 노트·기사를 임베딩해 의미 검색과 'AX 질문하기'에 반영합니다. 수집·초안 뒤로 잡으세요." },
];
const RIGHT: Def[] = [
  { key: "weekly", title: "3. 주간 흐름", desc: "지난주(월~일) 게시 노트로 '이번 주 AX 흐름'을 씁니다.", weekly: true, extra: "auto" },
  { key: "newsletter", title: "4. 뉴스레터 발송", desc: "최신 주간 흐름과 지난 발송 이후 새 노트를 활성 구독자에게 보냅니다. 주간 흐름 이후로 잡으세요.", weekly: true },
  { key: "teams", title: "6. Teams 발송", desc: "최신 주간 흐름과 지난 Teams 발송 이후 새 노트를 등록된 채널에 카드로 보냅니다.", weekly: true },
];

function Section({ d, c, onSave }: { d: Def; c: Row; onSave: (key: string, values: Row) => Promise<void> }) {
  const [enabled, setEnabled] = useState(bool(c.enabled));
  const [times, setTimes] = useState(asArray<string>(c.times).join(" / "));
  const [weekday, setWeekday] = useState(num(c.weekday));
  const [time, setTime] = useState(str(c.time));
  const [perRun, setPerRun] = useState(num(c.per_run, 5));
  const [minScore, setMinScore] = useState(num(c.min_score, 3));
  const [autoPub, setAutoPub] = useState(bool(c.auto_publish));
  const [err, setErr] = useState("");
  useEffect(() => {
    setEnabled(bool(c.enabled)); setTimes(asArray<string>(c.times).join(" / ")); setWeekday(num(c.weekday)); setTime(str(c.time));
    setPerRun(num(c.per_run, 5)); setMinScore(num(c.min_score, 3)); setAutoPub(bool(c.auto_publish));
  }, [c]);
  const save = () => {
    const { title: _t, desc: _d, ...base } = c;  // 화면용 제목·설명은 보내지 않는다
    const vals: Row = { ...base, enabled };
    if (d.weekly) {
      if (!TIME_RE.test(time.trim())) return setErr("시각은 HH:MM 형식이어야 합니다.");
      vals.weekday = weekday; vals.time = time.trim();
    } else {
      const parts = times.split("/").map((t) => t.trim()).filter(Boolean);
      const bad = parts.filter((t) => !TIME_RE.test(t));
      if (bad.length) return setErr(`잘못된 시각: ${bad.join(", ")}`);
      vals.times = parts;
    }
    if (d.extra === "draft") { vals.per_run = perRun; vals.min_score = minScore; }
    if (d.extra === "auto") vals.auto_publish = autoPub;
    setErr("");
    onSave(d.key, vals);
  };
  return (
    <div className="box sm">
      <div className="title">{d.title}</div>
      <p className="caption" style={{ marginBottom: 8 }}>{d.desc}</p>
      <Check label="사용" checked={enabled} onChange={setEnabled} />
      <div style={{ height: 8 }} />
      {d.weekly ? (
        <div className="row2">
          <Field label="요일"><select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>{WD.map((w, i) => <option key={w} value={i}>{w}요일</option>)}</select></Field>
          <Field label="시각 (HH:MM)"><input type="text" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
        </div>
      ) : (
        <Field label="실행 시각 (HH:MM, '/'로 구분)"><input type="text" value={times} onChange={(e) => setTimes(e.target.value)} /></Field>
      )}
      {d.extra === "draft" && (
        <div className="row2">
          <Field label="회당 최대 건수"><input type="number" min={1} max={30} value={perRun} onChange={(e) => setPerRun(Number(e.target.value))} /></Field>
          <Field label={`최소 점수 ${minScore}`}><input type="range" min={1} max={5} value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} /></Field>
        </div>
      )}
      {d.extra === "auto" && <div style={{ marginBottom: 10 }}><Check label="검토 없이 바로 게시" checked={autoPub} onChange={setAutoPub} /></div>}
      {err && <Alert kind="err">{err}</Alert>}
      <button className="btn primary sm" onClick={save}>저장</button>
    </div>
  );
}

export default function Schedule() {
  const { data, error, reload } = useLoad(() => A.get<Row>("schedule"), []);
  const act = useAct();
  // 서버는 {daily: {collection, drafting, vectorize}, weekly: {weekly, newsletter, teams}} 로 보낸다.
  // 예전엔 묶음을 풀지 않고 cfg.collection 을 찾아 늘 빈 값으로 보였다 → 저장 뒤 다시 불러오면 빈 칸, 빈 칸으로 저장하면 원래 값이 지워졌다 (2026-10-29)
  const cfg: Row = data ? { ...(isObj(data.daily) ? (data.daily as Row) : {}), ...(isObj(data.weekly) ? (data.weekly as Row) : {}),
    ...(isObj(data.schedule) ? (data.schedule as Row) : {}) } : {};
  const sec = (k: string) => (isObj(cfg[k]) ? (cfg[k] as Row) : {});
  const save = async (key: string, values: Row) => {
    await act(() => A.put("schedule", { [key]: values }), `${[...LEFT, ...RIGHT].find((d) => d.key === key)?.title} 스케줄을 저장했습니다.`);
    reload();
  };
  return (
    <div>
      <AdminHead title="배치 스케줄" note="서버가 켜져 있는 동안 30초마다 확인해 등록된 시각에 실행합니다." />
      {error && <Alert kind="err">{error}</Alert>}
      <div className="row2">
        <div>{LEFT.map((d) => <Section key={d.key} d={d} c={sec(d.key)} onSave={save} />)}</div>
        <div>{RIGHT.map((d) => <Section key={d.key} d={d} c={sec(d.key)} onSave={save} />)}</div>
      </div>
      <p className="caption">데일리 아카이브(지난 날짜 확정)는 시각 등록 없이 스케줄러가 상시 처리합니다.</p>
    </div>
  );
}
