"""Command line entry point:  python build.py  [options]"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
import tomllib
from pathlib import Path

from . import boundaries, export, merge, net, osm, wikidata

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the data files for the Zwiebelturm map.")
    ap.add_argument("--config", default=str(ROOT / "config.toml"))
    ap.add_argument("--countries", help="comma-separated ISO codes; overrides config.toml (e.g. AT,SI)")
    ap.add_argument("--wiki-regions", help="comma-separated region ids from config.toml, 'all' or 'none'; "
                                           "default: every region with enabled = true")
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
    countries = boundaries.load_countries(codes, cache)

    print(f"2/4 OpenStreetMap via {cfg['osm'].get('source', 'postpass')} (cached per grid cell)")
    elements = {}
    for iso, feature in countries.items():
        elements[iso] = osm.fetch_country(cfg["osm"], iso, feature["geometry"], cache,
                                          refresh=args.refresh in ("osm", "all"))
        print(f"  {iso}: {len(elements[iso])} OSM objects")
    records, stats = merge.build_records(elements, cfg["merge"])
    print(f"  → {len(records)} churches / towers after merging "
          f"({stats['duplicates_merged']} duplicates merged)")

    regions = cfg.get("wikipedia", {}).get("regions", [])
    sel = args.wiki_regions
    if sel == "none":
        regions = []
    elif sel and sel != "all":
        wanted = {s.strip() for s in sel.split(",")}
        unknown = wanted - {r["id"] for r in regions}
        if unknown:
            raise SystemExit(f"Unknown wiki region id(s): {', '.join(sorted(unknown))}")
        regions = [r for r in regions if r["id"] in wanted]
    elif not sel:
        regions = [r for r in regions if r.get("enabled")]
    print(f"3/4 Wikipedia / Wikidata merge: {', '.join(r['id'] for r in regions) or 'no region enabled'}")
    region_stats = []
    for region in regions:
        try:
            s = wikidata.enrich_region(region, records, cfg["wikipedia"], cfg["osm"], cache, Path(args.out),
                                       refresh=args.refresh in ("osm", "all"))
        except net.HttpError as e:
            # Wikimedia throttles hard at times. Everything fetched so far is kept in the cache.
            raise SystemExit(f"Wikipedia merge for '{region['id']}' stopped: {e}\n"
                             "Nothing was written. Run the same command again in a few minutes – it continues "
                             "from the cache. To build without Wikipedia: --wiki-regions none")
        region_stats.append(s)
        print(f"  {s['label']}: {s['churches']} churches, {s['matched']} matched to Wikidata "
              f"({s['by_tag']} by tag, {s['by_coordinates']} by coordinates), "
              f"{s['with_article']} with article, {s['with_photo']} with photo, "
              f"{s['roof_from_text']} roof types from article text")

    overrides = ROOT / "data" / "overrides.csv"
    if overrides.exists():
        with overrides.open(encoding="utf-8", newline="") as f:
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
