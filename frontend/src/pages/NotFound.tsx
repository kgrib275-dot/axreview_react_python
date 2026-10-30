// 없는 경로 (/App.tsx 의 path="*"). 서버(api/main.py spa)도 같은 경로에 404 를 주므로 검색 엔진의 soft 404 로 잡히지 않는다.
import { useEffect } from "react";
import { Link } from "react-router-dom";

export default function NotFound() {
  useEffect(() => {
    const prev = document.title;
    document.title = "페이지를 찾을 수 없습니다 — AX Review";
    return () => { document.title = prev; };
  }, []);
  return (
    <>
      <div className="eyebrow">404</div>
      <h2 className="sec-h">페이지를 <span className="grad">찾을 수 없습니다</span></h2>
      <p className="sec-p">주소가 바뀌었거나 잘못 입력됐을 수 있습니다. 아래에서 이어 가세요.</p>
      <div className="btn-row" style={{ marginTop: 16 }}>
        <Link className="btn primary" to="/notes">노트 목록</Link>
        <Link className="btn" to="/today">오늘의 AX</Link>
        <Link className="btn" to="/type">AX 테스트</Link>
        <Link className="btn" to="/">홈</Link>
      </div>
    </>
  );
}
