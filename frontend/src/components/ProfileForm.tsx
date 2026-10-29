// 참여형 콘텐츠 공용 조각 (Streamlit 판 app/play_ui.py) — 선택 프로필 폼, 공유 유입 기록, '결과 공유하기' 버튼.
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, post, track } from "../api";
import ShareBar from "./ShareBar";
import { Alert } from "./ui";

export const GENDERS = ["남성", "여성", "응답 안 함"];
export const AGES = ["14~29세", "30대", "40대", "50대", "60대 이상"]; // 만 14세 미만은 받지 않는다
export const COUNTRIES = ["대한민국", "미국", "중국", "일본", "베트남", "인도", "대만", "싱가포르", "인도네시아", "태국", "말레이시아",
  "필리핀", "독일", "영국", "프랑스", "튀르키예", "멕시코", "브라질", "캐나다", "호주"];
export const KR_REGIONS = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];

type Profile = { gender: string; age: string; country: string; region: string };
const KEY = "axreview-profile"; // 저장한 프로필은 라벨 표시용으로만 브라우저에 남긴다 (서버 조회 API 없음)

function loadProfile(): Profile | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || "null");
    return p && typeof p === "object" && p.country ? (p as Profile) : null;
  } catch {
    return null;
  }
}

/** 성별·연령대·지역 (선택). 참여 통계·지도에만 쓰고 개인을 알아볼 수 있는 정보는 받지 않는다. */
export default function ProfileForm({ source }: { source: string }) {
  const [me, setMe] = useState<Profile | null>(() => loadProfile());
  const [f, setF] = useState<Profile>(() => me ?? { gender: GENDERS[2], age: AGES[1], country: COUNTRIES[0], region: "-" });
  const [agree, setAgree] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const label = me ? `📍 통계 참여 중 · ${me.country} ${me.region} · ${me.age} (바꾸기)` : "📍 참여 통계에 보태기 (선택)";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!agree) return setMsg({ kind: "err", text: "동의해야 저장할 수 있습니다." });
    setBusy(true);
    try {
      const region = f.country === "대한민국" && f.region !== "-" ? f.region : "";
      await post("profile", { gender: f.gender, age: f.age, country: f.country, region, agree: true });
      const saved = { ...f, region };
      setMe(saved);
      try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* 사생활 보호 모드 */ }
      setMsg({ kind: "ok", text: "참여 통계에 반영했습니다. 고맙습니다!" });
    } catch (err) {
      setMsg({ kind: "err", text: (err as ApiError).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="expander profile-form" key={source}>
      <summary>{label}</summary>
      <div className="body">
        <p className="caption">
          <b>개인정보 수집·이용 안내 (선택)</b> · 항목: 성별·연령대·국가·국내 시·도 · 목적: 참여 통계·참여 지도 (서로 다른 참여자 3명 미만인 칸은 공개하지 않음)
          · 보유: 마지막 참여 후 13개월 · 동의하지 않아도 모든 기능을 쓸 수 있습니다. 이름·연락처는 받지 않고, IP로 위치를 추적하지 않습니다.
          만 14세 미만은 입력하지 마세요. <Link to="/privacy">개인정보 처리방침</Link>
        </p>
        <form onSubmit={submit}>
          <div className="row2">
            <div className="field"><label>성별</label>
              <select value={f.gender} onChange={(e) => setF({ ...f, gender: e.target.value })}>{GENDERS.map((g) => <option key={g}>{g}</option>)}</select></div>
            <div className="field"><label>연령대</label>
              <select value={f.age} onChange={(e) => setF({ ...f, age: e.target.value })}>{AGES.map((a) => <option key={a}>{a}</option>)}</select></div>
          </div>
          <div className="row2">
            <div className="field"><label>국가</label>
              <select value={f.country} onChange={(e) => setF({ ...f, country: e.target.value })}>{COUNTRIES.map((c) => <option key={c}>{c}</option>)}</select></div>
            <div className="field"><label>시·도 (대한민국)</label>
              <select value={f.region || "-"} onChange={(e) => setF({ ...f, region: e.target.value })}>{["-", ...KR_REGIONS].map((r) => <option key={r}>{r}</option>)}</select></div>
          </div>
          <label className="check"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> 만 14세 이상이며 위 수집·이용에 동의합니다</label>
          <button className="btn primary" style={{ marginTop: 10 }} disabled={busy}>저장</button>
        </form>
        {msg && <Alert kind={msg.kind}>{msg.text}</Alert>}
      </div>
    </details>
  );
}

/** 공유 링크(?s=1)로 들어온 방문을 세션당 한 번 기록한다. */
export function useShareVisit(content: string) {
  const [params] = useSearchParams();
  useEffect(() => {
    if (params.get("s") !== "1") return;
    const k = `_sv_${content}`;
    try {
      if (sessionStorage.getItem(k)) return;
      sessionStorage.setItem(k, "1");
    } catch { /* 저장 못 해도 기록은 한다 */ }
    track("share_visit", content);
  }, [params, content]);
}

type ShareProps = { content: string; path: string; params?: Record<string, string | number>; title: string; note?: string; text?: string; image?: string };

/** '🔗 결과 공유하기'를 누르면 기록하고 공유용 링크와 카카오톡·LinkedIn·복사 버튼을 보여 준다.
 *  path 가 /s/… (미리보기 주소)면 받는 사람 화면에 결과별 이미지가 뜨고, 아니면 ?s=1 을 붙인다. */
export function ShareReveal({ content, path, params = {}, title, note, text, image }: ShareProps) {
  const q = new URLSearchParams(Object.entries(path.startsWith("/s/") ? params : { ...params, s: "1" }).map(([k, v]) => [k, String(v)]));
  const qs = q.toString();
  const url = qs ? (path.includes("?") ? `${path}&${qs}` : `${path}?${qs}`) : path;
  const key = `_shared_${content}_${url}`;
  const [shown, setShown] = useState<boolean>(() => {
    try { return !!sessionStorage.getItem(key); } catch { return false; }
  });
  useEffect(() => {
    try { setShown(!!sessionStorage.getItem(key)); } catch { setShown(false); }
  }, [key]);
  if (!shown) {
    return (
      <button className="btn block" type="button" onClick={() => {
        try { sessionStorage.setItem(key, "1"); } catch { /* 무시 */ }
        track("share", content, url);
        setShown(true);
      }}>🔗 결과 공유하기</button>
    );
  }
  return <ShareBar note={note || "링크를 받은 사람은 내 결과를 보고 바로 테스트할 수 있어요"} url={url} title={title} text={text} image={image} imageName={`axreview-${content}.png`} />;
}
