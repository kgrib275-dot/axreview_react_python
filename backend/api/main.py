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
import threading
import time
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

from pipeline import db, settings_store  # noqa: E402  (.env 먼저)

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
    import anyio.to_thread
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100  # 동시 요청 작업 스레드 (기본 40)
    db.init_db()
    from pipeline.scheduler import start_scheduler_thread
    start_scheduler_thread()
    log.info("AX Review API 시작 · DB %s · 프론트 빌드 %s", db.DB_PATH, "있음" if DIST.exists() else "없음(npm run build 필요)")
    yield


app = FastAPI(title="AX Review API", docs_url="/api/docs" if os.environ.get("AXREVIEW_DEBUG") else None,
              redoc_url=None, openapi_url="/api/openapi.json" if os.environ.get("AXREVIEW_DEBUG") else None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)

# 보안 헤더 — 다른 사이트가 이 화면을 iframe 에 넣어 클릭을 가로채지 못하게(frame-ancestors), 형식 추측 금지 등.
# 스크립트 출처 제한(CSP script-src)은 데이터 랩·지도 문서(srcdoc)의 인라인 스크립트와 카카오 SDK 때문에 넣지 않았다.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_BODY = 64 * 1024            # 공개 API 요청 본문 상한 (관리 API 는 2MB) — 큰 본문으로 DB·백업을 불리지 못하게
MAX_BODY_ADMIN = 2 * 1024 * 1024
WRITE_PER_MIN = 240             # IP 하나가 1분에 보낼 수 있는 쓰기 요청 수 (회사 공용 IP 를 고려해 넉넉히)
_writes: dict[str, list[float]] = {}
_writes_lock = threading.Lock()


def _too_many_writes(ip: str) -> bool:
    """IP별 최근 1분 쓰기 요청 수 — 쿠키를 지워 가며 퀴즈·투표·기록을 반복해 통계를 왜곡하거나 DB를 불리는 것을 막는다."""
    now = time.monotonic()
    with _writes_lock:
        if len(_writes) > 20000:  # 메모리 상한 — 오래된 IP 정리
            for k in [k for k, v in _writes.items() if not v or now - v[-1] > 60]:
                _writes.pop(k, None)
        q = [t for t in _writes.get(ip, []) if now - t < 60]
        if len(q) >= WRITE_PER_MIN:
            _writes[ip] = q
            return True
        q.append(now)
        _writes[ip] = q
        return False


@app.middleware("http")
async def _guard(request: Request, call_next):
    # 위조 요청(CSRF) 차단 — 상태를 바꾸는 /api 요청은 우리 화면(api.ts)이 붙이는 X-Requested-With 가 있어야 한다.
    # 다른 사이트의 페이지는 이 헤더를 붙이면 브라우저가 사전 확인(CORS)을 하고, 이 서버는 CORS 를 허용하지 않으므로 막힌다.
    # 관리자 판정이 '이 PC(127.0.0.1)에서 온 요청'이라, 관리자가 이 PC에서 악성 페이지를 열면 몰래 관리자 IP 등록·발송이 되던 문제.
    if request.method not in _SAFE_METHODS and request.url.path.startswith("/api/"):
        is_admin_path = request.url.path.startswith("/api/admin/")
        try:
            size = int(request.headers.get("content-length") or 0)
        except ValueError:
            size = 0
        if size > (MAX_BODY_ADMIN if is_admin_path else MAX_BODY):
            return JSONResponse({"detail": "요청이 너무 큽니다."}, status_code=413)
        if not is_admin_path:
            raw = request.client.host if request.client else ""
            ip, _ = settings_store.client_ip(raw, dict(request.headers))
            if _too_many_writes(ip or raw or "-"):
                return JSONResponse({"detail": "요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요."}, status_code=429)
        site = request.headers.get("sec-fetch-site", "")
        if request.headers.get("x-requested-with") != "axreview" or site not in ("", "same-origin", "none"):
            # 403 이 아니라 428 — 관리 화면은 403 을 '관리자 아님'으로 보고 토큰 입력 화면으로 넘어가 버려서,
            # 이 헤더가 없는 예전 화면(배포 전에 열어 둔 탭)에서는 저장이 조용히 안 되는 것처럼 보였다 (2026-10-29).
            return JSONResponse({"detail": "화면이 예전 버전입니다. 새로고침(F5)한 뒤 다시 시도해 주세요."}, status_code=428)
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if request.headers.get("x-forwarded-proto") == "https" or request.headers.get("tailscale-funnel-request"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


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
    if hasattr(m, "root_router"):  # 접두어 없는 공개 경로 (메일 링크 /m/… — api/routers/mail_link.py)
        app.include_router(m.root_router)

# 2) 검색·공유·PDF 서버 렌더링 페이지
from app import web  # noqa: E402

for route in web.ROUTES:
    app.router.routes.append(route)

# 3) 정적 파일 — 공유 이미지 주소(/app/static/og/…)는 Streamlit 판과 같게 유지
class _CachedStatic(StaticFiles):
    """Cache-Control 을 붙인 정적 파일 — 예전엔 ETag 만 있어 다시 방문할 때마다 파일마다 확인 요청을 보냈다."""

    def __init__(self, *a, cache: str, **kw):
        super().__init__(*a, **kw)
        self._cache_header = cache

    def file_response(self, *a, **kw):
        resp = super().file_response(*a, **kw)
        resp.headers["Cache-Control"] = self._cache_header
        return resp


app.mount("/app/static", _CachedStatic(directory=ROOT / "static", cache="public, max-age=86400"), name="static")
if (DIST / "assets").exists():
    # 빌드 파일은 이름에 내용 해시가 들어가 바뀌면 이름도 바뀐다 → 1년 고정 캐시
    app.mount("/assets", _CachedStatic(directory=DIST / "assets", cache="public, max-age=31536000, immutable"), name="assets")


# 4) SPA — 나머지 GET 은 React index.html. 공유 미리보기(제목·설명·썸네일)는 응답 때 페이지별로 넣는다 (app/og_meta.py)
from app import og_meta  # noqa: E402


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404)
    file = DIST / path
    if path and file.is_file() and DIST in file.resolve().parents:
        return FileResponse(file, headers={"Cache-Control": "public, max-age=86400"})  # 로고·파비콘 등
    html = _index_html()
    if html is None:
        return HTMLResponse("<h1>AX Review</h1><p>프론트엔드를 아직 빌드하지 않았습니다: <code>cd frontend && npm run build</code></p>", status_code=503)
    # 앱에 없는 경로는 index.html 을 그대로 주되 404 로 — React 가 '페이지 없음' 화면을 그리고 검색 엔진은 soft 404 로 세지 않는다
    status = 200 if path.split("/", 1)[0] in _APP_ROUTES else 404
    return HTMLResponse(og_meta.render(html, path), status_code=status, headers={"Cache-Control": "no-cache"})


# App.tsx 가 선언한 라우트의 첫 경로 조각 ("" = 홈). og_meta.PAGES 에 있는 것은 자동으로 들어간다.
_APP_ROUTES = {p.strip("/") for p in og_meta.PAGES} | {
    "", "home", "notes", "today", "lab", "ask", "about", "type", "terms", "diagnosis", "habit", "career",
    "letter", "refer", "confirm", "unsubscribe", "privacy", "admin"}


_index: dict = {}


def _index_html() -> str | None:
    """dist/index.html — 다시 빌드하면 바로 반영되도록 수정 시각이 바뀔 때만 다시 읽는다 (페이지마다 디스크를 읽지 않게)."""
    index = DIST / "index.html"
    try:
        mtime = index.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    if _index.get("mtime") != mtime:
        _index.update(mtime=mtime, html=index.read_text(encoding="utf-8"))
    return _index["html"]
