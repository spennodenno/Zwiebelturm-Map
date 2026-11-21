"""Do the dots (points.bin) and the cards (site/data/d/*.json) say the same?   py tools/check_site.py"""
import glob
import json
import sys
from pathlib import Path

D = Path(__file__).resolve().parent.parent / "site" / "data"
m = json.loads((D / "manifest.json").read_text(encoding="utf-8"))
n, keys = m["n"], [c["key"] for c in m["categories"]]
cat = (D / "points.bin").read_bytes()[8 * n:9 * n]
rows = [r for f in sorted(glob.glob(str(D / "d" / "*.json"))) for r in json.loads(Path(f).read_text(encoding="utf-8"))]
bad = [(r["id"], r["roof"], keys[cat[i]]) for i, r in enumerate(rows) if i < n and keys[cat[i]] != r["roof"]]
print(f"built {m['generated']}: {n} dots, {len(rows)} cards, {len(bad)} where dot and card differ")
for b in bad[:10]:
    print("  ", b)
sys.exit(1 if bad or len(rows) != n else 0)
