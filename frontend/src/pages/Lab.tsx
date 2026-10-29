// AX 데이터 랩 (/lab) — 백엔드가 만든 인터랙티브 대시보드 HTML 문서(/api/lab/html)를 iframe srcdoc 으로 띄운다.
// 높이는 문서가 postMessage 로 알려 주면 그 값, 아니면 1400px (DocFrame).
import { get } from "../api";
import { SubscribeCTA } from "../components/Dialogs";
import DocFrame from "../components/DocFrame";
import { Alert, Guide, useLoad } from "../components/ui";

export default function Lab() {
  const { data, error, loading } = useLoad<string>(() => get<string>("lab/html").then((h) => (typeof h === "string" ? h : String(h ?? ""))), []);
  return (
    <div className="lab-page">
      <div className="eyebrow">AX Data Lab</div>
      <h2 className="sec-h">수집 데이터를 <span className="grad">직접 탐색</span>하세요</h2>
      <p className="muted" style={{ margin: "0 0 6px" }}>AX Review가 매일 읽는 기사에서 어떤 주제가 함께 움직이는지 보여 줍니다. 기간·소스 그룹·키워드를 고르면 모든 차트가 함께 좁혀지고, ▶ 버튼으로 날짜별로 자라는 모습을 재생할 수 있습니다.</p>
      <Guide title="여기서 볼 것" items={[
        ["급상승 키워드", "오른쪽 패널 맨 위 — 최근 갑자기 많이 잡힌 주제입니다."],
        ["키워드 네트워크", "원을 누르면 함께 나온 키워드와 대표 기사, 스트림·히트맵이 그 키워드로 좁혀집니다."],
        ["▶ 타임랩스", "필터 줄의 재생 버튼으로 날짜별로 주제가 자라는 모습을 봅니다."],
        ["지식 지도", "맨 아래 — 비슷한 글끼리 모인 무리를 확대해 보고 점을 눌러 원문을 엽니다."],
      ]} />
      {loading && !data && <div className="page-loading">데이터 랩을 그리는 중...</div>}
      {error && <Alert kind="err">{error}</Alert>}
      {data && <DocFrame html={data} title="AX 데이터 랩 인터랙티브 대시보드" fallback={1400} />}
      <div className="space" />
      <SubscribeCTA source="lab" headline="이 데이터가 매주 노트가 됩니다" sub="급상승 키워드를 편집자가 읽고 정리한 노트를 월요일마다 메일로 받아 보세요." />
    </div>
  );
}
