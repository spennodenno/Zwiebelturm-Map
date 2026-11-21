"""Turns raw OSM objects into one record per church (tower)."""
from __future__ import annotations

import re

from . import classify, geo

CHURCH_BUILDINGS = {"church", "chapel", "cathedral", "basilica"}
YEAR_KEYS = ("start_date", "year_of_construction", "construction_date", "building:start_date",
             "building:year", "year_built")
HEIGHT_KEYS = ("tower:height", "height", "building:height", "est_height")


def kind_of(tags: dict) -> str | None:
    """'church', 'tower', 'part' – or None if the object is not wanted."""
    religion = tags.get("religion")
    if tags.get("amenity") == "place_of_worship" and religion == "christian":
        return "church"
    if tags.get("building") in CHURCH_BUILDINGS and religion in (None, "christian"):
        return "church"
    if tags.get("man_made") == "campanile" or (
            tags.get("man_made") == "tower" and tags.get("tower:type") in ("bell_tower", "campanile")):
        return "tower"
    if classify.shape_key(tags):
        return "part"
    return None


def parse_height(value: str | None) -> float | None:
    if not value:
        return None
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(m|meter|metres?)?\s*$", value.strip(), re.I)
    return float(m.group(1).replace(",", ".")) if m else None


def _position(el: dict):
    if "lat" in el:
        return el["lat"], el["lon"]
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else None


def _richness(r: dict) -> float:
    t = r["tags"]
    return (100 * ("wikidata" in t or "wikipedia" in t) + 50 * ("name" in t)
            + 10 * (not r["id"].startswith("node")) + len(t))


def _names_compatible(a: dict, b: dict) -> bool:
    sim = geo.name_similarity(a["tags"].get("name"), b["tags"].get("name"))
    return sim is None or sim >= 0.5


def build_records(elements_by_country: dict[str, list[dict]], cfg: dict) -> tuple[list[dict], dict]:
    """Returns (records, stats). `elements_by_country` keeps config order: an object
    returned for two countries (border) belongs to the first."""
    churches, towers, parts = [], [], []
    seen: set[str] = set()
    for iso, elements in elements_by_country.items():
        for el in elements:
            oid = f"{el['type']}/{el['id']}"
            tags = el.get("tags") or {}
            kind = kind_of(tags)
            pos = _position(el)
            if oid in seen or kind is None or pos is None:
                continue
            seen.add(oid)
            item = {"id": oid, "ids": [oid], "lat": round(pos[0], 6), "lon": round(pos[1], 6),
                    "cc": iso, "kind": kind, "tags": tags, "near": []}
            (churches if kind == "church" else towers if kind == "tower" else parts).append(item)
    stats = {"osm_objects": len(seen), "raw_churches": len(churches), "raw_towers": len(towers),
             "raw_roof_parts": len(parts)}

    # 1. the same church mapped twice (node + building, building + relation …)
    r_dedupe, r_attach = cfg["dedupe_radius_m"], cfg["attach_radius_m"]
    grid = geo.Grid(max(r_dedupe, r_attach))
    primaries: list[dict] = []
    for rec in sorted(churches, key=_richness, reverse=True):
        best = None
        for d, other in grid.near(rec["lat"], rec["lon"], r_dedupe):
            if _names_compatible(rec, other) and (best is None or d < best[0]):
                best = (d, other)
        if best:
            target = best[1]
            target["ids"].append(rec["id"])
            for k, v in rec["tags"].items():
                target["tags"].setdefault(k, v)
        else:
            primaries.append(rec)
            grid.add(rec["lat"], rec["lon"], rec)
    stats["duplicates_merged"] = len(churches) - len(primaries)

    # 2. bell towers: attach to the nearest church, otherwise they are a dot of their own
    def nearest(item):
        hits = sorted(grid.near(item["lat"], item["lon"], r_attach), key=lambda h: h[0])
        return hits[0] if hits else None

    standalone = 0
    for t in towers:
        hit = nearest(t)
        if hit:
            hit[1]["near"].append({"id": t["id"], "dist": round(hit[0]), "tags": t["tags"]})
        else:
            primaries.append(t)
            grid.add(t["lat"], t["lon"], t)
            standalone += 1
    stats["standalone_towers"] = standalone

    # 3. roof parts (onion / dome roofs, tower building parts)
    orphan_onions = 0
    for p in parts:
        hit = nearest(p)
        if hit:
            hit[1]["near"].append({"id": p["id"], "dist": round(hit[0]), "tags": p["tags"]})
        elif classify.shape_key(p["tags"]) == "onion":
            orphan_onions += 1
    stats["onion_roofs_without_church"] = orphan_onions

    for rec in primaries:
        rec["near"].sort(key=lambda a: a["dist"])
        classify.classify_osm(rec)
        t = rec["tags"]
        for key in ("description", "description:de"):
            if t.get(key):
                hit = classify.parse_german(t[key])
                if "cat" in hit:
                    classify.combine_with_text(rec, hit["cat"], hit["phrase"], f"OSM {key}")
                    stats["roof_from_osm_description"] = stats.get("roof_from_osm_description", 0) + 1
                if hit.get("building_roof") and not rec.get("building_roof"):
                    rec["building_roof"] = hit["building_roof"]
        rec["name"] = t.get("name") or t.get("name:de") or t.get("alt_name")
        rec["year"] = next((t[k] for k in YEAR_KEYS if t.get(k)), None)
        heights = [parse_height(t.get(k)) for k in HEIGHT_KEYS]
        heights += [parse_height(a["tags"].get(k)) for a in rec["near"] for k in HEIGHT_KEYS]
        heights = [h for h in heights if h]
        rec["height"] = max(heights) if heights else None
    stats["records"] = len(primaries)
    return primaries, stats


def apply_overrides(records: list[dict], rows: list[dict]) -> int:
    """Manual / external classifications (data/overrides.csv) win over everything."""
    by_id = {i: r for r in records for i in r["ids"]}
    n = 0
    for row in rows:
        rec = by_id.get((row.get("osm_id") or "").strip())
        roof = (row.get("roof") or "").strip()
        if rec is None or roof not in classify.CAT_INDEX:
            continue
        # sub / n_onion / sub_text came from the old roof type; a stale one makes the card contradict the dot
        rec.update(roof=roof, sub=roof if classify.CATEGORIES[classify.CAT_INDEX[roof]]["bulbous"] else None)
        rec.pop("sub_text", None)
        if roof != "onion":
            rec.pop("n_onion", None)
        rec["src"] = [f"Override ({row.get('source') or 'manual'})" + (f": {row['note']}" if row.get("note") else "")]
        n += 1
    return n


MODEL_CLASSES = ("onion", "welsch", "other")          # what the photo model can say about a tower roof
MODEL_FAMILY = {"onion": "onion", "onion_double": "onion", "welsch": "welsch", "other": "other"}


def apply_predictions(records: list[dict], rows: list[dict], min_conf: float = 0.9,
                      protect: tuple | list = ("dome",)) -> dict:
    """The photo model's result (data/predictions.csv) replaces the roof type found from OSM tags or article
    text when its confidence is at least `min_conf`. Manual overrides (data/overrides.csv) are applied afterwards
    and still win. The model was trained without double onions and domes, so:
      - a prediction in the same family as the current type (onion / double onion) keeps the more specific type
        and only adds a note,
      - the types in `protect` (default: dome) are never overwritten,
      - "no_tower" (the photo shows no tower) is ignored.
    Every change is written to the source list of the church, so the info card shows where the type came from."""
    by_id = {i: r for r in records for i in r["ids"]}
    stats = {"seen": 0, "filled": 0, "overwritten": 0, "confirmed": 0, "protected": 0}
    for row in rows:
        roof = (row.get("roof") or "").strip()
        if roof not in MODEL_CLASSES:
            continue
        try:
            conf = float((row.get("confidence") or "").replace(",", "."))
        except ValueError:
            continue
        rec = by_id.get((row.get("osm_id") or "").strip())
        if rec is None or conf < min_conf:
            continue
        stats["seen"] += 1
        cur = rec["roof"]
        label = classify.CATEGORIES[classify.CAT_INDEX[roof]]["de"]
        note = f"Modell (Foto): {label}, {conf * 100:.0f} %"
        src = rec.setdefault("src", [])
        if MODEL_FAMILY.get(cur) == roof:
            stats["confirmed"] += 1
            src.append(note + " – bestätigt")
            continue
        if cur in protect:
            stats["protected"] += 1
            src.append(note + f" – nicht angewendet ({cur} ist geschützt)")
            continue
        old = classify.CATEGORIES[classify.CAT_INDEX[cur]]["de"]
        rec.update(roof=roof, sub=roof if classify.CATEGORIES[classify.CAT_INDEX[roof]]["bulbous"] else None)
        rec.pop("sub_text", None)
        if roof != "onion":
            rec.pop("n_onion", None)
        if cur == "unknown":
            stats["filled"] += 1
            src.append(note)
        else:
            stats["overwritten"] += 1
            src.append(note + f" – ersetzt: {old}")
    return stats
