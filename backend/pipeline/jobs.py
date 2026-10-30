"""배치 작업: 수집 → 노트 초안 → 주간 흐름 → 뉴스레터.

AI_NEWS의 run_pipeline.run()/start_background_run()을 옮겨 왔다. 작업 종류(kind)별로
동시에 하나만 돌고, 결과는 run_logs에 남는다. 스케줄러와 관리 화면 버튼이 같은
start()를 호출한다.
"""
from __future__ import annotations

import asyncio
import logging
import hashlib
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv

from . import alerts, db, fetch, industry, joblog, llm, mailer, notify, report_pdf, settings_store, vectorizer, warehouse
from .collectors import collect_source
from .config import load_sources_config
from .dedup import dedup_by_title_similarity, dedup_by_url_hash
from .filters import apply_keyword_filter
from .models import Item

log = logging.getLogger("axreview.jobs")
joblog.install()
SOURCES_FILE = db.ROOT / "config" / "sources.yaml"
KIND_LABELS = {"collect": "수집", "draft": "노트 초안", "weekly": "주간 흐름", "newsletter": "뉴스레터",
               "vectorize": "벡터화", "teams": "Teams 발송", "report": "주간 PDF", "warehouse": "Databricks 적재"}
# 이 작업들이 끝나면 (Databricks 설정이 있고 자동 적재가 켜져 있을 때) 바뀐 데이터를 적재한다.
_SYNC_AFTER = {"collect", "draft", "weekly", "newsletter"}

_state_lock = threading.Lock()
_active: dict[str, str] = {}  # kind -> 시작 시각
_LEASE_SEC = 3 * 3600  # 프로세스가 죽어 풀지 못한 잠금은 3시간 뒤 자동으로 풀린다


def config() -> dict:
    return load_sources_config(str(SOURCES_FILE))


def _model(cfg: dict, purpose: str = "model") -> str:
    """purpose: score_model / note_model / weekly_model / chat_model (config/sources.yaml)."""
    g = cfg.get("pipeline", {}).get("gemini", {})
    return g.get(purpose) or g.get("model", "gemini-2.5-flash")


def _http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; AXReviewBot/1.0)"})


# ───────────────────────── 1) 수집 ─────────────────────────

async def _collect_one(src: dict, client: httpx.AsyncClient) -> list[Item]:
    t0 = time.perf_counter()
    try:
        items = await collect_source(src, client, os.environ.get("NAVER_CLIENT_ID", ""),
                                     os.environ.get("NAVER_CLIENT_SECRET", ""),
                                     os.environ.get("REDDIT_CLIENT_ID", ""), os.environ.get("REDDIT_CLIENT_SECRET", ""))
    except Exception as e:
        log.warning("✗ %s 실패 (%.1fs): %s", src["name"], time.perf_counter() - t0, f"{type(e).__name__}: {e}"[:160])
        raise
    log.info("✓ %s %d건 (%.1fs)", src["name"], len(items), time.perf_counter() - t0)
    return items


async def _collect_raw(sources: list[dict]) -> tuple[list[Item], dict, dict]:
    log.info("소스 %d곳 동시 수집 시작", len(sources))
    async with _http_client() as client:
        results = await asyncio.gather(*(_collect_one(src, client) for src in sources), return_exceptions=True)
    items: list[Item] = []
    per_source: dict[str, int] = {}
    errors: dict[str, str] = {}
    for src, result in zip(sources, results):
        if isinstance(result, Exception):
            errors[src["name"]] = f"{type(result).__name__}: {result}"[:300]
            continue
        ok = [it for it in result if it.url.lower().startswith(("http://", "https://"))]  # javascript: 등 차단
        per_source[src["name"]] = len(ok)
        items.extend(ok)
    return items, per_source, errors


def preview(source_names: list[str]) -> tuple[list[Item], dict]:
    """DB에 쓰지 않고 지정 소스만 수집해 본다 (관리 > 수집 테스트)."""
    load_dotenv(db.ROOT / ".env")
    sources = [s for s in config()["sources"] if s["name"] in source_names]
    items, _, errors = asyncio.run(_collect_raw(sources))
    return items, errors


def pending_items(within_days: int = 14) -> list[Item]:
    """이전 수집에서 Gemini 한도·장애로 채점되지 못한 기사 (이번 수집 채점 요청에 함께 싣는다)."""
    return [
        Item(title=a["title"], url=a["url"], source=a["source"], source_type=a["source_type"],
             published_at=datetime.fromisoformat(a["published_at"]), excerpt=a["excerpt"] or "",
             url_hash=a["url_hash"])
        for a in db.unscored_articles(within_days)
    ]


def collect(only_sources: list[str] | None = None) -> dict:
    cfg = config()
    all_sources = cfg["sources"]
    if only_sources is not None:
        sources = [s for s in all_sources if s["name"] in only_sources]
    else:
        enabled = set(settings_store.enabled_sources([s["name"] for s in all_sources]))
        sources = [s for s in all_sources if s["name"] in enabled]

    items, per_source, errors = asyncio.run(_collect_raw(sources))
    log.info("수집 완료: %d건 (실패 소스 %d곳)", len(items), len(errors))
    dd = cfg.get("pipeline", {}).get("dedup", {})
    fresh = dedup_by_url_hash(items, db.get_existing_url_hashes())
    log.info("URL 중복 제거: %d → %d건", len(items), len(fresh))
    before = len(fresh)
    fresh = dedup_by_title_similarity(fresh, db.get_recent_titles(dd.get("title_recent_days", 7)),
                                      threshold=dd.get("title_similarity_threshold", 88))
    log.info("제목 유사도 중복 제거: %d → %d건", before, len(fresh))
    filtered = apply_keyword_filter(fresh, db.load_active_keyword_rules())
    log.info("키워드 필터 통과: %d → %d건", len(fresh), len(filtered))

    scored = rescored = 0
    pool = llm.pool_from_env()
    provider = llm.provider_name()
    batch = cfg.get("pipeline", {}).get("gemini", {}).get("score_batch_size", 150)
    # 이번 새 기사 + 지난번 못 매긴 기사를 한 요청에 묶는다 (무료 등급은 요청 횟수가 빠듯하다)
    pending = pending_items() if pool else []
    todo = filtered + pending
    stats: dict = {}  # unparsed(응답 파싱 실패)·failed(호출 실패) — judge 가 경고 원인을 가려 쓴다
    exhausted = False
    if todo and pool:
        log.info("%s AX 관련도 채점: 새 기사 %d건 + 지난 미채점 %d건 → 요청 %d번 (최대 %d건씩)",
                 provider, len(filtered), len(pending), -(-len(todo) // batch), batch)
        try:
            llm.score_items(todo, pool, _model(cfg, "score_model"), batch, stats)
        except llm.AllKeysExhausted:
            exhausted = True
            log.warning("%s 채점 불가 (한도 소진·호출 실패) — 점수 없이 저장, 다음 수집 때 다시 채점", provider)
        scored = sum(1 for it in filtered if it.llm_score)
        done = [it for it in pending if it.llm_score]
        db.update_article_scores([(it.url_hash, it.summary_ko, it.llm_score) for it in done])
        rescored = len(done)
        log.info("채점 완료: 새 기사 %d/%d건, 지난 미채점 %d/%d건", scored, len(filtered), rescored, len(pending))
    db.upsert_articles(filtered)
    log.info("DB 저장: %d건", len(filtered))
    return {
        "rescored": rescored,
        "collected": len(items), "new": len(fresh), "filtered": len(filtered), "scored": scored,
        "gemini": bool(pool), "provider": provider, "unparsed": stats.get("unparsed", 0), "exhausted": exhausted,
        "per_source": per_source, "source_errors": errors,
    }


# ───────────────────────── 2) 노트 초안 ─────────────────────────

def draft(per_run: int | None = None, min_score: int | None = None, hashes: list[str] | None = None) -> dict:
    pool = llm.pool_from_env()
    if not pool:
        raise RuntimeError("AI 모델 키(GEMINI_API_KEYS 또는 Claude)가 없어 노트 초안을 쓸 수 없습니다")
    cfg = config()
    if hashes:
        targets = [a for h in hashes if (a := db.article(h))]
    else:
        s = settings_store.load()["drafting"]
        targets = db.draft_candidates(min_score or s["min_score"], per_run or s["per_run"])

    model = _model(cfg, "note_model")
    max_chars = cfg.get("pipeline", {}).get("article_max_chars", 15000)

    log.info("노트 초안 대상 %d건", len(targets))

    def _one(art: dict) -> dict | None:
        if db.note_for_article(art["url_hash"]):
            db.set_article_status(art["url_hash"], "drafted")
            log.info("이미 노트가 있음 — 건너뜀: %s", art["title"][:50])
            return None
        text, full = fetch.article_text(art, max_chars)
        log.info("원문 %s: %s (%d자)", "확보" if full else "발췌만", art["title"][:50], len(text))
        try:
            note = llm.write_note(art, text, pool, model)
        except Exception as e:  # noqa: BLE001 - 한 건 실패로 나머지를 막지 않는다
            log.warning("노트 초안 실패 %s: %s", art["url"], e)
            return None
        note_id = db.add_note(**note, source=art["source"], url=art["url"], status="draft",
                              article_hash=art["url_hash"])
        db.set_article_status(art["url_hash"], "drafted")
        log.info("✓ 초안 저장 #%d %s", note_id, note["title"][:50])
        return {"id": note_id, "title": note["title"], "full_text": full}

    # 기사마다 원문 받기 + Gemini 호출이라 정상 키 수만큼 병렬로 돌린다.
    with ThreadPoolExecutor(max_workers=pool.workers(model)) as ex:
        results = list(ex.map(_one, targets))
    created = [r for r in results if r]
    failed = [a["title"][:60] for a, r in zip(targets, results) if not r]
    return {"targets": len(targets), "created": created, "failed": failed}


# ───────────────────────── 3) 주간 흐름 ─────────────────────────

def week_bounds(day: date) -> tuple[date, date]:
    monday = day - timedelta(days=day.weekday())
    return monday, monday + timedelta(days=6)


def week_label(monday: date) -> str:
    """'10월 4주'. 목요일이 속한 달 기준(ISO 주차 방식)으로 그 달의 몇 번째 주인지 센다."""
    thursday = monday + timedelta(days=3)
    first = thursday.replace(day=1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return f"{thursday.month}월 {(thursday - first_thursday).days // 7 + 1}주"


def weekly(target_day: date | None = None, auto_publish: bool | None = None) -> dict:
    """target_day가 속한 주(월~일)의 게시 노트로 주간 흐름을 쓴다. 기본은 지난주."""
    pool = llm.pool_from_env()
    if not pool:
        raise RuntimeError("AI 모델 키(GEMINI_API_KEYS 또는 Claude)가 없어 주간 흐름을 쓸 수 없습니다")
    monday, sunday = week_bounds(target_day or date.today() - timedelta(days=7))
    # 같은 주의 흐름(초안이든 게시든)이 이미 있으면 다시 만들지 않는다 — 놓친 작업 따라잡기·수동 실행이 겹치면 같은 주가 두 번 생겼다
    dup = next((i for i in db.issues(None) if i.get("week_start") == monday.isoformat()), None)
    if dup:
        log.info("%s 주간 흐름이 이미 있어(#%d, %s) 건너뜁니다", week_label(monday), dup["id"], dup["status"])
        return {"issue_id": dup["id"], "week": week_label(monday), "notes": 0, "published": dup["status"] == "published",
                "pdf": None, "skipped": True}
    notes = db.notes_published_between(monday.isoformat(), sunday.isoformat())
    if not notes:
        raise RuntimeError(f"{monday}~{sunday}에 게시된 노트가 없습니다")
    range_ = f"{monday:%Y.%m.%d} – {sunday:%m.%d}"
    published = db.issues("published")
    prev = published[-1] if published else None
    prev_headline = f"{prev['headline_em']} {prev['headline']}".strip() if prev else ""
    log.info("%s 게시 노트 %d편으로 주간 흐름 작성", range_, len(notes))
    text = llm.write_weekly(notes[:30], range_, prev_headline, pool, _model(config(), "weekly_model"))
    log.info("%s 응답: %s %s", llm.provider_name(), text["headline_em"], text["headline"][:60])
    if auto_publish is None:
        auto_publish = settings_store.load()["weekly"]["auto_publish"]
    issue_id = db.add_issue(week_label(monday), range_, text["headline_em"], text["headline"], text["body"],
                            status="published" if auto_publish else "draft", week_start=monday.isoformat())
    pdf = None
    if auto_publish:
        try:
            pdf = report(issue_id)["file"]
        except Exception as e:  # noqa: BLE001 - PDF 실패가 주간 흐름 게시를 막지 않게
            log.warning("주간 PDF 생성 실패: %s", e)
    return {"issue_id": issue_id, "week": week_label(monday), "notes": len(notes), "published": auto_publish,
            "pdf": pdf}


# ───────────────────────── 4) 뉴스레터 ─────────────────────────

def newsletter_content() -> tuple[dict | None, list[dict], str]:
    """(최신 게시 주간 흐름, 지난 발송 이후 새 노트, 제목)."""
    published = db.issues("published")
    issue = published[-1] if published else None
    since = (db.last_newsletter_at() or "")[:10]
    # 노트의 published 는 날짜뿐이라, 발송 당일 늦게 게시된 노트가 빠지지 않게 >= 로 본다 (당일 먼저 실린 노트가 한 번 더 실릴 수는 있다)
    notes = [n for n in db.notes("published") if n["published"] >= since][:10] if since else db.notes()[:10]
    subject = f"[AX Review] {issue['week']} · {issue['headline_em'] or issue['headline']}" if issue \
        else f"[AX Review] 새 노트 {len(notes)}편"
    return issue, notes, subject


def newsletter(trigger: str = "수동", only_to: str | None = None) -> dict:
    issue, notes, subject = newsletter_content()
    if not notes and not issue:
        raise RuntimeError("보낼 내용이 없습니다")
    if only_to:
        recipients = [(only_to, "")]
        subject = f"[테스트] {subject}"
    else:
        subs = db.subscribers(active_only=True)
        recipients = [(s["email"], s["token"]) for s in subs]
        if not recipients:
            raise RuntimeError("확인된 구독자가 없습니다")
    # 같은 호를 다시 보내면(중간 실패 후 재실행) 이미 받은 사람은 건너뛴다.
    # 키에 발송 주(KST 월요일)를 넣는다 — 제목만 쓰면 새 주간 흐름이 없는 주는 제목이 같아 조용히 0명에게 나갔다.
    monday, _ = week_bounds(datetime.now(db.KST).date())
    send_key = f"{monday.isoformat()}|{subject}"
    hash_of = lambda e: hashlib.sha256(e.lower().encode()).hexdigest()[:32]  # noqa: E731
    if not only_to:
        done = db.already_sent(send_key)
        skipped = sum(hash_of(e) in done for e, _ in recipients)
        recipients = [(e, t) for e, t in recipients if hash_of(e) not in done]
        if skipped:
            log.info("이미 받은 %d명은 건너뜀", skipped)
        if not recipients:
            return {"subject": subject, "sent": 0, "failed": 0, "notes": len(notes), "skipped": skipped}
    by_token = {s["token"]: s for s in ([] if only_to else subs)}
    log.info("메일 발송 시작: %d명 · %s", len(recipients), subject)
    pdf = latest_report_url()
    shared = mailer.prepare(issue, notes, pdf, send_key=send_key)  # 퀴즈·투표·용어 블록은 호마다 한 번 (수신자 전원 같은 문제)
    ok, failed = mailer.send(
        recipients, subject,
        lambda token: mailer.render(shared, token, industries=industry.parse((by_token.get(token) or {}).get("industries")),
                                    refer_key=(by_token.get(token) or {}).get("ref_key") or "",
                                    visitor=(by_token.get(token) or {}).get("visitor") or ""),  # 이어진 브라우저가 있어야 개인 블록
        claim=None if only_to else (lambda e: db.claim_send(send_key, hash_of(e))),
        release=None if only_to else (lambda e: db.release_send(send_key, hash_of(e))))
    if not only_to:
        db.record_newsletter(issue["id"] if issue else None, subject, len(recipients), len(failed), trigger)
    # 실패 주소는 작업 기록(→ Databricks)에 남기지 않고 건수만 — 개인정보
    if failed:
        log.warning("발송 실패 %d건", len(failed))
    return {"subject": subject, "sent": ok, "failed": len(failed), "notes": len(notes)}


# ───────────────────────── 5) 벡터화 ─────────────────────────

def vectorize(limit: int = 300) -> dict:
    if not vectorizer.has_api_keys():
        raise RuntimeError("GEMINI_API_KEYS가 없어 벡터화할 수 없습니다")
    log.info("임베딩 없는 노트·기사 최대 %d건 벡터화", limit)
    result = vectorizer.vectorize(limit)
    for t, v in result.items():
        log.info("%s: %d/%d건 완료", "노트" if t == "notes" else "기사", v["embedded"], v["pending"])
    return result


# ───────────────────────── 6) 주간 PDF 리포트 ─────────────────────────

def report_content(issue: dict | None = None) -> tuple[dict | None, list[dict], dict]:
    """(주간 흐름, 그 주 노트 최대 10편, 통계). issue가 없으면 최신 게시 흐름."""
    if issue is None:
        published = db.issues("published")
        issue = published[-1] if published else None
    if issue and issue.get("week_start"):
        monday = date.fromisoformat(issue["week_start"])
        notes = db.notes_published_between(monday.isoformat(), (monday + timedelta(days=6)).isoformat())
        start = datetime.combine(monday, datetime.min.time()).astimezone().isoformat()
        arts = [a for a in db.articles(60) if a["collected_at"] >= start]
    else:
        notes, arts = db.notes("published"), db.articles(7)
    stats = {"notes": len(notes), "collected": len(arts), "sources": len({a["source"] for a in arts})}
    return issue, notes[:10], stats


def report(issue_id: int | None = None) -> dict:
    issue = next((i for i in db.issues("published") if i["id"] == issue_id), None) if issue_id else None
    issue, notes, stats = report_content(issue)
    if not notes:
        raise RuntimeError("리포트에 넣을 게시 노트가 없습니다")
    log.info("PDF 렌더링 (Edge): 노트 %d편", len(notes))
    pdf = report_pdf.render_pdf(report_pdf.full_html(report_pdf.build_deck_html(issue, notes, stats)))
    path = report_pdf.report_path(issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pdf)
    return {"file": path.name, "pages": len(notes) + 2, "bytes": len(pdf), "issue_id": issue["id"] if issue else None}


def latest_report_url() -> str | None:
    published = db.issues("published")
    issue = published[-1] if published else None
    return report_pdf.report_url(mailer.site_url(), issue) if report_pdf.report_path(issue).exists() else None


# ───────────────────────── 7) Teams 발송 ─────────────────────────

def teams_content() -> tuple[dict | None, list[dict]]:
    """(최신 주간 흐름, 지난 Teams 발송 이후 새 노트)."""
    published = db.issues("published")
    issue = published[-1] if published else None
    since = (db.last_run_ok("teams") or "")[:10]
    notes = [n for n in db.notes("published") if not since or n["published"] > since]
    return issue, notes


def teams(only_url: str | None = None) -> dict:
    if only_url:
        hooks = [{"name": "테스트", "url": only_url}]
    else:
        hooks = [w for w in settings_store.load()["webhooks"] if w.get("enabled", True)]
    if not hooks:
        raise RuntimeError("활성화된 Teams 웹훅이 없습니다")
    issue, notes = teams_content()
    if not issue and not notes:
        raise RuntimeError("보낼 내용이 없습니다")
    payload = notify.build_card(issue, notes, mailer.site_url(), latest_report_url())
    log.info("Teams 웹훅 %d곳으로 발송", len(hooks))
    results = {w["name"]: notify.post(w["url"], payload) for w in hooks}
    failed = [name for name, (ok, _) in results.items() if not ok]
    return {"sent": len(hooks) - len(failed), "failed": failed, "notes": len(notes),
            "detail": {k: v[1] for k, v in results.items()}}


def warehouse_sync(full: bool = False) -> dict:
    log.info("Databricks 적재 대상: %s%s", warehouse.target(), " (전체 다시 적재)" if full else "")
    if full:
        warehouse.reset_state()
    return warehouse.sync()


# ───────────────────────── 백그라운드 실행 ─────────────────────────

_JOBS = {"collect": collect, "draft": draft, "weekly": weekly, "newsletter": newsletter,
         "vectorize": vectorize, "teams": teams, "report": report, "warehouse": warehouse_sync}


def active() -> dict[str, str]:
    with _state_lock:
        return dict(_active)


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def judge(kind: str, result: dict) -> tuple[bool, list[str]]:
    """(성공 여부, 경고 목록). 소스 한두 곳 실패나 Gemini 한도는 '경고', 작업 목적을 못 이룬 것만 '실패'."""
    warn = []
    if kind == "collect":
        errs = result.get("source_errors") or {}
        n_src = len(result.get("per_source") or {}) + len(errs)
        if errs:
            warn.append(f"소스 {len(errs)}곳 실패")
        unscored = result.get("filtered", 0) - result.get("scored", 0)
        name = result.get("provider") or "Gemini"
        if result.get("gemini") and result.get("filtered") and not result.get("scored"):
            # 원인을 가려 적는다 — 파싱 실패는 키를 늘려도 해결되지 않고, 한도 소진은 프롬프트를 고쳐도 소용없다
            cause = ("채점 응답 파싱 실패" if result.get("unparsed") else
                     "한도 소진" if result.get("exhausted") else "원인 불명 — 작업 로그 확인")
            warn.append(f"{name} 채점 0건 (미채점 {unscored}건, {cause})")
        elif result.get("unparsed"):
            warn.append(f"{name} 채점 응답 파싱 실패 {result['unparsed']}건")
        return not (n_src and len(errs) >= n_src * 0.5), warn  # 절반 이상 소스가 실패하면 실패
    if kind == "newsletter" and result.get("failed"):
        sent = result.get("sent", 0)
        warn.append(f"발송 실패 {result['failed']}건")
        return sent > 0, warn
    if kind == "draft" and result.get("failed"):
        warn.append(f"초안 실패 {len(result['failed'])}건")
        return bool(result.get("created")) or not result.get("targets"), warn
    return True, warn


def run(kind: str, trigger: str = "수동", **kwargs) -> dict:
    """작업 하나를 현재 스레드에서 실행하고 run_logs에 남긴다."""
    load_dotenv(db.ROOT / ".env")
    started = datetime.now().isoformat(timespec="seconds")
    if kind == "newsletter":
        kwargs.setdefault("trigger", trigger)
    try:
        result = _JOBS[kind](**kwargs)
    except Exception as e:
        log.exception("%s 작업 실패", kind)
        msg = _EMAIL_RE.sub("***@***", str(e))[:500]  # SMTP 오류 문구에 주소가 섞일 수 있다
        db.record_run_log(kind, trigger, started, ok=False, message=msg)
        alerts.job_failed(kind, trigger, msg)
        raise
    ok, warn = judge(kind, result)
    db.record_run_log(kind, trigger, started, ok=ok, message="; ".join(warn), result=result)
    if not ok:
        alerts.job_failed(kind, trigger, "; ".join(warn))
    elif warn:
        alerts.job_warning(kind, "; ".join(warn))
    if kind in _SYNC_AFTER and settings_store.load()["warehouse"]["auto_sync"] and warehouse.is_configured():
        if warehouse.breaker_tripped():
            _log_breaker_once()  # 무료 일일 한도에 걸린 날은 자동 적재를 쉰다 (수동 적재는 그대로 된다)
        else:
            start("warehouse", trigger=f"자동({KIND_LABELS[kind]} 후)")
    return result


_breaker_logged = ""  # 자동 적재 건너뜀 로그를 날짜당 한 줄만 남기기 위한 마지막 기록 날짜(KST)


def _log_breaker_once() -> None:
    global _breaker_logged
    today = datetime.now(db.KST).strftime("%Y-%m-%d")
    if _breaker_logged != today:
        _breaker_logged = today
        log.warning("Databricks 무료 일일 한도 소진 — 오늘(%s KST)은 작업 후 자동 적재를 건너뜁니다 (관리 > Databricks 수동 적재는 가능)", today)


def start(kind: str, trigger: str = "수동", **kwargs) -> bool:
    """같은 종류 작업이 돌고 있지 않으면 데몬 스레드로 시작한다."""
    with _state_lock:
        if kind in _active:
            return False
        # 프로세스 밖까지 — 서버가 두 개 떠 있어도(2026-10-29 실제로 있었음) 같은 작업이 동시에 두 번 돌지 않게 DB에 잡는다
        if not db.acquire_lease(f"job:{kind}", _LEASE_SEC):
            log.warning("%s 은(는) 다른 서버 프로세스에서 실행 중이라 건너뜁니다", KIND_LABELS[kind])
            return False
        _active[kind] = datetime.now().strftime("%H:%M:%S")
    joblog.begin(kind)

    def _worker():
        log.info("▶ %s 시작 (%s)", KIND_LABELS[kind], trigger)
        t0 = time.perf_counter()
        try:
            run(kind, trigger, **kwargs)
            log.info("■ %s 완료 (%.1fs)", KIND_LABELS[kind], time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001 - 이미 run_logs에 기록됨
            log.error("■ %s 실패 (%.1fs): %s", KIND_LABELS[kind], time.perf_counter() - t0, str(e)[:200])
        finally:
            joblog.end(kind)
            db.release_lease(f"job:{kind}")
            with _state_lock:
                _active.pop(kind, None)

    threading.Thread(target=_worker, daemon=True, name=f"job-{kind}").start()
    return True
