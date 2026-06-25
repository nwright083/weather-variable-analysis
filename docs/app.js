// Loads data + meta, wires the control panel, and renders all four tabs. ORI is
// computed live via OdorModel using whatever coefficients/options the controls select.
const APP = {
  meta: null, forecast: null, historical: null, hourly: null,
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

function localTimestampStr() {
  var d = new Date();
  var pad = function(n) { return n < 10 ? '0' + n : String(n); };
  var off = -d.getTimezoneOffset();
  var sign = off >= 0 ? '+' : '-';
  var absOff = Math.abs(off);
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) +
    sign + pad(Math.floor(absOff / 60)) + ':' + pad(absOff % 60);
}

function buildFormUrl(lat, lon) {
  var cfg = window.GOOGLE_FORM;
  var u = new URL(cfg.viewUrl);
  if (lat != null && lon != null) {
    u.searchParams.set(cfg.latEntry, lat.toFixed(6));
    u.searchParams.set(cfg.lonEntry, lon.toFixed(6));
  }
  if (cfg.tsEntry) {
    // Local time with UTC offset embedded — e.g. 2026-06-25T09:30:00-05:00
    u.searchParams.set(cfg.tsEntry, localTimestampStr());
  }
  if (cfg.tzEntry) {
    // Optional: pre-fill the Timezone field with the IANA name (e.g. "America/Chicago")
    u.searchParams.set(cfg.tzEntry, Intl.DateTimeFormat().resolvedOptions().timeZone);
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

  // Validation section
  var _mm = meta.model_metrics;
  if (_mm && _mm.models) {
    var _VP = {L:44, R:14, T:18, B:44, W:330, H:210};
    var _vpw = _VP.W - _VP.L - _VP.R;
    var _vph = _VP.H - _VP.T - _VP.B;
    var _VC = {exact_pittsburgh:'#3b82f6', pittsburgh_proximity:'#16a34a', estimated_calvert:'#f59e0b'};
    var _VN = {exact_pittsburgh:'Exact Pittsburgh', pittsburgh_proximity:'Proximity-Enhanced', estimated_calvert:'Est. Calvert City'};

    function _vx(v) { return _VP.L + v * _vpw; }
    function _vy(v) { return _VP.T + (1 - v) * _vph; }

    function _vPath(xs, ys, color) {
      var d = xs.map(function(x, i){ return (i ? 'L' : 'M') + ' ' + _vx(x).toFixed(1) + ' ' + _vy(ys[i]).toFixed(1); }).join(' ');
      return '<path d="' + d + '" fill="none" stroke="' + color + '" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>';
    }

    function _vGrid(xLbl, yLbl) {
      var g = '<rect x="' + _VP.L + '" y="' + _VP.T + '" width="' + _vpw + '" height="' + _vph + '" fill="#fafbfc" stroke="#cbd5e1" stroke-width="0.8"/>';
      [0.2, 0.4, 0.6, 0.8].forEach(function(v) {
        var lv = v.toFixed(1);
        g += '<line x1="' + _vx(0) + '" y1="' + _vy(v).toFixed(1) + '" x2="' + _vx(1) + '" y2="' + _vy(v).toFixed(1) + '" stroke="#e2e8f0" stroke-width="0.7"/>';
        g += '<line x1="' + _vx(v).toFixed(1) + '" y1="' + _vy(0) + '" x2="' + _vx(v).toFixed(1) + '" y2="' + _vy(1) + '" stroke="#e2e8f0" stroke-width="0.7"/>';
        g += '<text x="' + (_vx(v) - 1).toFixed(1) + '" y="' + (_VP.T + _vph + 11) + '" font-size="7.5" text-anchor="middle" fill="#94a3b8">' + lv + '</text>';
        g += '<text x="' + (_VP.L - 4) + '" y="' + (_vy(v) + 3).toFixed(1) + '" font-size="7.5" text-anchor="end" fill="#94a3b8">' + lv + '</text>';
      });
      g += '<text x="' + _vx(0).toFixed(1) + '" y="' + (_VP.T + _vph + 11) + '" font-size="7.5" text-anchor="middle" fill="#94a3b8">0</text>';
      g += '<text x="' + _vx(1).toFixed(1) + '" y="' + (_VP.T + _vph + 11) + '" font-size="7.5" text-anchor="middle" fill="#94a3b8">1</text>';
      g += '<text x="' + (_VP.L - 4) + '" y="' + (_vy(0) + 3).toFixed(1) + '" font-size="7.5" text-anchor="end" fill="#94a3b8">0</text>';
      g += '<text x="' + (_VP.L - 4) + '" y="' + (_vy(1) + 3).toFixed(1) + '" font-size="7.5" text-anchor="end" fill="#94a3b8">1</text>';
      g += '<text x="' + (_VP.L + _vpw / 2).toFixed(1) + '" y="' + (_VP.T + _vph + 28) + '" font-size="9" text-anchor="middle" fill="#64748b">' + xLbl + '</text>';
      g += '<text transform="rotate(-90 ' + (_VP.L - 30) + ' ' + (_VP.T + _vph / 2).toFixed(1) + ')" x="' + (_VP.L - 30) + '" y="' + (_VP.T + _vph / 2).toFixed(1) + '" font-size="9" text-anchor="middle" fill="#64748b">' + yLbl + '</text>';
      return g;
    }

    // ROC
    var _rocSvg = '<svg viewBox="0 0 ' + _VP.W + ' ' + _VP.H + '" class="val-chart-svg">' + _vGrid('False Positive Rate', 'True Positive Rate');
    _rocSvg += '<line x1="' + _vx(0).toFixed(1) + '" y1="' + _vy(0).toFixed(1) + '" x2="' + _vx(1).toFixed(1) + '" y2="' + _vy(1).toFixed(1) + '" stroke="#94a3b8" stroke-width="0.9" stroke-dasharray="4,3"/>';
    ['exact_pittsburgh', 'pittsburgh_proximity', 'estimated_calvert'].forEach(function(mk) {
      var m = _mm.models[mk]; if (!m || !m.fpr) return;
      _rocSvg += _vPath(m.fpr, m.tpr, _VC[mk]);
    });
    _rocSvg += '<text x="' + (_VP.L + _vpw / 2).toFixed(1) + '" y="' + (_VP.T - 5) + '" font-size="10" text-anchor="middle" font-weight="600" fill="#0f172a">ROC Curve</text>';
    _rocSvg += '</svg>';

    // PR
    var _prSvg = '<svg viewBox="0 0 ' + _VP.W + ' ' + _VP.H + '" class="val-chart-svg">' + _vGrid('Recall', 'Precision');
    ['exact_pittsburgh', 'pittsburgh_proximity', 'estimated_calvert'].forEach(function(mk) {
      var m = _mm.models[mk]; if (!m || !m.recall) return;
      _prSvg += _vPath(m.recall, m.precision, _VC[mk]);
      if (m.thr_opt !== undefined && m.recall.length) {
        var bI = 0, bF = -1;
        m.recall.forEach(function(r, i) { var f = 2 * m.precision[i] * r / (m.precision[i] + r + 1e-10); if (f > bF) { bF = f; bI = i; } });
        _prSvg += '<circle cx="' + _vx(m.recall[bI]).toFixed(1) + '" cy="' + _vy(m.precision[bI]).toFixed(1) + '" r="3.5" fill="' + _VC[mk] + '" stroke="#fff" stroke-width="1.2"/>';
      }
    });
    _prSvg += '<text x="' + (_VP.L + _vpw / 2).toFixed(1) + '" y="' + (_VP.T - 5) + '" font-size="10" text-anchor="middle" font-weight="600" fill="#0f172a">Precision-Recall Curve</text>';
    _prSvg += '</svg>';

    // Legend
    var _legHtml = '<div class="val-legend">';
    ['exact_pittsburgh', 'pittsburgh_proximity', 'estimated_calvert'].forEach(function(mk) {
      var m = _mm.models[mk]; if (!m) return;
      _legHtml += '<span class="val-legend-item"><span class="val-legend-dot" style="background:' + _VC[mk] + '"></span>' + _VN[mk] + ' (AUC ' + m.auc.toFixed(3) + ')</span>';
    });
    _legHtml += '</div>';

    // Metrics table
    var _tblHtml = '<table class="metrics-table"><thead><tr><th>Model</th><th>AUC</th><th>CV-AUC</th><th>Pseudo-R²</th><th>Evaluated on</th></tr></thead><tbody>';
    var _tblDef = {
      exact_pittsburgh:     {label:'Exact Pittsburgh',     basis:'Pittsburgh zip-day panel*'},
      pittsburgh_proximity: {label:'Proximity-Enhanced',   basis:'Pittsburgh zip-day panel'},
      estimated_calvert:    {label:'Est. Calvert City',    basis:'Pittsburgh panel (hand-tuned†)'},
    };
    ['exact_pittsburgh', 'pittsburgh_proximity', 'estimated_calvert'].forEach(function(mk) {
      var m = _mm.models[mk], r = _tblDef[mk]; if (!m || !r) return;
      _tblHtml += '<tr><td>' + r.label + '</td><td>' + m.auc.toFixed(3) + '</td><td>' + (m.cv_auc ? m.cv_auc.toFixed(3) : '—') + '</td><td>' + (m.pseudo_r2 ? m.pseudo_r2.toFixed(3) : '—') + '</td><td style="font-size:0.78rem;color:#475569">' + r.basis + '</td></tr>';
    });
    _tblHtml += '</tbody></table>';

    html +=
      '<div class="method-card">' +
      '<h2>Model Validation &amp; Performance</h2>' +
      '<div class="validation-charts">' +
      '<div class="val-chart">' + _rocSvg + '</div>' +
      '<div class="val-chart">' + _prSvg + '</div>' +
      '</div>' +
      _legHtml +
      _tblHtml +
      '<p style="font-size:0.8rem;color:#64748b;margin-top:0.7rem;">' +
      '* <i>Exact Pittsburgh</i> is a daily city-wide model; evaluated here on the zip-day panel, so its AUC (0.76) reflects cross-zip discrimination only — on its native daily panel it achieves AUC 0.87.' +
      '<br>† <i>Est. Calvert City</i> is hand-tuned for Calvert terrain (not re-fitted from data); no Calvert validation set exists yet, so curves show Pittsburgh panel performance only.' +
      '</p>' +
      '</div>';
  }

  // Data sources note + Copernicus attribution
  html +=
    '<div class="method-card" style="border-left:4px solid #0ea5e9;">' +
    '<h2>Weather Data Sources</h2>' +
    '<p style="margin-bottom:0.4rem;">The majority of weather data (temperature, humidity, wind, solar radiation, precipitation, pressure) comes from <b>Open-Meteo</b> — a free, open-source weather API that combines NWP forecast models with ERA5 historical reanalysis.</p>' +
    '<p style="margin-bottom:0;">Boundary-layer height data for January–June 2024 was not available from Open-Meteo for that window. That gap was filled using <b>ERA5 reanalysis data from the Copernicus Climate Data Store (CDS)</b> — the European Centre for Medium-Range Weather Forecasts (ECMWF) global reanalysis at 0.25° resolution. The ERA5 values were matched to each Pittsburgh zip-code centroid using nearest-neighbor grid interpolation and converted from meters to feet.</p>' +
    '</div>';

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
    '<p style="margin-bottom:0;font-size:0.85rem;color:#64748b;">Forecasts regenerate daily from Open-Meteo NWP data. Training data spans 2018–2026.</p>' +
    '</div>';

  html += '</div>';
  panel.innerHTML = html;
}

// ── Hourly forecast tab ───────────────────────────────────────────────────────

var _hourlyLocId = null;
var _hourlyDate  = null;

function renderHourly() {
  var wrap = document.getElementById("hourly-chart-wrap");
  if (!wrap || !APP.hourly || !_hourlyLocId || !_hourlyDate) return;

  var locId = _hourlyLocId;
  var date  = _hourlyDate;

  // Gather 24 hours of computed ORI values
  var hours = [];
  for (var h = 0; h < 24; h++) {
    var dt   = date + 'T' + (h < 10 ? '0' : '') + h + ':00';
    var cell = (APP.hourly.features[dt] || {})[locId];
    var ori  = cell ? APP.oriFor(cell) : null;
    hours.push({h: h, dt: dt, cell: cell, ori: ori});
  }

  // SVG chart dimensions
  var PL = 40, PR = 12, PT = 14, PB = 26;
  var W  = 600, H  = 180;
  var plotW = W - PL - PR;
  var plotH = H - PT - PB;

  function hx(h)   { return PL + (h / 23) * plotW; }
  function vy(ori) { return PT + plotH - (ori / 100) * plotH; }

  var valid = hours.filter(function(d) { return d.ori !== null; });

  // Area + line paths
  var areaPath = '', linePath = '';
  if (valid.length > 0) {
    var pts = valid.map(function(d) { return hx(d.h) + ',' + vy(d.ori); });
    linePath = 'M' + pts.join('L');
    var f = valid[0], l = valid[valid.length - 1];
    areaPath = linePath + 'L' + hx(l.h) + ',' + (PT + plotH) + 'L' + hx(f.h) + ',' + (PT + plotH) + 'Z';
  }

  // Y-axis grid + labels
  var yGridSvg = [0, 25, 50, 75, 100].map(function(v) {
    var y = vy(v);
    return '<line x1="' + PL + '" y1="' + y + '" x2="' + (PL + plotW) + '" y2="' + y +
      '" stroke="#e2e8f0" stroke-width="1"/>' +
      '<text x="' + (PL - 4) + '" y="' + (y + 4) + '" text-anchor="end" font-size="9" fill="#94a3b8">' + v + '%</text>';
  }).join('');

  // Tier threshold dashed lines
  var threshSvg = [
    {pct: 15, color: '#86efac'}, {pct: 30, color: '#fde047'}, {pct: 50, color: '#fdba74'}
  ].map(function(t) {
    var y = vy(t.pct);
    return '<line x1="' + PL + '" y1="' + y + '" x2="' + (PL + plotW) + '" y2="' + y +
      '" stroke="' + t.color + '" stroke-width="1.2" stroke-dasharray="4,3"/>';
  }).join('');

  // X-axis labels at 0, 3, 6 … 21
  var xLabelsSvg = [0, 3, 6, 9, 12, 15, 18, 21].map(function(h) {
    var lbl = h === 0 ? '12a' : h < 12 ? h + 'a' : h === 12 ? '12p' : (h - 12) + 'p';
    return '<text x="' + hx(h) + '" y="' + (H - PB + 12) + '" text-anchor="middle" font-size="9" fill="#64748b">' + lbl + '</text>';
  }).join('');

  // X-axis ticks for all 24 hours
  var xTicksSvg = hours.map(function(d) {
    return '<line x1="' + hx(d.h) + '" y1="' + (PT + plotH) + '" x2="' + hx(d.h) + '" y2="' + (PT + plotH + 3) + '" stroke="#cbd5e1" stroke-width="1"/>';
  }).join('');

  // Data circles with title tooltips
  var circlesSvg = valid.map(function(d) {
    var tier = OdorModel.getRiskTier(d.ori);
    var lbl  = d.h === 0 ? '12am' : d.h < 12 ? d.h + 'am' : d.h === 12 ? '12pm' : (d.h - 12) + 'pm';
    var tip  = lbl + ': ' + d.ori.toFixed(1) + '%';
    if (d.cell) {
      tip += '\nTemp: ' + d.cell.temp.toFixed(1) + '°F';
      tip += '\nWind: ' + d.cell.wind_speed.toFixed(1) + ' mph @ ' + Math.round(d.cell.wind_dir) + '°';
      tip += '\nBLH: ' + Math.round(d.cell.blh) + ' ft';
      tip += '\nSolar: ' + Math.round(d.cell.solar) + ' W/m²';
    }
    return '<circle cx="' + hx(d.h) + '" cy="' + vy(d.ori) + '" r="3" ' +
      'fill="rgb(' + tier.rgb.join(',') + ')" stroke="#fff" stroke-width="1">' +
      '<title>' + tip + '</title></circle>';
  }).join('');

  var svg =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" class="hourly-chart" aria-label="Hourly ORI chart">' +
    '<rect x="' + PL + '" y="' + PT + '" width="' + plotW + '" height="' + plotH + '" fill="#f8fafc"/>' +
    yGridSvg + threshSvg + xTicksSvg + xLabelsSvg +
    (areaPath ? '<path d="' + areaPath + '" fill="rgba(37,99,235,0.1)"/>' : '') +
    (linePath ? '<path d="' + linePath + '" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' : '') +
    circlesSvg +
    '<line x1="' + PL + '" y1="' + PT + '" x2="' + PL + '" y2="' + (PT + plotH) + '" stroke="#94a3b8" stroke-width="1"/>' +
    '<line x1="' + PL + '" y1="' + (PT + plotH) + '" x2="' + (PL + plotW) + '" y2="' + (PT + plotH) + '" stroke="#94a3b8" stroke-width="1"/>' +
    '</svg>';

  // 24-cell colored hour strip
  var stripCells = hours.map(function(d) {
    var tier     = d.ori !== null ? OdorModel.getRiskTier(d.ori) : {rgb: [148, 163, 184]};
    var textCol  = (d.ori !== null && d.ori >= 15) ? '#fff' : '#334155';
    var hLbl     = d.h === 0 ? '12a' : d.h < 12 ? d.h + 'a' : d.h === 12 ? '12p' : (d.h - 12) + 'p';
    var oriStr   = d.ori !== null ? d.ori.toFixed(0) + '%' : '—';
    var tip = '';
    if (d.cell) {
      var full = d.h === 0 ? '12am' : d.h < 12 ? d.h + 'am' : d.h === 12 ? '12pm' : (d.h - 12) + 'pm';
      tip = full + ': ' + (d.ori !== null ? d.ori.toFixed(1) + '%' : '—') +
        ' | ' + d.cell.temp.toFixed(1) + '°F, ' + d.cell.wind_speed.toFixed(1) + ' mph @ ' +
        Math.round(d.cell.wind_dir) + '°, BLH ' + Math.round(d.cell.blh) + 'ft';
    }
    return '<div class="hour-cell" style="background:rgb(' + tier.rgb.join(',') + ');color:' + textCol + ';" title="' + tip + '">' +
      '<div class="hour-cell-label">' + hLbl + '</div>' +
      '<div class="hour-cell-ori">' + oriStr + '</div>' +
      '</div>';
  }).join('');

  var legend =
    '<div class="hourly-legend">' +
    '<span class="badge-pill badge-clear">Clear &lt;15%</span>' +
    '<span class="badge-pill badge-moderate">Moderate 15–30%</span>' +
    '<span class="badge-pill badge-elevated">Elevated 30–50%</span>' +
    '<span class="badge-pill badge-high">High ≥50%</span>' +
    '</div>';

  wrap.innerHTML =
    '<div class="hourly-chart-box">' + svg + '</div>' +
    '<div class="hour-strip">' + stripCells + '</div>' +
    legend;
}

async function buildHourlyTab() {
  if (!APP.hourly) {
    APP.hourly = await loadJSON("data/hourly.json");
  }
  if (APP._locMaps.hourly) {
    APP._locMaps.hourly.map.invalidateSize();
    return;
  }

  var locs = APP.hourly.locations;
  _hourlyLocId = locs.length ? (locs[0].id || locs[0].zip) : null;
  _hourlyDate  = APP.hourly.dates[0];

  var panel = document.getElementById("tab-hourly");

  var datesHtml = APP.hourly.dates.map(function(d, i) {
    var dt  = new Date(d + 'T00:00:00');
    var lbl = dt.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
    return '<option value="' + d + '"' + (i === 0 ? ' selected' : '') + '>' + lbl + '</option>';
  }).join('');

  panel.innerHTML =
    '<div class="loc-header">' +
    '  <button id="btn-locate-hourly" class="btn-locate-small">📍 My Location</button>' +
    '  <span id="hourly-loc-label" class="loc-label">Click a tract on the map</span>' +
    '  <label style="font-size:0.82rem;flex-shrink:0;white-space:nowrap;">Day ' +
    '    <select id="hourly-date-sel">' + datesHtml + '</select>' +
    '  </label>' +
    '</div>' +
    '<div id="hourly-loc-map" class="loc-select-map"></div>' +
    '<div id="hourly-chart-wrap"></div>';

  await ensureGeoJson();

  var IND = [37.0486, -88.3480];
  var m   = L.map("hourly-loc-map", {zoomControl: false}).setView([37.05, -88.35], 9);
  L.tileLayer("https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    {attribution: "© OpenStreetMap contributors, © CARTO", maxZoom: 19}).addTo(m);
  L.circleMarker(IND, {radius: 6, color: "#475569", fillColor: "#64748b", fillOpacity: 0.85})
    .bindTooltip("Industrial Complex").addTo(m);

  var geoLayer = null;
  function renderHourlyLocMap() {
    if (geoLayer) { m.removeLayer(geoLayer); geoLayer = null; }
    // Color tracts by daily ORI on the selected day (reuse APP.forecast for consistency)
    var dailyFeats = APP.forecast.features[_hourlyDate] || {};
    geoLayer = L.geoJSON(APP._mapState.geojson, {
      style: function(f) {
        var fid  = f.properties.GEOID || f.properties.zip || "";
        var cell = dailyFeats[fid];
        var isSel = (fid === _hourlyLocId);
        if (!cell) return {color: isSel ? "#1e3a8a" : "#94a3b8", weight: isSel ? 3 : 1, fillColor: "#cbd5e1", fillOpacity: isSel ? 0.35 : 0.15};
        var tier = OdorModel.getRiskTier(APP.oriFor(cell));
        return {
          color: isSel ? "#1e3a8a" : "#475569",
          weight: isSel ? 3 : 1.2,
          fillColor: "rgb(" + tier.rgb.join(",") + ")",
          fillOpacity: isSel ? 0.65 : 0.4,
        };
      },
      onEachFeature: function(f, layer) {
        var fid   = f.properties.GEOID || f.properties.zip || "";
        var dname = f.properties.display_name || f.properties.NAME || fid;
        layer.on("click", function() {
          _hourlyLocId = fid;
          updateLocLabel("hourly", dname);
          renderHourlyLocMap();
          renderHourly();
        });
        var cell = dailyFeats[fid];
        var ori  = cell ? APP.oriFor(cell) : null;
        layer.bindTooltip(dname + (ori ? "<br>Daily ORI: " + ori.toFixed(1) + "%" : ""), {sticky: true});
      },
    }).addTo(m);
  }

  updateLocLabel("hourly", locDisplayName(_hourlyLocId) || (locs[0] && locs[0].name) || "");
  renderHourlyLocMap();

  APP._locMaps.hourly = {
    map: m,
    getLocId: function() { return _hourlyLocId; },
    setLocId: function(id, name) {
      _hourlyLocId = id;
      updateLocLabel("hourly", name);
      renderHourlyLocMap();
      renderHourly();
    },
  };

  // Re-render chart when mode/coefficients change
  APP.onChange(function() {
    if (document.getElementById("tab-hourly").classList.contains("active")) {
      renderHourly();
    }
  });
  // Re-color the mini-map too when mode changes
  APP.onChange(renderHourlyLocMap);

  // Day selector
  document.getElementById("hourly-date-sel").addEventListener("change", function() {
    _hourlyDate = this.value;
    renderHourlyLocMap();
    renderHourly();
  });

  // My Location button
  document.getElementById("btn-locate-hourly").addEventListener("click", function() {
    if (!navigator.geolocation) { alert("Geolocation not supported."); return; }
    navigator.geolocation.getCurrentPosition(function(pos) {
      var near = nearestLocation(pos.coords.latitude, pos.coords.longitude);
      if (!near) return;
      var nid = near.id || near.zip;
      APP._locMaps.hourly.setLocId(nid, locDisplayName(nid) || near.name);
    }, function() { alert("Could not get your location."); });
  });

  renderHourly();
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
    if (name === "hourly") {
      await buildHourlyTab();
      setTimeout(function() { if (APP._locMaps.hourly) APP._locMaps.hourly.map.invalidateSize(); }, 50);
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
