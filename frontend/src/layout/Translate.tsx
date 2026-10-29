// 언어 선택 — 브라우저 Google 번역 위젯 (서버·토큰·키 없음). Streamlit 판 app/translate_widget.py 와 같은 방식:
// 언어를 고르면 googtrans 쿠키(/ko/<언어>)를 심거나 지우고 새로고침한다. 쿠키가 있으면 처음 열 때 위젯을 불러 그 언어로 보인다.
// 예전(바로 바꾸기)에는 ① 위쪽 배너가 생겨 화면이 40px 밀리고 ② 새로고침하면 한국어로 보이는데 쿠키는 남아
// ③ 그 상태에서 KO 를 누르면 오히려 영어로 바뀌었다 (2026-10-29). 버튼 상태는 쿠키 하나로만 정한다.
// 헤더에는 '🌐 KO' 버튼 하나, 누르면 언어 목록이 뜬다. 로고·이 메뉴처럼 바뀌면 안 되는 곳은 class="notranslate".
import { useEffect, useRef, useState } from "react";

declare global {
  interface Window { google?: { translate: { TranslateElement: new (o: object, id: string) => void } }; axTranslateInit?: () => void }
}

// (Google 번역 코드, 버튼 표시, 그 나라 말로 쓴 이름)
const LANGS: [string, string, string][] = [
  ["ko", "KO", "한국어"], ["en", "EN", "English"], ["zh-CN", "中文", "中文(简体)"], ["ja", "日本語", "日本語"], ["vi", "VI", "Tiếng Việt"],
];

function current(): string {
  const m = document.cookie.match(/(?:^|;\s*)googtrans=\/ko\/([A-Za-z-]+)/);
  return m && LANGS.some(([c]) => c === m[1]) ? m[1] : "ko";
}

function setCookie(v: string) {
  const exp = v ? "" : ";expires=Thu, 01 Jan 1970 00:00:00 GMT";
  const host = location.hostname;
  // 위젯은 호스트·상위 도메인 두 곳에 쿠키를 쓰므로 둘 다 맞춘다.
  document.cookie = `googtrans=${v};path=/${exp}`;
  if (host.includes(".")) document.cookie = `googtrans=${v};path=/;domain=.${host}${exp}`;
}

/** 앱 시작 때 한 번 — 다른 언어를 골라 둔 방문자면 위젯을 불러온다. */
export function initTranslate() {
  const lang = current();
  // 관리 화면은 번역하지 않는다 — 외부 스크립트가 관리자 권한 화면에서 돌거나 구독자 이메일 등이 번역으로 나가지 않게
  if (lang === "ko" || location.pathname.startsWith("/admin") || document.getElementById("gt-el")) return;
  const host = document.createElement("div");
  host.id = "gt-el"; host.style.display = "none";
  document.body.appendChild(host);
  window.axTranslateInit = () => {
    new window.google!.translate.TranslateElement(
      { pageLanguage: "ko", includedLanguages: LANGS.map(([c]) => c).filter((c) => c !== "ko").join(","), autoDisplay: false }, "gt-el");
  };
  const s = document.createElement("script");
  s.src = "https://translate.google.com/translate_a/element.js?cb=axTranslateInit";
  document.head.appendChild(s);
}

export function LangToggle() {
  const now = current();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const go = (code: string) => {
    setOpen(false);
    if (code === now) return;
    setCookie(code === "ko" ? "" : `/ko/${code}`);
    location.reload();
  };
  const label = LANGS.find(([c]) => c === now)?.[1] || "KO";
  return (
    <div className="lang-pick notranslate" translate="no" ref={box}>
      <button type="button" className="lang-btn" aria-haspopup="menu" aria-expanded={open} aria-label="언어 선택 · Language"
        onClick={() => setOpen((o) => !o)}>🌐 {label}</button>
      {open && (
        <div className="lang-menu" role="menu">
          <div className="lang-cap">언어 선택 · Language</div>
          {LANGS.map(([code, , name]) => (
            <button key={code} type="button" role="menuitemradio" aria-checked={code === now} className={code === now ? "on" : ""} onClick={() => go(code)}>
              <span>{name}</span>{code === now && <b>✓</b>}
            </button>
          ))}
          <div className="lang-note">한국어 외 언어는 자동 번역입니다</div>
        </div>
      )}
    </div>
  );
}
