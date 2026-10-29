// 라우트 목록 — 페이지 파일은 각 담당이 만든다. 경로는 Streamlit 판과 같게 유지한다 (공유 링크·sitemap 호환).
import { lazy, Suspense } from "react";
import { Route, Routes } from "react-router-dom";
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
const Letter = L(() => import("./pages/Letter"));
const Refer = L(() => import("./pages/Refer"));
const Confirm = L(() => import("./pages/Confirm"));
const Unsubscribe = L(() => import("./pages/Unsubscribe"));
const Privacy = L(() => import("./pages/Privacy"));
const Admin = L(() => import("./pages/admin/AdminApp"));

export default function App() {
  return (
    <MeProvider>
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
            <Route path="/letter" element={<Letter />} />
            <Route path="/refer" element={<Refer />} />
            <Route path="/confirm" element={<Confirm />} />
            <Route path="/unsubscribe" element={<Unsubscribe />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/admin/*" element={<Admin />} />
            <Route path="*" element={<Home />} />
          </Routes>
        </Suspense>
      </Layout>
    </MeProvider>
  );
}
