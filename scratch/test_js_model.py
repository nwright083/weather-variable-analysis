import os
import sys
import json
import math
import shutil
import subprocess
import unittest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import odor_forecast_core as core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_JS = os.path.join(ROOT, "docs", "model.js")


@unittest.skipIf(shutil.which("node") is None, "node not installed")
class TestJsParity(unittest.TestCase):
    def _js_ori(self, cell, coeffs, opts):
        script = (
            "const m=require(process.argv[1]);"
            "const a=JSON.parse(process.argv[2]);"
            "process.stdout.write(String(m.computeOri(a.cell,a.coeffs,a.opts)));"
        )
        payload = json.dumps({"cell": cell, "coeffs": coeffs, "opts": opts})
        out = subprocess.check_output(["node", "-e", script, MODEL_JS, payload])
        return float(out.decode().strip())

    def test_parity_aligned_and_misaligned(self):
        loc = "ZIP 42029 (Calvert City)"
        base = {
            "temperature": 78.0, "temperature_squared": 78.0 ** 2, "solar_radiation": 180.0,
            "relative_humidity": 72.0, "wind_speed": 2.5, "precipitation": 0.0,
            "diurnal_temperature_range": 18.0, "boundary_layer_height": 600.0,
            "atmospheric_pressure": 1005.0, "location": loc,
        }
        for wind_dir in (10.0, 200.0, 355.0):
            row = dict(base, wind_direction=wind_dir)
            aligned = core.check_wind_alignment(wind_dir, loc)
            cell = {
                "temp": row["temperature"], "temp_sq": row["temperature_squared"],
                "solar": row["solar_radiation"], "rh": row["relative_humidity"],
                "wind_speed": row["wind_speed"], "precip": row["precipitation"],
                "dtr": row["diurnal_temperature_range"], "blh": row["boundary_layer_height"],
                "pressure": row["atmospheric_pressure"], "aligned": bool(aligned),
            }
            opts = {"pressureOffset": core.PRESSURE_ELEVATION_OFFSET,
                    "windFilter": True, "penalty": 0.25, "boost": 1.0}
            ori_py = core.predict_ori(row, core.COEFFS_PITTSBURGH,
                                      use_wind_filter=True, wind_penalty=0.25, wind_boost=1.0)
            ori_js = self._js_ori(cell, core.COEFFS_PITTSBURGH, opts)
            self.assertAlmostEqual(ori_py, ori_js, delta=0.1,
                                   msg=f"wind_dir={wind_dir} py={ori_py} js={ori_js}")

    def test_parity_four_models_multisource(self):
        """Python predict_ori and JS computeOri agree across the 2x2 of
        {Exact, Transfer} x {weather-only, Proximity} with nearest-source terms."""
        lat, lon = 36.9448, -88.2930  # Tract 9503, Marshall Co.
        base = {
            "temperature": 82.0, "temperature_squared": 82.0 ** 2, "solar_radiation": 210.0,
            "relative_humidity": 65.0, "wind_speed": 3.0, "precipitation": 0.0,
            "diurnal_temperature_range": 20.0, "boundary_layer_height": 550.0,
            "atmospheric_pressure": 1004.0,
        }
        OFF = core.PRESSURE_ELEVATION_OFFSET
        models = [
            (core.COEFFS_PITTSBURGH,           0.0,  False),  # exact_pittsburgh
            (core.COEFFS_PITTSBURGH_PROXIMITY, 0.0,  False),  # exact_pittsburgh_proximity
            (core.COEFFS_PITTSBURGH,           OFF,  True),   # pittsburgh_transfer
            (core.COEFFS_PITTSBURGH_PROXIMITY, OFF,  True),   # pittsburgh_transfer_proximity
        ]
        for wind_dir in (10.0, 200.0, 315.0):
            mse, msa = core.compute_multisource_terms(lat, lon, wind_dir)
            row = dict(base, wind_direction=wind_dir, mse=mse, msa=msa)
            cell = {
                "temp": base["temperature"], "temp_sq": base["temperature_squared"],
                "solar": base["solar_radiation"], "rh": base["relative_humidity"],
                "wind_speed": base["wind_speed"], "precip": base["precipitation"],
                "dtr": base["diurnal_temperature_range"], "blh": base["boundary_layer_height"],
                "pressure": base["atmospheric_pressure"], "mse": mse, "msa": msa,
            }
            for coeffs, offset, transfer in models:
                opts = {"pressureOffset": offset, "windFilter": False}
                ori_py = core.predict_ori(row, coeffs, use_wind_filter=False,
                                          apply_pressure_transfer=transfer)
                ori_js = self._js_ori(cell, coeffs, opts)
                self.assertAlmostEqual(
                    ori_py, ori_js, delta=0.1,
                    msg=f"wind_dir={wind_dir} transfer={transfer} py={ori_py} js={ori_js}")


if __name__ == "__main__":
    unittest.main()
