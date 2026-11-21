"""Command line entry point:  python build.py  [options]"""
from __future__ import annotations

import argparse
import csv
import math
import shutil
import sys
import time
import tomllib
import urllib.error
from pathlib import Path

from . import boundaries, export, merge, net, osm, wikidata

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS_FILE = ROOT / "data" / "predictions.csv"   # written by tools/train_yolo.py predict
FAILED_FILE = ROOT / "data" / "failed-regions.txt"     # ids that failed in the last run (one per line)
FAILED_LOG = ROOT / "data" / "build-failures.log"      # every failure with time and reason (appended)
# What can go wrong in one Wikipedia region without being a bug: server overload, network, unknown OSM relation.
REGION_ERRORS = (net.HttpError, urllib.error.URLError, TimeoutError, ConnectionError, OSError, SystemExit)


def tile_regions(records: list[dict], tcfg: dict, languages: dict | None = None) -> list[dict]:
    """Wikipedia regions made of a regular grid instead of an OSM boundary: every tile of `size_deg`
    degrees that contains at least one church of the chosen countries. No OSM relation, no names to look up."""
    size = float(tcfg.get("size_deg", 0.25))
    margin = float(tcfg.get("margin_deg", 0.003))       # ~300 m: the match radius reaches over the tile edge
    countries = {c.upper() for c in tcfg.get("countries", [])}
    box = tcfg.get("bbox")                              # [west, south, east, north]: only tiles that touch this box
    cells: dict[tuple[int, int], dict[str, int]] = {}
    for r in records:
        if not countries or r["cc"] in countries:
            c = cells.setdefault((math.floor(r["lat"] / size), math.floor(r["lon"] / size)), {})
            c[r["cc"]] = c.get(r["cc"], 0) + 1
    out = []
    for iy, ix in sorted(cells):
        s, w = iy * size, ix * size
        if box and not (w < box[2] and w + size > box[0] and s < box[3] and s + size > box[1]):
            continue
        tile = {"id": f"tile_{size:g}_{s:.3f}_{w:.3f}", "label": f"Kachel {s:.2f}N {w:.2f}E",
                "tile": True, "core": [w, s, w + size, s + size],
                "bbox": [w - margin, s - margin, w + size + margin, s + size + margin]}
        # Wikipedia editions of the country that has most churches in the tile (a border tile keeps its main country's list)
        main = max(cells[(iy, ix)], key=lambda cc: (cells[(iy, ix)][cc], cc))
        if languages and languages.get(main):
            tile["languages"] = list(languages[main])
        out.append(tile)
    return out


def read_failed() -> list[str]:
    return [l.strip() for l in FAILED_FILE.read_text(encoding="utf-8").splitlines() if l.strip()] \
        if FAILED_FILE.exists() else []


def write_failed(ids: list[str], log: list[str]) -> None:
    FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAILED_FILE.write_text("".join(i + "\n" for i in ids), encoding="utf-8")
    if log:
        with FAILED_LOG.open("a", encoding="utf-8") as f:
            f.write("".join(log))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the data files for the Zwiebelturm map.")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--countries", help="comma-separated ISO codes; overrides config.toml (e.g. AT,SI)")
    ap.add_argument("--wiki-regions", help="comma-separated region ids from config.toml, 'all', 'none' or 'tiles' "
                                           "(tiles only); default: every region with enabled = true + the tiles")
    ap.add_argument("--tile-countries", help="comma-separated ISO codes; overrides [wikipedia.tiles] countries")
    ap.add_argument("--refresh", choices=["osm", "wiki", "all"],
                    help="ignore the cache and download again")
    ap.add_argument("--out", default=str(ROOT / "site" / "data"))
    ap.add_argument("--cache", default=str(ROOT / "cache"))
    args = ap.parse_args(argv)

    cfg = tomllib.loads(Path(args.config).read_text(encoding="utf-8"))
    net.USER_AGENT = cfg["osm"]["user_agent"]
    cache = Path(args.cache)
    codes = [c.strip().upper() for c in args.countries.split(",")] if args.countries else cfg["countries"]
    if args.refresh in ("wiki", "all") and (cache / "wiki").exists():
        shutil.rmtree(cache / "wiki")

    print(f"1/4 Country outlines: {', '.join(codes)}")
    countries = boundaries.load_countries(codes, cache, cfg.get("clip", {}))

    print(f"2/4 OpenStreetMap via {cfg['osm'].get('source', 'postpass')} (cached per grid cell)")
    elements = {}
    for iso, feature in countries.items():
        elements[iso] = osm.fetch_country(cfg["osm"], iso, feature["geometry"], cache,
                                          refresh=args.refresh in ("osm", "all"))
        print(f"  {iso}: {len(elements[iso])} OSM objects")
    records, stats = merge.build_records(elements, cfg["merge"])
    print(f"  → {len(records)} churches / towers after merging "
          f"({stats['duplicates_merged']} duplicates merged)")

    wcfg = cfg.get("wikipedia", {})
    explicit = wcfg.get("regions", [])
    tcfg = wcfg.get("tiles", {})
    if args.tile_countries:
        tcfg = {**tcfg, "countries": [c.strip().upper() for c in args.tile_countries.split(",")]}
    tiles = tile_regions(records, tcfg, wcfg.get("country_languages")) if tcfg else []
    sel = args.wiki_regions
    if sel == "none":
        regions = []
    elif sel == "tiles":
        regions = tiles
    elif sel == "all":
        regions = explicit + (tiles if tcfg else [])
    elif sel:
        wanted = {s.strip() for s in sel.split(",")}
        unknown = wanted - {r["id"] for r in explicit + tiles}
        if unknown:
            raise SystemExit(f"Unknown wiki region id(s): {', '.join(sorted(unknown))}")
        regions = [r for r in explicit + tiles if r["id"] in wanted]
    else:
        regions = [r for r in explicit if r.get("enabled")] + (tiles if tcfg.get("enabled") else [])
    n_tiles = sum(1 for r in regions if r.get("tile"))
    print(f"3/4 Wikipedia / Wikidata merge: {len(regions) - n_tiles} regions"
          + (f" + {n_tiles} tiles of {tcfg.get('size_deg', 0.25):g}°" if n_tiles else ""))
    region_stats, failed, fail_log, done = [], [], [], set()
    unexpected = 0                                      # unexpected errors in a row
    n_explicit = len(regions) - n_tiles
    t_tiles = None                                      # the time estimate counts tiles only (regions are cached and fast)
    for k, region in enumerate(regions, 1):
        if region.get("tile") and t_tiles is None:
            t_tiles = time.time()
        # tiles do their own Denkmalliste setting (the lists exist for Bavaria only)
        rcfg = {**wcfg, "denkmal_lists": tcfg.get("denkmal_lists", False)} if region.get("tile") else wcfg
        try:
            s = wikidata.enrich_region(region, records, rcfg, cfg["osm"], cache, Path(args.out),
                                       refresh=args.refresh in ("osm", "all"), done=done)
        except osm.ConfigError as e:
            # a typo in config.toml: skip the region, but do not list it as failed (waiting and retrying cannot fix it)
            fail_log.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{region['id']}\tCONFIG ERROR: {e}\n")
            print(f"  [{k}/{len(regions)}] CONFIG ERROR {region['id']}: {e}")
            continue
        except REGION_ERRORS as e:
            # one region must not stop the rest: note it, go on, repeat it later by running build.py again.
            # Everything fetched so far stays in the cache.
            reason = (str(e) or e.__class__.__name__).replace("\n", " ")[:300]
            failed.append(region["id"])
            fail_log.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{region['id']}\t{reason}\n")
            print(f"  [{k}/{len(regions)}] FAILED {region['id']}: {reason}")
            unexpected = 0
            continue
        except Exception as e:
            # not a network or configuration problem: probably a bug. Note it and go on; five in a row end the run.
            reason = f"UNEXPECTED {type(e).__name__}: {e}".replace("\n", " ")[:300]
            failed.append(region["id"])
            fail_log.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{region['id']}\t{reason}\n")
            print(f"  [{k}/{len(regions)}] FAILED {region['id']}: {reason}")
            unexpected += 1
            if unexpected >= 5:
                raise
            continue
        unexpected = 0
        region_stats.append(s)
        if region.get("tile"):
            if s["churches"]:
                tiles_done = k - n_explicit
                eta = (time.time() - t_tiles) / tiles_done * (n_tiles - tiles_done) / 60
                print(f"  [{k}/{len(regions)}] {region['id']}: {s['churches']} churches, {s['matched']} matched, "
                      f"{s['with_photo']} with photo  (about {eta:.0f} min left)")
            continue
        print(f"  [{k}/{len(regions)}] {s['label']}: {s['churches']} churches, {s['matched']} matched to Wikidata "
              f"({s['by_tag']} by tag, {s['by_coordinates']} by coordinates), "
              f"{s['with_article']} with article, {s['with_photo']} with photo, "
              f"{s['roof_from_text']} roof types from article text, "
              f"{s['with_denkmal_text']} with Denkmalliste text ({s['roof_from_denkmal']} roof types from it)")
    if regions:
        # the list always holds what is still open: earlier failures of regions that ran now are cleared
        failed = sorted((set(read_failed()) - {r["id"] for r in regions}) | set(failed))
        write_failed(failed, fail_log)
    if failed:
        print(f"\n  {len(failed)} region(s) without Wikipedia data in this build (list: data/{FAILED_FILE.name}, "
              f"reasons: data/{FAILED_LOG.name}).\n  Run  py build.py  again: everything that worked is cached, "
              f"only the failed regions are asked again.\n")
    # one summary line for all tiles keeps the manifest small
    tile_stats = [s for s in region_stats if s["id"].startswith("tile_")]
    region_stats = [s for s in region_stats if not s["id"].startswith("tile_")]
    if tile_stats:
        keys = ("churches", "matched", "by_tag", "by_coordinates", "with_article", "with_photo",
                "roof_from_text", "with_denkmal_text", "roof_from_denkmal")
        region_stats.append({"id": "tiles", "label": f"{len(tile_stats)} Kacheln à {tcfg.get('size_deg', 0.25):g}°",
                             "bbox": None, **{k: sum(s[k] for s in tile_stats) for k in keys}})

    pcfg = cfg.get("predictions", {})
    if pcfg.get("apply", True) and PREDICTIONS_FILE.exists():
        with PREDICTIONS_FILE.open(encoding="utf-8-sig", newline="") as f:
            pred_rows = list(csv.DictReader(f))
        min_conf = float(pcfg.get("min_confidence", 0.9))
        ps = merge.apply_predictions(records, pred_rows, min_conf, pcfg.get("protect", ["dome"]))
        stats["predictions"] = {"min_confidence": min_conf, **ps}
        print(f"  Model (photo, confidence >= {min_conf:g}): {ps['seen']} predictions on churches of this map: "
              f"{ps['filled']} filled in, {ps['overwritten']} replaced another type, {ps['confirmed']} confirmed, "
              f"{ps['protected']} not applied (protected type)")

    overrides = ROOT / "data" / "overrides.csv"
    if overrides.exists():
        with overrides.open(encoding="utf-8-sig", newline="") as f:
            rows = [r for r in csv.DictReader(l for l in f if not l.startswith("#"))]
        stats["overrides_applied"] = merge.apply_overrides(records, rows)

    print("4/4 Writing site/data")
    manifest = export.write_site(records, countries, cfg, stats, region_stats, Path(args.out))
    width = max(len(c["de"]) for c in manifest["categories"])
    for c in reversed(manifest["categories"]):
        print(f"  {c['de']:<{width}}  {c['count']:>7}")
    print(f"Done: {manifest['n']} dots. Open the map with:  python serve.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
