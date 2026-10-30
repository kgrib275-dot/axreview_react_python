// 라우트 목록 — 페이지 파일은 각 담당이 만든다. 경로는 Streamlit 판과 같게 유지한다 (공유 링크·sitemap 호환).
import { lazy, Suspense, useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { track } from "./api";
import Layout from "./layout/Layout";
import { MeProvider } from "./me";

const L = (p: () => Promise<{ default: React.ComponentType }>) => lazy(p);
const Home = L(() => import("./pages/Home"));
const Notes = L(() => import("./pages/Notes"));
const Today = L(() => import("./pages/Today"));
const Lab = L(() => import("./pages/Lab"));
const Ask = L(() => import("./pages/Ask"));
const About = L(() => import("./pages/About"));
const TypeTest = L(() => import("./pages/TypeTest"));
const Terms = L(() => import("./pages/Terms"));
const Diagnosis = L(() => import("./pages/Diagnosis"));
const Habit = L(() => import("./pages/Habit"));
const Career = L(() => import("./pages/Career"));
const Letter = L(() => import("./pages/Letter"));
const Refer = L(() => import("./pages/Refer"));
const Confirm = L(() => import("./pages/Confirm"));
const Unsubscribe = L(() => import("./pages/Unsubscribe"));
const Privacy = L(() => import("./pages/Privacy"));
const Admin = L(() => import("./pages/admin/AdminApp"));
const NotFound = L(() => import("./pages/NotFound"));

/** 화면 이동 기록 (방문 패턴 분석) — 경로만 보낸다. 쿼리(확인·연결 토큰 등)는 보내지 않고, 관리 화면·관리자 이동은 서버가 버린다. */
function PageView() {
  const { pathname } = useLocation();
  useEffect(() => { if (!pathname.startsWith("/admin")) track("page_view", pathname); }, [pathname]);
  return null;
}

export default function App() {
  return (
    <MeProvider>
      <PageView />
      <Layout>
        <Suspense fallback={<div className="page-loading">불러오는 중…</div>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/home" element={<Home />} />
            <Route path="/notes" element={<Notes />} />
            <Route path="/today" element={<Today />} />
            <Route path="/lab" element={<Lab />} />
            <Route path="/ask" element={<Ask />} />
            <Route path="/about" element={<About />} />
            <Route path="/type" element={<TypeTest />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/diagnosis" element={<Diagnosis />} />
            <Route path="/habit" element={<Habit />} />
            <Route path="/career" element={<Career />} />
            <Route path="/letter" element={<Letter />} />
            <Route path="/refer" element={<Refer />} />
            <Route path="/confirm" element={<Confirm />} />
            <Route path="/unsubscribe" element={<Unsubscribe />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/admin/*" element={<Admin />} />
            {/* 없는 경로 — 라우트를 추가하면 api/main.py _APP_ROUTES 에도 넣어야 서버가 404 를 주지 않는다 */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </Layout>
    </MeProvider>
  );
}
