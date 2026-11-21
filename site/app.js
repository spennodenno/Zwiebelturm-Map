/* Zwiebelturm-Karte – front end. Plain JS, MapLibre GL for WebGL rendering.
   Data files are produced by the Python pipeline (see README.md). */
(function () {
  'use strict';
  const DATA = 'data/';
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const esc = (s) => String(s).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const a = (href, text) => `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;

  // Text of the "About this map" dialog. Plain HTML strings, no user input; x = {countries, date}.
  const ABOUT_DE = (x) => `
<h3>Worum es geht</h3>
<p>Die Karte zeigt Kirchen und freistehende Glockentürme in ${esc(x.countries)} und färbt sie nach der Dachform des Turms. Zwiebelhauben und ihre Verwandten sind farbig, alle anderen Türme grau. Es ist ein privates Hobbyprojekt und nicht kommerziell.</p>

<h3>So entsteht die Karte</h3>
<ol>
  <li><b>Kirchen aus OpenStreetMap.</b> Pro Land werden Gebetsstätten, Kirchengebäude und freistehende Glockentürme geladen.</li>
  <li><b>Zusammenführen.</b> Eine Kirche, die als Punkt und als Gebäude erfasst ist, wird zu einem Eintrag. Turm- und Dachteile in der Nähe werden der Kirche zugeordnet.</li>
  <li><b>Dachform aus den OSM-Angaben.</b> Entscheidend ist das Dach des Turms, nicht das des Kirchenschiffs. Steht dort nichts, gilt die Dachform als nicht erfasst.</li>
  <li><b>Wikipedia und Wikidata</b> kommen für ausgewählte Regionen dazu: Artikeltext, Einträge der bayerischen Denkmalliste, Fotos, Baujahr und weitere Angaben. Nennt ein Text die Dachform (zum Beispiel „Zwiebelhaube“), liest eine Wortregel sie aus. Das ist eine gewöhnliche Textsuche, keine KI.</li>
  <li><b>Bildmodell.</b> Aus Fotos schlägt ein Modell Dachformen vor (siehe „Einsatz von KI“). Ist es sich sehr sicher (ab 90 %), setzt es die Dachform auf der Karte; Stichproben und Meldungen werden von Hand geprüft.</li>
  <li><b>Ergebnis.</b> Die Seite besteht aus statischen Dateien, ohne eigenen Server und ohne Benutzerkonten. Fotos lädt dein Browser erst beim Öffnen einer Karte von Wikimedia Commons.</li>
</ol>

<h3>Einsatz von KI</h3>
<ul>
  <li><b>Bildmodell:</b> Ein kleines Klassifikationsmodell (YOLOv8) wurde mit von Hand beschrifteten Fotos auf Dachformen trainiert. Es ordnet weitere Fotos einer Dachform zu und nennt dazu seine Sicherheit. Es erzeugt keine Bilder oder Texte.</li>
  <li><b>Vorrang:</b> Per Hand geprüfte Einträge gehen vor dem Modell, das Modell geht vor den Angaben aus OpenStreetMap und den Artikeltexten. Wo das Modell die Dachform setzt, steht das auf der Karte unter „Woher die Einstufung kommt“. Das Modell kann sich irren; über „Falsch eingestuft?“ lässt sich ein Eintrag melden.</li>
  <li><b>Fotos:</b> Für eine Vorhersage wird ein Foto kurz geladen, ausgewertet und wieder verworfen. Nur von Hand beschriftete Fotos bleiben als Trainingsdaten lokal gespeichert und werden nicht veröffentlicht.</li>
  <li><b>Entwicklung:</b> Programm und Seitentexte entstanden mit Unterstützung eines KI-Assistenten (Claude von Anthropic). Die Texte aus Wikipedia und Wikidata stammen nicht von einer KI.</li>
</ul>
<p class="note">Das Bildmodell kann sich irren, vor allem bei Fotos, auf denen der Turm klein oder verdeckt ist.</p>

<h3>Genauigkeit</h3>
<p>Dunkelgrau heißt nur „Dachform nicht erfasst“. Das bedeutet nicht, dass der Turm keine Zwiebelhaube hat. OpenStreetMap wird von Freiwilligen gepflegt und ist nicht überall vollständig. Fehler lassen sich dort direkt beheben; bei Türmen ohne erfasste Dachform führt „Dachform in OSM eintragen“ in der Karte zur Bearbeitung. Alle Angaben ohne Gewähr.</p>

<h3>Datenquellen und Lizenzen</h3>
<ul>
  <li>${a('https://www.openstreetmap.org/copyright', 'OpenStreetMap')}-Mitwirkende: Kirchen- und Turmdaten, Lizenz ODbL. Die daraus abgeleiteten Datendateien dieser Seite (Ordner <code>data/</code>) dürfen unter denselben Bedingungen weiterverwendet werden (ODbL: Namensnennung, Weitergabe unter gleichen Bedingungen).</li>
  <li>${a('https://openfreemap.org', 'OpenFreeMap')} © ${a('https://www.openmaptiles.org', 'OpenMapTiles')}, Daten von OpenStreetMap: Hintergrundkarte.</li>
  <li>Wikipedia (CC BY-SA 4.0): Texte und Denkmallisten, jeweils mit Link zum Artikel. Wikidata (CC0): Angaben zu den Bauwerken.</li>
  <li>Wikimedia Commons: Fotos, jeweils unter der am Bild genannten Lizenz, mit Urheber und Link zur Bildseite.</li>
  <li>Natural Earth (gemeinfrei): Ländergrenzen. MapLibre GL JS (BSD-3-Clause): Kartendarstellung.</li>
</ul>

<h3>Datenschutz</h3>
<p>Diese Seite setzt keine Cookies und verwendet keine Analyse- oder Werbedienste. Im Browser (localStorage) werden nur deine Einstellungen gespeichert: Sprache, heller oder dunkler Modus, Kartenebenen und Punktfarben. Sie verlassen deinen Browser nicht.</p>
<p>Beim Laden der Hintergrundkarte fragt dein Browser tiles.openfreemap.org ab, beim Öffnen einer Karte mit Foto Wikimedia Commons. Diese Server erhalten dabei technisch bedingt deine IP-Adresse. Die Seite selbst wird bei einem Hosting-Anbieter ausgeliefert (zum Beispiel GitHub Pages), der Zugriffe protokollieren kann.</p>

<h3>Kontakt und Quelltext</h3>
<p>Fragen, Hinweise und Korrekturen über das ${a('https://github.com/spennodenno/Zwiebelturm-Map', 'GitHub-Projekt')}, dort liegt auch der Quelltext.</p>
<p class="note">Stand der Daten: ${esc(x.date)}.</p>`;

  const ABOUT_EN = (x) => `
<h3>What this is</h3>
<p>The map shows churches and free-standing bell towers in ${esc(x.countries)} and colours them by the roof shape of the tower. Onion domes and their relatives are in colour, all other towers are grey. It is a private hobby project and not commercial.</p>

<h3>How the map is made</h3>
<ol>
  <li><b>Churches from OpenStreetMap.</b> For each country, places of worship, church buildings and free-standing bell towers are downloaded.</li>
  <li><b>Merging.</b> A church mapped both as a point and as a building becomes one entry. Tower and roof parts nearby are attached to the church.</li>
  <li><b>Roof shape from the OSM tags.</b> What counts is the roof of the tower, not the roof of the nave. If nothing is tagged, the roof shape counts as not recorded.</li>
  <li><b>Wikipedia and Wikidata</b> are merged for selected regions: article text, entries of the Bavarian monument list, photos, year built and other details. If a text names the roof shape (for example “Zwiebelhaube”), a word rule picks it up. That is an ordinary text search, not AI.</li>
  <li><b>Image model.</b> A model suggests roof shapes from photos (see “Use of AI”). Where it is very sure (90 % or more) it sets the roof type on the map; spot checks and reports are reviewed by hand.</li>
  <li><b>Result.</b> The page is made of static files, with no server of its own and no user accounts. Your browser loads photos from Wikimedia Commons only when you open a card.</li>
</ol>

<h3>Use of AI</h3>
<ul>
  <li><b>Image model:</b> A small classification model (YOLOv8) was trained on hand-labelled photos to tell roof shapes apart. It assigns further photos to a roof shape and reports how sure it is. It does not generate images or text.</li>
  <li><b>Precedence:</b> Entries checked by hand come first, then the model, then the OpenStreetMap tags and article texts. Where the model sets the roof type, the card says so under “Where the classification comes from”. The model can be wrong; “Misclassified?” on the card reports an entry.</li>
  <li><b>Photos:</b> For a prediction a photo is downloaded briefly, analysed and discarded. Only hand-labelled photos stay on a local disk as training data, and they are not published.</li>
  <li><b>Development:</b> The software and the texts of this page were written with the help of an AI assistant (Claude by Anthropic). The texts from Wikipedia and Wikidata are not AI-written.</li>
</ul>
<p class="note">The image model can be wrong, especially on photos where the tower is small or hidden.</p>

<h3>Accuracy</h3>
<p>Dark grey only means “roof shape not recorded”. It does not mean the tower has no onion dome. OpenStreetMap is maintained by volunteers and is not complete everywhere. Mistakes can be fixed there directly; for towers without a recorded roof shape, “Add the roof shape in OSM” on the card opens the editor. No guarantee for any of the information.</p>

<h3>Data sources and licences</h3>
<ul>
  <li>${a('https://www.openstreetmap.org/copyright', 'OpenStreetMap')} contributors: church and tower data, licence ODbL. The data files derived from it on this site (folder <code>data/</code>) may be reused under the same terms (ODbL: attribution, share-alike).</li>
  <li>${a('https://openfreemap.org', 'OpenFreeMap')} © ${a('https://www.openmaptiles.org', 'OpenMapTiles')}, data from OpenStreetMap: base map.</li>
  <li>Wikipedia (CC BY-SA 4.0): texts and monument lists, each with a link to the article. Wikidata (CC0): facts about the buildings.</li>
  <li>Wikimedia Commons: photos, each under the licence shown with it, with author and a link to the file page.</li>
  <li>Natural Earth (public domain): country borders. MapLibre GL JS (BSD-3-Clause): map rendering.</li>
</ul>

<h3>Privacy</h3>
<p>This page sets no cookies and uses no analytics or advertising services. Only your settings are saved in the browser (localStorage): language, light or dark mode, map layers and dot colours. They do not leave your browser.</p>
<p>When the base map loads, your browser contacts tiles.openfreemap.org; when you open a card with a photo, it contacts Wikimedia Commons. These servers receive your IP address as a technical necessity. The page itself is delivered by a hosting provider (for example GitHub Pages), which may log requests.</p>

<h3>Contact and source code</h3>
<p>Questions, hints and corrections via the ${a('https://github.com/spennodenno/Zwiebelturm-Map', 'GitHub project')}, which also holds the source code.</p>
<p class="note">Data as of ${esc(x.date)}.</p>`;

  const T = {
    de: {
      title: 'Zwiebelturm-Karte',
      lede: (n, c) => `<b>${n}</b> Kirchen und Türme in ${c}. Farbig: Zwiebelhauben und Verwandte.`,
      legend: 'Dachform des Turms',
      hint: 'Klick auf einen Eintrag blendet ihn aus, Klick auf den Farbpunkt ändert die Farbe. Grau heißt: andere Turmform, oder in OpenStreetMap steht noch keine Dachform.',
      pickColor: 'Farbe ändern', colorsReset: 'Farben zurücksetzen',
      themeToLight: 'Zum hellen Modus wechseln', themeToDark: 'Zum dunklen Modus wechseln',
      about: 'Über diese Karte', aboutHtml: ABOUT_DE,
      credits: (d) => `Stand ${d}. Daten © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>-Mitwirkende (ODbL), Wikidata (CC0), Texte aus Wikipedia (CC BY-SA), Fotos von Wikimedia Commons (Lizenz am Bild), Hintergrundkarte: OpenFreeMap © OpenMapTiles, Grenzen: Natural Earth.`,
      loading: 'Lade Kirchen …',
      nodata: 'Noch keine Daten. Zuerst <code>python build.py</code> ausführen.',
      noname: 'Kirche ohne Namen in OSM', tower: 'Glockenturm',
      roof: 'Turmdach', built: 'Baujahr', height: 'Höhe', denomination: 'Konfession',
      naveRoof: 'Dach des Gebäudes', onions: 'Zwiebelhauben erfasst', place: 'Ort', architect: 'Architekt',
      style: 'Baustil', patron: 'Patrozinium', diocese: 'Diözese', monument: 'Denkmalnummer',
      monumentText: 'Denkmalliste', layers: 'Kartenebenen',
      g_labels: 'Ortsnamen', g_water: 'Gewässer', g_roads: 'Straßen und Bahn', g_borders: 'Landesgrenzen (Bundesländer)',
      g_landuse: 'Wald, Siedlung, Gebäude (ab Zoom 12)', nobase: 'Hintergrundkarte nicht erreichbar (offline?).',
      photo: 'Foto', why: 'Woher die Einstufung kommt', allTags: 'Alle OSM-Angaben', nearby: 'Zugehöriges Objekt',
      addRoof: 'Dachform in OSM eintragen', website: 'Website', source: 'Quelle',
      matched: (m) => m.dist == null ? 'Verknüpft über OSM-Tag' : `Verknüpft über Koordinaten (${m.dist} m)`,
      close: 'Schließen', error: 'Details konnten nicht geladen werden.',
      fixTitle: 'Falsch eingestuft?', fixOwner: 'Neue Dachform (gilt sofort, wird später geprüft):',
      fixPublic: 'Richtige Dachform melden (öffnet GitHub, ein Konto ist nötig):',
      fixDone: (x) => `Geändert auf „${x}“. Zur Prüfung vorgemerkt.`, fixFail: 'Nicht gespeichert: ',
      fixNoServer: 'Läuft python serve.py?',
    },
    en: {
      title: 'Onion Dome Map',
      lede: (n, c) => `<b>${n}</b> churches and towers in ${c}. In colour: onion domes and their relatives.`,
      legend: 'Tower roof type',
      hint: 'Click an entry to hide it, click its colour dot to change the colour. Grey means another tower type, or no roof shape recorded in OpenStreetMap yet.',
      pickColor: 'Change colour', colorsReset: 'Reset colours',
      themeToLight: 'Switch to light mode', themeToDark: 'Switch to dark mode',
      about: 'About this map', aboutHtml: ABOUT_EN,
      credits: (d) => `As of ${d}. Data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (ODbL), Wikidata (CC0), text from Wikipedia (CC BY-SA), photos from Wikimedia Commons (licence shown with each), base map: OpenFreeMap © OpenMapTiles, borders: Natural Earth.`,
      loading: 'Loading churches …',
      nodata: 'No data yet. Run <code>python build.py</code> first.',
      noname: 'Church without a name in OSM', tower: 'Bell tower',
      roof: 'Tower roof', built: 'Built', height: 'Height', denomination: 'Denomination',
      naveRoof: 'Roof of the building', onions: 'Onion roofs mapped', place: 'Place', architect: 'Architect',
      style: 'Style', patron: 'Dedication', diocese: 'Diocese', monument: 'Monument no.',
      monumentText: 'Monument list (Denkmalliste)', layers: 'Map layers',
      g_labels: 'Place names', g_water: 'Rivers and lakes', g_roads: 'Roads and railways', g_borders: 'State borders',
      g_landuse: 'Forest, settlements, buildings (from zoom 12)', nobase: 'Base map not reachable (offline?).',
      photo: 'Photo', why: 'Where the classification comes from', allTags: 'All OSM tags', nearby: 'Related object',
      addRoof: 'Add the roof shape in OSM', website: 'Website', source: 'Source',
      matched: (m) => m.dist == null ? 'Linked through the OSM tag' : `Linked by coordinates (${m.dist} m)`,
      close: 'Close', error: 'Could not load the details.',
      fixTitle: 'Misclassified?', fixOwner: 'New roof type (applies at once, checked later):',
      fixPublic: 'Report the correct roof type (opens GitHub, an account is needed):',
      fixDone: (x) => `Changed to “${x}”. Marked for review.`, fixFail: 'Not saved: ',
      fixNoServer: 'Is python serve.py running?',
    },
  };
  let lang = 'de';
  try { lang = localStorage.getItem('zt-lang') || ((navigator.language || 'de').startsWith('de') ? 'de' : 'en'); }
  catch (e) { lang = (navigator.language || 'de').startsWith('de') ? 'de' : 'en'; }
  if (!T[lang]) lang = 'en';
  const t = (k) => T[lang][k];
  const fmt = (n) => Number(n).toLocaleString(lang === 'de' ? 'de-DE' : 'en-GB');

  let man, map, cats, current = null, curIdx = -1, curCoords = null, fixMsg = '';
  let owner = false;                 // true only when the page is served by python serve.py
  let setCats = () => {};            // set in init: (changes: [[pointIndex, categoryIndex]]) -> recolours dots
  const REPO = 'https://github.com/spennodenno/Zwiebelturm-Map';
  const hidden = new Set();
  const chunkCache = new Map();

  // ---------- theme (set on <html data-theme> before first paint by index.html) ----------
  let theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  const ICON = {
    sun: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    moon: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>',
  };
  // OpenFreeMap styles: "dark" and its light counterpart "positron" use the same layers.
  const STYLE_URL = { dark: 'https://tiles.openfreemap.org/styles/dark', light: 'https://tiles.openfreemap.org/styles/positron' };
  // The dark style paints buildings (rgb 10,10,10) almost exactly like the ground (rgb 12,12,12), so
  // they are there from zoom 12 on but cannot be seen. This gives them a visible fill and outline.
  const BUILDING_PAINT = { dark: { 'fill-color': '#1a2128', 'fill-outline-color': '#34414e' }, light: null };

  // ---------- dot colours (changed in the legend, kept in this browser) ----------
  const HEX = /^#[0-9a-f]{6}$/i;
  let userColors = {};
  try { userColors = JSON.parse(localStorage.getItem('zt-colors') || '{}') || {}; } catch (e) { userColors = {}; }
  const colorOf = (c) => (HEX.test(userColors[c.key] || '') ? userColors[c.key] : c.color);
  const saveColors = () => { try { localStorage.setItem('zt-colors', JSON.stringify(userColors)); } catch (e) { /* private mode */ } };

  function el(tag, attrs, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') e.className = v; else if (k === 'style') e.style.cssText = v; else e.setAttribute(k, v);
    }
    for (const c of children.flat()) if (c != null && c !== false) e.append(c);
    return e;
  }
  const ext = (href, text) => el('a', { href, target: '_blank', rel: 'noopener' }, text);

  // ---------- start ----------
  // Base map: OpenFreeMap (free vector tiles made from OpenStreetMap, no key). If it cannot be
  // reached the page still works and shows the countries as plain shapes.
  const GROUPS = { labels: ['place'], water: ['water', 'waterway', 'water_name'],
    roads: ['transportation', 'transportation_name'], borders: ['boundary'],
    landuse: ['landcover', 'landuse', 'building', 'aeroway', 'park'] };
  let layerPrefs = { labels: true, water: true, roads: true, borders: true, landuse: true };
  try { Object.assign(layerPrefs, JSON.parse(localStorage.getItem('zt-layers') || '{}')); } catch (e) { /* ignore */ }
  let baseLayers = null;   // {group: [layer ids]} once the base map is loaded
  const styleCache = {};   // theme -> style JSON
  function loadBaseStyle(th) {
    if (styleCache[th]) return Promise.resolve(styleCache[th]);
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 7000);
    return fetch(STYLE_URL[th], { signal: ctl.signal })
      .then((r) => { if (!r.ok) throw new Error('style'); return r.json(); })
      .then((s) => { styleCache[th] = s; return s; })
      .catch(() => null).finally(() => clearTimeout(timer));
  }
  const copyStyle = (s) => JSON.parse(JSON.stringify(s));
  const voidStyle = () => ({ version: 8, sources: {}, layers: [{ id: 'void', type: 'background', paint: { 'background-color': css('--void') } }] });

  $('status').textContent = t('loading');
  Promise.all([
    fetch(DATA + 'manifest.json').then((r) => { if (!r.ok) throw new Error('manifest'); return r.json(); }),
    fetch(DATA + 'countries.geojson').then((r) => r.json()),
    fetch(DATA + 'points.bin').then((r) => r.arrayBuffer()),
    loadBaseStyle(theme),
    fetch(DATA + 'mask.geojson').then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(init).catch((err) => { console.error(err); $('status').innerHTML = t('nodata'); });

  function init([manifest, countries, buf, baseStyle, mask]) {
    man = manifest;
    cats = man.categories;
    const n = man.n;
    const lon = new Int32Array(buf, 0, n), lat = new Int32Array(buf, 4 * n, n), cat = new Uint8Array(buf, 8 * n, n);
    const features = new Array(n);
    for (let i = 0; i < n; i++) {
      features[i] = { type: 'Feature', id: i, properties: { c: cat[i] },
        geometry: { type: 'Point', coordinates: [lon[i] / 1e6, lat[i] / 1e6] } };
    }
    const useBase = (style) => !!(style && mask);
    const [w, s, e, nn] = man.bbox;
    map = new maplibregl.Map({
      container: 'map',
      style: useBase(baseStyle) ? copyStyle(baseStyle) : voidStyle(),
      bounds: [[w, s], [e, nn]],
      maxBounds: [[w - 25, s - 12], [e + 25, Math.min(nn + 12, 84)]],
      maxZoom: 18, dragRotate: false, pitchWithRotate: false, touchPitch: false, renderWorldCopies: false,
      attributionControl: false,
    });
    map.touchZoomRotate.disableRotation();
    window.zwiebelturm = { map };
    const wide = window.innerWidth > 720;
    if (!wide) $('legend-wrap').open = false;   // phones: legend starts folded so the map stays usable
    map.fitBounds([[w, s], [e, nn]], { duration: 0,
      padding: { top: wide ? 24 : 90, bottom: 24, left: wide ? 340 : 16, right: wide ? 24 : 16 } });
    map.addControl(new maplibregl.AttributionControl({ compact: true,
      customAttribution: '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> · Wikidata · Wikimedia Commons · Natural Earth' }), 'bottom-right');
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');

    // Everything we draw on top of the base style. Runs once at start and again after every
    // theme switch, because setStyle() removes all sources and layers that are not in the style.
    function buildLayers(withBase) {
      baseLayers = null;
      map.addSource('countries', { type: 'geojson', data: countries });
      if (withBase) {
        // sort the base map's layers into toggle groups, then hide the world outside the countries
        baseLayers = {};
        for (const l of map.getStyle().layers) {
          const g = Object.keys(GROUPS).find((k) => GROUPS[k].includes(l['source-layer']));
          if (g) (baseLayers[g] = baseLayers[g] || []).push(l.id);
          else if (l.type !== 'background') map.setLayoutProperty(l.id, 'visibility', 'none');
          if (l['source-layer'] === 'building' && l.type === 'fill' && BUILDING_PAINT[theme]) {
            for (const [k, v] of Object.entries(BUILDING_PAINT[theme])) map.setPaintProperty(l.id, k, v);
          }
        }
        for (const g of Object.keys(baseLayers)) setGroup(g, layerPrefs[g]);
        map.addSource('mask', { type: 'geojson', data: mask });
        map.addLayer({ id: 'mask', type: 'fill', source: 'mask', paint: { 'fill-color': css('--void'), 'fill-antialias': false } });
      } else {
        map.addLayer({ id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': css('--land') } });
      }
      renderPanel();
      map.addSource('pts', { type: 'geojson', data: { type: 'FeatureCollection', features }, maxzoom: 12, buffer: 8, tolerance: 0 });
      let bordersAdded = false;
      cats.forEach((c, i) => {
        const big = c.bulbous;
        if (big && !bordersAdded) {   // outlines sit above the grey dots and below the coloured ones
          bordersAdded = true;
          map.addLayer({ id: 'borders', type: 'line', source: 'countries',
            paint: { 'line-color': css('--border'), 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 10, 1.8] } });
        }
        map.addLayer({
          id: 'c' + i, type: 'circle', source: 'pts', filter: ['==', ['get', 'c'], i],
          layout: { visibility: hidden.has(i) ? 'none' : 'visible' },
          paint: {
            'circle-color': colorOf(c),
            'circle-radius': ['interpolate', ['exponential', 1.5], ['zoom'],
              4, big ? 1.8 : 0.9, 8, big ? 3.2 : 1.7, 12, big ? 6 : 4.5, 16, big ? 11 : 9],
            'circle-opacity': big ? 0.95 : ['interpolate', ['linear'], ['zoom'], 4, 0.6, 9, 0.9],
            'circle-stroke-color': css('--void'),
            'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 0, 11, 1],
          },
        });
      });
      map.addSource('sel', { type: 'geojson', data: current
        ? { type: 'Feature', geometry: { type: 'Point', coordinates: [current.lon, current.lat] }, properties: {} }
        : { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'sel', type: 'circle', source: 'sel',
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 7, 12, 12, 16, 17], 'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': css('--sel'), 'circle-stroke-width': 2 } });
      $('status').textContent = '';
    }
    map.on('load', () => buildLayers(useBase(baseStyle)));

    // theme switch: new base style, then our layers again
    let pendingBuild = null;
    map.on('style.load', () => {
      if (!pendingBuild) return;
      const withBase = pendingBuild.withBase;
      pendingBuild = null;
      buildLayers(withBase);
    });
    function setTheme(next) {
      theme = next;
      document.documentElement.setAttribute('data-theme', theme);
      try { localStorage.setItem('zt-theme', theme); } catch (err) { /* private mode */ }
      renderThemeButton();
      loadBaseStyle(next).then((style) => {
        if (theme !== next) return;   // switched again while the style was loading
        pendingBuild = { withBase: useBase(style) };
        map.setStyle(useBase(style) ? copyStyle(style) : voidStyle(), { diff: false });
      });
    }
    $('theme').addEventListener('click', () => setTheme(theme === 'dark' ? 'light' : 'dark'));

    function setGroup(g, on) {
      for (const id of (baseLayers && baseLayers[g]) || []) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
    }
    window.zwiebelturm.setGroup = setGroup;
    const layerIds = () => cats.map((_, i) => 'c' + i).filter((id, i) => !hidden.has(i) && map.getLayer(id));
    const pick = (p) => {
      const r = 6;
      const hits = map.queryRenderedFeatures([[p.x - r, p.y - r], [p.x + r, p.y + r]], { layers: layerIds() });
      let best = null, bestScore = Infinity;
      for (const f of hits) {
        const q = map.project(f.geometry.coordinates);
        // coloured dots win over grey ones under the same cursor
        const score = Math.hypot(q.x - p.x, q.y - p.y) - (cats[f.properties.c].bulbous ? 4 : 0);
        if (score < bestScore) { bestScore = score; best = f; }
      }
      return best;
    };
    map.on('click', (ev) => { const f = pick(ev.point); if (f) openCard(f.id, f.geometry.coordinates); else closeCard(); });
    let raf = 0;
    map.on('mousemove', (ev) => {
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; map.getCanvas().style.cursor = pick(ev.point) ? 'pointer' : ''; });
    });

    $('lang').addEventListener('click', () => {
      lang = lang === 'de' ? 'en' : 'de';
      try { localStorage.setItem('zt-lang', lang); } catch (err) { /* private mode */ }
      renderPanel();
      if (current) renderCard(current);
      if ($('about').open) renderAbout();
    });
    $('card-close').addEventListener('click', closeCard);
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape' && !$('about').open) closeCard(); });

    $('about-open').addEventListener('click', () => { renderAbout(); $('about').showModal(); });
    $('about-close').addEventListener('click', () => $('about').close());
    $('about').addEventListener('click', (ev) => { if (ev.target === $('about')) $('about').close(); });

    $('colors-reset').addEventListener('click', () => {
      userColors = {};
      saveColors();
      cats.forEach((c, i) => { if (map.getLayer('c' + i)) map.setPaintProperty('c' + i, 'circle-color', c.color); });
      renderPanel();
      if (current) renderCard(current);
    });
    renderPanel();

    // dots changed by hand: recolour at once (the data files only change with the next build.py)
    setCats = (changes) => {
      for (const [k, c] of changes) if (features[k]) features[k].properties.c = c;
      const src = map.getSource && map.getSource('pts');
      if (src) src.setData({ type: 'FeatureCollection', features });
    };
    // Owner mode: python serve.py answers /api/ping. Static hosting (GitHub Pages) does not.
    fetch('/api/ping', { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((j) => {
      if (!j || j.owner !== true) return;
      owner = true;
      if (current) renderCard(current);
      return fetch('/api/quick', { cache: 'no-store' }).then((r) => r.json()).then((rows) => {
        const at = new Map();
        for (let k = 0; k < n; k++) at.set(lon[k] + '_' + lat[k], k);
        const changes = [];
        for (const q of rows) {
          const k = at.get(q.lon + '_' + q.lat), ci = cats.findIndex((x) => x.key === q.roof);
          if (k !== undefined && ci >= 0) changes.push([k, ci]);
        }
        if (changes.length) setCats(changes);
      });
    }).catch(() => { /* static hosting: no owner mode */ });
  }

  // ---------- panel / legend ----------
  function countryList() {
    const names = man.countries.map((c) => c[lang] || c.en);
    return names.length > 1 ? names.slice(0, -1).join(', ') + (lang === 'de' ? ' und ' : ' and ') + names[names.length - 1] : names[0];
  }

  function renderThemeButton() {
    const b = $('theme');
    const label = theme === 'dark' ? t('themeToLight') : t('themeToDark');
    b.innerHTML = theme === 'dark' ? ICON.sun : ICON.moon;   // the icon shows the mode you switch to
    b.setAttribute('aria-label', label);
    b.title = label;
  }

  function setColor(i, hex, commit) {
    const c = cats[i];
    hex = hex.toLowerCase();
    if (hex === c.color.toLowerCase()) delete userColors[c.key]; else userColors[c.key] = hex;
    if (map.getLayer('c' + i)) map.setPaintProperty('c' + i, 'circle-color', hex);
    if (commit) {
      saveColors();
      $('colors-reset').hidden = !Object.keys(userColors).length;
      if (current) renderCard(current);
    }
  }

  function renderAbout() {
    $('about-title').textContent = t('about');
    $('about-body').innerHTML = t('aboutHtml')({ countries: countryList(), date: man.generated });
    $('about-close').setAttribute('aria-label', t('close'));
  }

  function renderPanel() {
    document.documentElement.lang = lang;
    document.title = t('title');
    document.querySelector('h1').textContent = t('title');
    $('lang').textContent = lang === 'de' ? 'EN' : 'DE';
    renderThemeButton();
    $('about-open').textContent = t('about');
    $('card-close').setAttribute('aria-label', t('close'));
    $('lede').innerHTML = t('lede')(fmt(man.n), countryList());
    $('legend-title').textContent = t('legend');
    const ul = $('legend');
    ul.textContent = '';
    let greyStarted = false;
    for (let i = cats.length - 1; i >= 0; i--) {
      const c = cats[i];
      if (!c.bulbous && !greyStarted) { greyStarted = true; ul.append(el('li', { class: 'sep', role: 'presentation' })); }
      const name = c[lang] || c.en;
      const li = el('li', { class: hidden.has(i) ? 'off' : null });
      const sw = el('input', { type: 'color', class: 'swatch', value: colorOf(c), title: t('pickColor'),
        'aria-label': `${t('pickColor')}: ${name}` });
      sw.addEventListener('input', () => setColor(i, sw.value, false));
      sw.addEventListener('change', () => setColor(i, sw.value, true));
      const b = el('button', { type: 'button', 'aria-pressed': String(!hidden.has(i)) },
        el('span', { class: 'label' }, name),
        el('span', { class: 'n' }, fmt(c.count)));
      b.addEventListener('click', () => {
        if (hidden.has(i)) hidden.delete(i); else hidden.add(i);
        b.setAttribute('aria-pressed', String(!hidden.has(i)));
        li.classList.toggle('off', hidden.has(i));
        if (map.getLayer('c' + i)) map.setLayoutProperty('c' + i, 'visibility', hidden.has(i) ? 'none' : 'visible');
      });
      li.append(sw, b);
      ul.append(li);
    }
    $('legend-hint').textContent = t('hint');
    $('colors-reset').textContent = t('colorsReset');
    $('colors-reset').hidden = !Object.keys(userColors).length;
    const lw = $('layers');
    lw.textContent = '';
    $('layers-title').textContent = t('layers');
    if (baseLayers) {
      for (const g of Object.keys(GROUPS)) {
        if (!baseLayers[g]) continue;
        const b = el('button', { type: 'button', 'aria-pressed': String(!!layerPrefs[g]) },
          el('span', { class: 'box' }), el('span', { class: 'label' }, t('g_' + g)), el('span'));
        b.addEventListener('click', () => {
          layerPrefs[g] = !layerPrefs[g];
          b.setAttribute('aria-pressed', String(layerPrefs[g]));
          window.zwiebelturm.setGroup(g, layerPrefs[g]);
          try { localStorage.setItem('zt-layers', JSON.stringify(layerPrefs)); } catch (e) { /* private mode */ }
        });
        lw.append(el('li', null, b));
      }
    } else if (map && map.loaded()) {
      lw.append(el('li', { class: 'fine' }, t('nobase')));
    }
    $('credits').innerHTML = t('credits')(man.generated);
  }

  // ---------- info card ----------
  function closeCard() {
    current = null;
    $('card').hidden = true;
    if (map && map.getSource('sel')) map.getSource('sel').setData({ type: 'FeatureCollection', features: [] });
  }

  function openCard(i, coords) {
    curIdx = i; curCoords = coords; fixMsg = '';
    map.getSource('sel').setData({ type: 'Feature', geometry: { type: 'Point', coordinates: coords }, properties: {} });
    const k = Math.floor(i / man.chunk_size);
    if (!chunkCache.has(k)) {
      chunkCache.set(k, fetch(DATA + 'd/' + String(k).padStart(4, '0') + '.json').then((r) => {
        if (!r.ok) throw new Error('chunk ' + k);
        return r.json();
      }));
    }
    const token = (openCard.token = (openCard.token || 0) + 1);
    chunkCache.get(k).then((rows) => {
      if (token !== openCard.token) return;
      current = rows[i % man.chunk_size];
      renderCard(current);
    }).catch((err) => {
      console.error(err);
      chunkCache.delete(k);
      $('card-body').replaceChildren(el('div', { class: 'card-pad' }, el('p', null, t('error'))));
      $('card').hidden = false;
    });
  }

  // Owner: change the roof type at once (serve.py writes data/overrides.csv + data/quick-changes.csv).
  // Everyone else: a prefilled GitHub issue; tools/fetch_reports.py counts them later.
  function fixBox(r) {
    const box = el('div', { class: 'fix' }, el('h3', null, t('fixTitle')),
      el('p', { class: 'fine' }, owner ? t('fixOwner') : t('fixPublic')));
    const row = el('div', { class: 'fix-row' });
    for (const k of ['onion', 'onion_double', 'welsch', 'dome', 'other']) {
      const c = cats.find((x) => x.key === k);
      if (!c) continue;
      const b = el('button', { type: 'button', class: r.roof === k ? 'cur' : '' },
        el('span', { class: 'dot', style: `background:${colorOf(c)}` }), c[lang] || c.en);
      b.addEventListener('click', () => (owner ? quickChange(r, c) : reportChange(r, c)));
      row.append(b);
    }
    box.append(row);
    if (fixMsg) box.append(el('p', { class: 'fine', role: 'status' }, fixMsg));
    return box;
  }

  function reportChange(r, c) {
    const body = [`osm_id: ${r.id}`, `proposed: ${c.key}`, `current: ${r.roof}`, `name: ${r.name || ''}`,
      `img: ${(r.wd && r.wd.image && r.wd.image.thumb) || ''}`, '',
      'Automatisch ausgewertete Meldung, bitte die Zeilen oben nicht ändern. / Machine-read report, please keep the lines above.'].join('\n');
    const url = `${REPO}/issues/new?title=${encodeURIComponent(`Meldung: ${r.id} → ${c.key}`)}&labels=report&body=${encodeURIComponent(body)}`;
    window.open(url, '_blank', 'noopener');
  }

  function quickChange(r, c) {
    const wd = r.wd || {};
    fetch('/api/quick', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: r.id, roof: c.key, previous: r.roof, name: r.name || '',
        lon: Math.round(r.lon * 1e6), lat: Math.round(r.lat * 1e6),   // exact values of points.bin (the clicked point is tile-rounded)
        img: (wd.image && wd.image.thumb) || '' }) })
      .then((res) => res.json().then((j) => { if (!res.ok) throw new Error(j.error || res.status); return j; }))
      .then(() => {
        r.roof = c.key; r.sub = c.bulbous ? c.key : null; delete r.sub_text;
        if (c.key !== 'onion') delete r.n_onion;
        r.src = ['Override (manual-quick): ' + (lang === 'de' ? 'noch nicht geprüft' : 'not yet checked')];
        setCats([[curIdx, cats.indexOf(c)]]);
        fixMsg = t('fixDone')(c[lang] || c.en);
        renderCard(r);
      })
      .catch((e) => { fixMsg = t('fixFail') + e.message + ' ' + t('fixNoServer'); renderCard(r); });
  }

  function shapeLabel(s) {
    const l = man.shape_labels[s];
    return l ? l[lang] || l.en : s;
  }

  function wikiLinkFromTag(v) {
    const m = /^([a-z-]+):(.+)$/.exec(v || '');
    return m ? [m[1], `https://${m[1]}.wikipedia.org/wiki/${encodeURIComponent(m[2].replace(/ /g, '_'))}`] : null;
  }

  function renderCard(r) {
    const tg = r.tags || {}, wd = r.wd || {};
    const c = cats.find((x) => x.key === r.roof) || cats[0];
    const body = [];
    const img = wd.image;
    if (img && (img.thumb || img.local)) {
      const fig = el('figure', null,
        el('img', { src: img.thumb || DATA + img.local, alt: r.name || '', loading: 'lazy', referrerpolicy: 'no-referrer' }),
        el('figcaption', null, `${t('photo')}: ${img.author || '?'} · `,
          img.license_url ? ext(img.license_url, img.license || 'Lizenz') : (img.license || ''),
          ' · ', ext(img.page, 'Wikimedia Commons')));
      fig.querySelector('img').addEventListener('error', () => fig.querySelector('img').remove());
      body.push(fig);
    }
    const pad = el('div', { class: 'card-pad' });
    pad.append(el('span', { class: 'chip' }, el('span', { class: 'dot', style: `background:${colorOf(c)}` }), c[lang] || c.en));
    const wdLabel = wd.label && (wd.label[lang] || wd.label.de || wd.label.en || Object.values(wd.label).find(Boolean));
    pad.append(el('h2', null, r.name || wdLabel || (r.kind === 'tower' ? t('tower') : t('noname'))));
    const P = (pid) => { const v = wd.props && wd.props[pid]; return v ? (v[lang] || v.de || v.en || Object.values(v).find(Boolean)) : null; };
    const country = man.countries.find((x) => x.iso === r.cc);
    const place = [P('P131') || tg['addr:city'] || tg['addr:place'] || tg['addr:suburb'], country && (country[lang] || country.en)].filter(Boolean).join(', ');
    pad.append(el('p', { class: 'sub' }, place));

    // The card has a fixed set of fields in a fixed order; a field without a value is left out.
    const DENOM = { catholic: 'katholisch', roman_catholic: 'römisch-katholisch', protestant: 'evangelisch',
      lutheran: 'evangelisch-lutherisch', evangelical: 'evangelikal', reformed: 'reformiert', orthodox: 'orthodox',
      old_catholic: 'altkatholisch', greek_catholic: 'griechisch-katholisch' };
    let roof = c[lang] || c.en;
    if (r.roof === 'other') roof = r.sub ? shapeLabel(r.sub) : (r.sub_text || roof);
    const own = tg['roof:shape'] || tg['building:roof:shape'];
    const naveRoof = (own && r.kind !== 'tower' && own !== r.sub) ? shapeLabel(own) : r.building_roof;
    const denom = tg.denomination ? ((lang === 'de' && DENOM[tg.denomination]) || tg.denomination.replace(/_/g, ' ')) : null;
    const facts = [
      [t('roof'), roof],
      [t('onions'), r.n_onion > 1 ? String(r.n_onion) : null],
      [t('naveRoof'), naveRoof],
      [t('built'), r.year],
      [t('style'), (tg['building:architecture'] || '').replace(/_/g, ' ') || P('P149')],
      [t('architect'), tg.architect || P('P84')],
      [t('height'), r.height ? fmt(r.height) + ' m' : null],
      [t('denomination'), denom],
      [t('patron'), P('P825')],
      [t('diocese'), tg.diocese || P('P708')],
      [t('monument'), tg['ref:BLfD'] || (r.denkmal && r.denkmal.nr)],
    ];
    const dl = el('dl', { class: 'facts' });
    for (const [l, v] of facts) if (v) dl.append(el('dt', null, l), el('dd', null, v));
    pad.append(dl);

    if (wd.intro && wd.intro.text) {
      const url = wd.wikipedia && wd.wikipedia[wd.intro.lang];
      pad.append(el('p', { class: 'intro' }, wd.intro.text + ' ', url ? el('span', { class: 'fine' }, '(', ext(url, 'Wikipedia'), ', CC BY-SA)') : null));
    }
    if (r.denkmal && r.denkmal.text) {
      pad.append(el('div', null, el('h3', null, t('monumentText')),
        el('p', { class: 'intro' }, r.denkmal.text + ' ', el('span', { class: 'fine' }, '(', ext(r.denkmal.list, 'Wikipedia'), ', CC BY-SA)'))));
    }

    const links = el('div', { class: 'links' });
    const wp = Object.assign({}, wd.wikipedia);
    const fromTag = wikiLinkFromTag(tg.wikipedia);
    if (fromTag && !wp[fromTag[0]]) wp[fromTag[0]] = fromTag[1];
    for (const [l, url] of Object.entries(wp)) links.append(ext(url, `Wikipedia (${l})`));
    const qid = wd.qid || (/^Q\d+/.exec(tg.wikidata || '') || [])[0];
    if (qid) links.append(ext('https://www.wikidata.org/wiki/' + qid, 'Wikidata'));
    const cc = wd.commons_category || (/^Category:(.+)/i.exec(tg.wikimedia_commons || '') || [])[1];
    if (cc) links.append(ext('https://commons.wikimedia.org/wiki/Category:' + encodeURIComponent(cc.replace(/ /g, '_')), 'Commons'));
    else if (/^File:/i.test(tg.wikimedia_commons || '')) links.append(ext('https://commons.wikimedia.org/wiki/' + encodeURIComponent(tg.wikimedia_commons.replace(/ /g, '_')), 'Commons'));
    const site = tg.website || tg['contact:website'];
    if (site && /^https?:\/\//.test(site)) links.append(ext(site, t('website')));
    links.append(ext('https://www.openstreetmap.org/' + r.id, 'OpenStreetMap'));
    if (r.roof === 'unknown') links.append(ext('https://www.openstreetmap.org/edit?' + r.id.replace('/', '='), t('addRoof')));
    pad.append(links);

    const why = (r.src || []).slice();
    if (wd.qid) why.push('Wikidata ' + wd.qid + ': ' + t('matched')(wd));
    if (r.denkmal) why.push('Denkmalliste ' + r.denkmal.nr + ' (' + r.denkmal.how + ')');
    if (why.length) pad.append(el('div', null, el('h3', null, t('why')), el('ul', { class: 'why' }, why.map((s) => el('li', null, s)))));

    pad.append(fixBox(r));

    const tagTable = (tags) => el('table', null, Object.keys(tags).sort().map((k) => el('tr', null, el('td', null, k), el('td', null, tags[k]))));
    const det = el('details', null, el('summary', null, `${t('allTags')} (${(r.ids || [r.id]).join(', ')})`), tagTable(tg));
    for (const a of r.near || []) det.append(el('h3', null, `${t('nearby')}: ${a.id} (${a.dist} m)`), tagTable(a.tags));
    pad.append(det);
    body.push(pad);
    $('card-body').replaceChildren(...body);
    $('card').hidden = false;
    $('card').scrollTop = 0;
  }
})();
