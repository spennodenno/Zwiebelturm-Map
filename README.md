# Zwiebelturm-Karte

Interactive map (dark and light mode) of church towers in Europe, coloured by roof type.
Onion domes (Zwiebelhauben) and their relatives get colours, everything else is grey.

- `build.py` – Python pipeline: downloads the data and writes `site/data/`
- `site/` – the finished static page (plain HTML/JS, no backend, no build step)
- `config.toml` – countries, Wikipedia regions and all parameters

Requirements: Python 3.11 or newer. No packages to install.

## Build and look at it

```
python build.py        # downloads everything, about 30 minutes the first time
python serve.py        # opens http://localhost:8000
```

Downloads are cached in `cache/`. A second run takes seconds; an interrupted run
continues where it stopped. `python build.py --refresh all` fetches fresh data.

Before the first own download, put a contact (mail address or repository URL)
into `user_agent` in `config.toml`. Wikimedia throttles anonymous clients
without one; if the Wikipedia step stops with HTTP 429, run the command again
a few minutes later. Everything already fetched is kept.

Useful options:

```
python build.py --countries AT,SI          # quick partial build
python build.py --wiki-regions none        # skip the Wikipedia merge
python build.py --wiki-regions all         # every region in config.toml, enabled or not
python build.py --refresh osm              # re-download OSM, keep the Wikipedia cache
```

## Base map and layers

The background (place names, water, roads, state borders, land use) comes from
OpenFreeMap vector tiles (`STYLE_URL` in `site/app.js`: style `dark` and, for light
mode, `positron`); each group can be switched in the legend. The button in the header
switches between dark and light mode (default: the operating system setting, then
remembered in the browser). The colours of the dots can be changed in the legend; they
are stored in the browser only. The "About this map" link at the bottom of the panel
opens the dialog with workflow, use of AI and licences (`ABOUT_DE` / `ABOUT_EN` in `site/app.js`). `site/data/mask.geojson` hides everything outside the
configured countries. Without internet the page falls back to plain country shapes.

## Tower roof from text

`pipeline/classify.py` → `parse_german`. Sources: OSM `description`, the Bavarian
monument lists on de.wikipedia (joined by `ref:BLfD` or coordinates, inside
Wikipedia regions) and Wikipedia articles. The rules look at the tower only:
a bulbous term (Zwiebel…, welsche Haube) always wins and is never undone by a
Satteldach of the nave; general roof words count only next to a tower word.

## Image model

```
python tools/make_labelset.py      # churches with photo → site/label/candidates.json
python serve.py                    # label at http://localhost:8000/label.html, save CSV as data/labels.csv
python tools/train_yolo.py train   # YOLOv8 classifier on data/labels.csv + data/labels-reviewed.csv
python tools/train_yolo.py predict # classify the unlabeled photos (330 px, streamed, nothing stored)
python serve.py                    # review at http://localhost:8000/label.html?review
```

`predict` writes `data/predictions.csv` (osm_id, roof, confidence, file, name; least certain first)
and `site/label/predictions.json`. It can be stopped and continued (`--redo` starts over,
`--limit 50` is a quick test). The review page saves every click through `serve.py` to
`data/labels-reviewed.csv` (training labels, all classes) and, for roof types the map knows, to
`data/overrides.csv`; the map changes with the next `python build.py`. Predictions never reach the
map by themselves.

Photos are not stored: the map card loads them from Wikimedia Commons when it is opened
(`download_photos = false` in `config.toml`). Only the photos of labeled churches are kept for
training, in `cache/photos`.

## Publish on GitHub Pages

1. Push the code (`site/data` and `cache` are ignored by git; the workflow builds the data on GitHub).
2. Repository → Settings → Pages → Source: **GitHub Actions**.
3. The workflow in `.github/workflows/pages.yml` publishes `site/` on every push.
   Run it manually with *rebuild* ticked to fetch fresh data on GitHub instead.

Any static host works the same way: upload the contents of `site/`.

## Change the scope

**Countries** – edit the `countries` list in `config.toml` (ISO codes) and rebuild.
The map shows exactly these countries and nothing else.

**Clipping a country** – some Natural Earth outlines contain overseas territories
(France: Guyane, Réunion, …). The optional `[clip]` table in `config.toml` limits a country
to a box `[west, south, east, north]`; only polygons completely inside it are kept:

```toml
[clip]
FR = [-6.0, 41.0, 10.0, 51.5]   # metropolitan France incl. Corsica
```

France has no Wikipedia region yet, so it has no photos or article text; its roof types
depend on the OSM tags (`roof:shape`) alone.

**Wikipedia regions** – add a block to `config.toml`:

```toml
[[wikipedia.regions]]
id = "tirol"
label = "Tirol"
enabled = true
osm_tags = { boundary = "administrative", admin_level = "4", name = "Tirol" }
```

`osm_tags` identify the boundary relation in OSM; any administrative area works.
For non-German regions put the local language first in `[wikipedia] languages`
(e.g. `["it", "de", "en"]`) so articles and keywords of that language are used.

**Corrections** – `data/overrides.csv` sets the roof type of single churches by
OSM id and wins over everything else. A future image classifier can write its
results into the same file (column `source`).

## How it works

| Step | Module | What happens |
|---|---|---|
| 1 | `pipeline/boundaries.py` | Country outlines from Natural Earth (1:10 m, public domain) |
| 2 | `pipeline/osm.py` | OSM download in 2° grid cells per country, restricted to the OSM country boundary. Source: Postpass (default) or Overpass |
| 3 | `pipeline/merge.py` | One record per church: node + building merged (30 m), bell towers and roof parts attached to the nearest church (60 m) |
| 4 | `pipeline/classify.py` | Roof categories and rules |
| 5 | `pipeline/wikidata.py` | Per enabled region: Wikidata items matched by the OSM `wikidata` tag or by coordinates (120 m when the names agree, 40 m when a name is missing, 24 m when they differ), statements, article links and intro, Commons photo (file name, thumbnail URL, author and licence; copied to `site/data/img` only with `download_photos = true`), roof hint from the article text |
| 6 | `pipeline/export.py` | `site/data/`: `points.bin` (9 bytes per church), detail files of 1 000 churches each (loaded on click), `manifest.json` |

### What counts as a church

`amenity=place_of_worship` + `religion=christian`, or `building=church|chapel|cathedral|basilica`,
plus free-standing bell towers (`man_made=tower` + `tower:type=bell_tower|campanile`).

### Roof categories

| Key | Meaning | Source |
|---|---|---|
| `onion` | Zwiebelhaube | `roof:shape=onion` on the church, its tower or a building part within 60 m; article text |
| `onion_double` | Doppelzwiebel | article text, overrides (OSM has no tag for it) |
| `welsch` | Welsche Haube, Laternenhaube | article text, overrides |
| `dome` | Kuppel | `roof:shape=dome` |
| `other` | any other tower roof (grey) | `roof:shape` on a bell tower / tower building part; article text |
| `unknown` | nothing recorded (dark grey) | – |

A `roof:shape` on the church building itself describes the nave, so apart from
onion and dome it does not classify the tower; it is shown in the info card.

### Data schema (detail record)

```
id, ids[]        OSM object(s), e.g. "way/123"
lat, lon, cc     position, country code
kind             "church" | "tower"
name, year, height
roof, sub, src[] category, OSM shape, and where the classification comes from
n_onion          number of onion roofs mapped
tags{}           all OSM tags
near[]           attached towers / roof parts with their tags and distance
wd{}             qid, label, desc, facts per language, wikipedia links, intro,
                 image {local, thumb, page, author, license, license_url}, commons_category
```

## Tests

```
python -m tests.test_pipeline       # offline end-to-end test with invented fixtures
python -m tests.load_test /tmp/zt   # 250 000 invented points, to check rendering speed
```

## Credits and licences

Map data © OpenStreetMap contributors (ODbL). Wikidata (CC0). Wikipedia text
(CC BY-SA 4.0). Photos from Wikimedia Commons, each under the licence shown
with it. Country outlines: Natural Earth. Rendering: MapLibre GL JS (BSD-3).
