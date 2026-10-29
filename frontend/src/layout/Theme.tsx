// 라이트/다크 전환 — 시스템(OS 따름) → 라이트 → 다크 순으로 돈다. 고른 값은 localStorage "ax_theme" 에 두고
// <html data-theme> 로 건다. 첫 그림 전 적용은 index.html 의 작은 inline 스크립트가 한다 (깜빡임 방지).
import { useEffect, useState } from "react";

type Pref = "system" | "light" | "dark";
const KEY = "ax_theme";
const NEXT: Record<Pref, Pref> = { system: "light", light: "dark", dark: "system" };
const ICON: Record<Pref, string> = { system: "◐", light: "☀︎", dark: "☾" };
const LABEL: Record<Pref, string> = { system: "시스템 설정", light: "라이트", dark: "다크" };

function readPref(): Pref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

function applyPref(p: Pref) {
  const root = document.documentElement;
  if (p === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", p);
  try {
    if (p === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, p);
  } catch {
    /* 저장이 막혀 있어도 이번 화면에는 적용된다 */
  }
  // 모바일 주소창 색 — 지금 실제로 보이는 배경색에 맞춘다
  const bg = getComputedStyle(root).getPropertyValue("--bg").trim();
  if (bg) document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
}

export function ThemeToggle() {
  const [pref, setPref] = useState<Pref>(readPref);
  useEffect(() => applyPref(pref), [pref]);
  const next = NEXT[pref];
  return (
    <button type="button" className="theme-btn" onClick={() => setPref(next)}
      title={`화면 테마: ${LABEL[pref]} (눌러서 ${LABEL[next]})`} aria-label={`화면 테마: ${LABEL[pref]}. 눌러서 ${LABEL[next]}로 바꾸기`}>
      <span aria-hidden="true">{ICON[pref]}</span>
    </button>
  );
}
