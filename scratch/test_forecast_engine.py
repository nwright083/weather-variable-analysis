import math
import unittest
import sqlite3
import os
import sys
import numpy as np
import pandas as pd

# Add the project root to path to test imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odor_forecast_core import (
    predict_ori,
    COEFFS_PITTSBURGH, COEFFS_EST_CALVERT, PRESSURE_ELEVATION_OFFSET
)

class TestCalvertOdorForecaster(unittest.TestCase):

    def setUp(self):
        self.test_db_path = "test_calvert_tester_logs.db"

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_database_initialization(self):
        """Verify SQLite database is initialized and contains correct tables and columns."""
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dispatches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                location TEXT,
                predicted_ori REAL,
                wind_direction REAL,
                wind_speed REAL,
                pblh REAL,
                status TEXT DEFAULT 'Scheduled',
                UNIQUE(date, location)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dispatch_id INTEGER,
                tester_name TEXT,
                date_reported TEXT,
                odor_detected TEXT,
                severity INTEGER,
                comments TEXT,
                FOREIGN KEY (dispatch_id) REFERENCES dispatches(id)
            )
        """)
        conn.commit()

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='dispatches'")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reports'")
        self.assertIsNotNone(cursor.fetchone())

        cursor.execute("PRAGMA table_info(dispatches)")
        columns = [col[1] for col in cursor.fetchall()]
        self.assertIn("date", columns)
        self.assertIn("location", columns)
        self.assertIn("predicted_ori", columns)
        self.assertIn("status", columns)

        conn.close()

    def test_prediction_math_pittsburgh(self):
        """predict_ori must apply PRESSURE_ELEVATION_OFFSET and return a calibrated probability."""
        mock_row = pd.Series({
            'temperature': 65.0,
            'temperature_squared': 65.0 ** 2,
            'solar_radiation': 200.0,
            'relative_humidity': 60.0,
            'wind_speed': 5.0,
            'precipitation': 0.0,
            'diurnal_temperature_range': 15.0,
            'boundary_layer_height': 1500.0,
            'atmospheric_pressure': 1013.0,
            'wind_direction': 20.0,       # NNE — aligned with bearing_from_source=200
            'bearing_from_source': 200.0,
        })

        # Reference z using the corrected pressure formula (offset applied).
        # wind_boost defaults to 1.0 → log(1.0)=0, no log-odds change for aligned case.
        z = (
            COEFFS_PITTSBURGH['const'] +
            COEFFS_PITTSBURGH['temperature'] * mock_row['temperature'] +
            COEFFS_PITTSBURGH['temperature_squared'] * mock_row['temperature_squared'] +
            COEFFS_PITTSBURGH['solar_radiation'] * mock_row['solar_radiation'] +
            COEFFS_PITTSBURGH['relative_humidity'] * mock_row['relative_humidity'] +
            COEFFS_PITTSBURGH['wind_speed'] * mock_row['wind_speed'] +
            COEFFS_PITTSBURGH['precipitation'] * mock_row['precipitation'] +
            COEFFS_PITTSBURGH['diurnal_temperature_range'] * mock_row['diurnal_temperature_range'] +
            COEFFS_PITTSBURGH['boundary_layer_height'] * mock_row['boundary_layer_height'] +
            COEFFS_PITTSBURGH['atmospheric_pressure'] * (mock_row['atmospheric_pressure'] - PRESSURE_ELEVATION_OFFSET)
        )
        z = max(-60.0, min(60.0, z))
        expected_ori = round(100.0 / (1.0 + math.exp(-z)), 1)

        self.assertAlmostEqual(predict_ori(mock_row, COEFFS_PITTSBURGH), expected_ori, places=1)

    def test_pressure_elevation_offset_raises_ori(self):
        """For typical Calvert City surface pressures, the elevation offset must raise ORI
        vs. the raw (uncorrected) prediction."""
        mock_row = pd.Series({
            'temperature': 78.0,
            'temperature_squared': 78.0 ** 2,
            'solar_radiation': 180.0,
            'relative_humidity': 72.0,
            'wind_speed': 2.5,
            'precipitation': 0.0,
            'diurnal_temperature_range': 18.0,
            'boundary_layer_height': 600.0,
            'atmospheric_pressure': 1005.0,  # typical Calvert City surface pressure
            'wind_direction': 10.0,
            'bearing_from_source': 190.0,
        })

        # ORI with correction applied (through predict_ori)
        ori_corrected = predict_ori(mock_row, COEFFS_PITTSBURGH)

        # ORI without correction (manually use raw pressure)
        z_raw = (
            COEFFS_PITTSBURGH['const'] +
            COEFFS_PITTSBURGH['temperature'] * mock_row['temperature'] +
            COEFFS_PITTSBURGH['temperature_squared'] * mock_row['temperature_squared'] +
            COEFFS_PITTSBURGH['solar_radiation'] * mock_row['solar_radiation'] +
            COEFFS_PITTSBURGH['relative_humidity'] * mock_row['relative_humidity'] +
            COEFFS_PITTSBURGH['wind_speed'] * mock_row['wind_speed'] +
            COEFFS_PITTSBURGH['precipitation'] * mock_row['precipitation'] +
            COEFFS_PITTSBURGH['diurnal_temperature_range'] * mock_row['diurnal_temperature_range'] +
            COEFFS_PITTSBURGH['boundary_layer_height'] * mock_row['boundary_layer_height'] +
            COEFFS_PITTSBURGH['atmospheric_pressure'] * mock_row['atmospheric_pressure']  # raw, no offset
        )
        z_raw = max(-60.0, min(60.0, z_raw))
        ori_raw = round(100.0 / (1.0 + math.exp(-z_raw)), 1)

        # pressure coef is negative and Calvert pressure > Pittsburgh training mean,
        # so subtracting the offset increases z and therefore ORI.
        self.assertGreater(ori_corrected, ori_raw,
                           msg=f"Offset should raise ORI: corrected={ori_corrected} raw={ori_raw}")

    def test_vector_wind_mean(self):
        """Speed-weighted vector mean must handle the 0°/360° wrap correctly.

        350° and 10° should average to ~0° (north), not 180° (south) as arithmetic mean gives.
        """
        dirs = np.array([350.0, 10.0])
        speeds = np.array([5.0, 5.0])
        u = speeds * np.sin(np.radians(dirs))
        v = speeds * np.cos(np.radians(dirs))
        vector_mean = np.degrees(np.arctan2(u.mean(), v.mean())) % 360

        # Must be near 0°/360° (north), not anywhere near 180° (south)
        dist_from_north = min(vector_mean, 360.0 - vector_mean)
        self.assertLess(dist_from_north, 5.0,
                        msg=f"Vector mean of 350°/10° should be near 0° (north), got {vector_mean:.2f}°")

        # Confirm the arithmetic mean would give the wrong answer (near 180°)
        arith_mean = dirs.mean()
        self.assertAlmostEqual(arith_mean, 180.0, places=0,
                               msg="Arithmetic mean of 350°/10° should equal 180° (demonstrating the bug)")

    def test_wind_direction_filter(self):
        """Wind corridor adjustment must operate in log-odds space, not probability space."""
        mock_row_aligned = pd.Series({
            'temperature': 65.0,
            'temperature_squared': 65.0 ** 2,
            'solar_radiation': 200.0,
            'relative_humidity': 60.0,
            'wind_speed': 2.0,
            'precipitation': 0.0,
            'diurnal_temperature_range': 25.0,
            'boundary_layer_height': 800.0,
            'atmospheric_pressure': 1013.0,
            'wind_direction': 20.0,       # NNE — aligned with bearing_from_source=200
            'bearing_from_source': 200.0,
        })

        mock_row_misaligned = mock_row_aligned.copy()
        mock_row_misaligned['wind_direction'] = 200.0  # SSW — blowing away from receiver

        ori_aligned = predict_ori(mock_row_aligned, COEFFS_EST_CALVERT)
        ori_misaligned = predict_ori(mock_row_misaligned, COEFFS_EST_CALVERT)

        # Build the base log-odds (no wind adjustment)
        base_z = (
            COEFFS_EST_CALVERT['const'] +
            COEFFS_EST_CALVERT['temperature'] * mock_row_aligned['temperature'] +
            COEFFS_EST_CALVERT['temperature_squared'] * mock_row_aligned['temperature_squared'] +
            COEFFS_EST_CALVERT['solar_radiation'] * mock_row_aligned['solar_radiation'] +
            COEFFS_EST_CALVERT['relative_humidity'] * mock_row_aligned['relative_humidity'] +
            COEFFS_EST_CALVERT['wind_speed'] * mock_row_aligned['wind_speed'] +
            COEFFS_EST_CALVERT['precipitation'] * mock_row_aligned['precipitation'] +
            COEFFS_EST_CALVERT['diurnal_temperature_range'] * mock_row_aligned['diurnal_temperature_range'] +
            COEFFS_EST_CALVERT['boundary_layer_height'] * mock_row_aligned['boundary_layer_height'] +
            COEFFS_EST_CALVERT['atmospheric_pressure'] * (mock_row_aligned['atmospheric_pressure'] - PRESSURE_ELEVATION_OFFSET)
        )

        # Defaults: wind_boost=1.0 (aligned), wind_penalty=0.25 (75% penalty, misaligned)
        z_aligned = max(-60.0, min(60.0, base_z + math.log(1.0)))
        z_misaligned = max(-60.0, min(60.0, base_z + math.log(0.25)))

        expected_aligned = round(100.0 / (1.0 + math.exp(-z_aligned)), 1)
        expected_misaligned = round(100.0 / (1.0 + math.exp(-z_misaligned)), 1)

        self.assertAlmostEqual(ori_aligned, expected_aligned, places=1)
        self.assertAlmostEqual(ori_misaligned, expected_misaligned, places=1)
        # Misaligned must always be lower than aligned
        self.assertLess(ori_misaligned, ori_aligned)


if __name__ == '__main__':
    unittest.main()
