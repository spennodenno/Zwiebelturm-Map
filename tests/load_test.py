"""Full-volume load test with INVENTED points (never shipped as map data).

    python -m tests.load_test /tmp/zt-load      # writes a throw-away copy of the site there

Generates ~250 000 random fake churches inside the real country outlines, runs
them through the normal pipeline (offline stand-ins instead of Overpass) and
writes a site copy, so rendering performance can be checked at realistic size.
"""
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

from pipeline import geo, net, run
from tests import fake_sources

ROOT = Path(__file__).resolve().parent.parent
COUNTS = {"DE": 62000, "AT": 17000, "CH": 9000, "CZ": 17000, "SI": 4000, "HU": 13000, "PL": 30000, "IT": 95000}


def main(target: str):
    random.seed(1)
    world = json.loads((ROOT / "cache/boundaries/ne_10m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    geoms = {f["properties"]["ISO_A2_EH"]: f["geometry"] for f in world["features"]}
    i = 1000
    fake_sources.ELEMENTS.clear()
    for iso, count in COUNTS.items():
        g = geoms[iso]
        w, s, e, n = geo.geometry_bbox(g)
        rings = [p[0] for p in geo.polygons(g)]
        made = 0
        while made < count:
            lon, lat = random.uniform(w, e), random.uniform(s, n)
            if not any(geo._point_in_ring(lon, lat, r) for r in rings):
                continue
            i += 1
            tags = {"amenity": "place_of_worship", "religion": "christian", "building": "church",
                    "name": f"Testkirche {i}", "denomination": "catholic"}
            roll = random.random()
            if roll < 0.025:
                tags["roof:shape"] = "onion"
            elif roll < 0.035:
                tags["roof:shape"] = "dome"
            el = fake_sources.way(i, round(lat, 6), round(lon, 6), **{k.replace(":", "__"): v for k, v in tags.items()})
            el["_cc"] = iso
            fake_sources.extra_elements.append(el)
            if 0.035 <= roll < 0.09:
                i += 1
                t = fake_sources.node(i, round(lat + 0.0002, 6), round(lon, 6), man_made="tower",
                                      tower__type="bell_tower", roof__shape=random.choice(["pyramidal", "gabled"]))
                t["_cc"] = iso
                fake_sources.extra_elements.append(t)
            made += 1
    # index by 2° cell so the stand-in answers quickly
    by_cell = {}
    for el in fake_sources.extra_elements:
        c = el.get("center") or el
        by_cell.setdefault((el["_cc"], int(c["lat"] // 2), int(c["lon"] // 2)), []).append(el)
    plain = fake_sources.fetch

    def fast(url, data=None, timeout=0):
        if "interpreter" in url and "map_to_area" not in data["data"]:
            import re
            s, w, n, e = map(float, re.search(r"\(area\.c\)\(([-\d.,]+)\)", data["data"]).group(1).split(","))
            iso = re.search(r'"ISO3166-1"="(\w+)"', data["data"]).group(1)
            els = by_cell.get((iso, int(s // 2), int(w // 2)), [])
            return json.dumps({"elements": [{k: v for k, v in el.items() if k != "_cc"} for el in els]}).encode()
        return plain(url, data, timeout)

    net.fetch = fast
    out = Path(target)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "site", out, ignore=shutil.ignore_patterns("data"))
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "boundaries").mkdir()
        shutil.copy(ROOT / "cache/boundaries/ne_10m_admin_0_countries.geojson", tmp / "boundaries")
        cfg = (ROOT / "config.toml").read_text(encoding="utf-8").replace("pause_s = 3", "pause_s = 0").replace('source = "postpass"', 'source = "overpass"')
        (tmp / "config.toml").write_text(cfg, encoding="utf-8")
        run.main(["--config", str(tmp / "config.toml"), "--cache", str(tmp), "--out", str(out / "data"), "--wiki-regions", "none"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/zt-load")
