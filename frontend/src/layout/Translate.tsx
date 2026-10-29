// KO/EN — 브라우저 Google 번역 위젯 (토큰·키 없음). EN 을 누를 때만 번역 스크립트를 불러온다.
import { useState } from "react";

declare global {
  interface Window { google?: { translate: { TranslateElement: new (o: object, id: string) => void } }; googleTranslateElementInit?: () => void }
}

function setLang(lang: "ko" | "en") {
  const go = () => {
    const sel = document.querySelector<HTMLSelectElement>("select.goog-te-combo");
    if (!sel) return false;
    sel.value = lang === "en" ? "en" : "";
    sel.dispatchEvent(new Event("change"));
    return true;
  };
  if (go()) return;
  if (!document.getElementById("gt-el")) {
    const host = document.createElement("div"); host.id = "gt-el"; host.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.appendChild(host);
    window.googleTranslateElementInit = () => {
      new window.google!.translate.TranslateElement({ pageLanguage: "ko", includedLanguages: "en,ko", autoDisplay: false }, "gt-el");
      let n = 0;
      const t = window.setInterval(() => { if (go() || ++n > 40) window.clearInterval(t); }, 250);
    };
    const s = document.createElement("script");
    s.src = "https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit";
    document.head.appendChild(s);
  }
}

export function LangToggle() {
  const [lang, set] = useState<"ko" | "en">("ko");
  const pick = (l: "ko" | "en") => { set(l); setLang(l); };
  return (
    <div className="lang" role="group" aria-label="언어">
      <button className={lang === "ko" ? "on" : ""} onClick={() => pick("ko")}>KO</button>
      <button className={lang === "en" ? "on" : ""} onClick={() => pick("en")}>EN</button>
    </div>
  );
}
