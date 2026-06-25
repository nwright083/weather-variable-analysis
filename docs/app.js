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
      windFilter: isCustom,
      continuousAlignment: true,
      penalty: isCustom
        ? 1 - (parseFloat(document.getElementById("cc-penalty_pct").value) / 100)
        : 1 - (wd.penalty_pct / 100),
      boost: isCustom
        ? parseFloat(document.getElementById("cc-boost").value)
        : wd.boost,
      distanceDecay: isCustom,
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
  var sel = document.getElementById("mode-select");
  if (sel) sel.addEventListener("input", function () {
    document.getElementById("custom-coeffs").hidden = (APP.mode() !== "custom");
    APP._fire();
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

// ── Location-select mini-maps (16-Day and 30-Day tabs) ────────────────────────

APP._locMaps = {};  // keyed by "forecast" | "monthly"

async function ensureGeoJson() {
  if (!APP._mapState.geojson) {
    APP._mapState.geojson = await loadJSON("calvert_areas.geojson");
  }
}

function updateLocLabel(tabKey, name) {
  var el = document.getElementById(tabKey + "-loc-label");
  if (el) el.textContent = name;
}

function nearestLocation(lat, lon) {
  var nearest = null, nearestDist = Infinity;
  APP.forecast.locations.forEach(function (loc) {
    var d = Math.hypot(loc.lat - lat, loc.lon - lon);
    if (d < nearestDist) { nearestDist = d; nearest = loc; }
  });
  return nearest;
}

function locDisplayName(locId) {
  if (!APP._mapState.geojson) return locId;
  var feat = APP._mapState.geojson.features.find(function (f) {
    return (f.properties.GEOID || f.properties.zip || "") === locId;
  });
  return feat ? (feat.properties.display_name || feat.properties.NAME || locId) : locId;
}

async function buildLocSelectMap(tabKey) {
  if (APP._locMaps[tabKey]) {
    APP._locMaps[tabKey].map.invalidateSize();
    return;
  }

  var panel = document.getElementById("tab-" + tabKey);
  if (!panel.querySelector(".loc-header")) {
    // Build the tab structure (header + mini-map + content area)
    var calHead = tabKey === "monthly"
      ? '<div class="calendar-head calendar-grid"></div>'
      : "";
    var contentId = tabKey === "forecast" ? "forecast-grid" : "calendar";
    var contentCls = tabKey === "forecast" ? "card-grid" : "calendar-grid";
    panel.innerHTML =
      '<div class="loc-header">' +
      '  <button id="btn-locate-' + tabKey + '" class="btn-locate-small">📍 My Location</button>' +
      '  <span id="' + tabKey + '-loc-label" class="loc-label">Click a tract on the map</span>' +
      '</div>' +
      '<div id="' + tabKey + '-loc-map" class="loc-select-map"></div>' +
      calHead +
      '<div id="' + contentId + '" class="' + contentCls + '"></div>';

    if (tabKey === "monthly") {
      var head = panel.querySelector(".calendar-head");
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach(function (d) {
        var c = document.createElement("div"); c.textContent = d; head.appendChild(c);
      });
    }
  }

  await ensureGeoJson();

  var IND = [37.0486, -88.3480];
  var m = L.map(tabKey + "-loc-map", {zoomControl: false}).setView([37.05, -88.35], 9);
  L.tileLayer("https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    {attribution: "© OpenStreetMap contributors, © CARTO", maxZoom: 19}).addTo(m);
  L.circleMarker(IND, {radius: 6, color: "#475569", fillColor: "#64748b", fillOpacity: 0.85})
    .bindTooltip("Industrial Complex").addTo(m);

  var locs = APP.forecast.locations;
  var locId = locs.length ? (locs[0].id || locs[0].zip) : null;
  var geoLayer = null;

  function renderLocMap() {
    if (geoLayer) { m.removeLayer(geoLayer); geoLayer = null; }
    var date = APP.forecast.dates[0];
    var feats = APP.forecast.features[date] || {};
    geoLayer = L.geoJSON(APP._mapState.geojson, {
      style: function (f) {
        var fid = f.properties.GEOID || f.properties.zip || "";
        var cell = feats[fid];
        var isSel = (fid === locId);
        if (!cell) return {color: isSel ? "#1e3a8a" : "#94a3b8", weight: isSel ? 3 : 1, fillColor: "#cbd5e1", fillOpacity: isSel ? 0.35 : 0.15};
        var tier = OdorModel.getRiskTier(APP.oriFor(cell));
        return {
          color: isSel ? "#1e3a8a" : "#475569",
          weight: isSel ? 3 : 1.2,
          fillColor: "rgb(" + tier.rgb.join(",") + ")",
          fillOpacity: isSel ? 0.65 : 0.4,
        };
      },
      onEachFeature: function (f, layer) {
        var fid = f.properties.GEOID || f.properties.zip || "";
        var dname = f.properties.display_name || f.properties.NAME || fid;
        layer.on("click", function () {
          locId = fid;
          renderLocMap();
          updateLocLabel(tabKey, dname);
          if (tabKey === "forecast") renderForecastGrid();
          else renderMonthly();
        });
        var cell = feats[fid];
        var ori = cell ? APP.oriFor(cell) : null;
        layer.bindTooltip(dname + (ori ? "<br>ORI: " + ori.toFixed(1) + "%" : ""), {sticky: true});
      },
    }).addTo(m);
  }

  // Set initial label
  updateLocLabel(tabKey, locDisplayName(locId) || (locs[0] && locs[0].name) || "");

  renderLocMap();
  APP.onChange(renderLocMap);

  APP._locMaps[tabKey] = {
    map: m,
    getLocId: function () { return locId; },
    setLocId: function (id, name) { locId = id; renderLocMap(); updateLocLabel(tabKey, name); },
  };

  // Wire the "My Location" button for this tab
  var btn = document.getElementById("btn-locate-" + tabKey);
  if (btn) {
    btn.addEventListener("click", function () {
      if (!navigator.geolocation) { alert("Geolocation not supported."); return; }
      navigator.geolocation.getCurrentPosition(function (pos) {
        var near = nearestLocation(pos.coords.latitude, pos.coords.longitude);
        if (!near) return;
        var nid = near.id || near.zip;
        APP._locMaps[tabKey].setLocId(nid, locDisplayName(nid) || near.name);
        if (tabKey === "forecast") renderForecastGrid();
        else renderMonthly();
      }, function () { alert("Could not get your location."); });
    });
  }

  // Initial content render
  if (tabKey === "forecast") renderForecastGrid();
  else renderMonthly();
}

// ── 16-Day forecast grid ──────────────────────────────────────────────────────

function renderForecastGrid() {
  var lm = APP._locMaps && APP._locMaps.forecast;
  var loc = lm ? lm.getLocId() : (APP.forecast.locations[0] ? (APP.forecast.locations[0].id || APP.forecast.locations[0].zip) : null);
  var grid = document.getElementById("forecast-grid");
  if (!loc || !grid) return;
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
      '<div style="font-weight:600;font-size:0.78rem;">' + dt.toLocaleDateString(undefined, {weekday: "short"}) + '</div>' +
      '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month: "short", day: "numeric"}) + '</div>' +
      '<div style="font-size:1.4rem;font-weight:700;color:' + rgb + ';margin:0.25rem 0;">' + ori.toFixed(1) + '%</div>' +
      '<span class="badge-pill ' + tier.cls + '">' + tier.label.split(" ")[0] + '</span>';
    grid.appendChild(card);
  });
}

// ── Leaflet map (ORI overview tab) ────────────────────────────────────────────

APP._mapState = {map: null, geo: null, geojson: null, dateSel: null};
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
    {attribution: "© OpenStreetMap contributors, © CARTO", maxZoom: 19}).addTo(map);
  L.circleMarker(IND, {radius: 9, color: "#475569", fillColor: "#64748b", fillOpacity: 0.9})
    .bindTooltip("Calvert City Industrial Complex (Source)").addTo(map);
  APP._mapState.map = map;
  APP._map = map;
  await ensureGeoJson();
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
      if (!cell) return {color: "#94a3b8", weight: 1, fillColor: "#cbd5e1", fillOpacity: 0.2};
      var tier = OdorModel.getRiskTier(APP.oriFor(cell));
      return {color: "#475569", weight: 1.5, fillColor: "rgb(" + tier.rgb.join(",") + ")", fillOpacity: 0.45};
    },
    onEachFeature: function (f, layer) {
      var locId = f.properties.GEOID || f.properties.zip || f.properties.ZCTA5CE10 || "";
      var cell = feats[locId];
      var ori = cell ? APP.oriFor(cell) : null;
      var tier = cell ? OdorModel.getRiskTier(ori) : {label: "N/A"};
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
  var lm = APP._locMaps && APP._locMaps.monthly;
  var loc = lm ? lm.getLocId()
    : (APP.historical.locations[0] ? (APP.historical.locations[0].id || APP.historical.locations[0].zip) : null);
  var cal = document.getElementById("calendar");
  if (!loc || !cal) return;
  cal.innerHTML = "";
  var dates = APP.historical.dates;
  var firstWeekday = (new Date(dates[0] + "T00:00:00").getDay() + 6) % 7;
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
        '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month: "short", day: "numeric"}) + '</div>' +
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
    if (!navigator.geolocation) { statusEl.textContent = "Geolocation not supported by this browser."; return; }
    statusEl.textContent = "Getting your location…";
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      if (skew) { lat += (Math.random() * 0.004) - 0.002; lon += (Math.random() * 0.004) - 0.002; }
      statusEl.textContent = (skew ? "Approximate" : "Exact") + " location captured — opening form…";
      window.open(buildFormUrl(lat, lon), "_blank", "noopener");
    }, function (err) {
      statusEl.textContent = "Could not get location: " + err.message;
    }, {enableHighAccuracy: true, timeout: 10000});
  }

  panel.querySelector("#btn-geo").addEventListener("click", function () { openForm(false); });
  panel.querySelector("#btn-geo-skew").addEventListener("click", function () { openForm(true); });
}

// ── Methodology tab ───────────────────────────────────────────────────────────

// Hand-written explanations keyed by mode id. Kept here (not in meta.json) so the
// prose stays editable without touching the data pipeline. Any mode present in
// meta.mode_labels but missing here falls back to a generic description.
var MODE_DOCS = {
  pittsburgh_proximity: {
    tagline: "Default. The only model aware of your location and the wind direction.",
    data: "Pittsburgh zip-day panel — ~36,600 observations (every ZIP × every day), 2018–2026, logistic regression.",
    how: "Beyond weather, it adds two spatial terms fitted in the same regression: <b>source proximity</b> " +
      "(risk decays with distance from the Calvert City industrial complex) and <b>continuous wind alignment</b> " +
      "(higher risk when the wind is actually carrying air from the source toward you). This is why the map " +
      "shows different risk for different tracts on the same day.",
    notes: [
      "Debiased: day-of-week and holiday <i>reporting</i> habits are removed so only weather/physics drive the score.",
      "Precipitation was corrected to −0.864 (the raw panel fit had an overfitting artifact that forced rainy days to 100%).",
      "Less sensitive to raw temperature than the Calvert/Pittsburgh daily models — once proximity, wind alignment, and the inversion signal (DTR) are accounted for, absolute warmth adds little.",
    ],
    best: "Best all-around choice: the only model with true spatial + wind-direction awareness.",
  },
  estimated_calvert: {
    tagline: "Pittsburgh science, hand-tuned for Calvert's flat rural terrain.",
    data: "Pittsburgh city-wide daily model, with coefficients manually adjusted using engineering judgment (not fitted to Calvert data).",
    how: "Starts from the city-wide Pittsburgh daily model, then strengthens the <b>wind-speed</b> and " +
      "<b>boundary-layer-height</b> sensitivities (open rural terrain disperses and mixes differently than a city " +
      "valley) and raises the baseline. It has <b>no</b> proximity or wind-direction terms, so every tract gets the " +
      "same score on a given day.",
    notes: [
      "Most temperature- and stagnation-sensitive of the models — it reacts strongly to warm, calm summer days with strong overnight inversions.",
      "It carries the strongest boundary-layer-height sensitivity of any model (deliberately boosted for rural mixing).",
      "Calibrated by judgment, not fit to local data — treat as an informed estimate.",
    ],
    best: "Use to see a Calvert-terrain-adjusted view, or to compare against the proximity model.",
  },
  exact_pittsburgh: {
    tagline: "The unmodified Pittsburgh model — a reference baseline.",
    data: "Pittsburgh city-wide daily logistic regression, used exactly as trained.",
    how: "The raw Pittsburgh science applied to Calvert weather with no terrain adjustment and no proximity terms. " +
      "Only the elevation pressure-offset correction is applied.",
    notes: [
      "Same temperature/DTR sensitivity as Estimated Calvert, but without the rural wind/mixing boosts.",
      "Useful as a 'what does the original model say, untouched?' reference.",
    ],
    best: "Reference/comparison baseline.",
  },
  calvert_fitted: {
    tagline: "Fitted directly from real Calvert City odor reports.",
    data: "Local Calvert reports (tester logs and/or the public form), fitted by analyze_calvert_reports.py.",
    how: "The only model trained on actual Calvert data. It learns which conditions precede real reported odors " +
      "here, rather than borrowing from another city. Severity (1–5) is used to weight stronger smells more.",
    notes: [
      "Installed only after it beats the Pittsburgh model on cross-validated accuracy and clears minimum-report gates.",
      "Improves as more reports are collected.",
    ],
    best: "Once enough local reports exist, this is the most Calvert-specific model available.",
  },
};

function renderMethodsTab() {
  var panel = document.getElementById("tab-methods");
  if (panel.dataset.built) return;
  panel.dataset.built = "1";

  var meta = APP.meta;
  var fitted = meta.fitted_meta || null;

  var html = '<div class="methods-wrap">';

  // Intro — what the number means
  html +=
    '<div class="method-card">' +
    '<h2>How these forecasts work</h2>' +
    '<p>Every forecast is an <b>Odor Risk Index (ORI)</b> — the estimated probability (0–100%) of a ' +
    'community-wide <b>odor-trapping</b> event on that day. It is computed from weather using logistic ' +
    'regression: the model combines the day\'s conditions into a score, then converts it to a probability.</p>' +
    '<p style="margin-bottom:0;">It predicts when the <b>atmosphere will trap and concentrate</b> odor near the ground — ' +
    'not whether the source is emitting. Risk tiers:</p>' +
    '<div class="tier-row">' +
    '<span class="badge-pill badge-clear">Clear / Low &lt; 15%</span>' +
    '<span class="badge-pill badge-moderate">Moderate 15–30%</span>' +
    '<span class="badge-pill badge-elevated">Elevated 30–50%</span>' +
    '<span class="badge-pill badge-high">High ≥ 50%</span>' +
    '</div></div>';

  // Shared physics
  html +=
    '<div class="method-card">' +
    '<h2>What drives the risk (all models)</h2>' +
    '<p>All models read the same weather inputs. The strongest physical drivers of odor trapping are:</p>' +
    '<ul>' +
    '<li><b>Diurnal temperature range (DTR)</b> — a big day-to-night temperature swing means clear, calm nights and ' +
    'strong overnight <b>temperature inversions</b> that trap air near the ground. The single most consistent driver.</li>' +
    '<li><b>Boundary-layer height (BLH)</b> — how high the air mixes. A low mixing height keeps odor concentrated near ' +
    'the surface. (DTR and BLH measure two sides of the same inversion physics.)</li>' +
    '<li><b>Wind speed</b> — stronger wind disperses odor and lowers risk.</li>' +
    '<li><b>Temperature, humidity, solar radiation, pressure, precipitation</b> — secondary modifiers.</li>' +
    '</ul>' +
    '<p style="margin-bottom:0;font-size:0.85rem;color:#64748b;">Two corrections apply to every model: an ' +
    '<b>elevation pressure offset</b> (Pittsburgh sits ~250 m higher than Calvert, so pressures are shifted into the ' +
    'training frame), and <b>de-biasing</b> (day-of-week and holiday <i>reporting</i> patterns are stripped out so the ' +
    'score reflects weather, not when people happen to file reports).</p>' +
    '</div>';

  // Per-model cards
  html += '<div class="method-card"><h2>The prediction models</h2>' +
    '<p style="font-size:0.88rem;color:#475569;">They differ because they were trained on differently-shaped data. ' +
    'Switch between them with the <b>Prediction Mode</b> selector on the left.</p></div>';

  Object.keys(meta.mode_labels).forEach(function (id) {
    var doc = MODE_DOCS[id];
    var label = meta.mode_labels[id];
    var isDefault = (id === meta.default_mode);
    html += '<div class="method-card model-card">';
    html += '<h3>' + label + (isDefault ? ' <span class="default-chip">default</span>' : '') + '</h3>';
    if (!doc) {
      html += '<p>' + (label) + ' — see project documentation for details.</p></div>';
      return;
    }
    html += '<p class="tagline">' + doc.tagline + '</p>';
    if (id === "calvert_fitted" && fitted) {
      html += '<p class="fitted-stats">Fitted from <b>' + (fitted.n_reports || "?") + ' reports</b>' +
        (fitted.cv_auc_candidate ? ' · cross-validated AUC ' + fitted.cv_auc_candidate +
          ' (vs ' + (fitted.cv_auc_deployed || "?") + ' deployed)' : '') + '.</p>';
    }
    html += '<p><span class="m-label">Trained on:</span> ' + doc.data + '</p>';
    html += '<p><span class="m-label">How it works:</span> ' + doc.how + '</p>';
    html += '<ul class="m-notes">';
    doc.notes.forEach(function (n) { html += '<li>' + n + '</li>'; });
    html += '</ul>';
    html += '<p class="m-best">' + doc.best + '</p>';
    html += '</div>';
  });

  // Custom + limitations
  html +=
    '<div class="method-card model-card">' +
    '<h3>Custom (manual)</h3>' +
    '<p class="tagline">Tune every coefficient yourself.</p>' +
    '<p>Exposes all model coefficients plus spatial adjustments (wind penalty/boost, distance decay) as sliders, ' +
    'so you can explore how each weather variable changes the forecast.</p>' +
    '</div>';

  html +=
    '<div class="method-card limitations">' +
    '<h2>Important limitations</h2>' +
    '<ul>' +
    '<li>Most models are <b>borrowed from Pittsburgh</b>, whose odor sources (coke/steel) differ chemically from ' +
    'Calvert\'s (chemical plants). The physics of atmospheric trapping transfers well; the exact source behavior may not.</li>' +
    '<li>The model predicts <b>trapping conditions</b>, not emissions. A high-risk day with no emissions means no odor; ' +
    'a low-risk day can still smell if there\'s a large release.</li>' +
    '<li>An <b>open question</b>: some residents report stronger odors after rain. The Pittsburgh data shows the ' +
    'opposite, so we keep rain as odor-suppressing for now and are collecting local reports to settle it.</li>' +
    '</ul>' +
    '<p style="margin-bottom:0;font-size:0.85rem;color:#64748b;">Data: Open-Meteo (NWP forecasts + ERA5 reanalysis). ' +
    'Forecasts regenerate daily.</p>' +
    '</div>';

  html += '</div>';
  panel.innerHTML = html;
}

// ── Map tab geolocation ───────────────────────────────────────────────────────

function wireLocateMapButton() {
  document.getElementById("btn-locate-map")?.addEventListener("click", function () {
    if (!navigator.geolocation) { alert("Geolocation not supported."); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      var lat = pos.coords.latitude, lon = pos.coords.longitude;
      if (APP._map) APP._map.setView([lat, lon], 12);
      if (APP._userMarker) APP._map.removeLayer(APP._userMarker);
      APP._userMarker = L.marker([lat, lon]).addTo(APP._map).bindPopup("Your location").openPopup();
      var near = nearestLocation(lat, lon);
      if (near) {
        var locId = near.id || near.zip;
        var cell = (APP.forecast.features[APP.forecast.dates[0]] || {})[locId];
        if (cell) {
          var ori = APP.oriFor(cell);
          var tier = OdorModel.getRiskTier(ori);
          L.popup().setLatLng([lat, lon])
            .setContent("<b>Nearest area:</b> " + near.name + "<br><b>ORI: " + ori + "%</b> — " + tier.label)
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
  wireControls();

  mapPanelScaffold();
  wireLocateMapButton();

  document.querySelectorAll(".tab").forEach(function (t) {
    t.addEventListener("click", function () { setActiveTab(t.dataset.tab); });
  });

  APP._onTab = async function (name) {
    if (name === "map") {
      await ensureMap();
      setTimeout(function () { APP._mapState.map.invalidateSize(); renderMap(); }, 50);
    }
    if (name === "forecast") {
      await buildLocSelectMap("forecast");
      setTimeout(function () { if (APP._locMaps.forecast) APP._locMaps.forecast.map.invalidateSize(); }, 50);
    }
    if (name === "monthly") {
      await buildLocSelectMap("monthly");
      setTimeout(function () { if (APP._locMaps.monthly) APP._locMaps.monthly.map.invalidateSize(); }, 50);
    }
    if (name === "report") { renderReportTab(); }
    if (name === "methods") { renderMethodsTab(); }
  };

  APP.onChange(renderForecastGrid);
  APP.onChange(function () {
    if (APP._mapState.map) renderMap();
    if (document.getElementById("tab-monthly").classList.contains("active")) renderMonthly();
  });

  // Pre-initialize the map tab (default active tab)
  await ensureMap();
  renderMap();
}

main().catch(function (e) {
  document.body.insertAdjacentHTML("afterbegin",
    '<p style="color:red;padding:1rem;font-family:monospace;">Failed to load: ' + e.message +
    " — run <code>python generate_site.py</code> first, then serve with <code>python -m http.server 8765 --directory docs</code></p>"
  );
});
