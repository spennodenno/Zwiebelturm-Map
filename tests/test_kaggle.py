"""Tile languages, cache merge and the Kaggle runner:  python -m tests.test_kaggle"""
import csv
import gzip
import importlib.util
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from pipeline import run as prun

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import merge_cache  # noqa: E402


def test_languages():
    rec = lambda cc, lat, lon: {"id": f"{cc}{lat}{lon}", "cc": cc, "lat": lat, "lon": lon}
    recs = [rec("DE", 48.1, 11.1), rec("CZ", 50.1, 14.1), rec("CZ", 50.12, 14.12), rec("CZ", 50.13, 14.13),
            rec("DE", 50.14, 14.14), rec("XX", 40.1, 5.1)]
    langs = {"CZ": ["cs", "de", "en"]}
    tiles = {t["core"][1]: t for t in prun.tile_regions(recs, {"size_deg": 0.25, "countries": []}, langs)}
    assert "languages" not in tiles[48.0], "German tile keeps the global list (same cache keys as before)"
    assert tiles[50.0]["languages"] == ["cs", "de", "en"], "border tile: the country with most churches decides"
    assert "languages" not in tiles[40.0], "a country without an entry uses the global list"
    assert prun.tile_regions(recs, {"countries": ["CZ"]}, langs)[0]["id"].startswith("tile_")


def gz(path: Path, lines: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in lines))


def test_merge():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        mine, other = t / "mine", t / "other"
        (mine / "cache" / "wiki").mkdir(parents=True)
        (mine / "cache" / "wiki" / "same.json").write_text("mine")
        gz(mine / "cache" / "wiki" / "store.jsonl.gz", ["a"])
        (other / "cache" / "wiki").mkdir(parents=True)
        (other / "cache" / "wiki" / "same.json").write_text("other")
        (other / "cache" / "wiki" / "new.json").write_text("new")
        gz(other / "cache" / "wiki" / "store.jsonl.gz", ["b"])
        for base, rows in ((mine, [("way/1", "onion", "0.95")]), (other, [("way/1", "other", "0.99"), ("way/2", "welsch", "0.91")])):
            (base / "data").mkdir()
            with (base / "data" / "predictions.csv").open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["osm_id", "roof", "confidence", "file", "name"])
                w.writerows([[i, r, c, "f", "n"] for i, r, c in rows])
        z = t / "out.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in other.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(other))
        s = merge_cache.merge(z, mine)
        assert s == {"copied": 1, "appended": 1, "kept": 1, "predictions": 1}, s
        assert (mine / "cache" / "wiki" / "same.json").read_text() == "mine"
        assert (mine / "cache" / "wiki" / "new.json").read_text() == "new"
        assert gzip.open(mine / "cache" / "wiki" / "store.jsonl.gz", "rt").read() == "a\nb\n"
        rows = list(csv.DictReader((mine / "data" / "predictions.csv").open(encoding="utf-8")))
        assert [(r["osm_id"], r["roof"]) for r in rows] == [("way/2", "welsch"), ("way/1", "onion")]   # least certain first, mine wins
        assert merge_cache.merge(z, mine) is None, "the same archive is merged once"
        assert merge_cache.merge(z, mine, again=True)["appended"] == 1


def test_runner():
    spec = importlib.util.spec_from_file_location("run_kaggle", ROOT / "kaggle" / "run_kaggle.py")
    rk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rk)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        rk.ROOT, rk.INPUT, rk.WORKING = t / "repo", t / "input", t / "working"
        (rk.ROOT / "cache" / "wiki").mkdir(parents=True)
        (rk.ROOT / "data").mkdir()
        (rk.ROOT / "slow.py").write_text("import time; time.sleep(30)")
        (rk.ROOT / "quick.py").write_text("print('quick')")
        t0 = time.time()
        assert rk.run(["slow.py"], time.time() + 1) is None and time.time() - t0 < 10, "a step is stopped at the deadline"
        assert rk.run(["quick.py"], time.time() + 30) == 0
        assert rk.run(["quick.py"], time.time() - 1) is None
        # model from an attached dataset, restore of an earlier zip, package
        (rk.INPUT / "model").mkdir(parents=True)
        (rk.INPUT / "model" / "best.pt").write_bytes(b"pt")
        assert rk.place_model() and (rk.ROOT / "cache" / "yolo-runs" / "roof" / "weights" / "best.pt").read_bytes() == b"pt"
        (rk.ROOT / "cache" / "wiki" / "x.json").write_text("1")
        (rk.ROOT / "data" / "predictions.csv").write_text("osm_id,roof,confidence,file,name\n", encoding="utf-8")
        rk.package()
        names = set(zipfile.ZipFile(rk.WORKING / rk.ZIP).namelist())
        assert names == {"cache/wiki/x.json", "data/predictions.csv"}, names
        shutil_dst = rk.INPUT / "earlier"
        shutil_dst.mkdir()
        (shutil_dst / rk.ZIP).write_bytes((rk.WORKING / rk.ZIP).read_bytes())
        (rk.ROOT / "cache" / "wiki" / "x.json").unlink()
        rk.restore()
        assert (rk.ROOT / "cache" / "wiki" / "x.json").exists()


if __name__ == "__main__":
    test_languages()
    test_merge()
    test_runner()
    print("kaggle tests passed")
