// Loads data + meta, wires the control panel, and renders all four tabs. ORI is
// computed live via OdorModel using whatever coefficients/options the controls select.

// Map a model mode to its metrics coefficient family. Exact/Transfer twins share a
// family (the pressure offset is a uniform shift that does not change AUC/thresholds).
function metricFamily(mode) {
  if (String(mode).indexOf("pooled") !== -1) return "pooled_proximity";
  if (String(mode).indexOf("proximity") !== -1) return "pittsburgh_proximity";
  if (String(mode).indexOf("calvert_fitted") !== -1) return "calvert_fitted";
  return "exact_pittsburgh";
}

// Risk-tier legend pills on the normalized 0-100 index (alert line = 50), fixed for every model.
function tierLegendHtml(firstLabel) {
  return '<span class="badge-pill badge-clear">' + firstLabel + " &lt; 50</span>" +
    '<span class="badge-pill badge-moderate">Moderate 50–70</span>' +
    '<span class="badge-pill badge-elevated">Elevated 70–85</span>' +
    '<span class="badge-pill badge-high">High ≥ 85</span>';
}

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
    var mo = this.meta.mode_offset;
    return {
      // Exact models score with the offset OFF (0); Transfer models with it ON.
      pressureOffset: (mo && mo[this.mode()] != null) ? mo[this.mode()] : this.meta.pressure_offset,
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
  // Public-facing 0-100 index (alert line = 50); the raw probability from oriFor() stays the
  // source of truth for alert decisions and is shown in tooltips so nothing is hidden.
  indexFor(cell) { return OdorModel.computeIndex(this.oriFor(cell), this.alertThreshold()); },
  // Display bundle for one forecast cell: index (headline), raw probability, tier, tooltip text.
  riskView(cell) {
    var prob = this.oriFor(cell);
    var idx = OdorModel.computeIndex(prob, this.alertThreshold());
    return {
      idx: idx, prob: prob, tier: OdorModel.getRiskTier(idx),
      tip: prob.toFixed(1) + "% modeled chance of a reported odor event. The Odor Index (0–100) " +
           "rescales this so the alert line sits at 50 — see the Methodology tab.",
    };
  },
  alertThreshold() {
    var mode = this.mode();
    var mm = this.meta && this.meta.model_metrics && this.meta.model_metrics.models;
    // Metrics are keyed by coefficient family (weather-only vs proximity); the pressure
    // offset does not change discrimination, so Exact/Transfer twins share a family.
    var md = mm && (mm[mode] || mm[metricFamily(mode)]);
    if (!md) return 30;
    // Prefer the daily-level threshold when present (avoids the zip-day granularity artifact)
    var raw = (md.thr_opt_daily != null) ? md.thr_opt_daily : md.thr_opt;
    if (raw != null && raw > 0.05 && raw < 1.0) return raw * 100;
    return 30; // fallback to Elevated tier start
  },
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
  sel.value = APP.meta.default_mode || "pittsburgh_transfer_proximity";
}

function buildCustomCoeffSliders() {
  var box = document.getElementById("custom-coeffs");
  var ranges = APP.meta.custom_slider_ranges;
  var proxDefs = APP.meta.coeffs.pooled_transfer_proximity || {};
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
    var alertDiv = tabKey === "forecast" ? '<div id="forecast-alert" class="forecast-alert"></div>' : "";
    panel.innerHTML =
      '<div class="loc-header">' +
      '  <button id="btn-locate-' + tabKey + '" class="btn-locate-small">📍 My Location</button>' +
      '  <span id="' + tabKey + '-loc-label" class="loc-label">Click a tract on the map</span>' +
      '</div>' +
      '<div id="' + tabKey + '-loc-map" class="loc-select-map"></div>' +
      calHead +
      alertDiv +
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
        var tier = OdorModel.getRiskTier(APP.indexFor(cell));
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
        var v = cell ? APP.riskView(cell) : null;
        layer.bindTooltip(dname + (v ? "<br>Odor Index " + Math.round(v.idx) + " · " + v.prob.toFixed(1) + "% chance" : ""), {sticky: true});
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

function renderForecastAlert(loc) {
  var banner = document.getElementById("forecast-alert");
  if (!banner || !APP.forecast) return;
  var thr = APP.alertThreshold();  // modeled probability %, the scientific decision boundary
  var alertDays = [], highDays = [];
  APP.forecast.dates.forEach(function (d) {
    var cell = APP.forecast.features[d] && APP.forecast.features[d][loc];
    if (!cell) return;
    var prob = APP.oriFor(cell);
    if (APP.indexFor(cell) >= 85) highDays.push(d);  // High tier on the index
    else if (prob >= thr) alertDays.push(d);         // above the alert line (index ≥ 50)
  });
  var thrNote = 'Alert line = Odor Index 50 (the model\'s data-derived ' + thr.toFixed(1) +
                '% probability threshold).';
  banner.className = "forecast-alert";
  if (highDays.length) {
    banner.classList.add("alert-high");
    banner.innerHTML =
      '<strong>🚨 High Odor Risk Forecast</strong>' +
      highDays.length + ' day' + (highDays.length > 1 ? 's' : '') +
      ' showing <b>High risk</b> (Odor Index ≥ 85) and ' +
      alertDays.length + ' additional day' +
      (alertDays.length !== 1 ? 's' : '') + ' above the alert line in the 16-day window.' +
      '<div class="alert-days">High risk days: ' +
      highDays.map(function(d){ var dt=new Date(d+'T00:00:00'); return dt.toLocaleDateString(undefined,{month:'short',day:'numeric'}); }).join(', ') +
      '</div>' +
      '<div class="alert-days">' + thrNote + '</div>';
  } else if (alertDays.length) {
    banner.classList.add("alert-elevated");
    banner.innerHTML =
      '<strong>⚠️ Elevated Odor Risk Forecast</strong>' +
      alertDays.length + ' day' + (alertDays.length > 1 ? 's' : '') +
      ' in the next 16 days are above the alert line (Odor Index ≥ 50). ' +
      'Residents near industrial areas may notice elevated odors on these days.' +
      '<div class="alert-days">' +
      alertDays.map(function(d){ var dt=new Date(d+'T00:00:00'); return dt.toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'}); }).join(' · ') +
      '</div>' +
      '<div class="alert-days">' + thrNote + '</div>';
  }
}

function renderForecastGrid() {
  var lm = APP._locMaps && APP._locMaps.forecast;
  var loc = lm ? lm.getLocId() : (APP.forecast.locations[0] ? (APP.forecast.locations[0].id || APP.forecast.locations[0].zip) : null);
  var grid = document.getElementById("forecast-grid");
  if (!loc || !grid) return;
  grid.innerHTML = "";
  APP.forecast.dates.forEach(function (d) {
    var cell = APP.forecast.features[d][loc];
    if (!cell) return;
    var v = APP.riskView(cell);
    var rgb = "rgb(" + v.tier.rgb.join(",") + ")";
    var dt = new Date(d + "T00:00:00");
    var card = document.createElement("div");
    card.className = "clean-card";
    card.innerHTML =
      '<div style="font-weight:600;font-size:0.78rem;">' + dt.toLocaleDateString(undefined, {weekday: "short"}) + '</div>' +
      '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month: "short", day: "numeric"}) + '</div>' +
      '<div title="' + v.tip + '" style="font-size:1.5rem;font-weight:700;color:' + rgb + ';margin:0.25rem 0 0;cursor:help;">' + Math.round(v.idx) + '</div>' +
      '<div style="font-size:0.55rem;opacity:0.6;margin-bottom:0.2rem;">Odor Index · hover for %</div>' +
      '<span class="badge-pill ' + v.tier.cls + '">' + v.tier.label.split(" ")[0] + '</span>';
    grid.appendChild(card);
  });
  renderForecastAlert(loc);
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
    '</div><div id="map"></div>';
  var sel = panel.querySelector("#map-date");
  APP.forecast.dates.forEach(function (d, i) {
    var o = document.createElement("option"); o.value = d; o.textContent = d; if (i === 1) o.selected = true;
    sel.appendChild(o);
  });
  sel.addEventListener("change", renderMap);
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
  if (ms.geo) { ms.map.removeLayer(ms.geo); ms.geo = null; }
  var feats = APP.forecast.features[date] || {};
  ms.geo = L.geoJSON(ms.geojson, {
    style: function (f) {
      var locId = f.properties.GEOID || f.properties.zip || f.properties.ZCTA5CE10 || "";
      var cell = feats[locId];
      if (!cell) return {color: "#94a3b8", weight: 1, fillColor: "#cbd5e1", fillOpacity: 0.2};
      var tier = OdorModel.getRiskTier(APP.indexFor(cell));
      return {color: "#475569", weight: 1.5, fillColor: "rgb(" + tier.rgb.join(",") + ")", fillOpacity: 0.45};
    },
    onEachFeature: function (f, layer) {
      var locId = f.properties.GEOID || f.properties.zip || f.properties.ZCTA5CE10 || "";
      var cell = feats[locId];
      var v = cell ? APP.riskView(cell) : null;
      var displayName = f.properties.display_name || f.properties.NAME || locId;
      layer.bindTooltip(
        "Area: " + displayName + "<br>Odor Index: " +
        (v === null ? "N/A" : Math.round(v.idx) + " (" + v.prob.toFixed(1) + "% chance)") +
        "<br>" + (v === null ? "N/A" : v.tier.label)
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
      var v = APP.riskView(cell);
      var dt = new Date(d + "T00:00:00");
      div.innerHTML =
        '<div style="font-size:0.68rem;opacity:0.6;">' + dt.toLocaleDateString(undefined, {month: "short", day: "numeric"}) + '</div>' +
        '<div title="' + v.tip + '" style="font-size:1.2rem;font-weight:700;color:rgb(' + v.tier.rgb.join(",") + ');cursor:help;">' + Math.round(v.idx) + '</div>' +
        '<span class="badge-pill ' + v.tier.cls + '" title="Wind ' + cell.wind_speed.toFixed(1) + ' mph @ ' +
        Math.round(cell.wind_dir) + '°, PBLH ' + Math.round(cell.blh) + ' ft, Rain ' + cell.precip.toFixed(2) + ' in · ' + v.prob.toFixed(1) + '% chance">' +
        v.tier.label.split(" ")[0] + '</span>';
    }
    cal.appendChild(div);
  });
}

// ── Report tab ────────────────────────────────────────────────────────────────

function renderReportTab() {
  var panel = document.getElementById("tab-report");
  if (panel.dataset.built) return;
  panel.dataset.built = "1";
  panel.innerHTML =
    '<div class="clean-card" style="text-align:left;max-width:560px;">' +
    '<h3 style="margin:0 0 0.5rem;">Report an Odor</h3>' +
    '<p style="font-size:0.88rem;color:#475569;margin:0 0 0.9rem;">Notice an odor? Report it through the Smell My City app — community reports build the local odor record that powers this forecast.</p>' +
    '<div style="display:flex;flex-direction:column;gap:0.6rem;">' +
    '  <a href="https://smellmycity.org/" target="_blank" rel="noopener" class="report-btn report-btn-link">📱 Report on Smell My City</a>' +
    '</div>' +
    '</div>';
}

// ── Methodology tab ───────────────────────────────────────────────────────────

// Hand-written explanations keyed by mode id. Kept here (not in meta.json) so the
// prose stays editable without touching the data pipeline. Any mode present in
// meta.mode_labels but missing here falls back to a generic description.
var MODE_DOCS = {
  pooled_transfer_proximity: {
    tagline: "Predicts when the atmosphere will trap and concentrate odor near the industrial sources — pooled from two well-monitored cities and read in Calvert's frame.",
    data: "A single logistic regression fit on daily records from Pittsburgh and Louisville — two cities with dense public odor-report and weather data — pooled with each city weighted equally.",
    how: "Each day's forecast is scored on two things: <b>trapping conditions</b> (diurnal temperature swing, boundary-layer height, wind speed, humidity, and related variables that decide whether odor stays near the ground), and <b>where you are</b> relative to the emitters — <b>nearest-source proximity</b> (risk decays with distance from the closest emitter: the Calvert City industrial complex or the TVA Shawnee plant) and <b>wind alignment</b> to that source. Calvert's lower elevation is corrected into the training frame.",
    notes: [
      "It models the <b>meteorology</b> (whether the air will trap odor), not the emissions (whether odor is being released) — so it is best read as a <b>relative</b> day-to-day indicator, shown as the 0–100 index.",
      "Day-of-week and holiday reporting habits are removed so weather and location drive the score, not human reporting cycles.",
      "Validated against Calvert's own VOC air monitors it tracks the region's signature pollutant, vinyl chloride, best — evidence the trapping signal is physically real here.",
    ],
    best: "The deployed model: a physically-grounded, honest relative indicator of odor-trapping risk for the Calvert City area.",
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
  var thrRows = '';
  if (meta.model_metrics && meta.model_metrics.models) {
    var mm = meta.model_metrics.models;
    Object.keys(meta.mode_labels || {}).forEach(function(id) {
      var m = mm[id] || mm[metricFamily(id)];  // metrics are keyed by coefficient family
      if (!m) return;
      // Prefer daily-level threshold (avoids zip-day granularity artifact)
      var rawThr = (m.thr_opt_daily != null) ? m.thr_opt_daily : m.thr_opt;
      var rawF1  = (m.f1_opt_daily  != null) ? m.f1_opt_daily  : m.f1_opt;
      var thr = rawThr * 100;
      var label = (meta.mode_labels[id] || id);
      var thrDisplay = (!rawThr || thr >= 100 || thr < 1) ? 'N/A (insufficient local data)' : thr.toFixed(1) + '%';
      var note = m.thr_opt_daily != null ? ' <span style="font-size:0.75rem;color:#64748b;">(daily)</span>' : '';
      thrRows += '<tr><td>' + label + '</td><td style="font-weight:600;">' + thrDisplay + note + '</td><td>' +
        (rawF1 != null ? rawF1.toFixed(3) : '—') + '</td></tr>';
    });
  }
  var thrTable = thrRows
    ? '<table class="metrics-table" style="margin-top:0.6rem;"><thead><tr>' +
      '<th>Model</th><th>Alert threshold (ORI)</th><th>F1 at threshold</th></tr></thead>' +
      '<tbody>' + thrRows + '</tbody></table>' +
      '<p style="font-size:0.78rem;color:#64748b;margin-top:0.3rem;margin-bottom:0;">' +
      'The <b>alert line (Odor Index 50)</b> is where the model\'s data-derived probability threshold lands on the 0–100 scale — that probability is the actual decision boundary; index 50 is just its label. It is the <b>F1-optimal</b> cutoff (the probability that best balances catching real odor days against false alarms), chosen by the data, not by hand. ' +
      'It updates automatically if a locally-fitted Calvert model is installed.</p>'
    : '';
  html +=
    '<div class="method-card">' +
    '<h2>How these forecasts work</h2>' +
    '<p>Every forecast is shown as an <b>Odor Risk Index (0–100)</b>. Under the hood the model produces a ' +
    'calibrated <b>probability</b> of a reported community-wide odor event that day; because such events are ' +
    'relatively rare, those probabilities are honest but small (a bad day is ~40%), which reads as deceptively ' +
    '“low.” So — exactly like the EPA Air Quality Index — we rescale the probability onto a 0–100 index with the ' +
    '<b>alert line fixed at 50</b>, so the number tracks how notable a day is. <b>The underlying probability is not ' +
    'hidden:</b> hover any day (or open a map area) to see the exact modeled % chance. Two distinct factors drive the score:</p>' +
    '<ul>' +
    '<li><b>Atmospheric trapping conditions</b> — temperature inversions, boundary-layer height, wind speed, ' +
    'humidity, and related variables that determine whether odors stay concentrated near the ground.</li>' +
    '<li><b>Wind direction and proximity to odor sources</b> — the <b>Proximity</b> models add two spatial terms: ' +
    'how directly the wind carries air from the nearest emitter toward each census tract, and how far that tract is ' +
    'from that source (risk decays with distance). Calvert is modeled with two sources — the Calvert City industrial ' +
    'complex and the TVA Shawnee Fossil Plant near Paducah — and each tract is driven by whichever is closest. ' +
    'Pittsburgh data showed a strong relationship between upwind proximity to industrial sites and the volume of ' +
    'community odor reports.</li>' +
    '</ul>' +
    '<p style="margin-bottom:0;">It predicts when the <b>atmosphere will trap and concentrate</b> odor near the ground — ' +
    'not whether the source is actively emitting, so it is best read as a <b>relative</b> day-to-day indicator. ' +
    'On the 0–100 index the color tiers are fixed: below <b>50</b> is Clear (under the alert line), then Moderate, ' +
    'Elevated, and High:</p>' +
    '<div class="tier-row">' +
    tierLegendHtml("Clear / Low") +
    '</div>' +
    (thrTable
      ? '<div style="margin-top:0.8rem;"><b style="font-size:0.9rem;">Data-derived alert thresholds (per model)</b>' + thrTable + '</div>'
      : '') +
    '</div>';

  // Shared physics
  html +=
    '<div class="method-card">' +
    '<h2>What drives the risk</h2>' +
    '<p>Two things move the score most, ranked by their real effect in the model:</p>' +
    '<ul>' +
    '<li><b>Where you are relative to the sources</b> — <b>nearest-source proximity</b> (risk decays with distance from the closest emitter) and <b>wind alignment</b> (higher when the wind carries source air toward you). Location is the single strongest lever.</li>' +
    '<li><b>The day\'s trapping conditions</b> — a <b>temperature window</b> (a quadratic term: risk peaks in a mid-range and falls off at the extremes), <b>solar radiation</b> and <b>humidity</b>, plus <b>diurnal temperature range</b> and <b>boundary-layer height</b> (two sides of the overnight-inversion physics that keeps air near the ground). No single weather variable dominates — they act as a cluster.</li>' +
    '<li><b>Wind speed &amp; rain</b> — stronger wind disperses odor and rain scavenges it, both lowering risk.</li>' +
    '</ul>' +
    '<p style="margin-bottom:0;font-size:0.85rem;color:#64748b;"><b>De-biasing</b> is built in ' +
    '(day-of-week and holiday <i>reporting</i> patterns are stripped out so the score reflects weather, not when ' +
    'people happen to file reports). An <b>elevation pressure offset</b> shifts Calvert\'s pressures into the ' +
    'training frame (Pittsburgh sits ~250 m higher); it is a small, uniform correction. Diurnal temperature range is ' +
    'the true daily high-minus-low, and each tract\'s exposure is driven by its nearest emitter.</p>' +
    '</div>';

  // ── Formula card ────────────────────────────────────────────────────────────
  (function () {
    // Show the two coefficient families (the Exact/Transfer split is the pressure
    // offset, not a coefficient, so it isn't a separate column here).
    var allModes = Object.keys(meta.coeffs || {}).filter(function(id) {
      return id !== 'calvert_fitted';
    });
    var modeLabels = {
      pooled_transfer_proximity:     'Coefficient',
      exact_pittsburgh:              'Weather-only',
      pittsburgh_transfer_proximity: 'Proximity',
    };

    function fmt(val) {
      if (val == null) return '<span class="na">—</span>';
      var abs = Math.abs(val);
      var s;
      if (abs === 0) s = '0';
      else if (abs < 0.0001) s = val.toExponential(2);
      else if (abs < 0.001)  s = val.toFixed(6);
      else if (abs < 0.01)   s = val.toFixed(5);
      else if (abs < 0.1)    s = val.toFixed(4);
      else                   s = val.toFixed(4);
      return '<span class="' + (val >= 0 ? 'coeff-pos' : 'coeff-neg') + '">' +
             (val >= 0 ? '+' : '−') + (val < 0 ? s : s) + '</span>';
    }
    function getCoeff(mode, key) {
      return (meta.coeffs[mode] || {})[key];
    }

    // Coefficient rows: [display name, symbol html, coeff key, is proximity-only]
    var rows = [
      ['Intercept (const)',           '&alpha;',                                    'const',                    false],
      ['Temperature',                  '<span class="fv">T</span>',                 'temperature',              false],
      ['Temperature²',                 '<span class="fv">T</span><sup>2</sup>',     'temperature_squared',      false],
      ['Diurnal temp range',           '<span class="fv">DTR</span>',               'diurnal_temperature_range',false],
      ['Boundary-layer height',        '<span class="fv">BLH</span>',               'boundary_layer_height',    false],
      ['Solar radiation',              '<span class="fv">S</span>',                 'solar_radiation',          false],
      ['Relative humidity',            '<span class="fv">RH</span>',                'relative_humidity',        false],
      ['Wind speed',                   '<span class="fv">W</span>',                 'wind_speed',               false],
      ['Precipitation',                '<span class="fv">P</span>',                 'precipitation',            false],
      ['Atmospheric pressure',         '<span class="fv">p</span> − <span class="fv">p</span><sub>0</sub>', 'atmospheric_pressure', false],
      ['Source exposure (proximity)',   '<span class="fv">e</span><sup>−0.02<span class="fv">d</span></sup>', 'multi_source_exposure', true],
      ['Wind alignment (proximity)',    '<span class="fv">align</span>',             'wind_align_weighted',      true],
    ];

    var tHead = '<tr><th>Variable</th><th>Symbol</th>';
    allModes.forEach(function(m) { tHead += '<th>' + modeLabels[m] + '</th>'; });
    tHead += '</tr>';

    var tBody = '';
    rows.forEach(function(row) {
      var name = row[0], sym = row[1], key = row[2], isProx = row[3];
      var trCls = isProx ? ' class="prox-row"' : '';
      tBody += '<tr' + trCls + '><td>' + name + (isProx ? ' <span style="font-size:0.72rem;color:#3b82f6;">★</span>' : '') + '</td>';
      tBody += '<td class="sym">' + sym + '</td>';
      allModes.forEach(function(m) {
        var v = getCoeff(m, key);
        tBody += '<td>' + (v != null ? fmt(v) : '<span class="na">—</span>') + '</td>';
      });
      tBody += '</tr>';
    });

    html +=
      '<div class="method-card">' +
      '<h2>The prediction formula</h2>' +
      '<p style="margin-bottom:0.7rem;">ORI is a logistic regression computed in two steps. First, weather inputs are combined into a raw log-odds score <span class="fv"><i>z</i></span>. Second, the logistic function maps that score to a probability.</p>' +

      '<div class="formula-block">' +
      '<div class="formula-step-label">Step 1 &mdash; Linear predictor</div>' +
      '<div class="formula-eq">' +
        '<span class="fv">z</span>&nbsp;=&nbsp;&alpha;&nbsp;' +
        '+&nbsp;&beta;<sub>T</sub>&thinsp;<span class="fv">T</span>&nbsp;' +
        '+&nbsp;&beta;<sub>T²</sub>&thinsp;<span class="fv">T</span><sup>2</sup>&nbsp;' +
        '+&nbsp;&beta;<sub>DTR</sub>&thinsp;<span class="fv">DTR</span>&nbsp;' +
        '+&nbsp;&beta;<sub>BLH</sub>&thinsp;<span class="fv">BLH</span>&nbsp;' +
        '+&nbsp;&beta;<sub>S</sub>&thinsp;<span class="fv">S</span>&nbsp;' +
        '+&nbsp;&beta;<sub>RH</sub>&thinsp;<span class="fv">RH</span>&nbsp;' +
        '+&nbsp;&beta;<sub>W</sub>&thinsp;<span class="fv">W</span>&nbsp;' +
        '+&nbsp;&beta;<sub>P</sub>&thinsp;<span class="fv">P</span>&nbsp;' +
        '+&nbsp;&beta;<sub>p</sub>&thinsp;(<span class="fv">p</span>&nbsp;&minus;&nbsp;<span class="fv">p</span><sub>0</sub>)' +
      '</div>' +
      '<div class="formula-prox">&#9733; Proximity-enhanced model adds: ' +
        '&beta;<sub>exp</sub>&thinsp;&middot;&thinsp;<span class="fv">e</span><sup>&minus;0.02<span class="fv">d</span></sup>' +
        '&nbsp;+&nbsp;&beta;<sub>align</sub>&thinsp;&middot;&thinsp;<span class="fv">align</span>' +
        ' &ensp;<span style="font-weight:400;opacity:0.7;">where <span class="fv">d</span> = distance from source (mi), <span class="fv">align</span> = cosine wind-bearing score (0–1)</span>' +
      '</div>' +
      '</div>' +

      '<div class="formula-block">' +
      '<div class="formula-step-label">Step 2 &mdash; Modeled probability</div>' +
      '<div class="formula-eq">' +
        '<span class="fv">P</span>&nbsp;=&nbsp;&sigma;(<span class="fv">z</span>)&nbsp;&times;&nbsp;100%&nbsp;=&nbsp;' +
        '<span class="frac"><span class="frac-n">100%</span><span class="frac-d">1&nbsp;+&nbsp;<span class="fv">e</span><sup>&minus;<span class="fv">z</span></sup></span></span>' +
        '&ensp;<span style="font-size:0.82rem;color:#64748b;">calibrated probability of a reported odor event, [0%, 100%]</span>' +
      '</div>' +
      '</div>' +

      '<div class="formula-block">' +
      '<div class="formula-step-label">Step 3 &mdash; Public Odor Risk Index (0&ndash;100, the displayed number)</div>' +
      '<div class="formula-eq" style="font-size:0.92rem;">' +
        'Index&nbsp;=&nbsp;50&thinsp;&middot;&thinsp;(<span class="fv">P</span>&thinsp;/&thinsp;<span class="fv">T</span>)&ensp;if&nbsp;<span class="fv">P</span>&nbsp;&le;&nbsp;<span class="fv">T</span>,&emsp;else&emsp;' +
        '50&nbsp;+&nbsp;50&thinsp;&middot;&thinsp;(<span class="fv">P</span>&nbsp;&minus;&nbsp;<span class="fv">T</span>)&thinsp;/&thinsp;(3<span class="fv">T</span>)' +
      '</div>' +
      '<div class="formula-prox" style="font-weight:400;">A monotonic rescaling of the Step-2 probability that puts each model&rsquo;s alert threshold ' +
        '<span class="fv">T</span> at index 50 and ~4<span class="fv">T</span> at 100 &mdash; so the public number tracks how notable a day is (like the EPA AQI). ' +
        'It changes nothing scientific: the probability <span class="fv">P</span> is the real quantity (shown in every tooltip) and the alert decision still uses <span class="fv">P</span>&nbsp;&ge;&nbsp;<span class="fv">T</span>.</div>' +
      '</div>' +

      '<p style="font-size:0.84rem;color:#475569;margin:0.8rem 0 0.4rem;"><b>Fitted coefficients (&beta;) by model</b> — positive values increase risk, negative values decrease it. ' +
      '<span style="color:#3b82f6;">★</span> rows appear only in the proximity-enhanced model.</p>' +
      '<div style="overflow-x:auto;">' +
      '<table class="formula-coeff-table"><thead>' + tHead + '</thead><tbody>' + tBody + '</tbody></table>' +
      '</div>' +
      '<p style="font-size:0.76rem;color:#94a3b8;margin-top:0.4rem;margin-bottom:0;">' +
        '<span class="fv">p</span><sub>0</sub> = ' + (meta.pressure_offset || 0).toFixed(2) + ' hPa (elevation offset correcting for the ~' +
        Math.round((meta.pressure_offset || 0) / 0.12) + ' m altitude difference between Pittsburgh and Calvert City training sites).' +
      '</p>' +
      '</div>';
  })();

  // Input variable table
  html +=
    '<div class="method-card">' +
    '<h2>Model input variables</h2>' +
    '<p style="font-size:0.88rem;color:#475569;margin-bottom:0.6rem;">All daily models use the same ten weather-derived features, computed as <b>daily aggregates</b> from the same hourly Open-Meteo feed. ' +
    'Weather measurements come from the Open-Meteo NWP grid at the standard meteorological heights used by the ERA5 / ECMWF forecast system.</p>' +
    '<table class="metrics-table">' +
    '<thead><tr><th>Variable</th><th>Units / scale</th><th>Daily aggregate</th><th>Physical role</th></tr></thead>' +
    '<tbody>' +
    '<tr><td><b>Temperature</b></td><td>°F at 2 m above ground</td><td>Daily mean</td><td>Higher temp → increased volatility / diffusion</td></tr>' +
    '<tr><td><b>Temperature² (quadratic)</b></td><td>°F² (derived)</td><td>Daily mean²</td><td>Captures the non-linear, U-shaped relationship between temp and odor risk</td></tr>' +
    '<tr><td><b>Diurnal temperature range (DTR)</b></td><td>°F (daily max − min, 2 m)</td><td>Day range</td><td>Strongest single predictor — large swing = clear calm nights with strong inversions</td></tr>' +
    '<tr><td><b>Boundary-layer height (BLH)</b></td><td>Feet (converted from m)</td><td>Daily mean</td><td>Mixing depth; low BLH traps odor near the surface</td></tr>' +
    '<tr><td><b>Solar radiation</b></td><td>W/m² (shortwave, surface)</td><td>Daily mean</td><td>Drives daytime mixing; more sun → more convective turbulence → lower trapping</td></tr>' +
    '<tr><td><b>Relative humidity</b></td><td>% at 2 m above ground</td><td>Daily mean</td><td>High humidity correlates with stable, stagnant air masses</td></tr>' +
    '<tr><td><b>Wind speed</b></td><td>mph at 10 m above ground</td><td>Daily mean</td><td>Dispersion; stronger wind reduces concentration</td></tr>' +
    '<tr><td><b>Wind direction → wind alignment</b></td><td>Degrees at 10 m; converted to alignment angle (°) with source bearing</td><td>Circular vector mean</td><td>Proximity model only: how directly the wind blows odor toward each census tract</td></tr>' +
    '<tr><td><b>Precipitation</b></td><td>Inches (rain only)</td><td>Daily sum</td><td>Rain scrubs and suppresses odor in Pittsburgh data (open question for Calvert)</td></tr>' +
    '<tr><td><b>Atmospheric pressure</b></td><td>hPa (surface); elevation-offset applied</td><td>Daily mean</td><td>Low pressure → unstable conditions; offset corrects Pittsburgh (~250 m) vs Calvert (~120 m) elevation difference</td></tr>' +
    '</tbody></table>' +
    '<p style="font-size:0.8rem;color:#64748b;margin-top:0.5rem;margin-bottom:0;">All variables are available from Open-Meteo\'s forecast API with no post-processing except unit conversions and the elevation pressure offset. ' +
    'Training labels used Pittsburgh community smell-event reports (2018–2026) binarized by weighted odor burden.</p>' +
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
    var _VC = {pooled_proximity:'#16a34a'};
    var _VN = {pooled_proximity:'Odor Risk Model (Pittsburgh + Louisville)'};

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
    ['pooled_proximity'].forEach(function(mk) {
      var m = _mm.models[mk]; if (!m || !m.fpr) return;
      _rocSvg += _vPath(m.fpr, m.tpr, _VC[mk]);
    });
    _rocSvg += '<text x="' + (_VP.L + _vpw / 2).toFixed(1) + '" y="' + (_VP.T - 5) + '" font-size="10" text-anchor="middle" font-weight="600" fill="#0f172a">ROC Curve</text>';
    _rocSvg += '</svg>';

    // PR
    var _prSvg = '<svg viewBox="0 0 ' + _VP.W + ' ' + _VP.H + '" class="val-chart-svg">' + _vGrid('Recall', 'Precision');
    ['pooled_proximity'].forEach(function(mk) {
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
    ['pooled_proximity'].forEach(function(mk) {
      var m = _mm.models[mk]; if (!m) return;
      _legHtml += '<span class="val-legend-item"><span class="val-legend-dot" style="background:' + _VC[mk] + '"></span>' + _VN[mk] + ' (AUC ' + m.auc.toFixed(3) + ')</span>';
    });
    _legHtml += '</div>';

    // Metrics table
    var _tblHtml = '<table class="metrics-table"><thead><tr><th>Model</th><th>AUC</th><th>CV-AUC</th><th>Pseudo-R²</th><th>Evaluated on</th></tr></thead><tbody>';
    var _tblDef = {
      pooled_proximity: {label:'Odor Risk Model (Pgh + Lou)', basis:'Pooled zip-day panel, cross-validated'},
    };
    ['pooled_proximity'].forEach(function(mk) {
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
      'AUC ~0.69 within the training cities (cross-validated). Applied to a new city like Calvert the honest skill is lower (~0.6), so the tool is best read as a relative indicator rather than an exact probability. Checked against Calvert\'s own VOC air monitors it tracks the area\'s signature pollutant, vinyl chloride, at AUC ~0.71 — evidence the trapping signal is physically real here.' +
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
    '<li>The <b>⏱️ Hourly tab</b> offers two views. <b>Default — Fitted hourly model (case-crossover):</b> ' +
    'Coefficients were estimated from 8+ years of Pittsburgh reports by comparing odor-report hours to ' +
    'non-report control hours within the same hour-of-day of the same calendar month. This design removes ' +
    'diurnal reporting bias and the solar/hour collinearity by construction. Features used: temperature ' +
    '(linear + quadratic), boundary-layer height, wind speed, relative humidity, atmospheric pressure, ' +
    'and precipitation — all at raw hourly values. Solar radiation and DTR are excluded (absorbed by the ' +
    'strata). Because the model has no intercept, the 24 within-day z-values are re-anchored so their mean ' +
    'matches the calibrated daily ORI. <b>Comparison — Daily model (constant-input):</b> The original daily ' +
    'logistic regression run on daily-aggregate inputs (solar daily-mean, precip daily-sum, RH/pressure/wind ' +
    'daily means, DTR constant). Only BLH and temperature vary sub-daily. Both views are anchored to the ' +
    'same dashed daily-ORI reference line.</li>' +
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

  // Tab-local model toggle
  var modeRadio = document.querySelector('input[name="hourly-mode"]:checked');
  var hourlyMode = modeRadio ? modeRadio.value : 'fitted';
  var hc = APP.meta && APP.meta.hourly_coeffs;
  var useFitted = (hourlyMode === 'fitted') && !!hc;

  // Calibrated daily ORI anchor (from daily model — shown as reference line)
  var dailyCell = (APP.forecast.features[date] || {})[locId];
  var dailyOri  = dailyCell ? APP.oriFor(dailyCell) : null;

  // ── Compute per-hour ORI values ────────────────────────────────────────────
  var hours = [];
  var pressureOffset = (APP.meta && APP.meta.pressure_offset) || 0;

  if (useFitted) {
    // Fitted case-crossover model: compute raw z for each hour, then anchor
    // so the 24-hour mean sits exactly on logit(dailyOri/100).
    var zVals = [];
    for (var h = 0; h < 24; h++) {
      var dt   = date + 'T' + (h < 10 ? '0' : '') + h + ':00';
      var cell = (APP.hourly.features[dt] || {})[locId];
      zVals.push(cell ? OdorModel.hourlyZ(cell, hc, pressureOffset) : null);
    }
    var nonNull = zVals.filter(function(z) { return z !== null; });
    var meanZ   = nonNull.length ? nonNull.reduce(function(a, b) { return a + b; }, 0) / nonNull.length : 0;
    var logitD  = dailyOri !== null ? Math.log(Math.max(dailyOri, 0.01) / Math.max(100 - dailyOri, 0.01)) : meanZ;
    var shift   = logitD - meanZ;
    for (var h = 0; h < 24; h++) {
      var dt   = date + 'T' + (h < 10 ? '0' : '') + h + ':00';
      var cell = (APP.hourly.features[dt] || {})[locId];
      var z    = zVals[h];
      var ori  = z !== null ? Math.round((100 / (1 + Math.exp(-(z + shift)))) * 10) / 10 : null;
      hours.push({h: h, dt: dt, cell: cell, ori: ori, idx: ori !== null ? OdorModel.computeIndex(ori, APP.alertThreshold()) : null});
    }
  } else {
    // Daily-constant-input fallback: substitute *_d fields for daily-natured features
    // so the daily-trained coefficients receive daily-aggregate inputs as they were trained on.
    for (var h = 0; h < 24; h++) {
      var dt   = date + 'T' + (h < 10 ? '0' : '') + h + ':00';
      var cell = (APP.hourly.features[dt] || {})[locId];
      var ori  = null;
      if (cell) {
        var fc = {
          temp: cell.temp, temp_sq: cell.temp_sq, blh: cell.blh, dtr: cell.dtr,
          solar: cell.solar_d, rh: cell.rh_d, wind_speed: cell.wind_speed_d,
          wind_dir: cell.wind_dir_d, precip: cell.precip_d, pressure: cell.pressure_d,
          wind_alignment: cell.wind_alignment_d, aligned: cell.aligned_d,
          distance: cell.distance,
        };
        ori = APP.oriFor(fc);
      }
      hours.push({h: h, dt: dt, cell: cell, ori: ori, idx: ori !== null ? OdorModel.computeIndex(ori, APP.alertThreshold()) : null});
    }
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
    var pts = valid.map(function(d) { return hx(d.h) + ',' + vy(d.idx); });
    linePath = 'M' + pts.join('L');
    var f = valid[0], l = valid[valid.length - 1];
    areaPath = linePath + 'L' + hx(l.h) + ',' + (PT + plotH) + 'L' + hx(f.h) + ',' + (PT + plotH) + 'Z';
  }

  // Y-axis grid + labels
  var yGridSvg = [0, 25, 50, 75, 100].map(function(v) {
    var y = vy(v);
    return '<line x1="' + PL + '" y1="' + y + '" x2="' + (PL + plotW) + '" y2="' + y +
      '" stroke="#e2e8f0" stroke-width="1"/>' +
      '<text x="' + (PL - 4) + '" y="' + (y + 4) + '" text-anchor="end" font-size="9" fill="#94a3b8">' + v + '</text>';
  }).join('');

  // Tier threshold dashed lines (Odor Index bands: alert 50, elevated 70, high 85)
  var threshSvg = [
    {pct: 50, color: '#fde047'}, {pct: 70, color: '#fdba74'}, {pct: 85, color: '#fca5a5'}
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
    var tier = OdorModel.getRiskTier(d.idx);
    var lbl  = d.h === 0 ? '12am' : d.h < 12 ? d.h + 'am' : d.h === 12 ? '12pm' : (d.h - 12) + 'pm';
    var tip  = lbl + ': index ' + Math.round(d.idx) + ' (' + d.ori.toFixed(1) + '% chance)';
    if (d.cell) {
      tip += '\nTemp: ' + d.cell.temp.toFixed(1) + '°F';
      tip += '\nBLH: ' + Math.round(d.cell.blh) + ' ft';
      if (useFitted) {
        tip += '\nWind (raw): ' + d.cell.wind_speed.toFixed(1) + ' mph @ ' + Math.round(d.cell.wind_dir) + '°';
        tip += '\nPrecip: ' + d.cell.precip.toFixed(3) + '"';
      } else {
        tip += '\nWind (daily avg): ' + (d.cell.wind_speed_d || 0).toFixed(1) + ' mph @ ' + Math.round(d.cell.wind_dir_d || 0) + '°';
      }
    }
    return '<circle cx="' + hx(d.h) + '" cy="' + vy(d.idx) + '" r="3" ' +
      'fill="rgb(' + tier.rgb.join(',') + ')" stroke="#fff" stroke-width="1">' +
      '<title>' + tip + '</title></circle>';
  }).join('');

  // Dashed daily-ORI anchor line
  var refLineSvg = '';
  if (dailyOri !== null) {
    var dailyIdx = OdorModel.computeIndex(dailyOri, APP.alertThreshold());
    var refY = vy(dailyIdx);
    refLineSvg =
      '<line x1="' + PL + '" y1="' + refY + '" x2="' + (PL + plotW) + '" y2="' + refY +
        '" stroke="#1e293b" stroke-width="1.5" stroke-dasharray="6,4"/>' +
      '<text x="' + (PL + 4) + '" y="' + (refY - 3) + '" font-size="8.5" fill="#1e293b" font-weight="600">Daily Index ' + Math.round(dailyIdx) + ' (' + dailyOri.toFixed(1) + '%)</text>';
  }

  var svgAriaLabel = useFitted ? 'Hourly odor risk (fitted case-crossover model)' : 'Relative trapping conditions through the day';
  var svg =
    '<svg viewBox="0 0 ' + W + ' ' + H + '" class="hourly-chart" aria-label="' + svgAriaLabel + '">' +
    '<rect x="' + PL + '" y="' + PT + '" width="' + plotW + '" height="' + plotH + '" fill="#f8fafc"/>' +
    yGridSvg + threshSvg + xTicksSvg + xLabelsSvg +
    (areaPath ? '<path d="' + areaPath + '" fill="rgba(37,99,235,0.1)"/>' : '') +
    (linePath ? '<path d="' + linePath + '" fill="none" stroke="#2563eb" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>' : '') +
    circlesSvg + refLineSvg +
    '<line x1="' + PL + '" y1="' + PT + '" x2="' + PL + '" y2="' + (PT + plotH) + '" stroke="#94a3b8" stroke-width="1"/>' +
    '<line x1="' + PL + '" y1="' + (PT + plotH) + '" x2="' + (PL + plotW) + '" y2="' + (PT + plotH) + '" stroke="#94a3b8" stroke-width="1"/>' +
    '</svg>';

  // 24-cell colored hour strip
  var stripCells = hours.map(function(d) {
    var tier     = d.idx !== null ? OdorModel.getRiskTier(d.idx) : {rgb: [148, 163, 184]};
    var textCol  = (d.idx !== null && d.idx >= 50) ? '#fff' : '#334155';
    var hLbl     = d.h === 0 ? '12a' : d.h < 12 ? d.h + 'a' : d.h === 12 ? '12p' : (d.h - 12) + 'p';
    var oriStr   = d.idx !== null ? Math.round(d.idx) : '—';
    var tip = '';
    if (d.cell) {
      var full = d.h === 0 ? '12am' : d.h < 12 ? d.h + 'am' : d.h === 12 ? '12pm' : (d.h - 12) + 'pm';
      tip = full + ': index ' + (d.idx !== null ? Math.round(d.idx) : '—') +
        (d.ori !== null ? ' (' + d.ori.toFixed(1) + '% chance)' : '') +
        ' | Temp ' + d.cell.temp.toFixed(1) + '°F, BLH ' + Math.round(d.cell.blh) + 'ft';
    }
    return '<div class="hour-cell" style="background:rgb(' + tier.rgb.join(',') + ');color:' + textCol + ';" title="' + tip + '">' +
      '<div class="hour-cell-label">' + hLbl + '</div>' +
      '<div class="hour-cell-ori">' + oriStr + '</div>' +
      '</div>';
  }).join('');

  var legendSubtitle = useFitted
    ? '— Fitted hourly model, anchored to daily ORI'
    : '— Daily model (constant-input), BLH &amp; temp vary';
  var legend =
    '<div class="hourly-legend">' +
    tierLegendHtml("Favorable") +
    '<span style="font-size:0.72rem;color:#64748b;align-self:center;margin-left:0.3rem;">' + legendSubtitle + '</span>' +
    '</div>';

  var caveat = useFitted
    ? '<div style="font-size:0.8rem;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;' +
      'border-radius:6px;padding:0.5rem 0.75rem;margin-top:0.5rem;line-height:1.5;">' +
      '<b>Fitted hourly model (case-crossover):</b> Coefficients were estimated from 8+ years of Pittsburgh ' +
      'smell reports by comparing odor-report hours to non-report control hours <em>within the same hour of the same calendar month</em>. ' +
      'This removes diurnal reporting bias and the solar/hour-of-day collinearity. Features: temperature (with quadratic), ' +
      'boundary-layer height, wind speed, humidity, atmospheric pressure, and precipitation — all at their raw hourly values. ' +
      'Solar radiation and DTR are excluded (absorbed by the strata). ' +
      'Because the model has no intercept, the 24 within-day values are <b>re-centered</b> so their mean matches the ' +
      'calibrated daily ORI (dashed line). The shape is data-fitted; the level is the daily forecast.' +
      '</div>'
    : '<div style="font-size:0.8rem;color:#64748b;background:#f8fafc;border:1px solid #e2e8f0;' +
      'border-radius:6px;padding:0.5rem 0.75rem;margin-top:0.5rem;line-height:1.5;">' +
      '<b>Daily model — constant-input view:</b> The deployed model is a <b>daily</b> logistic regression. ' +
      'This view holds all weather inputs that don\'t vary sub-daily at their <b>daily aggregate values</b>: ' +
      'solar radiation (daily mean), total precipitation (daily sum), relative humidity, atmospheric pressure, ' +
      'wind speed/direction (daily means), and DTR (daily max−min, constant by definition). ' +
      'Only <b>boundary-layer height (BLH)</b> and <b>temperature</b> vary hour by hour. ' +
      'The curve shows <em>when within the day</em> atmospheric trapping is most or least favorable, ' +
      'anchored to the calibrated daily ORI (dashed line). It is a qualitative within-day indicator, not a probability.' +
      '</div>';

  var chartTitle = useFitted
    ? 'Hourly odor risk (fitted case-crossover model)'
    : 'Relative trapping conditions through the day';

  wrap.innerHTML =
    '<p style="font-size:0.9rem;font-weight:600;color:#1e293b;margin:0 0 0.5rem;">' + chartTitle + '</p>' +
    '<div class="hourly-chart-box">' + svg + '</div>' +
    '<div class="hour-strip">' + stripCells + '</div>' +
    legend + caveat;
}

async function buildHourlyTab() {
  var panel = document.getElementById("tab-hourly");
  try {
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

  var datesHtml = APP.hourly.dates.map(function(d, i) {
    var dt  = new Date(d + 'T00:00:00');
    var lbl = dt.toLocaleDateString(undefined, {weekday: 'short', month: 'short', day: 'numeric'});
    return '<option value="' + d + '"' + (i === 0 ? ' selected' : '') + '>' + lbl + '</option>';
  }).join('');

  var hasFittedModel = !!(APP.meta && APP.meta.hourly_coeffs);
  var toggleHtml = hasFittedModel
    ? '<div class="hourly-model-toggle" style="display:flex;gap:0.5rem;align-items:center;' +
      'font-size:0.82rem;margin:0.25rem 0 0.5rem;">' +
      '<span style="color:#475569;font-weight:500;">Model:</span>' +
      '<label style="display:flex;gap:0.25rem;align-items:center;cursor:pointer;">' +
      '<input type="radio" name="hourly-mode" value="fitted" checked> Fitted hourly (case-crossover)</label>' +
      '<label style="display:flex;gap:0.25rem;align-items:center;cursor:pointer;">' +
      '<input type="radio" name="hourly-mode" value="daily"> Daily model (constant-input)</label>' +
      '</div>'
    : '';

  panel.innerHTML =
    '<div class="loc-header">' +
    '  <button id="btn-locate-hourly" class="btn-locate-small">📍 My Location</button>' +
    '  <span id="hourly-loc-label" class="loc-label">Click a tract on the map</span>' +
    '  <label style="font-size:0.82rem;flex-shrink:0;white-space:nowrap;">Day ' +
    '    <select id="hourly-date-sel">' + datesHtml + '</select>' +
    '  </label>' +
    '</div>' +
    '<div id="hourly-loc-map" class="loc-select-map"></div>' +
    toggleHtml +
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
        var tier = OdorModel.getRiskTier(APP.indexFor(cell));
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
        var v  = cell ? APP.riskView(cell) : null;
        layer.bindTooltip(dname + (v ? "<br>Daily Index: " + Math.round(v.idx) + " (" + v.prob.toFixed(1) + "% chance)" : ""), {sticky: true});
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

  // Hourly-model toggle (fitted vs daily constant-input)
  panel.querySelectorAll('input[name="hourly-mode"]').forEach(function(radio) {
    radio.addEventListener("change", renderHourly);
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
  } catch (e) {
    APP.hourly = null;
    panel.innerHTML =
      '<div style="padding:2rem;text-align:center;color:#b91c1c;">' +
      '<p style="font-size:1rem;font-weight:600;">Couldn\'t load the hourly forecast.</p>' +
      '<p style="font-size:0.85rem;color:#64748b;margin-bottom:1rem;">' + (e && e.message ? e.message : 'Unknown error') + '</p>' +
      '<button onclick="buildHourlyTab()" style="padding:0.4rem 1.2rem;border-radius:0.4rem;' +
      'background:#2563eb;color:#fff;border:none;cursor:pointer;font-size:0.9rem;">Retry</button>' +
      '</div>';
  }
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
          var v = APP.riskView(cell);
          L.popup().setLatLng([lat, lon])
            .setContent("<b>Nearest area:</b> " + near.name + "<br><b>Odor Index: " + Math.round(v.idx) + "</b> — " + v.tier.label + "<br>(" + v.prob.toFixed(1) + "% modeled chance)")
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
