/* FloodShield dashboard */
const API = 'https://floodshield-backend-nyyv.onrender.com';
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 0) => (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d });
const SCEN_COLORS = { S0_release: '#38bdf8', S1_moderate: '#facc15', S2_severe: '#fb923c', S3_extreme: '#ef4444' };
const DAM = [22.76389, 70.86583];

Chart.defaults.color = '#8a9aab';
Chart.defaults.borderColor = '#243140';
Chart.defaults.font.family = "'General Sans', system-ui, sans-serif";

/* ---------------- map ---------------- */
const map = L.map('map', { zoomControl: false, preferCanvas: true }).setView([22.83, 70.86], 12);
L.control.zoom({ position: 'bottomright' }).addTo(map);
const base = {
  'Satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 18, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics' }),
  'Dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors © CARTO' }),
  'Streets': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }),
};
base['Satellite'].addTo(map);
L.control.layers(base, null, { position: 'bottomright' }).addTo(map);
L.marker(DAM, { icon: L.divIcon({ className: '', html: '<div style="width:14px;height:14px;background:#22b8cf;border:2px solid #fff;transform:rotate(45deg);box-shadow:0 0 0 3px rgba(34,184,207,.35)"></div>', iconSize: [14, 14] }) })
  .addTo(map).bindPopup('<div class="popup"><b>Machhu-2 Dam</b><br>FRL 57.30 m · Top of dam 63.70 m<br>Gross storage 92.0 Mm³ (2021 survey)</div>');

let overlay = null, roadsLayer = null, placesLayer = L.layerGroup().addTo(map), facLayer = L.layerGroup().addTo(map), probLayer = null;
let current = null, currentLayer = 'depth', frameIdx = -1, playTimer = null;
const cache = {};

const LEGENDS = {
  depth: { title: 'Max water depth (m)', grad: 'linear-gradient(90deg,#b4f0ff,#50d2ff,#2d8cff,#3c46f0,#8c28dc,#d2147a)', ticks: ['0.1', '0.5', '1.5', '3', '6', '12+'] },
  arrival: { title: 'Flood arrival time (h after breach start)', grad: 'linear-gradient(90deg,#c81428,#f06e28,#fac83c,#96d278,#4696c8)', ticks: ['0', '1', '2', '4', '8+'] },
  velocity: { title: 'Max flow velocity (m/s)', grad: 'linear-gradient(90deg,#fff5c8,#ffbe5a,#f06e32,#be1e28,#64001e)', ticks: ['0', '1', '2', '4', '7+'] },
  hazard: { title: 'Hazard rating h·(v+0.5) — Defra FD2320', rows: [['#fadc5a', 'Low  < 0.75'], ['#f59632', 'Moderate  0.75–1.25'], ['#e13c28', 'Significant  1.25–2'], ['#820028', 'Extreme  > 2']] },
  sar: { title: 'Sentinel-1 observed', rows: [['#ff40a0', 'Newly wet 2 Sep 2024'], ['#285ac8', 'Water before event']] },
  prob: { title: 'Probability of inundation (ensemble)', rows: [['#fef0d9', '< 20 %'], ['#fdcc8a', '20–40 %'], ['#fc8d59', '40–60 %'], ['#e34a33', '60–80 %'], ['#b30000', '> 80 %']] },
};
function setLegend(key) {
  const L_ = LEGENDS[key];
  let h = `<div class="title">${L_.title}</div>`;
  if (L_.grad) h += `<div class="grad" style="background:${L_.grad}"></div><div class="ticks">${L_.ticks.map(t => `<span>${t}</span>`).join('')}</div>`;
  else h += L_.rows.map(([c, t]) => `<div class="row"><span class="sw" style="background:${c}"></span>${t}</div>`).join('');
  $('#legend').innerHTML = h;
}

function outUrl(id, f) { return `${API}/outputs/scenarios/${id}/${f}`; }

function showRaster() {
  if (!current) return;
  let url, bounds;
  if (frameIdx >= 0 && current.frames.length) {
    const f = current.frames[frameIdx];
    url = outUrl(current.id, f.png); bounds = current.layers.frames_bounds;
  } else {
    const l = current.layers[currentLayer];
    url = outUrl(current.id, l.png); bounds = l.bounds;
  }
  if (overlay) { overlay.setUrl(url); overlay.setBounds(L.latLngBounds(bounds)); }
  else overlay = L.imageOverlay(url, bounds, { opacity: 0.85, interactive: false }).addTo(map);
  setLegend(frameIdx >= 0 ? 'depth' : currentLayer);
}

async function loadVectors(s) {
  // cut roads
  if (roadsLayer) map.removeLayer(roadsLayer);
  const gj = await fetch(outUrl(s.id, 'roads_cut.geojson')).then(r => r.json()).catch(() => null);
  if (gj) {
    roadsLayer = L.geoJSON(gj, {
      style: f => ({ color: '#ff5a5f', weight: ['primary', 'trunk', 'secondary'].includes(f.properties.cls) ? 3.5 : 2, opacity: .95 }),
      onEachFeature: (f, l) => l.bindPopup(`<div class="popup"><b>${f.properties.name || 'Unnamed ' + f.properties.cls + ' road'}</b><br>Max depth ${fmt(f.properties.max_depth, 1)} m · flooded ${fmt(f.properties.flooded_km, 2)} km</div>`)
    });
    if ($('#chkRoads').checked) roadsLayer.addTo(map);
  }
  placesLayer.clearLayers();
  s.places.forEach(p => {
    const m = L.circleMarker([p.lat, p.lon], { radius: p.place === 'city' ? 9 : 6, color: '#fff', weight: 1.5, fillColor: p.depth > 3 ? '#ef4444' : p.depth > 1.5 ? '#fb923c' : '#facc15', fillOpacity: .95 });
    m.bindPopup(`<div class="popup"><b>${p.name}</b> <span class="badge">${p.place}</span><br>Max depth nearby: <b>${fmt(p.depth, 1)} m</b><br>Flood arrives: <b>${p.arrival_h == null ? '—' : fmt(p.arrival_h * 60, 0) + ' min'}</b> after breach start</div>`);
    if (p.place === 'city' || p.depth > 1) m.bindTooltip(p.name, { permanent: p.place === 'city', direction: 'right', className: '' });
    placesLayer.addLayer(m);
  });
  facLayer.clearLayers();
  s.facilities.forEach(f => {
    L.circleMarker([f.lat, f.lon], { radius: 6, color: '#0c1117', weight: 2, fillColor: '#e879f9', fillOpacity: 1 })
      .bindPopup(`<div class="popup"><b>${f.name}</b><br>${f.type}<br>Depth ${fmt(f.depth, 1)} m · arrival ${f.arrival_h == null ? '—' : fmt(f.arrival_h * 60) + ' min'}</div>`)
      .addTo(facLayer);
  });
}

function setStats(s) {
  const morbi = s.places.find(p => p.name === 'Morbi');
  const items = [
    ['Flooded area', `${fmt(s.flood.area_km2, 1)} km²`, `${s.res} m grid · depth > 0.1 m`],
    ['Max depth', `${fmt(s.flood.max_depth_m, 1)} m`, `river channel · 90th pct ${fmt(s.flood.p90_depth_m, 1)} m · mean ${fmt(s.flood.mean_depth_m, 1)} m`],
    ['Peak outflow', `${fmt(s.model.peak_q)} m³/s`, `at ${fmt(s.model.t_peak_h, 2)} h`],
    ['Buildings', fmt(s.buildings.total), `${fmt(s.buildings['> 3 m'])} in > 3 m water`, true],
    ['Roads cut', `${fmt(s.roads.total_km, 1)} km`, `${s.roads.bridges_affected} bridges · ${fmt(s.railway_km, 1)} km rail`],
    ['People exposed', s.people ? fmt(s.people.total) : '—', s.people ? `${fmt(s.people.hazard_significant_or_extreme)} in significant+ hazard` : 'WorldPop 2020', true],
    ['Morbi warning time', morbi && morbi.arrival_h != null ? `${fmt(morbi.arrival_h * 60)} min` : '—', morbi ? `depth ${fmt(morbi.depth, 1)} m (1979: 3.7–9.1 m)` : 'Morbi not flooded'],
  ];
  $('#stats').innerHTML = items.map(([l, v, d, a]) => `<div class="stat ${a ? 'alert' : ''}"><div class="l">${l}</div><div class="v">${v}</div><div class="d">${d}</div></div>`).join('');
}

function setDownloads(s) {
  const d = s.downloads;
  $('#downloads').innerHTML = `<div class="title">Export ${s.id}</div>
    <a href="${outUrl(s.id, d.shp)}" download>Shapefile (.zip)</a>
    <a href="${outUrl(s.id, d.kml)}" download>KML (Google Earth)</a>
    <a href="${outUrl(s.id, d.geojson)}" download>GeoJSON</a>
    <a href="${outUrl(s.id, d.depth_tif)}" download>Depth GeoTIFF</a>
    <a href="${outUrl(s.id, d.hazard_tif)}" download>Hazard GeoTIFF</a>`;
}

function setTimeline(s) {
  const n = s.frames.length;
  $('#frameSlider').max = n; $('#frameSlider').value = n;
  frameIdx = -1; $('#frameLabel').textContent = 'Max envelope (whole event)';
}
$('#frameSlider').addEventListener('input', e => {
  const v = +e.target.value, n = current.frames.length;
  frameIdx = v >= n ? -1 : v;
  $('#frameLabel').textContent = frameIdx < 0 ? 'Max envelope (whole event)' : `t = ${fmt(current.frames[v].t_h, 1)} h · ${fmt(current.frames[v].area_km2, 1)} km² wet`;
  showRaster();
});
$('#playBtn').addEventListener('click', () => {
  if (playTimer) { clearInterval(playTimer); playTimer = null; $('#playBtn').textContent = '▶'; return; }
  $('#playBtn').textContent = '❚❚';
  const sl = $('#frameSlider'); if (+sl.value >= current.frames.length) sl.value = 0;
  current.frames.forEach(f => { const i = new Image(); i.src = outUrl(current.id, f.png); });
  playTimer = setInterval(() => {
    let v = +sl.value + 1; if (v > current.frames.length) { v = current.frames.length; clearInterval(playTimer); playTimer = null; $('#playBtn').textContent = '▶'; }
    sl.value = v; sl.dispatchEvent(new Event('input'));
  }, 650);
});

document.querySelectorAll('#layerSeg button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#layerSeg button').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); currentLayer = b.dataset.layer; frameIdx = -1;
  if (current) { $('#frameSlider').value = current.frames.length; $('#frameLabel').textContent = 'Max envelope (whole event)'; }
  if (probLayer) { map.removeLayer(probLayer); probLayer = null; }
  if (overlay && !map.hasLayer(overlay)) overlay.addTo(map);
  showRaster();
}));
$('#chkRoads').addEventListener('change', e => roadsLayer && (e.target.checked ? roadsLayer.addTo(map) : map.removeLayer(roadsLayer)));
$('#chkPlaces').addEventListener('change', e => e.target.checked ? placesLayer.addTo(map) : map.removeLayer(placesLayer));
$('#chkFac').addEventListener('change', e => e.target.checked ? facLayer.addTo(map) : map.removeLayer(facLayer));

async function selectScenario(id) {
  const s = cache[id] || (cache[id] = await fetch(`${API}/api/scenario/${id}`).then(r => r.json()));
  current = s;
  if (probLayer) { map.removeLayer(probLayer); probLayer = null; }
  if (overlay && !map.hasLayer(overlay)) overlay.addTo(map);
  document.querySelectorAll('.scen').forEach(x => x.classList.toggle('on', x.dataset.id === id));
  showRaster(); setStats(s); setDownloads(s); setTimeline(s); loadVectors(s);
  const sc = s.model.scenario;
  const meta = scenMeta[id];
  $('#scenBasis').innerHTML = `<b>${s.label}</b><br>${meta ? meta.basis : 'Custom scenario from the Run simulation tab.'}
    <div class="kv" style="margin-top:10px">
      <div><span>Reservoir level</span><b>${fmt(sc.wse0, 2)} m</b></div>
      <div><span>Breach width</span><b>${fmt(sc.breach_width)} m</b></div>
      <div><span>Formation time</span><b>${fmt(sc.tf_h, 2)} h</b></div>
      <div><span>Flood inflow peak</span><b>${fmt(sc.inflow_peak || 0)} m³/s</b></div>
      <div><span>Volume released</span><b>${fmt(s.model.released_mcm, 1)} Mm³</b></div>
      <div><span>Solver runtime</span><b>${fmt(s.model.runtime_s)} s</b></div>
    </div>
    <h3 style="margin-top:12px">Warning time by settlement</h3>
    <div class="warn-list">${s.places.filter(p => p.arrival_h != null).slice(0, 8).map(p => `<div><span>${p.name}</span><b>${fmt(p.arrival_h * 60)} min · ${fmt(p.depth, 1)} m</b></div>`).join('') || '<span class="muted">No settlements reached.</span>'}</div>`;
  drawHydro(s.model.hydrograph, hydroChart, SCEN_COLORS[id] || '#22b8cf');
}

/* ---------------- charts ---------------- */
function mkLine(canvas) {
  return new Chart(canvas, {
    type: 'line', data: { labels: [], datasets: [] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: true, labels: { boxWidth: 10, font: { size: 11 } } } },
      scales: {
        x: { type: 'linear', title: { display: true, text: 'hours after breach start' }, ticks: { maxTicksLimit: 8 } },
        y: { title: { display: true, text: 'm³/s' }, ticks: { callback: v => v >= 1000 ? (v / 1000) + 'k' : v } },
        y2: { position: 'right', grid: { display: false }, title: { display: true, text: 'reservoir m' } }
      }
    }
  });
}
const hydroChart = mkLine($('#hydroChart'));
const previewChart = mkLine($('#previewChart'));
function drawHydro(h, chart, color) {
  chart.data.datasets = [
    { label: 'Downstream discharge', data: h.t_h.map((t, i) => ({ x: t, y: h.q[i] })), borderColor: color, backgroundColor: color + '33', fill: true, pointRadius: 0, borderWidth: 2, yAxisID: 'y' },
    { label: 'Reservoir level', data: h.t_h.map((t, i) => ({ x: t, y: h.wse[i] })), borderColor: '#8a9aab', borderDash: [4, 3], pointRadius: 0, borderWidth: 1.5, yAxisID: 'y2' },
  ];
  chart.update();
}

/* ---------------- scenarios list ---------------- */
let scenMeta = {}, scenList = [];
async function loadScenarios() {
  scenList = await fetch(`${API}/api/scenarios`).then(r => r.json());
  scenList.forEach(s => scenMeta[s.id] = s);
  $('#scenarioList').innerHTML = scenList.map(s => `
    <button class="scen" data-id="${s.id}" ${s.ready ? '' : 'disabled'}>
      <span class="dot" style="background:${SCEN_COLORS[s.id]}"></span>
      <span><div class="t">${s.label.split(' - ')[0]}</div><div class="s">${s.label.split(' - ')[1] || ''}</div></span>
      <span class="n">${s.ready ? fmt(s.summary.flood.area_km2, 1) + ' km²<br>' + fmt(s.summary.buildings.total) + ' bldg' : 'computing…'}</span>
    </button>`).join('');
  document.querySelectorAll('.scen').forEach(b => b.addEventListener('click', () => selectScenario(b.dataset.id)));
  const first = scenList.find(s => s.ready && s.id === 'S1_moderate') || scenList.find(s => s.ready);
  if (first && !current) selectScenario(first.id);
  buildCompare();
  if (scenList.some(s => !s.ready)) setTimeout(loadScenarios, 20000);
}

/* ---------------- compare ---------------- */
let compareChart;
const customRuns = [];
function buildCompare() {
  const rows = scenList.filter(s => s.ready).map(s => ({ id: s.id, name: s.label.split(' - ')[0], ...s.summary })).concat(customRuns);
  if (!rows.length) return;
  const t = $('#compareTable');
  t.innerHTML = `<tr><th>Scenario</th><th>Area km²</th><th>Max d m</th><th>Peak Q m³/s</th><th>Bldg</th><th>Roads km</th><th>People</th></tr>` +
    rows.map(r => `<tr><td>${r.name}</td><td>${fmt(r.flood.area_km2, 1)}</td><td>${fmt(r.flood.max_depth_m, 1)}</td><td>${fmt(r.peak_q)}</td><td>${fmt(r.buildings.total)}</td><td>${fmt(r.roads.total_km, 1)}</td><td>${r.people ? fmt(r.people.total) : '—'}</td></tr>`).join('');
  const data = {
    labels: rows.map(r => r.name),
    datasets: [
      { label: 'Flooded area (km²)', data: rows.map(r => r.flood.area_km2), backgroundColor: rows.map(r => SCEN_COLORS[r.id] || '#22b8cf'), yAxisID: 'y' },
      { label: 'Buildings affected (÷100)', data: rows.map(r => r.buildings.total / 100), backgroundColor: '#64748b', yAxisID: 'y' },
      { label: 'People exposed (÷1000)', data: rows.map(r => r.people ? r.people.total / 1000 : 0), backgroundColor: '#334155', yAxisID: 'y' },
    ]
  };
  if (compareChart) { compareChart.data = data; compareChart.update(); }
  else compareChart = new Chart($('#compareChart'), { type: 'bar', data, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 10, font: { size: 11 } } } } } });
}

/* ---------------- custom run ---------------- */
const fields = { wse0: [' m', 1], breach_width: [' m', 0], breach_bottom: [' m', 1], tf_h: [' h', 2], inflow_peak: [' m³/s', 0], manning: ['', 3], t_end_h: [' h', 0] };
function params() {
  const p = {}; Object.keys(fields).forEach(k => p[k] = +$('#' + k).value);
  p.label = `Custom: B=${p.breach_width} m, tf=${p.tf_h} h, WSE=${p.wse0} m`;
  return p;
}
let prevT;
function updatePreview() {
  Object.entries(fields).forEach(([k, [u, d]]) => $('#o_' + k).textContent = fmt(+$('#' + k).value, d) + u);
  clearTimeout(prevT);
  prevT = setTimeout(async () => {
    const r = await fetch(`${API}/api/breach/preview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params()) }).then(r => r.json());
    drawHydro(r, previewChart, '#22b8cf');
    $('#previewStats').innerHTML = `<div><span>Peak discharge</span><b>${fmt(r.peak_q)} m³/s</b></div><div><span>Time to peak</span><b>${fmt(r.t_peak_h, 2)} h</b></div>
      <div><span>Stored volume</span><b>${fmt(r.v0_mcm, 1)} Mm³</b></div><div><span>Released</span><b>${fmt(r.released_mcm, 1)} Mm³</b></div>`;
    const f = r.froehlich;
    $('#reco').innerHTML = `Froehlich (2008) recommendation for this reservoir level: average breach width <b>${fmt(f.b_avg)} m</b>, formation time <b>${fmt(f.tf_h, 2)} h</b>. Froehlich (1995) peak-flow check: <b>${fmt(f.qp_1995)} m³/s</b>.<br><button class="btn-ghost" id="useReco">Use recommended values</button>`;
    $('#useReco').onclick = () => { $('#breach_width').value = Math.round(f.b_avg / 10) * 10; $('#tf_h').value = Math.round(f.tf_h * 4) / 4; updatePreview(); };
  }, 180);
}
Object.keys(fields).forEach(k => $('#' + k).addEventListener('input', updatePreview));

$('#runBtn').addEventListener('click', async () => {
  const btn = $('#runBtn'); btn.disabled = true;
  const js = $('#jobStatus'); js.hidden = false; js.innerHTML = 'Submitting…';
  const job = await fetch(`${API}/api/simulate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(params()) }).then(r => r.json());
  const poll = async () => {
    const j = await fetch(`${API}/api/job/${job.id}`).then(r => r.json());
    if (j.status === 'done') {
      js.innerHTML = `Run <b>${j.id}</b> finished in ${fmt(j.runtime_s)} s. Showing results on the map.`;
      btn.disabled = false;
      const s = await fetch(`${API}/api/scenario/${j.id}`).then(r => r.json());
      cache[j.id] = s;
      customRuns.push({ id: j.id, name: 'Custom ' + (customRuns.length + 1), flood: s.flood, buildings: s.buildings, roads: s.roads, people: s.people, peak_q: s.model.peak_q });
      buildCompare();
      selectScenario(j.id);
      return;
    }
    if (j.status === 'error') { js.innerHTML = `<span style="color:var(--danger)">Simulation failed: ${j.error}</span>`; btn.disabled = false; return; }
    js.innerHTML = `LISFLOOD-FP ${j.status}${j.elapsed_s ? ` · ${fmt(j.elapsed_s)} s` : ''}<div class="bar"><i></i></div>`;
    setTimeout(poll, 2500);
  };
  poll();
});

/* ---------------- uncertainty ---------------- */
async function loadUncertainty() {
  const r = await fetch(`${API}/api/uncertainty`);
  if (!r.ok) { setTimeout(loadUncertainty, 30000); return null; }
  const u = await r.json();
  $('#uncBody').innerHTML = `
    <div class="kv">
      <div><span>Ensemble members</span><b>${u.n}</b></div>
      <div><span>Grid</span><b>${u.res} m</b></div>
      <div><span>Area flooded in any run</span><b>${fmt(u.area_any_km2, 1)} km²</b></div>
      <div><span>Area flooded in ≥50 %</span><b>${fmt(u.area_p50_km2, 1)} km²</b></div>
      <div><span>Area flooded in ≥90 %</span><b>${fmt(u.area_p90_km2, 1)} km²</b></div>
      <div><span>Buildings ≥50 % chance</span><b>${fmt(u.buildings_p50)}</b></div>
      <div><span>Buildings in any run</span><b>${fmt(u.buildings_any)}</b></div>
      <div><span>People ≥50 % chance</span><b>${fmt(u.people_p50)}</b></div>
    </div>
    <h3>Sampled ranges</h3>
    <div class="muted small">Breach width ${u.ranges.breach_width[0]}–${u.ranges.breach_width[1]} m · formation ${u.ranges.tf_h[0]}–${u.ranges.tf_h[1]} h · Manning n ${u.ranges.manning[0]}–${u.ranges.manning[1]} · reservoir ${u.ranges.wse0[0]}–${u.ranges.wse0[1]} m (sunny-day failures)</div>
    <button class="btn-primary" id="showProb" style="margin-top:14px">Show probability map</button>
    <div class="table-wrap"><table class="tbl"><tr><th>Run</th><th>B m</th><th>tf h</th><th>WSE m</th><th>n</th><th>Qp</th><th>km²</th></tr>
    ${u.members.map(m => `<tr><td>${m.id}</td><td>${m.breach_width}</td><td>${m.tf_h}</td><td>${m.wse0}</td><td>${m.manning}</td><td>${fmt(m.peak_q)}</td><td>${fmt(m.area_km2, 1)}</td></tr>`).join('')}</table></div>`;
  $('#showProb').onclick = () => {
    if (overlay) map.removeLayer(overlay);
    if (probLayer) map.removeLayer(probLayer);
    probLayer = L.imageOverlay(`${API}/outputs/uncertainty/${u.png}`, u.bounds, { opacity: .85 }).addTo(map);
    if (roadsLayer) map.removeLayer(roadsLayer); $('#chkRoads').checked = false;
    setLegend('prob');
  };
  return u;
}

/* ---------------- Sentinel-1 observed layer ---------------- */
let sarLayer = null, sarInfo = null;
$('#chkSar').addEventListener('change', async e => {
  if (!e.target.checked) { if (sarLayer) map.removeLayer(sarLayer); return; }
  if (!sarInfo) sarInfo = await fetch(`${API}/api/sar`).then(r => r.json());
  if (!sarLayer) sarLayer = L.imageOverlay(`${API}/outputs/sar/${sarInfo.png}`, sarInfo.bounds, { opacity: .9 })
    .bindTooltip(`Sentinel-1: ${fmt(sarInfo.flooded_km2, 1)} km² newly wet on ${sarInfo.after} (vs ${sarInfo.before})`);
  sarLayer.addTo(map);
});

/* ---------------- verification ---------------- */
async function loadVerification() {
  const r = await fetch(`${API}/api/verification`); if (!r.ok) return;
  const v = await r.json();
  const mb = Object.entries(v.mass_balance);
  const maxErr = Math.max(...mb.map(([, m]) => Math.abs(m.error_pct)));
  const conv = Object.entries(v.convergence);
  const val = v.validation_1979;
  $('#verif').innerHTML = `
    <div class="kv">
      <div><span>Mass-balance error (worst run)</span><b>${fmt(maxErr, 2)} %</b></div>
      <div><span>Runs checked</span><b>${mb.length}</b></div>
      ${conv.map(([id, c]) => `<div><span>${id.split('_')[0]} area 60 m vs 30 m</span><b>${fmt(c.area_60m, 1)} / ${fmt(c.area_30m, 1)} km²</b></div><div><span>Grid sensitivity</span><b>${fmt(c.diff_pct, 1)} %</b></div>`).join('')}
    </div>
    ${val ? `<div class="card" style="margin-top:6px"><b style="color:var(--text)">1979 plausibility check</b><br>
      Reported 1979: ${val.observed}.<br>
      Model S3 analogue (${val.res} m grid): Morbi <b style="color:var(--text)">${fmt(val.model_morbi_depth_m, 1)} m</b>, flood arrives at ${fmt(val.model_morbi_arrival_min)} min after breach start; Lilapar ${fmt(val.model_lilapar_depth_m, 1)} m.
      <b style="color:${val.within_range ? '#4ade80' : '#f59e0b'}">${val.within_range ? 'Inside' : 'Outside'} the reported range.</b>
      This is a plausibility check, not a calibration: the dam was rebuilt in 1989 and Morbi's terrain has changed.</div>` : ''}
    ${v.sar_check ? `<div class="card" style="margin-top:8px"><b style="color:var(--text)">Satellite check (Sentinel-1)</b><br>
      ${v.sar_check.event}: <b style="color:var(--text)">${fmt(v.sar_check.captured_by_model_pct, 0)} %</b> of SAR-detected flooded pixels in the Machchhu corridor lie inside the modelled S0 extent. ${fmt(v.sar_check.sar_pixels_outside_corridor_pct, 0)} % of SAR wet pixels are in other rain-fed catchments not driven by the dam. ${v.sar_check.note}</div>` : ''}`;
}

/* ---------------- SPH ---------------- */
let sphData = null, sphKey = 'validation', sphTimer = null, sphChart = null;
async function loadSPH() {
  sphData = await fetch(`${API}/api/sph`).then(r => r.json()).catch(() => ({}));
  const v = sphData.validation;
  if (v) {
    sphChart = new Chart($('#sphChart'), {
      type: 'scatter',
      data: { datasets: [
        { label: 'FloodShield SPH', data: v.sph.map(([t, z]) => ({ x: t, y: z })), showLine: true, pointRadius: 0, borderColor: '#22b8cf', borderWidth: 2 },
        { label: 'Martin & Moyce experiment', data: v.experiment.map(([z, t]) => ({ x: t, y: z })), pointRadius: 4, backgroundColor: '#f59e0b' } ] },
      options: { responsive: true, maintainAspectRatio: false, animation: false, plugins: { legend: { labels: { boxWidth: 10, font: { size: 11 } } } },
        scales: { x: { title: { display: true, text: 'T = t·√(g/a)' }, min: 0, max: 2.8 }, y: { title: { display: true, text: 'Front Z = x/a' }, min: 1 } } }
    });
    $('#sphStats').innerHTML = `<div><span>Fluid particles</span><b>${fmt(v.particles)}</b></div><div><span>Mean front error</span><b>${fmt(v.mean_abs_pct, 1)} %</b></div>
      <div><span>RMSE (Z)</span><b>${fmt(v.rmse_Z, 3)}</b></div><div><span>Runtime</span><b>${fmt(v.runtime_s)} s</b></div>`;
  }
  drawSPH();
}
function drawSPH() {
  clearInterval(sphTimer);
  const d = sphData && sphData[sphKey];
  const cv = $('#sphCanvas'), ctx = cv.getContext('2d');
  if (!d) { ctx.clearRect(0, 0, cv.width, cv.height); $('#sphCaption').textContent = 'Not computed yet.'; return; }
  const frames = d.frames; let k = 0;
  const isVal = sphKey === 'validation';
  const [x0, x1, y1] = isVal ? [0, 5, 1.6] : [-125, 262, 26];
  const sx = cv.width / (x1 - x0), sy = cv.height / y1, s = Math.min(sx, sy * 1);
  const col = v => { const c = Math.min(v / (isVal ? 2 : 15), 1); return `hsl(${200 - 190 * c},90%,${45 + 15 * c}%)`; };
  const draw = () => {
    const f = frames[k];
    ctx.fillStyle = '#0a0f14'; ctx.fillRect(0, 0, cv.width, cv.height);
    ctx.fillStyle = '#243140'; ctx.fillRect(0, cv.height - 3, cv.width, 3);
    const r = isVal ? 1.6 : 1.4;
    for (let i = 0; i < f.x.length; i++) { ctx.fillStyle = col(f.speed[i]); ctx.fillRect((f.x[i] - x0) * sx - r / 2, cv.height - 3 - f.y[i] * sx * (isVal ? 1 : 3) - r / 2, r, r); }
    ctx.fillStyle = '#c9d4de'; ctx.font = '22px JetBrains Mono';
    ctx.fillText(isVal ? `T = ${f.T}` : `t = ${f.t} s after breach`, 14, 30);
    k = (k + 1) % frames.length;
  };
  draw(); sphTimer = setInterval(draw, 700);
  $('#sphCaption').textContent = isVal
    ? 'Square water column (a × a) collapsing in a tank; colour = speed. Front position compared with experiment above.'
    : `Vertical section through the breach: ${fmt(d.H, 1)} m of water (FRL 57.30 m over breach bottom 42 m), instantaneous full-depth breach, ${fmt(d.particles)} particles, vertical scale ×3. SPH front speed ${fmt(d.sph_front_speed_ms, 1)} m/s vs Ritter dry-bed theory ${fmt(d.ritter_front_speed_ms, 1)} m/s (upper bound).`;
}
document.querySelectorAll('#sphSeg button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('#sphSeg button').forEach(x => x.classList.remove('on')); b.classList.add('on'); sphKey = b.dataset.k; drawSPH();
}));

/* ---------------- tabs ---------------- */
document.querySelectorAll('.tab').forEach(t => t.addEventListener('click', () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.pane').forEach(x => x.classList.remove('active'));
  t.classList.add('active'); $('#pane-' + t.dataset.tab).classList.add('active');
  if (t.dataset.tab === 'compare' && compareChart) compareChart.resize();
}));

setLegend('depth');
loadScenarios();
updatePreview();
loadUncertainty();
loadVerification();
loadSPH();
