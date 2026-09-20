from __future__ import annotations

import asyncio
import io
import json
import os
import queue
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel, ConfigDict, Field

from core.dedupe import DedupeStore
from core.downloader import download_all
from core.http import build_session
from core.scraper import (
    board_pins, enrich_with_details, related_pins,
    search_pins, typeahead_suggestions,
)
from core.storage import save_outputs

STATIC_DIR = Path(__file__).parent.parent / "static"


class ScrapeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = Field(default="search", pattern="^(search|board)?$")
    query: str = Field(min_length=1)
    limit: int = Field(default=25, ge=1, le=500)
    download: bool = True
    details: bool = True
    dedup: bool = False
    workers: int = Field(default=4, ge=1, le=16)
    delay: float = Field(default=1.0, ge=0, le=30)
    jitter: float = Field(default=0.5, ge=0, le=10)
    batch_size: int = Field(default=10, ge=1, le=100)
    min_width: int = Field(default=0, ge=0, le=10000)
    min_height: int = Field(default=0, ge=0, le=10000)
    proxy: str = ""


class Job:
    def __init__(self, req: ScrapeRequest, out_dir: Path):
        self.id = uuid.uuid4().hex[:12]
        self.req = req
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.events: queue.Queue = queue.Queue()
        self.status = "queued"
        self.phase = ""
        self.pins: list[dict] = []
        self.stats: dict = {}
        self.error = ""
        self.cancelled = False
        self.done = threading.Event()

    def emit(self, **ev):
        self.events.put(json.dumps(ev, default=str, ensure_ascii=False))

    def _check_cancel(self):
        if self.cancelled:
            raise RuntimeError("cancelled by user")

    def run(self):
        try:
            self._run()
            self.status = "cancelled" if self.cancelled else "finished"
        except Exception as e:
            self.status = "cancelled" if "cancelled" in str(e) else "error"
            if self.status == "error":
                self.error = str(e)
        self.done.set()
        self.emit(event="done", status=self.status, error=self.error,
                  total=len(self.pins), stats=self.stats)

    def _run(self):
        req = self.req
        session = build_session(
            proxy_pool=[p.strip() for p in req.proxy.split(",") if p.strip()] or None
        )
        store = (
            DedupeStore(self.out_dir / ".seen_pins.json", scan_dir=self.out_dir)
            if req.dedup else None
        )
        queries = [q.strip() for q in req.query.split(",") if q.strip()] or [req.query]
        batch = len(queries) > 1
        stem = (queries[0] if not batch else queries[0] + "-batch")
        stem = stem.strip().replace(" ", "_")[:40] or "pins"

        collect_total = req.limit * len(queries)
        self.emit(event="phase", phase="collect", total=collect_total, message="Collecting pins")

        def batch_save(partial: list[dict]) -> None:
            self._check_cancel()
            new = [p for p in partial if p["pin_id"] not in {q["pin_id"] for q in self.pins}]
            if store:
                new = store.filter(new)
            self.pins.extend(new)
            self.emit(event="progress", phase="collect", count=len(self.pins), total=collect_total)
            save_outputs(self.pins, self.out_dir, stem)

        def run_one(query: str) -> list[dict]:
            self.emit(event="query_start", query=query,
                      index=queries.index(query) + 1, total=len(queries))
            if req.mode == "board":
                return board_pins(session, query, req.limit,
                                  delay=req.delay, save_cb=batch_save,
                                  batch_size=req.batch_size, jitter=req.jitter)
            return search_pins(session, query, req.limit,
                               delay=req.delay, save_cb=batch_save,
                               batch_size=req.batch_size, jitter=req.jitter)

        existing_ids = {p["pin_id"] for p in self.pins}
        raw_pins: list[dict] = []
        for q in queries:
            for p in run_one(q):
                if p["pin_id"] not in existing_ids:
                    existing_ids.add(p["pin_id"])
                    raw_pins.append(p)
            self._check_cancel()

        pins = list(raw_pins)

        if not pins:
            clean_stem = re.sub(r"[^\w\-]+", "_", stem.lower().strip())
            for candidate in (f"{stem}.json", f"{clean_stem}.json", f"{stem.lower()}.json"):
                cached = self.out_dir / candidate
                if cached.exists():
                    try:
                        loaded = json.loads(cached.read_text(encoding="utf-8"))
                        if isinstance(loaded, list) and loaded:
                            pins = loaded
                            break
                    except Exception:
                        pass

        img_dir = self.out_dir / "images"
        if img_dir.exists():
            for p in pins:
                if not p.get("local_file"):
                    for ext in (".jpg", ".png", ".webp", ".jpeg"):
                        candidate = img_dir / f"{p['pin_id']}{ext}"
                        if candidate.is_file() and candidate.stat().st_size > 0:
                            p["local_file"] = candidate.name
                            break

        self.pins = pins

        if not pins:
            self.emit(event="nothing_new", total=0)
            return

        if req.details:
            self.emit(event="phase", phase="details", total=len(pins))
            done = {"n": 0}

            def _detail_cb(n):
                if self.cancelled:
                    raise RuntimeError("cancelled by user")
                done["n"] = max(done["n"], n)
                self.emit(event="progress", phase="details", count=done["n"], total=len(pins))

            enrich_with_details(session, pins, delay=req.delay,
                                workers=req.workers, jitter=req.jitter,
                                progress_cb=_detail_cb)
            self._check_cancel()

        if req.download:
            self.emit(event="phase", phase="download", total=len(pins))

            def _dl_cb(n):
                if self.cancelled:
                    raise RuntimeError("cancelled by user")
                self.emit(event="progress", phase="download", count=n, total=len(pins))

            self.stats = download_all(
                session, pins, self.out_dir / "images",
                req.workers, req.min_width, req.min_height,
                progress_cb=_dl_cb,
            )
            self._check_cancel()

        summary = save_outputs(pins, self.out_dir, stem)
        if store:
            store.add(pins)
            store.save()
        self.pins = pins
        self.emit(event="saved",
                  json_file=str(summary.get("json", "")),
                  csv_file=str(summary.get("csv", "")))


JOBS: dict[str, Job] = {}


def _out_dir() -> Path:
    return Path("web_output")


app = FastAPI(
    title="Pinterest Scraper",
    version="1.4.0",
    description=(
        "High-quality Pinterest scraper API. "
        "Search pins, boards, or visually similar content — "
        "with batch download, metadata export, and gallery management."
    ),
    docs_url=None,
    redoc_url=None,
)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schema["info"]["x-logo"] = {"url": "/static/og-image.png"}
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DOCS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#E60023">
<meta name="description" content="Pinterest Scraper API — scrape pins with full metadata, batch download, and export.">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Pinterest Scraper">
<meta property="og:title" content="Pinterest Scraper — API Reference">
<meta property="og:description" content="High-quality Pinterest scraper API with job events, exports, and gallery.">
<meta property="og:image" content="/static/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Pinterest Scraper — API Reference">
<meta name="twitter:description" content="High-quality Pinterest scraper API with job events, exports, and gallery.">
<meta name="twitter:image" content="/static/og-image.png">
<title>Pinterest Scraper · API Docs</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='48' fill='%23E60023'/><text x='50' y='72' font-size='60' text-anchor='middle' fill='white' font-family='serif' font-weight='bold'>P</text></svg>">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #FCFCFD; font-family: 'Inter', -apple-system, sans-serif; }
  body::before {
    content: '';
    position: fixed; inset: 0;
    background:
      radial-gradient(ellipse 800px 600px at 20% -10%, rgba(230, 0, 35, 0.06), transparent 50%),
      radial-gradient(ellipse 800px 600px at 100% 0%, rgba(139, 92, 246, 0.05), transparent 50%);
    pointer-events: none;
    z-index: 0;
  }
  .docs-topbar {
    position: sticky; top: 0; z-index: 100;
    display: flex; align-items: center; gap: 14px;
    padding: 14px 24px;
    background: #FCFCFD;
    border-bottom: 1px solid rgba(0,0,0,.06);
  }
  .docs-logo { display: flex; align-items: center; gap: 10px; text-decoration: none; color: inherit; }
  .docs-logo-badge {
    width: 36px; height: 36px; border-radius: 50%;
    background: linear-gradient(135deg, #FF1E3D 0%, #E60023 50%, #8B0020 100%);
    color: #fff; display: grid; place-items: center;
    font-size: 1.1rem; font-weight: 800;
    box-shadow: 0 12px 32px rgba(230,0,35,.25), inset 0 1px 0 rgba(255,255,255,.25);
  }
  .docs-logo-name { font-weight: 800; font-size: 1rem; letter-spacing: -0.03em; color: #0A0A0B; }
  .docs-logo-tag {
    font-size: .62rem; font-weight: 700;
    padding: 3px 8px; border-radius: 999px;
    background: #E60023; color: #fff;
    letter-spacing: .04em;
  }
  .docs-nav { margin-left: auto; display: flex; gap: 10px; align-items: center; }
  .docs-nav a {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: .84rem; font-weight: 600;
    text-decoration: none; color: #1F1F23;
    background: #fff;
    border: 1px solid rgba(0,0,0,.08);
    transition: all .15s ease;
  }
  .docs-nav a:hover { background: #F1F1F4; border-color: rgba(0,0,0,.12); }
  .docs-nav a.primary { background: #E60023; color: #fff; border-color: transparent; box-shadow: 0 4px 12px rgba(230,0,35,.3); }
  .docs-nav a.primary:hover { background: #C4001E; transform: translateY(-1px); }
  #swagger-ui { position: relative; z-index: 1; max-width: 1200px; margin: 0 auto; padding: 24px; }
  .swagger-ui .topbar { display: none !important; }
  .swagger-ui .info { margin: 24px 0 36px; }
  .swagger-ui .info .title { font-family: 'Inter', sans-serif; font-weight: 800; letter-spacing: -0.03em; font-size: 2rem; color: #0A0A0B; }
  .swagger-ui .info .title small { background: #E60023; padding: 3px 8px; border-radius: 999px; font-size: .65rem; }
  .swagger-ui .info .title small pre { background: transparent; }
  .swagger-ui .info p, .swagger-ui .info li { font-family: 'Inter', sans-serif; color: #6E6E78; }
  .swagger-ui .scheme-container {
    background: #fff; box-shadow: none; border: 1px solid rgba(0,0,0,.06);
    border-radius: 16px; padding: 16px 20px; margin: 0 0 24px;
  }
  .swagger-ui .opblock-tag {
    font-family: 'Inter', sans-serif; font-weight: 700; font-size: 1.1rem;
    color: #0A0A0B; border-bottom: 1px solid rgba(0,0,0,.06);
    padding: 16px 10px; margin: 8px 0;
  }
  .swagger-ui .opblock-tag:hover { background: #F1F1F4; border-radius: 12px; }
  .swagger-ui .opblock {
    border-radius: 14px;
    border: 1px solid rgba(0,0,0,.06);
    box-shadow: 0 1px 2px rgba(0,0,0,.04);
    margin: 8px 0;
    overflow: hidden;
    background: #fff;
  }
  .swagger-ui .opblock .opblock-summary { border-bottom: none; padding: 10px 16px; }
  .swagger-ui .opblock.opblock-get { background: rgba(59, 130, 246, 0.04); border-color: rgba(59, 130, 246, 0.2); }
  .swagger-ui .opblock.opblock-get .opblock-summary-method { background: #3B82F6; }
  .swagger-ui .opblock.opblock-post { background: rgba(16, 185, 129, 0.04); border-color: rgba(16, 185, 129, 0.2); }
  .swagger-ui .opblock.opblock-post .opblock-summary-method { background: #10B981; }
  .swagger-ui .opblock.opblock-put { background: rgba(245, 158, 11, 0.04); border-color: rgba(245, 158, 11, 0.2); }
  .swagger-ui .opblock.opblock-put .opblock-summary-method { background: #F59E0B; }
  .swagger-ui .opblock.opblock-delete { background: rgba(230, 0, 35, 0.04); border-color: rgba(230, 0, 35, 0.2); }
  .swagger-ui .opblock.opblock-delete .opblock-summary-method { background: #E60023; }
  .swagger-ui .opblock-summary-method {
    font-family: 'JetBrains Mono', monospace; font-weight: 700;
    font-size: .72rem; border-radius: 8px; padding: 6px 12px;
    min-width: 68px; text-shadow: none;
  }
  .swagger-ui .opblock-summary-path {
    font-family: 'JetBrains Mono', monospace; font-weight: 600; font-size: .88rem;
    color: #0A0A0B;
  }
  .swagger-ui .opblock-summary-description { color: #6E6E78; font-size: .86rem; }
  .swagger-ui .btn {
    font-family: 'Inter', sans-serif; font-weight: 600;
    border-radius: 10px; border: 1px solid rgba(0,0,0,.08);
    box-shadow: none; padding: 8px 16px;
    transition: all .15s ease;
  }
  .swagger-ui .btn.execute {
    background: #E60023; color: #fff; border-color: transparent;
    box-shadow: 0 4px 12px rgba(230,0,35,.3);
  }
  .swagger-ui .btn.execute:hover { background: #C4001E; }
  .swagger-ui .btn.authorize { color: #E60023; border-color: #E60023; }
  .swagger-ui .btn.authorize svg { fill: #E60023; }
  .swagger-ui .btn.authorize:hover { background: rgba(230, 0, 35, 0.08); }
  .swagger-ui select, .swagger-ui input[type=text], .swagger-ui input[type=email],
  .swagger-ui input[type=password], .swagger-ui input[type=search],
  .swagger-ui textarea {
    border-radius: 10px; border: 1.5px solid rgba(0,0,0,.1);
    font-family: 'Inter', sans-serif;
    padding: 8px 12px; outline: none;
  }
  .swagger-ui select:focus, .swagger-ui input:focus, .swagger-ui textarea:focus {
    border-color: #E60023; box-shadow: 0 0 0 3px rgba(230,0,35,.1);
  }
  .swagger-ui .highlight-code, .swagger-ui .microlight {
    font-family: 'JetBrains Mono', monospace; font-size: .8rem;
    border-radius: 10px;
  }
  .swagger-ui .model-box, .swagger-ui .model-container {
    background: #F7F7F9; border-radius: 12px; padding: 8px;
  }
  .swagger-ui section.models {
    border: 1px solid rgba(0,0,0,.06); border-radius: 16px; background: #fff;
    margin-top: 32px;
  }
  .swagger-ui section.models h4 {
    font-family: 'Inter', sans-serif; font-weight: 700;
    border-bottom: 1px solid rgba(0,0,0,.06); padding: 16px 20px;
    color: #0A0A0B;
  }
  .swagger-ui .responses-inner { padding: 16px 0; }
  .swagger-ui .response-col_status { font-family: 'JetBrains Mono', monospace; font-weight: 700; }
  .docs-footer {
    text-align: center; padding: 32px 24px; color: #6E6E78; font-size: .84rem;
    position: relative; z-index: 1;
    border-top: 1px solid rgba(0,0,0,.06);
    margin-top: 40px;
  }
  @media (max-width: 760px) {
    .docs-topbar { padding: 12px 16px; gap: 10px; flex-wrap: wrap; }
    .docs-logo-name, .docs-logo-tag { display: none; }
    .docs-nav { gap: 6px; width: 100%; justify-content: flex-end; }
    .docs-nav a { padding: 7px 12px; font-size: .78rem; }
    #swagger-ui { padding: 16px 14px; }
    .swagger-ui .info .title { font-size: 1.4rem; }
  }
  body[data-theme="dark"] { background: #08080A; color: #F7F7F9; }
  body[data-theme="dark"] .docs-topbar { background: #08080A; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .docs-logo-name { color: #F7F7F9; }
  body[data-theme="dark"] .docs-nav a { background: #0F0F12; border-color: rgba(255,255,255,.08); color: #E5E5EA; }
  body[data-theme="dark"] .swagger-ui .info .title { color: #F7F7F9; }
  body[data-theme="dark"] .swagger-ui .info p, body[data-theme="dark"] .swagger-ui .info li { color: #8E8E99; }
  body[data-theme="dark"] .swagger-ui .opblock-tag { color: #F7F7F9; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .swagger-ui .opblock { background: #0F0F12; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .swagger-ui .opblock-summary-path { color: #F7F7F9; }
  body[data-theme="dark"] .swagger-ui .opblock-summary-description { color: #8E8E99; }
  body[data-theme="dark"] .swagger-ui .scheme-container { background: #0F0F12; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .swagger-ui .model-box, body[data-theme="dark"] .swagger-ui .model-container { background: #17171B; }
  body[data-theme="dark"] .swagger-ui section.models { background: #0F0F12; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .swagger-ui section.models h4 { color: #F7F7F9; border-color: rgba(255,255,255,.06); }
  body[data-theme="dark"] .docs-footer { border-color: rgba(255,255,255,.06); color: #8E8E99; }
</style>
</head>
<body>
<header class="docs-topbar">
  <a class="docs-logo" href="/">
    <span class="docs-logo-badge">P</span>
    <span class="docs-logo-name">Pinterest Scraper</span>
    <span class="docs-logo-tag">API</span>
  </a>
  <nav class="docs-nav">
    <a href="/"><i class="bi bi-house"></i> Home</a>
    <a href="/api/health" target="_blank"><i class="bi bi-activity"></i> Health</a>
    <a href="/openapi.json" target="_blank" class="primary"><i class="bi bi-filetype-json"></i> OpenAPI</a>
  </nav>
</header>
<div id="swagger-ui"></div>
<div class="docs-footer">Made with <span style="color:#E60023">♥</span> using FastAPI</div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
  (function() {
    const savedTheme = localStorage.getItem('theme');
    const prefers = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.body.dataset.theme = savedTheme || prefers;
  })();
  SwaggerUIBundle({
    url: '/openapi.json',
    dom_id: '#swagger-ui',
    deepLinking: true,
    docExpansion: 'list',
    defaultModelsExpandDepth: 0,
    defaultModelExpandDepth: 1,
    displayRequestDuration: true,
    filter: true,
    tryItOutEnabled: true,
    persistAuthorization: true,
    syntaxHighlight: { activate: true, theme: 'agate' },
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: 'BaseLayout',
  });
</script>
</body>
</html>
"""


@app.get("/docs", include_in_schema=False)
async def custom_docs():
    return HTMLResponse(DOCS_HTML)


@app.get("/redoc", include_in_schema=False)
async def custom_redoc():
    from fastapi.openapi.docs import get_redoc_html
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title="Pinterest Scraper · ReDoc",
    )


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/scrape")
def start_scrape(req: ScrapeRequest):
    job = Job(req, _out_dir())
    JOBS[job.id] = job
    threading.Thread(target=job.run, daemon=True).start()
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")

    async def gen():
        loop = asyncio.get_running_loop()
        while True:
            try:
                ev = await asyncio.wait_for(
                    loop.run_in_executor(None, job.events.get, True, 0.2), 5
                )
                yield f"data: {ev}\n\n"
                if json.loads(ev).get("event") == "done":
                    return
            except (queue.Empty, asyncio.TimeoutError):
                if job.done.is_set() and job.events.empty():
                    return
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@app.get("/api/jobs/{job_id}/result")
def job_result(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    if not job.done.is_set():
        raise HTTPException(409, "job still running")
    return {"status": job.status, "stats": job.stats, "error": job.error, "pins": job.pins}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    job.cancelled = True
    job.status = "cancelled"
    job.done.set()
    job.emit(event="done", status="cancelled", total=len(job.pins), stats=job.stats)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/images/{name}")
def job_image(job_id: str, name: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    path = (job.out_dir / "images" / name).resolve()
    if not str(path).startswith(str(job.out_dir.resolve())) or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.get("/api/jobs/{job_id}/export/{fmt}")
def export_job(job_id: str, fmt: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    if not job.done.is_set():
        raise HTTPException(409, "job still running")
    if fmt == "zip":
        return _zip_response(job.pins)
    if fmt == "xlsx":
        return _xlsx_response(job.pins)
    raise HTTPException(400, "format must be zip or xlsx")


_SUGGEST_TTL = 300
_suggest_cache: dict[str, tuple[float, list[dict]]] = {}
_suggest_locks: dict[str, threading.Lock] = {}
_suggest_locks_guard = threading.Lock()


@app.get("/api/suggest")
def suggest(q: str = ""):
    q = q.strip().lower()
    if len(q) < 2:
        return {"suggestions": []}
    now = time.monotonic()
    hit = _suggest_cache.get(q)
    if hit and now - hit[0] < _SUGGEST_TTL:
        return {"suggestions": hit[1]}
    with _suggest_locks_guard:
        lock = _suggest_locks.setdefault(q, threading.Lock())
    with lock:
        now = time.monotonic()
        hit = _suggest_cache.get(q)
        if hit and now - hit[0] < _SUGGEST_TTL:
            return {"suggestions": hit[1]}
        try:
            session = build_session()
            out = typeahead_suggestions(session, q)
        except Exception:
            out = []
        _suggest_cache[q] = (now, out)
        if len(_suggest_cache) > 200:
            oldest = sorted(_suggest_cache, key=lambda k: _suggest_cache[k][0])
            for k in oldest[:100]:
                _suggest_cache.pop(k, None)
        return {"suggestions": out}


@app.get("/api/images/{name}")
def global_image(name: str):
    img_dir = (_out_dir() / "images").resolve()
    path = (img_dir / name).resolve()
    if not path.is_relative_to(img_dir) or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.get("/api/gallery")
def get_gallery():
    img_dir = (_out_dir() / "images").resolve()
    if not img_dir.exists():
        return {"pins": [], "total": 0}
    metadata_map: dict[str, dict] = {}
    for jf in _out_dir().glob("*.json"):
        if jf.name == "schedules.json" or jf.name.startswith("."):
            continue
        try:
            items = json.loads(jf.read_text(encoding="utf-8"))
            if isinstance(items, list):
                for p in items:
                    if isinstance(p, dict) and p.get("pin_id"):
                        metadata_map[str(p["pin_id"])] = p
        except Exception:
            pass
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    image_files = sorted(
        [f for f in img_dir.iterdir() if f.is_file() and f.suffix.lower() in valid_exts],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    gallery_pins = []
    for f in image_files:
        pin_id = f.stem
        meta = metadata_map.get(pin_id)
        if meta:
            p = dict(meta)
            p["local_file"] = f.name
        else:
            p = {
                "pin_id": pin_id,
                "title": f"Pin {pin_id}",
                "description": "",
                "local_file": f.name,
                "image_url": f"/api/images/{f.name}",
                "pin_url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id.isdigit() else "",
                "saves": None,
                "comments": None,
            }
        gallery_pins.append(p)
    return {"pins": gallery_pins, "total": len(gallery_pins)}


@app.get("/api/gallery/export/zip")
def export_gallery():
    img_dir = (_out_dir() / "images").resolve()
    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
    pins = (
        [{"local_file": f.name} for f in img_dir.iterdir()
         if f.is_file() and f.suffix.lower() in valid_exts]
        if img_dir.exists() else []
    )
    return _zip_response(pins)


def _zip_response(pins: list[dict]) -> StreamingResponse:
    buf = io.BytesIO()
    img_dir = _out_dir() / "images"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for p in pins:
            f = p.get("local_file")
            if f and (img_dir / f).is_file():
                zf.write(img_dir / f, f"images/{f}")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": 'attachment; filename="pins-images.zip"'})


def _xlsx_response(pins: list[dict]) -> StreamingResponse:
    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise HTTPException(500, "openpyxl is required for XLSX export")
    wb = Workbook()
    ws = wb.active
    ws.title = "pins"
    cols = list(pins[0].keys()) if pins else ["pin_id"]
    ws.append(cols)
    for p in pins:
        ws.append([str(p.get(c)) if p.get(c) is not None else "" for c in cols])
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = 22
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="pins.xlsx"'},
    )


_visual_cache: dict[str, tuple[float, list[dict]]] = {}


@app.get("/api/visual-search")
def visual_search(pin_id: str = "", limit: int = 25):
    pin_id = pin_id.strip()
    if not pin_id.isdigit():
        raise HTTPException(400, "numeric pin_id required")
    cached = _visual_cache.get(pin_id)
    if cached and time.monotonic() - cached[0] < 600:
        return {"pins": cached[1]}
    try:
        session = build_session()
        pins = related_pins(session, pin_id, limit=min(limit, 50))
    except Exception as e:
        raise HTTPException(502, f"visual search failed: {e}")
    _visual_cache[pin_id] = (time.monotonic(), pins)
    return {"pins": pins}


SCHEDULES_FILE = _out_dir() / "schedules.json"


def _load_schedules() -> list[dict]:
    if SCHEDULES_FILE.exists():
        try:
            return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
    return []


def _save_schedules(items: list[dict]) -> None:
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


class ScheduleIn(BaseModel):
    mode: str = Field(default="search", pattern="^(search|board)$")
    query: str = Field(min_length=1)
    interval_hours: float = Field(default=24, ge=1, le=720)
    limit: int = Field(default=25, ge=1, le=200)


@app.get("/api/schedules")
def list_schedules():
    return {"schedules": _load_schedules()}


@app.post("/api/schedules")
def add_schedule(sch: ScheduleIn):
    items = _load_schedules()
    entry = {
        "id": uuid.uuid4().hex[:10],
        "mode": sch.mode,
        "query": sch.query.strip(),
        "interval_hours": sch.interval_hours,
        "limit": sch.limit,
        "next_run": time.time() + sch.interval_hours * 3600,
        "created": time.time(),
        "last_run": None,
        "runs": 0,
    }
    items.append(entry)
    _save_schedules(items)
    return entry


@app.delete("/api/schedules/{sid}")
def delete_schedule(sid: str):
    items = [s for s in _load_schedules() if s.get("id") != sid]
    _save_schedules(items)
    return {"ok": True, "remaining": len(items)}


def _scheduler_loop():
    while True:
        try:
            now = time.time()
            changed = False
            schedules = _load_schedules()
            for sch in schedules:
                if now >= sch.get("next_run", now + 3600):
                    req = ScrapeRequest(
                        mode=sch["mode"], query=sch["query"],
                        limit=sch["limit"], download=True, details=True, dedup=True,
                    )
                    job = Job(req, _out_dir())
                    JOBS[job.id] = job
                    threading.Thread(target=job.run, daemon=True).start()
                    sch["last_run"] = now
                    sch["next_run"] = now + sch["interval_hours"] * 3600
                    sch["runs"] = sch.get("runs", 0) + 1
                    sch["last_job_id"] = job.id
                    changed = True
            if changed:
                _save_schedules(schedules)
        except Exception:
            pass
        time.sleep(60)


@app.on_event("startup")
def _start_scheduler():
    threading.Thread(target=_scheduler_loop, daemon=True).start()


class DeleteImagesIn(BaseModel):
    names: list[str] = Field(default_factory=list)
    all: bool = False


@app.post("/api/images/delete")
def delete_images(payload: DeleteImagesIn):
    img_dir = (_out_dir() / "images").resolve()
    if payload.all:
        targets = [p for p in img_dir.glob("*") if p.is_file()]
    else:
        targets = []
        for name in payload.names:
            p = (img_dir / name).resolve()
            if str(p).startswith(str(img_dir)) and p.is_file():
                targets.append(p)
    deleted = 0
    for p in targets:
        try:
            p.unlink()
            deleted += 1
        except OSError:
            pass
    return {"deleted": deleted}


def main():
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()