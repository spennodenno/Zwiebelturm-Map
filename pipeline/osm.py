"""OpenStreetMap download.

Volume strategy: every country is cut into grid cells; each cell is one query
restricted to the country's OSM boundary. Results are cached per cell
(cache/osm-<source>/<ISO>/), so an interrupted run resumes where it stopped,
and a cell that times out is split into four smaller ones automatically.

Two interchangeable sources (config.toml, [osm] source):
  "postpass"  Geofabrik's Postpass (SQL on a PostGIS copy of OSM) – fast, default
  "overpass"  the classic Overpass API
Both deliver the same objects in the same shape: {type, id, lat, lon, tags}.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from . import geo, net

# What is fetched. The first two are the churches themselves, the rest are
# objects that carry the tower's roof shape and get attached to a church nearby.
CHURCH_FILTERS = [
    'nwr["amenity"="place_of_worship"]["religion"="christian"]',
    'nwr["building"~"^(church|chapel|cathedral|basilica)$"]',
]
TOWER_FILTERS = [
    'nwr["man_made"="tower"]["tower:type"~"^(bell_tower|campanile)$"]',
    'nwr["man_made"="campanile"]',
]
PART_FILTERS = [
    'nwr["roof:shape"~"^(onion|dome)$"]',
    'nwr["building:roof:shape"~"^(onion|dome)$"]',
    'nwr["building:part"~"tower|steeple|spire|belfry"]["roof:shape"]',
    'nwr["tower:type"~"^(bell_tower|campanile)$"]["roof:shape"]',
]
MIN_CELL_DEG = 0.2


class OverpassOverload(Exception):
    pass


def _query(cfg: dict, ql: str) -> dict:
    """Runs one query, rotating through the configured servers."""
    last: Exception | None = None
    for endpoint in cfg["endpoints"]:
        try:
            raw = net.fetch_retry(endpoint, {"data": ql}, timeout=cfg["timeout_s"] + 60,
                                  tries=4, min_interval=cfg["pause_s"])
            obj = json.loads(raw)
        except net.HttpError as e:
            if e.status == 400:
                raise SystemExit(f"Overpass rejected the query (bug in the query text):\n{e.body}\n{ql}")
            last = e
            continue
        except Exception as e:  # network trouble, invalid JSON from an overloaded server
            last = e
            continue
        remark = obj.get("remark", "")
        if "error" in remark.lower():
            raise OverpassOverload(remark)
        return obj
    raise SystemExit(f"No Overpass server answered ({last}).\n"
                     "Run the same command again later – finished cells are cached.")


def cell_query(iso: str, s: float, w: float, n: float, e: float, timeout_s: int) -> str:
    bbox = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    lines = "\n".join(f"  {f}(area.c){bbox};" for f in CHURCH_FILTERS + TOWER_FILTERS + PART_FILTERS)
    return (f'[out:json][timeout:{timeout_s}][maxsize:1073741824];\n'
            f'area["ISO3166-1"="{iso}"]["admin_level"="2"]->.c;\n'
            f'(\n{lines}\n);\nout tags center qt;')


# ---------- Postpass ----------

_PP_TYPES = {"N": "node", "W": "way", "R": "relation"}
_PP_TAGSETS = (
    [{"amenity": "place_of_worship", "religion": "christian"}]
    + [{"building": b} for b in ("church", "chapel", "cathedral", "basilica")]
    + [{"man_made": "tower", "tower:type": t} for t in ("bell_tower", "campanile")]
    + [{"man_made": "campanile"}]
    + [{k: v} for k in ("roof:shape", "building:roof:shape") for v in ("onion", "dome")]
    + [{"building:part": b} for b in ("tower", "steeple", "spire", "belfry", "bell_tower", "church_tower")]
)
_PP_CHURCH_SETS = 7   # the first seven tag sets are churches and bell towers (used for region membership)


def _pp_tag_condition(tagsets) -> str:
    return " OR ".join("p.tags @> '" + json.dumps(t, separators=(",", ":")) + "'" for t in tagsets)


def _pp_boundary(tags: dict) -> str:
    sel = json.dumps(tags, separators=(",", ":")).replace("'", "''")
    return (f"(SELECT geom FROM postpass_polygon WHERE osm_type='R' AND tags @> '{sel}' "
            "ORDER BY ST_NPoints(geom) DESC LIMIT 1)")


def postpass_cell_query(iso: str, s: float, w: float, n: float, e: float) -> str:
    boundary = _pp_boundary({"boundary": "administrative", "admin_level": "2", "ISO3166-1": iso})
    return ("SELECT p.osm_type, p.osm_id, p.tags, "
            "round(ST_X(ST_Centroid(p.geom))::numeric, 6) AS lon, round(ST_Y(ST_Centroid(p.geom))::numeric, 6) AS lat "
            f"FROM postpass_pointpolygon p, {boundary} c "
            f"WHERE p.geom && ST_MakeEnvelope({w:.5f},{s:.5f},{e:.5f},{n:.5f},4326) "
            f"AND ({_pp_tag_condition(_PP_TAGSETS)}) AND ST_Intersects(p.geom, c.geom)")


def _postpass(cfg: dict, sql: str) -> list[dict]:
    try:
        raw = net.fetch_retry(cfg["postpass_endpoint"], {"data": sql, "options[geojson]": "false"},
                              timeout=cfg["timeout_s"] + 60, tries=2, min_interval=cfg["pause_s"])
    except net.HttpError as e:
        if e.status == 400:
            raise SystemExit(f"Postpass rejected the query:\n{e.body}\n{sql}")
        raise OverpassOverload(str(e))   # too slow / too big → the caller splits the cell
    except TimeoutError as e:
        raise OverpassOverload(f"no answer within {cfg['timeout_s'] + 60}s ({e})")
    except Exception as e:
        raise SystemExit(f"Postpass did not answer ({e}).\n"
                         "Run the same command again later – finished cells are cached.")
    return json.loads(raw)["result"]


def _pp_elements(rows: list[dict]) -> list[dict]:
    return [{"type": _PP_TYPES[r["osm_type"]], "id": r["osm_id"], "lat": float(r["lat"]), "lon": float(r["lon"]),
             "tags": r["tags"]} for r in rows if r.get("lat") is not None]


def _run_cell(cfg, iso, s, w, n, e) -> list[dict]:
    if cfg.get("source", "postpass") == "postpass":
        return _pp_elements(_postpass(cfg, postpass_cell_query(iso, s, w, n, e)))
    return _query(cfg, cell_query(iso, s, w, n, e, cfg["timeout_s"])).get("elements", [])


def _fetch_cell(cfg, iso, s, w, n, e, cache: Path, refresh: bool, depth=0) -> list[dict]:
    name = f"{s:.3f}_{w:.3f}_{n:.3f}_{e:.3f}"
    path = cache / f"{name}.json.gz"
    split_marker = cache / f"{name}.split"
    if path.exists() and not refresh:
        return net.read_gz_json(path)
    if not split_marker.exists() or refresh:
        try:
            t0 = time.time()
            elements = _run_cell(cfg, iso, s, w, n, e)
            net.write_gz_json(path, elements)
            print(f"  {iso} cell {name}: {len(elements)} objects ({time.time() - t0:.0f}s)")
            return elements
        except OverpassOverload as err:
            if (n - s) / 2 < MIN_CELL_DEG:
                raise SystemExit(f"The OSM server keeps failing for {iso} cell {name}: {err}\n"
                                 "Run the same command again later – finished cells are cached.")
            print(f"  {iso} cell {name}: {str(err)[:90]} → splitting into 4")
            split_marker.parent.mkdir(parents=True, exist_ok=True)
            split_marker.write_text("split")
    ms, mw = (s + n) / 2, (w + e) / 2
    out: list[dict] = []
    for cs, cw, cn, ce in ((s, w, ms, mw), (s, mw, ms, e), (ms, w, n, mw), (ms, mw, n, e)):
        out += _fetch_cell(cfg, iso, cs, cw, cn, ce, cache, refresh, depth + 1)
    return out


def fetch_country(cfg: dict, iso: str, geometry: dict, cache_dir: Path, refresh=False) -> list[dict]:
    """All relevant OSM objects of one country (deduplicated by OSM id)."""
    w, s, e, n = geo.geometry_bbox(geometry)
    step = cfg["cell_deg"]
    cache = cache_dir / f"osm-{cfg.get('source', 'postpass')}" / iso
    w0, s0 = math.floor(w / step) * step, math.floor(s / step) * step
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    pad = 0.1  # the Natural Earth outline is coarser than the OSM boundary
    y = s0
    while y < n + pad:
        x = w0
        while x < e + pad:
            if geo.rect_intersects(geometry, x - pad, y - pad, x + step + pad, y + step + pad):
                for el in _fetch_cell(cfg, iso, y, x, y + step, x + step, cache, refresh):
                    key = (el["type"], el["id"])
                    if key not in seen:
                        seen.add(key)
                        out.append(el)
            x = round(x + step, 6)
        y = round(y + step, 6)
    return out


def region_query(osm_tags: dict, timeout_s: int) -> str:
    sel = "".join(f'["{k}"="{v}"]' for k, v in osm_tags.items())
    lines = "\n".join(f"  {f}(area.r);" for f in CHURCH_FILTERS + TOWER_FILTERS)
    return (f'[out:json][timeout:{timeout_s}];\n'
            f'rel{sel};\nout ids bb;\nmap_to_area->.r;\n(\n{lines}\n);\nout ids;')


def fetch_region(cfg: dict, region: dict, cache_dir: Path, refresh=False) -> dict:
    """Bounding box of an admin region and the ids of all churches inside it."""
    path = cache_dir / f"osm-{cfg.get('source', 'postpass')}" / "regions" / f"{region['id']}.json.gz"
    if path.exists() and not refresh:
        return net.read_gz_json(path)
    if cfg.get("source", "postpass") == "postpass":
        b = _pp_boundary(region["osm_tags"])
        box = _postpass(cfg, "SELECT ST_XMin(g) AS w, ST_YMin(g) AS s, ST_XMax(g) AS e, ST_YMax(g) AS n "
                             f"FROM (SELECT ST_Extent(geom) AS g FROM {b} x) y")
        if not box or box[0]["w"] is None:
            raise SystemExit(f"Wikipedia region '{region['id']}': no OSM relation matches {region['osm_tags']}")
        bb = box[0]
        rows = _postpass(cfg, f"SELECT p.osm_type, p.osm_id FROM postpass_pointpolygon p, {b} c "
                              f"WHERE p.geom && ST_MakeEnvelope({bb['w']},{bb['s']},{bb['e']},{bb['n']},4326) "
                              f"AND ({_pp_tag_condition(_PP_TAGSETS[:_PP_CHURCH_SETS])}) AND ST_Intersects(p.geom, c.geom)")
        result = {"bbox": [bb["w"], bb["s"], bb["e"], bb["n"]],
                  "ids": [f"{_PP_TYPES[r['osm_type']]}/{r['osm_id']}" for r in rows]}
        net.write_gz_json(path, result)
        return result
    obj = _query(cfg, region_query(region["osm_tags"], 300))
    rels = [el for el in obj["elements"] if el["type"] == "relation" and "bounds" in el]
    if not rels:
        raise SystemExit(f"Wikipedia region '{region['id']}': no OSM relation matches {region['osm_tags']}")
    b = rels[0]["bounds"]
    ids = [f"{el['type']}/{el['id']}" for el in obj["elements"] if "bounds" not in el]
    result = {"bbox": [b["minlon"], b["minlat"], b["maxlon"], b["maxlat"]], "ids": ids,
              "relation": rels[0]["id"]}
    net.write_gz_json(path, result)
    return result


def region_municipalities(cfg: dict, region: dict, cache_dir: Path) -> list[str]:
    """Names of the municipalities (admin_level 8) inside a region – Postpass only."""
    if cfg.get("source", "postpass") != "postpass":
        return []
    path = cache_dir / "osm-postpass" / "regions" / f"{region['id']}-municipalities.json.gz"
    if path.exists():
        return net.read_gz_json(path)
    b = _pp_boundary(region["osm_tags"])
    rows = _postpass(cfg, "SELECT DISTINCT p.tags->>'name' AS name FROM postpass_polygon p, " + b + " c "
                          "WHERE p.tags @> '{\"boundary\":\"administrative\",\"admin_level\":\"8\"}' "
                          "AND p.geom && c.geom AND ST_Within(ST_PointOnSurface(p.geom), c.geom)")
    names = sorted(r["name"] for r in rows if r.get("name"))
    net.write_gz_json(path, names)
    return names
