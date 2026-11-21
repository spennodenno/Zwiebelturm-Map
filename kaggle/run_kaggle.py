"""The pipeline for other countries inside a Kaggle notebook (CPU is enough; the GPU is not used).

    !git clone --depth 1 https://github.com/spennodenno/Zwiebelturm-Map.git
    %cd Zwiebelturm-Map
    !python kaggle/run_kaggle.py                       # default countries: see COUNTRIES
    !python kaggle/run_kaggle.py --countries CZ,PL --hours 10

What it does, in this order (every step is resumable, everything lands in zwiebel-kaggle-out.zip):
  restore   an earlier zwiebel-kaggle-out.zip that is attached to the notebook as input (Add Input → this notebook's output)
  model     best.pt from an attached dataset → cache/yolo-runs/roof/weights/   (without it the predict step is skipped)
  probe     one Wikidata and one Commons request: shows at once whether Wikimedia answers Kaggle
  build     build.py --countries … --tile-countries … --wiki-regions tiles     (OSM + Wikidata + Wikipedia, tiles only)
  labelset  tools/make_labelset.py
  predict   tools/train_yolo.py predict
  package   ALWAYS, also after a timeout or a crash: cache/ + data/predictions.csv → /kaggle/working/zwiebel-kaggle-out.zip
A step that is still running when the time budget (--hours) is used up is stopped; the next run continues it.
Download the zip afterwards and run  py tools/merge_cache.py zwiebel-kaggle-out.zip  on your PC.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
INPUT = Path(os.environ.get("KAGGLE_INPUT", "/kaggle/input"))
WORKING = Path(os.environ.get("KAGGLE_WORKING", "/kaggle/working"))
ZIP = "zwiebel-kaggle-out.zip"
COUNTRIES = "AT,CH,CZ,SI,HU,PL,IT,FR"
FAILED = ROOT / "data" / "failed-regions.txt"


def say(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def run(cmd: list[str], deadline: float) -> int | None:
    """Runs a step with live output. Returns the exit code, or None when the time budget ended it."""
    left = deadline - time.time()
    if left <= 0:
        say(f"no time left for: {' '.join(cmd)}")
        return None
    say("$ " + " ".join(cmd))
    p = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
    try:
        return p.wait(timeout=left)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        say("time budget used up: step stopped (the next run continues it)")
        return None


def restore() -> None:
    import merge_cache
    for z in sorted(INPUT.rglob(ZIP), key=lambda p: p.stat().st_mtime):
        say(f"restoring {z}")
        say(f"  {merge_cache.merge(z, ROOT)}")


def place_model() -> bool:
    dst = ROOT / "cache" / "yolo-runs" / "roof" / "weights" / "best.pt"
    if not dst.exists():
        found = sorted(INPUT.rglob("best.pt")) if INPUT.exists() else []
        if not found:
            say("no best.pt in the inputs: the predict step is skipped (add your model as a dataset)")
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(found[0], dst)
    return True


def probe() -> None:
    from pipeline import net
    import tomllib
    net.USER_AGENT = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))["osm"]["user_agent"]
    for name, url in (("Wikidata SPARQL", "https://query.wikidata.org/sparql?format=json&query=SELECT%20%3Fa%20WHERE%20%7Bwd%3AQ1%20wdt%3AP31%20%3Fa%7D"),
                      ("Wikipedia API", "https://de.wikipedia.org/w/api.php?action=query&titles=Berlin&format=json"),
                      ("Commons photo", "https://commons.wikimedia.org/wiki/Special:FilePath/Example.jpg?width=100")):
        try:
            say(f"probe {name}: {len(net.fetch(url, timeout=30))} bytes")
        except Exception as e:
            say(f"probe {name}: FAILED {e}  <- Wikimedia may block this machine; see the log of the build step")


def package() -> None:
    out = WORKING / ZIP
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for sub in ("osm-postpass", "wiki"):
            for f in (ROOT / "cache" / sub).rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(ROOT))
        for name in ("predictions.csv", "failed-regions.txt", "build-failures.log"):
            f = ROOT / "data" / name
            if f.exists():
                z.write(f, f.relative_to(ROOT))
    say(f"packaged {out} ({out.stat().st_size / 1e6:.0f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--countries", default=COUNTRIES)
    ap.add_argument("--hours", type=float, default=11, help="time budget; a Kaggle session ends after 12 h")
    ap.add_argument("--build-retries", type=int, default=2, help="extra build passes while regions failed")
    ap.add_argument("--retry-wait-min", type=float, default=10)
    ap.add_argument("--no-predict", action="store_true")
    ap.add_argument("--limit", type=int, help="predict at most N photos (a quick test)")
    a = ap.parse_args()
    deadline = time.time() + a.hours * 3600 - 600          # 10 min left for packaging
    try:
        restore()
        have_model = place_model() and not a.no_predict
        probe()
        build = ["build.py", "--countries", a.countries, "--tile-countries", a.countries, "--wiki-regions", "tiles"]
        code = run(build, deadline)
        tries = 0
        while code == 0 and FAILED.exists() and FAILED.read_text(encoding="utf-8").strip() and tries < a.build_retries:
            tries += 1
            say(f"regions failed: pause {a.retry_wait_min:g} min, then build pass {tries} of {a.build_retries}")
            time.sleep(min(a.retry_wait_min * 60, max(0, deadline - time.time())))
            code = run(build, deadline)
        if code == 0 and have_model:
            if not importable("ultralytics"):
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics"], check=False)
            if run(["tools/make_labelset.py"], deadline) == 0:
                run(["tools/train_yolo.py", "predict"] + (["--limit", str(a.limit)] if a.limit else []), deadline)
        elif code not in (0, None):
            say(f"build failed with exit code {code}: see the log above")
    finally:
        package()
    return 0


def importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    sys.exit(main())
