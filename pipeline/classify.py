"""Roof-type categories and the rules that assign them.

The category index is what the front end receives per point; the list order is
also the drawing order (later = on top). To add a category, append it here and
add rules below – the front end reads labels and colours from the manifest.
"""
from __future__ import annotations

import re

CATEGORIES = [
    {"key": "unknown", "color": "#3f4955", "bulbous": False,
     "de": "Turmdach nicht erfasst", "en": "Tower roof not recorded"},
    {"key": "other", "color": "#8d97a3", "bulbous": False,
     "de": "Andere Turmform (Spitzhelm, Satteldach …)", "en": "Other tower type (spire, saddleback …)"},
    {"key": "dome", "color": "#2fd0c8", "bulbous": True,
     "de": "Kuppel", "en": "Dome"},
    {"key": "welsch", "color": "#b388ff", "bulbous": True,
     "de": "Welsche Haube / Laternenhaube", "en": "Welsch cap / lantern cap"},
    {"key": "onion", "color": "#ffb000", "bulbous": True,
     "de": "Zwiebelhaube", "en": "Onion dome"},
    {"key": "onion_double", "color": "#ff3d7f", "bulbous": True,
     "de": "Doppelzwiebel", "en": "Double onion dome"},
]
CAT_INDEX = {c["key"]: i for i, c in enumerate(CATEGORIES)}
# How specific a bulbous label is; the more specific one wins when sources differ.
SPECIFICITY = {"dome": 1, "welsch": 2, "onion": 3, "onion_double": 4}

# OSM roof:shape values -> display names (for the info card)
SHAPE_LABELS = {
    "onion": {"de": "Zwiebelhaube", "en": "onion dome"},
    "dome": {"de": "Kuppel", "en": "dome"},
    "pyramidal": {"de": "Pyramidendach / Spitzhelm", "en": "pyramidal roof / spire"},
    "cone": {"de": "Kegeldach", "en": "conical roof"},
    "spire": {"de": "Spitzhelm", "en": "spire"},
    "gabled": {"de": "Satteldach", "en": "gabled (saddleback) roof"},
    "hipped": {"de": "Walmdach", "en": "hipped roof"},
    "half-hipped": {"de": "Krüppelwalmdach", "en": "half-hipped roof"},
    "crosspitched": {"de": "Kreuzdach", "en": "cross-gabled roof"},
    "flat": {"de": "Flachdach", "en": "flat roof"},
    "skillion": {"de": "Pultdach", "en": "skillion roof"},
    "mansard": {"de": "Mansarddach", "en": "mansard roof"},
    "gambrel": {"de": "Mansardgiebeldach", "en": "gambrel roof"},
    "round": {"de": "Tonnendach", "en": "barrel roof"},
    "saltbox": {"de": "Schleppdach", "en": "saltbox roof"},
}

OSM_SHAPE_TO_CAT = {"onion": "onion", "dome": "dome"}  # every other value -> "other"


def shape_key(tags: dict) -> str | None:
    v = tags.get("roof:shape") or tags.get("building:roof:shape")
    return v.strip().lower() if v else None


def is_tower_object(tags: dict) -> bool:
    """Objects whose roof:shape describes a tower (not a nave)."""
    if tags.get("man_made") in ("tower", "campanile"):
        return True
    if tags.get("tower:type") in ("bell_tower", "campanile"):
        return True
    bp = tags.get("building:part", "")
    return any(w in bp for w in ("tower", "steeple", "spire", "belfry"))


def classify_osm(record: dict) -> None:
    """Sets roof / sub / src on a merged record from OSM evidence only.

    Rules, strongest first:
      1. any onion roof on the church itself or an attached object  -> onion
      2. any dome                                                   -> dome
      3. a tower object (bell tower, tower building part) with
         another roof shape                                         -> other (+ sub = shape)
      4. nothing usable                                             -> unknown
    A non-bulbous roof:shape on the church building itself describes the nave,
    not the tower, so it is shown in the card but does not classify the tower.
    """
    bulbous: list[tuple[str, str]] = []   # (shape, source text)
    tower: list[tuple[str, str]] = []
    own = shape_key(record["tags"])
    if own:
        src = f"OSM {record['id']}: roof:shape={own}"
        if own in OSM_SHAPE_TO_CAT:
            bulbous.append((own, src))
        elif record["kind"] == "tower" or is_tower_object(record["tags"]):
            tower.append((own, src))
    for a in record.get("near", []):
        s = shape_key(a["tags"])
        if not s:
            continue
        src = f"OSM {a['id']}: roof:shape={s} ({a['dist']} m)"
        if s in OSM_SHAPE_TO_CAT:
            bulbous.append((s, src))
        elif is_tower_object(a["tags"]):
            tower.append((s, src))
    onions = [b for b in bulbous if b[0] == "onion"]
    if onions:
        record.update(roof="onion", sub="onion", src=[s for _, s in onions], n_onion=len(onions))
    elif bulbous:
        record.update(roof="dome", sub="dome", src=[s for _, s in bulbous])
    elif tower:
        record.update(roof="other", sub=tower[0][0], src=[s for _, s in tower])
    else:
        record.update(roof="unknown", sub=None, src=[])


# ---------- text heuristics (Wikipedia article text) ----------
# Checked in order; first hit per language wins. de/en are the tuned ones, the
# other languages are a starting vocabulary for when their regions are enabled.
KEYWORDS: dict[str, list[tuple[str, str]]] = {
    "de": [
        ("onion_double", r"doppelzwiebel|doppelte[rnm]? zwiebel"),
        ("onion", r"zwiebel(turm|türm|haube|helm|kuppel|dach|spitze|förmig|bekrön)|\bzwiebel\b"),
        ("welsch", r"welsche[rnms]? haube|welschhaube|laternenhaube|glockenhaube|haubendach|"
                   r"barocke[rnm]? haube|kuppelhaube|turmhaube|haubenhelm"),
        ("other", r"spitzhelm|spitzturm|pyramidenhelm|pyramidendach|rautenhelm|rhombendach|"
                  r"faltdach|zeltdach|sattelturm|satteldachturm|satteldach|treppengiebel|"
                  r"dachreiter|turmhelm|helmdach|nadelhelm"),
    ],
    "en": [
        ("onion_double", r"double onion"),
        ("onion", r"onion[- ]dome|onion[- ]shaped|onion[- ]domed|onion spire|onion tower"),
        ("welsch", r"welsch (hood|cap|dome)|bell[- ]shaped (dome|cap|roof)|lantern cupola"),
        ("other", r"\bspire\b|gabled tower|saddleback|pyramidal roof|rhenish helm"),
    ],
    "it": [("onion", r"cupola a cipolla|a bulbo|cuspide a cipolla")],
    "fr": [("onion", r"clocher[- ]à[- ]bulbe|bulbe|bulbeux|en oignon")],
    "cs": [("onion", r"cibulov|cibulí")],
    "pl": [("onion", r"cebulast|hełm cebul")],
    "sl": [("onion", r"čebulast")],
    "hu": [("onion", r"hagymasisak|hagymakupol")],
}


# --- German: tower-aware parsing -------------------------------------------------
# The question is always the roof of the TOWER. A nave with a Satteldach and a tower
# with a Zwiebelhaube must come out as onion, so the rules are, strongest first:
#   1. a bulbous term anywhere (Zwiebel…, welsche Haube …) – these words only ever
#      describe towers or ridge turrets                                -> bulbous, locked
#   2. a term that only exists for towers (Spitzhelm, Sattelturm …)    -> other
#   3. a general roof word (Satteldach, Pultdach …) only when it stands in the same
#      clause as a tower word ("Chorturm mit Satteldach")              -> other
#   4. a general roof word elsewhere describes the building, not the tower
#      -> no classification; reported as building roof
_DE_TOWER = r"turm|türm|dachreiter|campanile"
_DE_BULBOUS = [
    ("onion_double", r"doppelzwiebel|doppelte[rnm]? zwiebel"),
    ("onion", r"zwiebel"),
    ("welsch", r"welsche[rnms]? haube|welschhaube|laternenhaube|glockenhaube|haubendach|"
               r"barocke[rnm]? haube|kuppelhaube|turmhaube|haubenhelm"),
]
_DE_TOWER_ONLY = (r"spitzhelm|spitzturm|pyramidenhelm|rautenhelm|rhombendach|faltdach|sattelturm|"
                  r"satteldachturm|turmhelm|helmdach|nadelhelm|knickhelm|achteckhelm|treppengiebelturm")
_DE_ROOF = (r"satteldach|pultdach|zeltdach|pyramidendach|walmdach|flachdach|kegeldach|"
            r"treppengiebel|spitzdach|(?<!wil)helm|haube|kuppel")


def _word(text: str, m: re.Match) -> str:
    start, end = m.start(), m.end()
    while start > 0 and (text[start - 1].isalpha() or text[start - 1] == "-"):
        start -= 1
    while end < len(text) and text[end].isalpha():
        end += 1
    return text[start:end]


def parse_german(text: str) -> dict:
    """Returns {"cat", "phrase"} for the tower roof (if any) and "building_roof" (if any)."""
    low = text.lower()
    out: dict = {}
    for cat, pattern in _DE_BULBOUS:
        m = re.search(pattern, low)
        if m:
            out.update(cat=cat, phrase=_word(text, m))
            break
    if "cat" not in out:
        m = re.search(_DE_TOWER_ONLY, low)
        if m:
            out.update(cat="other", phrase=_word(text, m))
    # clause by clause: which roof words stand next to a tower word?
    pos = 0
    for clause in re.split(r"[.;,\n]", low):
        start = pos
        pos += len(clause) + 1
        roof = re.search(_DE_ROOF, clause)
        tower = re.search(_DE_TOWER, clause)
        if roof and tower and "cat" not in out:
            word = _word(text, re.compile(_DE_ROOF).search(low, start + roof.start()))
            kind = roof.group(0)
            # only a plain "Haube" counts as a baroque cap; compounds like Spitzhaube are other roofs
            plain = word.lower().rstrip("n")
            out.update(cat="welsch" if plain == "haube" else "dome" if plain.startswith("kuppel") else "other",
                       phrase=word)
        elif roof and not tower and "building_roof" not in out and roof.group(0) not in ("helm", "haube", "kuppel"):
            out["building_roof"] = _word(text, re.compile(_DE_ROOF).search(low, start + roof.start()))
        elif tower and not roof and "cat" not in out and "dachreiter" in clause and "tower_hint" not in out:
            out["tower_hint"] = "Dachreiter"
    if "cat" not in out and out.get("tower_hint"):
        out.update(cat="other", phrase="Dachreiter")
    return out


def classify_text(text: str, lang: str) -> tuple[str, str] | None:
    """Returns (category, matched phrase) or None."""
    if lang == "de":
        r = parse_german(text)
        return (r["cat"], r["phrase"]) if "cat" in r else None
    low = text.lower()
    for cat, pattern in KEYWORDS.get(lang, []):
        m = re.search(pattern, low)
        if m:
            return cat, _word(text, m)
    return None


def combine_with_text(record: dict, text_cat: str, phrase: str, source: str) -> None:
    """Text is a heuristic: it fills gaps and refines within the bulbous family,
    but never overrules an explicit OSM tower roof of another type. A bulbous result
    is locked: later "other" hits (e.g. the Satteldach of the nave) cannot undo it."""
    current = record["roof"]
    note = f"{source}: „{phrase}“ (text rule)"
    if text_cat == "other":
        if current == "unknown":
            record.update(roof="other", sub=None, sub_text=phrase)
            record["src"].append(note)
        return
    if current == "other":
        record["src"].append(note + " – not applied, OSM tower roof differs")
        return
    if SPECIFICITY[text_cat] > SPECIFICITY.get(current, 0):
        record.update(roof=text_cat, sub=text_cat)
    record["src"].append(note)
