import asyncio
import os
from pathlib import Path
from datetime import datetime
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .models import ScrapeRequest, ScrapeResponse, JobResultResponse, HealthResponse
from .jobs import job_manager, JobStatus, JobPhase
from core.scraper import PinterestScraper
from core.downloader import download_all
from core.dedupe import DedupeStore
from core.storage import StorageManager
from core.http import build_session


BASE_DIR = Path(__file__).parent.parent
STATIC_DIR = BASE_DIR / "webui"
DOWNLOADS_DIR = BASE_DIR / "downloads"
STORAGE_DIR = BASE_DIR / "storage"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Pinterest Scraper API",
    description="High-performance Pinterest content scraper",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = STATIC_DIR / "pinterest.html"
    if index_file.exists():
        return index_file
    return {"error": "UI not found"}


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/scrape", response_model=ScrapeResponse)
async def start_scrape(request: ScrapeRequest, background_tasks: BackgroundTasks):
    job_id = job_manager.create_job(request.dict())
    background_tasks.add_task(scrape_worker, job_id)
    return {"job_id": job_id}


async def scrape_worker(job_id: str):
    try:
        job = job_manager.get_job(job_id)
        if not job:
            return

        request_data = job["request"]
        proxy_list = request_data.get("proxy", "").split(",") if request_data.get("proxy") else None
        
        session = build_session(proxy_pool=proxy_list)
        scraper = PinterestScraper(
            proxy_pool=proxy_list,
            delay=request_data.get("delay", 1.0),
            jitter=request_data.get("jitter", 0.5),
        )

        query = request_data.get("query")
        mode = request_data.get("mode", "search")
        limit = request_data.get("limit", 25)
        download = request_data.get("download", True)
        dedup_enabled = request_data.get("dedup", False)

        job_manager.update_progress(job_id, JobPhase.COLLECT, 0, limit, 0)

        if mode == "board":
            pins = scraper.get_board_pins(query, limit)
        else:
            pins = scraper.search(query, limit)

        job_manager.update_progress(job_id, JobPhase.COLLECT, 50, limit, len(pins))

        if dedup_enabled:
            dedup = DedupeStore(f".dedup_{job_id}.json")
            pins, skipped = dedup.deduplicate_pins(pins)

        job_manager.update_progress(job_id, JobPhase.DETAILS, 60, limit, len(pins))

        if request_data.get("details", True):
            for i, pin in enumerate(pins):
                job_manager.update_progress(job_id, JobPhase.DETAILS, 60 + (20 * (i / len(pins))), limit, i)

        job_manager.update_progress(job_id, JobPhase.DOWNLOAD, 80, limit, 0)

        stats = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "total_size": 0,
        }

        if download and pins:
            job_downloads_dir = DOWNLOADS_DIR / job_id
            download_stats = download_all(session, pins, str(job_downloads_dir), request_data.get("workers", 4))
            stats.update(download_stats)

        job_manager.update_progress(job_id, JobPhase.DOWNLOAD, 99, limit, len(pins))

        job_manager.set_result(job_id, pins, stats)

    except Exception as e:
        print(f"Error in scrape worker: {str(e)}")
        job_manager.set_error(job_id, str(e))


@app.get("/api/jobs/{job_id}/events")
async def get_job_events(job_id: str):
    async def event_generator() -> AsyncGenerator[str, None]:
        previous_count = 0
        
        while True:
            job = job_manager.get_job(job_id)
            
            if not job:
                yield f"data: {{'error': 'Job not found'}}\n\n"
                break

            current_count = len(job.get("events", []))
            
            if current_count > previous_count:
                for event in job["events"][previous_count:]:
                    yield f"data: {str(event).replace(\"'\", '\"')}\n\n"
                previous_count = current_count

            if job["status"] != JobStatus.RUNNING:
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(job_id: str):
    result = job_manager.get_result(job_id)
    
    if not result:
        raise HTTPException(status_code=404, detail="Job not found")

    return result


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job_manager.cancel_job(job_id)
    
    return {"status": "cancelled", "job_id": job_id}


@app.get("/api/jobs/{job_id}/download/zip")
async def download_zip(job_id: str):
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    downloads_path = DOWNLOADS_DIR / job_id
    
    if not downloads_path.exists():
        raise HTTPException(status_code=404, detail="Downloads not found")

    storage = StorageManager(str(STORAGE_DIR))
    pins = job_manager.results.get(job_id, [])
    
    zip_path = storage.create_zip(
        str(downloads_path),
        f"{job_id}.zip",
        include_metadata=True,
        metadata={"query": job["request"].get("query"), "pins": pins},
    )

    if not zip_path:
        raise HTTPException(status_code=500, detail="Failed to create ZIP")

    return FileResponse(zip_path, filename=f"pins_{job_id}.zip")


@app.get("/api/jobs/{job_id}/download/xlsx")
async def download_xlsx(job_id: str):
    job = job_manager.get_job(job_id)
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    storage = StorageManager(str(STORAGE_DIR))
    pins = job_manager.results.get(job_id, [])

    if not pins:
        raise HTTPException(status_code=404, detail="No results to export")

    xlsx_path = storage.save_xlsx(pins, f"{job_id}.xlsx")

    if not xlsx_path:
        raise HTTPException(status_code=500, detail="Failed to create XLSX")

    return FileResponse(xlsx_path, filename=f"pins_{job_id}.xlsx")


@app.get("/api/stats")
async def get_stats():
    return job_manager.get_stats()


def run_server(host: str = "0.0.0.0", port: int = 8080):
    import uvicorn
    
    uvicorn.run(app, host=host, port=port)
