// 소개 (/about) — Streamlit 판 app_pages/about.py 이식. 숫자 띠·흐름선 스타일은 Home.css 를 같이 쓴다.
import { Link } from "react-router-dom";
import { get } from "../api";
import { useDialogs } from "../components/Dialogs";
import { useLoad } from "../components/ui";
import { CountUp } from "./Home";
import "./Home.css";

type About = {
  sources?: Record<string, { name: string; url: string }[]>;
  // 계약의 counts 는 항목이 정해져 있지 않아 홈과 같은 이름(notes·sources) + articles·issues 를 기대하고 없으면 0 으로 둔다.
  counts?: { sources?: number; articles?: number; articles_week?: number; notes?: number; issues?: number };
};

const STEPS: [string, string][] = [
  ["수집", "RSS 피드·공식 검색 API·목록 페이지 HTML로 국내외 소스를 하루 여러 번 읽습니다."],
  ["거르기", "같은 주소·비슷한 제목을 지우고, AX 키워드 규칙에 맞는 기사만 남깁니다."],
  ["채점", "AI가 기업 AX 관점에서 깊게 읽을 가치를 1~5점으로 매기고 한 줄 요약을 붙입니다."],
  ["노트 초안", "높은 점수의 원문을 읽고 요약·핵심 포인트·현업 실행·AX 적용 점검으로 정리합니다."],
  ["사람 검토", "편집자가 초안을 확인하고 고친 뒤에만 게시합니다."],
  ["주간 흐름", "한 주의 노트를 한 줄 흐름으로 묶어 뉴스레터·Teams·PDF로 보냅니다."],
];

const MORE: [string, string, string, string][] = [
  ["/lab", "🕸", "데이터 랩", "키워드 네트워크·히트맵·타임랩스로 수집 데이터를 탐색"],
  ["/lab", "✦", "지식 지도", "뜻이 가까운 노트·기사를 한 장의 지도로"],
  ["/diagnosis", "☑", "AX 자가진단", "12문항으로 전략·실행·기반 준비도 점검"],
  ["/ask", "💬", "AX 질문하기", "쌓인 노트를 근거로 묻고 답하기"],
];

export default function AboutPage() {
  const { openSubscribe, openContact } = useDialogs();
  const { data } = useLoad(() => get<About>("about"));
  const c = data?.counts || {};
  const nSources = c.sources ?? Object.values(data?.sources || {}).reduce((a, v) => a + v.length, 0);
  const nArticles = c.articles ?? c.articles_week ?? 0;
  const nNotes = c.notes ?? 0;
  const nIssues = c.issues ?? 0;

  const FAQ: [string, string][] = [
    ["노트는 AI가 쓰나요?", "초안은 AI가 원문을 읽고 쓰지만, 편집자가 검토하고 고친 노트만 게시합니다."],
    ["얼마나 자주 갱신되나요?", "수집은 하루 여러 번, 노트는 검토되는 대로, 주간 흐름은 매주 한 번 나옵니다."],
    ["어떤 자료를 읽나요?", `기업·AX 리더, 연구소·벤더 공식 블로그, 경영·전략 매체, 리서치, 산업별·국내 매체 등 ${nSources}곳입니다. 홈의 '어디서 찾아 읽나'에서 전체 목록을 볼 수 있습니다.`],
    ["구독을 해지하려면?", "뉴스레터 아래의 '구독 해지' 링크를 누르면 바로 해지됩니다."],
  ];

  return (
    <>
      <div className="eyebrow">About</div>
      <h2 className="sec-h">AX Review <span className="grad">소개</span></h2>
      <p className="sec-p" style={{ maxWidth: 760 }}>
        AX Review는 기업 AI 전환(AX)을 추진하며 읽은 아티클·리포트·대담을 노트로 정리하고, 매주 AX 흐름을 한 줄로 묶어 공유하는 공간입니다.
      </p>

      <div className="cols3" style={{ marginTop: 18 }}>
        {([
          ["🔭", "찾기", "국내외 리더·연구소·벤더·매체의 원문을 매일 훑어 AX에 의미 있는 후보를 고릅니다."],
          ["✏️", "정리하기", "요약에서 끝내지 않고 핵심 포인트, 현업 실행 단계, 우리 조직 적용 방안까지 붙입니다."],
          ["🗂", "쌓기", "노트를 Strategy · Implementation · Enablement로 분류해 검색 가능한 지식으로 쌓습니다."],
        ] as [string, string, string][]).map(([icon, title, desc]) => (
          <div key={title} className="box">
            <h3 style={{ fontSize: "1.15rem", marginBottom: 8 }}>{icon} {title}</h3>
            <p className="sec-p">{desc}</p>
          </div>
        ))}
      </div>

      <h3 className="sub-h">카테고리</h3>
      <div className="table-wrap">
        <table className="table">
          <thead><tr><th>카테고리</th><th>다루는 내용</th></tr></thead>
          <tbody>
            <tr><td>AX Strategy</td><td>AX 방향, 투자·조직·거버넌스, 경영진 의사결정</td></tr>
            <tr><td>AX Implementation</td><td>업무·현장별 AI 적용 사례와 파일럿 설계</td></tr>
            <tr><td>AX Enablement</td><td>데이터 기반, 플랫폼, 보안, 인재·역량</td></tr>
          </tbody>
        </table>
      </div>

      {/* ---------- 숫자로 보기 ---------- */}
      <div className="space" />
      <div className="eyebrow">By the numbers</div>
      <h3 className="sec-h" style={{ fontSize: "1.4rem" }}>숫자로 보는 <span className="grad">AX Review</span></h3>
      <div className="hero-stats" style={{ marginTop: 14 }}>
        <div><CountUp to={nSources} /><span>수집 소스</span></div>
        <div><CountUp to={nArticles} /><span>검토한 기사</span></div>
        <div><CountUp to={nNotes} /><span>게시 노트</span></div>
        <div><CountUp to={nIssues} /><span>주간 흐름</span></div>
      </div>

      {/* ---------- 만드는 과정 ---------- */}
      <div className="space" />
      <div className="eyebrow">How it works</div>
      <h3 className="sec-h" style={{ fontSize: "1.4rem" }}>원문이 <span className="grad">노트가 되기까지</span></h3>
      <ol className="flowline">
        {STEPS.map(([b, s]) => <li key={b}><b>{b}</b><span>{s}</span></li>)}
      </ol>

      <h3 className="sub-h">편집 원칙</h3>
      <div className="cols2">
        <div className="box"><b>원문을 먼저 봅니다</b><br />모든 노트에 원문 링크를 답니다. 원문에 없는 수치·사실·인용은 쓰지 않고, 추정은 '~로 보입니다'처럼 구분합니다.</div>
        <div className="box"><b>실행까지 씁니다</b><br />요약에서 끝내지 않고 현업 실행 단계와 우리 조직에 적용할 때 점검할 것을 붙입니다.</div>
      </div>

      <h3 className="sub-h">더 둘러보기</h3>
      <div className="cols3" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(min(220px,100%),1fr))" }}>
        {MORE.map(([to, icon, title, desc], i) => (
          <div key={i} className="box">
            <Link to={to} className="more">{icon} {title}</Link>
            <div className="caption" style={{ marginTop: 6 }}>{desc}</div>
          </div>
        ))}
      </div>

      <h3 className="sub-h">자주 묻는 질문</h3>
      {FAQ.map(([q, a]) => (
        <details key={q} className="expander">
          <summary>{q}</summary>
          <div className="body sec-p">{a}</div>
        </details>
      ))}

      <div className="btn-row" style={{ marginTop: 28 }}>
        <button className="btn primary" onClick={() => openSubscribe("about")}>뉴스레터 구독 →</button>
        <button className="btn" onClick={openContact}>문의하기</button>
      </div>
    </>
  );
}
