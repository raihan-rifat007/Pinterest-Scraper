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
    title="Pinterest Scraper API",
    version="07",
    description="High-quality Pinterest scraper API with job events, exports, and gallery management.",
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
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = _custom_openapi


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DOCS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<meta name="theme-color" content="#E60023">
<meta name="description" content="Pinterest Scraper API reference with multi-language code samples and live try-it-out.">
<meta property="og:type" content="website">
<meta property="og:title" content="Pinterest Scraper — API Reference">
<meta property="og:description" content="High-quality Pinterest scraper API with live code samples.">
<meta property="og:image" content="/static/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Pinterest Scraper — API Reference">
<meta name="twitter:image" content="/static/og-image.png">
<title>Pinterest Scraper · API Reference</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='48' fill='%23E60023'/><text x='50' y='72' font-size='60' text-anchor='middle' fill='white' font-family='serif' font-weight='bold'>P</text></svg>">
<style>
:root {
  --red: #E60023;
  --red-hover: #C4001E;
  --red-soft: rgba(230, 0, 35, 0.08);
  --blue: #3B82F6;
  --blue-soft: rgba(59, 130, 246, 0.10);
  --green: #10B981;
  --green-soft: rgba(16, 185, 129, 0.10);
  --amber: #F59E0B;
  --amber-soft: rgba(245, 158, 11, 0.10);
  --purple: #8B5CF6;
  --purple-soft: rgba(139, 92, 246, 0.10);
  --bg: #FAFAFB;
  --bg-elevated: #FFFFFF;
  --bg-sunken: #F4F4F6;
  --bg-code: #0B0B0F;
  --surface: #F1F1F4;
  --surface-2: #E8E8EC;
  --border: rgba(0,0,0,0.07);
  --border-strong: rgba(0,0,0,0.12);
  --text: #0A0A0B;
  --text-soft: #2A2A30;
  --text-muted: #6B6B76;
  --text-dim: #A0A0AA;
  --radius-sm: 10px;
  --radius: 14px;
  --radius-lg: 18px;
  --radius-xl: 22px;
  --radius-full: 999px;
  --shadow-xs: 0 1px 2px rgba(0,0,0,.04);
  --shadow-sm: 0 2px 8px rgba(0,0,0,.05), 0 1px 2px rgba(0,0,0,.04);
  --shadow: 0 8px 24px rgba(0,0,0,.07);
  --shadow-lg: 0 20px 60px rgba(0,0,0,.12);
  --shadow-red: 0 12px 32px rgba(230, 0, 35, 0.22);
  --ease: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --font: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif;
  --mono: 'JetBrains Mono', 'SF Mono', monospace;
  --topnav-bg: rgba(250, 250, 251, 0.88);
  --safe-top: env(safe-area-inset-top, 0px);
  --safe-bottom: env(safe-area-inset-bottom, 0px);
  --safe-left: env(safe-area-inset-left, 0px);
  --safe-right: env(safe-area-inset-right, 0px);
}
body[data-theme="dark"] {
  --bg: #08080A;
  --bg-elevated: #0F0F12;
  --bg-sunken: #050506;
  --bg-code: #050507;
  --surface: #17171B;
  --surface-2: #202026;
  --border: rgba(255, 255, 255, 0.07);
  --border-strong: rgba(255, 255, 255, 0.13);
  --text: #F7F7F9;
  --text-soft: #E5E5EA;
  --text-muted: #8E8E99;
  --text-dim: #57575F;
  --topnav-bg: rgba(8, 8, 10, 0.88);
}
* { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
html { scroll-behavior: smooth; scroll-padding-top: 90px; -webkit-text-size-adjust: 100%; }
body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  letter-spacing: -0.011em;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  transition: background .25s var(--ease), color .25s var(--ease);
}
a { color: inherit; text-decoration: none; }
button { font-family: inherit; cursor: pointer; border: none; background: none; color: inherit; }
::selection { background: var(--red); color: #fff; }
svg { display: block; }
kbd {
  font-family: var(--mono); font-size: .68rem; font-weight: 600;
  padding: 2px 6px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: 5px;
  color: var(--text-muted);
  line-height: 1.2;
}

.topnav {
  position: sticky; top: 0; z-index: 100;
  background: var(--topnav-bg);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border);
  padding-top: var(--safe-top);
}
.topnav-inner {
  max-width: 1600px; margin: 0 auto;
  height: 64px;
  padding: 0 max(24px, var(--safe-left)) 0 max(24px, var(--safe-right));
  display: flex; align-items: center; gap: 16px;
}
.brand {
  display: flex; align-items: center; gap: 10px;
  padding: 4px; border-radius: var(--radius-full);
  transition: background .15s;
  flex-shrink: 0;
}
.brand:hover { background: var(--surface); }
.brand-badge {
  width: 34px; height: 34px; border-radius: 50%;
  background: linear-gradient(135deg, #FF1E3D 0%, var(--red) 50%, #8B0020 100%);
  color: #fff; display: grid; place-items: center;
  font-size: 1.1rem; font-weight: 800;
  box-shadow: var(--shadow-red), inset 0 1px 0 rgba(255,255,255,.25);
  flex-shrink: 0;
}
.brand-name { font-weight: 800; font-size: .98rem; letter-spacing: -0.03em; }
.brand-tag {
  font-size: .6rem; font-weight: 700;
  padding: 3px 8px; border-radius: 999px;
  background: var(--red); color: #fff;
  letter-spacing: .05em; text-transform: uppercase;
}
.topnav-spacer { flex: 1; }
.search-trigger {
  display: flex; align-items: center; gap: 10px;
  width: 100%; max-width: 420px;
  height: 38px;
  padding: 0 6px 0 14px;
  background: var(--surface);
  border: 1px solid transparent;
  border-radius: var(--radius-full);
  color: var(--text-muted);
  font-size: .86rem; font-weight: 500;
  transition: all .15s;
  cursor: text;
}
.search-trigger:hover { background: var(--surface-2); border-color: var(--border-strong); }
.search-trigger .st-text { flex: 1; text-align: left; }
.search-trigger .st-kbd { display: inline-flex; gap: 3px; }
.navlinks { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
.navlink {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 12px; border-radius: var(--radius-sm);
  font-size: .84rem; font-weight: 600;
  color: var(--text-soft);
  transition: all .15s;
}
.navlink:hover { background: var(--surface); color: var(--text); }
.navlink.primary {
  background: var(--red); color: #fff;
  box-shadow: 0 2px 8px rgba(230,0,35,.25);
}
.navlink.primary:hover { background: var(--red-hover); }
.theme-toggle {
  width: 38px; height: 38px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--bg-elevated);
  color: var(--text-muted);
  display: grid; place-items: center;
  transition: all .15s;
}
.theme-toggle:hover { color: var(--text); border-color: var(--border-strong); }
.theme-toggle:active { transform: scale(.92); }

.hero {
  position: relative;
  padding: 56px max(24px, var(--safe-left)) 40px max(24px, var(--safe-right));
  overflow: hidden;
  isolation: isolate;
}
.hero-bg {
  position: absolute; inset: 0; z-index: -1;
  background:
    radial-gradient(ellipse 900px 500px at 15% -20%, rgba(230,0,35,.09), transparent 60%),
    radial-gradient(ellipse 700px 400px at 85% 0%, rgba(139,92,246,.08), transparent 60%);
}
body[data-theme="dark"] .hero-bg {
  background:
    radial-gradient(ellipse 900px 500px at 15% -20%, rgba(230,0,35,.16), transparent 60%),
    radial-gradient(ellipse 700px 400px at 85% 0%, rgba(139,92,246,.14), transparent 60%);
}
.hero-grid {
  position: absolute; inset: 0; z-index: -1;
  background-image:
    linear-gradient(rgba(0,0,0,.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,0,0,.03) 1px, transparent 1px);
  background-size: 40px 40px;
  -webkit-mask-image: radial-gradient(ellipse 800px 500px at 50% 30%, black, transparent 70%);
  mask-image: radial-gradient(ellipse 800px 500px at 50% 30%, black, transparent 70%);
}
body[data-theme="dark"] .hero-grid {
  background-image:
    linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
}
.hero-inner { max-width: 1600px; margin: 0 auto; }
.hero-eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  font-size: .78rem; font-weight: 600;
  color: var(--text-muted);
  margin-bottom: 20px;
  box-shadow: var(--shadow-xs);
}
.hero-eyebrow .pulse {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 0 3px rgba(16,185,129,.22);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
.hero h1 {
  font-size: clamp(2.1rem, 5vw, 3.4rem);
  font-weight: 900;
  letter-spacing: -0.05em;
  line-height: 1.02;
  margin-bottom: 16px;
  max-width: 800px;
  background: linear-gradient(140deg, var(--text) 20%, var(--text-muted) 90%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero h1 .accent {
  background: linear-gradient(135deg, var(--red), #FF4D6A);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.hero p {
  font-size: 1.02rem;
  color: var(--text-muted);
  line-height: 1.65;
  max-width: 640px;
}
.hero-stats {
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-top: 24px;
}
.stat-pill {
  display: flex; flex-direction: column; gap: 2px;
  padding: 12px 18px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  min-width: 120px;
  box-shadow: var(--shadow-xs);
  transition: all .2s var(--ease);
}
.stat-pill:hover { transform: translateY(-2px); box-shadow: var(--shadow-sm); border-color: var(--border-strong); }
.stat-pill-num {
  font-family: var(--mono);
  font-size: 1.4rem; font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.stat-pill-lbl {
  font-size: .68rem; font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .08em;
  margin-top: 3px;
}

.layout {
  max-width: 1600px;
  margin: 0 auto;
  padding: 0 max(24px, var(--safe-left)) calc(80px + var(--safe-bottom)) max(24px, var(--safe-right));
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 420px;
  gap: 32px;
  align-items: start;
}

.sidebar {
  position: sticky;
  top: 88px;
  max-height: calc(100vh - 110px);
  display: flex; flex-direction: column;
  overflow: hidden;
}
.sidebar-filter {
  display: flex; align-items: center; gap: 8px;
  height: 38px;
  padding: 0 12px;
  background: var(--surface);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  margin-bottom: 12px;
  flex-shrink: 0;
  transition: all .15s;
}
.sidebar-filter:focus-within {
  background: var(--bg-elevated);
  border-color: var(--red);
  box-shadow: 0 0 0 3px var(--red-soft);
}
.sidebar-filter svg { color: var(--text-muted); flex-shrink: 0; }
.sidebar-filter input {
  flex: 1; min-width: 0;
  border: none; outline: none; background: transparent;
  font: 500 .84rem var(--font);
  color: var(--text);
  height: 100%;
}
.sidebar-filter input::placeholder { color: var(--text-dim); }
.chip-row {
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-bottom: 14px;
  flex-shrink: 0;
}
.filter-chip {
  padding: 4px 10px;
  border-radius: var(--radius-full);
  background: var(--surface);
  color: var(--text-muted);
  font-size: .68rem; font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  transition: all .15s;
  border: 1px solid transparent;
}
.filter-chip:hover { background: var(--surface-2); color: var(--text); }
.filter-chip.active {
  background: var(--red-soft);
  color: var(--red);
  border-color: rgba(230, 0, 35, 0.2);
}
.sidebar-nav { flex: 1; overflow-y: auto; padding-right: 4px; }
.nav-group { margin-bottom: 16px; }
.nav-group-title {
  display: flex; align-items: center; gap: 8px;
  padding: 0 8px 6px;
  font-size: .64rem; font-weight: 800;
  text-transform: uppercase; letter-spacing: .1em;
  color: var(--text-dim);
}
.nav-group-title .count {
  margin-left: auto;
  padding: 2px 7px;
  background: var(--surface);
  border-radius: 999px;
  font-size: .6rem;
  color: var(--text-muted);
  font-family: var(--mono);
}
.nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  color: var(--text-soft);
  font-size: .82rem; font-weight: 500;
  transition: all .12s;
  cursor: pointer;
  border: 1px solid transparent;
  text-decoration: none;
  width: 100%;
  text-align: left;
}
.nav-item:hover { background: var(--surface); color: var(--text); }
.nav-item.active {
  background: var(--red-soft);
  color: var(--red);
  border-color: rgba(230, 0, 35, 0.2);
  font-weight: 600;
}
.nav-item .method {
  font-family: var(--mono);
  font-size: .55rem; font-weight: 700;
  padding: 2px 6px; border-radius: 5px;
  letter-spacing: .04em;
  flex-shrink: 0;
  min-width: 40px; text-align: center;
}
.method.get { background: var(--blue-soft); color: var(--blue); }
.method.post { background: var(--green-soft); color: var(--green); }
.method.put, .method.patch { background: var(--amber-soft); color: var(--amber); }
.method.delete { background: var(--red-soft); color: var(--red); }
.nav-item .path-text {
  font-family: var(--mono);
  font-size: .74rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
}

.content { min-width: 0; }
.content-header {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; margin-bottom: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.content-header h2 {
  font-size: 1.35rem; font-weight: 800;
  letter-spacing: -0.035em;
}
.content-header .lead {
  color: var(--text-muted); font-size: .84rem;
  margin-top: 3px;
}
.filter-hint {
  font-size: .74rem; font-weight: 600;
  color: var(--text-muted);
  padding: 5px 11px;
  background: var(--surface);
  border-radius: var(--radius-full);
}

.endpoint {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  margin-bottom: 10px;
  overflow: hidden;
  transition: border-color .2s, box-shadow .2s;
  scroll-margin-top: 100px;
}
.endpoint:hover { border-color: var(--border-strong); }
.endpoint.selected {
  border-color: rgba(230, 0, 35, 0.35);
  box-shadow: 0 0 0 3px var(--red-soft);
}
.endpoint.highlight {
  animation: highlightPulse 1.5s ease-out;
}
@keyframes highlightPulse {
  0% { box-shadow: 0 0 0 0 rgba(230, 0, 35, 0.5); }
  100% { box-shadow: 0 0 0 0 rgba(230, 0, 35, 0); }
}
.endpoint-head {
  display: flex; align-items: center; gap: 12px;
  padding: 14px 18px;
  cursor: pointer;
  user-select: none;
  transition: background .15s;
}
.endpoint-head:hover { background: var(--surface); }
.endpoint.open .endpoint-head { background: var(--surface); border-bottom: 1px solid var(--border); }
.endpoint-method {
  font-family: var(--mono);
  font-size: .66rem; font-weight: 700;
  padding: 5px 10px; border-radius: 7px;
  letter-spacing: .05em;
  flex-shrink: 0;
  min-width: 58px; text-align: center;
}
.endpoint-method.get { background: var(--blue); color: #fff; }
.endpoint-method.post { background: var(--green); color: #fff; }
.endpoint-method.put, .endpoint-method.patch { background: var(--amber); color: #fff; }
.endpoint-method.delete { background: var(--red); color: #fff; }
.endpoint-path {
  font-family: var(--mono);
  font-size: .88rem; font-weight: 600;
  color: var(--text);
  flex-shrink: 0;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  min-width: 0;
}
.endpoint-summary {
  color: var(--text-muted);
  font-size: .82rem;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  flex: 1; min-width: 0;
  padding-left: 12px;
  border-left: 1px solid var(--border);
  margin-left: 4px;
}
.endpoint-chevron {
  color: var(--text-dim);
  flex-shrink: 0;
  transition: transform .25s var(--ease);
}
.endpoint.open .endpoint-chevron { transform: rotate(90deg); }
.endpoint-body {
  display: none;
  padding: 20px 22px;
}
.endpoint.open .endpoint-body { display: block; animation: slideDown .25s var(--ease); }
@keyframes slideDown {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}
.endpoint-desc {
  color: var(--text-soft);
  font-size: .88rem; line-height: 1.7;
  margin-bottom: 18px;
}
.endpoint-section { margin-bottom: 20px; }
.endpoint-section:last-child { margin-bottom: 0; }
.section-title {
  display: flex; align-items: center; gap: 8px;
  font-size: .66rem; font-weight: 800;
  text-transform: uppercase; letter-spacing: .1em;
  color: var(--text-dim);
  margin-bottom: 10px;
}
.section-title::after {
  content: ''; flex: 1; height: 1px;
  background: var(--border);
}
.param-table {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.param-row {
  display: grid;
  grid-template-columns: minmax(120px, 1fr) minmax(70px, auto) minmax(56px, auto) 2fr;
  gap: 14px;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
  align-items: baseline;
  font-size: .82rem;
}
.param-row:last-child { border-bottom: none; }
.param-row.header {
  background: var(--bg-sunken);
  font-size: .64rem; font-weight: 800;
  text-transform: uppercase; letter-spacing: .08em;
  color: var(--text-dim);
}
.param-name {
  font-family: var(--mono); font-weight: 600;
  color: var(--text);
  overflow-wrap: break-word;
}
.param-type {
  font-family: var(--mono); font-size: .74rem;
  color: var(--purple); font-weight: 500;
}
.param-required {
  font-size: .62rem; font-weight: 700;
  padding: 2px 7px; border-radius: 999px;
  background: var(--red-soft); color: var(--red);
  text-align: center;
  text-transform: uppercase; letter-spacing: .04em;
}
.param-required.optional { background: var(--surface); color: var(--text-dim); }
.param-desc { color: var(--text-muted); font-size: .78rem; }
.response-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border);
  font-size: .82rem;
}
.response-row:last-child { border-bottom: none; }
.status-code {
  font-family: var(--mono);
  font-size: .74rem; font-weight: 700;
  padding: 3px 9px; border-radius: 6px;
  min-width: 48px; text-align: center;
}
.status-code.ok { background: var(--green-soft); color: var(--green); }
.status-code.redirect { background: var(--blue-soft); color: var(--blue); }
.status-code.client { background: var(--amber-soft); color: var(--amber); }
.status-code.server { background: var(--red-soft); color: var(--red); }
.response-desc { color: var(--text-muted); }

.code-panel {
  position: sticky;
  top: 88px;
  max-height: calc(100vh - 110px);
  display: flex; flex-direction: column;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.code-panel-head {
  padding: 16px 18px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.code-panel-head-top {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 4px;
}
.code-panel-head .method {
  font-family: var(--mono);
  font-size: .62rem; font-weight: 700;
  padding: 3px 8px; border-radius: 6px;
  letter-spacing: .05em;
  flex-shrink: 0;
}
.code-panel-head .method.get { background: var(--blue); color: #fff; }
.code-panel-head .method.post { background: var(--green); color: #fff; }
.code-panel-head .method.put, .code-panel-head .method.patch { background: var(--amber); color: #fff; }
.code-panel-head .method.delete { background: var(--red); color: #fff; }
.code-panel-head .path {
  font-family: var(--mono);
  font-size: .82rem; font-weight: 600;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.code-panel-head .summary {
  font-size: .78rem; color: var(--text-muted);
  margin-top: 2px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.lang-tabs {
  display: flex; gap: 2px;
  padding: 8px 12px;
  background: var(--bg-sunken);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-shrink: 0;
}
.lang-tabs::-webkit-scrollbar { display: none; }
.lang-tab {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: .74rem; font-weight: 700;
  color: var(--text-muted);
  background: transparent;
  transition: all .12s;
  white-space: nowrap;
  flex-shrink: 0;
  letter-spacing: -0.005em;
}
.lang-tab:hover { background: var(--bg-elevated); color: var(--text); }
.lang-tab.active {
  background: var(--bg-elevated);
  color: var(--text);
  box-shadow: var(--shadow-xs);
}
.code-panel-body {
  flex: 1; overflow-y: auto;
  padding: 16px;
  display: flex; flex-direction: column; gap: 14px;
}
.code-block {
  position: relative;
  background: var(--bg-code);
  border-radius: var(--radius);
  padding: 16px 18px;
  font-family: var(--mono);
  font-size: .76rem;
  color: #E5E5EA;
  overflow-x: auto;
  line-height: 1.65;
  border: 1px solid rgba(255,255,255,.05);
}
.code-block pre { margin: 0; white-space: pre; }
.copy-btn {
  position: absolute; top: 8px; right: 8px;
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 9px;
  background: rgba(255,255,255,.08);
  color: rgba(255,255,255,.7);
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 7px;
  font-size: .66rem; font-weight: 600;
  transition: all .15s;
  font-family: var(--font);
  cursor: pointer;
}
.copy-btn:hover { background: rgba(255,255,255,.15); color: #fff; }
.copy-btn.copied { background: var(--green); color: #fff; border-color: transparent; }
.copy-btn svg { width: 11px; height: 11px; }

.tok-key { color: #7EE8FA; }
.tok-string { color: #A5F3A0; }
.tok-num { color: #FFB86C; }
.tok-bool { color: #FF79C6; }
.tok-null { color: #8E8E99; }
.tok-punc { color: #6B6B76; }
.tok-comment { color: #6B6B76; font-style: italic; }
.tok-fn { color: #B794F6; }

.path-params-inline {
  display: flex; flex-direction: column; gap: 8px;
  padding: 12px 14px;
  background: var(--bg-sunken);
  border-radius: var(--radius);
  border: 1px solid var(--border);
}
.path-params-inline label {
  display: flex; flex-direction: column; gap: 4px;
  font-size: .74rem; font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .06em;
}
.path-params-inline input {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1.5px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text);
  font-family: var(--mono); font-size: .82rem;
  outline: none;
  transition: all .15s;
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
}
.path-params-inline input:focus {
  border-color: var(--red);
  box-shadow: 0 0 0 3px var(--red-soft);
}

.auth-panel {
  padding: 12px 14px;
  background: var(--bg-sunken);
  border-radius: var(--radius);
  border: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 8px;
}
.auth-panel label {
  font-size: .68rem; font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .06em;
  display: flex; align-items: center; gap: 6px;
}
.auth-panel label .badge {
  padding: 2px 7px; border-radius: 999px;
  background: var(--green-soft); color: var(--green);
  font-size: .58rem;
}
.auth-input-row { display: flex; gap: 6px; }
.auth-input-row input {
  flex: 1; min-width: 0;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1.5px solid var(--border-strong);
  background: var(--bg-elevated);
  color: var(--text);
  font-family: var(--mono); font-size: .78rem;
  outline: none;
  transition: all .15s;
}
.auth-input-row input:focus {
  border-color: var(--red);
  box-shadow: 0 0 0 3px var(--red-soft);
}

.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 9px 16px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  font-size: .82rem; font-weight: 600;
  transition: all .15s;
  cursor: pointer;
  font-family: inherit;
  min-height: 38px;
  justify-content: center;
}
.btn:active { transform: scale(.97); }
.btn.primary { background: var(--red); color: #fff; box-shadow: 0 2px 8px rgba(230,0,35,.25); }
.btn.primary:hover { background: var(--red-hover); }
.btn.ghost { background: var(--bg-elevated); color: var(--text-soft); border-color: var(--border); }
.btn.ghost:hover { background: var(--surface); border-color: var(--border-strong); }
.btn.small { padding: 7px 12px; font-size: .76rem; min-height: 32px; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn.full { width: 100%; }

.run-row {
  display: flex; align-items: center; gap: 8px;
  flex-wrap: wrap;
}
.run-status {
  font-family: var(--mono); font-size: .74rem;
  color: var(--text-muted);
  margin-left: auto;
}
.run-status.ok { color: var(--green); font-weight: 700; }
.run-status.err { color: var(--red); font-weight: 700; }
.loader {
  width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.response-panel {
  display: none;
  background: var(--bg-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-top: 2px;
}
.response-panel.show { display: block; animation: slideDown .25s var(--ease); }
.response-head {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  background: var(--bg-elevated);
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.response-head .status-code { font-size: .74rem; padding: 3px 9px; }
.response-meta {
  font-family: var(--mono); font-size: .72rem;
  color: var(--text-muted);
}
.response-actions { display: flex; gap: 6px; margin-left: auto; }
.response-action {
  padding: 4px 10px;
  border-radius: 7px;
  font-size: .68rem; font-weight: 600;
  color: var(--text-muted);
  background: var(--surface);
  transition: all .12s;
}
.response-action:hover { background: var(--surface-2); color: var(--text); }
.json-tree {
  padding: 12px 14px;
  font-family: var(--mono);
  font-size: .74rem;
  max-height: 420px;
  overflow: auto;
  line-height: 1.7;
}
.jt-line {
  display: flex; align-items: center; gap: 6px;
  padding: 1px 4px;
  border-radius: 4px;
  cursor: default;
  min-height: 20px;
}
.jt-line:hover { background: rgba(139, 92, 246, 0.06); }
.jt-line.jt-toggle { cursor: pointer; }
.jt-toggle:hover { background: rgba(139, 92, 246, 0.10); }
.jt-arrow {
  color: var(--text-dim);
  transition: transform .15s;
  flex-shrink: 0;
}
.jt-node.collapsed > .jt-line .jt-arrow { transform: rotate(-90deg); }
.jt-node.collapsed > .jt-children { display: none; }
.jt-key { color: var(--blue); }
.jt-string { color: var(--green); }
.jt-num { color: var(--amber); }
.jt-bool { color: #C084FC; }
.jt-null { color: var(--text-dim); font-style: italic; }
.jt-count { color: var(--text-dim); font-size: .68rem; }
.jt-children { padding-left: 12px; border-left: 1px dashed var(--border); margin-left: 5px; }

.cmdk-backdrop {
  position: fixed; inset: 0; z-index: 400;
  background: rgba(0,0,0,.55);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  display: none;
  align-items: flex-start;
  justify-content: center;
  padding-top: 12vh;
  padding-left: 16px; padding-right: 16px;
}
.cmdk-backdrop.show { display: flex; animation: fadeIn .15s ease; }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.cmdk {
  width: 100%; max-width: 580px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  max-height: 70vh;
  display: flex; flex-direction: column;
  animation: popIn .25s var(--ease-spring);
}
@keyframes popIn { from { transform: scale(.96) translateY(-10px); opacity: 0; } to { transform: scale(1) translateY(0); opacity: 1; } }
.cmdk-input-wrap {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.cmdk-input-wrap svg { color: var(--text-muted); flex-shrink: 0; }
.cmdk-input {
  flex: 1;
  border: none; outline: none;
  background: transparent;
  font: 500 1rem var(--font);
  color: var(--text);
}
.cmdk-input::placeholder { color: var(--text-dim); }
.cmdk-results {
  padding: 8px;
  overflow-y: auto;
  flex: 1;
}
.cmdk-item {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background .1s;
}
.cmdk-item:hover, .cmdk-item.active { background: var(--surface); }
.cmdk-item .m {
  font-family: var(--mono); font-size: .62rem; font-weight: 700;
  padding: 3px 7px; border-radius: 6px;
  min-width: 42px; text-align: center;
  flex-shrink: 0;
}
.cmdk-item .m.get { background: var(--blue-soft); color: var(--blue); }
.cmdk-item .m.post { background: var(--green-soft); color: var(--green); }
.cmdk-item .m.delete { background: var(--red-soft); color: var(--red); }
.cmdk-item .p {
  font-family: var(--mono); font-size: .82rem; font-weight: 500;
  flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.cmdk-item .s {
  font-size: .74rem; color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  max-width: 200px;
}
.cmdk-footer {
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  background: var(--bg-sunken);
  display: flex; gap: 12px;
  font-size: .7rem; color: var(--text-muted);
  flex-shrink: 0;
}
.cmdk-footer span { display: flex; align-items: center; gap: 5px; }
.cmdk-empty {
  padding: 40px 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: .86rem;
}

.code-panel-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  flex: 1; padding: 40px 24px;
  text-align: center;
  color: var(--text-muted);
}
.code-panel-empty svg { color: var(--text-dim); margin-bottom: 14px; }
.code-panel-empty h3 {
  font-size: .95rem; font-weight: 700; color: var(--text);
  margin-bottom: 6px;
}
.code-panel-empty p { font-size: .82rem; line-height: 1.6; }

.mobile-panel-toggle {
  display: none;
  position: fixed; bottom: 20px; right: 20px; z-index: 50;
  padding: 12px 18px;
  background: var(--red); color: #fff;
  border-radius: var(--radius-full);
  font-size: .82rem; font-weight: 700;
  box-shadow: 0 8px 24px rgba(230,0,35,.4);
  align-items: center; gap: 8px;
}

.docs-footer {
  border-top: 1px solid var(--border);
  background: var(--bg-sunken);
  padding: 24px max(24px, var(--safe-left)) calc(24px + var(--safe-bottom)) max(24px, var(--safe-right));
  margin-top: 60px;
}
.docs-footer-inner {
  max-width: 1600px; margin: 0 auto;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 14px;
  font-size: .82rem; color: var(--text-muted);
}
.docs-footer-inner .heart { color: var(--red); }

.toast-container {
  position: fixed;
  bottom: calc(20px + var(--safe-bottom));
  left: 50%; transform: translateX(-50%);
  display: flex; flex-direction: column; gap: 8px;
  z-index: 500;
  pointer-events: none;
  align-items: center;
}
.toast {
  padding: 10px 16px;
  background: var(--text);
  color: var(--bg-elevated);
  border-radius: var(--radius-full);
  font-size: .82rem; font-weight: 600;
  pointer-events: auto;
  animation: toastIn .3s var(--ease-spring);
  display: flex; align-items: center; gap: 8px;
  box-shadow: var(--shadow-lg);
}
@keyframes toastIn { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
.toast .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--surface-2); border-radius: 10px; border: 2px solid transparent; background-clip: padding-box; }
::-webkit-scrollbar-thumb:hover { background-color: var(--text-dim); background-clip: padding-box; }
* { scrollbar-width: thin; scrollbar-color: var(--surface-2) transparent; }

@media (max-width: 1400px) {
  .layout { grid-template-columns: 240px minmax(0, 1fr) 380px; gap: 24px; }
}
@media (max-width: 1180px) {
  .layout { grid-template-columns: 220px minmax(0, 1fr); }
  .code-panel {
    position: fixed; top: auto; bottom: 0; left: 0; right: 0;
    max-height: 75vh;
    border-radius: var(--radius-xl) var(--radius-xl) 0 0;
    transform: translateY(100%);
    transition: transform .3s var(--ease);
    z-index: 300;
    box-shadow: 0 -20px 60px rgba(0,0,0,.3);
  }
  .code-panel.show { transform: translateY(0); }
  .code-panel-close { display: flex !important; }
  .mobile-panel-toggle { display: inline-flex; }
}
@media (max-width: 860px) {
  .hero { padding: 40px 18px 32px; }
  .hero h1 { font-size: 1.9rem; }
  .layout {
    grid-template-columns: 1fr;
    gap: 0;
    padding: 0 14px calc(60px + var(--safe-bottom));
  }
  .sidebar {
    position: static;
    max-height: none;
    margin-bottom: 16px;
  }
  .sidebar-nav {
    display: flex; gap: 6px; overflow-x: auto; padding-bottom: 6px;
  }
  .nav-group { margin-bottom: 0; flex-shrink: 0; }
  .nav-group-title { display: none; }
  .nav-group > div { display: flex; gap: 6px; }
  .nav-item { flex-shrink: 0; white-space: nowrap; padding: 6px 10px; }
  .nav-item .path-text { max-width: 140px; }
  .param-row { grid-template-columns: 1fr; gap: 5px; }
  .param-row.header { display: none; }
  .param-name::before { content: 'Name · '; color: var(--text-dim); font-family: var(--font); font-size: .68rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; margin-right: 4px; }
  .endpoint-summary { display: none; }
  .brand-name, .brand-tag { display: none; }
  .topnav-inner { padding: 0 14px; height: 58px; gap: 8px; }
  .search-trigger { max-width: 100%; }
  .search-trigger .st-kbd { display: none; }
  .navlink span { display: none; }
  .navlink { padding: 8px 10px; }
}
@media (max-width: 480px) {
  .hero h1 { font-size: 1.6rem; }
  .hero-stats { gap: 6px; }
  .stat-pill { min-width: 0; flex: 1; padding: 9px 12px; }
  .stat-pill-num { font-size: 1.05rem; }
  .stat-pill-lbl { font-size: .58rem; }
}

.code-panel-close {
  display: none;
  width: 30px; height: 30px; border-radius: 8px;
  align-items: center; justify-content: center;
  color: var(--text-muted);
  background: var(--surface);
  position: absolute; top: 12px; right: 12px;
  z-index: 2;
}
.code-panel-close:hover { background: var(--surface-2); color: var(--text); }

@media print {
  .topnav, .sidebar, .code-panel, .hero-bg, .hero-grid, .mobile-panel-toggle, .cmdk-backdrop { display: none !important; }
  .layout { display: block; padding: 0; }
  .endpoint { break-inside: avoid; border-color: #ccc; }
  .endpoint.open .endpoint-body { display: block !important; }
}
</style>
</head>
<body>

<header class="topnav">
  <div class="topnav-inner">
    <a class="brand" href="/">
      <span class="brand-badge">P</span>
      <span class="brand-name">Pinterest Scraper</span>
      <span class="brand-tag">API</span>
    </a>
    <div class="topnav-spacer"></div>
    <button class="search-trigger" id="search-trigger" type="button">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <span class="st-text">Search endpoints…</span>
      <span class="st-kbd"><kbd>⌘</kbd><kbd>K</kbd></span>
    </button>
    <nav class="navlinks">
      <a class="navlink" href="/" title="Home">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>
        <span>Home</span>
      </a>
      <a class="navlink primary" href="/openapi.json" target="_blank" title="OpenAPI JSON">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        <span>OpenAPI</span>
      </a>
      <button class="theme-toggle" id="theme-toggle" type="button" aria-label="Toggle theme">
        <svg id="theme-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
      </button>
    </nav>
  </div>
</header>

<section class="hero">
  <div class="hero-bg"></div>
  <div class="hero-grid"></div>
  <div class="hero-inner">
    <div class="hero-eyebrow">
      <span class="pulse"></span>
      <span id="hero-version">Loading…</span>
    </div>
    <h1>Pinterest Scraper <span class="accent">API</span></h1>
    <p id="hero-desc">High-quality Pinterest scraper API with job events, exports, and gallery management.</p>
    <div class="hero-stats" id="hero-stats"></div>
  </div>
</section>

<div class="layout">
  <aside class="sidebar">
    <label class="sidebar-filter">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input id="filter-input" type="text" placeholder="Filter…" autocomplete="off">
    </label>
    <div class="chip-row" id="chip-row"></div>
    <nav class="sidebar-nav" id="sidebar-nav"></nav>
  </aside>

  <main class="content">
    <div class="content-header">
      <div>
        <h2>API Reference</h2>
        <div class="lead" id="content-lead">All endpoints exposed by the service.</div>
      </div>
      <div class="filter-hint" id="filter-hint" style="display:none"></div>
    </div>
    <div id="endpoints-container"></div>
  </main>

  <aside class="code-panel" id="code-panel">
    <button class="code-panel-close" id="code-panel-close" aria-label="Close">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
    <div class="code-panel-empty" id="code-empty">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
      <h3>Select an endpoint</h3>
      <p>Click any endpoint to see code samples in cURL, Python, JavaScript, and Go.</p>
    </div>
    <div id="code-panel-content" style="display:none; flex-direction: column; flex: 1; min-height: 0;"></div>
  </aside>
</div>

<button class="mobile-panel-toggle" id="mobile-panel-toggle" type="button">
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
  <span>Code</span>
</button>

<footer class="docs-footer">
  <div class="docs-footer-inner">
    <div>Made with <span class="heart">♥</span> using FastAPI</div>
    <div id="footer-meta"></div>
  </div>
</footer>

<div class="cmdk-backdrop" id="cmdk-backdrop">
  <div class="cmdk">
    <div class="cmdk-input-wrap">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input class="cmdk-input" id="cmdk-input" placeholder="Search endpoints by path, method, or summary…" autocomplete="off">
      <kbd>ESC</kbd>
    </div>
    <div class="cmdk-results" id="cmdk-results"></div>
    <div class="cmdk-footer">
      <span><kbd>↑</kbd><kbd>↓</kbd> navigate</span>
      <span><kbd>↵</kbd> open</span>
      <span style="margin-left:auto"><kbd>⌘</kbd><kbd>K</kbd> toggle</span>
    </div>
  </div>
</div>

<div class="toast-container" id="toast-container"></div>

<script>window.__SPEC__ = __SPEC_JSON__;</script>
<script>
(function () {
  'use strict';

  var METHOD_ORDER = ['get', 'post', 'put', 'patch', 'delete'];
  var METHOD_LABEL = { get: 'GET', post: 'POST', put: 'PUT', patch: 'PATCH', delete: 'DELETE' };
  var LANGS = ['curl', 'python', 'javascript', 'go'];
  var LANG_LABEL = { curl: 'cURL', python: 'Python', javascript: 'JavaScript', go: 'Go' };

  var $ = function (id) { return document.getElementById(id); };

  var state = {
    spec: null,
    endpoints: [],
    filtered: [],
    activeMethod: 'all',
    activeEndpointId: null,
    activeLang: 'curl',
    authToken: '',
    pathParamValues: {},
    lastResponse: null,
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function toast(msg) {
    var c = $('toast-container');
    if (!c) return;
    var el = document.createElement('div');
    el.className = 'toast';
    el.innerHTML = '<span class="dot"></span><span>' + escapeHtml(msg) + '</span>';
    c.appendChild(el);
    setTimeout(function () {
      el.style.transition = 'opacity .25s, transform .25s';
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      setTimeout(function () { el.remove(); }, 260);
    }, 1800);
  }

  function setIcon() {
    var icon = $('theme-icon');
    if (!icon) return;
    var dark = document.body.getAttribute('data-theme') === 'dark';
    icon.innerHTML = dark
      ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>'
      : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem('docs-theme') || localStorage.getItem('theme'); } catch (e) {}
    var prefers = 'light';
    try { prefers = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'; } catch (e) {}
    document.body.setAttribute('data-theme', saved || prefers);
    setIcon();
  }

  function toggleTheme() {
    var next = document.body.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    document.body.setAttribute('data-theme', next);
    try { localStorage.setItem('docs-theme', next); } catch (e) {}
    setIcon();
    toast(next === 'dark' ? 'Dark mode' : 'Light mode');
  }

  function initAuth() {
    try {
      var t = localStorage.getItem('docs-auth-token');
      if (t) state.authToken = t;
    } catch (e) {}
  }

  function saveAuth(token) {
    state.authToken = token || '';
    try {
      if (token) localStorage.setItem('docs-auth-token', token);
      else localStorage.removeItem('docs-auth-token');
    } catch (e) {}
  }

  function initLang() {
    try {
      var l = localStorage.getItem('docs-lang');
      if (l && LANGS.indexOf(l) >= 0) state.activeLang = l;
    } catch (e) {}
  }

  function saveLang(l) {
    state.activeLang = l;
    try { localStorage.setItem('docs-lang', l); } catch (e) {}
  }

  function resolveRef(ref, spec) {
    if (!ref || ref.indexOf('#/') !== 0) return null;
    var parts = ref.slice(2).split('/');
    var cur = spec;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return null;
      cur = cur[parts[i].replace(/~1/g, '/').replace(/~0/g, '~')];
    }
    return cur;
  }

  function schemaType(schema) {
    if (!schema) return 'any';
    if (schema.$ref) return schema.$ref.split('/').pop();
    if (schema.anyOf || schema.oneOf) {
      var arr = schema.anyOf || schema.oneOf;
      return arr.map(schemaType).join(' | ');
    }
    if (schema.type === 'array') return 'array<' + schemaType(schema.items) + '>';
    if (Array.isArray(schema.type)) return schema.type.join(' | ');
    return schema.type || 'object';
  }

  function sampleFromSchema(schema, spec, depth) {
    depth = depth || 0;
    if (!schema || depth > 5) return null;
    if (schema.$ref) {
      var resolved = resolveRef(schema.$ref, spec);
      return sampleFromSchema(resolved, spec, depth + 1);
    }
    if (schema.example !== undefined) return schema.example;
    if (schema.default !== undefined) return schema.default;
    if (schema.anyOf || schema.oneOf) return sampleFromSchema((schema.anyOf || schema.oneOf)[0], spec, depth + 1);
    var t = schema.type;
    if (t === 'object' || schema.properties) {
      var out = {};
      var props = schema.properties || {};
      Object.keys(props).forEach(function (k) { out[k] = sampleFromSchema(props[k], spec, depth + 1); });
      return out;
    }
    if (t === 'array') return [sampleFromSchema(schema.items, spec, depth + 1)];
    if (t === 'string') {
      if (schema.enum && schema.enum.length) return schema.enum[0];
      if (schema.format === 'date-time') return new Date().toISOString();
      return 'string';
    }
    if (t === 'integer' || t === 'number') return 0;
    if (t === 'boolean') return false;
    return null;
  }

  function buildEndpointData(path, method, op, spec) {
    var params = [];
    var allParams = [].concat(op.parameters || []);
    if (op.requestBody) {
      var rb = op.requestBody;
      var content = rb.content || {};
      var key = content['application/json'] ? 'application/json' : Object.keys(content)[0];
      var contentObj = key ? content[key] : null;
      var schema = contentObj ? contentObj.schema : null;
      var resolved = schema && schema.$ref ? resolveRef(schema.$ref, spec) : schema;
      var props = (resolved && resolved.properties) || {};
      var required = (resolved && resolved.required) || [];
      Object.keys(props).forEach(function (name) {
        params.push({
          name: name,
          type: schemaType(props[name]),
          required: required.indexOf(name) >= 0,
          desc: (props[name] && props[name].description) || '',
          in: 'body'
        });
      });
    }
    allParams.forEach(function (p) {
      params.push({
        name: p.name,
        type: schemaType(p.schema || {}),
        required: !!p.required,
        desc: p.description || '',
        in: p.in || 'query'
      });
    });

    var exampleJSON = null;
    if (op.requestBody) {
      var c = op.requestBody.content || {};
      var k = c['application/json'] ? 'application/json' : Object.keys(c)[0];
      if (k) {
        var s = c[k].schema;
        var r = s && s.$ref ? resolveRef(s.$ref, spec) : s;
        exampleJSON = sampleFromSchema(r, spec, 0);
      }
    }

    var methodUpper = method.toUpperCase();
    return {
      id: 'ep-' + method + '-' + path.replace(/[^\w]/g, '_'),
      path: path,
      method: method,
      methodLabel: METHOD_LABEL[method] || methodUpper,
      summary: op.summary || '',
      description: op.description || '',
      tags: op.tags || ['default'],
      params: params,
      exampleJSON: exampleJSON,
      responses: op.responses || {}
    };
  }

  function fillPath(path, params, values) {
    return path.replace(/{([^}]+)}/g, function (_, name) {
      var v = values[name];
      if (v) return v;
      var p = params.filter(function (x) { return x.name === name && x.in === 'path'; })[0];
      if (p && /int|number/.test(p.type)) return '1234';
      if (p) return 'example';
      return 'value';
    });
  }

  function generateCode(ep, lang) {
    var origin = window.location.origin;
    var fullPath = fillPath(ep.path, ep.params, state.pathParamValues);
    var url = origin + fullPath;
    var bodyParams = ep.params.filter(function (p) { return p.in === 'body'; });
    var queryParams = ep.params.filter(function (p) { return p.in === 'query'; });
    var hasBody = bodyParams.length > 0 || ep.exampleJSON != null;
    var authHeader = state.authToken ? 'Bearer ' + state.authToken : null;

    var bodyObj = ep.exampleJSON;
    var queryStr = queryParams.map(function (p) {
      return p.name + '=' + encodeURIComponent(p.type === 'integer' || p.type === 'number' ? '0' : (p.type === 'boolean' ? 'true' : 'value'));
    }).join('&');
    var urlWithQuery = queryStr ? url + '?' + queryStr : url;

    if (lang === 'curl') {
      var lines = ["curl -X " + ep.methodLabel + " '" + urlWithQuery + "'"];
      if (hasBody) lines.push("  -H 'Content-Type: application/json'");
      if (authHeader) lines.push("  -H 'Authorization: " + authHeader + "'");
      if (hasBody) lines.push("  -d '" + JSON.stringify(bodyObj || {}, null, 2).replace(/'/g, "'\\''") + "'");
      return lines.join(" \\\n");
    }

    if (lang === 'python') {
      var py = "import requests\n\n";
      if (hasBody) py += "payload = " + JSON.stringify(bodyObj || {}, null, 4) + "\n\n";
      py += "headers = {";
      var hdrs = [];
      if (hasBody) hdrs.push("'Content-Type': 'application/json'");
      if (authHeader) hdrs.push("'Authorization': '" + authHeader + "'");
      py += hdrs.join(', ') + "}\n\n";
      py += "response = requests." + ep.method.toLowerCase() + "(\n";
      py += "    '" + urlWithQuery + "',\n";
      if (hasBody) py += "    json=payload,\n";
      py += "    headers=headers,\n";
      py += "    timeout=60,\n";
      py += ")\n\n";
      py += "print(response.status_code)\nprint(response.json())";
      return py;
    }

    if (lang === 'javascript') {
      var js = "const response = await fetch('" + urlWithQuery + "', {\n";
      js += "  method: '" + ep.methodLabel + "',\n";
      js += "  headers: {\n";
      if (hasBody) js += "    'Content-Type': 'application/json',\n";
      if (authHeader) js += "    'Authorization': '" + authHeader + "',\n";
      js += "  },\n";
      if (hasBody) js += "  body: JSON.stringify(" + JSON.stringify(bodyObj || {}, null, 2) + "),\n";
      js += "});\n\n";
      js += "const data = await response.json();\nconsole.log(data);";
      return js;
    }

    if (lang === 'go') {
      var g = "package main\n\nimport (\n    \"bytes\"\n    \"encoding/json\"\n    \"fmt\"\n    \"net/http\"\n)\n\nfunc main() {\n";
      if (hasBody) {
        g += "    payload := map[string]interface{}{}\n";
        g += "    bodyBytes, _ := json.Marshal(payload)\n";
        g += "    req, _ := http.NewRequest(\"" + ep.methodLabel + "\", \"" + urlWithQuery + "\", bytes.NewBuffer(bodyBytes))\n";
      } else {
        g += "    req, _ := http.NewRequest(\"" + ep.methodLabel + "\", \"" + urlWithQuery + "\", nil)\n";
      }
      if (hasBody) g += "    req.Header.Set(\"Content-Type\", \"application/json\")\n";
      if (authHeader) g += "    req.Header.Set(\"Authorization\", \"" + authHeader + "\")\n";
      g += "    resp, err := http.DefaultClient.Do(req)\n";
      g += "    if err != nil { panic(err) }\n";
      g += "    defer resp.Body.Close()\n";
      g += "    var out interface{}\n";
      g += "    json.NewDecoder(resp.Body).Decode(&out)\n";
      g += "    fmt.Println(resp.Status, out)\n}";
      return g;
    }

    return '';
  }

  function highlightCode(code, lang) {
    var esc = escapeHtml(code);
    if (lang === 'python' || lang === 'go' || lang === 'javascript') {
      esc = esc.replace(/(#.*$|\/\/.*$)/gm, '<span class="tok-comment">$1</span>');
      esc = esc.replace(/'([^'\\]|\\.)*'/g, '<span class="tok-string">$&</span>');
      esc = esc.replace(/"([^"\\]|\\.)*"/g, '<span class="tok-string">$&</span>');
      esc = esc.replace(/\b(import|from|def|class|return|if|else|elif|for|while|in|not|and|or|True|False|None|package|func|type|var|const|let|await|async|new|interface|struct|map|string|int|bool|float|nil|null|true|false|func|defer|go|fmt|panic|print|console|log|println|Println|Print|json|requests|fetch|response|req|body|headers|method)\b/g, '<span class="tok-fn">$1</span>');
      esc = esc.replace(/\b(\d+)\b/g, '<span class="tok-num">$1</span>');
    }
    return esc;
  }

  function renderJsonTree(value, key, path, depth) {
    depth = depth || 0;
    path = path || '$';
    var indent = depth * 14;

    if (value === null) {
      return '<div class="jt-line" style="padding-left:' + indent + 'px">' +
        (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
        '<span class="jt-null">null</span></div>';
    }
    if (typeof value === 'boolean') {
      return '<div class="jt-line" style="padding-left:' + indent + 'px">' +
        (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
        '<span class="jt-bool">' + value + '</span></div>';
    }
    if (typeof value === 'number') {
      return '<div class="jt-line" style="padding-left:' + indent + 'px">' +
        (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
        '<span class="jt-num">' + value + '</span></div>';
    }
    if (typeof value === 'string') {
      var display = value.length > 120 ? value.slice(0, 120) + '…' : value;
      return '<div class="jt-line jt-copyable" style="padding-left:' + indent + 'px" data-copy-val="' + escapeHtml(value) + '" title="Click to copy">' +
        (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
        '<span class="jt-string">"' + escapeHtml(display) + '"</span></div>';
    }
    if (Array.isArray(value)) {
      var aid = 'jt-' + Math.random().toString(36).slice(2, 9);
      if (value.length === 0) {
        return '<div class="jt-line" style="padding-left:' + indent + 'px">' +
          (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
          '<span style="color:var(--text-dim)">[]</span></div>';
      }
      var items = value.map(function (v, i) { return renderJsonTree(v, null, path + '[' + i + ']', depth + 1); }).join('');
      return '<div class="jt-node">' +
        '<div class="jt-line jt-toggle" style="padding-left:' + indent + 'px" data-target="' + aid + '">' +
          '<svg class="jt-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
          (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
          '<span class="jt-count">Array(' + value.length + ')</span>' +
        '</div>' +
        '<div class="jt-children" id="' + aid + '">' + items + '</div>' +
      '</div>';
    }
    if (typeof value === 'object') {
      var oid = 'jt-' + Math.random().toString(36).slice(2, 9);
      var keys = Object.keys(value);
      if (keys.length === 0) {
        return '<div class="jt-line" style="padding-left:' + indent + 'px">' +
          (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
          '<span style="color:var(--text-dim)">{}</span></div>';
      }
      var children = keys.map(function (k) { return renderJsonTree(value[k], k, path + '.' + k, depth + 1); }).join('');
      return '<div class="jt-node">' +
        '<div class="jt-line jt-toggle" style="padding-left:' + indent + 'px" data-target="' + oid + '">' +
          '<svg class="jt-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>' +
          (key != null ? '<span class="jt-key">"' + escapeHtml(key) + '"</span><span style="color:var(--text-dim)">: </span>' : '') +
          '<span class="jt-count">Object(' + keys.length + ')</span>' +
        '</div>' +
        '<div class="jt-children" id="' + oid + '">' + children + '</div>' +
      '</div>';
    }
    return '';
  }

  function renderHero(spec, endpoints) {
    var heroVer = $('hero-version');
    if (heroVer) heroVer.textContent = 'v' + (spec.info && spec.info.version || '1.0.0') + ' · Live';
    var heroDesc = $('hero-desc');
    if (heroDesc && spec.info && spec.info.description) heroDesc.textContent = spec.info.description;
    var tags = {};
    endpoints.forEach(function (e) { tags[e.tags[0] || 'default'] = 1; });
    var methods = {};
    endpoints.forEach(function (e) { methods[e.method] = 1; });
    var stats = [
      { num: endpoints.length, lbl: 'Endpoints' },
      { num: Object.keys(tags).length, lbl: 'Groups' },
      { num: Object.keys(methods).length, lbl: 'Methods' }
    ];
    var el = $('hero-stats');
    if (el) {
      el.innerHTML = stats.map(function (s) {
        return '<div class="stat-pill"><div class="stat-pill-num">' + s.num + '</div><div class="stat-pill-lbl">' + s.lbl + '</div></div>';
      }).join('');
    }
    var fm = $('footer-meta');
    if (fm) fm.textContent = 'API v' + (spec.info && spec.info.version || '1.0.0');
  }

  function renderChips() {
    var row = $('chip-row');
    if (!row) return;
    var methods = { all: true, get: true, post: true, put: true, patch: true, delete: true };
    var order = ['all', 'get', 'post', 'put', 'patch', 'delete'];
    row.innerHTML = order.filter(function (m) { return methods[m]; }).map(function (m) {
      return '<button class="filter-chip' + (state.activeMethod === m ? ' active' : '') + '" data-method-chip="' + m + '">' + (m === 'all' ? 'All' : m.toUpperCase()) + '</button>';
    }).join('');
  }

  function renderSidebar(endpoints) {
    var nav = $('sidebar-nav');
    if (!nav) return;
    var groups = {};
    endpoints.forEach(function (ep) {
      var tag = ep.tags[0] || 'default';
      if (!groups[tag]) groups[tag] = [];
      groups[tag].push(ep);
    });
    var tagOrder = Object.keys(groups).sort();
    if (!tagOrder.length) {
      nav.innerHTML = '';
      return;
    }
    nav.innerHTML = tagOrder.map(function (tag) {
      var items = groups[tag].map(function (ep) {
        return '<a class="nav-item" href="#' + ep.id + '" data-endpoint="' + ep.id + '">' +
          '<span class="method ' + ep.method + '">' + ep.methodLabel + '</span>' +
          '<span class="path-text">' + escapeHtml(ep.path) + '</span>' +
        '</a>';
      }).join('');
      return '<div class="nav-group">' +
        '<div class="nav-group-title">' + escapeHtml(tag) + '<span class="count">' + groups[tag].length + '</span></div>' +
        '<div>' + items + '</div>' +
      '</div>';
    }).join('');
  }

  function renderEndpoint(ep) {
    var paramsHTML = '';
    if (ep.params.length) {
      paramsHTML = '<div class="endpoint-section">' +
        '<div class="section-title">Parameters</div>' +
        '<div class="param-table">' +
          '<div class="param-row header"><div>Name</div><div>Type</div><div>Required</div><div>Description</div></div>' +
          ep.params.map(function (p) {
            return '<div class="param-row">' +
              '<div class="param-name">' + escapeHtml(p.name) + '</div>' +
              '<div class="param-type">' + escapeHtml(p.type) + '</div>' +
              '<div class="param-required' + (p.required ? '' : ' optional') + '">' + (p.required ? 'Required' : 'Optional') + '</div>' +
              '<div class="param-desc">' + escapeHtml(p.desc) + '</div>' +
            '</div>';
          }).join('') +
        '</div>' +
      '</div>';
    }

    var respKeys = Object.keys(ep.responses);
    var responsesHTML = '';
    if (respKeys.length) {
      responsesHTML = '<div class="endpoint-section">' +
        '<div class="section-title">Responses</div>' +
        respKeys.map(function (code) {
          var resp = ep.responses[code] || {};
          var cls = 'ok';
          var n = parseInt(code, 10);
          if (n >= 500) cls = 'server';
          else if (n >= 400) cls = 'client';
          else if (n >= 300) cls = 'redirect';
          return '<div class="response-row">' +
            '<span class="status-code ' + cls + '">' + escapeHtml(code) + '</span>' +
            '<span class="response-desc">' + escapeHtml(resp.description || '') + '</span>' +
          '</div>';
        }).join('') +
      '</div>';
    }

    return '<article class="endpoint" id="' + ep.id + '" data-endpoint="' + ep.id + '">' +
      '<div class="endpoint-head" data-toggle>' +
        '<span class="endpoint-method ' + ep.method + '">' + ep.methodLabel + '</span>' +
        '<span class="endpoint-path">' + escapeHtml(ep.path) + '</span>' +
        '<span class="endpoint-summary">' + escapeHtml(ep.summary) + '</span>' +
        '<svg class="endpoint-chevron" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>' +
      '</div>' +
      '<div class="endpoint-body">' +
        (ep.description ? '<div class="endpoint-desc">' + escapeHtml(ep.description) + '</div>' : '') +
        paramsHTML + responsesHTML +
      '</div>' +
    '</article>';
  }

  function renderContent(endpoints) {
    var c = $('endpoints-container');
    if (!c) return;
    if (!endpoints.length) {
      c.innerHTML = '<div class="endpoint" style="padding:40px; text-align:center; color:var(--text-muted);">' +
        '<p style="font-size:.88rem;">No endpoints match your filter.</p>' +
      '</div>';
      return;
    }
    c.innerHTML = endpoints.map(renderEndpoint).join('');
  }

  function getEndpoint(id) {
    return state.endpoints.filter(function (e) { return e.id === id; })[0];
  }

  function renderCodePanel(ep) {
    var content = $('code-panel-content');
    var empty = $('code-empty');
    if (!content || !empty) return;

    if (!ep) {
      content.style.display = 'none';
      empty.style.display = 'flex';
      return;
    }

    empty.style.display = 'none';
    content.style.display = 'flex';

    var langTabs = LANGS.map(function (l) {
      return '<button class="lang-tab' + (l === state.activeLang ? ' active' : '') + '" data-lang="' + l + '">' + LANG_LABEL[l] + '</button>';
    }).join('');

    var pathParams = ep.params.filter(function (p) { return p.in === 'path'; });
    var pathParamsHTML = '';
    if (pathParams.length) {
      pathParamsHTML = '<div class="path-params-inline">' +
        pathParams.map(function (p) {
          var v = state.pathParamValues[p.name] || '';
          return '<label>' + escapeHtml(p.name) + '<input type="text" data-path-param="' + escapeHtml(p.name) + '" value="' + escapeHtml(v) + '" placeholder="Enter ' + escapeHtml(p.name) + '"></label>';
        }).join('') +
      '</div>';
    }

    var authHTML = '<div class="auth-panel">' +
      '<label>Bearer token ' + (state.authToken ? '<span class="badge">Saved</span>' : '') + '</label>' +
      '<div class="auth-input-row">' +
        '<input type="password" id="auth-input" placeholder="Paste your token (optional)" value="' + escapeHtml(state.authToken) + '">' +
        '<button class="btn ghost small" id="auth-save" type="button">Save</button>' +
      '</div>' +
    '</div>';

    content.innerHTML =
      '<div class="code-panel-head">' +
        '<div class="code-panel-head-top">' +
          '<span class="method ' + ep.method + '">' + ep.methodLabel + '</span>' +
          '<span class="path">' + escapeHtml(ep.path) + '</span>' +
        '</div>' +
        (ep.summary ? '<div class="summary">' + escapeHtml(ep.summary) + '</div>' : '') +
      '</div>' +
      '<div class="lang-tabs" role="tablist">' + langTabs + '</div>' +
      '<div class="code-panel-body">' +
        authHTML +
        pathParamsHTML +
        '<div class="code-block">' +
          '<button class="copy-btn" type="button" data-copy-code>' +
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
            '<span>Copy</span>' +
          '</button>' +
          '<pre id="code-pre"></pre>' +
        '</div>' +
        '<div class="run-row">' +
          '<button class="btn primary full" id="run-btn" type="button">' +
            '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>' +
            '<span>Run request</span>' +
          '</button>' +
        '</div>' +
        '<div class="response-panel" id="response-panel">' +
          '<div class="response-head" id="response-head"></div>' +
          '<div class="json-tree" id="json-tree"></div>' +
        '</div>' +
      '</div>';

    updateCodePre(ep);
  }

  function updateCodePre(ep) {
    var pre = $('code-pre');
    if (!pre) return;
    var code = generateCode(ep, state.activeLang);
    pre.innerHTML = highlightCode(code, state.activeLang);
  }

  function selectEndpoint(id) {
    if (state.activeEndpointId === id) {
      openCodePanelMobile();
      return;
    }
    state.activeEndpointId = id;
    var ep = getEndpoint(id);
    if (!ep) return;

    document.querySelectorAll('.endpoint').forEach(function (el) {
      el.classList.toggle('selected', el.id === id);
    });
    document.querySelectorAll('.nav-item').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-endpoint') === id);
    });

    var el = document.getElementById(id);
    if (el) el.classList.add('open');
    renderCodePanel(ep);
    openCodePanelMobile();

    if (history.replaceState) {
      history.replaceState(null, '', '#' + id);
    }
  }

  function openCodePanelMobile() {
    var panel = $('code-panel');
    if (!panel) return;
    if (window.innerWidth <= 1180) {
      panel.classList.add('show');
    }
  }

  function closeCodePanelMobile() {
    var panel = $('code-panel');
    if (panel) panel.classList.remove('show');
  }

  function applyFilter() {
    var input = $('filter-input');
    var q = (input && input.value || '').trim().toLowerCase();
    var method = state.activeMethod;
    var filtered = state.endpoints.filter(function (ep) {
      if (method !== 'all' && ep.method !== method) return false;
      if (!q) return true;
      return ep.path.toLowerCase().indexOf(q) >= 0
        || (ep.summary || '').toLowerCase().indexOf(q) >= 0
        || (ep.description || '').toLowerCase().indexOf(q) >= 0
        || ep.tags.join(' ').toLowerCase().indexOf(q) >= 0;
    });
    state.filtered = filtered;
    renderContent(filtered);
    renderSidebar(filtered);
    var hint = $('filter-hint');
    if (hint) {
      if (q || method !== 'all') {
        hint.style.display = '';
        hint.textContent = filtered.length + ' shown';
      } else {
        hint.style.display = 'none';
      }
    }
  }

  function handleTryIt(ep) {
    var runBtn = $('run-btn');
    var status = document.querySelector('.run-status');
    if (!runBtn) return;

    var fullPath = fillPath(ep.path, ep.params, state.pathParamValues);
    var url = fullPath;

    runBtn.disabled = true;
    var oldHtml = runBtn.innerHTML;
    runBtn.innerHTML = '<span class="loader"></span><span>Sending…</span>';

    var opts = { method: ep.methodLabel, headers: { 'Accept': 'application/json' } };
    if (state.authToken) opts.headers['Authorization'] = 'Bearer ' + state.authToken;

    var bodyParams = ep.params.filter(function (p) { return p.in === 'body'; });
    if (bodyParams.length && ep.exampleJSON != null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(ep.exampleJSON);
    }

    var startTime = performance.now();

    fetch(url, opts)
      .then(function (res) {
        var elapsed = Math.round(performance.now() - startTime);
        return res.text().then(function (text) {
          var parsed = null;
          try { parsed = JSON.parse(text); } catch (e) { parsed = text; }
          showResponse(res.status, res.statusText, parsed, elapsed, text.length);
          return { ok: res.ok, status: res.status };
        });
      })
      .catch(function (err) {
        showResponse(0, 'Network error', { error: String(err) }, 0, 0);
      })
      .then(function () {
        runBtn.disabled = false;
        runBtn.innerHTML = oldHtml;
      });
  }

  function showResponse(status, statusText, body, ms, sizeBytes) {
    var panel = $('response-panel');
    var head = $('response-head');
    var tree = $('json-tree');
    if (!panel || !head || !tree) return;

    var cls = 'ok';
    if (status >= 500) cls = 'server';
    else if (status >= 400) cls = 'client';
    else if (status >= 300) cls = 'redirect';

    var sizeStr = sizeBytes > 1024 ? (sizeBytes / 1024).toFixed(1) + ' KB' : sizeBytes + ' B';
    var jsonText = typeof body === 'string' ? body : JSON.stringify(body, null, 2);

    head.innerHTML =
      '<span class="status-code ' + cls + '">' + status + ' ' + escapeHtml(statusText || '') + '</span>' +
      '<span class="response-meta">' + ms + 'ms · ' + sizeStr + '</span>' +
      '<div class="response-actions">' +
        '<button class="response-action" type="button" data-copy-response>Copy JSON</button>' +
        '<button class="response-action" type="button" data-collapse-all>Collapse all</button>' +
      '</div>';

    if (typeof body === 'object' && body !== null) {
      tree.innerHTML = renderJsonTree(body, null, '$', 0);
    } else {
      tree.innerHTML = '<div class="jt-line"><span class="jt-string">' + escapeHtml(String(body)) + '</span></div>';
    }
    panel.classList.add('show');
    panel.setAttribute('data-json-text', jsonText);
  }

  function copyText(text, label) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        toast((label || 'Copied') + ' to clipboard');
        return true;
      }).catch(function () {
        toast('Copy failed');
        return false;
      });
    }
    toast('Copy not supported');
    return Promise.resolve(false);
  }

  function handleClick(e) {
    var t = e.target;
    if (!t || !t.closest) return;

    // endpoint head toggles
    var toggle = t.closest('[data-toggle]');
    if (toggle) {
      var art = toggle.closest('.endpoint');
      if (art) {
        var id = art.getAttribute('data-endpoint');
        if (state.activeEndpointId === id) {
          art.classList.toggle('open');
        } else {
          selectEndpoint(id);
        }
      }
      return;
    }

    // nav item
    var navItem = t.closest('.nav-item');
    if (navItem) {
      e.preventDefault();
      var id2 = navItem.getAttribute('data-endpoint');
      if (id2) selectEndpoint(id2);
      return;
    }

    // copy button (code)
    var copyBtn = t.closest('[data-copy-code]');
    if (copyBtn) {
      var ep = getEndpoint(state.activeEndpointId);
      if (ep) {
        var code = generateCode(ep, state.activeLang);
        copyText(code, 'Code').then(function () {
          var old = copyBtn.innerHTML;
          copyBtn.classList.add('copied');
          copyBtn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span>Copied</span>';
          setTimeout(function () {
            copyBtn.innerHTML = old;
            copyBtn.classList.remove('copied');
          }, 1400);
        });
      }
      return;
    }

    // run button
    var runBtn = t.closest('#run-btn');
    if (runBtn) {
      var ep2 = getEndpoint(state.activeEndpointId);
      if (ep2) handleTryIt(ep2);
      return;
    }

    // language tabs
    var langTab = t.closest('.lang-tab');
    if (langTab) {
      saveLang(langTab.getAttribute('data-lang'));
      var ep3 = getEndpoint(state.activeEndpointId);
      if (ep3) {
        document.querySelectorAll('.lang-tab').forEach(function (x) { x.classList.remove('active'); });
        langTab.classList.add('active');
        updateCodePre(ep3);
      }
      return;
    }

    // auth save
    var authSave = t.closest('#auth-save');
    if (authSave) {
      var inp = $('auth-input');
      if (inp) {
        saveAuth(inp.value.trim());
        toast(state.authToken ? 'Token saved' : 'Token cleared');
        var ep4 = getEndpoint(state.activeEndpointId);
        if (ep4) renderCodePanel(ep4);
      }
      return;
    }

    // method chip
    var chip = t.closest('[data-method-chip]');
    if (chip) {
      state.activeMethod = chip.getAttribute('data-method-chip');
      renderChips();
      applyFilter();
      return;
    }

    // JSON tree toggle
    var jtToggle = t.closest('.jt-toggle');
    if (jtToggle) {
      var targetId = jtToggle.getAttribute('data-target');
      if (targetId) {
        var node = document.getElementById(targetId);
        if (node) node.parentElement.classList.toggle('collapsed');
      }
      return;
    }

    // copyable json value
    var jtCopy = t.closest('.jt-copyable');
    if (jtCopy) {
      var val = jtCopy.getAttribute('data-copy-val');
      if (val != null) copyText(val, 'Value');
      return;
    }

    // response actions
    var respCopy = t.closest('[data-copy-response]');
    if (respCopy) {
      var rp = $('response-panel');
      if (rp) copyText(rp.getAttribute('data-json-text') || '', 'Response');
      return;
    }
    var collapseAll = t.closest('[data-collapse-all]');
    if (collapseAll) {
      var tree = $('json-tree');
      if (tree) {
        var nodes = tree.querySelectorAll('.jt-node');
        var anyOpen = false;
        nodes.forEach(function (n) { if (!n.classList.contains('collapsed')) anyOpen = true; });
        nodes.forEach(function (n) {
          if (anyOpen) n.classList.add('collapsed');
          else n.classList.remove('collapsed');
        });
        collapseAll.textContent = anyOpen ? 'Expand all' : 'Collapse all';
      }
      return;
    }

    // close mobile panel
    var panelClose = t.closest('#code-panel-close');
    if (panelClose) { closeCodePanelMobile(); return; }

    var mobileToggle = t.closest('#mobile-panel-toggle');
    if (mobileToggle) {
      if (state.activeEndpointId) {
        openCodePanelMobile();
      } else {
        toast('Select an endpoint first');
      }
      return;
    }

    // cmdk backdrop click
    if (t.id === 'cmdk-backdrop') { closeCmdK(); return; }
  }

  function handleInput(e) {
    var t = e.target;
    if (!t) return;
    if (t.id === 'filter-input') { applyFilter(); return; }
    if (t.id === 'cmdk-input') { renderCmdKResults(t.value); return; }
    if (t.getAttribute && t.getAttribute('data-path-param')) {
      var name = t.getAttribute('data-path-param');
      state.pathParamValues[name] = t.value;
      var ep = getEndpoint(state.activeEndpointId);
      if (ep) updateCodePre(ep);
      return;
    }
  }

  // ---------- Cmd+K ----------
  var cmdkIndex = -1;
  var cmdkItems = [];

  function openCmdK() {
    var bd = $('cmdk-backdrop');
    if (!bd) return;
    bd.classList.add('show');
    var inp = $('cmdk-input');
    if (inp) {
      inp.value = '';
      renderCmdKResults('');
      setTimeout(function () { inp.focus(); }, 30);
    }
  }

  function closeCmdK() {
    var bd = $('cmdk-backdrop');
    if (bd) bd.classList.remove('show');
  }

  function renderCmdKResults(q) {
    var container = $('cmdk-results');
    if (!container) return;
    q = (q || '').toLowerCase().trim();
    cmdkItems = state.endpoints.filter(function (ep) {
      if (!q) return true;
      return ep.path.toLowerCase().indexOf(q) >= 0
        || (ep.summary || '').toLowerCase().indexOf(q) >= 0
        || ep.method.indexOf(q) >= 0
        || ep.tags.join(' ').toLowerCase().indexOf(q) >= 0;
    }).slice(0, 30);
    cmdkIndex = cmdkItems.length ? 0 : -1;
    if (!cmdkItems.length) {
      container.innerHTML = '<div class="cmdk-empty">No results for "' + escapeHtml(q) + '"</div>';
      return;
    }
    container.innerHTML = cmdkItems.map(function (ep, i) {
      return '<div class="cmdk-item' + (i === 0 ? ' active' : '') + '" data-idx="' + i + '">' +
        '<span class="m ' + ep.method + '">' + ep.methodLabel + '</span>' +
        '<span class="p">' + escapeHtml(ep.path) + '</span>' +
        '<span class="s">' + escapeHtml(ep.summary || '') + '</span>' +
      '</div>';
    }).join('');
  }

  function setCmdKIndex(i) {
    if (i < 0 || i >= cmdkItems.length) return;
    cmdkIndex = i;
    var container = $('cmdk-results');
    if (!container) return;
    container.querySelectorAll('.cmdk-item').forEach(function (el, n) {
      el.classList.toggle('active', n === i);
    });
    var active = container.querySelector('.cmdk-item.active');
    if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
  }

  function initCmdK() {
    var trigger = $('search-trigger');
    if (trigger) trigger.addEventListener('click', openCmdK);

    document.addEventListener('click', function (e) {
      var item = e.target.closest && e.target.closest('.cmdk-item');
      if (item) {
        var idx = parseInt(item.getAttribute('data-idx'), 10);
        var ep = cmdkItems[idx];
        if (ep) {
          closeCmdK();
          selectEndpoint(ep.id);
          var el = document.getElementById(ep.id);
          if (el) {
            el.scrollIntoView({ behavior: 'smooth', block: 'start' });
            el.classList.add('highlight');
            setTimeout(function () { el.classList.remove('highlight'); }, 1600);
          }
        }
      }
    });

    document.addEventListener('keydown', function (e) {
      var tag = document.activeElement && document.activeElement.tagName;
      var isInput = tag === 'INPUT' || tag === 'TEXTAREA';
      var cmdkOpen = $('cmdk-backdrop').classList.contains('show');

      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
        e.preventDefault();
        if (cmdkOpen) closeCmdK(); else openCmdK();
        return;
      }
      if (cmdkOpen) {
        if (e.key === 'Escape') { e.preventDefault(); closeCmdK(); return; }
        if (e.key === 'ArrowDown') { e.preventDefault(); setCmdKIndex(Math.min(cmdkIndex + 1, cmdkItems.length - 1)); return; }
        if (e.key === 'ArrowUp') { e.preventDefault(); setCmdKIndex(Math.max(cmdkIndex - 1, 0)); return; }
        if (e.key === 'Enter') {
          e.preventDefault();
          var ep = cmdkItems[cmdkIndex];
          if (ep) {
            closeCmdK();
            selectEndpoint(ep.id);
            var el = document.getElementById(ep.id);
            if (el) {
              el.scrollIntoView({ behavior: 'smooth', block: 'start' });
              el.classList.add('highlight');
              setTimeout(function () { el.classList.remove('highlight'); }, 1600);
            }
          }
          return;
        }
      }
      if (e.key === '/' && !isInput) {
        e.preventDefault();
        var f = $('filter-input');
        if (f) f.focus();
      }
    });
  }

  // ---------- Boot ----------
  function boot(spec) {
    if (!spec || !spec.paths) throw new Error('Invalid OpenAPI spec');
    state.spec = spec;
    var endpoints = [];
    var paths = spec.paths;
    Object.keys(paths).forEach(function (path) {
      var methods = paths[path];
      METHOD_ORDER.forEach(function (method) {
        if (methods[method]) {
          endpoints.push(buildEndpointData(path, method, methods[method], spec));
        }
      });
    });
    endpoints.sort(function (a, b) {
      var ta = a.tags[0] || 'default';
      var tb = b.tags[0] || 'default';
      if (ta !== tb) return ta < tb ? -1 : 1;
      if (a.path !== b.path) return a.path < b.path ? -1 : 1;
      return METHOD_ORDER.indexOf(a.method) - METHOD_ORDER.indexOf(b.method);
    });
    state.endpoints = endpoints;
    state.filtered = endpoints;

    renderHero(spec, endpoints);
    renderChips();
    renderSidebar(endpoints);
    renderContent(endpoints);

    // deep link
    var hash = (window.location.hash || '').slice(1);
    if (hash && getEndpoint(hash)) {
      setTimeout(function () {
        selectEndpoint(hash);
        var el = document.getElementById(hash);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }, 80);
    }

    // keyboard shortcut hint
    if (typeof window.matchMedia === 'function') {
      var isMac = window.navigator.platform.toUpperCase().indexOf('MAC') >= 0;
      var st = document.querySelector('.search-trigger .st-kbd');
      if (st && isMac) st.innerHTML = '<kbd>⌘</kbd><kbd>K</kbd>';
      else if (st) st.innerHTML = '<kbd>Ctrl</kbd><kbd>K</kbd>';
    }
  }

  function showError(title, detail) {
    var hv = $('hero-version');
    if (hv) hv.textContent = 'Error';
    var c = $('endpoints-container');
    if (c) {
      c.innerHTML = '<div class="endpoint" style="padding:40px; text-align:center;">' +
        '<h3 style="font-size:1rem; margin-bottom:6px;">' + escapeHtml(title) + '</h3>' +
        '<p style="font-size:.84rem; color:var(--text-muted); margin-bottom:14px;">' + escapeHtml(detail) + '</p>' +
        '<a class="btn primary" href="/openapi.json" target="_blank" style="display:inline-flex;">Open raw spec</a>' +
      '</div>';
    }
  }

  function init() {
    initTheme();
    initAuth();
    initLang();

    var tt = $('theme-toggle');
    if (tt) tt.addEventListener('click', function (e) { e.preventDefault(); toggleTheme(); });

    document.addEventListener('click', handleClick);
    document.addEventListener('input', handleInput);
    initCmdK();

    try {
      if (window.__SPEC__) boot(window.__SPEC__);
      else showError('No spec', 'OpenAPI schema not embedded.');
    } catch (err) {
      console.error(err);
      showError('Render error', String(err && err.message || err));
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
</script>
</body>
</html>
"""


@app.get("/docs", include_in_schema=False)
async def custom_docs():
    try:
        spec = app.openapi()
        spec_json = json.dumps(spec, default=str, ensure_ascii=False)
        spec_json = spec_json.replace("</", "<\\/")
    except Exception as e:
        spec_json = json.dumps({"info": {"version": "0"}, "paths": {}, "_error": str(e)})
    html = DOCS_HTML.replace("__SPEC_JSON__", spec_json)
    return HTMLResponse(html)


@app.get("/redoc", include_in_schema=False)
async def custom_redoc():
    from fastapi.openapi.docs import get_redoc_html
    return get_redoc_html(openapi_url=app.openapi_url, title="Pinterest Scraper · ReDoc")


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
