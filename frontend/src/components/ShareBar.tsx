// 공유 바 — 카카오톡·LinkedIn·결과 카드 받기·링크 복사·기기 공유 (Streamlit 판 app/note_ui.share_bar 와 같은 동작).
// url 은 /s/… 공유 주소(미리보기 이미지가 결과별로 뜸) 또는 현재 주소.
import { useState } from "react";
import { useMe } from "../me";

declare global {
  interface Window { Kakao?: { isInitialized(): boolean; init(k: string): void; Share: { sendScrap(o: { requestUrl: string }): void } } }
}

type Props = { note?: string; url?: string; title?: string; text?: string; image?: string; imageName?: string };

export default function ShareBar({ note = "", url, title, text, image, imageName = "axreview-result.png" }: Props) {
  const { me } = useMe();
  const [flash, setFlash] = useState<Record<string, string>>({});
  const abs = () => new URL(url || location.href, location.origin).href;
  const done = (k: string, msg: string) => {
    setFlash((f) => ({ ...f, [k]: msg }));
    setTimeout(() => setFlash((f) => ({ ...f, [k]: "" })), 1600);
  };
  const copy = async (k: string, msg: string) => {
    try {
      await navigator.clipboard.writeText(abs());
      done(k, msg);
    } catch {
      prompt("아래 주소를 복사하세요", abs());
    }
  };
  const kakao = async () => {
    const key = me?.kakao_key;
    if (key) {
      const go = () => {
        try {
          if (!window.Kakao!.isInitialized()) window.Kakao!.init(key);
          window.Kakao!.Share.sendScrap({ requestUrl: abs() });
        } catch (e) { console.warn(e); }
      };
      if (window.Kakao) return go();
      const s = document.createElement("script");
      s.src = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.4/kakao.min.js";
      s.crossOrigin = "anonymous";
      s.onload = go;
      document.head.appendChild(s);
      return;
    }
    if (navigator.share && matchMedia("(pointer: coarse)").matches) return navigator.share({ title: title || document.title, url: abs() }).catch(() => undefined);
    copy("kakao", "복사됨 — 카톡에 붙여넣기 ✓");
  };
  const linkedin = () => {
    const body = (text || title || document.title) + "\n" + abs();
    window.open("https://www.linkedin.com/feed/?shareActive=true&text=" + encodeURIComponent(body), "_blank", "noopener");
  };
  return (
    <div className="nt-bar">
      <span className="nt-read">{note}</span>
      <span className="sp" />
      <button className="act kakao" type="button" onClick={kakao}>{flash.kakao || "카카오톡"}</button>
      <button className="act li" type="button" onClick={linkedin}>LinkedIn</button>
      {image && <a className="act" href={image} download={imageName}>🖼 결과 카드 받기</a>}
      <button className="act" type="button" onClick={() => copy("copy", "복사됨 ✓")}>{flash.copy || "🔗 링크 복사"}</button>
      {typeof navigator !== "undefined" && "share" in navigator && (
        <button className="act" type="button" onClick={() => navigator.share({ title: title || document.title, url: abs() }).catch(() => undefined)}>공유</button>
      )}
    </div>
  );
}
