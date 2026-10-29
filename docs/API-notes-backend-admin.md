# 관리 API 구현 메모 (backend/api/routers/admin_*.py)

docs/API.md "관리" 표를 기준으로 구현했다. 표에 있는 주소·이름은 그대로 두고 **필드·주소만 더했다** (이름 바꾸거나 뺀 것 없음).
모든 라우터는 `APIRouter(prefix="/admin/…", dependencies=[Depends(require_admin)])` — 비관리자는 403.
관리자 행동은 Streamlit 판 `admin_ui.log_action` 처럼 `access_logs` 에 `page='관리'` 로 남긴다 (`admin_jobs.log_action`) → `GET /api/admin/actions`.

## 공통으로 더한 것
- 작업을 시작하는 화면 응답(dashboard, articles, issues, reports, search, sources, warehouse, newsletter, teams)에는 `jobs: {active, last_finished, kinds}` (= `GET jobs/status`) 와 `xxx_running` 불리언이 같이 실린다 — 화면이 버튼 비활성·진행 로그를 바로 그릴 수 있게.
- joblog 한 줄 형식: `{time: "HH:MM:SS", level: "INFO|WARNING|ERROR", msg}`.
- `run_logs` 행 형식: `{id, kind, label, started_at, finished_at, trigger, ok, message, summary, result}` — `summary` 는 Streamlit 판 `_summary()` 와 같은 한 줄.

## 라우터별 추가·차이
| 주소 | 메모 |
|---|---|
| POST `jobs/{kind}` | `kind` 는 `jobs._JOBS` 키만 (아니면 400). kwargs 는 작업별 허용 목록만 통과 (`collect: only_sources · draft: per_run,min_score,hashes · weekly: target_day,auto_publish · newsletter: only_to · vectorize: limit · teams: only_url · report: issue_id · warehouse: full`), 그 밖의 키는 400. 응답 `{started, kind, label, message}` — 이미 돌고 있으면 `started=false` (200). |
| GET `jobs/{kind}/log` | 추가. 작업 하나의 joblog 버퍼 (`preview` 포함). |
| GET `jobs/logs` | `kind` 가 KIND_LABELS 에 없으면 400. `latest` = 가장 최근 기록의 result JSON. |
| GET `dashboard` | `gemini: {models, rows}` 는 `gemini_keys.status_rows(models)` 형식 (키는 끝 4자리만). `gemini_keys.status()` 라는 함수는 없어서 이것을 썼다. `gemini_ok · smtp_ok · schedules_on · drafting{min_score, per_run}` 추가. |
| notes | `GET notes?status=` 응답에 `counts: {draft, published, rejected}` 와 `meta`(카테고리·유형·독자 목록) 추가. `GET notes/{id}` 추가 (`body_html` 포함). `POST notes` (직접 작성, `publish: true` 면 바로 게시). `PUT notes/{id}` 는 저장 — `{status: "rejected"|"draft"}` 만 주면 반려/게시 내리기(다른 필드 생략 가능). 게시는 `POST notes/{id}/publish` (편집 내용 같이 보내면 저장 후 게시, 벡터화 작업 자동 시작 — 원본과 같음). 삭제 시 원문 기사는 `skipped` 로. |
| articles | `status` 는 쉼표 목록(기본 `new`), `days` 는 1·3·7·30·90 만. `PUT articles/status {hashes, status}` (여러 건) 추가. |
| briefing | **AI 종합 브리핑(Gemini)은 `?spotlight=1` 일 때만** 만들고 15분 캐시 (기본 GET 은 Gemini 를 쓰지 않음). `POST briefing/archive {date}` 는 지난 날짜를 지금 확정 (오늘·미래 400, 기사 없으면 404, 이미 있으면 `already: true`). `POST briefing/draft {hash}` 추가 ('이 기사로 초안 만들기'). |
| issues | `GET issues?target_day=` 각 호에 `candidates`(그 주 게시 노트 카드), `picks_list`, `leader_three`(현재 picks 기준 선정 결과), `auto_preview`(picks 비었을 때 자동 선정 요약) 포함. `target`(생성 대상 주 정보) · `this_week`(직접 작성 기본값) 추가. `POST issues/generate {target_day}` → `jobs.start('weekly', target_day, auto_publish=False)`. `PUT issues/{id}` 의 `status` = `published`(게시/저장) \| `draft`(초안으로), `picks` 는 id 배열(최대 3). `POST issues` 는 원본처럼 바로 게시 (`status: "draft"`, `week_start` 선택). |
| reports | `GET reports` 는 게시 흐름 최신순 + PDF 상태. 추가: `GET reports/{id}` · `GET reports/{id}/html`(미리보기 문서, iframe srcdoc) · `GET reports/{id}/pdf`(내려받기). `POST reports/{id}` 는 노트 없으면 400. |
| search | `GET search` 추가 (임베딩 현황). `POST search {q}` 는 Gemini 임베딩 1회. `PUT ask-settings` 는 준 키만 바꾸고 범위 검사 (free 0~100, member 1~500, per_ip 1~1000, global 1~100000). |
| sources | `PUT sources {enabled: [이름…]}`. `POST sources/test {names}` 는 DB 에 쓰지 않는 미리보기 (항목·키워드 통과·오류·joblog). 추가: `POST sources/collect {names}` (선택 소스 실제 수집 = `jobs.start('collect', only_sources)`). `PUT keywords {keywords: [...]}` 는 표 전체 교체 (`aliases` 는 배열 또는 쉼표 문자열). |
| schedule | `PUT schedule {구역: {...}}` — 준 구역만 저장. daily 구역 `times` 는 배열 또는 `"08:00 / 14:00"` 문자열. 잘못된 시각·요일·구역 이름은 400. |
| ops | 행 형식 `{status: ok\|warn\|bad, icon, area, item, detail, action}` + `counts`. 포트는 FastAPI 판에 맞춤 (개발 5002, 공개 5012~5019, 건강 확인 `/robots.txt`). '오류 상세 숨김' 행은 api/main.py 의 처리기 기준 문구, **'관리 API 토큰' 행 추가**. `POST ops/backup` 은 `db.backup(force=True)` — 무결성 실패 500. |
| engagement | `GET engagement?days&sample` 한 번에 모든 탭: `summary, daily, funnel, type{counts, crosstab[age\|gender\|country\|region], axes_avg}, quiz{per_question, age_gender, streaks}, term{track_age, missed}, poll[], map(지도 데이터)`. pivot/crosstab 은 `{index, columns, rows}`. 추가: `GET engagement/map.html` (지도 HTML 문서, iframe srcdoc). 집계 1분 캐시, 예시 데이터 넣기/지우기·토글 때 비움. |
| warehouse | 테이블 현황(`warehouse.status()`, 무거움)은 2분 캐시, `?refresh=1` 로 다시 셈. `connection` 은 호스트·경로·토큰 끝 4자리만. `POST warehouse/reset {tables?}` 는 모르는 테이블이면 400. |
| subscribers | 행 `{email, created_at, active, industries, ref_code, referred_by, confirmed, referrals}` — **token·confirm_token·ref_key 는 내려보내지 않음**. `?q=` 이메일 부분 검색. 추가: `GET subscribers/csv`, `PUT subscribers {rows: [{email, active}]}`(여러 명). `POST subscribers {email}` 은 `confirmed=True`. |
| newsletter | `GET newsletter` 에 `html`(preview=True 로 만든 본문) 과 `preview_url`(`GET newsletter/preview.html`) 둘 다. `POST newsletter/test {to}` 는 동기 발송(원본과 같음). |
| members | `POST members` 응답 `{email, code, months}` — 코드는 이 응답에만 (저장은 해시). `POST members/{id}/extend {months?=1}`. 행에 `state(이용 중/만료/해지) · expired · used_today` 추가. |
| webhooks | 목록은 `url_short`(앞 60자) 만. 등록·수정 모두 `settings_store.webhook_url_ok` 통과해야 함(아니면 400). `PUT webhooks/{id} {enabled?, name?, url?}`. |
| teams | `GET teams` 에 카드 JSON(`card`), 웹훅 목록, 발송 기록. |
| access | `GET admin-ips` 에 `my_ip · proxied`. `GET access-logs?view=admin\|ask\|view\|all&limit`. `GET actions` = `view=admin`. |
| privacy | `GET privacy` 에 기재사항·필수 항목·빠진 항목·현재 시행본·버전 목록·공지 기간·기본 시행일·`snapshot`(지금 공지하면 게시될 내용 — 공개 `/api/privacy` 의 `draft` 와 같은 JSON). 첫 게시는 `major` 무시. `DELETE privacy/versions/{id}` 는 시행 전 버전만 (아니면 400). |

## 검증 (2026-10-28, 스크래치 DB 사본 · 포트 5092 · 스케줄러 꺼짐)
- 모든 GET 과 위 POST/PUT/DELETE 를 무해한 입력으로 확인. 비관리자(X-Forwarded-For + Host: example.com) 는 전부 403.
- 실제로 돌리지 않은 것: `POST jobs/{kind}` 의 실제 시작(검증만), `POST articles/draft`·`briefing/draft`(초안 작업 — Gemini), `issues/generate`, `reports/{id}` 생성, `search`(임베딩), `sources/collect`, `newsletter/test·send`, `teams/send`, `webhooks/{id}/test` 는 가짜 주소로만, `warehouse/test·sync`, `ops/backup`(실제 data/backups 에 쓰므로), `subscribers/confirm-mails`(SMTP 없음 → 400 만 확인).
- 설정 파일(data/settings.json)은 시험 뒤 원래 내용으로 되돌렸다.
