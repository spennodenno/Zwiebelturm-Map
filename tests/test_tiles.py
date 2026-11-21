"""Offline test of tiles, automatic box splitting and the failure list:  python -m tests.test_tiles"""
import json
import re
import shutil
import tempfile
import urllib.parse
from pathlib import Path

from pipeline import net, run
from tests import fake_sources

ROOT = Path(__file__).resolve().parent.parent
net.time.sleep = lambda s: None            # no real waiting for retries and politeness pauses

mode = {"fail": None}                      # None | "all" | "big" | "cut"
sparql_calls = []


def fetch(url, data=None, timeout=0):
    if "sparql" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["query"][0]
        w, s = map(float, re.search(r'SouthWest "Point\(([-\d.]+) ([-\d.]+)\)', q).groups())
        e, n = map(float, re.search(r'NorthEast "Point\(([-\d.]+) ([-\d.]+)\)', q).groups())
        sparql_calls.append((w, s, e, n))
        if mode["fail"] == "all" or (mode["fail"] == "big" and e - w > 0.3):
            raise net.HttpError(504, url, "timeout")
        if mode["fail"] == "cut" and e - w > 0.3:                   # HTTP 200, but the JSON stops in the middle
            return b'{"head": {"vars": ["item"]}, "results": {"bindings": [{"item" "Q1"'
        if mode["fail"] == "bug" and e - w > 0.3:
            raise KeyError("some bug")
    return fake_sources.fetch(url, data, timeout)


def build(tmp: Path, out: Path):
    run.main(["--config", str(tmp / "config.toml"), "--countries", "DE,AT", "--cache", str(tmp), "--out", str(out)])
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def main():
    net.fetch = fetch
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "boundaries").mkdir()
        (tmp / "boundaries" / "ne_10m_admin_0_countries.geojson").write_bytes(
            (ROOT / "cache" / "boundaries" / "ne_10m_admin_0_countries.geojson").read_bytes())
        cfg = (ROOT / "config.toml").read_text(encoding="utf-8")
        cfg = cfg.replace('source = "postpass"', 'source = "overpass"').replace("pause_s = 3", "pause_s = 0")
        cfg = cfg.replace("enabled = true", "enabled = false")               # no explicit region
        cfg = re.sub(r"(\[wikipedia\.tiles\]\nenabled = )false", r"\1true", cfg)
        cfg = cfg.replace('countries = ["DE"]       # ISO', 'countries = ["DE", "AT"]       # ISO').replace("size_deg = 0.25", "size_deg = 0.5")
        (tmp / "config.toml").write_text(cfg, encoding="utf-8")
        run.FAILED_FILE, run.FAILED_LOG = tmp / "failed-regions.txt", tmp / "build-failures.log"
        out = tmp / "out"

        # 1) everything fails (Wikidata down): the build still finishes, failures are listed, nothing is lost
        mode["fail"] = "all"
        man = build(tmp, out)
        failed = run.read_failed()
        assert man["n"] == 7 and failed and all(i.startswith("tile_") for i in failed), failed
        assert not any("wd" in r for f in (out / "d").glob("*.json") for r in json.loads(f.read_text(encoding="utf-8")))
        log = run.FAILED_LOG.read_text(encoding="utf-8")
        assert all(i in log for i in failed) and "504" in log

        # 2) Wikidata answers only small boxes: each failing tile is split into four and succeeds
        mode["fail"] = "big"
        sparql_calls.clear()
        man = build(tmp, out)
        assert run.read_failed() == [], run.read_failed()                     # the earlier failures are cleared
        assert max(e - w for w, s, e, n in sparql_calls) > 0.3 and any(e - w < 0.3 for w, s, e, n in sparql_calls)
        tiles = [r for r in man["wikipedia_regions"] if r["id"] == "tiles"]
        assert len(tiles) == 1 and tiles[0]["matched"] == 3 and tiles[0]["churches"] == 7, tiles
        recs = {r["id"]: r for f in (out / "d").glob("*.json") for r in json.loads(f.read_text(encoding="utf-8"))}
        assert recs["way/1"]["wd"]["qid"] == "Q900001" and recs["way/4"]["wd"]["qid"] == "Q900002"
        assert recs["way/4"]["roof"] == "onion_double"                         # roof type from the article text
        assert len(man["wikipedia_regions"]) == 1                              # not one entry per tile

        # 2b) a cut-off JSON answer is handled like a timeout (the box is split) and does not end the build
        mode["fail"] = "cut"
        shutil.rmtree(tmp / "wiki", ignore_errors=True)
        man = build(tmp, out)
        assert run.read_failed() == [] and [r for r in man["wikipedia_regions"] if r["id"] == "tiles"][0]["matched"] == 3

        # 2c) an unexpected error in single tiles is logged and the run goes on
        mode["fail"] = "bug"
        shutil.rmtree(tmp / "wiki", ignore_errors=True)
        build(tmp, out)
        assert run.read_failed() and "UNEXPECTED KeyError" in run.FAILED_LOG.read_text(encoding="utf-8")
        mode["fail"] = "big"
        shutil.rmtree(tmp / "wiki", ignore_errors=True)
        build(tmp, out)
        assert run.read_failed() == []

        # 3) a tile does not touch records an explicit region has already processed
        a = {"id": "x", "tile": True, "label": "t", "core": [10.9, 47.7, 11.2, 47.9], "bbox": [10.9, 47.7, 11.2, 47.9]}
        wcfg = {"languages": ["de"], "classes": ["Q16970"], "match_radius_m": 120, "properties": []}
        s = run.wikidata.enrich_region(a, list(recs.values()), wcfg, {}, tmp, out, done={"way/1"})
        assert s["churches"] == len([r for r in recs.values() if 47.7 <= r["lat"] < 47.9 and 10.9 <= r["lon"] < 11.2]) - 1

    # 4) bbox: only tiles that touch the box
    recs_l = [{"cc": "DE", "lat": 47.8, "lon": 11.0}, {"cc": "DE", "lat": 52.5, "lon": 13.4}, {"cc": "AT", "lat": 47.8, "lon": 13.0}]
    assert len(run.tile_regions(recs_l, {"countries": ["DE"], "size_deg": 0.5})) == 2
    only = run.tile_regions(recs_l, {"countries": ["DE"], "size_deg": 0.5, "bbox": [8.9, 47.2, 13.9, 50.6]})
    assert [t["core"] for t in only] == [[11.0, 47.5, 11.5, 48.0]], only
    assert len(run.tile_regions(recs_l, {"size_deg": 0.5, "bbox": [8.9, 47.2, 13.9, 50.6]})) == 2   # DE south + AT

    print("tile tests passed")


if __name__ == "__main__":
    main()
