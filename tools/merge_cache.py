"""Bring the results of a Kaggle run (or any other copy of this project) into your own cache.

    py tools/merge_cache.py C:\\Users\\you\\Downloads\\zwiebel-kaggle-out.zip      (or an unzipped folder)

The archive holds  cache/…  and  data/predictions.csv.  What happens:
  * a cache file you do not have yet is copied (request files are named by a hash of the request, so a
    file that exists on both sides holds the same answer: yours is kept),
  * a store file (*.jsonl.gz) that exists on both sides is extended by the other one (gzip files can be appended),
  * predictions are added by osm_id (your own row wins), sorted least certain first, like predict writes them.
The same archive is merged once (cache/merged.txt); --again repeats it.
Afterwards:  py build.py   (everything fetched on Kaggle is cached, so this takes minutes)
"""
import argparse
import csv
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def merge_predictions(src: Path, dst: Path) -> int:
    def rows(p):
        with p.open(encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            return r.fieldnames, list(r)
    head, new = rows(src)
    old = rows(dst)[1] if dst.exists() else []
    have = {r["osm_id"] for r in old}
    add = [r for r in new if r["osm_id"] not in have]
    out = sorted(old + add, key=lambda r: float(r.get("confidence") or 0))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=head)
        w.writeheader()
        w.writerows(out)
    return len(add)


def merge_dir(src: Path, root: Path) -> dict:
    stats = {"copied": 0, "appended": 0, "kept": 0, "predictions": 0}
    for f in sorted((src / "cache").rglob("*")) if (src / "cache").exists() else []:
        if not f.is_file():
            continue
        dst = root / "cache" / f.relative_to(src / "cache")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copyfile(f, dst)
            stats["copied"] += 1
        elif f.name.endswith(".jsonl.gz"):
            with dst.open("ab") as out, f.open("rb") as inp:
                shutil.copyfileobj(inp, out)
            stats["appended"] += 1
        else:
            stats["kept"] += 1
    pred = src / "data" / "predictions.csv"
    if pred.exists():
        stats["predictions"] = merge_predictions(pred, root / "data" / "predictions.csv")
    return stats


def merge(archive: Path, root: Path = ROOT, again: bool = False) -> dict | None:
    mark = root / "cache" / "merged.txt"
    key = f"{archive.name} {archive.stat().st_size}" if archive.is_file() else None
    if key and not again and mark.exists() and key in mark.read_text(encoding="utf-8").splitlines():
        return None
    if archive.is_file():
        with tempfile.TemporaryDirectory() as tmp:
            zipfile.ZipFile(archive).extractall(tmp)
            stats = merge_dir(Path(tmp), root)
    else:
        stats = merge_dir(archive, root)
    if key:
        mark.parent.mkdir(parents=True, exist_ok=True)
        with mark.open("a", encoding="utf-8") as f:
            f.write(key + "\n")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--again", action="store_true", help="merge an archive that was merged before")
    a = ap.parse_args()
    if not a.archive.exists():
        sys.exit(f"Not found: {a.archive}")
    s = merge(a.archive, ROOT, a.again)
    if s is None:
        print("This archive was merged before (use --again to repeat it).")
        return 0
    print(f"{s['copied']} cache files copied, {s['appended']} store files extended, {s['kept']} already there, "
          f"{s['predictions']} new predictions.\nNext:  py build.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
