"""Count public reports ("Falsch eingestuft?" on the map opens a prefilled GitHub issue).

    py tools/fetch_reports.py            reads the issues of the repo, writes data/reports.csv
    py tools/fetch_reports.py --repo owner/name

Each issue title starts with "Meldung:" and the body has the lines  osm_id: / proposed: / current: / name: / img: .
Per church and proposed roof type, every GitHub account counts once (a second issue from the same person is
ignored), so the number is the number of different people. Reports never change the map: you decide in
    http://localhost:8000/label.html?queue=reports      (most reported first)
Closed issues still count; reviewed churches disappear from the queue by themselves.
"""
import argparse
import csv
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "spennodenno/Zwiebelturm-Map"
ID_RE = re.compile(r"^(node|way|relation)/\d+$")
CLASSES = {"onion", "onion_double", "welsch", "dome", "other"}


def parse_issue(issue: dict) -> dict | None:
    if not str(issue.get("title", "")).startswith("Meldung:") or "pull_request" in issue:
        return None
    fields = {}
    for line in str(issue.get("body") or "").splitlines():
        m = re.match(r"^(osm_id|proposed|current|name|img):\s*(.*)$", line.strip())
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2).strip()
    if not ID_RE.match(fields.get("osm_id", "")) or fields.get("proposed") not in CLASSES:
        return None
    img = fields.get("img", "")
    return {"osm_id": fields["osm_id"], "proposed": fields["proposed"], "current": fields.get("current", ""),
            "name": fields.get("name", "")[:200], "img": img if img.startswith("https://") else "",
            "user": (issue.get("user") or {}).get("login", "?"), "created": issue.get("created_at", "")}


def count_reports(issues: list[dict]) -> list[dict]:
    seen, groups = set(), {}
    for iss in issues:
        r = parse_issue(iss)
        if not r or (r["osm_id"], r["proposed"], r["user"]) in seen:
            continue
        seen.add((r["osm_id"], r["proposed"], r["user"]))
        g = groups.setdefault((r["osm_id"], r["proposed"]), {**r, "count": 0})
        g["count"] += 1
        g["last"] = max(g.get("last", ""), r["created"])
    # one row per church: the proposal with the most reports; other proposals add to "also"
    best = {}
    for (osm_id, proposed), g in groups.items():
        if osm_id not in best or g["count"] > best[osm_id]["count"]:
            best[osm_id] = g
    return sorted(best.values(), key=lambda g: (-g["count"], g["osm_id"]))


def fetch_issues(repo: str, user_agent: str) -> list[dict]:
    out, page = [], 1
    while True:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}",
                                     headers={"User-Agent": user_agent, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.load(r)
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=REPO)
    ap.add_argument("--out", default=str(ROOT / "data" / "reports.csv"))
    args = ap.parse_args(argv)
    try:
        issues = fetch_issues(args.repo, "zwiebelturm-karte/1.0 (report counter)")
    except Exception as e:   # no network, private repo, rate limit (60 requests/hour without a token)
        print(f"Could not read the issues of {args.repo}: {e}")
        return 1
    rows = count_reports(issues)
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["osm_id", "proposed", "count", "current", "name", "img", "last"])
        w.writerows([[g["osm_id"], g["proposed"], g["count"], g["current"], g["name"], g["img"], g.get("last", "")] for g in rows])
    print(f"{len(rows)} churches reported ({sum(g['count'] for g in rows)} reports) -> {out}")
    print("Review them:  py serve.py   then   http://localhost:8000/label.html?queue=reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
