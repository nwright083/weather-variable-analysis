// Pure ORI math — mirrors odor_forecast_core.predict_ori exactly.
// Dual-mode: attaches to window.OdorModel in the browser and exports for Node tests.
(function (root) {
  function computeZ(cell, c, pressureOffset) {
    var z = c.const
      + c.temperature * cell.temp
      + c.temperature_squared * cell.temp_sq
      + c.solar_radiation * cell.solar
      + c.relative_humidity * cell.rh
      + c.wind_speed * cell.wind_speed
      + c.precipitation * cell.precip
      + c.diurnal_temperature_range * cell.dtr
      + c.boundary_layer_height * cell.blh
      + c.atmospheric_pressure * (cell.pressure - pressureOffset);
    // Optional proximity terms (pittsburgh_proximity mode).
    // Mirrors predict_ori: exposure = exp(-0.02 * distance), wind_align = cell.wind_alignment.
    if (c.multi_source_exposure !== undefined && cell.distance !== undefined) {
      z += c.multi_source_exposure * Math.exp(-0.02 * cell.distance);
    }
    if (c.wind_align_weighted !== undefined && cell.wind_alignment !== undefined) {
      z += c.wind_align_weighted * cell.wind_alignment;
    }
    return z;
  }

  function computeOri(cell, c, opts) {
    var z = computeZ(cell, c, opts.pressureOffset);

    if (opts.windFilter) {
      if (opts.continuousAlignment && cell.wind_alignment !== undefined) {
        // Continuous cosine-based alignment (new behavior)
        var alignment = cell.wind_alignment;  // 0 to 1
        var effMult = opts.penalty + (opts.boost - opts.penalty) * alignment;
        z += Math.log(Math.max(effMult, 1e-9));
      } else {
        // Original discrete sector logic (backward compat)
        z += cell.aligned
          ? Math.log(Math.max(opts.boost, 1e-9))
          : Math.log(Math.max(opts.penalty, 1e-9));
      }
    }

    if (opts.distanceDecay && cell.distance) {
      z -= opts.decayRate * cell.distance;
    }
    z = Math.max(-60, Math.min(60, z));
    return Math.round((100 / (1 + Math.exp(-z))) * 10) / 10;
  }

  function getRiskTier(ori) {
    if (ori < 15) return { label: "Clear / Low Risk", cls: "badge-clear", rgb: [22, 163, 74] };
    if (ori < 30) return { label: "Moderate Risk", cls: "badge-moderate", rgb: [202, 138, 4] };
    if (ori < 50) return { label: "Elevated Risk", cls: "badge-elevated", rgb: [234, 88, 12] };
    return { label: "High Risk", cls: "badge-high", rgb: [220, 38, 38] };
  }

  var api = { computeZ: computeZ, computeOri: computeOri, getRiskTier: getRiskTier };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  root.OdorModel = api;
})(typeof window !== "undefined" ? window : globalThis);
