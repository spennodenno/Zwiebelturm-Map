"""Local preview and review server:  python serve.py   → http://localhost:8000

Besides the static site it offers two local endpoints for the review page
(http://localhost:8000/label.html?review):
  GET  /api/reviewed   ids you have already decided
  POST /api/review     {"id": "way/123", "roof": "onion", "name": "..."}  → saved to
                         data/labels-reviewed.csv   (training labels, every class)
                         data/overrides.csv         (only roof types the map knows; the map changes
                                                     with the next python build.py)
Nothing is changed by predictions alone, only by a review click.
"""
import csv
import functools
import http.server
import io
import json
import pathlib
import re
import threading
import webbrowser

ROOT = pathlib.Path(__file__).resolve().parent
SITE = ROOT / "site"
DATA = ROOT / "data"
PORT = 8000
CLASSES = {"onion", "onion_double", "welsch", "dome", "other", "no_tower", "skip"}
MAP_CLASSES = {"onion", "onion_double", "welsch", "dome", "other"}   # roof types of the map (classify.CATEGORIES)
SOURCE = "yolov8-cls-reviewed"
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
                if SOURCE in ln:
                    continue                                  # an earlier review of the same church: replaced below
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
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _local_origin(self) -> bool:
        origin = self.headers.get("Origin")                   # blocks other websites from posting to localhost
        return origin is None or origin in (f"http://localhost:{PORT}", f"http://127.0.0.1:{PORT}")

    def do_GET(self):
        if self.path.split("?")[0] == "/api/reviewed":
            return self._json(reviewed_ids())
        super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/review":
            return self._json({"error": "not found"}, 404)
        if not self._local_origin():
            return self._json({"error": "forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length", 0))
            if not 0 < n < 10_000:
                raise ValueError("bad length")
            d = json.loads(self.rfile.read(n))
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
    webbrowser.open(f"http://localhost:{PORT}")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()


if __name__ == "__main__":
    main()
