# AX Review API 계약 (backend ↔ frontend)

모든 주소는 `/api/…`. 응답은 JSON. 오류는 `{"detail": "사람에게 보여 줄 문구"}` + HTTP 상태(400 입력, 403 권한, 404 없음, 429 한도).
공개 API는 `deps.caller` 로 방문자(서명 쿠키 `axv`)를 식별하고 필요하면 쿠키를 심는다. 관리 API는 `deps.require_admin`
(로컬·등록 IP 또는 `X-Admin-Token` 헤더 = `.env ADMIN_TOKEN`). 날짜는 `YYYY-MM-DD`, 시각은 ISO 문자열.
기존 동작의 근거는 Streamlit 판 `C:\Users\김성환\Desktop\DEV\AxReview\app_pages\*.py` 와 `app\*.py` (읽기 전용으로 참고).

## 공통
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| GET `/api/me` | — | `{visitor, is_admin, member: {id, expires, quota, used} \| null, state: {…visitor_state 스냅샷}, privacy_active, ask_enabled, kakao_key, site_url}` |
| PUT `/api/me/state` | `{키: 값, …}` 허용 키만 저장 (`state_keep` 규칙: q, semantic, cats, kinds, inds, sort, term_q, dq_*, axt_*, term_*, member_id, subscribed, pref_inds, diag_weak) | `{ok: true}` |
| DELETE `/api/me` | — | 내 기록 지우기 (engage.erase_visitor) + 새 쿠키. `{erased: n}` |
| POST `/api/engage` | `{kind, item?, value?, extra?}` kind 허용: share, share_visit, subscribe_open, ref_visit, member_request_open | `{ok: true}` (하루 400건 상한은 engage.record 가 적용) |
| POST `/api/profile` | `{gender, age, country, region, agree: true}` | `{ok: true}` · 만 14세 동의 없으면 400 |
| GET `/api/site` | — | `{counts: {notes, articles_week, sources}, sources: {그룹: [{name, url}]}, privacy_active}` |

## 홈·노트
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| GET `/api/home` | — | `{issue: {id, week, range, headline_em, headline, body_html(강조 적용된 HTML), editor_note_html, pdf_url?}, issues: [{week, headline_em, headline_short}], leader3: [{id, title, category, point}], stance, for_you: [{url, kicker, title}], ticker: {head, rows: [{keyword, cur, prev, rising}]}, latest_notes: [노트 카드], counts, sources}` |
| GET `/api/notes` | `?q&semantic=1&cats=a,b&kinds=a,b&inds=a,b&sort=latest\|popular` | `{notes: [{id, title, category, kind, audiences, tags, summary, published, source, views, industries, similarity?}], meta: {categories, kinds, industries}, semantic_note?: "한도 문구"}` |
| GET `/api/notes/{id}` | — | `{note: {…모든 열, body_html(마크다운→HTML, 목차 h3 포함), toc: [제목]}, prev: {id,title}?, next: {id,title}?, related: [{id, title, category, similarity}], share_url}` 404면 없음 |
| GET `/api/letter` | — | `{letters: [{label, html}]}` (mailer.build_html preview=True) |
| GET `/api/about` | — | `{sources: {그룹: [{name, url}]}, counts}` |

## 오늘의 AX
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| GET `/api/today` | `?d=YYYY-MM-DD` (선택, 공유 링크) | `{day, term: {track, track_label, term, define, hint}, quiz: [{i, q, sub, options, url?, mine?: {choice, correct, answer, why, stats: {n, rate, choices: {보기: n}}}}], score, done, streak, poll: {day, question, options, mine?: 선택, counts?: {보기: n}}, yesterday: {question, winner, actual, crowd, mine, band}?, map_html: 공개 지도 HTML 문서}` |
| POST `/api/today/quiz` | `{day, i, choice}` | 답한 문항의 `mine` 객체 (중복 답은 400) |
| POST `/api/today/poll` | `{day, choice}` | `{counts}` |

## 데이터 랩·지도
| GET `/api/lab/html` | — | `text/html` — Streamlit 판 `app/datalab.py` 가 만들던 HTML 문서 그대로 (iframe srcdoc 으로 띄움) |
| GET `/api/map/html` | `?days&sample=1`(관리자만 sample·개별 행) | `text/html` 참여 지도 문서 (app/geo_map.py) |

## AX 테스트
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| GET `/api/type` | — | `{axes, questions: [{q, a, b}], types: {코드: {emoji, name, line, buddy, category}}, strength, watch}` |
| POST `/api/type/result` | `{answers: ["S","T",…12]}` | `{code, axes: [[l,r,lc,rc]], share_pct, strengths, watch, buddy, recommended_notes: [카드], share: {url: "/s/t/CODE", title, text, image}}` 기록(type_test) |
| GET `/api/terms` | `?track=ai\|ax` | `{tracks, questions: [{i, format, term, prompt, options, …}], dictionary: {track: [[term, define, hint]]}}` 정답은 숨김 |
| POST `/api/terms/answer` | `{track, i, pick}` | `{correct, answer, explain}` |
| POST `/api/terms/result` | `{track, picks: [...]}` | `{score, level, wrong: [term…], review: […], share: {...}}` 기록(term_quiz) |
| GET `/api/diagnosis` | — | `{areas: {cat: [label, [질문…]]}, scale, levels, next}` |
| POST `/api/diagnosis/result` | `{answers: [0-3 × 12 또는 null]}` | `{code, scores, total, level: [name, color], weakest, next_steps, recommended: [카드], report_txt, share: {url: "/s/d?a=", image}}` 전부 답하면 기록(diagnosis) |

## AX 질문하기
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| GET `/api/ask/usage` | — | `{enabled, quota, used, limit_hit, member, is_admin, free_daily, member_daily, plan_price, global_hit}` |
| POST `/api/ask` | `{question, history: [{role, content}]}` | `{answer, sources: [{title, url, kind, sim}], weak}` 한도 넘으면 429, 동시 요청은 409 |
| POST `/api/ask/web` | `{question, history}` | `{answer}` |
| POST `/api/ask/redeem` | `{code}` | `{expires, quota}` 또는 400 |
| POST `/api/membership/request` | `{name, email, company, agree}` | `{ok}` |

## 구독·추천·문의
| 메서드·주소 | 요청 | 응답 |
|---|---|---|
| POST `/api/subscribe` | `{email, industries: [], agree: true, source, ref?}` | `{ok: true, message}` (존재 여부 비노출, 확인 메일 발송) |
| POST `/api/subscribe/confirm` | `{t}` | `{ok}` 또는 400 |
| GET `/api/unsubscribe?token=` | — | `{email_masked}` 또는 404 ; POST `/api/unsubscribe` `{token}` → `{ok}` |
| GET `/api/refer?k=` | — | `{email, code, count, unlocked, link, pdfs: [{name, label, url, locked, latest}]}` 404면 잘못된 열쇠 |
| POST `/api/contact` | `{name, email, company, message, agree}` | `{ok}` |

## 개인정보 처리방침
| GET `/api/privacy` | `?v=날짜` | `{active, versions: [{id, announced_at, effective_date, summary, status}], current_date, upcoming: [...], selected: {effective_date, announced_at, content: snapshot JSON}, draft?: snapshot(공지 전)}` |

## 관리 (모두 `require_admin`, 주소 `/api/admin/...`)
| 주소 | 설명 |
|---|---|
| GET `dashboard` | counts, 최근 run_logs, gemini 키 상태(`gemini_keys.status()` 형식), 켜진 스케줄, 활성 작업 |
| POST `jobs/{kind}` `{…kwargs}` / GET `jobs/status` / GET `jobs/logs?kind&limit` | 작업 시작(jobs.start) · 진행 중 작업 + joblog 버퍼 · run_logs |
| GET `notes?status=draft\|published\|rejected` · PUT `notes/{id}` · POST `notes/{id}/publish` · DELETE `notes/{id}` | 노트 검토 |
| GET `articles?days&q&min_score` · POST `articles/draft {hashes}` · PUT `articles/{hash}/status {status}` | 수집 기사 |
| GET `briefing?date` · POST `briefing/archive {date}` · GET `briefing/dates` | 데일리 브리핑 |
| GET `issues` · POST `issues` · PUT `issues/{id}` · DELETE `issues/{id}` · POST `issues/generate {target_day}` · GET/PUT `lens` | 주간 흐름·편집 관점 (picks 후보 노트 포함) |
| GET `reports` · POST `reports/{issue_id}` | 주간 PDF |
| POST `search {q}` · GET/PUT `ask-settings` | 의미 검색 시험·질문하기 설정 |
| GET/PUT `sources` · POST `sources/test {names}` · GET/PUT `keywords` | 수집 설정 |
| GET/PUT `schedule` | 배치 스케줄 (settings_store 섹션들) |
| GET `ops` · POST `ops/backup` | 운영 점검 행 목록 (Streamlit 판 admin/ops.py 와 같은 항목) |
| GET `engagement?days&sample` · GET `engagement/csv` · POST `engagement/sample {action: seed\|clear}` · PUT `engagement/sample-on-map {on}` | 참여 분석 집계 전부 |
| GET `warehouse` · POST `warehouse/test` · POST `warehouse/sync {full}` · PUT `warehouse/auto {on}` · POST `warehouse/reset` | Databricks |
| GET `subscribers` · PUT `subscribers/{email} {active}` · POST `subscribers {email}` · POST `subscribers/confirm-mails` · GET `newsletter` (preview html·subject·counts) · POST `newsletter/test {to}` · POST `newsletter/send` · GET `members` · POST `members {email, months, memo}` → `{code}` · POST `members/{id}/extend` · PUT `members/{id} {active}` · GET/POST/PUT/DELETE `webhooks` · POST `webhooks/{id}/test` · GET `teams` · POST `teams/send` · GET `contacts` | 구독·발송 |
| GET/POST/DELETE `admin-ips` · GET `access-logs` · GET `actions` | 관리자·접속 |
| GET/PUT `privacy` · POST `privacy/publish {effective_date, summary, major}` · DELETE `privacy/versions/{id}` | 처리방침 |

노트 카드 공통 형식: `{id, title, category, kind, summary, published, source, tags, audiences}`.
