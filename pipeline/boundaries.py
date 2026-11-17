"""Country outlines from Natural Earth (public domain, 1:10 million)."""
from __future__ import annotations

import json
from pathlib import Path

from . import net

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
          "geojson/ne_10m_admin_0_countries.geojson")


def _iso(props: dict) -> str:
    for key in ("ISO_A2_EH", "ISO_A2"):
        v = props.get(key)
        if v and v != "-99":
            return v
    return ""


def _round(coords, nd=4):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    out = [_round(c, nd) for c in coords]
    if out and isinstance(out[0][0], (int, float)):  # a ring: drop repeated points
        dedup = [out[0]]
        for p in out[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        return dedup
    return out


def _points(coords):
    if isinstance(coords[0], (int, float)):
        yield coords
    else:
        for c in coords:
            yield from _points(c)


def _clip_parts(geometry: dict, box: list[float]) -> dict:
    """Keeps the polygons of a MultiPolygon whose bounding box lies completely inside
    box = [west, south, east, north]. Used to drop overseas territories (France: Guyane, Réunion …)."""
    w, s, e, n = box
    if geometry["type"] != "MultiPolygon":
        return geometry
    kept = []
    for poly in geometry["coordinates"]:
        pts = list(_points(poly[0]))
        if (min(p[0] for p in pts) >= w and max(p[0] for p in pts) <= e
                and min(p[1] for p in pts) >= s and max(p[1] for p in pts) <= n):
            kept.append(poly)
    if not kept:
        raise SystemExit(f"[clip] box {box} contains no part of the country outline")
    return {"type": "MultiPolygon", "coordinates": kept}


def _npoints(geometry: dict) -> int:
    return sum(1 for _ in _points(geometry["coordinates"]))


def load_countries(codes: list[str], cache_dir: Path, clip: dict | None = None) -> dict[str, dict]:
    """Returns {ISO: GeoJSON feature} for the configured countries, in config order.
    clip = {ISO: [west, south, east, north]} (config.toml [clip]) removes parts outside the box."""
    clip = clip or {}
    path = cache_dir / "boundaries" / "ne_10m_admin_0_countries.geojson"
    if not path.exists():
        print("  downloading Natural Earth country outlines …")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(net.fetch_retry(NE_URL, timeout=300))
    world = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for f in world["features"]:
        iso = _iso(f["properties"])
        if iso not in codes:
            continue
        # Some codes occur twice (ISO_A2_EH of Clipperton Island is also "FR"): keep the larger outline.
        if iso in found and _npoints(f["geometry"]) <= _npoints(found[iso]["geometry"]):
            continue
        p = f["properties"]
        geom = f["geometry"]
        if iso in clip:
            geom = _clip_parts(geom, clip[iso])
        found[iso] = {
            "type": "Feature",
            "properties": {"iso": iso, "en": p.get("NAME") or p.get("NAME_EN"),
                           "de": p.get("NAME_DE") or p.get("NAME")},
            "geometry": {"type": geom["type"], "coordinates": _round(geom["coordinates"])},
        }
    missing = [c for c in codes if c not in found]
    if missing:
        raise SystemExit(f"Unknown country code(s) in config.toml: {', '.join(missing)}")
    return {c: found[c] for c in codes}


def _area(ring) -> float:
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def world_mask(countries: dict[str, dict]) -> dict:
    """Everything EXCEPT the configured countries, as one GeoJSON feature. The front end
    paints it in the background colour above the base map, so nothing outside shows.

    The countries are dissolved first: a border segment shared by two configured
    countries occurs once in each direction and cancels out; what remains is stitched
    into rings (outer edge of the block, plus enclosed gaps such as Liechtenstein)."""
    edges: dict[tuple, tuple] = {}
    extra = []                                   # holes inside a country (San Marino …) stay masked
    for f in countries.values():
        polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
        for poly in polys:
            ring = [tuple(p) for p in poly[0]]
            if _area(ring) < 0:
                ring.reverse()
            for a, b in zip(ring, ring[1:]):
                if a == b:
                    continue
                if (b, a) in edges:
                    del edges[(b, a)]
                else:
                    edges[(a, b)] = b
            extra += [[list(p) for p in hole] for hole in poly[1:]]
    nxt: dict[tuple, list] = {}
    for a, b in edges:
        nxt.setdefault(a, []).append(b)
    rings = []
    while nxt:
        start = next(iter(nxt))
        ring, cur = [start], start
        while True:
            outs = nxt.get(cur)
            if not outs:
                break
            b = outs.pop()
            if not outs:
                del nxt[cur]
            ring.append(b)
            cur = b
            if cur == start:
                break
        if len(ring) >= 4 and ring[0] == ring[-1]:
            rings.append([list(p) for p in ring])
    world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]
    holes = [r for r in rings if _area(r) > 0]           # outer edge of the country block
    gaps = [r for r in rings if _area(r) < 0]            # enclosed foreign territory
    coords = [[world] + holes] + [[g] for g in gaps] + [[e] for e in extra]
    return {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": coords}}
