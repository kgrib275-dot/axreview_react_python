// 뉴스레터 미리보기 (/letter) — Streamlit 판 app_pages/letter.py 이식. 메일 HTML 은 iframe srcdoc 으로 띄운다.
import { useState } from "react";
import { get } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import { Alert, useLoad } from "../components/ui";
import "./Home.css";

type Letters = { letters: { label: string; html: string }[] };

export default function LetterPage() {
  const { data, error, loading } = useLoad(() => get<Letters>("letter"));
  const [pick, setPick] = useState(0);
  const letters = data?.letters || [];
  const cur = letters[pick] || letters[0];

  return (
    <>
      <div className="eyebrow">Newsletter preview</div>
      <h2 className="sec-h">받게 될 <span className="grad">메일</span> 미리 보기</h2>
      <p className="sec-p" style={{ maxWidth: 760 }}>
        매주 월요일 아침, 아래 모양 그대로 메일함에 도착합니다. 한 주의 흐름 → <b>리더가 알아야 할 3가지</b> → 새 노트 순서입니다.
      </p>

      {error && <Alert kind="err">{error}</Alert>}
      {loading && !data && <div className="page-loading">불러오는 중…</div>}
      {data && !letters.length && <Alert kind="info">⏳ 첫 호를 준비하고 있습니다.</Alert>}

      {cur && (
        <>
          <div className="seg" role="radiogroup" aria-label="호 선택" style={{ margin: "14px 0" }}>
            {letters.map((l, i) => (
              <button key={l.label + i} type="button" role="radio" aria-checked={i === pick} className={i === pick ? "on" : ""} onClick={() => setPick(i)}>{l.label}</button>
            ))}
          </div>
          <div className="two-col">
            <iframe
              className="doc-frame" title={cur.label} srcDoc={cur.html} height={1100}
              sandbox="allow-popups allow-popups-to-escape-sandbox"
            />
            <div>
              <SubscribeCTA source="letter" headline="이 메일을 매주 받아 보세요" sub="무료 · 언제든 메일 하단 링크로 해지" />
              <div className="guide">
                <div className="guide-h">📨 메일 구성</div>
                <ol>
                  <li><b>이번 주 AX 흐름</b><span>한 줄 헤드라인과 4~5문장 요약. 꼭 알아야 할 구절은 <strong className="hl">이렇게</strong> 표시됩니다.</span></li>
                  <li><b>리더가 알아야 할 3가지</b><span>우리 관점(업종·관심 주제)에 맞는 노트 3편의 핵심을 한 줄씩 뽑았습니다.</span></li>
                  <li><b>새 노트</b><span>지난 호 이후 새로 쌓인 노트. 제목을 누르면 사이트에서 전문을 봅니다.</span></li>
                </ol>
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}
