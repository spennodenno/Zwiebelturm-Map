"""Offline stand-ins for Overpass, Wikidata, Commons and Wikipedia.

All objects here are INVENTED test data (ids 1–99, Q900001 …). They exist only
to exercise the pipeline without network access.
"""
import json
import re
import urllib.parse


def node(i, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {k.replace("__", ":"): v for k, v in tags.items()}}


def way(i, lat, lon, **tags):
    return {"type": "way", "id": i, "center": {"lat": lat, "lon": lon},
            "tags": {k.replace("__", ":"): v for k, v in tags.items()}}


M = 1 / 111320  # one metre in degrees latitude

ELEMENTS = [
    way(1, 47.8000, 11.0000, building="church", name="St. Test", wikidata="Q900001"),
    node(2, 47.8000 + 12 * M, 11.0000, amenity="place_of_worship", religion="christian",
         name="Sankt Test", denomination="catholic", start_date="1735"),
    way(3, 47.8000 + 20 * M, 11.0001, building__part="yes", roof__shape="onion", height="41,5 m"),
    way(4, 47.8200, 11.0300, building="church", name="St. Georg", amenity="place_of_worship", religion="christian"),
    way(5, 47.8400, 11.0500, building="chapel"),
    node(6, 47.8400 + 30 * M, 11.0500, man_made="tower", tower__type="bell_tower", roof__shape="pyramidal"),
    node(7, 47.9000, 11.1000, man_made="tower", tower__type="bell_tower", roof__shape="gabled", name="Campanile Test"),
    way(8, 47.7000, 10.9000, building="yes", roof__shape="onion"),
    way(9, 47.8600, 11.0700, building="church", name="Heilig Kreuz", roof__shape="gabled",
        amenity="place_of_worship", religion="christian", wikimedia_commons="File:Test_kreuz.jpg"),
    way(10, 48.9000, 12.5000, building="church", name="Outside", roof__shape="dome"),
    way(11, 47.8100, 11.0100, building="church", religion="muslim", amenity="place_of_worship"),
    way(12, 47.8700, 11.0800, building="church", name="Mariä Himmelfahrt", amenity="place_of_worship", religion="christian"),
]
REGION_IDS = [("way", 1), ("node", 2), ("way", 4), ("way", 5), ("node", 6), ("node", 7), ("way", 9), ("way", 12)]

ENTITIES = {
    "Q900001": {"labels": {"de": {"value": "St. Test"}, "en": {"value": "St Test's Church"}},
                "descriptions": {"de": {"value": "Kirche in Testdorf"}},
                "sitelinks": {"dewiki": {"title": "St. Test (Testdorf)"}},
                "claims": {
                    "P18": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "string", "value": "Test church.jpg"}}}],
                    "P571": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "time", "value": {"time": "+1735-00-00T00:00:00Z", "precision": 9}}}}],
                    "P2048": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "quantity", "value": {"amount": "+41.5", "unit": "http://www.wikidata.org/entity/Q11573"}}}}],
                    "P149": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "wikibase-entityid", "value": {"id": "Q900100"}}}}],
                    "P373": [{"rank": "normal", "mainsnak": {"snaktype": "value", "datavalue": {"type": "string", "value": "St. Test (Testdorf)"}}}],
                }},
    "Q900002": {"labels": {"de": {"value": "St. Georg"}}, "descriptions": {},
                "sitelinks": {"dewiki": {"title": "St. Georg (Testdorf)"}}, "claims": {}},
    "Q900003": {"labels": {"de": {"value": "Mariä Himmelfahrt"}}, "descriptions": {},
                "sitelinks": {"dewiki": {"title": "Mariä Himmelfahrt (Testdorf)"}}, "claims": {}},
    "Q900100": {"labels": {"de": {"value": "Barock"}, "en": {"value": "Baroque"}}},
    "P571": {"labels": {"de": {"value": "Gründung, Erstellung bzw. Entstehung"}, "en": {"value": "inception"}}},
    "P2048": {"labels": {"de": {"value": "Höhe"}, "en": {"value": "height"}}},
    "P149": {"labels": {"de": {"value": "Architekturstil"}, "en": {"value": "architectural style"}}},
    "Q11573": {"labels": {"de": {"value": "Meter"}, "en": {"value": "metre"}}},
}
SPARQL_ROWS = [("Q900001", "St. Test", 11.0002, 47.8001), ("Q900002", "St. Georg", 11.0304, 47.8203),
               ("Q900003", "Mariä Himmelfahrt", 11.0801, 47.8701), ("Q900004", "Far away chapel", 11.5, 47.5)]
ARTICLES = {
    "St. Test (Testdorf)": "St. Test ist eine Kirche in Testdorf.\n\n== Geschichte ==\nErbaut 1735.",
    "St. Georg (Testdorf)": "St. Georg ist eine Pfarrkirche.\n\n== Architektur ==\nDer Turm trägt eine Doppelzwiebelhaube.",
    "Mariä Himmelfahrt (Testdorf)": "Die Kirche hat einen Turm mit welscher Haube und Laterne.",
}

calls = {"overpass": 0, "split_forced": False}
extra_elements = []          # the synthetic generator appends here
fail_big_cells_once = False  # test for the automatic split


def fetch(url, data=None, timeout=0):
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(parts.query)
    if "interpreter" in url:
        calls["overpass"] += 1
        ql = data["data"]
        if "map_to_area" in ql:
            els = [{"type": "relation", "id": 99, "bounds": {"minlat": 47.6, "minlon": 10.7, "maxlat": 48.0, "maxlon": 11.3}}]
            els += [{"type": t, "id": i} for t, i in REGION_IDS]
            return json.dumps({"elements": els}).encode()
        s, w, n, e = map(float, re.search(r"\(area\.c\)\(([-\d.,]+)\)", ql).group(1).split(","))
        iso = re.search(r'"ISO3166-1"="(\w+)"', ql).group(1)
        if fail_big_cells_once and not calls["split_forced"] and n - s > 1.5:
            calls["split_forced"] = True
            return json.dumps({"elements": [], "remark": "runtime error: Query timed out"}).encode()
        out = []
        for el in ELEMENTS + extra_elements:
            if el.get("_cc", "DE") != iso:
                continue
            c = el.get("center") or el
            if s <= c["lat"] <= n and w <= c["lon"] <= e:
                out.append({k: v for k, v in el.items() if k != "_cc"})
        return json.dumps({"elements": out}).encode()
    if "sparql" in url:
        return json.dumps({"results": {"bindings": [
            {"item": {"value": "http://www.wikidata.org/entity/" + qid}, "itemLabel": {"value": label},
             "loc": {"value": f"Point({lon} {lat})"}} for qid, label, lon, lat in SPARQL_ROWS]}}).encode()
    if "wikidata.org/w/api.php" in url:
        return json.dumps({"entities": {i: ENTITIES.get(i, {"missing": ""}) for i in q["ids"][0].split("|")}}).encode()
    if "commons.wikimedia.org" in url:
        pages, norm = [], []
        for t in q["titles"][0].split("|"):
            pages.append({"title": t, "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/thumb/" + t.split(":")[1].replace(" ", "_"),
                "descriptionurl": "https://commons.wikimedia.org/wiki/" + t.replace(" ", "_"),
                "extmetadata": {"Artist": {"value": '<a href="//commons.wikimedia.org/wiki/User:T">Test&nbsp;Author</a>'},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}]})
        return json.dumps({"query": {"pages": pages, "normalized": norm}}).encode()
    if "upload.wikimedia.org" in url:
        return b"\xff\xd8fake-jpeg"
    if "wikipedia.org/w/api.php" in url:
        pages = []
        for t in q["titles"][0].split("|"):
            text = ARTICLES.get(t, "")
            if q["prop"][0] == "extracts":
                pages.append({"title": t, "extract": text.split("\n\n==")[0]})
            else:
                pages.append({"title": t, "revisions": [{"slots": {"main": {"content": text}}}]})
        return json.dumps({"query": {"pages": pages}}).encode()
    raise AssertionError("unexpected URL " + url)
