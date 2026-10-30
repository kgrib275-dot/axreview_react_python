// 전역 실행 로그 독 — 어느 관리 화면에 있든 배치 작업(수집·초안·주간 흐름·뉴스레터·벡터화·PDF·Teams·적재)이 돌면
// 화면 아래에 실시간 로그를 띄운다. 작업을 시작한 화면을 떠나면 진행 상황이 안 보였다 (2026-10-30).
// 데이터는 JobsProvider 가 이미 2초마다 폴링하는 GET jobs/status 를 그대로 쓴다 — 추가 요청 없음.
// 각 화면의 JobStatus 블록은 그대로 두고, 이 독은 덧붙인 것이다.
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { LogView, label, useJobs } from "./JobRunner";

// 화면 경로마다 따로인 useRemembered 대신 고정 키 — 어느 관리 화면이든 접힘·닫힘 상태가 같아야 한다
const DOCK_KEY = "axreview-adm-dock";
type Saved = { collapsed: boolean; closedSig: string };
const load = (): Saved => {
  try { return { collapsed: false, closedSig: "", ...JSON.parse(localStorage.getItem(DOCK_KEY) || "{}") }; } catch { return { collapsed: false, closedSig: "" }; }
};

/** 시작·종료 시각 문자열(HH:MM:SS 또는 ISO)에서 HH:MM 만. */
const hhmm = (s: string) => (s.match(/(\d{1,2}:\d{2})/) || [])[1] || s;

export function LogDock({ onHeight }: { onHeight: (h: number) => void }) {
  const { status } = useJobs();
  const [saved, setSaved] = useState<Saved>(load);
  useEffect(() => { try { localStorage.setItem(DOCK_KEY, JSON.stringify(saved)); } catch { /* 사생활 보호 모드 */ } }, [saved]);

  const kinds = Object.keys(status.active);
  // 진행 중 작업 묶음의 서명 — 닫으면 이 서명을 기억하고, 새 작업이 시작돼 서명이 바뀌면 다시 뜬다
  const sig = kinds.map((k) => `${k}@${status.active[k]}`).sort().join("|");

  // 이 세션에서 진행 중인 걸 본 작업이 끝나면 결과(status.last)를 닫을 때까지 남긴다.
  // 페이지를 막 연 시점의 오래된 last 는 띄우지 않는다 — 몇 시간 전 로그가 매번 뜨면 성가시다
  const [done, setDone] = useState(false);
  const prevSig = useRef("");
  useEffect(() => {
    if (sig) setDone(false);
    else if (prevSig.current && prevSig.current !== saved.closedSig) setDone(true);
    prevSig.current = sig;
  }, [sig]); // eslint-disable-line react-hooks/exhaustive-deps

  const [tab, setTab] = useState("");
  const cur = kinds.includes(tab) ? tab : kinds[0] || "";

  const live = !!sig && sig !== saved.closedSig;
  const last = status.last;
  const visible = live || (done && !!last);

  // 펼친 독 높이만큼 본문 아래 여백 — 독이 페이지 끝 내용을 영영 가리지 않게
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!visible || !el) { onHeight(0); return; }
    const report = () => onHeight(el.offsetHeight);
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => ro.disconnect();
  }, [visible, saved.collapsed, onHeight]);

  if (!visible) return null;

  const lines = live ? status.logs[cur] || [] : last?.lines || [];
  const lastLine = lines[lines.length - 1];
  const title = live
    ? `⏳ ${label(cur)} 진행 중${status.active[cur] ? ` · 시작 ${hhmm(status.active[cur])}` : ""}`
    : `■ ${label(last?.kind || "")} 완료${last?.ended ? ` · 종료 ${hhmm(last.ended)}` : ""}`;
  const close = () => {
    if (live) setSaved((s) => ({ ...s, closedSig: sig }));
    setDone(false);
  };
  const toggle = () => setSaved((s) => ({ ...s, collapsed: !s.collapsed }));

  return (
    <div ref={ref} className={`log-dock${saved.collapsed ? " collapsed" : ""}${live ? " live" : ""}`} role="region" aria-label="실행 로그">
      <div className="ld-head">
        <b className="ld-title" onClick={toggle}>{title}</b>
        {live && kinds.length > 1 && !saved.collapsed && (
          <div className="ld-tabs" role="tablist">
            {kinds.map((k) => (
              <button key={k} type="button" role="tab" className={k === cur ? "on" : ""} onClick={() => setTab(k)}>{label(k)}</button>
            ))}
          </div>
        )}
        {saved.collapsed && (
          <span className="ld-peek" title={lastLine?.msg}>{lastLine ? `${lastLine.tm} ${lastLine.msg}` : "로그를 기다리는 중…"}</span>
        )}
        <span className="ld-sp" />
        <button type="button" className="btn sm ghost" onClick={toggle} aria-expanded={!saved.collapsed}>{saved.collapsed ? "펼치기" : "접기"}</button>
        <button type="button" className="btn sm ghost" onClick={close} title="다음 작업이 시작될 때까지 숨깁니다">닫기</button>
      </div>
      {!saved.collapsed && <LogView lines={lines} live={live} />}
    </div>
  );
}
