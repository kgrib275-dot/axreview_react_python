// 전 페이지 공통 틀 — 헤더(내비·구독·테마·KO/EN), 푸터, 플로팅 버튼, 구독 띠, 대화상자, 추천 링크(?ref=)·공유 유입(?s=1) 기록.
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router-dom";
import { track } from "../api";
import { DialogProvider, useDialogs } from "../components/Dialogs";
import { useMe } from "../me";
import Nudge from "./Nudge";
import { ThemeToggle } from "./Theme";
import { LangToggle } from "./Translate";

const NAV = [
  ["/", "✦ 이번 호"], ["/notes", "노트"], ["/today", "오늘의 AX"], ["/lab", "데이터 랩"], ["/ask", "AX 질문하기"], ["/about", "소개"],
] as const;
const PLAY = [["/type", "AX 리더 유형 테스트"], ["/career", "AX 커리어 유형"], ["/habit", "AI 활용 습관 진단"], ["/terms", "AI·AX 용어 퀴즈"], ["/diagnosis", "AX 준비도 자가진단"]] as const;

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <DialogProvider>
      <Shell>{children}</Shell>
    </DialogProvider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { me, state, setState } = useMe();
  const { openSubscribe } = useDialogs();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const [params] = useSearchParams();

  useEffect(() => {
    setOpen(false);
    document.querySelector("main")?.scrollTo?.(0, 0);
    window.scrollTo(0, 0);
  }, [loc.pathname]);

  // 추천 링크로 온 방문 → 구독 시 추천인으로 남긴다. 공유 링크(?s=1) 유입 기록은 각 페이지가 content 를 알고 한다.
  useEffect(() => {
    const ref = params.get("ref");
    if (ref && /^[a-z0-9]{6,12}$/.test(ref) && state.ref !== ref) {
      setState({ ref });
      track("ref_visit", ref);
    }
  }, [params, state.ref, setState]);

  const isAdminArea = loc.pathname.startsWith("/admin");
  return (
    <>
      <header className="hdr">
        <div className="container hdr-in">
          {/* (N) = React·FastAPI 새 버전 표시 — Streamlit 판과 구분 */}
          <Link to="/" className="logo" aria-label="AX Review (새 버전)"><img className="logo-dk" src="/logo.svg" alt="" height={26} /><img className="logo-lt" src="/logo-light.svg" alt="" height={26} /><span className="ver">(N)</span></Link>
          <button className="btn sm burger" aria-label="메뉴" onClick={() => setOpen((o) => !o)}>☰ 메뉴</button>
          <nav className={`nav ${open ? "open" : ""}`}>
            {NAV.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => (isActive ? "on" : "")}>{label}</NavLink>
            ))}
            <div className="dd">
              <button type="button">AX 테스트 ▾</button>
              <div className="menu">{PLAY.map(([to, label]) => <NavLink key={to} to={to}>{label}</NavLink>)}</div>
            </div>
            {me?.is_admin && <NavLink to="/admin" className={() => (isAdminArea ? "on" : "")}>관리</NavLink>}
          </nav>
          <div className="hdr-right">
            <ThemeToggle />
            <LangToggle />
            <button className="btn primary sm sub" onClick={() => openSubscribe("header")}>구독</button>
          </div>
        </div>
      </header>
      <main>
        <div className="container page">{children}</div>
      </main>
      <Footer />
      <a className="fab fab-ask" href="/ask" title="AX 질문하기">✦</a>
      <button className="fab fab-top" title="맨 위로" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>↑</button>
      {!isAdminArea && !state.subscribed && (!me?.is_admin || params.get("nudge") === "1") && <Nudge onSubscribe={() => openSubscribe("sticky_bar")} />}
    </>
  );
}

function Footer() {
  const { me } = useMe();
  return (
    <footer className="container">
      <div className="site-foot">
        <span>© 2026 <b>AX Review</b></span>
        <span>기업 AX를 위해 읽은 자료를 정리한 노트입니다.</span>
        <span>
          <Link to="/letter">뉴스레터 미리보기</Link>
          {me?.privacy_active !== false && <> · <Link to="/privacy" style={{ color: "var(--ink-hi)", fontWeight: 800 }}>개인정보 처리방침</Link></>}
        </span>
      </div>
    </footer>
  );
}
