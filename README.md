<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=0,2,2,5,30&height=220&section=header&text=Pinterest%20Scraper&fontSize=64&fontColor=ffffff&fontAlignY=38&desc=Production-grade%20scraping%20%C2%B7%20Premium%20web%20UI%20%C2%B7%20Full%20metadata&descAlignY=60&descSize=16&animation=fadeIn" width="100%" />

<br />

<a href="https://pinterestscraperr.onrender.com?q=taylor+swift&filter=video">
  <img src="https://img.shields.io/badge/Live%20Demo-pinterestscraperr-E60023?style=for-the-badge&logo=render&logoColor=white&labelColor=000000" alt="Live Demo" />
</a>

<br /><br />

<a href="#-features"><img src="https://img.shields.io/badge/Features-000000?style=for-the-badge" /></a>
<a href="#-screenshots"><img src="https://img.shields.io/badge/Screenshots-000000?style=for-the-badge" /></a>
<a href="#-quick-start"><img src="https://img.shields.io/badge/Quick%20Start-000000?style=for-the-badge" /></a>
<a href="#-api-reference"><img src="https://img.shields.io/badge/API%20Reference-000000?style=for-the-badge" /></a>
<a href="#-deployment"><img src="https://img.shields.io/badge/Deploy-000000?style=for-the-badge" /></a>

<br /><br />

<a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" /></a>
<a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white" /></a>
<a href="https://render.com"><img src="https://img.shields.io/badge/Deploy-Render-46E3B7?style=flat-square&logo=render&logoColor=white" /></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-E60023?style=flat-square" /></a>

<br /><br />

<a href="https://github.com/raihan-rifat007/Pinterest-Scraper/stargazers"><img src="https://img.shields.io/github/stars/raihan-rifat007/Pinterest-Scraper?style=social" /></a>
<a href="https://github.com/raihan-rifat007/Pinterest-Scraper/network/members"><img src="https://img.shields.io/github/forks/raihan-rifat007/Pinterest-Scraper?style=social" /></a>

<br /><br />

**A production-grade Pinterest scraper engineered with a premium web UI.**<br />
Search · Board scrape · Download · Deduplicate · Export — all from one interface.

<br />

[Getting Started](#-quick-start) · [Report Bug](https://github.com/raihan-rifat007/Pinterest-Scraper/issues) · [Request Feature](https://github.com/raihan-rifat007/Pinterest-Scraper/issues)

</div>

---

<br />

<div align="center">

## ✨ What Makes This Different

</div>

<table>
<tr>
<td align="center" width="25%">
<br />
<img src="https://img.shields.io/badge/-%F0%9F%8E%A8-E60023?style=for-the-badge" width="60" />
<br /><br />
<b>Premium UI</b>
<br /><br />
<sub>Stripe-inspired masonry grid,<br />dark mode, live progress</sub>
<br /><br />
</td>
<td align="center" width="25%">
<br />
<img src="https://img.shields.io/badge/-%E2%9A%A1-E60023?style=for-the-badge" width="60" />
<br /><br />
<b>Real-time</b>
<br /><br />
<sub>SSE progress stream,<br />live metadata, instant export</sub>
<br /><br />
</td>
<td align="center" width="25%">
<br />
<img src="https://img.shields.io/badge/-%F0%9F%94%8D-E60023?style=for-the-badge" width="60" />
<br /><br />
<b>Full Metadata</b>
<br /><br />
<sub>25+ fields per pin —<br />saves, colors, creator, board</sub>
<br /><br />
</td>
<td align="center" width="25%">
<br />
<img src="https://img.shields.io/badge/-%F0%9F%9A%80-E60023?style=for-the-badge" width="60" />
<br /><br />
<b>Production</b>
<br /><br />
<sub>Retry logic, rate-limit aware,<br />proxy pool, dedup</sub>
<br /><br />
</td>
</tr>
</table>

<br />

---

## 📖 Table of Contents

<div align="center">

| | | |
|:-:|:-:|:-:|
| [🎯 Features](#-features) | [📸 Screenshots](#-screenshots) | [🏗️ Architecture](#️-architecture) |
| [🚀 Quick Start](#-quick-start) | [🔌 API Reference](#-api-reference) | [⚙️ Configuration](#️-configuration) |
| [☁️ Deployment](#️-deployment) | [🛠️ Tech Stack](#️-tech-stack) | [📊 Metadata](#-metadata-fields) |
| [🗺️ Roadmap](#️-roadmap) | [🤝 Contributing](#-contributing) | [⚖️ License](#️-license) |

</div>

<br />

---

## 🎯 Features

<div align="center">

**Everything you need to scrape, enrich, and export Pinterest content at scale.**

</div>

<br />

<table>
<tr>
<td width="50%" valign="top">

### 🔍 Scraping
- **Keyword search** — single query or comma-separated batch
- **Board scraping** — pass any board URL
- **Visual search** — related pins by pin ID
- **Typeahead suggest** — search + user results
- **High-res upgrade** — automatic `/originals/` path injection
- **Video detection** — extracts direct MP4 URLs

</td>
<td width="50%" valign="top">

### ⚡ Performance
- **Concurrent downloads** — configurable worker pool (1–16)
- **Retry logic** — exponential backoff on transient failures
- **Rate-limit aware** — adaptive delay + jitter
- **Proxy pool** — rotate across multiple proxies
- **Streaming export** — ZIP + XLSX built on-the-fly
- **Lazy image loading** — IntersectionObserver + native

</td>
</tr>
<tr>
<td valign="top">

### 🎨 Premium UI
- **Masonry grid** — 3 view modes: masonry · grid · list
- **Live SSE progress** — phase chips, ETA, rate/s
- **Video playback** — inline in pin modal
- **Dark / light theme** — system preference aware
- **Command palette** — `⌘K` fuzzy search
- **Right-click context menu** — per-card actions
- **Keyboard shortcuts** — `1/2/3` views · `F` focus · `S` sidebar

</td>
<td valign="top">

### 🚀 Advanced
- **Cross-run dedup** — hash + URL fingerprint
- **Scheduled scrapes** — cron-style, configurable hours
- **Collections** — group pins across sessions
- **History** — search / visual / delete events
- **Bulk selection** — long-press to batch delete
- **URL state** — shareable filters + sort state
- **Focus mode** — chrome-free browsing

</td>
</tr>
</table>

<br />

---

## 📸 Screenshots

<div align="center">

> _Replace these with screenshots from your deployed instance._

<br />

<table>
<tr>
<td align="center" width="50%">

### 🔍 Search View
<a href="docs/Search.png">
  <img src="docs/Search.png" width="100%" alt="Search View" />
</a>

<sub>Premium masonry grid with live scrape progress</sub>

</td>
<td align="center" width="50%">

### 🖼️ Pin Detail Modal
<a href="docs/Modal.png">
  <img src="docs/Modal.png" width="100%" alt="Pin Modal" />
</a>

<sub>Full metadata · video playback · palette extraction</sub>

</td>
</tr>
<tr>
<td align="center" width="50%">

### 📖 API Docs
<a href="docs/Docs.png">
  <img src="docs/Docs.png" width="100%" alt="API Docs" />
</a>

<sub>Auto-generated from OpenAPI with custom theme</sub>

</td>
</tr>
</table>

</div>

<br />

---

## 🏗️ Architecture

<div align="center">

```mermaid
flowchart TB
    subgraph Client["🖥️ Client"]
        UI["Premium Web UI<br/><sub>Vanilla JS · No build step</sub>"]
    end

    subgraph API["⚡ FastAPI Server"]
        direction TB
        Routes["REST Endpoints<br/><sub>/api/scrape · /api/gallery · /api/schedules</sub>"]
        SSE["SSE Stream<br/><sub>/api/jobs/:id/events</sub>"]
        Jobs["Job Manager<br/><sub>Threaded workers · Queue-based events</sub>"]
    end

    subgraph Core["🔧 Core Engine"]
        direction LR
        Scraper["Scraper"]
        HTTP["HTTP Layer<br/><sub>Retry · Rate-limit · Proxy</sub>"]
        Downloader["Downloader<br/><sub>ThreadPoolExecutor</sub>"]
        Dedupe["Dedupe Store"]
        Storage["Storage<br/><sub>JSON · CSV · XLSX · ZIP</sub>"]
    end

    subgraph External["🌐 External"]
        Pinterest["Pinterest API"]
    end

    subgraph FS["💾 Filesystem"]
        Output["web_output/<br/><sub>images · metadata · dedup store</sub>"]
    end

    UI -->|POST /api/scrape| Routes
    UI -.->|EventSource| SSE
    Routes --> Jobs
    Jobs --> Scraper
    Scraper --> HTTP
    HTTP --> Pinterest
    Jobs --> Downloader
    Downloader --> Output
    Jobs --> Dedupe
    Jobs --> Storage
    Storage --> Output
    Jobs -->|emit| SSE

    classDef client fill:#E60023,stroke:#8B0020,color:#fff
    classDef api fill:#009688,stroke:#00695C,color:#fff
    classDef core fill:#3B82F6,stroke:#1E40AF,color:#fff
    classDef ext fill:#8B5CF6,stroke:#6D28D9,color:#fff
    classDef fs fill:#F59E0B,stroke:#B45309,color:#fff

    class UI client
    class Routes,SSE,Jobs api
    class Scraper,HTTP,Downloader,Dedupe,Storage core
    class Pinterest ext
    class Output fs
```

</div>

<br />

Request Lifecycle

```mermaid
sequenceDiagram
    participant U as 👤 User
    participant W as 🖥️ Web UI
    participant A as ⚡ FastAPI
    participant J as 🔧 Job Runner
    participant P as 🌐 Pinterest
    participant D as 💾 Disk

    U->>W: Enter query
    W->>A: POST /api/scrape
    A->>J: Spawn thread
    A-->>W: { job_id }
    W->>A: GET /api/jobs/:id/events (SSE)
    
    J->>P: Search pins
    P-->>J: Pin metadata
    J-->>W: phase: collect
    J->>P: Fetch details
    J-->>W: phase: details
    J->>D: Download images
    J-->>W: phase: download
    J->>D: Save JSON + CSV
    J-->>W: done: { stats }
    
    W->>A: GET /api/jobs/:id/result
    A-->>W: { pins: [...] }
    W->>U: Render masonry grid
```

<br />

---

🚀 Quick Start

<div align="center">

⚡ One-Command Setup

</div>

<table>
<tr>
<td width="33%" valign="top" align="center">

🐍 Python

<br />

```bash
pip install -r requirements.txt

uvicorn api.server:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

<br />

<sub>Fastest for development</sub>

</td>
<td width="33%" valign="top" align="center">

🐳 Docker

<br />

```bash
docker build -t pin-scraper .

docker run -p 8000:8000 \
  -v $(pwd)/web_output:/app/web_output \
  pin-scraper
```

<br />

<sub>Isolated · production-ready</sub>

</td>
<td width="33%" valign="top" align="center">

☁️ Render

<br />

```
1. Fork this repo
2. Go to render.com
3. New Web Service
4. Connect repo
5. Auto-detects render.yaml
6. Deploy ✓
```

<br />

<sub>Free tier available</sub>

</td>
</tr>
</table>

<br />

<details>
<summary><b>📋 Prerequisites & Manual Setup</b></summary>

<br />

Requirements:

· Python 3.10+
· 512 MB RAM minimum
· ~100 MB disk for output

Step-by-step:

```bash
# 1. Clone
git clone https://github.com/raihan-rifat007/Pinterest-Scraper.git
cd T

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

# 5. Open browser
# → http://localhost:8000
```

Verify installation:

```bash
curl http://localhost:8000/api/health
# → {"ok": true}
```

</details>

<br />

---

🔌 API Reference

<div align="center">

Base URL: https://test-g9v5.onrender.com
Interactive docs: /docs · OpenAPI JSON: /openapi.json

</div>

<br />

🔥 Scrape Endpoints

<table>
<tr>
<th align="left">Method</th>
<th align="left">Endpoint</th>
<th align="left">Description</th>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/POST-10B981?style=flat-square" /></td>
<td><code>/api/scrape</code></td>
<td>Start a scrape job</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/jobs/{id}/events</code></td>
<td>SSE stream — live progress</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/jobs/{id}/result</code></td>
<td>Final result after job completes</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/POST-10B981?style=flat-square" /></td>
<td><code>/api/jobs/{id}/cancel</code></td>
<td>Cancel a running job</td>
</tr>
</table>

<details>
<summary><b>📝 POST /api/scrape — Full Request Body</b></summary>

<br />

```json
{
  "query": "dark academia",
  "mode": "search",
  "limit": 50,
  "download": true,
  "details": true,
  "dedup": false,
  "workers": 4,
  "delay": 1.0,
  "jitter": 0.5,
  "batch_size": 10,
  "min_width": 0,
  "min_height": 0,
  "proxy": ""
}
```

Field Type Default Description
query string — Search term or board URL. Comma-separate for batch.
mode search \| board search Scrape mode
limit int 25 Max pins per query (1–500)
download bool true Download images to disk
details bool true Fetch full pin details
dedup bool false Skip pins seen in previous runs
workers int 4 Concurrent download threads (1–16)
delay float 1.0 Seconds between paginated requests
jitter float 0.5 Random jitter added to delay
batch_size int 10 Save metadata every N pins
min_width int 0 Skip images narrower than this
min_height int 0 Skip images shorter than this
proxy string "" Single proxy or comma-separated pool

</details>

<br />

🖼️ Images & Gallery

<table>
<tr>
<th align="left">Method</th>
<th align="left">Endpoint</th>
<th align="left">Description</th>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/images/{name}</code></td>
<td>Serve a downloaded image</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/gallery</code></td>
<td>All downloaded pins with metadata</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/gallery/export/zip</code></td>
<td>ZIP of all gallery images</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/POST-10B981?style=flat-square" /></td>
<td><code>/api/images/delete</code></td>
<td>Delete images by filename</td>
</tr>
</table>

<br />

📦 Export

<table>
<tr>
<th align="left">Method</th>
<th align="left">Endpoint</th>
<th align="left">Description</th>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/jobs/{id}/export/zip</code></td>
<td>ZIP of job images</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/jobs/{id}/export/xlsx</code></td>
<td>XLSX metadata spreadsheet</td>
</tr>
</table>

<br />

🔍 Suggest & Visual Search

<table>
<tr>
<th align="left">Method</th>
<th align="left">Endpoint</th>
<th align="left">Description</th>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/suggest?q=term</code></td>
<td>Typeahead suggestions</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/visual-search?pin_id=123</code></td>
<td>Related pins by ID</td>
</tr>
</table>

<br />

⏰ Schedules

<table>
<tr>
<th align="left">Method</th>
<th align="left">Endpoint</th>
<th align="left">Description</th>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/GET-3B82F6?style=flat-square" /></td>
<td><code>/api/schedules</code></td>
<td>List all schedules</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/POST-10B981?style=flat-square" /></td>
<td><code>/api/schedules</code></td>
<td>Create a schedule</td>
</tr>
<tr>
<td><img src="https://img.shields.io/badge/DELETE-E60023?style=flat-square" /></td>
<td><code>/api/schedules/{id}</code></td>
<td>Delete a schedule</td>
</tr>
</table>

<br />

📡 SSE Event Types

The /api/jobs/{id}/events stream emits these event types:

Event Payload Description
phase phase, total, message Phase started (collect / details / download)
progress phase, count, total Progress within a phase
query_start query, index, total Batch query started
nothing_new total All pins already exist (dedup hit)
saved json_file, csv_file Metadata saved to disk
done status, total, stats, error Job completed

<br />

💡 Example — cURL

```bash
# Start a scrape
curl -X POST https://pinterestscraperr.onrender.com/api/scrape \
  -H "Content-Type: application/json" \
  -d '{
    "query": "minimal wallpaper",
    "limit": 30,
    "download": true,
    "details": true
  }'

# → {"job_id": "abc123def456"}

# Stream progress (SSE)
curl -N https://pinterestscraperr.onrender.com/api/jobs/abc123def456/events

# Fetch final result
curl https://pinterestscraperr.onrender.com/api/jobs/abc123def456/result
```

<br />

💡 Example — Python

```python
import requests

BASE = "https://test-g9v5.onrender.com"

# 1. Start scrape
job = requests.post(f"{BASE}/api/scrape", json={
    "query": "cyberpunk city",
    "limit": 50,
    "download": True,
}).json()["job_id"]

# 2. Stream events
with requests.get(f"{BASE}/api/jobs/{job}/events", stream=True) as r:
    for line in r.iter_lines():
        if line and line.startswith(b"data: "):
            print(line[6:].decode())

# 3. Get results
pins = requests.get(f"{BASE}/api/jobs/{job}/result").json()["pins"]
print(f"Scraped {len(pins)} pins")
```

<br />

---

⚙️ Configuration

<div align="center">

Everything is stored per-browser in localStorage. No server config file required.

</div>

<br />

📁 Output Structure

Each scrape writes to web_output/:

```text
web_output/
├── {stem}.json          # Full pin metadata array
├── {stem}.csv           # Flat CSV with all columns
├── .seen_pins.json      # Deduplication store (when dedup=true)
├── schedules.json       # Scheduled scrape definitions
└── images/
    ├── {pin_id}.jpg
    ├── {pin_id}.png
    ├── {pin_id}.webp
    └── ...
```

<br />

🔀 Proxy Support

Pass a single proxy or comma-separated pool in the proxy field:

```text
# Single
http://user:pass@host:port

# Pool (rotated round-robin)
http://proxy1:port,http://proxy2:port,http://proxy3:port
```

<br />

🎛️ UI Settings

Setting Default Range Description
Max pins 25 1–500 Pins to fetch per query
Min image width 0 0–10000 Skip images narrower than this
Min image height 0 0–10000 Skip images shorter than this
Concurrent workers 4 1–16 Download parallelization
Delay between pages 1.0s 0–30 Anti rate-limit
Random jitter 0.5s 0–10 Randomized delay
Batch save every N 10 1–100 Metadata checkpoint interval

<br />

---

☁️ Deployment

<div align="center">

☁️ Render — Recommended

</div>

<br />

<table>
<tr>
<td width="50%" valign="top">

✅ One-Click Deploy

https://render.com/images/deploy-to-render-button.svg

The repo ships with render.yaml — Render auto-detects and configures everything.

</td>
<td width="50%" valign="top">

⚙️ Manual Setup

1. Push repo to GitHub
2. Go to render.com → New Web Service
3. Connect your repo
4. Render auto-detects render.yaml
5. Click Deploy ✨

</td>
</tr>
</table>

⚠️ Free tier notice: Render's free plan uses ephemeral storage. Downloaded images are lost on restart. Use a paid plan or mount a persistent disk at /app/web_output.

<br />

🐳 Docker

<details>
<summary><b>Dockerfile</b></summary>

<br />

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

</details>

<details>
<summary><b>docker-compose.yml</b></summary>

<br />

```yaml
version: "3.9"

services:
  scraper:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./web_output:/app/web_output
    environment:
      - PORT=8000
    restart: unless-stopped
```

</details>

```bash
# Build & run
docker build -t pinterest-scraper .
docker run -p 8000:8000 -v $(pwd)/web_output:/app/web_output pinterest-scraper

# Or with compose
docker compose up -d
```

<br />

🖥️ VPS / Bare Metal

```bash
# Install
pip install -r requirements.txt

# Run with uvicorn (production)
uvicorn api.server:app \
  --host 0.0.0.0 \
  --port 80 \
  --workers 1 \
  --log-level warning
```
Recommended: Put Nginx in front for TLS + static caching. Use systemd or supervisor for process management.

<details>
<summary><b>systemd unit example</b></summary>

<br />

```ini
[Unit]
Description=Pinterest Scraper
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/pinterest-scraper
ExecStart=/opt/pinterest-scraper/.venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

</details>

<br />

---

🛠️ Tech Stack

<div align="center">

<table>
<tr>
<td align="center" width="120"><b>Backend</b></td>
<td>
<img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" />
<img src="https://img.shields.io/badge/Uvicorn-499848?style=for-the-badge&logo=gunicorn&logoColor=white" />
<img src="https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white" />
</td>
</tr>
<tr>
<td align="center"><b>Networking</b></td>
<td>
<img src="https://img.shields.io/badge/requests-2B2D30?style=for-the-badge&logo=python&logoColor=white" />
<img src="https://img.shields.io/badge/ThreadPool-FF6B6B?style=for-the-badge" />
<img src="https://img.shields.io/badge/SSE-4B5563?style=for-the-badge" />
</td>
</tr>
<tr>
<td align="center"><b>Export</b></td>
<td>
<img src="https://img.shields.io/badge/openpyxl-217346?style=for-the-badge&logo=microsoft-excel&logoColor=white" />
<img src="https://img.shields.io/badge/ZIP-6B7280?style=for-the-badge" />
<img src="https://img.shields.io/badge/CSV-FFB000?style=for-the-badge" />
</td>
</tr>
<tr>
<td align="center"><b>Frontend</b></td>
<td>
<img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" />
<img src="https://img.shields.io/badge/CSS3-1572B6?style=for-the-badge&logo=css3&logoColor=white" />
<img src="https://img.shields.io/badge/Chart.js-FF6384?style=for-the-badge&logo=chartdotjs&logoColor=white" />
<img src="https://img.shields.io/badge/Bootstrap%20Icons-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white" />
</td>
</tr>
<tr>
<td align="center"><b>Deployment</b></td>
<td>
<img src="https://img.shields.io/badge/Render-46E3B7?style=for-the-badge&logo=render&logoColor=white" />
<img src="https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white" />
<img src="https://img.shields.io/badge/Nginx-009639?style=for-the-badge&logo=nginx&logoColor=white" />
</td>
</tr>
</table>

</div>

<br />

---

📊 Metadata Fields

Every pin object returned by the API contains 25+ fields:

<div align="center">

Category Fields
Identity pin_id · pin_url
Content title · description · alt_text
Media image_url · width · height · aspect_ratio
Engagement saves · repin_count · likes · comments
Creator creator_username · creator_name · creator_profile
Board board_name · board_url
External external_link · domain
Visual dominant_color
Temporal created_at
Video is_video · video_url
Local local_file

</div>

<br />

<details>
<summary><b>📄 Full field reference</b></summary>

<br />

Field Type Description
pin_id string Pinterest pin ID
pin_url string Full Pinterest URL
title string Pin title
description string Pin description
alt_text string Auto-generated alt text
image_url string Highest-resolution image URL
width int Image width in px
height int Image height in px
aspect_ratio float width / height
saves int Total saves
repin_count int Repin count
likes int Like count
comments int Comment count
creator_username string Pinterest username
creator_name string Display name
creator_profile string Profile URL
board_name string Board name
board_url string Board URL
external_link string External link on pin
domain string External link domain
dominant_color string Hex color code
created_at string ISO creation timestamp
is_video bool True if video pin
video_url string Direct MP4 URL (if video)
local_file string Downloaded filename (if saved)

</details>

<br />

---

🗺️ Roadmap

<div align="center">

<table>
<tr>
<th align="center" width="60">Status</th>
<th align="left">Feature</th>
<th align="left">ETA</th>
</tr>
<tr>
<td align="center">✅</td>
<td>Search + board scraping</td>
<td><sub>Shipped</sub></td>
</tr>
<tr>
<td align="center">✅</td>
<td>Premium web UI + dark mode</td>
<td><sub>Shipped</sub></td>
</tr>
<tr>
<td align="center">✅</td>
<td>SSE live progress</td>
<td><sub>Shipped</sub></td>
</tr>
<tr>
<td align="center">✅</td>
<td>ZIP + XLSX export</td>
<td><sub>Shipped</sub></td>
</tr>
<tr>
<td align="center">✅</td>
<td>Scheduled scrapes + collections</td>
<td><sub>Shipped</sub></td>
</tr>
<tr>
<td align="center">🚧</td>
<td>Multi-language SDK (JS · Python · Go)</td>
<td><sub>Q1 2026</sub></td>
</tr>
<tr>
<td align="center">🚧</td>
<td>PostgreSQL backend for persistent storage</td>
<td><sub>Q1 2026</sub></td>
</tr>
<tr>
<td align="center">📋</td>
<td>Webhook notifications on job completion</td>
<td><sub>Q2 2026</sub></td>
</tr>
<tr>
<td align="center">📋</td>
<td>Bulk board scraping via CSV input</td>
<td><sub>Q2 2026</sub></td>
</tr>
<tr>
<td align="center">💡</td>
<td>AI-powered pin description generation</td>
<td><sub>Backlog</sub></td>
</tr>
</table>

</div>

<br />

---

🤝 Contributing

<div align="center">

Contributions, issues, and feature requests are welcome!

</div>

<br />

<table>
<tr>
<td width="33%" align="center">

🍴 Fork

Fork the repository

</td>
<td width="33%" align="center">

🌿 Branch

git checkout -b feat/amazing

</td>
<td width="33%" align="center">

🚀 Push

git push origin feat/amazing

</td>
</tr>
</table>

<br />

```bash
# 1. Fork & clone
git clone https://github.com/YOUR_USERNAME/T.git

# 2. Create feature branch
git checkout -b feat/amazing-feature

# 3. Commit changes
git commit -m "feat: add amazing feature"

# 4. Push
git push origin feat/amazing-feature

# 5. Open a Pull Request
```

<br />

<div align="center">

📏 Commit Convention

Prefix Usage
feat: New feature
fix: Bug fix
docs: Documentation
refactor: Code refactor
perf: Performance
chore: Maintenance

</div>

<br />

---

📈 Star History

<div align="center">

<a href="https://star-history.com/#raihan-rifat007/Pinterest-Scraper &Date">
  <img src="https://api.star-history.com/svg?repos=raihan-rifat007/Pinterest-Scraper&type=Date" alt="Star History Chart" width="600" />
</a>

<br /><br />

If this project helped you, please consider giving it a ⭐

<a href="https://github.com/raihan-rifat007/Pinterest-Scraper/stargazers">
  <img src="https://img.shields.io/github/stars/raihan-rifat007/T?style=for-the-badge&logo=github&color=E60023&labelColor=000000" alt="Star this repo" />
</a>

</div>

<br />

---

⚖️ License

<div align="center">

MIT License

Copyright © 2026 Raihan Rifat

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files, to deal in the Software without restriction — including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies.

See the LICENSE file for full text.

</div>

<br />

---

⚠️ Disclaimer

<div align="center">

<table>
<tr>
<td align="center">
<br />
<b>⚖️ Please read before use</b>
<br /><br />
This project is intended for <b>personal, educational, and research use only</b>.<br />
Respect Pinterest's <a href="https://policy.pinterest.com/en/terms-of-service">Terms of Service</a> and <code>robots.txt</code>.<br />
Do not use at scale or for commercial scraping without explicit permission.
<br /><br />
</td>
</tr>
</table>

</div>

<br />

---

<div align="center">

💝 Credits

Built with <img src="https://img.shields.io/badge/-%E2%9D%A4-E60023?style=flat-square" /> using Python · FastAPI · Vanilla JS

<br />

<a href="https://github.com/raihan-rifat007/Pinterest-Scraper/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=raihan-rifat007/Pinterest-Scraper" alt="Contributors" />
</a>

<br /><br />

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=0,2,2,5,30&height=120&section=footer&text=Thank%20you%20for%20visiting&fontSize=20&fontColor=ffffff&animation=fadeIn" width="100%" />

</div>
