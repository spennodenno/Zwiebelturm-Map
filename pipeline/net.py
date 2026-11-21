"""Small HTTP layer: polite, retrying, disk-cached. Standard library only."""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
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
    """A small persistent dictionary: remembers every single item ever fetched, so changing a
    radius or adding a region only downloads what is new.

    On disk it is an append-only gzip JSON-lines file (`*.jsonl.gz`): `save()` appends only the keys
    that are new since the last save instead of rewriting the whole file, which matters once a store
    holds tens of thousands of articles. One copy per file stays in memory for the whole run.
    A store written by the earlier version (`*.json.gz`, one dictionary) is read once and converted."""

    _open: dict[str, "Store"] = {}

    def __new__(cls, path: Path):
        key = str(path)
        if key not in cls._open:
            cls._open[key] = super().__new__(cls)
        return cls._open[key]

    def __init__(self, path: Path):
        if getattr(self, "_ready", False):
            return
        self._ready = True
        old = Path(path)
        self.path = old.with_name(old.name.replace(".json.gz", ".jsonl.gz"))
        self.data: dict = {}
        if self.path.exists():
            if not self._read_lines():                   # damaged tail: rewrite what could be read
                tmp = self.path.with_suffix(self.path.suffix + ".tmp")
                with gzip.open(tmp, "wt", encoding="utf-8") as f:
                    for k, v in self.data.items():
                        f.write(json.dumps([k, v], ensure_ascii=False, separators=(",", ":")) + "\n")
                tmp.replace(self.path)
        elif old.exists() and old != self.path:
            self.data = read_gz_json(old)               # one-time conversion of the old format
            self._saved: set = set()
            self.save()
        self._saved = set(self.data)

    def _read_lines(self) -> bool:
        """Loads the file; False when it ends in a damaged gzip block."""
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as f:
                for line in f:
                    try:
                        k, v = json.loads(line)
                    except ValueError:
                        continue                         # a line cut off by a crash
                    self.data[k] = v
        except (EOFError, OSError, zlib.error):
            return False                                 # the last gzip block was cut off by a crash
        return True

    def missing(self, keys) -> list:
        return [k for k in dict.fromkeys(keys) if k not in self.data]

    def save(self) -> None:
        new = [k for k in self.data if k not in self._saved]
        if not new:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self.path, "at", encoding="utf-8") as f:
            for k in new:
                f.write(json.dumps([k, self.data[k]], ensure_ascii=False, separators=(",", ":")) + "\n")
        self._saved.update(new)
