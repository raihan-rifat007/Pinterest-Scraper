import asyncio
import uuid
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum
import json


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPhase(str, Enum):
    COLLECT = "collect"
    DETAILS = "details"
    DOWNLOAD = "download"
    COMPLETED = "completed"


@dataclass
class JobProgress:
    job_id: str
    phase: str
    progress: int
    total: int
    current: int
    timestamp: str


class JobManager:
    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.results: Dict[str, List[Dict[str, Any]]] = {}
        self.stats: Dict[str, Dict[str, Any]] = {}

    def create_job(self, request_data: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        
        self.jobs[job_id] = {
            "id": job_id,
            "status": JobStatus.PENDING,
            "phase": JobPhase.COLLECT,
            "created_at": datetime.now().isoformat(),
            "request": request_data,
            "progress": 0,
            "total": 0,
            "current": 0,
            "stats": {
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
            },
            "events": [],
        }
        
        return job_id

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)

    def update_progress(
        self,
        job_id: str,
        phase: str,
        progress: int,
        total: int = 0,
        current: int = 0,
    ):
        if job_id not in self.jobs:
            return

        job = self.jobs[job_id]
        job["phase"] = phase
        job["progress"] = min(progress, 100)
        job["total"] = total
        job["current"] = current
        job["status"] = JobStatus.RUNNING

        event = {
            "timestamp": datetime.now().isoformat(),
            "phase": phase,
            "progress": progress,
            "total": total,
            "current": current,
        }
        job["events"].append(event)

    def set_result(self, job_id: str, pins: List[Dict[str, Any]], stats: Dict[str, Any]):
        if job_id not in self.jobs:
            return

        self.results[job_id] = pins
        self.stats[job_id] = stats
        
        job = self.jobs[job_id]
        job["status"] = JobStatus.COMPLETED
        job["phase"] = JobPhase.COMPLETED
        job["progress"] = 100
        job["stats"] = stats
        job["completed_at"] = datetime.now().isoformat()

    def set_error(self, job_id: str, error: str):
        if job_id not in self.jobs:
            return

        job = self.jobs[job_id]
        job["status"] = JobStatus.FAILED
        job["error"] = error
        job["completed_at"] = datetime.now().isoformat()

    def cancel_job(self, job_id: str):
        if job_id not in self.jobs:
            return

        job = self.jobs[job_id]
        job["status"] = JobStatus.CANCELLED
        job["completed_at"] = datetime.now().isoformat()

    def get_result(self, job_id: str) -> Optional[Dict[str, Any]]:
        if job_id not in self.jobs:
            return None

        job = self.jobs[job_id]
        pins = self.results.get(job_id, [])
        stats = self.stats.get(job_id, {})

        return {
            "job_id": job_id,
            "status": job["status"],
            "pins": pins,
            "stats": stats,
            "error": job.get("error"),
        }

    def get_events(self, job_id: str) -> List[Dict[str, Any]]:
        if job_id not in self.jobs:
            return []

        return self.jobs[job_id].get("events", [])

    def cleanup_old_jobs(self, keep_hours: int = 24):
        from datetime import timedelta

        cutoff_time = datetime.now() - timedelta(hours=keep_hours)

        jobs_to_delete = []
        
        for job_id, job in self.jobs.items():
            try:
                created = datetime.fromisoformat(job["created_at"])
                if created < cutoff_time:
                    jobs_to_delete.append(job_id)
            except:
                pass

        for job_id in jobs_to_delete:
            self.jobs.pop(job_id, None)
            self.results.pop(job_id, None)
            self.stats.pop(job_id, None)

        return len(jobs_to_delete)

    def get_stats(self) -> Dict[str, Any]:
        total_jobs = len(self.jobs)
        completed = sum(1 for j in self.jobs.values() if j["status"] == JobStatus.COMPLETED)
        failed = sum(1 for j in self.jobs.values() if j["status"] == JobStatus.FAILED)
        running = sum(1 for j in self.jobs.values() if j["status"] == JobStatus.RUNNING)

        return {
            "total_jobs": total_jobs,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": total_jobs - completed - failed - running,
        }


job_manager = JobManager()
