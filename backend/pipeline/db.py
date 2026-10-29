"""AX Review의 단일 SQLite 저장소.

AI_NEWS의 수집 테이블(articles, keywords, run_logs, access_logs)과 사이트 테이블(notes,
issues, subscribers, contacts, newsletters)을 한 DB에 둔다. 연결은 호출마다 열고 닫는다 —
Streamlit 세션 스레드와 스케줄러 스레드가 동시에 쓰기 때문에 연결을 공유하지 않는다.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from .models import Item, KeywordRule

ROOT = Path(__file__).resolve().parent.parent
# AXREVIEW_DB: 부하 테스트 등에서 복사본 DB를 쓰게 한다 (비우면 data/axreview.db).
DB_PATH = Path(os.environ["AXREVIEW_DB"]) if os.environ.get("AXREVIEW_DB") else ROOT / "data" / "axreview.db"
KEYWORDS_SEED = ROOT / "config" / "keywords.yaml"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]{1,64}@[A-Za-z0-9.-]{1,185}\.[A-Za-z]{2,24}$")  # 길이 제한 + 수식 문자(=,+로 시작) 차단

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  url_hash      TEXT PRIMARY KEY,
  url           TEXT NOT NULL,
  title         TEXT NOT NULL,
  source        TEXT NOT NULL,
  source_type   TEXT NOT NULL,
  published_at  TEXT,
  collected_at  TEXT NOT NULL,
  excerpt       TEXT,
  summary_ko    TEXT,
  llm_score     INTEGER,
  matched_kw    TEXT,
  kw_score      REAL,
  status        TEXT DEFAULT 'new'          -- new / drafted / skipped
);
CREATE TABLE IF NOT EXISTS keywords (
  id INTEGER PRIMARY KEY, keyword TEXT NOT NULL, aliases TEXT,
  mode TEXT DEFAULT 'include', weight REAL DEFAULT 1.0, active INTEGER DEFAULT 1, category TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL, source TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL, kind TEXT NOT NULL DEFAULT '아티클',
  audiences TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', published TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'published',  -- draft / published / rejected
  article_hash TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week TEXT NOT NULL, range TEXT NOT NULL,
  headline_em TEXT NOT NULL DEFAULT '', headline TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'published',  -- draft / published
  week_start TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS subscribers (
  email TEXT PRIMARY KEY, created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1, token TEXT
);
CREATE TABLE IF NOT EXISTS contacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL, email TEXT NOT NULL, company TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newsletters (
  id INTEGER PRIMARY KEY, issue_id INTEGER, subject TEXT, sent_at TEXT NOT NULL,
  recipients INTEGER, failed INTEGER, trigger TEXT
);
CREATE TABLE IF NOT EXISTS run_logs (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, trigger TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, ok INTEGER DEFAULT 1, message TEXT, result TEXT
);
CREATE TABLE IF NOT EXISTS article_archives (
  date TEXT PRIMARY KEY, content TEXT NOT NULL, total_count INTEGER NOT NULL, archived_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS newsletter_sends (
  send_key TEXT NOT NULL, email_hash TEXT NOT NULL, sent_at TEXT NOT NULL, PRIMARY KEY (send_key, email_hash)
);
CREATE TABLE IF NOT EXISTS access_logs (
  id INTEGER PRIMARY KEY, ip TEXT, page TEXT NOT NULL, action TEXT NOT NULL DEFAULT 'view',
  detail TEXT, created_at TEXT NOT NULL
);
"""

# 이전 버전 DB(샘플 사이트만 있던 시절)에 없던 컬럼 — 있으면 건너뛴다.
_MIGRATIONS = [
    ("notes", "status", "TEXT NOT NULL DEFAULT 'published'"),
    ("notes", "article_hash", "TEXT"),
    ("notes", "created_at", "TEXT"),
    ("issues", "status", "TEXT NOT NULL DEFAULT 'published'"),
    ("issues", "week_start", "TEXT"),
    ("issues", "created_at", "TEXT"),
    ("subscribers", "active", "INTEGER NOT NULL DEFAULT 1"),
    ("subscribers", "token", "TEXT"),
    ("notes", "embedding", "TEXT"),
    ("articles", "embedding", "TEXT"),
    ("issues", "editor_note", "TEXT NOT NULL DEFAULT ''"),  # 에디터 코멘트 (사람이 쓰는 관점 한두 줄)
    ("issues", "picks", "TEXT NOT NULL DEFAULT ''"),  # '리더가 알아야 할 3가지'로 직접 고른 노트 id (쉼표)
    ("subscribers", "ref_code", "TEXT NOT NULL DEFAULT ''"),  # 추천 링크 코드 (pipeline/referral.py)
    ("subscribers", "referred_by", "TEXT NOT NULL DEFAULT ''"),  # 이 구독자를 데려온 추천 코드
    ("subscribers", "industries", "TEXT NOT NULL DEFAULT ''"),  # 받고 싶은 업종 (쉼표, pipeline/industry.py)
    ("subscribers", "unsubscribed_at", "TEXT"),  # 해지 시각 — 30일 뒤 행을 지운다 (purge_expired)
    ("subscribers", "confirmed_at", "TEXT"),  # 확인 메일 링크를 누른 시각 — 이것이 있어야 발송·추천 집계 (이중 확인)
    ("subscribers", "confirm_token", "TEXT"),  # 확인 메일 링크용 (해지 토큰과 별도)
    ("subscribers", "ref_key", "TEXT"),  # 본인 추천 현황·지난 호 열람 열쇠 (해지 토큰과 별도, pipeline/referral.py)
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")  # WAL에서는 안전 — 커밋마다 디스크 동기화를 줄여 쓰기가 빨라진다
    return conn


def _rows(sql: str, params: tuple = (), keep_embedding: bool = False) -> list[dict]:
    conn = connect()
    try:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
    if not keep_embedding:
        # 임베딩(768차원 JSON)은 화면·세션 상태에 실을 필요가 없다.
        for r in rows:
            r.pop("embedding", None)
    return rows


def _exec(sql: str, params: tuple = ()) -> int:
    """쓰기 쿼리를 실행하고 영향받은 행 수를 반환한다."""
    conn = connect()
    try:
        with conn:
            return conn.execute(sql, params).rowcount
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        # WAL: 읽는 동안에도 쓸 수 있다 (기본 모드는 쓰는 동안 모든 읽기가 기다림). DB 파일에 저장되는 설정이라 한 번이면 된다.
        conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            conn.executescript(_SCHEMA)
            for table, col, ddl in _MIGRATIONS:
                cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            conn.execute("UPDATE subscribers SET token = lower(hex(randomblob(16))) WHERE token IS NULL")
            # 이중 확인 도입(2026-10-28) 전 구독자는 확인된 것으로 본다
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='app_meta'").fetchone():
                conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            if not conn.execute("SELECT 1 FROM app_meta WHERE key='doi_migrated'").fetchone():
                conn.execute("UPDATE subscribers SET confirmed_at = created_at WHERE confirmed_at IS NULL")
                conn.execute("INSERT INTO app_meta (key, value) VALUES ('doi_migrated', ?)", (_now(),))
            conn.execute("UPDATE subscribers SET ref_key = lower(hex(randomblob(16))) WHERE ref_key IS NULL AND confirmed_at IS NOT NULL")

            if not conn.execute("SELECT COUNT(*) FROM keywords").fetchone()[0] and KEYWORDS_SEED.exists():
                for e in yaml.safe_load(KEYWORDS_SEED.read_text(encoding="utf-8")) or []:
                    conn.execute(
                        "INSERT INTO keywords (keyword, aliases, mode, weight, category) VALUES (?,?,?,?,?)",
                        (e["keyword"], json.dumps(e.get("aliases", []), ensure_ascii=False),
                         e.get("mode", "include"), e.get("weight", 1.0), e.get("category", "")),
                    )
        optimize(conn)
    finally:
        conn.close()


# ───────────────────────── 노트 ─────────────────────────

def notes(status: str = "published") -> list[dict]:
    return _rows("SELECT * FROM notes WHERE status = ? ORDER BY published DESC, id DESC", (status,))


def note(note_id: int) -> dict | None:
    rows = _rows("SELECT * FROM notes WHERE id = ?", (note_id,))
    return rows[0] if rows else None


_NOTE_FIELDS = {"title", "source", "url", "category", "kind", "audiences", "tags", "summary", "body",
                "published", "status", "article_hash"}


def add_note(**fields) -> int:
    fields = {k: v for k, v in fields.items() if k in _NOTE_FIELDS}
    fields.setdefault("published", date.today().isoformat())
    fields["created_at"] = _now()
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                f"INSERT INTO notes ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                tuple(fields.values()),
            )
            return cur.lastrowid
    finally:
        conn.close()


def update_note(note_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in _NOTE_FIELDS}
    if fields:
        # 내용이 바뀌면 임베딩을 지워 다음 벡터화 때 다시 만든다.
        reset = ", embedding = NULL" if fields.keys() & {"title", "summary", "body", "tags"} else ""
        _exec(f"UPDATE notes SET {', '.join(f'{k} = ?' for k in fields)}{reset} WHERE id = ?",
              (*fields.values(), note_id))


def publish_note(note_id: int) -> None:
    _exec("UPDATE notes SET status = 'published', published = ? WHERE id = ?", (date.today().isoformat(), note_id))


def delete_note(note_id: int) -> None:
    _exec("DELETE FROM notes WHERE id = ?", (note_id,))


def notes_published_between(start: str, end: str) -> list[dict]:
    return _rows(
        "SELECT * FROM notes WHERE status = 'published' AND published BETWEEN ? AND ? ORDER BY published DESC",
        (start, end),
    )


# ───────────────────────── 주간 흐름 ─────────────────────────

def issues(status: str | None = "published") -> list[dict]:
    if status is None:
        return _rows("SELECT * FROM issues ORDER BY id DESC")
    # 주차(week_start) 순 — 지난주를 나중에 생성해도 순서가 꼬이지 않게 한다.
    return _rows("SELECT * FROM issues WHERE status = ? ORDER BY COALESCE(week_start, ''), id", (status,))


def add_issue(week: str, range_: str, headline_em: str, headline: str, body: str,
              status: str = "published", week_start: str | None = None) -> int:
    conn = connect()
    try:
        with conn:
            return conn.execute(
                "INSERT INTO issues (week, range, headline_em, headline, body, status, week_start, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (week, range_, headline_em, headline, body, status, week_start, _now()),
            ).lastrowid
    finally:
        conn.close()


def update_issue(issue_id: int, **fields) -> None:
    allowed = {"week", "range", "headline_em", "headline", "body", "status", "editor_note", "picks"}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        _exec(f"UPDATE issues SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), issue_id))


def delete_issue(issue_id: int) -> None:
    _exec("DELETE FROM issues WHERE id = ?", (issue_id,))


# ───────────────────────── 구독·문의·뉴스레터 ─────────────────────────

def subscribe(email: str, industries: str = "", referred_by: str = "", confirmed: bool = False) -> str | None:
    """구독 신청. 확인 메일을 보내야 하면 확인 토큰을, 이미 확인된 구독이면 None을 돌려준다.

    - 이중 확인: 확인 링크를 눌러야(confirm) 발송 대상·추천 집계에 들어간다 — 남의 주소를 구독시키거나
      가짜 주소로 추천 보상을 받지 못하게. confirmed=True는 관리자가 직접 넣을 때만.
    - 이미 확인된 구독은 아무것도 바꾸지 않는다(남이 업종 등을 바꾸지 못하게).
    - referred_by(추천 코드)는 처음 등록하는 주소에만 남긴다 — 재구독·자기 추천으로 보상 수를 늘리지 못하게.
    """
    email = email.strip().lower()
    now = _now()
    token = secrets.token_hex(16)
    conn = connect()
    try:
        with conn:
            row = conn.execute("SELECT active, confirmed_at FROM subscribers WHERE email = ?", (email,)).fetchone()
            if row and row["active"] and row["confirmed_at"]:
                return None
            if row:  # 확인 전 재신청·해지 후 재구독 — 다시 확인받는다
                conn.execute("UPDATE subscribers SET active = 1, industries = ?, confirm_token = ?, unsubscribed_at = NULL, "
                             "confirmed_at = ?, ref_key = COALESCE(ref_key, ?) WHERE email = ?",
                             (industries, None if confirmed else token, now if confirmed else None,
                              secrets.token_hex(16) if confirmed else None, email))
            else:
                if referred_by and not conn.execute(
                        "SELECT 1 FROM subscribers WHERE ref_code = ? AND email != ?", (referred_by, email)).fetchone():
                    referred_by = ""  # 없는 코드
                conn.execute(
                    "INSERT INTO subscribers (email, created_at, active, token, industries, referred_by, confirm_token, confirmed_at, ref_key) "
                    "VALUES (?,?,1,?,?,?,?,?,?)",
                    (email, now, secrets.token_hex(16), industries, referred_by, None if confirmed else token,
                     now if confirmed else None, secrets.token_hex(16) if confirmed else None),
                )
            return None if confirmed else token
    finally:
        conn.close()


def confirm_subscription(confirm_token: str) -> str | None:
    """확인 링크 → 구독 확정. 확정된 이메일(없으면 None). 본인 추천 열쇠(ref_key)도 이때 만든다."""
    if not confirm_token or not re.fullmatch(r"[0-9a-f]{32}", confirm_token):
        return None
    conn = connect()
    try:
        with conn:
            row = conn.execute("SELECT email, ref_key FROM subscribers WHERE confirm_token = ? AND active = 1", (confirm_token,)).fetchone()
            if not row:
                return None
            conn.execute("UPDATE subscribers SET confirmed_at = COALESCE(confirmed_at, ?), confirm_token = NULL, "
                         "ref_key = COALESCE(ref_key, ?) WHERE email = ?", (_now(), secrets.token_hex(16), row["email"]))
            return row["email"]
    finally:
        conn.close()


def pending_confirmations() -> list[dict]:
    """확인 메일을 (다시) 보낼 신청 — 관리 화면 '확인 메일 보내기'용."""
    return _rows("SELECT email, confirm_token FROM subscribers WHERE active = 1 AND confirmed_at IS NULL AND confirm_token IS NOT NULL")


def unsubscribe(token: str) -> str | None:
    rows = _rows("SELECT email FROM subscribers WHERE token = ?", (token,))
    if not rows:
        return None
    _exec("UPDATE subscribers SET active = 0, unsubscribed_at = ? WHERE token = ?", (_now(), token))
    return rows[0]["email"]


def subscribers(active_only: bool = False) -> list[dict]:
    """active_only=True: 발송 대상 = 해지하지 않았고 확인 링크를 누른 구독자."""
    where = "WHERE active = 1 AND confirmed_at IS NOT NULL" if active_only else ""
    return _rows(f"SELECT email, created_at, active, token, industries, ref_code, referred_by, confirmed_at, ref_key FROM subscribers {where} "
                 "ORDER BY created_at DESC")


def set_subscriber_active(email: str, active: bool) -> None:
    _exec("UPDATE subscribers SET active = ? WHERE email = ?", (int(active), email))


def delete_subscriber(email: str) -> None:
    _exec("DELETE FROM subscribers WHERE email = ?", (email,))


def add_contact(name: str, email: str, company: str, message: str) -> None:
    _exec(
        "INSERT INTO contacts (name, email, company, message, created_at) VALUES (?,?,?,?,?)",
        (name, email, company, message, _now()),
    )


def contacts() -> list[dict]:
    return _rows("SELECT * FROM contacts ORDER BY created_at DESC")


def record_newsletter(issue_id: int | None, subject: str, recipients: int, failed: int, trigger: str) -> None:
    _exec(
        "INSERT INTO newsletters (issue_id, subject, sent_at, recipients, failed, trigger) VALUES (?,?,?,?,?,?)",
        (issue_id, subject, _now(), recipients, failed, trigger),
    )


def newsletters() -> list[dict]:
    return _rows("SELECT * FROM newsletters ORDER BY id DESC")


def last_newsletter_at() -> str | None:
    rows = _rows("SELECT sent_at FROM newsletters WHERE recipients > failed ORDER BY id DESC LIMIT 1")
    return rows[0]["sent_at"] if rows else None


# ───────────────────────── 키워드 (AI_NEWS와 동일) ─────────────────────────

def list_keywords() -> list[dict]:
    rows = _rows("SELECT * FROM keywords ORDER BY id")
    for r in rows:
        r["aliases"] = json.loads(r["aliases"] or "[]")
        r["active"] = bool(r["active"])
    return rows


def replace_keywords(rows: list[dict]) -> None:
    """관리 화면의 편집 표 전체를 그대로 저장한다."""
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM keywords")
            for r in rows:
                if not str(r.get("keyword") or "").strip():
                    continue
                conn.execute(
                    "INSERT INTO keywords (keyword, aliases, mode, weight, active, category) VALUES (?,?,?,?,?,?)",
                    (r["keyword"].strip(), json.dumps(r.get("aliases") or [], ensure_ascii=False),
                     r.get("mode") or "include", float(r.get("weight") or 1.0),
                     int(bool(r.get("active", True))), r.get("category") or ""),
                )
    finally:
        conn.close()


def load_active_keyword_rules() -> list[KeywordRule]:
    return [
        KeywordRule(keyword=r["keyword"], aliases=r["aliases"], mode=r["mode"], weight=r["weight"],
                    category=r["category"] or "")
        for r in list_keywords() if r["active"]
    ]


# ───────────────────────── 수집 기사 ─────────────────────────

def get_existing_url_hashes() -> set[str]:
    return {r["url_hash"] for r in _rows("SELECT url_hash FROM articles")}


def get_recent_titles(days: int = 7) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return [r["title"] for r in _rows("SELECT title FROM articles WHERE collected_at >= ?", (since,))]


def upsert_articles(items: list[Item]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn = connect()
    try:
        with conn:
            for it in items:
                conn.execute(
                    "INSERT OR IGNORE INTO articles (url_hash, url, title, source, source_type, published_at,"
                    " collected_at, excerpt, summary_ko, llm_score, matched_kw, kw_score)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (it.url_hash, it.url, it.title, it.source, it.source_type, it.published_at.isoformat(), now,
                     it.excerpt, it.summary_ko, it.llm_score, json.dumps(it.matched_kw, ensure_ascii=False),
                     it.kw_score),
                )
    finally:
        conn.close()


def articles(since_days: int = 30) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
    return _rows(
        "SELECT * FROM articles WHERE collected_at >= ? ORDER BY collected_at DESC, llm_score DESC", (since,)
    )


def article(url_hash: str) -> dict | None:
    rows = _rows("SELECT * FROM articles WHERE url_hash = ?", (url_hash,))
    return rows[0] if rows else None


def draft_candidates(min_score: int, limit: int, within_days: int = 7) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    return _rows(
        "SELECT * FROM articles WHERE status = 'new' AND llm_score >= ? AND collected_at >= ?"
        " ORDER BY llm_score DESC, kw_score DESC LIMIT ?",
        (min_score, since, limit),
    )


def unscored_articles(within_days: int = 7) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    return _rows(
        "SELECT * FROM articles WHERE COALESCE(llm_score, 0) = 0 AND COALESCE(summary_ko, '') = ''"
        " AND status = 'new' AND collected_at >= ?", (since,)
    )


def update_article_scores(rows: list[tuple[str, str, int]]) -> None:
    """(url_hash, summary_ko, llm_score) 목록을 반영한다."""
    conn = connect()
    try:
        with conn:
            conn.executemany("UPDATE articles SET summary_ko = ?, llm_score = ? WHERE url_hash = ?",
                             [(s, sc, h) for h, s, sc in rows])
    finally:
        conn.close()


def set_article_status(url_hash: str, status: str) -> None:
    _exec("UPDATE articles SET status = ? WHERE url_hash = ?", (status, url_hash))


# ───────────────────────── 실행·접속 로그 ─────────────────────────

def record_run_log(kind: str, trigger: str, started_at: str, ok: bool,
                   message: str = "", result: dict | None = None) -> None:
    _exec(
        "INSERT INTO run_logs (kind, trigger, started_at, finished_at, ok, message, result) VALUES (?,?,?,?,?,?,?)",
        (kind, trigger, started_at, _now(), int(ok), message, json.dumps(result or {}, ensure_ascii=False)),
    )


def run_logs(limit: int = 200) -> list[dict]:
    return _rows("SELECT * FROM run_logs ORDER BY id DESC LIMIT ?", (limit,))


def record_access(ip: str | None, page: str, action: str = "view", detail: str = "") -> None:
    _exec(
        "INSERT INTO access_logs (ip, page, action, detail, created_at) VALUES (?,?,?,?,?)",
        (ip, page, action, detail, _now()),
    )


def access_logs(limit: int = 500) -> list[dict]:
    return _rows("SELECT * FROM access_logs ORDER BY id DESC LIMIT ?", (limit,))


def counts() -> dict:
    one = lambda sql: _rows(sql)[0]["n"]  # noqa: E731
    return {
        "articles": one("SELECT COUNT(*) n FROM articles"),
        "candidates": one("SELECT COUNT(*) n FROM articles WHERE status = 'new' AND llm_score >= 3"),
        "drafts": one("SELECT COUNT(*) n FROM notes WHERE status = 'draft'"),
        "published": one("SELECT COUNT(*) n FROM notes WHERE status = 'published'"),
        "subscribers": one("SELECT COUNT(*) n FROM subscribers WHERE active = 1"),
        "contacts": one("SELECT COUNT(*) n FROM contacts"),
    }


# ───────────────────────── 임베딩 (의미 검색) ─────────────────────────

_EMBED_TABLES = {"notes": "id", "articles": "url_hash"}


def missing_embeddings(table: str, limit: int) -> list[dict]:
    where = "status = 'published'" if table == "notes" else "COALESCE(llm_score, 0) >= 3"
    return _rows(f"SELECT * FROM {table} WHERE embedding IS NULL AND {where} ORDER BY rowid DESC LIMIT ?", (limit,))


def set_embedding(table: str, key, vector: list[float]) -> None:
    _exec(f"UPDATE {table} SET embedding = ? WHERE {_EMBED_TABLES[table]} = ?", (json.dumps(vector), key))


def clear_embedding(table: str, key) -> None:
    _exec(f"UPDATE {table} SET embedding = NULL WHERE {_EMBED_TABLES[table]} = ?", (key,))


def embedded_rows(table: str, since_days: int | None = None) -> list[dict]:
    where = "embedding IS NOT NULL"
    params: tuple = ()
    if table == "notes":
        where += " AND status = 'published'"
    elif since_days:
        where += " AND collected_at >= ?"
        params = ((datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat(),)
    rows = _rows(f"SELECT * FROM {table} WHERE {where}", params, keep_embedding=True)
    for r in rows:
        r["embedding"] = json.loads(r["embedding"])
    return rows


def embedding_signature(table: str, since_days: int | None = None) -> tuple:
    """임베딩 캐시 무효화용 (행 수, 가장 최근 시각)."""
    col = "created_at" if table == "notes" else "collected_at"
    where, params = "embedding IS NOT NULL", ()
    if table == "notes":
        where += " AND status = 'published'"
    elif since_days:
        where += " AND collected_at >= ?"
        params = ((datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat(),)
    conn = connect()
    try:
        return tuple(conn.execute(f"SELECT COUNT(*), MAX({col}) FROM {table} WHERE {where}", params).fetchone())
    finally:
        conn.close()


def embedding_counts() -> dict:
    one = lambda sql: _rows(sql)[0]["n"]  # noqa: E731
    return {
        "notes": one("SELECT COUNT(*) n FROM notes WHERE status = 'published' AND embedding IS NOT NULL"),
        "notes_total": one("SELECT COUNT(*) n FROM notes WHERE status = 'published'"),
        "articles": one("SELECT COUNT(*) n FROM articles WHERE embedding IS NOT NULL"),
        "articles_total": one("SELECT COUNT(*) n FROM articles WHERE COALESCE(llm_score, 0) >= 3"),
    }


# ───────────────────────── 데일리 아카이브 (AI_NEWS archiving) ─────────────────────────

KST = timezone(timedelta(hours=9))


def _kst_date(iso: str) -> str:
    return datetime.fromisoformat(iso).astimezone(KST).strftime("%Y-%m-%d")


def article_dates() -> set[str]:
    return {_kst_date(r["collected_at"]) for r in _rows("SELECT collected_at FROM articles")}


def articles_on(date_str: str) -> list[dict]:
    """KST 날짜 기준 그날 수집된 기사. collected_at은 UTC로 저장된다."""
    start = datetime.fromisoformat(date_str).replace(tzinfo=KST)
    end = start + timedelta(days=1)
    return _rows(
        "SELECT * FROM articles WHERE collected_at >= ? AND collected_at < ? ORDER BY llm_score DESC",
        (start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()),
    )


def archived_dates() -> list[str]:
    return [r["date"] for r in _rows("SELECT date FROM article_archives ORDER BY date DESC")]


def insert_archive(date_str: str, content: dict) -> bool:
    return _exec(
        "INSERT OR IGNORE INTO article_archives (date, content, total_count, archived_at) VALUES (?,?,?,?)",
        (date_str, json.dumps(content, ensure_ascii=False), content["total_count"], _now()),
    ) == 1


def get_archive(date_str: str) -> dict | None:
    rows = _rows("SELECT * FROM article_archives WHERE date = ?", (date_str,))
    if not rows:
        return None
    return {**json.loads(rows[0]["content"]), "archived_at": rows[0]["archived_at"]}


def access_count_today(ip: str | None, action: str) -> int:
    today = date.today().isoformat()
    return _rows(
        "SELECT COUNT(*) n FROM access_logs WHERE ip IS ? AND action = ? AND created_at >= ?", (ip, action, today)
    )[0]["n"]


def last_run_ok(kind: str) -> str | None:
    rows = _rows("SELECT started_at FROM run_logs WHERE kind = ? AND ok = 1 ORDER BY id DESC LIMIT 1", (kind,))
    return rows[0]["started_at"] if rows else None


def note_view_counts() -> dict[int, int]:
    """노트별 상세 조회 수 (access_logs의 note_view 기록)."""
    rows = _rows("SELECT detail, COUNT(*) n FROM access_logs WHERE action = 'note_view' GROUP BY detail")
    return {int(r["detail"]): r["n"] for r in rows if (r["detail"] or "").isdigit()}


def access_count_since(ip: str | None, action: str, minutes: int) -> int:
    since = (datetime.now() - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM access_logs WHERE ip IS ? AND action = ? AND created_at >= ?",
                            (ip, action, since)).fetchone()[0]
    finally:
        conn.close()


def access_count_today_all(action: str) -> int:
    """오늘 모든 접속자의 action 수 (전체 하루 한도용)."""
    return _rows("SELECT COUNT(*) n FROM access_logs WHERE action = ? AND created_at >= ?",
                 (action, date.today().isoformat()))[0]["n"]


# 보관 기간 (개인정보 처리방침 /privacy·pipeline/privacy.py가 이 값을 그대로 쓴다)
RETENTION_DAYS = {"access_logs": 90, "engagements": 395, "visitor_state": 395, "profiles": 395, "contacts": 365,
                  "unsubscribed": 30, "unconfirmed": 7, "members_expired": 180, "newsletter_sends": 365}


def purge_expired() -> dict[str, int]:
    """보관 기간이 지난 기록을 지운다 (스케줄러 하루 정리). {이름: 지운 행 수}."""
    now = datetime.now()
    ago = lambda d: (now - timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
    kst_ago = lambda d: (datetime.now(KST) - timedelta(days=d)).isoformat(timespec="seconds")  # noqa: E731
    R = RETENTION_DAYS
    stmts = {
        "접속 기록": ("DELETE FROM access_logs WHERE created_at < ?", (ago(R["access_logs"]),)),
        "참여 기록": ("DELETE FROM engagements WHERE created_at < ?", (kst_ago(R["engagements"]),)),
        "화면 선택값": ("DELETE FROM visitor_state WHERE updated_at < ?", (ago(R["visitor_state"]),)),
        "선택 프로필": ("DELETE FROM profiles WHERE updated_at < ? AND visitor NOT IN "
                    "(SELECT DISTINCT visitor FROM engagements WHERE created_at >= ?)", (kst_ago(R["profiles"]), kst_ago(R["profiles"]))),
        "문의": ("DELETE FROM contacts WHERE created_at < ?", (ago(R["contacts"]),)),
        "해지한 구독자": ("DELETE FROM subscribers WHERE active = 0 AND unsubscribed_at IS NOT NULL AND unsubscribed_at < ?",
                    (ago(R["unsubscribed"]),)),
        "확인 안 된 구독 신청": ("DELETE FROM subscribers WHERE confirmed_at IS NULL AND created_at < ?", (ago(R["unconfirmed"]),)),
        "끝난 월 구독": ("DELETE FROM members WHERE expires < ?", (ago(R["members_expired"])[:10],)),
        "발송 기록": ("DELETE FROM newsletter_sends WHERE sent_at < ?", (ago(R["newsletter_sends"]),)),
    }
    out = {}
    conn = connect()
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name, (sql, params) in stmts.items():
            table = sql.split()[2]
            if table in tables:
                with conn:
                    out[name] = conn.execute(sql, params).rowcount
    finally:
        conn.close()
    return out


def already_sent(send_key: str) -> set[str]:
    return {r["email_hash"] for r in _rows("SELECT email_hash FROM newsletter_sends WHERE send_key = ?", (send_key,))}


def mark_sent(send_key: str, email_hash: str) -> None:
    _exec("INSERT OR IGNORE INTO newsletter_sends (send_key, email_hash, sent_at) VALUES (?,?,?)", (send_key, email_hash, _now()))


def note_for_article(url_hash: str) -> bool:
    return bool(_rows("SELECT 1 FROM notes WHERE article_hash = ? LIMIT 1", (url_hash,)))


def ran_ok_since(kind: str, since: datetime) -> bool:
    rows = _rows("SELECT 1 FROM run_logs WHERE kind = ? AND ok = 1 AND started_at >= ? LIMIT 1",
                 (kind, since.isoformat(timespec="seconds")))
    return bool(rows)


def set_meta(key: str, value: str) -> None:
    _exec("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _exec("INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def get_meta(key: str) -> str | None:
    try:
        rows = _rows("SELECT value FROM app_meta WHERE key = ?", (key,))
    except sqlite3.OperationalError:
        return None
    return rows[0]["value"] if rows else None


def purge_access_logs(keep_days: int = 90) -> int:
    """오래된 접속 기록(IP 포함)을 지운다 — 개인정보 보관 기간 제한."""
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    conn = connect()
    try:
        with conn:
            return conn.execute("DELETE FROM access_logs WHERE created_at < ?", (cutoff,)).rowcount
    finally:
        conn.close()


def csv_safe(df):
    """엑셀에서 수식으로 실행될 수 있는 값(=,+,-,@로 시작)을 문자로 만든다 (CSV 수식 주입 방지)."""
    return df.map(lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)


def optimize(conn: sqlite3.Connection | None = None) -> None:
    """쿼리 계획용 통계 갱신 (PRAGMA optimize — 필요한 표만 ANALYZE). 앱 시작과 하루 한 번 정리 때 부른다.

    통계가 없으면 SQLite가 '종류' 인덱스로 수만 행을 훑는 계획을 고른다 (1만 명 실측: 방문자별 조회 50ms → 0.8ms,
    참여 지도 1.5초 → 0.3초)."""
    own = conn is None
    conn = conn or connect()
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sqlite_stat1'").fetchone():
            conn.execute("ANALYZE")
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        if own:
            conn.close()


BACKUP_DIR = ROOT / "data" / "backups"


def backup(keep: int = 14, force: bool = False) -> Path | None:
    """SQLite 온라인 백업 (앱이 쓰는 중에도 일관된 사본). 오늘 날짜 파일로 저장하고 keep개만 남긴다.

    - 오늘 백업이 이미 있으면 건너뛴다(force=True면 새로) — 손상된 DB로 재시작해 정상 백업을 덮어쓰지 않게.
    - 시험용 DB(AXREVIEW_DB)로 돌 때는 건너뛴다 — 실제 백업 폴더를 시험 데이터로 덮지 않게.
    - 만든 뒤 PRAGMA integrity_check로 확인하고, 깨졌으면 .bad로 바꾸고 오류를 낸다.
    """
    if os.environ.get("AXREVIEW_DB") and not force:
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"axreview-{datetime.now():%Y%m%d}.db"
    if dest.exists() and not force:
        return None
    tmp = dest.with_suffix(".tmp")
    src, out = connect(), sqlite3.connect(tmp)
    try:
        src.backup(out)
        check = out.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        out.close()
        src.close()
    if check != "ok":
        tmp.replace(dest.with_suffix(".bad"))
        raise RuntimeError(f"백업 무결성 검사 실패: {check}")
    tmp.replace(dest)
    for old in sorted(BACKUP_DIR.glob("axreview-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return dest


def last_backup() -> tuple[str, int] | None:
    files = sorted(BACKUP_DIR.glob("axreview-*.db")) if BACKUP_DIR.exists() else []
    if not files:
        return None
    f = files[-1]
    return datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="minutes"), f.stat().st_size
