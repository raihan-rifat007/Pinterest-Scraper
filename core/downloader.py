import os
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class FileDownloader:
    def __init__(self, session: requests.Session, output_dir: str, workers: int = 4):
        self.session = session
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.workers = min(workers, 16)
        self.stats = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "total_size": 0,
        }

    def download_file(self, url: str, filename: str) -> bool:
        if not url or not filename:
            return False

        filepath = self.output_dir / filename

        if filepath.exists():
            self.stats["skipped"] += 1
            return True

        try:
            response = self.session.get(url, timeout=30, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            self.stats["downloaded"] += 1
            self.stats["total_size"] += total_size
            return True

        except Exception as e:
            print(f"Error downloading {url}: {str(e)}")
            self.stats["failed"] += 1
            if filepath.exists():
                filepath.unlink()
            return False

    def download_batch(
        self,
        items: List[Dict[str, Any]],
        url_key: str = "image_url",
        name_key: str = "id",
        callback: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        def download_item(item):
            url = item.get(url_key)
            name = item.get(name_key, "")
            
            if not url or not name:
                return False

            ext = self._get_extension(url)
            filename = f"{name}{ext}"
            
            success = self.download_file(url, filename)
            
            if callback:
                callback(item, success)
            
            return success

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(download_item, item) for item in items]
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Download task error: {str(e)}")

        return self.stats

    def _get_extension(self, url: str) -> str:
        try:
            path = url.split("?")[0]
            if "." in path:
                ext = "." + path.split(".")[-1].lower()
                if ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]:
                    return ext
        except:
            pass
        return ".jpg"


def download_all(
    session: requests.Session,
    pins: List[Dict[str, Any]],
    output_dir: str = "downloads",
    workers: int = 4,
    callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    downloader = FileDownloader(session, output_dir, workers)
    return downloader.download_batch(pins, callback=callback)
