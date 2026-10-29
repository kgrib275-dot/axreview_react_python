// 관리 영역 틀 — 왼쪽 메뉴(15개 화면) + 중첩 라우트. 관리자가 아니거나 API 가 403 을 돌려주면 토큰 입력 화면을 띄운다.
import { lazy, Suspense, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { Alert } from "../../components/ui";
import { useMe } from "../../me";
import "./admin.css";
import { ToastProvider, onForbidden } from "./common";
import { JobsProvider } from "./JobRunner";

const L = (p: () => Promise<{ default: React.ComponentType }>) => lazy(p);
const PAGES: { path: string; label: string; grp?: string; C: React.LazyExoticComponent<React.ComponentType> }[] = [
  { path: "dashboard", label: "대시보드", grp: "운영", C: L(() => import("./Dashboard")) },
  { path: "review", label: "노트 검토", grp: "콘텐츠", C: L(() => import("./Review")) },
  { path: "briefing", label: "데일리 브리핑", C: L(() => import("./Briefing")) },
  { path: "articles", label: "수집 기사", C: L(() => import("./Articles")) },
  { path: "issues", label: "주간 흐름", C: L(() => import("./Issues")) },
  { path: "report", label: "주간 PDF 리포트", C: L(() => import("./Report")) },
  { path: "search", label: "의미 검색·질문하기", C: L(() => import("./Search")) },
  { path: "collect", label: "수집 설정", grp: "설정", C: L(() => import("./Collect")) },
  { path: "schedule", label: "배치 스케줄", C: L(() => import("./Schedule")) },
  { path: "ops", label: "운영 점검", grp: "운영 현황", C: L(() => import("./Ops")) },
  { path: "engagement", label: "참여 분석", C: L(() => import("./Engagement")) },
  { path: "warehouse", label: "Databricks 적재", C: L(() => import("./Warehouse")) },
  { path: "subscribers", label: "구독·발송", grp: "사람", C: L(() => import("./Subscribers")) },
  { path: "access", label: "관리자·접속", C: L(() => import("./Access")) },
  { path: "privacy", label: "개인정보 처리방침", C: L(() => import("./PrivacySettings")) },
];

const TOKEN_KEY = "axreview-admin-token";

function TokenPrompt({ reason, onDone }: { reason: string; onDone: () => Promise<void> }) {
  const [tok, setTok] = useState("");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      localStorage.setItem(TOKEN_KEY, tok.trim());
    } catch {
      /* 저장 못 해도 /api/me 는 다시 읽는다 */
    }
    await onDone();
    setBusy(false);
  };
  return (
    <div className="box adm-token">
      <div className="eyebrow">Admin</div>
      <h2 className="sec-h" style={{ fontSize: "1.4rem" }}>🔒 관리자 확인</h2>
      <Alert kind="warn">{reason}</Alert>
      <p className="caption">이 PC(localhost)·등록된 IP 에서는 자동으로 관리자입니다. 그 밖에서는 backend .env 의 ADMIN_TOKEN 을 입력하세요. 이 브라우저에만 저장됩니다.</p>
      <div className="field">
        <label>관리자 토큰</label>
        <input type="password" value={tok} onChange={(e) => setTok(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} autoFocus />
      </div>
      <div className="btn-row">
        <button className="btn primary" disabled={busy || !tok.trim()} onClick={save}>확인</button>
        <button className="btn ghost" disabled={busy} onClick={() => { try { localStorage.removeItem(TOKEN_KEY); } catch { /* */ } setTok(""); onDone(); }}>토큰 지우기</button>
      </div>
    </div>
  );
}

export default function AdminApp() {
  const { me, reload } = useMe();
  const [forbidden, setForbidden] = useState<string | null>(null);

  useEffect(() => {
    onForbidden(() => setForbidden("관리 API 가 접근을 거부했습니다 (403). 토큰을 확인해 주세요."));
    return () => onForbidden(() => undefined);
  }, []);

  if (!me) return <div className="page-loading">불러오는 중…</div>;
  if (!me.is_admin || forbidden) {
    return (
      <div className="container page">
        <TokenPrompt
          reason={forbidden || "관리자 IP 가 아니거나 토큰이 없습니다."}
          onDone={async () => {
            await reload();
            setForbidden(null);
          }}
        />
      </div>
    );
  }

  return (
    <ToastProvider>
      <JobsProvider>
        <div className="container adm">
          <nav className="adm-side" aria-label="관리 메뉴">
            {PAGES.map((p) => (
              <span key={p.path} style={{ display: "contents" }}>
                {p.grp && <div className="grp">{p.grp}</div>}
                <NavLink to={`/admin/${p.path}`} className={({ isActive }) => (isActive ? "on" : "")}>{p.label}</NavLink>
              </span>
            ))}
          </nav>
          <main className="adm-main">
            <Suspense fallback={<div className="page-loading">불러오는 중…</div>}>
              <Routes>
                <Route index element={<Navigate to="dashboard" replace />} />
                {PAGES.map((p) => <Route key={p.path} path={p.path} element={<p.C />} />)}
                <Route path="*" element={<Navigate to="dashboard" replace />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </JobsProvider>
    </ToastProvider>
  );
}
