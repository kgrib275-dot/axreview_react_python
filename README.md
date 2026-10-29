# AX Review — React + FastAPI 판

Streamlit 판(AxReview)을 **React(화면) + FastAPI(Python API)** 로 나눠 다시 만든 독립 프로젝트입니다.
**2026-10-29부터 운영·개발은 이 프로젝트에서만 합니다** — Streamlit 판은 더 고치지 않습니다(필요할 때만 따로).

- 저장소: https://github.com/kgrib275-dot/axreview_react_python (Streamlit 판은 별도 저장소 `axreview`)
- 공개 주소: Tailscale Funnel 10000 (`start-public.bat` 창에 표시)

폴더·가상환경·DB·설정·Databricks 스키마·실행 스크립트·로컬 포트가 모두 따로입니다.
다만 동시에 돌리면 겹치는 것이 있습니다: ① 외부 공개(Funnel 10000)는 한쪽만 ② `.env` 의 Gemini 키·Databricks 토큰을 복사해 왔으므로
두 공개 서버가 모두 배치를 돌리면 Gemini 하루 한도를 같이 씀 — 계속 둘 다 운영하려면 이 프로젝트용 키를 따로 넣으세요.

| | Streamlit 판 | 이 프로젝트 |
|---|---|---|
| 화면 | Streamlit (서버가 매번 다시 그림) | React 18 + TypeScript (브라우저가 그림, 빌드 결과를 서버가 그대로 제공) |
| 서버 | Streamlit 한 프로세스 | FastAPI + uvicorn (`/api/…` JSON) |
| 동시 100명 첫 응답 (실측, 이 PC) | 15.7초 | **0.7초** (95% 1.0초) |
| 개발 포트 / 공개 로컬 포트 | 4002 / 4012~ | **5002** (화면 개발 5173) / **5012~** |
| DB | `AxReview/data/axreview.db` | `backend/data/axreview.db` |
| Databricks 스키마 기본값 | `axreview` | **`axreview_react`** |
| 작업 스케줄러 이름 | `AXReview Public` | **`AXReview React Public`** |

## 0. 엔진은 Streamlit 판의 "복사본"입니다

화면 언어(React·TypeScript)와 서버 설계(FastAPI API)만 새로 만들었고, **데이터 엔진은 Streamlit 판 코드를 2026-10-28 시점에 복사해 왔습니다.**

| 복사해 온 것 (엔진) | 새로 만든 것 |
|---|---|
| `backend/pipeline/` — 수집·채점·노트 초안·주간 흐름·메일·Databricks 적재·참여 기록·개인정보 처리 규칙 | `backend/api/` — 화면이 쓰는 JSON API (공개 12개·관리 16개 라우터) |
| `backend/config/` — 수집 소스·키워드 | `frontend/` — 화면 전체 (공개 15개·관리 15개) |
| `backend/app/` 의 `ax_types.py`·`glossary.py`·`og_cards.py`·`datalab.py`·`geo_map.py`·`web.py`·`og_meta.py` (콘텐츠·공유 이미지·검색용 HTML) | `start-public`·`start-dev`·`install-autostart` |

**같은 코드가 아니라 복사본이라, 한쪽을 고쳐도 다른 쪽에는 반영되지 않습니다.**
- 이 프로젝트로 정착했으므로(2026-10-29) 엔진도 **여기만** 고칩니다. Streamlit 판과는 시간이 지나며 동작이 달라질 수 있습니다.
- Streamlit 판에도 같은 수정이 필요하면 그때 따로 옮깁니다.

복사할 때 이 프로젝트에 맞게 바꾼 엔진 부분 (Streamlit 판과 다름):
| 항목 | Streamlit 판 | 이 프로젝트 |
|---|---|---|
| Databricks 기본 스키마 (`pipeline/warehouse.py`) | `axreview` | `axreview_react` |
| `SITE_URL` 기본값 (`pipeline/mailer.py`) | `http://localhost:4002` | `http://localhost:5002` |
| 공유 메타 넣는 곳 (`app/og_meta.py`) | Streamlit 의 `index.html` 파일에 기록 | 서버가 `frontend/dist/index.html` 을 내보낼 때 **페이지별로** 넣음 (파일은 그대로 — 다시 빌드해도 안 빠짐) |
| 의미 검색 한도 | 세션당 40회 | 방문자당 하루 40회 (API 에는 세션이 없음) |
| 용어 퀴즈 채점 | 서버 세션이 정답을 기억 | 정답을 숨긴 채 `seed` 로 같은 문제를 다시 만들어 채점 |

API 로 옮기며 생긴 그 밖의 차이(응답에 더한 필드 등)는 `docs/API-notes-backend-public.md`·`docs/API-notes-backend-admin.md`.

## 1. 구조
```
backend/                 Python 3.12 · FastAPI
  api/main.py            앱: /api 라우터 자동 등록 + 검색·공유 페이지 + 정적 파일 + React 빌드(SPA) + 스케줄러
  api/deps.py            방문자(서명 쿠키 axv)·관리자 판정·남용 제한
  api/routers/           공개 API 12개 + 관리 API 16개 (admin_*.py)
  pipeline/              데이터·배치 (수집·채점·노트·주간 흐름·메일·Databricks·참여·개인정보 처리방침 …)
  app/                   콘텐츠(유형 테스트·용어)·공유 이미지·검색용 HTML(web.py)·데이터 랩/지도 문서
  config/                수집 소스 83곳(sources.yaml)·후보·키워드
  static/                로고·공유 이미지(og/)·d3 등
  tools/                 import_content.py(콘텐츠 가져오기)·check_feeds.py(피드 점검)
  serve.py               실행기
frontend/                Vite + React 18 + TypeScript (외부 UI 라이브러리 없음)
  src/pages/             공개 화면 15개 + admin/ 관리 화면 15개
  src/components/ layout/  공유 바·대화상자·노트 카드·헤더·푸터·구독 띠·KO/EN
docs/API.md              화면 ↔ API 계약,  docs/API-notes-*.md 구현 메모(계약에 덧붙인 필드)
start-public.bat/.ps1    외부 공개 (Tailscale Funnel)
start-dev.bat            개발 실행 (백엔드 자동 재시작 + 화면 개발 서버)
install-autostart.ps1    로그온 시 자동 시작 + 절전 해제
```

## 2. 설치 (처음 한 번)
요구 사항: Windows, Python 3.12, Node.js 20+, Microsoft Edge(PDF·공유 이미지 렌더링).
```powershell
cd backend
py -3.12 -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env    # 없으면 아래 3장 표대로 직접 작성
cd ..\frontend
npm install
npm run build             # frontend\dist 생성 (start-public 이 자동으로도 함)
```
콘텐츠를 Streamlit 판에서 가져오려면(기사·노트·주간 흐름·키워드만, 개인정보 제외):
```powershell
cd backend
venv\Scripts\python tools\import_content.py "C:\...\AxReview\data\axreview.db"
```
> 이 폴더는 처음 만들 때 이미 한 번 가져왔습니다 (기사 1,108 · 노트 22 · 주간 흐름 1 · 키워드 20).

## 3. 환경 변수 (`backend/.env`)
| 변수 | 용도 |
|---|---|
| `GEMINI_API_KEYS` | 쉼표로 여러 개 — 채점·노트·주간 흐름·질문하기·임베딩 |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASS` `SMTP_FROM` `SMTP_TLS` | 구독 확인·뉴스레터 메일 |
| `SITE_URL` | 메일·공유·sitemap 주소 (start-public 이 공개 주소로 자동 설정) |
| `DATABRICKS_SERVER_HOSTNAME` `DATABRICKS_HTTP_PATH` `DATABRICKS_TOKEN` | Databricks 적재 연결 — **이 프로젝트 전용 값으로 따로 넣을 수 있습니다** |
| `DATABRICKS_CATALOG` / `DATABRICKS_SCHEMA` | 기본 `workspace` / **`axreview_react`** — 같은 워크스페이스를 써도 Streamlit 판(`axreview`)과 테이블이 섞이지 않음 |
| `ADMIN_TOKEN` | 관리 API 토큰. 비우면 로컬 접속·등록 IP만 관리자. 넣으면 관리 화면에서 한 번 입력해 다른 PC에서도 관리 가능 (`X-Admin-Token`) |
| `NAVER_*` `REDDIT_*` `KAKAO_JS_KEY` `ALERT_EMAIL` | 선택 (Streamlit 판과 같음) |
| `AXREVIEW_PORT` `AXREVIEW_HOST` `AXREVIEW_SCHEDULER=1` `AXREVIEW_NO_SCHEDULER=1` `AXREVIEW_DB` | 실행 옵션 |

Databricks 적재 상태는 이 프로젝트 DB 안에 따로 기억합니다 — 처음 적재하면 `axreview_react` 스키마에 모든 테이블을 새로 만듭니다.
관리 > Databricks 적재에서 접속 시험·적재·전체 다시 적재.

## 4. 실행
| 목적 | 방법 | 주소 |
|---|---|---|
| 개발 | `start-dev.bat` (백엔드 코드 바뀌면 자동 재시작, 화면은 즉시 반영) | 화면 http://localhost:5173 · API http://localhost:5002 |
| 로컬 한 프로세스 | `npm run build` 후 `cd backend && venv\Scripts\python serve.py` | http://localhost:5002 |
| 외부 공개 | `start-public.bat` | 창에 표시되는 `https://<PC>.<tailnet>.ts.net:<포트>` |
| 자동 시작 | `powershell -ExecutionPolicy Bypass -File install-autostart.ps1` | 로그온 1분 뒤 공개 서버 |

`start-public` 이 하는 일: 이 프로젝트의 공개 창이 이미 떠 있으면 그 창과 서버를 끔(두 개가 돌면 배치가 두 번 돎) → 소스가 바뀌었으면 화면 빌드 → 비어 있는 로컬 포트(5012~) 선택 → `SITE_URL`·스케줄러 켜기 → Tailscale Funnel 공개 →
서버가 죽으면 5초 뒤 재시작 → Ctrl+C 면 Funnel 포트가 **아직 이 서버를 가리킬 때만** 해제 (다른 서버가 넘겨받았으면 그대로 둠).

> **Funnel 포트**: 10000 을 씁니다 (443 = Trade_IQ · 8443 = 다른 프로젝트). 10000 을 기존 Streamlit 판이 쓰고 있으면 그 공개를 끄고 넘겨받습니다.
> 기존 서버는 켜진 채 남으니 필요 없으면 그 창을 닫으세요 — Streamlit 판 start-public 도 같은 규칙이라 닫아도 이 사이트 공개는 유지됩니다.
> 반대로 이 사이트가 10000 을 쓰는 동안 Streamlit 판 start-public 을 실행하면 넘겨받지 않고 "다른 서비스가 쓰고 있습니다" 로 멈춥니다.
> 다른 포트를 쓰려면 `set AXREVIEW_FUNNEL_PORT=8443` 후 실행.

로컬(127.0.0.1) 접속은 관리자입니다 — 화면 상단 '관리' → `/admin`.

## 5. 기능 (Streamlit 판과 같음)
- **공개**: 이번 호(흐름·에디터 코멘트·리더 3가지·나를 위한 추천·급상승 띠·최신 노트 60초 갱신) · 노트(검색·의미 검색·분류·종류·업종 필터·인기순·북마크·상세 목차·관련 노트·공유) ·
  오늘의 AX(퀴즈·예측·연속 참여·오늘의 용어·참여 지도) · 데이터 랩 · AX 질문하기(무료 3회·월 구독 코드·웹 검색 보완) · 소개 ·
  AX 테스트(리더 유형 16종·용어 퀴즈·준비도 자가진단) · 뉴스레터 미리보기 · 추천 현황 · 구독 확인·해지 · 개인정보 처리방침(버전별 선택)
- **관리 15개**: 대시보드 · 노트 검토 · 데일리 브리핑 · 수집 기사 · 주간 흐름(편집 관점) · 주간 PDF · 의미 검색·질문 설정 · 수집 설정 · 배치 스케줄 ·
  운영 점검 · 참여 분석 · Databricks 적재 · 구독·발송(월 구독·Teams·문의) · 관리자·접속 · 개인정보 처리방침
- **링크 공유 미리보기(제목·설명·썸네일)**: 카톡·LinkedIn·Teams 는 JS 를 실행하지 않고 첫 HTML 의 `<meta>` 만 읽습니다.
  홈·노트·오늘의 AX·데이터 랩·질문하기·소개·유형 테스트·용어 퀴즈·자가진단·뉴스레터·처리방침은 페이지별 제목·설명 + `static/og.png`
  (`app/og_meta.py` 의 `PAGES` 에서 고침), 노트 상세 `/n/{id}` 는 노트 제목·요약, 결과 공유 `/s/…` 는 결과별 이미지.
  썸네일 다시 만들기: `cd backend && venv\Scripts\python -m app.og_meta`. 카톡은 미리보기를 캐시하므로 바꾼 뒤 카카오 공유 디버거에서 초기화.
- **검색·공유**: `/n/{id}`·`/sitemap.xml`·`/robots.txt`·결과별 미리보기 `/s/…`·주간 PDF `/r/…` (서버 렌더링 HTML)
- **보안·개인정보**: 서명 쿠키, 이중 확인 구독, 질문 한도 원자적 처리, 열쇠 분리·PDF 서명 링크, IP 기준 제한, 보관 기간 자동 삭제, 내 기록 지우기,
  처리방침 필수 기재사항·수집 시점 고지·만 14세 확인 — 규칙은 `pipeline/` 이 그대로라 Streamlit 판과 같습니다.

자세한 수집 방식·데이터 구조·보관 기간·운영 체크리스트는 Streamlit 판 README 와 같습니다(같은 `pipeline/`).

## 6. 검증 (2026-10-28)
- 화면: `tsc` 0 오류, `vite build` 경고 0
- 브라우저 통합 시험(DB 복사본): 공개 17개 주소 + 관리 15개 화면 — JS 오류 0, API 실패 0 (잘못된 토큰 시험 3개는 의도된 404),
  퀴즈 답·유형 테스트 12문항·용어 퀴즈 채점·구독 창·모바일 390px 가로 스크롤 없음 확인
- 검색·공유·PDF 주소 200, 공유 미리보기 제목 적용, PDF 생성(Edge) 동작
- 동시 접속(API): 10명 0.31초 · 50명 0.68초 · 100명 0.70초(중앙값), 실패 0
- (10-29) 외부 공개 상태 확인: 공개 주소에서 홈·홈 API·`/n/{id}`·sitemap·`/s/t/…`·공유 이미지 200 (0.03~0.34초), 공유 미리보기 주소가 공개 주소로 잡힘
- (10-29) 모바일 좌우 여백 수정: `.page`·`.adm` 의 `padding` 줄임말이 `.container` 좌우 20px 을 0 으로 덮던 문제 — 위·아래만 지정하도록 바꿈,
  390px 에서 홈·노트·유형 테스트·관리 모두 좌우 20px·가로 스크롤 없음
- (10-29) 공유 미리보기 수정: 예전엔 서버 시작 때 `dist/index.html` 에 메타를 써 넣어서 `npm run build` 를 다시 하면 빠졌음 →
  응답 때 넣도록 바꾸고 페이지별 제목·설명 추가. 공개 주소에서 `/`·`/notes`·`/type`·`/diagnosis`·`/today` 의 제목·`og:url`·`og:image` 확인

## 6-1. 1만 명 대비 점검·수정 (2026-10-29)
1만 명 규모 복사본(방문자 1만·참여 18만 건)으로 부하 시험 + 보안·동시성 점검 후 고친 것.

| 구분 | 문제 | 수정 |
|---|---|---|
| 데이터 | 퀴즈·투표·추천 방문을 빠르게 두 번 누르면 두 번 저장 | `engagements` 부분 유일 인덱스(`ux_eng_once`) + `INSERT OR IGNORE` — 5번 동시 전송해도 1건 |
| 데이터 | 오늘의 퀴즈가 하루 중 수집 뒤 바뀔 수 있음 | 처음 만들 때 `daily_quizzes` 에 저장 (투표와 같은 방식) |
| 데이터 | 화면 선택값·구독 신청·`settings.json` 읽고-쓰기 경쟁 | `BEGIN IMMEDIATE`, 설정은 임시 파일 → 교체 + 깨진 파일이면 저장 중단 |
| 데이터 | 서버가 두 개 뜨면 같은 작업·뉴스레터 중복 | 작업별 DB 잠금(`lease:job:*`), 뉴스레터는 받는 사람별로 먼저 잡고 보냄 |
| 성능 | 접속 기록 표에 인덱스 없음 → 노트 목록·남용 제한이 표 전체를 훑음 | `ix_acc_*` 인덱스 + 노트 조회 수 60초 캐시 |
| 성능 | 캐시 만료 순간 동시 재계산 (오늘의 AX 빈 캐시 + 20명 = 24초) | `api/common.cached` — 한 요청만 계산, 나머지는 직전 값 (→ 2.7초) |
| 성능 | Databricks 적재가 참여 기록 전체를 매번 읽음 | 참여 기록은 마지막 id 뒤만 읽고 지워진 행은 SQL 로 (18만 행 0.13초) |
| 성능 | 보관 기간 정리가 한 번에 지워 쓰기 잠금을 오래 잡음 | 5천 행씩 나눠 삭제 |
| 성능 | Gemini 응답이 멈추면 작업 스레드가 묶임 | 호출 시간 제한 120초 |
| 보안 | 관리자가 이 PC에서 악성 페이지를 열면 관리 기능 위조 요청 가능(CSRF) | 상태를 바꾸는 `/api` 요청은 `X-Requested-With: axreview` + 같은 출처만 (`api/main.py`) |
| 보안 | 쿠키 없이 반복하면 의미 검색 무제한 | IP 하루 120회 · 전체 하루 3,000회 |
| 보안 | 보안 헤더 없음 | `X-Frame-Options`·CSP `frame-ancestors`·`nosniff`·Referrer·Permissions·HSTS(공개 주소) |
| 보안 | 확인 메일 반복 발송 가능 · `javascript:` 링크 · 쿠키 HttpOnly · 토큰 비교 | 주소별 10분 1회·하루 3회, http(s) 주소만 저장, `axv` HttpOnly, `hmac.compare_digest` |
| 운영 | 회사 공용 IP 하나에 여러 명이면 제한에 걸림 | 질문하기 동시 1건은 방문자 기준(IP당 4건), 구독 IP 제한 10→30/시간 |

부하 결과 (복사본, 응답 중앙값): 20명 — 홈 0.68초·오늘의 AX 2.7초(전 23.9초)·노트 0.39초·내 정보 0.07초,
100명 — 0.3~2.4초, 300명 — 1~7초. 실패 0. 서버 한 개가 초당 약 50건을 처리합니다.

## 6-2. 화면 변경 (2026-10-29)
- **라이트 모드**: 헤더 KO/EN 옆 버튼(시스템 ◐ → 라이트 ☀ → 다크 ☾), `localStorage ax_theme`. 히어로·뉴스레터 띠·지도 문서는 의도적으로 어둡게 둠.
- **메인 인터랙션(v1 복원)**: `src/fx.ts` — 히어로 3D 구체 네트워크(마우스 따라 기울어짐)·커서 스포트라이트·카드 기울기·스크롤 등장·상단 진행 바.
- **구독 창**: 오타 도메인(gmial.com 등)이면 고친 주소 제안 + "입력한 주소 그대로" 버튼, 메일을 받을 수 없는 도메인(DNS 에 MX·A 없음)은 막음
  (`pipeline/email_check.py`, dnspython). SMTP 설정 전에는 "보냈습니다" 대신 "신청을 받았습니다"로 안내. 결과 문구가 화면 밖에 생기지 않게 버튼 위로.
- **노트 길이**: 새 노트는 본문 1,200자 이내·요약 2문장(`pipeline/llm.py` NOTE_PROMPT). 기존 긴 노트는 '요약·핵심 포인트'만 먼저 보이고
  나머지는 "자세히 보기"로 펼침 (`핵심 2분 · 전체 9분`).
- **참여 지도 예시 데이터**: v1 과 같은 가상 방문자 180명·3,110건(`s:` 접두어, 통계·적재 제외). 관리 > 참여 분석에서 넣기·지우기·지도 표시 끄기.

## 7. 아직 직접 확인하지 않은 것
- 실제 수집·노트 초안·벡터화·뉴스레터 발송·Teams·Databricks 적재 실행 (Gemini 한도·외부 발송을 쓰지 않으려고 시작 검증까지만 했습니다 —
  `pipeline/` 은 Streamlit 판과 같은 코드). 공개 서버의 스케줄러가 돌면서 처음 실제로 실행됩니다 — 관리 > 배치 스케줄·운영 점검에서 결과 확인
