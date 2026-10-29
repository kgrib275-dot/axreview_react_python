// 내 추천 현황 (/refer?k=구독자 토큰) — Streamlit 판 app_pages/refer.py 이식.
// 이메일 일부만 보여 주고 추천 링크·진행 상황·보상(지난 호 PDF)을 준다.
import { useSearchParams } from "react-router-dom";
import { get } from "../api";
import ShareBar from "../components/ShareBar";
import { Alert, useLoad } from "../components/ui";

type Refer = {
  email: string; code: string; count: number; unlocked: boolean; link: string;
  pdfs?: { name: string; label: string; url?: string; locked: boolean; latest?: boolean }[];
  reward_at?: number; // 계약 외 — 없으면 Streamlit 판 referral.REWARD_AT(3)
};

export default function ReferPage() {
  const [params] = useSearchParams();
  const k = params.get("k") || "";
  const { data, error, loading } = useLoad(
    () => (k ? get<Refer>(`refer?k=${encodeURIComponent(k)}`) : Promise.resolve(null)),
    [k],
  );

  const head = (
    <>
      <div className="eyebrow">Referral</div>
      <h2 className="sec-h">친구를 초대하고 <span className="grad">지난 호 전체</span>를 받으세요</h2>
    </>
  );
  if (loading && k) return <>{head}<div className="page-loading">불러오는 중…</div></>;
  if (!data || error) {
    return (
      <>
        {head}
        <Alert kind="info">✉ 메일 하단의 '내 추천 링크 받기'로 들어와 주세요. 구독을 해지했다면 다시 구독한 뒤 다음 메일의 링크를 쓰면 됩니다.</Alert>
      </>
    );
  }

  const goal = data.reward_at || 3;
  const done = Math.min(data.count, goal);
  const pct = Math.round((done / goal) * 100);
  const pdfs = data.pdfs || [];

  return (
    <>
      {head}
      <div className="guide">
        <div className="guide-h">📬 {data.email} 님의 추천 현황</div>
        <div style={{ fontSize: "2.2rem", fontWeight: 900, margin: "4px 0" }}>
          {data.count}명 <span style={{ fontSize: "1rem", color: "var(--muted)" }}>/ 목표 {goal}명</span>
        </div>
        <div style={{ height: 8, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden", margin: "6px 0 4px" }}
          role="progressbar" aria-valuemin={0} aria-valuemax={goal} aria-valuenow={done}>
          <div style={{ height: "100%", width: `${pct}%`, background: "linear-gradient(90deg,#0A6FD6,#5BC2F5)" }} />
        </div>
        <span style={{ color: "var(--muted)", fontSize: ".84rem" }}>내 링크로 처음 구독하고 확인 메일까지 누른 사람만 셉니다. 구독을 해지하면 빠집니다.</span>
      </div>
      <pre className="box" style={{ margin: "8px 0", padding: "12px 14px", fontFamily: "var(--f-mono)", fontSize: ".9rem", overflow: "auto", whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{data.link}</pre>
      <ShareBar
        note="이 링크로 구독하면 추천으로 셉니다" url={data.link} title="AX Review — 기업 AX 노트를 매주 메일로"
        text="기업 AI 전환(AX) 사례를 매주 한 번 정리해 보내 주는 뉴스레터인데, 실무에 꽤 도움이 됩니다. 구독은 무료예요."
      />

      <h3 style={{ fontSize: "1.25rem", margin: "26px 0 10px" }}>지난 호 주간 PDF</h3>
      {!pdfs.length && <p className="caption">아직 만들어진 PDF가 없습니다.</p>}
      <ul className="sec-p" style={{ paddingLeft: 22, margin: 0 }}>
        {pdfs.map((f) => {
          const label = f.label || f.name.replace(/^axreview_/, "").replace(/\.pdf$/, "");
          const open = !f.locked && f.url;
          return (
            <li key={f.name}>
              {open ? (
                <><a href={f.url}>{label} 주간 리포트</a>{f.latest ? " · 최신 호" : ""}</>
              ) : (
                <>🔒 {label} 주간 리포트 — {Math.max(1, goal - data.count)}명 더 초대하면 열립니다</>
              )}
            </li>
          );
        })}
      </ul>
    </>
  );
}
