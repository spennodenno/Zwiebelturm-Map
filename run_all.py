"""Everything in one go, unattended:   py run_all.py

    1. train      py tools/train_yolo.py train             new model from data/labels*.csv
    2. predict    py tools/train_yolo.py predict --redo    all known photos with the new model
    3. build      py build.py                              Wikipedia / Wikidata (tiles + regions from config.toml)
                  → repeated after a pause while regions fail (everything that worked is cached)
    4. labelset   py tools/make_labelset.py                the new churches with photos
    5. predict    py tools/train_yolo.py predict           only the photos that are new (resumes if stopped)
    6. apply      py build.py                              again, from the cache (minutes): puts the new predictions
                                                           with confidence >= [predictions] min_confidence on the map

Options:
    --steps train,predict-redo,build,labelset,predict,apply   run only these steps (default: all, in this order)
    --build-retries 2        extra build passes while data/failed-regions.txt is not empty
    --retry-wait-min 20      pause before such a pass (Wikidata overload usually passes)
    --predict-retries 3      extra passes of `predict` while single photos failed
    --predict-wait-min 5     pause before such a pass
    --limit N                predict at most N photos per predict step (a quick test run)

Log: data/run-all.log (everything the steps print, with times). A step that fails stops the run, except the
failed Wikipedia regions: those are listed in data/failed-regions.txt and data/build-failures.log.
Stopped (Ctrl+C or crash)? Start it again: build and predict continue from the cache / the saved predictions.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "data" / "run-all.log"
FAILED = ROOT / "data" / "failed-regions.txt"
ALL_STEPS = ["train", "predict-redo", "build", "labelset", "predict", "apply"]

_log = None


def say(msg: str = "") -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}" if msg else ""
    print(line, flush=True)
    _log.write(line + "\n")
    _log.flush()


def run(cmd: list[str]) -> tuple[int, str]:
    """Runs a step, shows and logs its output live. Returns (exit code, output)."""
    say("$ " + " ".join(["py"] + cmd))
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    p = subprocess.Popen([sys.executable, *cmd], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    out = []
    try:
        for line in p.stdout:
            print(line, end="", flush=True)
            _log.write(line)
            out.append(line)
        _log.flush()
        return p.wait(), "".join(out)
    except KeyboardInterrupt:
        p.terminate()
        raise


def failed_regions() -> list[str]:
    return [l.strip() for l in FAILED.read_text(encoding="utf-8").splitlines() if l.strip()] if FAILED.exists() else []


def keep_awake() -> None:
    """Windows: no automatic sleep while this script runs (does not stop a manual sleep or closing the lid)."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except Exception:
        pass


def main() -> int:
    global _log
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--steps", default=",".join(ALL_STEPS))
    ap.add_argument("--build-retries", type=int, default=2)
    ap.add_argument("--retry-wait-min", type=float, default=20)
    ap.add_argument("--predict-retries", type=int, default=3)
    ap.add_argument("--predict-wait-min", type=float, default=5)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    bad = [s for s in steps if s not in ALL_STEPS]
    if bad:
        sys.exit(f"Unknown step(s): {', '.join(bad)}. Possible: {', '.join(ALL_STEPS)}")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _log = LOG.open("a", encoding="utf-8")
    keep_awake()
    t0 = time.time()
    summary: list[str] = []
    lim = ["--limit", str(args.limit)] if args.limit else []
    predict = ["tools/train_yolo.py", "predict"]

    def predict_step(label: str, redo: bool) -> bool:
        """predict; a redo pass that is stopped can only be continued WITHOUT --redo (the first checkpoint
        has already replaced the old file), so every retry is a plain predict."""
        code, out = run(predict + (["--redo"] if redo else []) + lim)
        passes, total = 0, 0
        while True:
            m = re.search(r"(\d+) new predictions, (\d+) failed", out)
            total += int(m.group(1)) if m else 0
            if code != 0 or args.limit or passes >= args.predict_retries or not m \
                    or int(m.group(2)) == 0 or int(m.group(1)) == 0:
                break                                        # nothing failed, or a retry brought nothing new
            passes += 1
            say(f"{m.group(2)} photos failed (throttling, deleted files): pause {args.predict_wait_min:g} min, "
                f"then pass {passes} of {args.predict_retries}")
            time.sleep(args.predict_wait_min * 60)
            code, out = run(predict)
        summary.append(f"{label}: " + (f"{total} new predictions, {m.group(2)} still failed" if m else f"exit code {code}"))
        return code == 0

    try:
        for step in [s for s in ALL_STEPS if s in steps]:
            say(f"=== {step} ===")
            ts = time.time()
            ok = True
            if step == "train":
                ok = run(["tools/train_yolo.py", "train"])[0] == 0
            elif step == "predict-redo":
                ok = predict_step("predict --redo", True)
            elif step == "build":
                code = run(["build.py"])[0]
                tries = 0
                while code == 0 and failed_regions() and tries < args.build_retries:
                    tries += 1
                    say(f"{len(failed_regions())} Wikipedia regions failed: pause {args.retry_wait_min:g} min, "
                        f"then build pass {tries} of {args.build_retries}")
                    time.sleep(args.retry_wait_min * 60)
                    code = run(["build.py"])[0]
                ok = code == 0
                left = failed_regions()
                summary.append("build: " + ("FAILED (exit code %d), see the end of data/run-all.log" % code if not ok else
                                            f"{len(left)} regions still without Wikipedia data (data/failed-regions.txt)"
                                            if left else "all regions done"))
            elif step == "labelset":
                ok = run(["tools/make_labelset.py"])[0] == 0
            elif step == "predict":
                ok = predict_step("predict", False)
            elif step == "apply":
                code = run(["build.py"])[0]
                ok = code == 0
                summary.append("apply (build from the cache with the new predictions): " + ("done" if ok else f"FAILED (exit code {code})"))
            say(f"=== {step}: {'done' if ok else 'FAILED'} after {(time.time() - ts) / 60:.1f} min ===")
            if not ok:
                summary.append(f"{step}: FAILED - run stopped here, see data/run-all.log")
                return 1
    except KeyboardInterrupt:
        say("Stopped by Ctrl+C. Start the same command again to continue.")
        return 130
    finally:
        say("--- summary ---")
        for line in summary:
            say("  " + line)
        say(f"total {(time.time() - t0) / 60:.0f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
