"""Offline end-to-end test:  python -m tests.test_pipeline"""
import json
import struct
import tempfile
from pathlib import Path

from pipeline import boundaries, classify, geo, net, run
from tests import fake_sources

ROOT = Path(__file__).resolve().parent.parent


def main():
    boundaries.load_countries(["DE"], ROOT / "cache")   # the only real download: country outlines
    net.fetch = fake_sources.fetch
    fake_sources.fail_big_cells_once = True
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "boundaries").mkdir()
        (tmp / "boundaries" / "ne_10m_admin_0_countries.geojson").write_bytes(
            (ROOT / "cache" / "boundaries" / "ne_10m_admin_0_countries.geojson").read_bytes())
        out = tmp / "out"
        cfg = (ROOT / "config.toml").read_text(encoding="utf-8").replace("pause_s = 3", "pause_s = 0").replace('source = "postpass"', 'source = "overpass"')
        (tmp / "config.toml").write_text(cfg, encoding="utf-8")
        run.main(["--config", str(tmp / "config.toml"), "--countries", "DE,AT", "--cache", str(tmp), "--out", str(out)])
        calls_first = fake_sources.calls["overpass"]
        run.main(["--config", str(tmp / "config.toml"), "--countries", "DE,AT", "--cache", str(tmp), "--out", str(out)])
        assert fake_sources.calls["overpass"] == calls_first, "second run must come from the cache"
        assert fake_sources.calls["split_forced"]

        man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        recs = [r for f in sorted((out / "d").glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
        by = {r["id"]: r for r in recs}
        assert man["n"] == len(recs) == 7, man["n"]
        raw = (out / "points.bin").read_bytes()
        n = man["n"]
        assert len(raw) == 9 * n
        lon = struct.unpack(f"<{n}i", raw[:4 * n]); lat = struct.unpack(f"<{n}i", raw[4 * n:8 * n]); cat = raw[8 * n:]
        for i, r in enumerate(recs):
            assert abs(lon[i] / 1e6 - r["lon"]) < 1e-6 and abs(lat[i] / 1e6 - r["lat"]) < 1e-6
            assert man["categories"][cat[i]]["key"] == r["roof"]

        a = by["way/1"]                       # node + way merged, onion from a roof part, exact Wikidata match
        assert a["ids"] == ["way/1", "node/2"] and a["roof"] == "onion" and a["tags"]["denomination"] == "catholic"
        assert a["year"] == "1735" and a["height"] == 41.5
        assert a["wd"]["qid"] == "Q900001" and a["wd"]["how"] == "OSM wikidata tag"
        assert (out / a["wd"]["image"]["local"]).read_bytes().startswith(b"\xff\xd8")
        assert a["wd"]["image"]["author"] == "Test Author" and a["wd"]["image"]["license"] == "CC BY-SA 4.0"
        assert ["Höhe", "41,5 m"] in a["wd"]["facts"]["de"] and ["Architectural style", "Baroque"] in a["wd"]["facts"]["en"]
        assert a["wd"]["wikipedia"]["de"] == "https://de.wikipedia.org/wiki/St._Test_(Testdorf)"
        assert a["wd"]["intro"]["text"].startswith("St. Test ist")
        b = by["way/4"]                       # matched by coordinates, roof from article text
        assert b["wd"]["qid"] == "Q900002" and b["wd"]["how"] == "coordinates" and b["roof"] == "onion_double"
        assert by["way/12"]["roof"] == "welsch"
        c = by["way/5"]                       # bell tower attached → other / pyramidal
        assert c["roof"] == "other" and c["sub"] == "pyramidal" and c["near"][0]["id"] == "node/6"
        assert by["node/7"]["kind"] == "tower" and by["node/7"]["roof"] == "other"
        assert by["way/9"]["roof"] == "unknown" and by["way/9"]["wd"]["image"]["thumb"]   # nave roof ≠ tower roof
        assert by["way/10"]["roof"] == "dome" and "wd" not in by["way/10"]
        assert "way/11" not in by and "way/8" not in by
        assert man["stats"]["onion_roofs_without_church"] == 1
        assert man["wikipedia_regions"][0]["matched"] == 3
        assert [c["iso"] for c in man["countries"]] == ["DE", "AT"]

    assert classify.classify_text("Der Zwiebelturm prägt das Ortsbild.", "de")[0] == "onion"
    assert classify.classify_text("ein schlanker Spitzhelm", "de")[0] == "other"
    assert classify.classify_text("Kuppelfresko im Langhaus", "de") is None
    assert geo.name_similarity("Pfarrkirche St. Georg", "Sankt Georg") == 1.0
    assert geo.name_similarity("St. Georg", "St. Martin") == 0.0
    print("all pipeline tests passed")


if __name__ == "__main__":
    main()
