// 구독 해지 (/unsubscribe?token=) — Streamlit 판 app_pages/unsubscribe.py 이식.
// 먼저 토큰으로 가린 이메일을 받아 보여 주고, 버튼을 눌러야 해지한다.
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, get, post } from "../api";
import { Alert, useLoad } from "../components/ui";

export default function UnsubscribePage() {
  const [params] = useSearchParams();
  const token = (params.get("token") || "").slice(0, 100);
  const { data, error, loading } = useLoad(
    () => (token ? get<{ email_masked: string }>(`unsubscribe?token=${encodeURIComponent(token)}`) : Promise.resolve(null)),
    [token],
  );
  const [done, setDone] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      await post("unsubscribe", { token });
      setDone(data?.email_masked || "");
    } catch (e) {
      setErr((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  };

  const invalid = !token || !!error || (!loading && !data);
  return (
    <>
      <div className="eyebrow">뉴스레터</div>
      <h2 className="sec-h">구독 해지</h2>
      {done !== null ? (
        <>
          <Alert kind="ok">{done ? `${done} 주소의 구독을 해지했습니다. ` : "구독을 해지했습니다. "}다시 받고 싶으면 홈에서 언제든 구독할 수 있습니다.</Alert>
          <Link className="more" to="/">← 홈으로</Link>
        </>
      ) : loading ? (
        <div className="page-loading">불러오는 중…</div>
      ) : invalid ? (
        <>
          <Alert kind="warn">유효하지 않은 해지 링크입니다. 메일 하단의 링크를 다시 눌러 주세요.</Alert>
          <Link className="more" to="/">← 홈으로</Link>
        </>
      ) : (
        <>
          <p className="sec-p" style={{ margin: "8px 0 14px" }}>
            아래 버튼을 누르면 AX Review 뉴스레터 구독이 해지됩니다.{data?.email_masked ? <> ({data.email_masked})</> : null}
          </p>
          <button className="btn primary" onClick={run} disabled={busy}>구독 해지하기</button>
          {err && <Alert kind="err">{err}</Alert>}
        </>
      )}
    </>
  );
}
