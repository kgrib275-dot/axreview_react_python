"""AX Review API + 정적 화면 서버 (FastAPI).

한 프로세스가 맡는 것:
1. /api/…            React 화면이 쓰는 JSON API (api/routers/*)
2. /n/ /sitemap.xml /robots.txt /s/… /r/…   검색 엔진·메신저용 서버 렌더링 페이지 (app/web.py)
3. /app/static/…     공유 이미지·로고·vendor JS
4. /assets/… 와 그 밖의 모든 GET   React 빌드(frontend/dist) — 없는 경로는 index.html (SPA)
5. 배치 스케줄러 (AXREVIEW_SCHEDULER=1 일 때만 — start-public 이 설정)

실행: python serve.py  (포트 AXREVIEW_PORT, 기본 5002)
"""
from __future__ import annotations

import importlib
import logging
import os
import pkgutil
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent  # backend/
DIST = ROOT.parent / "frontend" / "dist"
load_dotenv(ROOT / ".env")

from pipeline import db  # noqa: E402  (.env 먼저)

log = logging.getLogger("axreview.api")


def _log_file() -> None:
    from logging.handlers import RotatingFileHandler
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    port = os.environ.get("AXREVIEW_PORT", "5002")
    h = RotatingFileHandler(log_dir / f"axreview-{port}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(h)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _log_file()
    db.init_db()
    from pipeline.scheduler import start_scheduler_thread
    start_scheduler_thread()
    log.info("AX Review API 시작 · DB %s · 프론트 빌드 %s", db.DB_PATH, "있음" if DIST.exists() else "없음(npm run build 필요)")
    yield


app = FastAPI(title="AX Review API", docs_url="/api/docs" if os.environ.get("AXREVIEW_DEBUG") else None,
              redoc_url=None, openapi_url="/api/openapi.json" if os.environ.get("AXREVIEW_DEBUG") else None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("처리되지 않은 오류: %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "서버 오류가 났습니다. 잠시 후 다시 시도해 주세요."}, status_code=500)  # 내부 정보 비노출


# 1) API 라우터 자동 등록
from api import routers as _routers_pkg  # noqa: E402

for mod in pkgutil.iter_modules(_routers_pkg.__path__):
    m = importlib.import_module(f"api.routers.{mod.name}")
    if hasattr(m, "router"):
        app.include_router(m.router, prefix="/api")

# 2) 검색·공유·PDF 서버 렌더링 페이지
from app import web  # noqa: E402

for route in web.ROUTES:
    app.router.routes.append(route)

# 3) 정적 파일 — 공유 이미지 주소(/app/static/og/…)는 Streamlit 판과 같게 유지
app.mount("/app/static", StaticFiles(directory=ROOT / "static"), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


# 4) SPA — 나머지 GET 은 React index.html. 공유 미리보기(제목·설명·썸네일)는 응답 때 페이지별로 넣는다 (app/og_meta.py)
from app import og_meta  # noqa: E402


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    file = DIST / path
    if path and file.is_file() and DIST in file.resolve().parents:
        return FileResponse(file)
    index = DIST / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>AX Review</h1><p>프론트엔드를 아직 빌드하지 않았습니다: <code>cd frontend && npm run build</code></p>", status_code=503)
    return HTMLResponse(og_meta.render(index.read_text(encoding="utf-8"), path), headers={"Cache-Control": "no-cache"})
