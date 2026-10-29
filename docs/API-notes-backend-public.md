# 공개 API 구현 메모 (backend/api/routers — docs/API.md 와 다른 점·덧붙인 것)

docs/API.md 의 공개 주소·형식은 그대로 두고 **필드를 더했을 뿐 이름을 바꾸거나 뺀 것은 없다.** 아래는 프론트가 알아야 할 차이.

## 공통
- `PUT /api/me/state` 는 **합치기(merge)** 다. 보낸 키만 바꾸고 나머지는 유지한다. 값이 `null` 이면 그 키를 지운다.
  허용 키 외는 조용히 무시. 고른 값이 하나도 없는 새 방문자는 저장하지 않는다 (state_keep 규칙).
- 서버가 상태를 직접 쓰는 경우: 유형 결과(`axt_*`), 용어 퀴즈 결과(`term_*`), 자가진단(`diag_weak`), 구독(`subscribed`, `pref_inds`),
  구독 코드 적용(`member_id`), 해지(`subscribed` 제거). 화면은 다음 `GET /api/me` 에서 그대로 받는다.
- `member_id` 는 저장값일 뿐이고 `/api/me`·`/api/ask/*` 가 매번 `membership.get` 으로 다시 확인한다. 만료·해지면 저장값도 지운다.
- 쿠키 `axv` 는 프록시(X-Forwarded-For) 경유면 `Secure` 로 심는다 — 로컬 http 시험에서는 쿠키가 안 돌아올 수 있다 (배포는 https).
- `GET /api/profile` 을 더했다: `{profile: {gender, age, country, region}|null, genders, ages, countries, regions}` (선택 프로필 폼 보기값).
- `POST /api/engage` 의 `ref_visit` 은 `item` 이 추천 코드 형식일 때만, 같은 방문자·같은 코드는 한 번만 기록. `share` 의 `value` 는 사이트 안 경로(`/…`)만 남긴다.

## 홈·노트
- `/api/home`: `ticker` 는 띄울 키워드가 없으면 `null`. `issues[]` 에 `now`(현재 호) 추가. `counts.categories` (카테고리별 노트 수) 추가. `issue.id` 포함.
- `/api/notes`: `sort=popular` 는 조회 수(`views`) 기준. `semantic_used`(의미 검색이 실제로 쓰였는지), `count` 추가.
  의미 검색 한도는 **질의 200자 · 방문자당 하루 40회** (Streamlit 판은 세션당 40회 — API 에는 세션이 없어 바꿨다). 같은 질의는 10분 캐시라 횟수를 다시 세지 않는다.
  한도를 넘거나 임베딩을 못 쓰면 단어 검색으로 대신하고 `semantic_note` 에 문구를 준다 (Gemini 키 소진 시 자연스럽게 단어 검색).
- `/api/notes/{id}`: 숫자가 아닌 id 도 404. `note` 에 `minutes`(읽는 시간), `tag_list`, `audience_list`, `industries` 추가.
  `body_html` 의 `### 제목` 은 `<h3 id="sec-N">` (N = `toc` 순서) 로 나가 목차 이동에 쓸 수 있다. `prev` = 더 오래된 노트, `next` = 더 새로운 노트.

## 오늘의 AX
- `/api/today`: 정답(`answer`)·해설(`why`)은 **답한 문항의 `mine` 안에만** 있다. `answered`(답한 수), `left: {hours, minutes}`(다음 문제까지),
  `share`(전부 답했을 때 `{url, title, text}`, 아니면 `null`), `yesterday.hit`(내 예측 적중 여부), `poll.total`, `poll.target_day` 추가.
  `?d=` 는 형식만 검사하고(`shared_day` 로 돌려줌) 문제는 늘 오늘 것이다 — 공유 링크로 와도 어제 문제를 다시 풀 수는 없다.
- `POST /api/today/poll` 응답에 `mine`, `total` 추가. 중복 투표는 400.

## 데이터 랩·지도
- `GET /api/lab/map/html` 을 더했다 — 지식 지도(knowledge.knowledge_map) 문서. `/api/lab/html` 은 탐색 대시보드만.
- `GET /api/map/html`: 관리자가 아니면 `days`·`sample` 을 무시하고 공개용(묶은 값, 설정 `engage.sample_on_map` 따름)만 준다.

## AX 테스트
- `GET /api/type`: `axes` 는 `[{l, r, label, l_text, r_text}]`, `questions[].a/b` 는 `[문구, 글자]`.
- `GET /api/type/{code}` 를 더했다 — 공유 링크(`?t=코드`)의 친구 결과 카드 (기록 없음). 응답은 `POST /api/type/result` 와 같은 형식.
- `POST /api/type/result` 응답에 `emoji, name, line, category, distribution: {total, top: [{code, emoji, name, n, pct}]}` 추가. `buddy` 는 `{code, emoji, name}`.
  같은 방문자가 같은 답을 다시 보내면 기록하지 않는다 (새로고침 중복 방지).
- **용어 퀴즈는 `seed` 가 필요하다.** `GET /api/terms?track=ai` 가 `seed` 와 문제를 주고, `POST /api/terms/answer`·`/api/terms/result` 는 `{track, seed, …}` 를 받는다
  (정답을 숨긴 채 서버가 같은 문제를 다시 만들어 채점하기 위해). `GET /api/terms?track=ai&seed=…` 로 같은 문제를 복원할 수 있다.
  `GET /api/terms` (track 없이) 는 트랙·레벨·용어 사전·참여 통계만. `?q=` 로 용어 사전을 거른다.
  결과 응답에 `right, n, track_label, stats: {n, avg, top_pct}` 추가. `POST …/result` 에 `force: true` 를 주면 같은 결과도 다시 기록한다 ('한 번 더').
- `POST /api/diagnosis/result`: `answers` 는 12개 배열(0~3 또는 null) 또는 공유 링크의 12자리 코드 문자열. 일부만 답해도 점수를 돌려주고(`done` 추가),
  전부 답했을 때만 기록한다. `next_steps` 는 `{카테고리: {label, score, level, color, step}}`. `share` 에 `title, text, level_line` 추가.

## 질문하기
- `GET /api/ask/usage` 에 `web_search`(웹 검색 보완 켜짐), `examples`(예시 질문) 추가.
- `POST /api/ask`: 한도 429, 같은 IP 동시 요청 409, 기능 꺼짐 503. 응답에 `fallback`(Gemini 실패로 근거 목록으로 대신 답함) 추가.
  `history` 는 `[{role: user|assistant, content}]` 중 최근 6개만 쓴다. 질문 원문은 서버에 남지 않는다.
- `POST /api/ask/web`: 설정에서 꺼져 있으면 403. 응답 `{answer, fallback}`.
- `POST /api/ask/redeem`: 성공 시 `member_id` 를 서버가 visitor_state 에 저장한다 (화면이 따로 PUT 할 필요 없음). 시도 제한 5회/시간(방문자)·10회(IP) → 429.

## 구독·추천·문의
- `POST /api/subscribe`: 이미 구독 중이어도 같은 200 응답(존재 비노출). `industries` 는 아는 업종만 남긴다. `source` 는 알려진 위치 이름이 아니면 `other`. 응답에 `reward_at` 추가.
- `POST /api/subscribe/confirm` 응답에 `message` 추가. `GET /api/unsubscribe` 응답에 `active` 추가, `POST` 응답에 `email_masked, message` 추가.
  해지는 GET 으로 바뀌지 않는다 (POST 만).
- `GET /api/refer` 에 `reward_at`, `share: {title, text}` 추가. `pdfs[].url` 은 잠긴 호면 `null`.
- 문의·구독 신청·월 구독 신청은 모두 `agree: true` 가 없으면 400, 시도 제한은 429.

## 개인정보 처리방침
- `active: false` 면 나머지 필드는 비어 있다 (페이지를 두지 않는다). 관리자에게만 `admin_notice`(점검 문구) 가 붙는다. `?v=` 가 없는 날짜면 현재 버전.
