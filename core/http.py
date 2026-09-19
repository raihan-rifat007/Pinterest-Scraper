import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Optional
import random


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
]


class ProxyRotator:
    def __init__(self, proxy_list: Optional[List[str]] = None):
        self.proxies = proxy_list or []
        self.current_index = 0

    def get_next(self) -> Optional[Dict[str, str]]:
        if not self.proxies:
            return None
        
        proxy = self.proxies[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.proxies)
        
        return {
            "http": proxy,
            "https": proxy,
        }

    def get_random(self) -> Optional[Dict[str, str]]:
        if not self.proxies:
            return None
        
        proxy = random.choice(self.proxies)
        return {
            "http": proxy,
            "https": proxy,
        }


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def build_session(proxy_pool: Optional[List[str]] = None) -> requests.Session:
    session = requests.Session()
    
    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        method_whitelist=["HEAD", "GET", "OPTIONS", "POST"],
        backoff_factor=1
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "User-Agent": get_random_user_agent(),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    
    if proxy_pool:
        rotator = ProxyRotator(proxy_pool)
        original_request = session.request
        
        def request_with_proxy(*args, **kwargs):
            kwargs["proxies"] = rotator.get_random()
            return original_request(*args, **kwargs)
        
        session.request = request_with_proxy
    
    return session
