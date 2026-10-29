"""참여형 콘텐츠 기록·집계 — AX 유형 테스트, 오늘의 퀴즈, 예측 투표, 구독 유입.

모든 참여는 engagements 한 테이블에 쌓는다 (kind / item / value / extra / visitor / created_at).
  type_test       item=유형 코드, extra=축별 점수 JSON
  quiz            item=날짜:문항번호, value=고른 답, extra={"correct": 0|1}
  poll            item=날짜, value=고른 키워드
  subscribe_open  item=유입 위치 (구독 창을 연 곳)
  subscribe       item=유입 위치 (구독 완료)
  share_visit     item=콘텐츠 (공유 링크로 들어온 방문)
방문자(visitor)는 브라우저 쿠키 axv(무작위 값) — 없으면 IP의 해시. IP 원문은 여기 남기지 않는다.
성별·연령대·지역(profiles)은 본인이 고른 경우에만 방문자별로 한 줄 남긴다 (IP 위치 추적 없음).
퀴즈(13가지 유형)·투표(11가지 유형) 문제는 날짜를 시드로 수집 데이터에서 규칙으로 만든다 (Gemini 호출 없음).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
import threading
from collections import Counter
from datetime import date, datetime, timedelta

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS engagements (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, item TEXT NOT NULL DEFAULT '', value TEXT NOT NULL DEFAULT '',
  extra TEXT NOT NULL DEFAULT '', visitor TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eng_kind ON engagements(kind, created_at);
CREATE INDEX IF NOT EXISTS ix_eng_visitor ON engagements(visitor, created_at);
CREATE INDEX IF NOT EXISTS ix_eng_kind_item ON engagements(kind, item);
CREATE INDEX IF NOT EXISTS ix_eng_created ON engagements(created_at);
CREATE TABLE IF NOT EXISTS profiles (
  visitor TEXT PRIMARY KEY, gender TEXT NOT NULL DEFAULT '', age TEXT NOT NULL DEFAULT '',
  country TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_polls (
  day TEXT PRIMARY KEY, question TEXT NOT NULL, options TEXT NOT NULL, target_day TEXT NOT NULL, created_at TEXT NOT NULL,
  metric TEXT NOT NULL DEFAULT 'kw', edges TEXT NOT NULL DEFAULT ''
);
"""


_schema_ready: set[str] = set()


# 한 사람이 한 번만 남기는 기록 — 더블클릭·동시 요청으로 두 줄이 생기지 않게 DB가 막는다 (통계가 부풀지 않게)
ONCE_KINDS = ("quiz", "poll", "ref_visit")
_ONCE_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS ux_eng_once ON engagements(kind, visitor, item) "
               "WHERE kind IN ('quiz','poll','ref_visit') AND visitor != ''")


def _conn():
    # 스키마 확인은 프로세스당(DB 파일당) 한 번만 — 화면 한 번에 _conn이 수십 번 불려 매번 하면 쌓인다.
    conn = db.connect()
    if str(db.DB_PATH) not in _schema_ready:
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ux_eng_once'").fetchone():
            with conn:  # 이전에 생긴 중복은 첫 기록만 남기고 지운 뒤 유일 인덱스를 만든다
                conn.execute("DELETE FROM engagements WHERE kind IN ('quiz','poll','ref_visit') AND visitor != '' AND id NOT IN "
                             "(SELECT MIN(id) FROM engagements WHERE kind IN ('quiz','poll','ref_visit') AND visitor != '' "
                             "GROUP BY kind, visitor, item)")
                conn.execute(_ONCE_INDEX)
        _schema_ready.add(str(db.DB_PATH))
    return conn


def today() -> date:
    return datetime.now(db.KST).date()


_COOKIE_RE = re.compile(r"[0-9a-f]{16,64}")
MAX_PER_VISITOR_DAY = 400  # 한 방문자가 하루에 남길 수 있는 참여 기록 수 (DB를 무한히 키우는 남용 방지)


_secret_cache: dict[str, bytes] = {}
_secret_lock = threading.Lock()


def _secret() -> bytes:
    """IP를 해시할 때 쓰는 비밀값 — 없으면 data/.visitor_secret에 만들어 둔다 (IP를 역추적할 수 없게).
    요청마다 파일을 읽지 않게 메모리에 두고, 처음 만들 때 두 스레드가 서로 다른 값을 쓰지 않게 잠근다."""
    path = db.ROOT / "data" / ".visitor_secret"
    key = str(path)
    if key not in _secret_cache:
        with _secret_lock:
            if key not in _secret_cache:
                if not path.exists():
                    path.write_text(secrets.token_hex(32), encoding="utf-8")
                _secret_cache[key] = path.read_text(encoding="utf-8").strip().encode()
    return _secret_cache[key]


def _sig(raw: str) -> str:
    return hmac.new(_secret(), ("axv:" + raw).encode(), hashlib.sha256).hexdigest()[:16]


def sign_cookie(raw: str) -> str:
    """쿠키에 넣을 값 = 무작위 값.서명 (서버 비밀값으로 서명 — 위조한 값은 받지 않는다)."""
    return f"{raw}.{_sig(raw)}"


def _known(raw: str) -> bool:
    conn = _conn()
    try:
        v = "c:" + raw
        return bool(conn.execute("SELECT 1 FROM engagements WHERE visitor=? LIMIT 1", (v,)).fetchone()
                    or conn.execute("SELECT 1 FROM sqlite_master WHERE name='visitor_state'").fetchone()
                    and conn.execute("SELECT 1 FROM visitor_state WHERE visitor=? LIMIT 1", (v,)).fetchone())
    finally:
        conn.close()


def check_cookie(cookie: str | None) -> tuple[str | None, bool]:
    """(무작위 값, 다시 심어야 하는지). 서명이 맞으면 그대로, 서명 없는 예전 쿠키는 이미 기록이 있는 방문자만 받아
    서명된 값으로 바꿔 심는다. 위조·모르는 값은 None (새 방문자로 처리)."""
    if not isinstance(cookie, str):
        return None, False
    raw, _, sig = cookie.partition(".")
    if not _COOKIE_RE.fullmatch(raw):
        return None, False
    if sig:
        return (raw, False) if hmac.compare_digest(sig, _sig(raw)) else (None, False)
    return (raw, True) if _known(raw) else (None, False)


def visitor_id(raw: str | None, ip: str | None) -> str:
    """raw: check_cookie가 돌려준 무작위 값."""
    if isinstance(raw, str) and _COOKIE_RE.fullmatch(raw):
        return "c:" + raw
    return "i:" + hmac.new(_secret(), (ip or "-").encode(), hashlib.sha256).hexdigest()[:16]


def erase_visitor(visitor: str) -> int:
    """'내 기록 지우기' — 이 방문자의 참여 기록·선택 프로필·화면 선택값을 지운다 (Databricks에도 다음 적재 때 삭제 반영)."""
    conn = _conn()
    try:
        n = conn.execute("DELETE FROM engagements WHERE visitor=?", (visitor,)).rowcount
        n += conn.execute("DELETE FROM profiles WHERE visitor=?", (visitor,)).rowcount
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='visitor_state'").fetchone():
            n += conn.execute("DELETE FROM visitor_state WHERE visitor=?", (visitor,)).rowcount
        conn.commit()
        return n
    finally:
        conn.close()


def count_today(kind: str, visitor: str) -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM engagements WHERE kind=? AND visitor=? AND created_at >= ?",
                            (kind, visitor, today().isoformat())).fetchone()[0]
    finally:
        conn.close()


def recent_count(kind: str, visitor: str, minutes: int) -> int:
    since = (datetime.now(db.KST) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM engagements WHERE kind=? AND visitor=? AND created_at >= ?",
                            (kind, visitor, since)).fetchone()[0]
    finally:
        conn.close()


def attempt(kind: str, visitor: str, ip: str | None, per_visitor: int, per_ip: int, minutes: int = 60) -> bool:
    """남용 제한 — 방문자 기준과 IP 기준을 함께 본다(쿠키를 바꿔도 IP로 묶임). 허용이면 시도를 기록하고 True."""
    if recent_count(kind, visitor, minutes) >= per_visitor or db.access_count_since(ip, kind, minutes) >= per_ip:
        return False
    record(kind, visitor=visitor)
    db.record_access(ip, "제한 기록", kind)
    return True


def record(kind: str, item: str = "", value: str = "", extra=None, visitor: str = "") -> bool:
    """기록을 남긴다. 남겼으면 True — ONCE_KINDS 를 이미 남겼거나 하루 한도를 넘으면 False."""
    conn = _conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM engagements WHERE visitor=? AND created_at >= ?",
                         (visitor, today().isoformat())).fetchone()[0]
        if n >= MAX_PER_VISITOR_DAY:
            return False
        item, value = str(item)[:200], str(value)[:200]
        cur = conn.execute("INSERT OR IGNORE INTO engagements (kind, item, value, extra, visitor, created_at) VALUES (?,?,?,?,?,?)",
                           (kind, item, value, json.dumps(extra, ensure_ascii=False) if extra is not None else "", visitor,
                            datetime.now(db.KST).isoformat(timespec="seconds")))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


SAMPLE = "s:"  # 예시(가상) 데이터의 방문자 접두어 — 분석·통계·적재에서는 기본으로 뺀다


def rows(kind: str | None = None, since_days: int | None = None, include_sample: bool = False) -> list[dict]:
    where, params = [], []
    if not include_sample:
        where.append("visitor NOT LIKE ?"); params.append(SAMPLE + "%")
    if kind:
        where.append("kind = ?"); params.append(kind)
    if since_days:
        where.append("created_at >= ?"); params.append((today() - timedelta(days=since_days - 1)).isoformat())
    conn = _conn()
    try:
        sql = "SELECT * FROM engagements" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY id"
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def mine(kind: str, visitor: str, item_prefix: str = "") -> list[dict]:
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM engagements WHERE kind=? AND visitor=? AND item LIKE ? ORDER BY id",
            (kind, visitor, item_prefix + "%"))]
    finally:
        conn.close()


def _streak_of(days: set[str]) -> int:
    d, n = today(), 0
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def streak(visitor: str) -> int:
    """오늘(또는 어제)까지 퀴즈·투표에 연속으로 참여한 날 수."""
    conn = _conn()
    try:
        days = {r[0] for r in conn.execute(
            "SELECT DISTINCT substr(created_at, 1, 10) FROM engagements WHERE visitor=? AND kind IN ('quiz', 'poll')",
            (visitor,))}
    finally:
        conn.close()
    return _streak_of(days)


def streaks(visitors) -> dict[str, int]:
    """여러 방문자의 연속 참여일을 한 번의 쿼리로 (관리 화면 — 방문자마다 조회하면 1만 명에서 30초+)."""
    want = set(visitors)
    yesterday = (today() - timedelta(days=1)).isoformat()
    days: dict[str, set] = {}
    conn = _conn()
    try:
        # 연속 참여가 1일 이상이려면 오늘이나 어제 참여했어야 한다 → 그 방문자들의 기록만 읽는다 (결과는 같고 행 수는 수십 분의 1).
        live = {v for (v,) in conn.execute("SELECT DISTINCT visitor FROM engagements WHERE kind IN ('quiz', 'poll') "
                                            "AND created_at >= ?", (yesterday,)) if v in want}
        for v in live:
            days[v] = {d for (d,) in conn.execute("SELECT DISTINCT substr(created_at, 1, 10) FROM engagements "
                                                  "WHERE visitor=? AND kind IN ('quiz', 'poll')", (v,))}
    finally:
        conn.close()
    return {v: _streak_of(days.get(v, set())) for v in want}


# ───────────────────────── 오늘의 퀴즈 ─────────────────────────
# 문제 유형 13가지(_Q_TEMPLATES) 중 그날 데이터로 만들 수 있는 것에서 3개를 날짜 시드로 고른다.
# 각 유형은 (rng, ctx) → 문항 dict 또는 None(데이터가 모자람).

QUIZ_PER_DAY = 3
CATS3 = ["AX Strategy", "AX Implementation", "AX Enablement"]


def _kw_cats() -> dict[str, str]:
    return {k["keyword"]: k["category"] for k in db.list_keywords() if k["category"]}


def _kws(a: dict) -> list[str]:
    return json.loads(a["matched_kw"] or "[]")


def _groups() -> dict[str, str]:
    from . import jobs  # 순환 참조 피하기
    return {s["name"]: s.get("group", "기타") for s in jobs.config()["sources"]}


def _opts(rng, answer, pool, k=3):
    others = [x for x in dict.fromkeys(pool) if x != answer]
    if len(others) < k:
        return None
    opts = [answer] + rng.sample(others, k)
    rng.shuffle(opts)
    return opts


def _q(q, sub, opts, answer, why, url=None):
    return {"q": q, "sub": sub, "options": opts, "answer": answer, "why": why, **({"url": url} if url else {})} if opts else None


def _t_article_kw(rng, c):
    pool = [a for a in c["arts"] if any(k in c["cats"] for k in _kws(a))]
    if not pool:
        return None
    a = rng.choice(pool)
    mk = [k for k in _kws(a) if k in c["cats"]]
    return _q("이 기사에 AX Review가 붙인 키워드는?", a["title"], _opts(rng, mk[0], [k for k in c["cats"] if k not in mk[1:]]),
              mk[0], f"{a['source']} 기사 · 키워드 {', '.join(mk)}", a["url"])


def _t_top_kw(rng, c):
    if len(c["kwc"]) < 4:
        return None
    top = c["kwc"].most_common(1)[0][0]
    opts = _opts(rng, top, [k for k, _ in c["kwc"].most_common(10)])
    return _q("최근 7일 AX Review가 가장 많이 잡은 키워드는?", "수집 기사 기준", opts, top,
              " · ".join(f"{k} {c['kwc'][k]}건" for k in sorted(opts or [], key=lambda k: -c["kwc"][k])))


def _t_least_kw(rng, c):
    top = [k for k, _ in c["kwc"].most_common(8)]
    if len(top) < 4:
        return None
    pick = rng.sample(top, 4)
    low = min(pick, key=lambda k: c["kwc"][k])
    rng.shuffle(pick)
    return _q("다음 중 최근 7일 가장 '적게' 잡힌 키워드는?", "함정 주의 — 많은 게 아니라 적은 것", pick, low,
              " · ".join(f"{k} {c['kwc'][k]}건" for k in sorted(pick, key=lambda k: c["kwc"][k])))


def _t_note_cat(rng, c):
    if not c["notes"]:
        return None
    n = rng.choice(c["notes"])
    return _q("이 노트는 어느 카테고리일까?", n["title"], list(CATS3), n["category"],
              "Strategy=방향·투자·거버넌스 / Implementation=현장 적용 / Enablement=데이터·보안·역량", f"/notes?id={n['id']}")


def _t_article_source(rng, c):
    if len(c["srcc"]) < 4 or not c["arts"]:
        return None
    a = rng.choice(c["arts"])
    return _q("이 기사를 낸 곳은?", a["title"], _opts(rng, a["source"], list(c["srcc"])), a["source"],
              f"{a['source']} · {(a['published_at'] or '')[:10]}", a["url"])


def _t_top_source(rng, c):
    if len(c["srcc"]) < 4:
        return None
    top = c["srcc"].most_common(1)[0][0]
    opts = _opts(rng, top, [s for s, _ in c["srcc"].most_common(10)])
    return _q("최근 7일 AX 기사를 가장 많이 낸 곳은?", "키워드 필터를 통과한 기사 기준", opts, top,
              " · ".join(f"{s} {c['srcc'][s]}건" for s in sorted(opts or [], key=lambda s: -c["srcc"][s])))


def _t_kw_cat(rng, c):
    kws = [k for k, v in c["cats"].items() if v in CATS3]
    if not kws:
        return None
    k = rng.choice(kws)
    return _q(f"'{k}' 키워드는 AX Review에서 어느 카테고리로 분류될까?", "키워드 규칙 기준", list(CATS3), c["cats"][k],
              "Strategy=방향·투자·거버넌스 / Implementation=현장 적용 / Enablement=데이터·보안·역량")


def _t_note_audience(rng, c):
    from .llm import AUDIENCES
    pool = [n for n in c["notes"] if n["audiences"]]
    if not pool:
        return None
    n = rng.choice(pool)
    aud = [a for a in n["audiences"].split(",") if a]
    wrong = [a for a in AUDIENCES if a not in aud]
    if len(wrong) < 3:
        return None
    opts = [aud[0]] + rng.sample(wrong, 3)
    rng.shuffle(opts)
    return _q("이 노트의 추천 독자에 포함된 사람은?", n["title"], opts, aud[0], f"추천 독자: {', '.join(aud)}", f"/notes?id={n['id']}")


def _t_pair(rng, c):
    hubs = [k for k, _ in c["kwc"].most_common(5)]
    rng.shuffle(hubs)
    for hub in hubs:
        pc = Counter(k for a in c["week"] if hub in _kws(a) for k in _kws(a) if k != hub and k in c["cats"])
        if len(pc) >= 1 and len(c["kwc"]) >= 5:
            best = pc.most_common(1)[0][0]
            opts = _opts(rng, best, [k for k, _ in c["kwc"].most_common(10) if k != hub])
            if opts:
                return _q(f"'{hub}'와 같은 기사에 가장 자주 함께 나온 키워드는?", "최근 7일 · 데이터 랩 키워드 네트워크 기준", opts, best,
                          " · ".join(f"{k} {pc[k]}회" for k in sorted(opts, key=lambda k: -pc[k])))
    return None


def _t_score(rng, c):
    pool = [a for a in c["arts"] if a["llm_score"]]
    if not pool:
        return None
    a = rng.choice(pool)
    return _q("이 기사의 AX 관련도 점수(1~5)는?", a["title"], ["2점", "3점", "4점", "5점"], f"{max(2, a['llm_score'])}점",
              f"AI가 '기업 AX 관점에서 깊게 읽을 가치'로 매긴 점수 · {a['source']}", a["url"])


def _t_volume(rng, c):
    n = len(c["week"])
    if n < 20:
        return None
    step = max(10, int(round(n / 4 / 10)) * 10)  # 구간 폭 (10건 단위)
    start = max(0, (n // step - rng.randint(0, 3)) * step)  # 정답이 몇 번째 구간에 올지 섞는다
    bands = [(start + i * step, start + (i + 1) * step - 1) for i in range(4)]
    ans = next((f"{lo}~{hi}건" for lo, hi in bands if lo <= n <= hi), None)
    if not ans:
        return None
    return _q("최근 7일 AX 키워드에 걸린 수집 기사는 몇 건일까?", "중복 제거·키워드 필터 통과 기준",
              [f"{lo}~{hi}건" for lo, hi in bands], ans, f"실제 {n}건")


def _t_group(rng, c):
    groups = c["groups"]
    pool = [a for a in c["arts"] if a["source"] in groups]
    names = sorted(set(groups.values()))
    if not pool or len(names) < 4:
        return None
    a = rng.choice(pool)
    g = groups[a["source"]]
    return _q(f"'{a['source']}'는 어느 소스 그룹에 속할까?", "홈 '어디서 찾아 읽나' 분류 기준", _opts(rng, g, names), g,
              f"{a['source']} → {g}")


def _t_note_kind(rng, c):
    from .llm import KINDS
    if not c["notes"]:
        return None
    n = rng.choice(c["notes"])
    return _q("이 노트의 원문 유형은?", n["title"], list(KINDS), n["kind"], f"{n['source']} · {n['kind']}", f"/notes?id={n['id']}")


_Q_TEMPLATES = [_t_article_kw, _t_top_kw, _t_least_kw, _t_note_cat, _t_article_source, _t_top_source, _t_kw_cat,
                _t_note_audience, _t_pair, _t_score, _t_volume, _t_group, _t_note_kind]


def _context(day: date) -> dict:
    cats = _kw_cats()
    before = lambda a: (a["published_at"] or "")[:10] < day.isoformat()  # noqa: E731 - 그날 전 데이터로만 (하루 동안 고정)
    week = [a for a in db.articles(8) if before(a) and any(k in cats for k in _kws(a))]
    arts = [a for a in db.articles(14) if before(a) and (a["llm_score"] or 0) >= 4] or week
    return {"cats": cats, "week": week, "arts": sorted(arts, key=lambda a: a["url_hash"]),
            "kwc": Counter(k for a in week for k in set(_kws(a)) if k in cats),
            "srcc": Counter(a["source"] for a in week), "notes": sorted(db.notes(), key=lambda n: n["id"]),
            "groups": _groups()}


def daily_quiz(day: date | None = None) -> list[dict]:
    """그날의 3문항 [{q, sub, options, answer, why, url?}] — 처음 만들 때 DB에 저장해 그날 안에서는 바뀌지 않는다.

    문제는 최근 기사로 만드는데, 하루 중 수집이 돌면 기사 목록이 바뀌어 같은 날짜라도 문제가 달라질 수 있었다
    (이미 낸 답이 다른 문제로 채점되거나, 열어 둔 화면에서 답하면 '보기 중에서 골라 주세요'). 투표(daily_polls)와 같은 방식."""
    day = day or today()
    conn = _conn()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS daily_quizzes (day TEXT PRIMARY KEY, data TEXT NOT NULL, created_at TEXT NOT NULL)")
        r = conn.execute("SELECT data FROM daily_quizzes WHERE day=?", (day.isoformat(),)).fetchone()
        if r:
            return json.loads(r["data"])
        quiz = _build_quiz(day)
        if quiz:  # 기사가 없어 비면 저장하지 않는다 (수집 뒤 다시 만든다)
            conn.execute("INSERT OR IGNORE INTO daily_quizzes (day, data, created_at) VALUES (?,?,?)",
                         (day.isoformat(), json.dumps(quiz, ensure_ascii=False), datetime.now(db.KST).isoformat(timespec="seconds")))
            conn.commit()
            r = conn.execute("SELECT data FROM daily_quizzes WHERE day=?", (day.isoformat(),)).fetchone()  # 동시에 만든 쪽이 먼저면 그것
            return json.loads(r["data"]) if r else quiz
        return quiz
    finally:
        conn.close()


def _build_quiz(day: date) -> list[dict]:
    rng = random.Random(f"axquiz:{day.isoformat()}")
    ctx = _context(day)
    order = _Q_TEMPLATES[:]
    rng.shuffle(order)
    out = []
    for t in order:
        q = t(rng, ctx)
        if q and q["answer"] in q["options"]:
            out.append(q)
        if len(out) == QUIZ_PER_DAY:
            break
    return out


def quiz_stats(day_iso: str) -> dict[int, dict]:
    """문항별 참여 수·정답률."""
    # 그날 문항만 DB에서 묶어 센다 (전체 퀴즈 기록을 읽지 않게 — ix_eng_kind_item).
    stats: dict[int, dict] = {}
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT item, value, COUNT(*), SUM(COALESCE(json_extract(NULLIF(extra, ''), '$.correct'), 0)) FROM engagements "
            "WHERE kind='quiz' AND item >= ? AND item < ? AND visitor NOT LIKE ? GROUP BY item, value",
            (day_iso + ":", day_iso + ";", SAMPLE + "%"))
        for item, value, n, correct in cur:
            idx = item.partition(":")[2]
            if not idx.isdigit():
                continue
            s = stats.setdefault(int(idx), {"n": 0, "correct": 0, "choices": Counter()})
            s["n"] += n
            s["correct"] += int(correct or 0)
            s["choices"][value] += n
    finally:
        conn.close()
    return stats


# ───────────────────────── 예측 투표 ─────────────────────────
# 투표 유형 11가지(_POLLS). 날마다 하나를 골라 그날 보기와 함께 저장하고, 대상 날짜의 실제 기사로 채점한다.
# 측정(metric): kw · group · source · cat · hi_ratio · volume:<키워드> · domestic · catkw:<카테고리> · total · duel:<a>|<b>

def _bands(edges: list[int], unit: str) -> list[str]:
    return [f"{edges[0]}{unit} 미만"] + [f"{a}~{b - 1}{unit}" for a, b in zip(edges, edges[1:])] + [f"{edges[-1]}{unit} 이상"]


def _band_of(value: float, edges: list[int], unit: str) -> str:
    labels = _bands(edges, unit)
    for i, e in enumerate(edges):
        if value < e:
            return labels[i]
    return labels[-1]


def _poll_defs(ctx: dict) -> list[dict]:
    kwc, cats = ctx["kwc"], ctx["cats"]
    top_kw = [k for k, _ in kwc.most_common(5)]
    groups = Counter(ctx["groups"].get(a["source"], "기타") for a in ctx["week"])
    srcs = [s for s, _ in ctx["srcc"].most_common(5)]
    per_day = max(1, len(ctx["week"]) / 7)
    vol_edges = sorted({max(1, round(per_day * f)) for f in (.5, 1, 1.5)})
    defs = [
        {"metric": "kw", "question": "내일 가장 많이 잡힐 AX 키워드는?", "options": top_kw},
        {"metric": "group", "question": "내일 AX 기사를 가장 많이 낼 소스 그룹은?", "options": [g for g, _ in groups.most_common(4)]},
        {"metric": "source", "question": "내일 AX 기사를 가장 많이 낼 매체는?", "options": srcs},
        {"metric": "cat", "question": "내일 가장 많이 잡힐 AX 카테고리는?", "options": list(CATS3)},
        {"metric": "hi_ratio", "question": "내일 기사 중 AX 점수 4점 이상 비율은?", "options": _bands([30, 40, 50], "%")},
        {"metric": "domestic", "question": "내일 AX 기사는 국내와 해외 중 어디가 더 많을까?", "options": ["국내", "해외"]},
        {"metric": "catkw:AX Enablement", "question": "내일 가장 많이 잡힐 '기반(Enablement)' 키워드는?",
         "options": [k for k, _ in kwc.most_common() if cats.get(k) == "AX Enablement"][:4]},
        {"metric": "catkw:AX Implementation", "question": "내일 가장 많이 잡힐 '실행(Implementation)' 키워드는?",
         "options": [k for k, _ in kwc.most_common() if cats.get(k) == "AX Implementation"][:4]},
        {"metric": "total", "question": "내일 AX 키워드에 걸릴 기사는 몇 건일까?", "options": _bands(vol_edges, "건"), "edges": vol_edges},
    ]
    if top_kw:
        k = top_kw[0]
        edges = sorted({max(1, round(kwc[k] / 7 * f)) for f in (.5, 1, 1.5)})
        defs.append({"metric": f"volume:{k}", "question": f"내일 '{k}' 기사는 몇 건일까?", "options": _bands(edges, "건"), "edges": edges})
    if len(top_kw) >= 3:
        a, b = top_kw[1], top_kw[2]
        defs.append({"metric": f"duel:{a}|{b}", "question": f"내일 '{a}' vs '{b}', 더 많이 잡힐 쪽은?", "options": [a, b]})
    return [d for d in defs if len(d["options"]) >= 2]


def _ensure_poll_columns(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(daily_polls)")}
    if "metric" not in cols:  # 처음 만든 투표 테이블(키워드 투표만 있던 때)에 측정 열을 더한다
        conn.execute("ALTER TABLE daily_polls ADD COLUMN metric TEXT NOT NULL DEFAULT 'kw'")
        conn.execute("ALTER TABLE daily_polls ADD COLUMN edges TEXT NOT NULL DEFAULT ''")
        conn.commit()


def daily_poll(day: date | None = None) -> dict:
    """그날의 투표 — 처음 열릴 때 유형과 보기를 정해 저장해 둔다 (그날 안에서는 바뀌지 않게)."""
    day = day or today()
    conn = _conn()
    try:
        _ensure_poll_columns(conn)
        r = conn.execute("SELECT * FROM daily_polls WHERE day=?", (day.isoformat(),)).fetchone()
        if r:
            return {**dict(r), "options": json.loads(r["options"]), "edges": json.loads(r["edges"] or "[]")}
        defs = _poll_defs(_context(day)) or [{"metric": "cat", "question": "내일 가장 많이 잡힐 AX 카테고리는?", "options": list(CATS3)}]
        pick = random.Random(f"axpoll:{day.isoformat()}").choice(defs)
        poll = {"day": day.isoformat(), "question": pick["question"], "options": pick["options"],
                "target_day": (day + timedelta(days=1)).isoformat(), "metric": pick["metric"], "edges": pick.get("edges", [])}
        conn.execute("INSERT OR IGNORE INTO daily_polls (day, question, options, target_day, created_at, metric, edges) "
                     "VALUES (?,?,?,?,?,?,?)",
                     (poll["day"], poll["question"], json.dumps(poll["options"], ensure_ascii=False), poll["target_day"],
                      datetime.now(db.KST).isoformat(timespec="seconds"), poll["metric"], json.dumps(poll["edges"])))
        conn.commit()
        return poll
    finally:
        conn.close()


def actual_counts(day_iso: str, options: list[str], metric: str = "kw", edges: list[int] | None = None) -> Counter:
    """대상 날짜에 발행된 기사로 보기별 실제 값을 센다 (구간형은 맞는 구간에 1)."""
    cats = _kw_cats()
    arts = [a for a in db.articles(10) if (a["published_at"] or "")[:10] == day_iso]
    tagged = [a for a in arts if any(k in cats for k in _kws(a))]
    c: Counter = Counter()
    if metric in ("kw", "duel") or metric.startswith(("catkw:", "duel:")):
        for a in tagged:
            for k in set(_kws(a)):
                if k in options:
                    c[k] += 1
    elif metric == "group":
        groups = _groups()
        c.update(g for g in (groups.get(a["source"], "기타") for a in tagged) if g in options)
    elif metric == "source":
        c.update(a["source"] for a in tagged if a["source"] in options)
    elif metric == "cat":
        for a in tagged:
            for cat in {cats[k] for k in _kws(a) if cats.get(k) in options}:
                c[cat] += 1
    elif metric == "domestic":
        groups = _groups()
        c.update("국내" if groups.get(a["source"]) == "국내" else "해외" for a in tagged)
    elif metric == "hi_ratio" and arts:
        c[_band_of(sum((a["llm_score"] or 0) >= 4 for a in arts) / len(arts) * 100, [30, 40, 50], "%")] = 1
    elif metric == "total" and edges:
        c[_band_of(len(tagged), edges, "건")] = 1
    elif metric.startswith("volume:") and edges:
        k = metric.split(":", 1)[1]
        c[_band_of(sum(k in _kws(a) for a in tagged), edges, "건")] = 1
    return c


def poll_votes(day_iso: str) -> Counter:
    conn = _conn()
    try:
        return Counter(dict(conn.execute(
            "SELECT value, COUNT(*) FROM engagements WHERE kind='poll' AND item=? AND visitor NOT LIKE ? GROUP BY value",
            (day_iso, SAMPLE + "%")).fetchall()))
    finally:
        conn.close()


def poll_result(day_iso: str) -> dict | None:
    """끝난 투표의 결과 (대상 날짜가 지났을 때만)."""
    conn = _conn()
    try:
        _ensure_poll_columns(conn)
        r = conn.execute("SELECT * FROM daily_polls WHERE day=?", (day_iso,)).fetchone()
    finally:
        conn.close()
    if not r or r["target_day"] >= today().isoformat():
        return None
    options = json.loads(r["options"])
    actual = actual_counts(r["target_day"], options, r["metric"], json.loads(r["edges"] or "[]"))
    votes = poll_votes(day_iso)
    winner = actual.most_common(1)[0][0] if actual else None
    band = r["metric"] in ("hi_ratio", "total") or r["metric"].startswith("volume:")
    return {"day": day_iso, "target_day": r["target_day"], "question": r["question"], "options": options, "band": band,
            "actual": actual, "votes": votes, "winner": winner, "crowd": votes.most_common(1)[0][0] if votes else None}


# ───────────────────────── 집계 (관리 화면) ─────────────────────────

def funnel_by_source(since_days: int = 30) -> list[dict]:
    opens = Counter(r["item"] for r in rows("subscribe_open", since_days))
    subs = Counter(r["item"] for r in rows("subscribe", since_days))
    return [{"유입 위치": s, "구독 창 열기": opens[s], "구독 완료": subs[s],
             "전환율(%)": round(subs[s] / opens[s] * 100, 1) if opens[s] else 0.0}
            for s in sorted(set(opens) | set(subs), key=lambda s: -(subs[s] * 1000 + opens[s]))]


_DAY_COLS = {"type_test": "유형 테스트", "quiz": "퀴즈 응답", "term_quiz": "용어 퀴즈", "poll": "투표",
             "share_visit": "공유 유입", "subscribe": "구독"}


def _since(since_days: int) -> str:
    return (today() - timedelta(days=since_days - 1)).isoformat()


def daily_activity(since_days: int = 14) -> list[dict]:
    sums = ", ".join(f"SUM(kind = '{k}')" for k in _DAY_COLS)
    conn = _conn()
    try:
        cur = conn.execute(f"SELECT substr(created_at, 1, 10) AS d, COUNT(DISTINCT visitor), {sums} FROM engagements "
                           "WHERE created_at >= ? AND visitor NOT LIKE ? GROUP BY d ORDER BY d", (_since(since_days), SAMPLE + "%"))
        return [{"날짜": r[0], "참여자": r[1], **{label: r[i + 2] for i, label in enumerate(_DAY_COLS.values())}} for r in cur]
    finally:
        conn.close()


def retention(since_days: int = 14) -> dict:
    """참여한 날이 2일 이상인 방문자 비율."""
    conn = _conn()
    try:
        n_days = [r[0] for r in conn.execute(
            "SELECT COUNT(DISTINCT substr(created_at, 1, 10)) FROM engagements WHERE kind IN ('type_test', 'quiz', 'term_quiz', 'poll') "
            "AND created_at >= ? AND visitor NOT LIKE ? GROUP BY visitor", (_since(since_days), SAMPLE + "%"))]
    finally:
        conn.close()
    total = len(n_days)
    back = sum(1 for n in n_days if n >= 2)
    return {"visitors": total, "returning": back, "rate": round(back / total * 100, 1) if total else 0.0}


# ───────────────────────── 선택 프로필 (성별·연령대·지역) ─────────────────────────

GENDERS = ["남성", "여성", "응답 안 함"]
AGES = ["14~29세", "30대", "40대", "50대", "60대 이상"]  # 만 14세 미만은 받지 않는다
# 국가 이름 → ISO 3166 숫자 코드 (세계 지도 world-atlas의 id와 같다)
COUNTRIES = {
    "대한민국": "410", "미국": "840", "중국": "156", "일본": "392", "베트남": "704", "인도": "356", "대만": "158",
    "싱가포르": "702", "인도네시아": "360", "태국": "764", "말레이시아": "458", "필리핀": "608", "독일": "276",
    "영국": "826", "프랑스": "250", "튀르키예": "792", "멕시코": "484", "브라질": "076", "캐나다": "124", "호주": "036",
}
# 국내 시·도 → (위도, 경도) — 지도 위 원 위치
KR_REGIONS = {
    "서울": (37.57, 126.98), "부산": (35.18, 129.08), "대구": (35.87, 128.60), "인천": (37.46, 126.71),
    "광주": (35.16, 126.85), "대전": (36.35, 127.38), "울산": (35.54, 129.31), "세종": (36.48, 127.29),
    "경기": (37.41, 127.52), "강원": (37.82, 128.16), "충북": (36.80, 127.70), "충남": (36.52, 126.80),
    "전북": (35.72, 127.15), "전남": (34.82, 126.89), "경북": (36.49, 128.89), "경남": (35.46, 128.21),
    "제주": (33.49, 126.50),
}


def save_profile(visitor: str, gender: str, age: str, country: str, region: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO profiles (visitor, gender, age, country, region, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(visitor) DO UPDATE SET gender=excluded.gender, age=excluded.age, country=excluded.country, "
            "region=excluded.region, updated_at=excluded.updated_at",
            (visitor, gender, age, country, region if country == "대한민국" else "",
             datetime.now(db.KST).isoformat(timespec="seconds")))
        conn.commit()
    finally:
        conn.close()


def profile(visitor: str) -> dict | None:
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM profiles WHERE visitor=?", (visitor,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def profiles(include_sample: bool = False) -> dict[str, dict]:
    conn = _conn()
    try:
        return {r["visitor"]: dict(r) for r in conn.execute("SELECT * FROM profiles")
                if include_sample or not r["visitor"].startswith(SAMPLE)}
    finally:
        conn.close()


def map_data(since_days: int | None = None, include_sample: bool = False) -> dict:
    """세계 지도용 — 참여 기록 × 프로필. 개인을 알 수 없게 방문자 값은 넘기지 않는다."""
    out, sample = [], 0
    # 같은 칸(나라·지역·성별·연령대·종류·유형·정답)끼리 묶어 n(건수)으로 보낸다 — 1만 명 기준 3.5MB → 수십 KB.
    for r in _map_rows(since_days, include_sample, grouped=True):
        sample += r["n"] if r["s"] else 0
        out.append({"c": COUNTRIES[r["country"]], "cn": r["country"], "r": r["region"], "g": r["gender"],
                    "a": r["age"], "k": r["kind"], "t": r["t"], "ok": r["ok"], "n": r["n"]})
    return {"rows": out, "regions": KR_REGIONS, "countries": COUNTRIES, "genders": GENDERS, "ages": AGES,
            "profiles": _profile_count(include_sample), "sample": sample}


_MAP_KINDS = ("type_test", "quiz", "term_quiz", "poll", "share", "share_visit", "subscribe")


def _map_rows(since_days: int | None, include_sample: bool, grouped: bool = True) -> list[dict]:
    """참여 기록 × 프로필 (지도용 열만), 같은 칸끼리 묶어 n(건수)으로 센다."""
    # 정답: 퀴즈는 extra.correct, 용어 퀴즈는 70점 이상 (지도 정답률용)
    ok = ("CASE e.kind WHEN 'quiz' THEN json_extract(NULLIF(e.extra, ''), '$.correct') "
          "WHEN 'term_quiz' THEN (CAST(e.value AS INTEGER) >= 70 AND e.value GLOB '[0-9]*') END")
    cols = (f"p.country, p.region, p.gender, p.age, e.kind, CASE e.kind WHEN 'type_test' THEN e.item ELSE '' END AS t, "
            f"{ok} AS ok, e.visitor LIKE '{SAMPLE}%' AS s")
    where = [f"e.kind IN ({','.join('?' * len(_MAP_KINDS))})", f"p.country IN ({','.join('?' * len(COUNTRIES))})"]
    params: list = [*_MAP_KINDS, *COUNTRIES]
    if not include_sample:
        where.append("e.visitor NOT LIKE ?"); params.append(SAMPLE + "%")
    if since_days:
        where.append("e.created_at >= ?"); params.append((today() - timedelta(days=since_days - 1)).isoformat())
    sql = f"SELECT {cols}, COUNT(*) AS n FROM engagements e JOIN profiles p ON p.visitor = e.visitor " \
          f"WHERE {' AND '.join(where)} GROUP BY 1, 2, 3, 4, 5, 6, 7, 8"
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _profile_count(include_sample: bool) -> int:
    conn = _conn()
    try:
        sql = "SELECT COUNT(*) FROM profiles" + ("" if include_sample else " WHERE visitor NOT LIKE ?")
        return conn.execute(sql, () if include_sample else (SAMPLE + "%",)).fetchone()[0]
    finally:
        conn.close()


# ───────────────────────── 예시(가상) 데이터 ─────────────────────────

def sample_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM engagements WHERE visitor LIKE ?", (SAMPLE + "%",)).fetchone()[0]
    finally:
        conn.close()


def clear_sample() -> int:
    conn = _conn()
    try:
        n = conn.execute("DELETE FROM engagements WHERE visitor LIKE ?", (SAMPLE + "%",)).rowcount
        conn.execute("DELETE FROM profiles WHERE visitor LIKE ?", (SAMPLE + "%",))
        conn.commit()
        return n
    finally:
        conn.close()


def seed_sample(visitors: int = 180, days: int = 14, seed: int = 28) -> int:
    """지도·화면 시연용 가상 참여. 방문자 값이 s:로 시작해 실제 통계와 섞이지 않는다. 다시 넣으면 기존 예시는 지운다."""
    from app import ax_types  # 순환 참조 피하기

    clear_sample()
    rng = random.Random(seed)
    countries = [("대한민국", 62), ("베트남", 9), ("중국", 7), ("미국", 6), ("인도", 4), ("튀르키예", 3), ("일본", 2),
                 ("독일", 2), ("브라질", 1), ("멕시코", 1), ("싱가포르", 1), ("인도네시아", 1), ("영국", 1)]
    regions = [("서울", 26), ("경기", 24), ("인천", 5), ("부산", 6), ("대구", 4), ("대전", 4), ("울산", 5), ("광주", 3),
               ("세종", 2), ("충남", 4), ("충북", 3), ("경남", 5), ("경북", 4), ("전북", 2), ("전남", 2), ("강원", 1), ("제주", 1)]
    ages = [("14~29세", 14), ("30대", 32), ("40대", 30), ("50대", 18), ("60대 이상", 6)]
    genders = [("남성", 52), ("여성", 36), ("응답 안 함", 12)]
    pick = lambda pairs: rng.choices([p for p, _ in pairs], [w for _, w in pairs])[0]  # noqa: E731
    codes = list(ax_types.TYPES)
    weights = [rng.uniform(.5, 3) for _ in codes]
    kws = list(_kw_cats())[:6] or ["AI agent"]
    now = datetime.now(db.KST)
    conn = _conn()
    n = 0
    try:
        for v in range(visitors):
            vis = f"{SAMPLE}{v:04d}"
            country = pick(countries)
            conn.execute("INSERT OR REPLACE INTO profiles (visitor, gender, age, country, region, updated_at) VALUES (?,?,?,?,?,?)",
                         (vis, pick(genders), pick(ages), country, pick(regions) if country == "대한민국" else "",
                          now.isoformat(timespec="seconds")))
            skill = rng.uniform(.3, .85)
            active = sorted(rng.sample(range(days), k=min(days, max(1, int(rng.expovariate(1 / 3)) + 1))))
            for i, d in enumerate(active):
                ts = (now - timedelta(days=d, minutes=rng.randint(0, 600))).isoformat(timespec="seconds")
                day = ts[:10]
                ev = []
                if i == 0 or rng.random() < .15:
                    ev.append(("type_test", rng.choices(codes, weights)[0], "", json.dumps({"axes": []})))
                for q in range(3):
                    ev.append(("quiz", f"{day}:{q}", "", json.dumps({"correct": int(rng.random() < skill)})))
                if rng.random() < .7:
                    ev.append(("poll", day, rng.choice(kws), ""))
                if rng.random() < .35:
                    from app import glossary
                    track = rng.choice(list(glossary.TERMS))
                    miss = rng.sample([t[0] for t in glossary.TERMS[track]], rng.randint(0, 5))
                    ev.append(("term_quiz", track, str(100 - len(miss) * 10), json.dumps({"wrong": miss}, ensure_ascii=False)))
                if rng.random() < .25:
                    ev.append(("share", rng.choice(["type_test", "today"]), "", ""))
                if rng.random() < .2:
                    ev.append(("share_visit", rng.choice(["type_test", "today"]), "", ""))
                for kind, item, value, extra in ev:
                    # OR IGNORE: 날짜가 겹친 퀴즈·투표는 한 사람 한 번 (ux_eng_once)
                    n += conn.execute("INSERT OR IGNORE INTO engagements (kind, item, value, extra, visitor, created_at) VALUES (?,?,?,?,?,?)",
                                      (kind, item, value, extra, vis, ts)).rowcount
        conn.commit()
    finally:
        conn.close()
    return n


K_MIN = 3  # 공개 지도에서 서로 다른 참여자가 이보다 적은 칸은 '기타(소수)'로 묶는다 (재식별 방지 — 건수가 아니라 사람 수)


def _map_people(include_sample: bool) -> dict:
    """공개 지도 칸별 '서로 다른 방문자' 집합 크기 — (종류, 나라)와 (종류, 나라, 속성, 값)."""
    where = [f"e.kind IN ({','.join('?' * len(_MAP_KINDS))})", f"p.country IN ({','.join('?' * len(COUNTRIES))})"]
    params: list = [*_MAP_KINDS, *COUNTRIES]
    if not include_sample:
        where.append("e.visitor NOT LIKE ?"); params.append(SAMPLE + "%")
    sql = (f"SELECT DISTINCT e.visitor, p.country, p.region, p.gender, p.age, e.kind, "
           f"CASE e.kind WHEN 'type_test' THEN e.item ELSE '' END AS t FROM engagements e JOIN profiles p ON p.visitor = e.visitor "
           f"WHERE {' AND '.join(where)}")
    people: dict = {}
    conn = _conn()
    try:
        for v, country, region, gender, age, kind, t in conn.execute(sql, params):
            c = COUNTRIES[country]
            for k in ("", kind):
                people.setdefault((k, c), set()).add(v)
                for attr, val in (("a", age), ("g", gender), ("t", t), ("r", region)):
                    if val:
                        people.setdefault((k, c, attr, val), set()).add(v)
    finally:
        conn.close()
    return {key: len(s) for key, s in people.items()}


def map_public(include_sample: bool = False) -> dict:
    """공개 지도용 — 나라별·콘텐츠별로 서버에서 묶고, 적은 칸은 숨긴다. 참여 한 건씩의 행·날짜는 내보내지 않는다."""
    agg: dict[str, dict[str, dict]] = {}
    sample = 0
    for r in _map_rows(None, include_sample, grouped=True):  # DB에서 칸별로 묶어 온다 (1만 명: 18만 행 → 수천 행)
        n = r["n"]
        sample += n if r["s"] else 0
        for k in ("", r["kind"]):
            c = agg.setdefault(k, {}).setdefault(COUNTRIES[r["country"]], {
                "n": 0, "ok": 0, "okn": 0, "a": Counter(), "g": Counter(), "t": Counter(), "r": Counter()})
            c["n"] += n
            if r["ok"] is not None:
                c["okn"] += n
                c["ok"] += int(r["ok"]) * n
            c["a"][r["age"]] += n
            c["g"][r["gender"]] += n
            if r["t"]:
                c["t"][r["t"]] += n
            if r["region"]:
                c["r"][r["region"]] += n

    people = _map_people(include_sample)

    def fold(k: str, code: str, attr: str, counter: Counter) -> dict:
        ok = lambda val: people.get((k, code, attr, val), 0) >= K_MIN  # noqa: E731
        out = {val: n for val, n in counter.items() if ok(val)}
        rest = sum(n for val, n in counter.items() if not ok(val))
        if rest:
            out["기타(소수)"] = rest
        return out

    for k, countries in agg.items():
        for code in list(countries):
            c = countries[code]
            if people.get((k, code), 0) < K_MIN:
                del countries[code]
                continue
            for key in ("a", "g", "t", "r"):
                c[key] = fold(k, code, key, c[key])
            if c["okn"] < K_MIN:
                c["ok"] = c["okn"] = 0
    return {"public": True, "agg": agg, "regions": KR_REGIONS, "countries": COUNTRIES, "genders": GENDERS,
            "ages": AGES, "profiles": _profile_count(include_sample), "sample": sample}
