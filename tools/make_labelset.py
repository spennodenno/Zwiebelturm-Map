"""Step 1 of the image-model workflow: collect the churches that have a photo.

    python tools/make_labelset.py            # writes site/label/candidates.json
    python serve.py                          # then open http://localhost:8000/label.html

Only churches inside Wikipedia regions have photos, so enable more regions in
config.toml (and rebuild) to get more images to label.
"""
import glob
import json
import random
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = []
for f in sorted(glob.glob(str(ROOT / "site" / "data" / "d" / "*.json"))):
    for r in json.loads(Path(f).read_text(encoding="utf-8")):
        img = (r.get("wd") or {}).get("image") or {}
        src = ("data/" + img["local"]) if img.get("local") else img.get("thumb")
        if src:
            file = img.get("file")                     # Commons file name (older builds: taken from the page URL)
            if not file and "/File:" in (img.get("page") or ""):
                file = urllib.parse.unquote(img["page"].split("/File:", 1)[1]).replace("_", " ")
            rows.append({"id": r["id"], "name": r.get("name") or "", "img": src, "file": file or "",
                         "roof": r["roof"], "why": "; ".join(r.get("src", []))[:200]})
random.seed(1)
random.shuffle(rows)
out = ROOT / "site" / "label" / "candidates.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
print(f"{len(rows)} churches with a photo → {out}")
