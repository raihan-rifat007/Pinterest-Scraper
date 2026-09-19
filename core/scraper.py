import json
import time
from typing import List, Dict, Any, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .http import build_session


class PinterestScraper:
    def __init__(self, proxy_pool: Optional[List[str]] = None, delay: float = 1.0, jitter: float = 0.5):
        self.session = build_session(proxy_pool)
        self.base_url = "https://www.pinterest.com"
        self.delay = delay
        self.jitter = jitter
        self.current_proxy_index = 0

    def _apply_delay(self):
        import random
        delay = self.delay + (random.random() * self.jitter)
        time.sleep(delay)

    def search(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        results = []
        cursor = None
        
        while len(results) < limit:
            try:
                params = {
                    "q": query,
                    "scope": "pins",
                    "rs": "typed",
                }
                if cursor:
                    params["cursor"] = cursor

                response = self.session.get(
                    f"{self.base_url}/search/pins/",
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                
                if "data" not in data or not data["data"]:
                    break

                for pin in data["data"]:
                    if len(results) >= limit:
                        break
                    
                    pin_data = self._extract_pin_data(pin)
                    if pin_data:
                        results.append(pin_data)

                if "bookmark" in data:
                    cursor = data["bookmark"]
                else:
                    break

                self._apply_delay()
                
            except Exception as e:
                print(f"Error during search: {str(e)}")
                break

        return results[:limit]

    def get_board_pins(self, board_url: str, limit: int = 25) -> List[Dict[str, Any]]:
        results = []
        cursor = None

        try:
            parts = board_url.strip("/").split("/")
            if "pinterest.com" in board_url:
                username = parts[-2]
                board_name = parts[-1]
            else:
                username = parts[0]
                board_name = parts[1]

            while len(results) < limit:
                params = {
                    "username": username,
                    "board_name": board_name,
                }
                if cursor:
                    params["cursor"] = cursor

                response = self.session.get(
                    f"{self.base_url}/user/{username}/board/{board_name}/",
                    params=params,
                    timeout=30
                )
                response.raise_for_status()
                
                data = response.json()
                
                if "data" not in data or not data["data"]:
                    break

                for pin in data["data"]:
                    if len(results) >= limit:
                        break
                    
                    pin_data = self._extract_pin_data(pin)
                    if pin_data:
                        results.append(pin_data)

                if "bookmark" in data:
                    cursor = data["bookmark"]
                else:
                    break

                self._apply_delay()
                
        except Exception as e:
            print(f"Error fetching board pins: {str(e)}")

        return results[:limit]

    def _extract_pin_data(self, pin: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            pin_id = pin.get("id")
            if not pin_id:
                return None

            media = pin.get("media", {})
            image_url = None
            
            if "image" in media:
                image_url = media["image"].get("orig", {}).get("url")
            
            if not image_url and "images" in media:
                images = media.get("images", {})
                for size in ["orig", "236x", "474x"]:
                    if size in images:
                        image_url = images[size].get("url")
                        if image_url:
                            break

            pin_type = "video" if media.get("type") == "video" else "image"
            duration = media.get("video_duration") if pin_type == "video" else None

            return {
                "id": pin_id,
                "url": f"https://pinterest.com/pin/{pin_id}/",
                "title": pin.get("title", ""),
                "description": pin.get("description", ""),
                "image_url": image_url,
                "thumb": image_url,
                "type": pin_type,
                "duration": duration,
                "created_at": pin.get("created_at"),
            }
        except Exception as e:
            print(f"Error extracting pin data: {str(e)}")
            return None

    def get_pin_details(self, pin_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.session.get(
                f"{self.base_url}/pin/{pin_id}/",
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            if "data" in data:
                return self._extract_pin_data(data["data"])
            
            return None
        except Exception as e:
            print(f"Error fetching pin details: {str(e)}")
            return None

    def get_related_pins(self, pin_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        results = []
        
        try:
            response = self.session.get(
                f"{self.base_url}/pin/{pin_id}/related/",
                params={"limit": limit},
                timeout=30
            )
            response.raise_for_status()
            
            data = response.json()
            if "data" in data:
                for pin in data["data"][:limit]:
                    pin_data = self._extract_pin_data(pin)
                    if pin_data:
                        results.append(pin_data)
            
            return results
        except Exception as e:
            print(f"Error fetching related pins: {str(e)}")
            return []


def search_pins(query: str, limit: int = 25, proxy_pool: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    scraper = PinterestScraper(proxy_pool=proxy_pool)
    return scraper.search(query, limit)


def board_pins(board_url: str, limit: int = 25, proxy_pool: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    scraper = PinterestScraper(proxy_pool=proxy_pool)
    return scraper.get_board_pins(board_url, limit)
