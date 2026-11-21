"""Local preview and review server:  python serve.py   → http://localhost:8000

Besides the static site it offers local endpoints (only for you, they write into data/):
  GET  /api/ping       the map shows the "Misclassified?" buttons as owner buttons when this answers
  POST /api/quick      {"id","roof","previous","name","lon","lat","img"}: instant change from the map card →
                         data/overrides.csv (source manual-quick) + data/quick-changes.csv (to be checked)
  GET  /api/quick      quick changes not yet checked (the map re-applies them after a reload)
  GET  /api/queue?mode=reports|quick   review queue for label.html?queue=reports|quick
                         (reports: most reported first, from data/reports.csv; see tools/fetch_reports.py)
For the review page (http://localhost:8000/label.html?review):
  GET  /api/reviewed   ids you have already decided
  POST /api/review     {"id": "way/123", "roof": "onion", "name": "..."}  → saved to
                         data/labels-reviewed.csv   (training labels, every class)
                         data/overrides.csv         (only roof types the map knows; the map changes
                                                     with the next python build.py)
Nothing is changed by predictions alone, only by a review click.
"""
import csv
import datetime
import functools
import http.server
import io
import json
import pathlib
import re
import threading
import urllib.parse
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
SITE = ROOT / "site"
DATA = ROOT / "data"
PORT = 8000
CLASSES = {"onion", "onion_double", "welsch", "dome", "other", "no_tower", "skip"}
MAP_CLASSES = {"onion", "onion_double", "welsch", "dome", "other"}   # roof types of the map (classify.CATEGORIES)
SOURCE = "yolov8-cls-reviewed"
QUICK_SOURCE = "manual-quick"      # instant change from the map; replaced by the next review click
QUICK_FILE = "quick-changes.csv"
QUICK_HEAD = ["osm_id", "roof", "previous", "name", "lon", "lat", "img", "time"]
ID_RE = re.compile(r"^(node|way|relation)/\d+$")
_lock = threading.Lock()


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8-sig", newline="") if path.exists() else ""


def _write(path: pathlib.Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    tmp.replace(path)


def _csv_line(fields, nl: str) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator=nl).writerow(fields)
    return buf.getvalue()


def _first_field(line: str) -> str:
    try:
        return next(csv.reader([line]))[0]
    except (StopIteration, IndexError):
        return ""


def save_review(osm_id: str, roof: str, name: str = "") -> dict:
    """Upsert one reviewed label. Returns what was written."""
    if not ID_RE.match(osm_id or "") or roof not in CLASSES:
        raise ValueError("bad id or class")
    name = (name or "")[:200].replace("\r", " ").replace("\n", " ")
    out = {"labels": True, "overrides": "none"}
    with _lock:
        # 1) training labels: every class, one row per church
        path = DATA / "labels-reviewed.csv"
        text = _read(path)
        nl = "\r\n" if "\r\n" in text else "\n"
        rows = [r for r in csv.reader(io.StringIO(text)) if r]
        rows = [r for r in rows[1:] if r[0] != osm_id] if rows and rows[0][:1] == ["osm_id"] else [r for r in rows if r[0] != osm_id]
        rows.append([osm_id, roof, SOURCE, name])
        DATA.mkdir(exist_ok=True)
        _write(path, _csv_line(["osm_id", "roof", "source", "note"], nl) + "".join(_csv_line(r, nl) for r in rows))

        # 2) map override: only for roof types the map knows; never touches hand-written lines
        path = DATA / "overrides.csv"
        text = _read(path)
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines(keepends=True)
        kept, manual = [], False
        for ln in lines:
            if ln.strip() and not ln.startswith("#") and _first_field(ln) == osm_id:
                if SOURCE in ln or QUICK_SOURCE in ln:
                    continue                                  # an earlier review or quick change of the same church: replaced below
                manual = True                                 # a hand-written override wins
            kept.append(ln)
        if kept and not kept[-1].endswith(("\n", "\r")):
            kept[-1] += nl
        if manual:
            out["overrides"] = "kept manual override"
        elif roof in MAP_CLASSES:
            kept.append(_csv_line([osm_id, roof, SOURCE, name], nl))
            out["overrides"] = "written"
        elif len(kept) != len(lines):
            out["overrides"] = "removed"
        if path.exists() or roof in MAP_CLASSES:
            _write(path, "".join(kept))
        _drop_quick(osm_id)                                   # decided now: no longer "to check"
    return out


def _read_table(name: str) -> list[dict]:
    return [r for r in csv.DictReader(io.StringIO(_read(DATA / name))) if r.get("osm_id")]


def _write_table(name: str, head: list[str], rows: list[dict]) -> None:
    DATA.mkdir(exist_ok=True)
    _write(DATA / name, _csv_line(head, "\r\n") + "".join(_csv_line([r.get(h, "") for h in head], "\r\n") for r in rows))


def _drop_quick(osm_id: str) -> None:
    rows = _read_table(QUICK_FILE)
    kept = [r for r in rows if r["osm_id"] != osm_id]
    if len(kept) != len(rows):
        _write_table(QUICK_FILE, QUICK_HEAD, kept)


def save_quick(d: dict) -> dict:
    """Instant change from the map card. A hand-written override of the same church is never replaced."""
    osm_id, roof = d.get("id"), d.get("roof")
    if not ID_RE.match(osm_id or "") or roof not in MAP_CLASSES:
        raise ValueError("bad id or class")
    clean = lambda v, n: str(v or "")[:n].replace("\r", " ").replace("\n", " ")
    try:
        lon, lat = int(d.get("lon")), int(d.get("lat"))
    except (TypeError, ValueError):
        raise ValueError("bad coordinates")
    img = clean(d.get("img"), 500)
    if img and not img.startswith("https://"):
        img = ""
    with _lock:
        path = DATA / "overrides.csv"
        text = _read(path)
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines(keepends=True)
        kept = []
        for ln in lines:
            if ln.strip() and not ln.startswith("#") and _first_field(ln) == osm_id:
                if SOURCE in ln or QUICK_SOURCE in ln:
                    continue
                raise ValueError("a hand-written override for this church exists in data/overrides.csv")
            kept.append(ln)
        if kept and not kept[-1].endswith(("\n", "\r")):
            kept[-1] += nl
        kept.append(_csv_line([osm_id, roof, QUICK_SOURCE, clean(d.get("name"), 200)], nl))
        _write(path, "".join(kept))
        rows = _read_table(QUICK_FILE)
        old = next((r for r in rows if r["osm_id"] == osm_id), None)
        previous = old["previous"] if old else clean(d.get("previous"), 20)   # keep the very first value
        rows = [r for r in rows if r["osm_id"] != osm_id]
        rows.append({"osm_id": osm_id, "roof": roof, "previous": previous, "name": clean(d.get("name"), 200),
                     "lon": lon, "lat": lat, "img": img, "time": datetime.datetime.now().isoformat(timespec="seconds")})
        _write_table(QUICK_FILE, QUICK_HEAD, rows)
    return {"saved": True}


def queue(mode: str) -> list[dict]:
    """Rows for label.html?queue=…  (same fields as predictions.json: id, name, img, pred, conf) plus count/current."""
    done = set(reviewed_ids())
    out = []
    if mode == "quick":
        for r in reversed(_read_table(QUICK_FILE)):
            if r["osm_id"] not in done:
                out.append({"id": r["osm_id"], "name": r["name"], "img": r["img"], "pred": r["roof"], "conf": 1,
                            "count": 1, "current": r["previous"], "kind": "quick"})
    elif mode == "reports":
        for r in _read_table("reports.csv"):
            if r["osm_id"] not in done:
                out.append({"id": r["osm_id"], "name": r.get("name", ""), "img": r.get("img", ""), "pred": r["proposed"],
                            "conf": 1, "count": int(r.get("count") or 1), "current": r.get("current", ""), "kind": "reports"})
        out.sort(key=lambda x: -x["count"])
    return out


def reviewed_ids() -> list[str]:
    ids = set()
    for name in ("labels.csv", "labels-reviewed.csv"):
        for r in csv.DictReader(io.StringIO(_read(DATA / name))):
            if r.get("osm_id"):
                ids.add(r["osm_id"])
    return sorted(ids)


class Handler(http.server.SimpleHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")           # after a rebuild the browser must not show old points.bin / manifest
        super().end_headers()

    def _local_origin(self) -> bool:
        origin = self.headers.get("Origin")                   # blocks other websites from posting to localhost
        return origin is None or origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        if path == "/api/reviewed":
            return self._json(reviewed_ids())
        if path == "/api/ping":
            return self._json({"owner": True})
        if path == "/api/quick":
            return self._json([{"id": r["osm_id"], "roof": r["roof"], "lon": int(r["lon"]), "lat": int(r["lat"])}
                               for r in _read_table(QUICK_FILE) if r["lon"].lstrip("-").isdigit() and r["lat"].lstrip("-").isdigit()])
        if path == "/api/queue":
            mode = urllib.parse.parse_qs(qs).get("mode", [""])[0]
            return self._json(queue(mode) if mode in ("quick", "reports") else [])
        super().do_GET()

    def do_POST(self):
        route = self.path.split("?")[0]
        if route not in ("/api/review", "/api/quick"):
            return self._json({"error": "not found"}, 404)
        if not self._local_origin():
            return self._json({"error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n < 10_000:
                raise ValueError("bad length")
            d = json.loads(self.rfile.read(n))
            if route == "/api/quick":
                return self._json(save_quick(d))
            return self._json(save_review(d.get("id"), d.get("roof"), d.get("name", "")))
        except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/"):
            super().log_message(fmt, *args)


def main():
    handler = functools.partial(Handler, directory=str(SITE))
    print(f"Serving the map at http://localhost:{PORT}  (Ctrl+C to stop)")
    print(f"Review the model's predictions: http://localhost:{PORT}/label.html?review")
    print(f"Check your quick changes:       http://localhost:{PORT}/label.html?queue=quick")
    print(f"Check reports (most first):     http://localhost:{PORT}/label.html?queue=reports")
    webbrowser.open(f"http://localhost:{PORT}")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
