// Loads data + meta, wires the control panel, and renders all four tabs. ORI is
// computed live via OdorModel using whatever coefficients/options the controls select.
const APP = {
  meta: null, forecast: null, historical: null,
  _callbacks: [],
  onChange(cb) { this._callbacks.push(cb); },
  _fire() { this._callbacks.forEach(function (cb) { cb(); }); },
  mode() { return document.getElementById("mode-select").value; },
  activeCoeffs() {
    if (this.mode() === "custom") return this._customCoeffs();
    return this.meta.coeffs[this.mode()];
  },
  _customCoeffs() {
    var c = {};
    Object.keys(this.meta.custom_slider_ranges).forEach(function (k) {
      if (SPATIAL_KEYS.indexOf(k) === -1) {
        c[k] = parseFloat(document.getElementById("cc-" + k).value);
      }
    });
    return c;
  },
  opts() {
    var isCustom = this.mode() === "custom";
    var wd = this.meta.wind_defaults;
    var dd = this.meta.distance_defaults;
    return {
      pressureOffset: this.meta.pressure_offset,
      windFilter: modeIsProximity() ? false : document.getElementById("wind-filter").checked,
      continuousAlignment: document.getElementById("continuous-alignment")?.checked ?? true,
      penalty: isCustom
        ? 1 - (parseFloat(document.getElementById("cc-penalty_pct").value) / 100)
        : 1 - (wd.penalty_pct / 100),
      boost: isCustom
        ? parseFloat(document.getElementById("cc-boost").value)
        : wd.boost,
      distanceDecay: modeIsProximity() ? false : document.getElementById("distance-decay").checked,
      decayRate: isCustom
        ? parseFloat(document.getElementById("cc-decay_rate").value)
        : dd.rate,
    };
  },
  oriFor(cell) { return OdorModel.computeOri(cell, this.activeCoeffs(), this.opts()); },
};

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(path);
  return r.json();
}

// ── Controls ─────────────────────────────────────────────────────────────────

// Keys that are spatial adjustment parameters, not model coefficients
var SPATIAL_KEYS = ["penalty_pct", "boost", "decay_rate"];

// Modes where wind alignment and distance decay are baked into the regression
// coefficients — post-hoc toggles would double-count the spatial effects
var PROXIMITY_MODES = ["pittsburgh_proximity", "calvert_proximity"];

function modeIsProximity() { return PROXIMITY_MODES.indexOf(APP.mode()) !== -1; }

function syncToggleRow() {
  var tr = document.querySelector(".toggle-row");
  if (tr) tr.hidden = modeIsProximity();
}

var CC_LABELS = {
  "const": "Const (intercept)",
  "temperature": "Temperature",
  "temperature_squared": "Temp²",
  "solar_radiation": "Solar Radiation",
  "relative_humidity": "Rel. Humidity",
  "wind_speed": "Wind Speed",
  "precipitation": "Precipitation",
  "diurnal_temperature_range": "Diurnal Temp Range",
  "boundary_layer_height": "Boundary Layer Ht",
  "atmospheric_pressure": "Atm. Pressure",
  "multi_source_exposure": "Source Exposure β",
  "wind_align_weighted": "Wind Alignment β",
  "penalty_pct": "Wind Penalty %",
  "boost": "Wind Boost",
  "decay_rate": "Decay Rate /mi",
};

function buildModeSelect() {
  var sel = document.getElementById("mode-select");
  Object.keys(APP.meta.mode_labels).forEach(function (key) {
    var o = document.createElement("option"); o.value = key; o.textContent = APP.meta.mode_labels[key];
    sel.appendChild(o);
  });
  var custom = document.createElement("option"); custom.value = "custom"; custom.textContent = "Custom (manual)";
  sel.appendChild(custom);
  sel.value = APP.meta.default_mode || "pittsburgh_proximity";
}

function buildCustomCoeffSliders() {
  var box = document.getElementById("custom-coeffs");
  var ranges = APP.meta.custom_slider_ranges;
  var proxDefs = APP.meta.coeffs.pittsburgh_proximity || {};
  var wd = APP.meta.wind_defaults;
  var dd = APP.meta.distance_defaults;

  function fmt(k, v) {
    if (k === "penalty_pct") return Math.round(v) + "%";
    if (k === "boost" || k === "decay_rate") return parseFloat(v).toFixed(2);
    return parseFloat(v).toFixed(4);
  }

  function addSlider(k, r, defVal) {
    var label = CC_LABELS[k] || k;
    var valId = "cc-val-" + k;
    var wrap = document.createElement("label");
    wrap.style.fontSize = "0.78rem";
    wrap.innerHTML = label + ' <span id="' + valId + '">' + fmt(k, defVal) + '</span>' +
      '<input type="range" id="cc-' + k + '" min="' + r[0] + '" max="' + r[1] +
      '" step="' + r[2] + '" value="' + defVal + '">';
    wrap.querySelector("input").addEventListener("input", function () {
      document.getElementById(valId).textContent = fmt(k, this.value);
    });
    box.appendChild(wrap);
  }

  function sectionHead(text) {
    var h = document.createElement("div");
    h.className = "cc-section-head";
    h.textContent = text;
    box.appendChild(h);
  }

  sectionHead("Model Coefficients");
  Object.keys(ranges).filter(function (k) { return SPATIAL_KEYS.indexOf(k) === -1; })
    .forEach(function (k) {
      addSlider(k, ranges[k], (proxDefs[k] != null) ? proxDefs[k] : 0);
    });

  sectionHead("Spatial Adjustments");
  addSlider("penalty_pct", ranges.penalty_pct || [0, 100, 5], wd.penalty_pct);
  addSlider("boost", ranges.boost || [1.0, 3.0, 0.05], wd.boost);
  addSlider("decay_rate", ranges.decay_rate || [0.0, 0.5, 0.01], dd.rate);
}

function wireControls() {
  ["mode-select", "wind-filter", "continuous-alignment", "distance-decay"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("input", function () {
      document.getElementById("custom-coeffs").hidden = (APP.mode() !== "custom");
      syncToggleRow();
      APP._fire();
    });
  });
  document.getElementById("custom-coeffs").addEventListener("input", function () { APP._fire(); });
}

// ── Tab routing ───────────────────────────────────────────────────────────────

function setActiveTab(name) {
  document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("active", t.dataset.tab === name); });
  document.querySelectorAll(".tab-panel").forEach(function (p) { p.classList.toggle("active", p.id === "tab-" + name); });
  if (APP._onTab) APP._onTab(name);
}
APP.switchTab = setActiveTab;

// ── 16-Day forecast grid ──────────────────────────────────────────────────────

function renderForecastGrid() {
  var loc = document.getElementById("forecast-loc").value;
  var grid = document.getElementById("forecast-grid");
  grid.innerHTML = "";
  APP.forecast.dates.forEach(function (d) {
    var cell = APP.forecast.features[d][loc];
    if (!cell) return;
    var ori = APP.oriFor(cell);
    var tier = OdorModel.getRiskTier(ori);
    var rgb = "rgb(" + tier.rgb.join(",") + ")";
    var dt = new Date(d + "T00:00:00");
    var card = document.createElement("div");
    card.className = "clean-card";
    card.innerHTML =
      '<div style="font-weight:600;font-size:0.78rem;">' + dt.toLocaleDateString(undefined, {weekday:"short"}) + '</div>' +
      '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month:"short", day:"numeric"}) + '</div>' +
      '<div style="font-size:1.4rem;font-weight:700;color:' + rgb + ';margin:0.25rem 0;">' + ori.toFixed(1) + '%</div>' +
      '<span class="badge-pill ' + tier.cls + '">' + tier.label.split(" ")[0] + '</span>';
    grid.appendChild(card);
  });
}

function buildForecastLocSelect() {
  var sel = document.getElementById("forecast-loc");
  APP.forecast.locations.forEach(function (l) {
    var locId = l.id || l.zip;
    var o = document.createElement("option"); o.value = locId; o.textContent = locId + " — " + l.name;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderForecastGrid);
}

// ── Leaflet map ───────────────────────────────────────────────────────────────

APP._mapState = { map: null, geo: null, geojson: null, dateSel: null };
APP._map = null;
APP._userMarker = null;

function mapPanelScaffold() {
  var panel = document.getElementById("tab-map");
  panel.innerHTML =
    '<button id="btn-locate-map" class="btn-locate">📍 Use My Location</button>' +
    '<div class="map-toolbar">' +
    '  <label>Date <select id="map-date"></select></label>' +
    '  <fieldset class="layers"><legend>Layers</legend>' +
    '    <label><input type="checkbox" id="layer-risk" checked> Risk</label>' +
    '    <label title="Coming soon"><input type="checkbox" id="layer-plume" disabled> Plume</label>' +
    '    <label title="Coming soon"><input type="checkbox" id="layer-reports" disabled> Reports</label>' +
    '  </fieldset>' +
    '</div><div id="map"></div>';
  var sel = panel.querySelector("#map-date");
  APP.forecast.dates.forEach(function (d, i) {
    var o = document.createElement("option"); o.value = d; o.textContent = d; if (i === 1) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderMap);
  panel.querySelector("#layer-risk").addEventListener("change", renderMap);
  APP._mapState.dateSel = sel;
}

async function ensureMap() {
  if (APP._mapState.map) return;
  var IND = [37.0486, -88.3480];
  var map = L.map("map").setView([IND[0] - 0.05, IND[1]], 10);
  L.tileLayer("https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    { attribution: "© OpenStreetMap contributors, © CARTO", maxZoom: 19 }).addTo(map);
  L.circleMarker(IND, { radius: 9, color: "#475569", fillColor: "#64748b", fillOpacity: 0.9 })
    .bindTooltip("Calvert City Industrial Complex (Source)").addTo(map);
  APP._mapState.map = map;
  APP._map = map;  // alias for geolocation handler
  APP._mapState.geojson = await loadJSON("calvert_areas.geojson");
}

function renderMap() {
  if (!APP._mapState.map) return;
  var ms = APP._mapState;
  var date = ms.dateSel.value;
  var showRisk = document.getElementById("layer-risk").checked;
  if (ms.geo) { ms.map.removeLayer(ms.geo); ms.geo = null; }
  if (!showRisk) return;
  var feats = APP.forecast.features[date] || {};
  ms.geo = L.geoJSON(ms.geojson, {
    style: function (f) {
      var locId = f.properties.GEOID || f.properties.zip || f.properties.ZCTA5CE10 || "";
      var cell = feats[locId];
      if (!cell) return { color: "#94a3b8", weight: 1, fillColor: "#cbd5e1", fillOpacity: 0.2 };
      var tier = OdorModel.getRiskTier(APP.oriFor(cell));
      return { color: "#475569", weight: 1.5, fillColor: "rgb(" + tier.rgb.join(",") + ")", fillOpacity: 0.45 };
    },
    onEachFeature: function (f, layer) {
      var locId = f.properties.GEOID || f.properties.zip || f.properties.ZCTA5CE10 || "";
      var cell = feats[locId];
      var ori = cell ? APP.oriFor(cell) : null;
      var tier = cell ? OdorModel.getRiskTier(ori) : { label: "N/A" };
      var displayName = f.properties.display_name || f.properties.NAME || locId;
      layer.bindTooltip(
        "Area: " + displayName + "<br>ORI: " +
        (ori === null ? "N/A" : ori.toFixed(1) + "%") + "<br>" + tier.label
      );
    },
  }).addTo(ms.map);
}

// ── 30-day historical calendar ────────────────────────────────────────────────

function renderMonthly() {
  var panel = document.getElementById("tab-monthly");
  if (!panel.querySelector("#monthly-loc")) {
    panel.innerHTML =
      '<label>Location <select id="monthly-loc"></select></label>' +
      '<div class="calendar-head calendar-grid"></div>' +
      '<div id="calendar" class="calendar-grid"></div>';
    var sel = panel.querySelector("#monthly-loc");
    APP.historical.locations.forEach(function (l) {
      var locId = l.id || l.zip;
      var o = document.createElement("option"); o.value = locId; o.textContent = locId + " — " + l.name;
      sel.appendChild(o);
    });
    sel.addEventListener("change", renderMonthly);
    var head = panel.querySelector(".calendar-head");
    ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].forEach(function (d) {
      var c = document.createElement("div"); c.textContent = d; head.appendChild(c);
    });
  }
  var loc = panel.querySelector("#monthly-loc").value;
  var cal = panel.querySelector("#calendar");
  cal.innerHTML = "";
  var dates = APP.historical.dates;
  var firstWeekday = (new Date(dates[0] + "T00:00:00").getDay() + 6) % 7; // Mon=0
  for (var i = 0; i < firstWeekday; i++) { cal.appendChild(document.createElement("div")); }
  dates.forEach(function (d) {
    var cell = APP.historical.features[d][loc];
    var div = document.createElement("div");
    div.className = "clean-card";
    if (cell) {
      var ori = APP.oriFor(cell);
      var tier = OdorModel.getRiskTier(ori);
      var dt = new Date(d + "T00:00:00");
      div.innerHTML =
        '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined,{month:"short",day:"numeric"}) + '</div>' +
        '<div style="font-size:1.1rem;font-weight:700;color:rgb(' + tier.rgb.join(",") + ');">' + ori.toFixed(1) + '%</div>' +
        '<span class="badge-pill ' + tier.cls + '" title="Wind ' + cell.wind_speed.toFixed(1) + ' mph @ ' +
        Math.round(cell.wind_dir) + '°, PBLH ' + Math.round(cell.blh) + ' ft, Rain ' + cell.precip.toFixed(2) + ' in">' +
        tier.label.split(" ")[0] + '</span>';
    }
    cal.appendChild(div);
  });
}

// ── Report tab ────────────────────────────────────────────────────────────────

function buildFormUrl(lat, lon) {
  var cfg = window.GOOGLE_FORM;
  var u = new URL(cfg.viewUrl);
  if (lat != null && lon != null) {
    u.searchParams.set(cfg.latEntry, lat.toFixed(6));
    u.searchParams.set(cfg.lonEntry, lon.toFixed(6));
  }
  if (cfg.tsEntry) {
    u.searchParams.set(cfg.tsEntry, new Date().toISOString());
  }
  return u.toString();
}

function renderReportTab() {
  var panel = document.getElementById("tab-report");
  if (panel.dataset.built) return;
  panel.dataset.built = "1";
  panel.innerHTML =
    '<div class="clean-card" style="text-align:left;max-width:560px;">' +
    '<h3 style="margin:0 0 0.5rem;">Report an Odor</h3>' +
    '<p style="font-size:0.85rem;margin:0 0 0.8rem;color:#475569;">Choose an option — your location will be captured and the report form will open automatically with it pre-filled.</p>' +
    '<div style="display:flex;flex-direction:column;gap:0.6rem;">' +
    '  <button id="btn-geo" class="report-btn">📍 Use My Exact Location</button>' +
    '  <button id="btn-geo-skew" class="report-btn">🛡️ Use Approximate Location (Privacy)</button>' +
    '</div>' +
    '<div id="geo-status" style="font-size:0.78rem;color:#64748b;margin-top:0.7rem;min-height:1.2em;"></div>' +
    '</div>';

  function openForm(skew) {
    var statusEl = panel.querySelector("#geo-status");
    if (!navigator.geolocation) {
      statusEl.textContent = "Geolocation not supported by this browser.";
      return;
    }
    statusEl.textContent = "Getting your location…";
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      if (skew) { lat += (Math.random() * 0.004) - 0.002; lon += (Math.random() * 0.004) - 0.002; }
      statusEl.textContent = (skew ? "Approximate" : "Exact") + " location captured — opening form…";
      window.open(buildFormUrl(lat, lon), "_blank", "noopener");
    }, function (err) {
      statusEl.textContent = "Could not get location: " + err.message;
    }, { enableHighAccuracy: true, timeout: 10000 });
  }

  panel.querySelector("#btn-geo").addEventListener("click", function () { openForm(false); });
  panel.querySelector("#btn-geo-skew").addEventListener("click", function () { openForm(true); });
}

// ── Map tab geolocation ───────────────────────────────────────────────────────

function wireLocateMapButton() {
  document.getElementById("btn-locate-map")?.addEventListener("click", function () {
    if (!navigator.geolocation) { alert("Geolocation not supported."); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      // Center the map
      if (APP._map) APP._map.setView([lat, lon], 12);
      // Add a marker
      if (APP._userMarker) APP._map.removeLayer(APP._userMarker);
      APP._userMarker = L.marker([lat, lon]).addTo(APP._map)
        .bindPopup("Your location").openPopup();
      // Find nearest location in today's data and show its ORI
      var today = APP.forecast.dates[0];
      var features = APP.forecast.features[today] || {};
      var nearest = null, nearestDist = Infinity;
      APP.forecast.locations.forEach(function (loc) {
        var d = Math.hypot(loc.lat - lat, loc.lon - lon);
        if (d < nearestDist) { nearestDist = d; nearest = loc; }
      });
      if (nearest) {
        var locId = nearest.id || nearest.zip;
        var cell = features[locId];
        if (cell) {
          var ori = APP.oriFor(cell);
          var tier = OdorModel.getRiskTier(ori);
          L.popup().setLatLng([lat, lon])
            .setContent("<b>Nearest forecast area:</b> " + nearest.name + "<br><b>ORI: " + ori + "%</b> — " + tier.label)
            .openOn(APP._map);
        }
      }
    }, function () { alert("Could not get your location."); });
  });
}

// ── Main bootstrap ────────────────────────────────────────────────────────────

async function main() {
  APP.meta       = await loadJSON("data/meta.json");
  APP.forecast   = await loadJSON("data/forecast.json");
  APP.historical = await loadJSON("data/historical.json");

  document.getElementById("source-badge").textContent = "🟢 Source: " + APP.meta.source;
  document.getElementById("updated-stamp").textContent = "Updated: " + APP.meta.generated_utc;

  buildModeSelect();
  buildCustomCoeffSliders();
  buildForecastLocSelect();
  if (APP.meta.distance_defaults) {
    document.getElementById("distance-decay").checked = APP.meta.distance_defaults.enabled;
  }
  wireControls();
  syncToggleRow();

  mapPanelScaffold();
  wireLocateMapButton();

  document.querySelectorAll(".tab").forEach(function (t) {
    t.addEventListener("click", function () { setActiveTab(t.dataset.tab); });
  });

  APP._onTab = async function (name) {
    if (name === "map")     { await ensureMap(); setTimeout(function () { APP._mapState.map.invalidateSize(); renderMap(); }, 50); }
    if (name === "monthly") { renderMonthly(); }
    if (name === "report")  { renderReportTab(); }
  };

  APP.onChange(renderForecastGrid);
  APP.onChange(function () {
    if (APP._mapState.map) renderMap();
    if (document.getElementById("tab-monthly").classList.contains("active")) renderMonthly();
  });

  renderForecastGrid();

  // Pre-initialize the map on the default tab
  await ensureMap();
  renderMap();
}

main().catch(function (e) {
  document.body.insertAdjacentHTML("afterbegin",
    '<p style="color:red;padding:1rem;font-family:monospace;">Failed to load: ' + e.message +
    " — run <code>python generate_site.py</code> first, then serve with <code>python -m http.server 8765 --directory docs</code></p>"
  );
});
