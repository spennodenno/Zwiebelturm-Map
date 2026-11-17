"""Geometry helpers without external dependencies."""
from __future__ import annotations

import math
import re
import unicodedata

M_PER_DEG = 111_320.0


def dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular distance – accurate to well under 1 % at the ranges used here."""
    x = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = lat2 - lat1
    return math.hypot(x, y) * M_PER_DEG


class Grid:
    """Spatial hash for 'everything within r metres' queries (r <= cell_m)."""

    def __init__(self, cell_m: float):
        self.dlat = cell_m / M_PER_DEG
        # cell width chosen at 60° N so that cells are at least cell_m wide everywhere south of it
        self.dlon = cell_m / (M_PER_DEG * math.cos(math.radians(60)))
        self.cells: dict[tuple[int, int], list] = {}

    def _key(self, lat, lon):
        return (math.floor(lat / self.dlat), math.floor(lon / self.dlon))

    def add(self, lat, lon, item):
        self.cells.setdefault(self._key(lat, lon), []).append((lat, lon, item))

    def near(self, lat, lon, radius_m):
        """Yield (distance_m, item) within radius, unsorted."""
        ky, kx = self._key(lat, lon)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for la, lo, item in self.cells.get((ky + dy, kx + dx), ()):
                    d = dist_m(lat, lon, la, lo)
                    if d <= radius_m:
                        yield d, item


# ---------- polygons (GeoJSON Polygon / MultiPolygon coordinates) ----------

def polygons(geometry: dict) -> list:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    raise ValueError(geometry["type"])


def geometry_bbox(geometry: dict) -> tuple[float, float, float, float]:
    xs, ys = [], []
    for poly in polygons(geometry):
        for x, y, *_ in poly[0]:
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)  # w, s, e, n


def _point_in_ring(x, y, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _segment_hits_rect(x1, y1, x2, y2, w, s, e, n) -> bool:
    """Liang–Barsky clip test."""
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - w), (dx, e - x1), (-dy, y1 - s), (dy, n - y1)):
        if p == 0:
            if q < 0:
                return False
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return False
                t0 = max(t0, t)
            else:
                if t < t0:
                    return False
                t1 = min(t1, t)
    return True


def rect_intersects(geometry: dict, w, s, e, n) -> bool:
    """True if the rectangle touches the (outer rings of the) geometry."""
    for poly in polygons(geometry):
        ring = poly[0]
        for i in range(len(ring) - 1):
            if _segment_hits_rect(ring[i][0], ring[i][1], ring[i + 1][0], ring[i + 1][1], w, s, e, n):
                return True
        if _point_in_ring((w + e) / 2, (s + n) / 2, ring):
            return True
    return False


# ---------- names ----------

_SAINT = re.compile(r"\b(sankt|saint|sainte|santa|santo|san|sant|svateho|svate|sv|swietego|swietej|sw|szent|st)\b\.?")
_GENERIC = {
    "kirche", "pfarrkirche", "stadtpfarrkirche", "filialkirche", "wallfahrtskirche", "kapelle",
    "kath", "katholische", "evangelische", "ev", "evang", "church", "chapel", "parish", "of", "the",
    "chiesa", "cappella", "di", "del", "della", "kostel", "kaple", "kosciol", "kaplica", "cerkev",
    "kapela", "templom", "kapolna", "pfarramt", "und", "and", "e", "a", "i",
}


def name_tokens(name: str | None) -> set[str]:
    if not name:
        return set()
    s = unicodedata.normalize("NFKD", name.lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).replace("ß", "ss").replace("ł", "l")
    s = _SAINT.sub(" ", s)
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in _GENERIC and len(t) > 1}


def name_similarity(a: str | None, b: str | None) -> float | None:
    """Share of the shorter name's distinctive words found in the other; None if a name is missing."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return None
    return len(ta & tb) / min(len(ta), len(tb))
