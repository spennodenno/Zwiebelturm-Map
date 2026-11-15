"""Country outlines from Natural Earth (public domain, 1:10 million)."""
from __future__ import annotations

import json
from pathlib import Path

from . import net

NE_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
          "geojson/ne_10m_admin_0_countries.geojson")


def _iso(props: dict) -> str:
    for key in ("ISO_A2_EH", "ISO_A2"):
        v = props.get(key)
        if v and v != "-99":
            return v
    return ""


def _round(coords, nd=4):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], nd), round(coords[1], nd)]
    out = [_round(c, nd) for c in coords]
    if out and isinstance(out[0][0], (int, float)):  # a ring: drop repeated points
        dedup = [out[0]]
        for p in out[1:]:
            if p != dedup[-1]:
                dedup.append(p)
        return dedup
    return out


def load_countries(codes: list[str], cache_dir: Path) -> dict[str, dict]:
    """Returns {ISO: GeoJSON feature} for the configured countries, in config order."""
    path = cache_dir / "boundaries" / "ne_10m_admin_0_countries.geojson"
    if not path.exists():
        print("  downloading Natural Earth country outlines …")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(net.fetch_retry(NE_URL, timeout=300))
    world = json.loads(path.read_text(encoding="utf-8"))
    found: dict[str, dict] = {}
    for f in world["features"]:
        iso = _iso(f["properties"])
        if iso in codes and iso not in found:
            p = f["properties"]
            found[iso] = {
                "type": "Feature",
                "properties": {"iso": iso, "en": p.get("NAME") or p.get("NAME_EN"),
                               "de": p.get("NAME_DE") or p.get("NAME")},
                "geometry": {"type": f["geometry"]["type"],
                             "coordinates": _round(f["geometry"]["coordinates"])},
            }
    missing = [c for c in codes if c not in found]
    if missing:
        raise SystemExit(f"Unknown country code(s) in config.toml: {', '.join(missing)}")
    return {c: found[c] for c in codes}
