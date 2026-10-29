// KO/EN — 브라우저 Google 번역 위젯 (서버·토큰·키 없음). Streamlit 판 app/translate_widget.py 와 같은 방식:
// 버튼을 누르면 googtrans 쿠키(/ko/en)를 심거나 지우고 새로고침한다. 쿠키가 있으면 처음 열 때 위젯을 불러 영어로 보인다.
// 예전(바로 바꾸기)에는 ① 위쪽 배너가 생겨 화면이 40px 밀리고 ② 새로고침하면 한국어로 보이는데 쿠키는 남아
// ③ 그 상태에서 KO 를 누르면 오히려 영어로 바뀌었다 (2026-10-29). 버튼 상태는 쿠키 하나로만 정한다.
// 로고·이 버튼처럼 바뀌면 안 되는 곳은 class="notranslate".

declare global {
  interface Window { google?: { translate: { TranslateElement: new (o: object, id: string) => void } }; axTranslateInit?: () => void }
}

const isEn = () => /(^|;\s*)googtrans=\/ko\/en/.test(document.cookie);

function setCookie(v: string) {
  const exp = v ? "" : ";expires=Thu, 01 Jan 1970 00:00:00 GMT";
  const host = location.hostname;
  // 위젯은 호스트·상위 도메인 두 곳에 쿠키를 쓰므로 둘 다 맞춘다.
  document.cookie = `googtrans=${v};path=/${exp}`;
  if (host.includes(".")) document.cookie = `googtrans=${v};path=/;domain=.${host}${exp}`;
}

/** 앱 시작 때 한 번 — 영어로 보기를 골라 둔 방문자면 위젯을 불러온다. */
export function initTranslate() {
  if (!isEn() || document.getElementById("gt-el")) return;
  const host = document.createElement("div");
  host.id = "gt-el"; host.style.display = "none";
  document.body.appendChild(host);
  window.axTranslateInit = () => {
    new window.google!.translate.TranslateElement({ pageLanguage: "ko", includedLanguages: "en", autoDisplay: false }, "gt-el");
  };
  const s = document.createElement("script");
  s.src = "https://translate.google.com/translate_a/element.js?cb=axTranslateInit";
  document.head.appendChild(s);
}

export function LangToggle() {
  const en = isEn();
  const go = (toEn: boolean) => {
    if (toEn === en) return;
    setCookie(toEn ? "/ko/en" : "");
    location.reload();
  };
  return (
    <div className="lang notranslate" role="group" aria-label="언어" translate="no">
      <button className={!en ? "on" : ""} aria-pressed={!en} onClick={() => go(false)}>KO</button>
      <button className={en ? "on" : ""} aria-pressed={en} onClick={() => go(true)}>EN</button>
    </div>
  );
}
