"""Streamlit 판 DB에서 '콘텐츠'만 가져온다 — 기사·노트·주간 흐름·키워드·데일리 아카이브.

개인정보(구독자·문의·월 구독·접속 기록·참여 기록·프로필·화면 선택값)는 가져오지 않는다. 처음 한 번만 쓴다.
사용:  venv\\Scripts\\python tools\\import_content.py  "C:\\...\\AxReview\\data\\axreview.db"
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline import db  # noqa: E402

TABLES = ["keywords", "articles", "notes", "issues", "article_archives"]

src_path = Path(sys.argv[1])
db.init_db()
src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
dst = db.connect()
try:
    for t in TABLES:
        cols = [r[1] for r in dst.execute(f"PRAGMA table_info({t})")]
        src_cols = {r[1] for r in src.execute(f"PRAGMA table_info({t})")}
        use = [c for c in cols if c in src_cols]
        rows = src.execute(f"SELECT {', '.join(use)} FROM {t}").fetchall()
        if t == "keywords":
            dst.execute("DELETE FROM keywords")
        dst.executemany(f"INSERT OR IGNORE INTO {t} ({', '.join(use)}) VALUES ({', '.join('?' * len(use))})", rows)
        print(f"{t}: {len(rows)}건")
    dst.commit()
finally:
    src.close()
    dst.close()
db.optimize()
print("완료 →", db.DB_PATH)
