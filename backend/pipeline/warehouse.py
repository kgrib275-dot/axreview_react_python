"""Databricks 적재 — 앱은 로컬 SQLite로 돌고, 바뀐 행만 Databricks Delta 테이블로 MERGE한다.

화면마다 DB를 여러 번 읽는 Streamlit에 클라우드 왕복(쿼리당 0.3초+, Warehouse 기동 대기)을 넣지 않기
위해 운영 DB는 로컬에 두고, Databricks는 쌓아 두고 분석·공유하는 곳으로 쓴다.

- 대상: <catalog>.<schema> (기본 workspace.axreview — Trade_IQ와 같은 카탈로그, 스키마만 따로)
- 변경 감지: 행 내용 해시를 로컬 warehouse_sync 테이블에 기억해 바뀐 행만 보낸다. 로컬에서 지운 행은
  Databricks에서도 지운다. '전체 다시 적재'는 이 기억을 지우고 모두 보낸다.
- 보내지 않는 것: 구독자·문의(이메일)·접속 기록(IP)은 개인정보라 제외, 임베딩 열(768차원)은 용량이 커서 제외.
  참여 기록·선택 프로필은 익명 방문자 값(쿠키)과 연령대·지역 같은 묶음 값만 있어 함께 보낸다.
- 여러 행을 MERGE 한 문장에 묶는다(행마다 보내면 행당 0.3~1초 — Trade_IQ multirow.py 실측).
  값은 모두 이름 있는 파라미터로 넘긴다.

.env: DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_TOKEN
      (선택) DATABRICKS_CATALOG=workspace, DATABRICKS_SCHEMA=axreview_react
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime

import logging

from . import db, engage

log = logging.getLogger(__name__)

# 로컬 테이블 -> 기본 키
TABLES = {"articles": "url_hash", "notes": "id", "issues": "id", "article_archives": "date",
          "keywords": "id", "newsletters": "id", "run_logs": "id",
          "engagements": "id", "daily_polls": "day", "profiles": "visitor"}
TABLE_LABELS = {"articles": "수집 기사", "notes": "노트", "issues": "주간 흐름", "article_archives": "데일리 아카이브",
                "keywords": "키워드", "newsletters": "뉴스레터 발송", "run_logs": "작업 기록",
                "engagements": "참여 기록", "daily_polls": "예측 투표 문항", "profiles": "선택 프로필"}
EXCLUDED_COLUMNS = {"embedding"}
MAX_PARAMS = 600  # 한 문장에 싣는 파라미터 수 상한 (Trade_IQ와 같은 값)
_TYPES = {"INTEGER": "BIGINT", "REAL": "DOUBLE"}  # 나머지(TEXT 등)는 STRING

_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{2,100}\."
                      r"(cloud\.databricks\.com|gcp\.databricks\.com|azuredatabricks\.net|databricks\.azure\.cn|databricks\.azure\.us)$")
_PATH_RE = re.compile(r"^/sql/1\.0/(warehouses|endpoints)/[A-Za-z0-9]{8,40}$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,60}$")

_STATE_SQL = """CREATE TABLE IF NOT EXISTS warehouse_sync (
  tbl TEXT NOT NULL, pk TEXT NOT NULL, row_hash TEXT NOT NULL, synced_at TEXT NOT NULL, PRIMARY KEY (tbl, pk))"""


class NotConfigured(RuntimeError):
    pass


def settings() -> dict:
    return {
        "host": os.environ.get("DATABRICKS_SERVER_HOSTNAME", "").strip(),
        "http_path": os.environ.get("DATABRICKS_HTTP_PATH", "").strip(),
        "token": os.environ.get("DATABRICKS_TOKEN", "").strip(),
        "catalog": os.environ.get("DATABRICKS_CATALOG", "").strip() or "workspace",
        "schema": os.environ.get("DATABRICKS_SCHEMA", "").strip() or "axreview_react",
    }


def problems(cfg: dict | None = None) -> list[str]:
    """설정이 비었거나 잘못된 항목 (비어 있으면 정상)."""
    cfg = cfg or settings()
    required = {"host": "DATABRICKS_SERVER_HOSTNAME", "http_path": "DATABRICKS_HTTP_PATH", "token": "DATABRICKS_TOKEN"}
    out = [f"{env} 비어 있음" for k, env in required.items() if not cfg[k]]
    # 토큰이 엉뚱한 서버로 가지 않게 알려진 Databricks 도메인만 허용한다 (Trade_IQ와 같은 규칙).
    if cfg["host"] and not _HOST_RE.match(cfg["host"]):
        out.append("DATABRICKS_SERVER_HOSTNAME이 Databricks 도메인이 아님")
    if cfg["http_path"] and not _PATH_RE.match(cfg["http_path"]):
        out.append("DATABRICKS_HTTP_PATH 형식이 /sql/1.0/warehouses/<id>가 아님")
    for k in ("catalog", "schema"):
        if not _IDENT_RE.match(cfg[k]):
            out.append(f"DATABRICKS_{k.upper()} 이름이 올바르지 않음")
    return out


def is_configured() -> bool:
    return not problems()


def target() -> str:
    cfg = settings()
    return f"{cfg['catalog']}.{cfg['schema']}"


def _connect():
    cfg = settings()
    if problems(cfg):
        raise NotConfigured(", ".join(problems(cfg)))
    from databricks import sql as dbsql
    # 시간 제한: 접속이 걸리면 적재 작업이 '실행 중'으로 남아 이후 자동 적재가 모두 건너뛰어진다
    return dbsql.connect(server_hostname=cfg["host"], http_path=cfg["http_path"], access_token=cfg["token"],
                         _socket_timeout=120, _retry_stop_after_attempts_count=3)


# ───────────────────────── 로컬 쪽 ─────────────────────────

def _local():
    conn = db.connect()
    conn.execute(_STATE_SQL)
    conn.executescript(engage.SCHEMA)  # 참여 테이블이 아직 없어도 적재가 깨지지 않게
    return conn


def _columns(conn, table: str) -> list[tuple[str, str]]:
    """(열 이름, Databricks 타입) — 제외 열은 뺀다."""
    return [(r["name"], _TYPES.get((r["type"] or "").upper(), "STRING"))
            for r in conn.execute(f"PRAGMA table_info({table})") if r["name"] not in EXCLUDED_COLUMNS]


def _hash(row: dict) -> str:
    return hashlib.sha1(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _pseudonymize(table: str, row: dict) -> dict:
    """분석에 필요 없는 식별 연결 고리를 뺀다 — 월 구독 번호(m:<id>)·추천 코드는 members/subscribers의 이메일로 이어진다."""
    if table == "engagements":
        if str(row.get("item", "")).startswith("m:"):
            row["item"] = "m"
        if row.get("kind") in ("ref_visit",):
            row["item"] = "ref"
        if row.get("kind") == "subscribe":
            row["value"] = "ref" if row.get("value") else ""
    return row


# 행이 추가만 되고 바뀌지 않는 표(정수 id) — 전체를 읽어 해시하지 않고 마지막으로 보낸 id 뒤만 읽는다.
# 참여 기록은 사용자 수에 비례해 수백만 행까지 커지므로, 예전처럼 매번 전부 읽으면 그동안 API 가 수십 초 멈췄다(500만 행 11초+).
APPEND_ONLY = {"engagements"}


def _diff_append_only(conn, table: str, cols: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[dict], list[str]]:
    pk = TABLES[table]
    names = ", ".join(c for c, _ in cols)
    last = conn.execute("SELECT MAX(CAST(pk AS INTEGER)) FROM warehouse_sync WHERE tbl=?", (table,)).fetchone()[0] or 0
    rows = [_pseudonymize(table, dict(r)) for r in conn.execute(
        f"SELECT {names} FROM {table} WHERE {pk} > ? AND visitor NOT LIKE ? ORDER BY {pk}", (last, engage.SAMPLE + "%"))]
    # 보관 기간이 지나 지워진 행 — 비교는 SQLite 안에서 (파이썬으로 전체 키를 읽지 않게)
    deleted = [r[0] for r in conn.execute(
        f"SELECT pk FROM warehouse_sync s WHERE tbl=? AND NOT EXISTS (SELECT 1 FROM {table} t WHERE t.{pk} = CAST(s.pk AS INTEGER))",
        (table,))]
    return cols, rows, deleted


def _diff(conn, table: str) -> tuple[list[tuple[str, str]], list[dict], list[str]]:
    """(열 목록, 보낼 행, 지울 기본 키)."""
    cols = _columns(conn, table)
    if table in APPEND_ONLY:
        return _diff_append_only(conn, table, cols)
    pk = TABLES[table]
    names = ", ".join(c for c, _ in cols)
    where = f" WHERE visitor NOT LIKE '{engage.SAMPLE}%'" if table in ("engagements", "profiles") else ""  # 예시 데이터 제외
    rows = [_pseudonymize(table, dict(r)) for r in conn.execute(f"SELECT {names} FROM {table}{where}")]
    known = {r["pk"]: r["row_hash"] for r in conn.execute("SELECT pk, row_hash FROM warehouse_sync WHERE tbl=?", (table,))}
    changed = [r for r in rows if known.get(str(r[pk])) != _hash(r)]
    local_pks = {str(r[pk]) for r in rows}
    return cols, changed, [k for k in known if k not in local_pks]


def status() -> list[dict]:
    """관리 화면용 — Databricks에 접속하지 않고 로컬 기준으로 셈한다.
    전체 행을 해시해 비교하므로 무겁다 (참여 18만 행 기준 약 2초) — 화면에서는 캐시해서 부른다."""
    conn = _local()
    try:
        out = []
        for table in TABLES:
            _, changed, deleted = _diff(conn, table)
            total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            last = conn.execute("SELECT MAX(synced_at) FROM warehouse_sync WHERE tbl=?", (table,)).fetchone()[0]
            out.append({"테이블": f"{TABLE_LABELS[table]} ({table})", "로컬 행": total,
                        "적재 대기": len(changed) + len(deleted), "마지막 적재": last or "-"})
        return out
    finally:
        conn.close()


def last_synced() -> str:
    """마지막 적재 시각 (행 해시를 계산하지 않는 가벼운 조회 — 운영 점검용)."""
    conn = _local()
    try:
        return conn.execute("SELECT MAX(synced_at) FROM warehouse_sync").fetchone()[0] or "-"
    finally:
        conn.close()


def reset_state(tables: list[str] | None = None) -> None:
    """적재 기억을 지운다 — 다음 적재 때 전부 다시 보낸다."""
    conn = _local()
    try:
        for table in tables or list(TABLES):
            conn.execute("DELETE FROM warehouse_sync WHERE tbl=?", (table,))
        conn.commit()
    finally:
        conn.close()


# ───────────────────────── Databricks 쪽 ─────────────────────────

def _q(name: str) -> str:
    return f"`{name}`"  # range·date·trigger 같은 예약어 열 이름이 있다


def _ensure_table(cur, fq: str, cols: list[tuple[str, str]]) -> None:
    defs = ", ".join(f"{_q(c)} {t}" for c, t in cols)
    cur.execute(f"CREATE TABLE IF NOT EXISTS {fq} ({defs}, `_synced_at` TIMESTAMP) USING DELTA")
    cur.execute(f"DESCRIBE TABLE {fq}")
    have = {r[0] for r in cur.fetchall()}
    missing = [(c, t) for c, t in cols if c not in have]  # 로컬에 나중에 생긴 열
    if missing:
        cur.execute(f"ALTER TABLE {fq} ADD COLUMNS ({', '.join(f'{_q(c)} {t}' for c, t in missing)})")


def _merge(cur, fq: str, pk: str, cols: list[tuple[str, str]], rows: list[dict]) -> None:
    alias = ", ".join(f"c{i}" for i in range(len(cols)))
    select = ", ".join(f"CAST(c{i} AS {t}) AS {_q(c)}" for i, (c, t) in enumerate(cols))
    values, params = [], {}
    for j, row in enumerate(rows):
        values.append("(" + ", ".join(f":r{j}_{i}" for i in range(len(cols))) + ")")
        for i, (c, _) in enumerate(cols):
            params[f"r{j}_{i}"] = row[c]
    cur.execute(
        f"MERGE INTO {fq} AS t USING (SELECT {select}, current_timestamp() AS `_synced_at` "
        f"FROM VALUES {', '.join(values)} AS v({alias})) AS s ON t.{_q(pk)} = s.{_q(pk)} "
        "WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *",
        params,
    )


def _delete(cur, fq: str, pk: str, pk_type: str, keys: list[str]) -> None:
    marks = ", ".join(f"CAST(:k{i} AS {pk_type})" for i in range(len(keys)))
    cur.execute(f"DELETE FROM {fq} WHERE {_q(pk)} IN ({marks})", {f"k{i}": k for i, k in enumerate(keys)})


def test_connection() -> dict:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT current_user(), current_version().dbsql_version")
        user, version = cur.fetchone()
        cur.execute(f"SHOW SCHEMAS IN {_q(settings()['catalog'])}")
        schemas = {r[0] for r in cur.fetchall()}
    return {"user": user, "version": version, "schema_exists": settings()["schema"] in schemas}


def sync(tables: list[str] | None = None) -> dict:
    """바뀐 행을 Databricks로 MERGE한다. 테이블 하나가 실패해도 나머지는 계속한다."""
    cfg = settings()
    fq_schema = f"{_q(cfg['catalog'])}.{_q(cfg['schema'])}"
    result: dict = {"target": target(), "tables": {}, "failed": {}}
    local = _local()
    try:
        with _connect() as conn, conn.cursor() as cur:
            log.info("Databricks 접속됨 — 스키마 확인")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {fq_schema}")
            for table in tables or list(TABLES):
                pk = TABLES[table]
                fq = f"{fq_schema}.{_q(table)}"
                try:
                    cols, changed, deleted = _diff(local, table)
                    _ensure_table(cur, fq, cols)
                    size = max(1, MAX_PARAMS // len(cols))
                    for start in range(0, len(changed), size):
                        chunk = changed[start:start + size]
                        _merge(cur, fq, pk, cols, chunk)
                        now = datetime.now().isoformat(timespec="seconds")
                        # 보낸 묶음마다 기억해 두어, 중간에 실패해도 다음엔 나머지만 보낸다.
                        local.executemany(
                            "INSERT OR REPLACE INTO warehouse_sync (tbl, pk, row_hash, synced_at) VALUES (?, ?, ?, ?)",
                            [(table, str(r[pk]), _hash(r), now) for r in chunk])
                        local.commit()
                    pk_type = dict(cols)[pk]
                    for start in range(0, len(deleted), MAX_PARAMS):
                        keys = deleted[start:start + MAX_PARAMS]
                        _delete(cur, fq, pk, pk_type, keys)
                        local.executemany("DELETE FROM warehouse_sync WHERE tbl=? AND pk=?", [(table, k) for k in keys])
                        local.commit()
                    result["tables"][table] = {"upserted": len(changed), "deleted": len(deleted)}
                    log.info("✓ %s: 반영 %d · 삭제 %d", table, len(changed), len(deleted))
                except Exception as e:  # noqa: BLE001 - 테이블별로 격리
                    result["failed"][table] = f"{type(e).__name__}: {e}"[:300]
                    log.warning("✗ %s 실패: %s", table, result["failed"][table][:160])
    finally:
        local.close()
    return result
