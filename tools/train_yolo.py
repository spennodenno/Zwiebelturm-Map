"""YOLOv8 roof classifier: train on your labels, then sort the unlabeled photos.

    pip install ultralytics
    python tools/train_yolo.py train            # data/labels.csv + data/labels-reviewed.csv
    python tools/train_yolo.py predict          # classify every unlabeled photo, nothing is kept on disk
    python tools/train_yolo.py predict --redo   # ignore earlier predictions and classify everything again

predict downloads each photo from Wikimedia Commons at 330 px, classifies it in memory and
forgets it. It writes
    data/predictions.csv          osm_id, roof, confidence, file, name   (least certain first)
    site/label/predictions.json   the same for the review page
and can be stopped with Ctrl+C at any time; the next run continues where it stopped.
Review the uncertain ones at http://localhost:8000/label.html?review (python serve.py).
Predictions never go into the map by themselves; only reviewed labels reach data/overrides.csv.

Classes are the labels you used. MERGE / DROP below change them for training only.
"""
import csv
import hashlib
import io
import json
import random
import shutil
import sys
import time
import tomllib
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import net  # noqa: E402

DATASET = ROOT / "cache" / "yolo-dataset"
RUNS = ROOT / "cache" / "yolo-runs"
PHOTOS = ROOT / "cache" / "photos"          # photos of the labeled churches (training set)
MERGE = {"onion_double": "onion"}           # too few images for their own class (first run)
DROP = {"dome"}                             # 4 images only; remove from the training set
PREDICT_WIDTH = 330                         # px; a standard Commons thumbnail size
FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/{}?width={}"
CHECKPOINT_EVERY = 100


def setup_net() -> None:
    cfg = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    net.USER_AGENT = cfg["osm"]["user_agent"]


def read_rows(path: Path) -> list[dict]:
    """CSV rows; '#' lines are ignored, a BOM at the start of the file is fine."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(l for l in f if not l.startswith("#")) if r.get("osm_id")]


def candidates(path: Path | None = None) -> dict:
    path = path or ROOT / "site" / "label" / "candidates.json"
    return {r["id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def known_ids() -> set[str]:
    """Churches whose roof type you have already decided (labels, reviews, manual overrides)."""
    return {r["osm_id"] for name in ("labels.csv", "labels-reviewed.csv", "overrides.csv")
            for r in read_rows(ROOT / "data" / name)}


# ---------- training ----------

def train_photo(row: dict) -> Path | None:
    """The stored photo of a labeled church. Looks in site/data/img, then in cache/photos
    (same file names as the pipeline uses), and downloads it into cache/photos if missing."""
    img = row["img"]
    if img.startswith("data/"):
        p = ROOT / "site" / img
        if p.exists():
            return p
        p = PHOTOS / Path(img).name
        return p if p.exists() else None
    ext = img.rsplit(".", 1)[-1].lower().split("?")[0]
    p = PHOTOS / (hashlib.sha1(img.encode()).hexdigest()[:16] + "." + (ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"))
    if not p.exists():
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(net.fetch_retry(img, timeout=60, tries=8, min_interval=1.0))
        except Exception as e:
            print(f"  photo missing for {row['id']} ({str(e)[:80]})")
            return None
    return p


def train():
    from ultralytics import YOLO
    setup_net()
    cand = candidates()
    by_id = {}                                              # reviewed labels win over the first round
    for name in ("labels.csv", "labels-reviewed.csv"):
        for r in read_rows(ROOT / "data" / name):
            by_id[r["osm_id"]] = r
    labels = [r for r in by_id.values() if r.get("roof") and r["roof"] != "skip" and r["osm_id"] in cand]
    for r in labels:                                        # merge tiny classes for the first run
        r["roof"] = MERGE.get(r["roof"], r["roof"])
    labels = [r for r in labels if r["roof"] not in DROP]
    print("classes:", {c: sum(r["roof"] == c for r in labels) for c in sorted({r["roof"] for r in labels})})
    if DATASET.exists():
        shutil.rmtree(DATASET)
    random.seed(1)
    random.shuffle(labels)
    for k, r in enumerate(labels):
        src = train_photo(cand[r["osm_id"]])
        if src is None:
            continue
        split = "val" if k % 5 == 0 else "train"            # 20 % validation
        dst = DATASET / split / r["roof"]
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst / (r["osm_id"].replace("/", "_") + src.suffix))
    model = YOLO("yolov8n-cls.pt")                          # small pretrained classifier
    model.train(data=str(DATASET), epochs=40, imgsz=320, project=str(RUNS), name="roof", exist_ok=True)


# ---------- prediction (streaming) ----------

def commons_url(file: str, width: int = PREDICT_WIDTH) -> str:
    return FILEPATH.format(urllib.parse.quote(file.replace(" ", "_"), safe=""), width)


def write_predictions(rows: list[dict], csv_path: Path, json_path: Path, cand: dict) -> None:
    rows = sorted(rows, key=lambda r: r["confidence"])      # least certain first
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = csv_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "roof", "confidence", "file", "name"])
        w.writerows([[r["osm_id"], r["roof"], r["confidence"], r.get("file", ""), r.get("name", "")] for r in rows])
    tmp.replace(csv_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps([
        {"id": r["osm_id"], "name": r.get("name", ""), "img": cand[r["osm_id"]]["img"] if r["osm_id"] in cand else "",
         "file": r.get("file", ""), "pred": r["roof"], "conf": r["confidence"]} for r in rows],
        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def run_predict(model, cand: dict, skip: set[str], fetch, csv_path: Path, json_path: Path,
                redo: bool = False, limit: int | None = None) -> int:
    """Classify the photos of all candidates that are not in `skip`. `fetch(url) -> bytes`.
    Each image is decoded in memory and dropped. Returns the number of new predictions."""
    from PIL import Image
    done = {} if redo else {r["osm_id"]: {**r, "confidence": float(r["confidence"])} for r in read_rows(csv_path)}
    todo = [c for i, c in cand.items() if i not in skip and i not in done]
    if limit:
        todo = todo[:limit]
    missing_file = [c for c in todo if not c.get("file")]
    if missing_file:
        print(f"{len(missing_file)} candidates have no Commons file name – run python tools/make_labelset.py again.")
    todo = [c for c in todo if c.get("file")]
    print(f"{len(done)} earlier predictions kept, {len(todo)} photos to classify")
    new = failed = 0
    t0 = time.time()
    try:
        for n, c in enumerate(todo, 1):
            try:
                img = Image.open(io.BytesIO(fetch(commons_url(c["file"])))).convert("RGB")
                res = model.predict(img, verbose=False)[0]
            except Exception as e:                           # deleted file, throttling, broken image: try again next run
                failed += 1
                print(f"  skipped {c['id']}: {str(e)[:100]}")
                continue
            done[c["id"]] = {"osm_id": c["id"], "roof": res.names[res.probs.top1],
                             "confidence": round(float(res.probs.top1conf), 3), "file": c["file"], "name": c["name"]}
            new += 1
            if new % CHECKPOINT_EVERY == 0:
                write_predictions(list(done.values()), csv_path, json_path, cand)
                rate = n / max(time.time() - t0, 1e-9)
                print(f"  {n}/{len(todo)} ({rate:.1f} photos/s, {failed} failed)")
    except KeyboardInterrupt:
        print("\nStopped; saving what is done.")
    write_predictions(list(done.values()), csv_path, json_path, cand)
    print(f"{new} new predictions, {failed} failed → {csv_path} (uncertain ones on top)")
    return new


def predict():
    from ultralytics import YOLO
    setup_net()
    best = RUNS / "roof" / "weights" / "best.pt"
    if not best.exists():
        sys.exit("No trained model found. Run: python tools/train_yolo.py train")
    cand = candidates()
    limit = None
    if "--limit" in sys.argv:                                # for a quick test: --limit 50
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    run_predict(YOLO(str(best)), cand, known_ids(),
                lambda url: net.fetch_retry(url, timeout=60, tries=6, min_interval=1.0),
                ROOT / "data" / "predictions.csv", ROOT / "site" / "label" / "predictions.json",
                redo="--redo" in sys.argv, limit=limit)


if __name__ == "__main__":
    {"train": train, "predict": predict}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
