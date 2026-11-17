"""Small HTTP layer: polite, retrying, disk-cached. Standard library only."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "zwiebelturm-karte/1.0"
_last_call: dict[str, float] = {}


class HttpError(Exception):
    def __init__(self, status: int, url: str, body: str = "", retry_after: float | None = None):
        super().__init__(f"HTTP {status} for {url[:120]} {body[:300]}")
        self.status = status
        self.body = body
        self.retry_after = retry_after


def fetch(url: str, data: dict | None = None, timeout: int = 180) -> bytes:
    """One HTTP request (POST when `data` is given). Tests replace this function."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip",
        "Accept": "application/json, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except urllib.error.HTTPError as e:
        ra = e.headers.get("Retry-After") if e.headers else None
        raise HttpError(e.code, url, e.read().decode("utf-8", "replace"),
                        float(ra) if ra and ra.isdigit() else None) from None


def fetch_retry(url: str, data: dict | None = None, timeout: int = 180,
                tries: int = 5, min_interval: float = 0.0) -> bytes:
    """`fetch` with a per-host minimum interval and backoff on 429/5xx/network errors."""
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(tries):
        wait = _last_call.get(host, 0) + min_interval - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            _last_call[host] = time.time()
            return fetch(url, data, timeout)
        except HttpError as e:
            if e.status not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            # a server that names its own waiting time (Wikimedia: a few seconds) is taken at its word
            delay = min((e.retry_after + 2) * (attempt + 1), 90) if e.retry_after else 15 * 2 ** attempt
            if not e.retry_after:
                print(f"    HTTP {e.status} from {host}, retry in {delay}s")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if attempt == tries - 1:
                raise
            delay = 15 * 2 ** attempt
            print(f"    network error from {host} ({e}), retry in {delay}s")
        time.sleep(delay)
    raise RuntimeError("unreachable")


def read_gz_json(path: Path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def write_gz_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    tmp.replace(path)


def cached_json(cache_dir: Path, url: str, data: dict | None = None,
                min_interval: float = 0.3, timeout: int = 180, tries: int = 12):
    """GET/POST returning JSON, cached on disk by request."""
    key = hashlib.sha1((url + "|" + json.dumps(data, sort_keys=True)).encode()).hexdigest()[:20]
    path = cache_dir / f"{key}.json.gz"
    if path.exists():
        return read_gz_json(path)
    obj = json.loads(fetch_retry(url, data, timeout=timeout, tries=tries, min_interval=min_interval))
    write_gz_json(path, obj)
    return obj


class Store:
    """A small persistent dictionary (one gzip JSON file): remembers every single item ever
    fetched, so changing a radius or adding a region only downloads what is new."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = read_gz_json(path) if path.exists() else {}

    def missing(self, keys) -> list:
        return [k for k in dict.fromkeys(keys) if k not in self.data]

    def save(self) -> None:
        write_gz_json(self.path, self.data)
