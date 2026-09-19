from __future__ import annotations

import json
import random
import re
import time

import requests

from .config import ACCEPT_LANGS, BASE, REFERERS, USER_AGENTS


def browser_headers(referer: str | None = None) -> dict:
    h = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": random.choice(ACCEPT_LANGS),
    }
    if referer:
        h["Referer"] = referer
    elif random.random() < 0.5:
        h["Referer"] = random.choice(REFERERS)
    return h


def polite_sleep(base: float, jitter: float = 0.5) -> None:
    time.sleep(max(0.0, base + random.uniform(0, jitter)))


def build_session(proxy_pool: list[str] | None = None) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/javascript, */*, q=0.01",
        "Accept-Language": "en-US,en;q=0.9",
        "X-Requested-With": "XMLHttpRequest",
        "X-Pinterest-AppState": "active",
    })
    s.proxies_pool = proxy_pool or []
    try:
        home = s.get(
            f"{BASE}/", timeout=15,
            headers=browser_headers(referer="https://www.pinterest.com/"),
            proxies=_pick_proxies(s),
        )
        m = re.search(r'"appVersion":"([^"]+)"', home.text)
        if m:
            s.headers["X-APP-VERSION"] = m.group(1)
    except requests.RequestException:
        pass
    return s


def _pick_proxies(session: requests.Session) -> dict | None:
    pool = getattr(session, "proxies_pool", [])
    if pool:
        p = random.choice(pool)
        return {"http": p, "https": p}
    return None


def api_get(
    session: requests.Session,
    url: str,
    params: dict,
    max_retries: int = 3,
    headers: dict | None = None,
    timeout: int = 20,
) -> dict | None:
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        merged = {**browser_headers(), **(headers or {})}
        try:
            r = session.get(
                url, params=params, timeout=timeout,
                headers=merged, proxies=_pick_proxies(session),
            )
        except requests.RequestException as e:
            print(f"  network error: {e}")
            time.sleep(backoff)
            backoff *= 2
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                print("  response is not JSON (possibly blocked)")
                return None
        if r.status_code == 429:
            wait = backoff + random.uniform(2, 5)
            print(f"  HTTP 429 rate-limited — cooling down {wait:.0f}s")
            time.sleep(wait)
            backoff *= 2
            continue
        if r.status_code in (401, 403) or r.status_code >= 500:
            print(f"  HTTP {r.status_code}, retry {attempt}/{max_retries} in {backoff:.0f}s")
            time.sleep(backoff)
            backoff *= 2
            continue
        print(f"  HTTP {r.status_code} — giving up")
        return None
    return None


def api_data(
    session: requests.Session,
    url: str,
    options: dict,
    source_url: str,
    handler: str = "www/[username].js",
    referer: str | None = None,
) -> tuple[object, str | None]:
    params = {
        "source_url": source_url,
        "data": json.dumps({"options": options, "context": {}}),
    }
    headers = {
        "X-Pinterest-PWS-Handler": handler,
        "Referer": referer or f"{BASE}{source_url}",
    }
    payload = api_get(session, url, params, headers=headers)
    if not payload:
        return None, None
    rr = payload.get("resource_response", {})
    bookmark = rr.get("bookmark") or None
    if bookmark in ("", "-end-"):
        bookmark = None
    return rr.get("data"), bookmark
