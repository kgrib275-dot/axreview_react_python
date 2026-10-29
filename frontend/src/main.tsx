import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./styles/theme.css";
import { startFx } from "./fx";
import { initTranslate } from "./layout/Translate";

// Google 번역은 글자를 <font> 로 감싸 DOM 을 바꾼다 — React 가 바뀐 노드를 지우거나 앞에 넣으려다 화면이 깨지지 않게
// (React 이슈 #11538 의 알려진 우회). 부모가 다르면 조용히 넘어간다.
const _remove = Node.prototype.removeChild;
Node.prototype.removeChild = function <T extends Node>(this: Node, child: T): T {
  if (child.parentNode !== this) return child;
  return _remove.call(this, child) as T;
};
const _insert = Node.prototype.insertBefore;
Node.prototype.insertBefore = function <T extends Node>(this: Node, node: T, ref: Node | null): T {
  if (ref && ref.parentNode !== this) return _insert.call(this, node, null) as T;
  return _insert.call(this, node, ref) as T;
};

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);

initTranslate(); // 영어로 보기를 골라 둔 방문자만 번역 위젯을 불러온다
startFx(); // 스포트라이트·카드 기울기·등장·진행 바·히어로 구체 (v1 app/fx.py)
