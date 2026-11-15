/* Zwiebelturm-Karte – front end. Plain JS, MapLibre GL for WebGL rendering.
   Data files are produced by the Python pipeline (see README.md). */
(function () {
  'use strict';
  const DATA = 'data/';
  const $ = (id) => document.getElementById(id);
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const T = {
    de: {
      title: 'Zwiebelturm-Karte',
      lede: (n, c) => `<b>${n}</b> Kirchen und Türme in ${c}. Farbig: Zwiebelhauben und Verwandte.`,
      legend: 'Dachform des Turms',
      hint: 'Klick auf einen Eintrag blendet ihn aus. Grau heißt: andere Turmform, oder in OpenStreetMap steht noch keine Dachform.',
      wiki: 'Wikipedia-Daten eingebunden für',
      of: 'von', churches: 'Kirchen',
      credits: (d) => `Stand ${d}. Daten © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>-Mitwirkende (ODbL), Wikidata (CC0), Texte aus Wikipedia (CC BY-SA), Fotos von Wikimedia Commons (Lizenz am Bild), Grenzen: Natural Earth.`,
      loading: 'Lade Kirchen …',
      nodata: 'Noch keine Daten. Zuerst <code>python build.py</code> ausführen.',
      noname: 'Kirche ohne Namen in OSM', tower: 'Glockenturm',
      roof: 'Dachform Turm', built: 'Baujahr', height: 'Höhe', denomination: 'Konfession',
      naveRoof: 'Dach des Gebäudes', onions: 'Zwiebelhauben erfasst', place: 'Ort', architect: 'Architekt',
      style: 'Baustil', heritage: 'Denkmalschutz',
      photo: 'Foto', why: 'Woher die Einstufung kommt', allTags: 'Alle OSM-Angaben', nearby: 'Zugehöriges Objekt',
      addRoof: 'Dachform in OSM eintragen', website: 'Website', source: 'Quelle',
      matched: (m) => m.dist == null ? 'Verknüpft über OSM-Tag' : `Verknüpft über Koordinaten (${m.dist} m)`,
      close: 'Schließen', error: 'Details konnten nicht geladen werden.',
    },
    en: {
      title: 'Onion Dome Map',
      lede: (n, c) => `<b>${n}</b> churches and towers in ${c}. In colour: onion domes and their relatives.`,
      legend: 'Tower roof type',
      hint: 'Click an entry to hide it. Grey means another tower type, or no roof shape recorded in OpenStreetMap yet.',
      wiki: 'Wikipedia data merged for',
      of: 'of', churches: 'churches',
      credits: (d) => `As of ${d}. Data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (ODbL), Wikidata (CC0), text from Wikipedia (CC BY-SA), photos from Wikimedia Commons (licence shown with each), borders: Natural Earth.`,
      loading: 'Loading churches …',
      nodata: 'No data yet. Run <code>python build.py</code> first.',
      noname: 'Church without a name in OSM', tower: 'Bell tower',
      roof: 'Tower roof', built: 'Built', height: 'Height', denomination: 'Denomination',
      naveRoof: 'Roof of the building', onions: 'Onion roofs mapped', place: 'Place', architect: 'Architect',
      style: 'Style', heritage: 'Heritage status',
      photo: 'Photo', why: 'Where the classification comes from', allTags: 'All OSM tags', nearby: 'Related object',
      addRoof: 'Add the roof shape in OSM', website: 'Website', source: 'Source',
      matched: (m) => m.dist == null ? 'Linked through the OSM tag' : `Linked by coordinates (${m.dist} m)`,
      close: 'Close', error: 'Could not load the details.',
    },
  };
  let lang = 'de';
  try { lang = localStorage.getItem('zt-lang') || ((navigator.language || 'de').startsWith('de') ? 'de' : 'en'); }
  catch (e) { lang = (navigator.language || 'de').startsWith('de') ? 'de' : 'en'; }
  if (!T[lang]) lang = 'en';
  const t = (k) => T[lang][k];
  const fmt = (n) => Number(n).toLocaleString(lang === 'de' ? 'de-DE' : 'en-GB');

  let man, map, cats, current = null;
  const hidden = new Set();
  const chunkCache = new Map();

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
  $('status').textContent = t('loading');
  Promise.all([
    fetch(DATA + 'manifest.json').then((r) => { if (!r.ok) throw new Error('manifest'); return r.json(); }),
    fetch(DATA + 'countries.geojson').then((r) => r.json()),
    fetch(DATA + 'points.bin').then((r) => r.arrayBuffer()),
  ]).then(init).catch((err) => { console.error(err); $('status').innerHTML = t('nodata'); });

  function init([manifest, countries, buf]) {
    man = manifest;
    cats = man.categories;
    const n = man.n;
    const lon = new Int32Array(buf, 0, n), lat = new Int32Array(buf, 4 * n, n), cat = new Uint8Array(buf, 8 * n, n);
    const features = new Array(n);
    for (let i = 0; i < n; i++) {
      features[i] = { type: 'Feature', id: i, properties: { c: cat[i] },
        geometry: { type: 'Point', coordinates: [lon[i] / 1e6, lat[i] / 1e6] } };
    }
    const [w, s, e, nn] = man.bbox;
    map = new maplibregl.Map({
      container: 'map',
      style: { version: 8, sources: {}, layers: [{ id: 'void', type: 'background', paint: { 'background-color': css('--void') } }] },
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

    map.on('load', () => {
      map.addSource('countries', { type: 'geojson', data: countries });
      map.addLayer({ id: 'land', type: 'fill', source: 'countries', paint: { 'fill-color': css('--land') } });
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
          paint: {
            'circle-color': c.color,
            'circle-radius': ['interpolate', ['exponential', 1.5], ['zoom'],
              4, big ? 1.8 : 0.9, 8, big ? 3.2 : 1.7, 12, big ? 6 : 4.5, 16, big ? 11 : 9],
            'circle-opacity': big ? 0.95 : ['interpolate', ['linear'], ['zoom'], 4, 0.6, 9, 0.9],
            'circle-stroke-color': css('--void'),
            'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 0, 11, 1],
          },
        });
      });
      map.addSource('sel', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'sel', type: 'circle', source: 'sel',
        paint: { 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 7, 12, 12, 16, 17], 'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 } });
      $('status').textContent = '';
    });

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
      try { localStorage.setItem('zt-lang', lang); } catch (e) { /* private mode */ }
      renderPanel();
      if (current) renderCard(current);
    });
    $('card-close').addEventListener('click', closeCard);
    document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') closeCard(); });
    renderPanel();
  }

  // ---------- panel / legend ----------
  function renderPanel() {
    document.documentElement.lang = lang;
    document.title = t('title');
    document.querySelector('h1').textContent = t('title');
    $('lang').textContent = lang === 'de' ? 'EN' : 'DE';
    $('card-close').setAttribute('aria-label', t('close'));
    const names = man.countries.map((c) => c[lang] || c.en);
    const list = names.length > 1 ? names.slice(0, -1).join(', ') + (lang === 'de' ? ' und ' : ' and ') + names[names.length - 1] : names[0];
    $('lede').innerHTML = t('lede')(fmt(man.n), list);
    $('legend-title').textContent = t('legend');
    const ul = $('legend');
    ul.textContent = '';
    let greyStarted = false;
    for (let i = cats.length - 1; i >= 0; i--) {
      const c = cats[i];
      if (!c.bulbous && !greyStarted) { greyStarted = true; ul.append(el('li', { class: 'sep', role: 'presentation' })); }
      const b = el('button', { type: 'button', 'aria-pressed': String(!hidden.has(i)) },
        el('span', { class: 'dot', style: `background:${c.color}` }),
        el('span', { class: 'label' }, c[lang] || c.en),
        el('span', { class: 'n' }, fmt(c.count)));
      b.addEventListener('click', () => {
        if (hidden.has(i)) hidden.delete(i); else hidden.add(i);
        b.setAttribute('aria-pressed', String(!hidden.has(i)));
        if (map.getLayer('c' + i)) map.setLayoutProperty('c' + i, 'visibility', hidden.has(i) ? 'none' : 'visible');
      });
      ul.append(el('li', null, b));
    }
    $('legend-hint').textContent = t('hint');
    const reg = $('regions');
    reg.textContent = '';
    for (const r of man.wikipedia_regions || []) {
      const b = el('button', { type: 'button' }, r.label);
      b.addEventListener('click', () => map.fitBounds([[r.bbox[0], r.bbox[1]], [r.bbox[2], r.bbox[3]]], { padding: 60 }));
      reg.append(el('p', { class: 'fine' }, t('wiki') + ' ', b, ` (${fmt(r.matched)} ${t('of')} ${fmt(r.churches)} ${t('churches')})`));
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
    if (img && (img.local || img.thumb)) {
      const fig = el('figure', null,
        el('img', { src: img.local ? DATA + img.local : img.thumb, alt: r.name || '', loading: 'lazy', referrerpolicy: 'no-referrer' }),
        el('figcaption', null, `${t('photo')}: ${img.author || '?'} · `,
          img.license_url ? ext(img.license_url, img.license || 'Lizenz') : (img.license || ''),
          ' · ', ext(img.page, 'Wikimedia Commons')));
      fig.querySelector('img').addEventListener('error', () => fig.querySelector('img').remove());
      body.push(fig);
    }
    const pad = el('div', { class: 'card-pad' });
    pad.append(el('span', { class: 'chip' }, el('span', { class: 'dot', style: `background:${c.color}` }), c[lang] || c.en));
    const wdLabel = wd.label && (wd.label[lang] || wd.label.de || wd.label.en);
    pad.append(el('h2', null, r.name || wdLabel || (r.kind === 'tower' ? t('tower') : t('noname'))));
    const country = man.countries.find((x) => x.iso === r.cc);
    const place = [tg['addr:city'] || tg['addr:place'] || tg['addr:suburb'], country && (country[lang] || country.en)].filter(Boolean).join(', ');
    const desc = wd.desc && (wd.desc[lang] || wd.desc.de || wd.desc.en);
    pad.append(el('p', { class: 'sub' }, desc ? `${desc} · ${place}` : place));

    const facts = [];
    let roof = c[lang] || c.en;
    if (r.roof === 'other' && r.sub) roof = shapeLabel(r.sub);
    facts.push([t('roof'), roof]);
    if (r.n_onion > 1) facts.push([t('onions'), String(r.n_onion)]);
    const own = tg['roof:shape'] || tg['building:roof:shape'];
    if (own && r.kind !== 'tower' && own !== r.sub) facts.push([t('naveRoof'), shapeLabel(own)]);
    if (r.year) facts.push([t('built'), r.year]);
    if (r.height) facts.push([t('height'), fmt(r.height) + ' m']);
    if (tg.denomination) facts.push([t('denomination'), tg.denomination.replace(/_/g, ' ')]);
    if (tg.architect) facts.push([t('architect'), tg.architect]);
    if (tg['building:architecture']) facts.push([t('style'), tg['building:architecture'].replace(/_/g, ' ')]);
    if (tg.heritage) facts.push([t('heritage'), [tg['heritage:operator'], tg['ref:' + (tg['heritage:operator'] || '')]].filter(Boolean).join(' ') || tg.heritage]);
    const seen = new Set(facts.map((f) => f[0].toLowerCase()));
    for (const [l, v] of (wd.facts && (wd.facts[lang] || wd.facts.de || wd.facts.en)) || []) {
      if (!seen.has(l.toLowerCase())) facts.push([l, v]);
    }
    const dl = el('dl', { class: 'facts' });
    for (const [l, v] of facts) dl.append(el('dt', null, l), el('dd', null, v));
    pad.append(dl);

    if (wd.intro && wd.intro.text) {
      const url = wd.wikipedia && wd.wikipedia[wd.intro.lang];
      pad.append(el('p', { class: 'intro' }, wd.intro.text + ' ', url ? el('span', { class: 'fine' }, '(', ext(url, 'Wikipedia'), ', CC BY-SA)') : null));
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
    if (why.length) pad.append(el('div', null, el('h3', null, t('why')), el('ul', { class: 'why' }, why.map((s) => el('li', null, s)))));

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
