"""Instant changes, review queue and report counting:  python -m tests.test_reports"""
import csv
import tempfile
from pathlib import Path

import serve
from tools import fetch_reports


def rows(path):
    return list(csv.DictReader(path.open(encoding="utf-8", newline="")))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        serve.DATA = Path(tmp)
        data = serve.DATA
        (data / "overrides.csv").write_text("osm_id,roof,source,note\r\nway/9,dome,manual,by hand\r\n", encoding="utf-8")
        q = dict(id="way/1", roof="onion", previous="other", name="St. A", lon=11500000, lat=48100000, img="https://x/y.jpg")

        serve.save_quick(q)
        ov = rows(data / "overrides.csv")
        assert [r["roof"] for r in ov if r["osm_id"] == "way/1"] == ["onion"] and ov[-1]["source"] == "manual-quick"
        assert any(r["osm_id"] == "way/9" for r in ov), "hand-written line must stay"
        # a second quick change replaces the first and keeps the very first 'previous'
        serve.save_quick({**q, "roof": "welsch", "previous": "onion"})
        qc = rows(data / "quick-changes.csv")
        assert len(qc) == 1 and qc[0]["roof"] == "welsch" and qc[0]["previous"] == "other"
        assert [r["roof"] for r in rows(data / "overrides.csv") if r["osm_id"] == "way/1"] == ["welsch"]
        # hand-written overrides are never replaced, bad input is refused
        for bad in ({**q, "id": "way/9"}, {**q, "roof": "no_tower"}, {**q, "id": "x"}, {**q, "lon": "a"}):
            try:
                serve.save_quick(bad)
            except ValueError:
                continue
            raise AssertionError(bad)
        assert [r["id"] for r in serve.queue("quick")] == ["way/1"]
        assert serve.queue("quick")[0]["current"] == "other" and serve.queue("quick")[0]["pred"] == "welsch"

        # a review decides the church: quick line and to-check entry disappear, review label stays
        serve.save_review("way/1", "onion", "St. A")
        assert [r["source"] for r in rows(data / "overrides.csv") if r["osm_id"] == "way/1"] == [serve.SOURCE]
        assert not rows(data / "quick-changes.csv") and serve.queue("quick") == []

        # reports: most reported first, reviewed churches drop out
        (data / "reports.csv").write_text(
            "osm_id,proposed,count,current,name,img,last\r\nway/2,onion,1,other,B,,\r\nway/3,welsch,4,other,C,https://x/c.jpg,\r\n"
            "way/1,other,9,onion,A,,\r\n", encoding="utf-8")
        assert [r["id"] for r in serve.queue("reports")] == ["way/3", "way/2"]

    # counting of GitHub issues
    body = lambda i, p: f"osm_id: {i}\nproposed: {p}\ncurrent: other\nname: X\nimg: https://u/a.jpg\n"
    iss = lambda t, b, u: {"title": t, "body": b, "user": {"login": u}, "created_at": "2026-11-01T00:00:00Z"}
    got = fetch_reports.count_reports([
        iss("Meldung: a", body("way/1", "onion"), "anna"), iss("Meldung: a", body("way/1", "onion"), "ben"),
        iss("Meldung: a", body("way/1", "onion"), "anna"),        # same person twice: once
        iss("Meldung: b", body("way/2", "bogus"), "anna"),        # unknown class: ignored
        iss("Frage", body("way/3", "onion"), "anna"),             # not a report
    ])
    assert [(g["osm_id"], g["count"]) for g in got] == [("way/1", 2)], got
    print("report tests passed")


if __name__ == "__main__":
    main()
