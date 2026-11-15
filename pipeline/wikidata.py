"""Wikipedia / Wikidata / Commons merge for the configured regions.

For each enabled region:
  1. OSM: bounding box of the region and the ids of the churches inside it.
  2. Wikidata: all church items (configured classes incl. subclasses) with
     coordinates in that box, plus every item referenced by an OSM `wikidata` tag.
  3. Match by coordinates (nearest OSM church within the radius, name as
     tie-break); an OSM `wikidata` tag is an exact match and wins.
  4. Per matched item: statements, Wikipedia article links + intro, Commons
     photo with author and licence, and a roof-type hint from the article text.
"""
from __future__ import annotations

import hashlib
import html
import re
import shutil
import urllib.parse
from pathlib import Path

from . import classify, geo, net, osm

SPARQL = "https://query.wikidata.org/sparql"
WD_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _get(cache: Path, base: str, params: dict):
    return net.cached_json(cache, base + "?" + urllib.parse.urlencode(params), min_interval=1.0)


# ---------- Wikidata ----------

def sparql_candidates(cache: Path, bbox, classes, languages) -> list[dict]:
    w, s, e, n = bbox
    values = " ".join(f"wd:{c}" for c in classes)
    q = f"""SELECT DISTINCT ?item ?itemLabel ?loc WHERE {{
  SERVICE wikibase:box {{
    ?item wdt:P625 ?loc .
    bd:serviceParam wikibase:cornerSouthWest "Point({w} {s})"^^geo:wktLiteral ;
                    wikibase:cornerNorthEast "Point({e} {n})"^^geo:wktLiteral .
  }}
  VALUES ?cls {{ {values} }}
  ?item wdt:P31/wdt:P279* ?cls .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{','.join(languages)}". }}
}}"""
    data = _get(cache, SPARQL, {"query": q, "format": "json"})
    out = {}
    for b in data["results"]["bindings"]:
        m = re.match(r"Point\(([-\d.eE]+) ([-\d.eE]+)\)", b["loc"]["value"])
        if not m:
            continue
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        out.setdefault(qid, {"qid": qid, "label": b.get("itemLabel", {}).get("value"),
                             "lon": float(m.group(1)), "lat": float(m.group(2))})
    return list(out.values())


def get_entities(cache: Path, ids, languages, labels_only=False) -> dict:
    store = net.Store(cache / ("store-labels.json.gz" if labels_only else "store-entities.json.gz"))
    ids = sorted(set(ids))
    for batch in _chunks(store.missing(ids), 50):
        data = _get(cache, WD_API, {"action": "wbgetentities", "ids": "|".join(batch),
                                    "props": "labels" if labels_only else "labels|descriptions|claims|sitelinks",
                                    "languages": "|".join(languages), "format": "json"})
        got = data.get("entities") or {}
        for k in batch:
            v = got.get(k)
            store.data[k] = None if v is None or "missing" in v else v
        store.save()
    return {k: store.data[k] for k in ids if store.data.get(k)}


def _best_statements(entity: dict, pid: str) -> list[dict]:
    claims = [c for c in entity.get("claims", {}).get(pid, [])
              if c.get("rank") != "deprecated" and c["mainsnak"].get("snaktype") == "value"]
    preferred = [c for c in claims if c.get("rank") == "preferred"]
    return preferred or claims


def _format_time(v: dict, lang: str) -> str:
    m = re.match(r"([+-])(\d+)-(\d\d)-(\d\d)", v["time"])
    if not m:
        return v["time"]
    year, month, day = int(m.group(2)), int(m.group(3)), int(m.group(4))
    era = (" v. Chr." if lang == "de" else " BC") if m.group(1) == "-" else ""
    p = v.get("precision", 9)
    if p >= 11:
        return (f"{day}.{month}.{year}" if lang == "de" else f"{year}-{month:02d}-{day:02d}") + era
    if p == 10:
        return f"{month}/{year}{era}"
    if p == 9:
        return f"{year}{era}"
    if p == 8:
        return (f"{year // 10 * 10}er Jahre" if lang == "de" else f"{year // 10 * 10}s") + era
    if p == 7:
        c = (year - 1) // 100 + 1
        return (f"{c}. Jahrhundert" if lang == "de" else f"{c}th century") + era
    return f"{year}{era}"


def _value(snak: dict, lang: str, labels: dict) -> str | None:
    dv = snak.get("datavalue")
    if not dv:
        return None
    v, t = dv["value"], dv["type"]
    if t == "wikibase-entityid":
        return labels.get(v["id"], {}).get(lang)   # no label in the configured languages → value is left out
    if t == "time":
        return _format_time(v, lang)
    if t == "quantity":
        amount = v["amount"].lstrip("+")
        if lang == "de":
            amount = amount.replace(".", ",")
        unit = v.get("unit", "1").rsplit("/", 1)[-1]
        if unit in ("Q11573",):
            return f"{amount} m"
        return amount if unit == "1" else f"{amount} {labels.get(unit, {}).get(lang) or ''}".strip()
    if t == "monolingualtext":
        return v["text"]
    if t == "string":
        return v
    return None


def _label_map(entities: dict, languages) -> dict:
    out = {}
    for k, e in entities.items():
        lab = e.get("labels", {})
        fallback = next(iter(lab.values()), {}).get("value")
        out[k] = {l: lab.get(l, {}).get("value") or lab.get("en", {}).get("value") or fallback
                  for l in languages}
    return out


# ---------- Commons ----------

def _strip_html(s: str | None) -> str | None:
    if not s:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip() or None


def download_photo(url: str, cache_dir: Path, out_dir: Path) -> str | None:
    """Stores a thumbnail next to the data files, so the page needs no third-party requests."""
    ext = url.rsplit(".", 1)[-1].lower().split("?")[0]
    name = hashlib.sha1(url.encode()).hexdigest()[:16] + "." + (ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg")
    cached = cache_dir / "photos" / name
    try:
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(net.fetch_retry(url, timeout=60, tries=8, min_interval=1.0))
        (out_dir / "img").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached, out_dir / "img" / name)
        return "img/" + name
    except Exception as e:   # the card then falls back to the Commons URL
        print(f"    photo not downloaded ({str(e)[:80]})")
        return None


def commons_images(cache: Path, files, width: int = 500) -> dict:
    """{file name: {thumb, page, author, license, license_url}}"""
    store = net.Store(cache / f"store-commons-{width}.json.gz")
    files = sorted(set(files))
    for batch in _chunks(store.missing(files), 40):
        data = _get(cache, COMMONS_API, {
            "action": "query", "titles": "|".join("File:" + f for f in batch), "prop": "imageinfo",
            "iiprop": "url|extmetadata", "iiurlwidth": width,
            "iiextmetadatafilter": "Artist|LicenseShortName|LicenseUrl|Credit|AttributionRequired",
            "format": "json", "formatversion": 2})
        q = data.get("query", {})
        back = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for f in batch:
            store.data[f] = None
        for page in q.get("pages", []):
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            meta = {k: v.get("value") for k, v in (info.get("extmetadata") or {}).items()}
            asked = back.get(page["title"], page["title"]).split(":", 1)[1]
            store.data[asked] = {
                "thumb": info.get("thumburl") or info.get("url"),
                "page": info.get("descriptionurl"),
                "author": _strip_html(meta.get("Artist")) or _strip_html(meta.get("Credit")),
                "license": _strip_html(meta.get("LicenseShortName")),
                "license_url": meta.get("LicenseUrl"),
            }
        store.save()
    return {f: dict(store.data[f]) for f in files if store.data.get(f)}


# ---------- Wikipedia ----------

def _wp_query(cache: Path, lang: str, params: dict) -> list[dict]:
    """MediaWiki query with continuation; returns all `pages` objects."""
    pages, cont = [], {}
    while True:
        data = _get(cache, f"https://{lang}.wikipedia.org/w/api.php",
                    {"action": "query", "redirects": 1, "format": "json", "formatversion": 2, **params, **cont})
        pages += data.get("query", {}).get("pages", [])
        if "continue" not in data:
            return pages
        cont = data["continue"]


def articles(cache: Path, lang: str, titles) -> dict[str, dict]:
    """{page title: {"intro": plain-text intro, "text": wikitext}} – fetched in batches,
    because Wikimedia throttles anonymous clients to a few requests per minute."""
    store = net.Store(cache / f"store-articles-{lang}.json.gz")
    titles = sorted(set(titles))
    for batch in _chunks(store.missing(titles), 20):
        joined = "|".join(batch)
        got: dict[str, dict] = {t: {} for t in batch}
        for p in _wp_query(cache, lang, {"prop": "extracts", "exintro": 1, "explaintext": 1,
                                         "exlimit": "max", "titles": joined}):
            if p.get("extract"):
                got.setdefault(p["title"], {})["intro"] = p["extract"]
        for p in _wp_query(cache, lang, {"prop": "revisions", "rvprop": "content", "rvslots": "main",
                                         "titles": joined}):
            rev = (p.get("revisions") or [None])[0]
            if rev:
                got.setdefault(p["title"], {})["text"] = rev.get("slots", {}).get("main", {}).get("content", "")
        store.data.update(got)
        store.save()
    return {t: store.data[t] for t in titles if store.data.get(t)}


def _intro(text: str, limit=420) -> str | None:
    first = text.split("\n\n==")[0].split("\n==")[0].strip()
    first = re.sub(r"\s+", " ", first)
    if not first:
        return None
    if len(first) <= limit:
        return first
    cut = first[:limit]
    return cut[:cut.rfind(" ")] + " …"


def _article_url(lang: str, title: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="/:(),")


# ---------- matching ----------

def match(candidates: list[dict], records: list[dict], radius_m: float) -> dict[str, dict]:
    """Greedy one-to-one match by coordinates. Returns {record id: candidate}."""
    grid = geo.Grid(radius_m)
    for r in records:
        grid.add(r["lat"], r["lon"], r)
    pairs = []
    for c in candidates:
        for d, r in grid.near(c["lat"], c["lon"], radius_m):
            sim = geo.name_similarity(c.get("label"), r.get("name"))
            # a clear name match beats a nearer neighbour; a clear mismatch goes last.
            # Without a confirming name the object must be practically on the same spot.
            tier = 0 if (sim is not None and sim >= 0.5) else 1 if sim is None else 2
            if d > (radius_m, radius_m / 3, radius_m / 5)[tier]:
                continue
            pairs.append((tier, d, c["qid"], r["id"], c, r))
    pairs.sort(key=lambda p: p[:4])
    used_q, result = set(), {}
    for tier, d, qid, rid, c, r in pairs:
        if qid in used_q or rid in result:
            continue
        used_q.add(qid)
        result[rid] = {**c, "dist": round(d), "how": "coordinates"}
    return result


def _qid(value: str | None) -> str | None:
    m = re.match(r"\s*(Q\d+)", value or "")
    return m.group(1) if m else None


def enrich_region(region: dict, records: list[dict], wcfg: dict, osm_cfg: dict, cache_dir: Path,
                  out_dir: Path, refresh=False) -> dict:
    """Adds `wd` (and possibly a roof type) to the records inside the region. Returns stats."""
    cache = cache_dir / "wiki"
    languages = wcfg["languages"]
    info = osm.fetch_region(osm_cfg, region, cache_dir, refresh)
    in_region = set(info["ids"])
    local = [r for r in records if in_region.intersection(r["ids"])]

    # exact matches through the OSM wikidata tag
    assigned: dict[str, dict] = {}
    for r in local:
        q = _qid(r["tags"].get("wikidata"))
        if q:
            assigned[r["id"]] = {"qid": q, "how": "OSM wikidata tag", "dist": None}
    taken = {a["qid"] for a in assigned.values()}
    skip = re.compile("|".join(wcfg.get("exclude_labels") or ["$^"]), re.I)
    candidates = [c for c in sparql_candidates(cache, info["bbox"], wcfg["classes"], languages)
                  if c["qid"] not in taken and not skip.search(c.get("label") or "")]
    free = [r for r in local if r["id"] not in assigned]
    assigned.update(match(candidates, free, wcfg["match_radius_m"]))

    entities = get_entities(cache, [a["qid"] for a in assigned.values()], languages)
    props = wcfg["properties"]
    refs = set(props)
    for e in entities.values():
        for pid in props:
            for c in _best_statements(e, pid):
                dv = c["mainsnak"].get("datavalue", {})
                if dv.get("type") == "wikibase-entityid":
                    refs.add(dv["value"]["id"])
                elif dv.get("type") == "quantity" and "/" in dv["value"].get("unit", ""):
                    refs.add(dv["value"]["unit"].rsplit("/", 1)[-1])
    labels = _label_map(get_entities(cache, refs, languages, labels_only=True), languages)

    files = {}
    for r in local:
        a = assigned.get(r["id"])
        e = entities.get(a["qid"]) if a else None
        f = None
        if e:
            st = _best_statements(e, "P18")
            f = st[0]["mainsnak"]["datavalue"]["value"] if st else None
        if not f:
            tag = r["tags"].get("wikimedia_commons", "")
            f = tag.split(":", 1)[1] if tag.lower().startswith("file:") else None
        if f:
            files[r["id"]] = f.replace("_", " ")
    images = commons_images(cache, files.values(), wcfg.get("photo_width", 500))
    if wcfg.get("download_photos", True):
        for img in images.values():
            if img.get("thumb"):
                saved = download_photo(img["thumb"], cache_dir, out_dir)
                if saved:
                    img["local"] = saved

    texts = {l: articles(cache, l, [t for t in (e.get("sitelinks", {}).get(f"{l}wiki", {}).get("title")
                                                for e in entities.values()) if t]) for l in languages}

    stats = {"id": region["id"], "label": region["label"], "bbox": info["bbox"], "churches": len(local),
             "matched": 0, "by_tag": 0, "by_coordinates": 0, "with_article": 0, "with_photo": 0,
             "roof_from_text": 0}
    for r in local:
        a = assigned.get(r["id"])
        e = entities.get(a["qid"]) if a else None
        img = images.get(files.get(r["id"], ""))
        if not e:
            if img:
                r["wd"] = {"image": img}
                stats["with_photo"] += 1
            continue
        stats["matched"] += 1
        stats["by_tag" if a["how"] != "coordinates" else "by_coordinates"] += 1
        wd = {"qid": a["qid"], "how": a["how"], "dist": a["dist"],
              "label": {l: e.get("labels", {}).get(l, {}).get("value") for l in languages},
              "desc": {l: e.get("descriptions", {}).get(l, {}).get("value") for l in languages},
              "facts": {}, "wikipedia": {}}
        for l in languages:
            rows = []
            for pid in props:
                vals = [v for v in (_value(c["mainsnak"], l, labels) for c in _best_statements(e, pid)) if v]
                if vals:
                    name = labels.get(pid, {}).get(l) or pid
                    rows.append([name[:1].upper() + name[1:], ", ".join(dict.fromkeys(vals))])
            wd["facts"][l] = rows
            title = e.get("sitelinks", {}).get(f"{l}wiki", {}).get("title")
            if title:
                wd["wikipedia"][l] = _article_url(l, title)
        st = _best_statements(e, "P373")
        if st:
            wd["commons_category"] = st[0]["mainsnak"]["datavalue"]["value"]
        if img:
            wd["image"] = img
            stats["with_photo"] += 1
        # article: intro for the card, keywords for the roof type
        before = r["roof"]
        for l in languages:
            title = e.get("sitelinks", {}).get(f"{l}wiki", {}).get("title")
            art = texts[l].get(title) if title else None
            if not art:
                continue
            if "intro" not in wd and art.get("intro"):
                wd["intro"] = {"lang": l, "text": _intro(art["intro"])}
            hit = classify.classify_text(art.get("text") or art.get("intro") or "", l)
            if hit:
                classify.combine_with_text(r, hit[0], hit[1], l)
                break
        if wd["wikipedia"]:
            stats["with_article"] += 1
        if r["roof"] != before:
            stats["roof_from_text"] += 1
        # fill gaps in the headline fields from Wikidata
        if not r.get("year"):
            st = _best_statements(e, "P571")
            if st:
                r["year"] = _value(st[0]["mainsnak"], languages[0], labels)
        if not r.get("height"):
            st = _best_statements(e, "P2048")
            if st:
                try:
                    r["height"] = float(st[0]["mainsnak"]["datavalue"]["value"]["amount"])
                except (KeyError, ValueError):
                    pass
        if not r.get("name"):
            r["name"] = wd["label"].get(languages[0]) or wd["label"].get("en")
        r["wd"] = wd
    return stats
