"""Writes the static data files the web page loads.

site/data/
  manifest.json    counts, categories (labels + colours), chunk index, credits
  countries.geojson
  points.bin       [lon int32 × n][lat int32 × n][category uint8 × n], little endian, 1e-6 degrees
  d/0000.json …    detail records, `chunk_size` per file, same order as points.bin

Points are sorted along a Z-order curve, so each detail file covers a compact
area and point i lives in file floor(i / chunk_size) at position i % chunk_size.
"""
from __future__ import annotations

import array
import json
import shutil
import sys
import time
from pathlib import Path

from . import boundaries, classify, geo


def _morton(lat: float, lon: float) -> int:
    x = int((lon + 180) / 360 * 65535)
    y = int((lat + 90) / 180 * 65535)
    z = 0
    for i in range(16):
        z |= ((x >> i) & 1) << (2 * i) | ((y >> i) & 1) << (2 * i + 1)
    return z


def _detail(r: dict) -> dict:
    d = {"id": r["id"], "lat": r["lat"], "lon": r["lon"], "cc": r["cc"], "kind": r["kind"],
         "roof": r["roof"], "tags": r["tags"]}
    for k in ("name", "sub", "sub_text", "building_roof", "year", "height", "n_onion", "wd", "denkmal"):
        if r.get(k):
            d[k] = r[k]
    if len(r["ids"]) > 1:
        d["ids"] = r["ids"]
    if r.get("src"):
        d["src"] = r["src"]
    if r.get("near"):
        d["near"] = r["near"][:8]
    return d


def write_site(records: list[dict], countries: dict[str, dict], cfg: dict, stats: dict,
               regions: list[dict], out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda r: _morton(r["lat"], r["lon"]))
    n = len(records)

    lon = array.array("i", (round(r["lon"] * 1e6) for r in records))
    lat = array.array("i", (round(r["lat"] * 1e6) for r in records))
    cat = array.array("B", (classify.CAT_INDEX[r["roof"]] for r in records))
    if sys.byteorder == "big":
        lon.byteswap()
        lat.byteswap()
    (out_dir / "points.bin").write_bytes(lon.tobytes() + lat.tobytes() + cat.tobytes())

    ddir = out_dir / "d"
    if ddir.exists():
        shutil.rmtree(ddir)
    ddir.mkdir()
    size = cfg["export"]["chunk_size"]
    for k in range(0, max(n, 1), size):
        (ddir / f"{k // size:04d}.json").write_text(
            json.dumps([_detail(r) for r in records[k:k + size]], ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8")

    (out_dir / "countries.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": list(countries.values())},
                   ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    (out_dir / "mask.geojson").write_text(json.dumps(boundaries.world_mask(countries), separators=(",", ":")),
                                          encoding="utf-8")

    boxes = [geo.geometry_bbox(f["geometry"]) for f in countries.values()]
    by_cat = [0] * len(classify.CATEGORIES)
    by_country = {iso: [0] * len(classify.CATEGORIES) for iso in countries}
    for r in records:
        i = classify.CAT_INDEX[r["roof"]]
        by_cat[i] += 1
        by_country[r["cc"]][i] += 1
    manifest = {
        "generated": time.strftime("%Y-%m-%d"),
        "n": n,
        "chunk_size": size,
        "bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                 max(b[2] for b in boxes), max(b[3] for b in boxes)],
        "categories": [{**c, "count": by_cat[i]} for i, c in enumerate(classify.CATEGORIES)],
        "shape_labels": classify.SHAPE_LABELS,
        "countries": [{"iso": iso, **f["properties"], "count": sum(by_country[iso]),
                       "by_category": by_country[iso]} for iso, f in countries.items()],
        "wikipedia_regions": regions,
        "stats": stats,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest
