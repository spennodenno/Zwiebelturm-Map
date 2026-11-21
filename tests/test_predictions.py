"""The photo model's result on the map:  python -m tests.test_predictions"""
from pipeline import classify, merge


def rec(i, roof):
    return {"ids": [i], "roof": roof, "sub": roof if roof in ("onion", "onion_double", "welsch", "dome") else None,
            "src": ["OSM"], "n_onion": 2 if roof == "onion" else None, "sub_text": "x"}


def main():
    recs = [rec("way/1", "unknown"), rec("way/2", "onion"), rec("way/3", "onion_double"), rec("way/4", "dome"),
            rec("way/5", "other"), rec("way/6", "welsch"), rec("way/7", "onion"), rec("way/8", "unknown"),
            rec("way/9", "unknown")]
    rows = [
        {"osm_id": "way/1", "roof": "onion", "confidence": "0.95"},        # fills a gap
        {"osm_id": "way/2", "roof": "other", "confidence": "0.93"},        # the text said onion, the photo says no
        {"osm_id": "way/3", "roof": "onion", "confidence": "0.99"},        # same family: keeps the double onion
        {"osm_id": "way/4", "roof": "other", "confidence": "0.97"},        # dome is protected
        {"osm_id": "way/5", "roof": "welsch", "confidence": "0,91"},       # decimal comma is accepted
        {"osm_id": "way/6", "roof": "welsch", "confidence": "0.96"},       # confirmed
        {"osm_id": "way/7", "roof": "other", "confidence": "0.89"},        # below the limit: no change
        {"osm_id": "way/8", "roof": "no_tower", "confidence": "0.99"},     # no tower on the photo: ignored
        {"osm_id": "way/404", "roof": "onion", "confidence": "0.99"},      # church not on the map: ignored
        {"osm_id": "way/9", "roof": "onion", "confidence": "n/a"},         # unreadable: ignored
    ]
    st = merge.apply_predictions(recs, rows, 0.9, ["dome"])
    r = {x["ids"][0]: x for x in recs}
    assert r["way/1"]["roof"] == "onion" and r["way/1"]["sub"] == "onion" and "Modell" in r["way/1"]["src"][-1]
    assert r["way/2"]["roof"] == "other" and r["way/2"]["sub"] is None and "n_onion" not in r["way/2"]
    assert "ersetzt: Zwiebelhaube" in r["way/2"]["src"][-1] and "93 %" in r["way/2"]["src"][-1]
    assert r["way/3"]["roof"] == "onion_double" and "bestätigt" in r["way/3"]["src"][-1]
    assert r["way/4"]["roof"] == "dome" and "geschützt" in r["way/4"]["src"][-1]
    assert r["way/5"]["roof"] == "welsch"
    assert r["way/6"]["roof"] == "welsch" and "bestätigt" in r["way/6"]["src"][-1]
    assert r["way/7"]["roof"] == "onion" and r["way/7"]["src"] == ["OSM"]
    assert r["way/8"]["roof"] == "unknown" and r["way/9"]["roof"] == "unknown"
    assert st == {"seen": 6, "filled": 1, "overwritten": 2, "confirmed": 2, "protected": 1}, st
    assert all(x["roof"] in classify.CAT_INDEX for x in recs)
    print("prediction tests passed")


if __name__ == "__main__":
    main()
