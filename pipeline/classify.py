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
    "cs": [("onion", r"cibulov|cibulí")],
    "pl": [("onion", r"cebulast|hełm cebul")],
    "sl": [("onion", r"čebulast")],
    "hu": [("onion", r"hagymasisak|hagymakupol")],
}


def classify_text(text: str, lang: str) -> tuple[str, str] | None:
    """Returns (category, matched phrase) or None."""
    low = text.lower()
    for cat, pattern in KEYWORDS.get(lang, []):
        m = re.search(pattern, low)
        if m:
            start, end = m.start(), m.end()          # widen the hit to the whole word
            while start > 0 and (text[start - 1].isalpha() or text[start - 1] == "-"):
                start -= 1
            while end < len(text) and text[end].isalpha():
                end += 1
            return cat, text[start:end]
    return None


def combine_with_text(record: dict, text_cat: str, phrase: str, lang: str) -> None:
    """Text is a heuristic: it fills gaps and refines within the bulbous family,
    but never overrules an explicit OSM tower roof of another type."""
    current = record["roof"]
    note = f"Wikipedia ({lang}) text mentions “{phrase}” (keyword heuristic)"
    if text_cat == "other":
        if current == "unknown":
            record.update(roof="other", sub=None)
            record["src"].append(note)
        return
    if current == "other":
        record["src"].append(note + " – not applied, OSM tower roof differs")
        return
    if SPECIFICITY[text_cat] > SPECIFICITY.get(current, 0):
        record.update(roof=text_cat, sub=text_cat)
    record["src"].append(note)
