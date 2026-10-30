// 구독 확인 (/confirm?t=토큰) — Streamlit 판 app_pages/confirm.py 이식.
// 메일 보안 검사기·링크 미리보기가 주소를 먼저 열어도 확정되지 않도록, 버튼을 눌러야 확정한다.
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError, post } from "../api";
import { Alert } from "../components/ui";
import { useMe } from "../me";

export default function ConfirmPage() {
  const [params] = useSearchParams();
  const { setState } = useMe();
  const token = params.get("t") || "";
  const [done, setDone] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const confirm = async () => {
    setBusy(true);
    setErr(null);
    try {
      await post("subscribe/confirm", { t: token });
      setDone(true);
      setState({ subscribed: true, sub_pending: null });  // 확인 대기 → 구독 완료
    } catch (e) {
      setErr((e as ApiError).message || "링크가 만료됐거나 이미 확인된 신청입니다. 구독 창에서 다시 신청해 주세요.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="eyebrow">구독 확인</div>
      <h2 className="sec-h">구독 <span className="grad">확인</span></h2>
      {done ? (
        <Alert kind="ok">📬 구독이 완료됐습니다. 다음 호부터 매주 월요일에 보내 드릴게요.</Alert>
      ) : !token ? (
        <Alert kind="info">✉ 확인 메일의 '구독 확인하기' 링크로 들어와 주세요.</Alert>
      ) : (
        <>
          <p className="sec-p" style={{ margin: "8px 0 14px" }}>아래 버튼을 누르면 AX Review 주간 메일 구독이 완료됩니다.</p>
          <button className="btn primary" onClick={confirm} disabled={busy}>✓ 구독 확인하기</button>
          {err && <Alert kind="err">{err}</Alert>}
        </>
      )}
    </>
  );
}
