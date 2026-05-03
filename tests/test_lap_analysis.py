"""
tests/test_lap_analysis.py
==========================
Unit tests + regression fixtures for domain/lap_analysis.py.

Run (from repo root, with pandas installed):
    python -m pytest tests/test_lap_analysis.py -v
  or
    python -m unittest tests.test_lap_analysis -v

Coverage goals
--------------
  normalize_circuit     — all known aliases + unknown passthrough
  normalize_session     — all known aliases + unknown passthrough
  classify_fast_slow_tiers — n=1, n=2, n=3, n=6 (regression), multi-group
  build_lap_sus_map     — happy path, empty df, missing cols
  build_lap_time_map    — happy path, outlap filter, min_lap_s filter, col aliases
  join_sus_and_laptimes — full match, partial match, no match
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd

from domain.lap_analysis import (
    normalize_circuit,
    normalize_session,
    classify_fast_slow_tiers,
    build_lap_sus_map,
    build_lap_time_map,
    join_sus_and_laptimes,
)


# ──────────────────────────────────────────────────────────────────
# normalize_circuit
# ──────────────────────────────────────────────────────────────────

class TestNormalizeCircuit(unittest.TestCase):

    def test_phillip_island_variants(self):
        for raw in ("PHILLIPISLAND", "Phillip Island", "PHI", "AUSTRALIA",
                    "WORKSHOP", "PHILLIP_ISLAND", "phillip island"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_circuit(raw), "PHILLIP ISLAND")

    def test_standard_circuits_passthrough(self):
        for raw, expected in [
            ("PORTIMAO",     "PORTIMAO"),
            ("ASSEN",        "ASSEN"),
            ("ESTORIL",      "ESTORIL"),
            ("JEREZ",        "JEREZ"),
            ("MAGNY COURS",  "MAGNY COURS"),
        ]:
            self.assertEqual(normalize_circuit(raw), expected)

    def test_none_and_empty(self):
        self.assertEqual(normalize_circuit(None), "")
        self.assertEqual(normalize_circuit(""), "")

    def test_strips_whitespace(self):
        self.assertEqual(normalize_circuit("  portimao  "), "PORTIMAO")


# ──────────────────────────────────────────────────────────────────
# normalize_session
# ──────────────────────────────────────────────────────────────────

class TestNormalizeSession(unittest.TestCase):

    def test_fp_aliases(self):
        for raw in ("FP", "FP1", "FP2", "L1", "L2", "fp1"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_session(raw), "FP")

    def test_qp_aliases(self):
        for raw in ("QP", "QP1", "QP2"):
            self.assertEqual(normalize_session(raw), "QP")

    def test_wup_aliases(self):
        for raw in ("WUP", "WUP1", "WUP2"):
            self.assertEqual(normalize_session(raw), "WUP")

    def test_race_and_sp(self):
        self.assertEqual(normalize_session("RACE1"), "RACE1")
        self.assertEqual(normalize_session("RACE2"), "RACE2")
        self.assertEqual(normalize_session("SP"),    "SP")

    def test_unknown_passthrough(self):
        self.assertEqual(normalize_session("UNKNOWN"), "UNKNOWN")

    def test_none_and_empty(self):
        self.assertEqual(normalize_session(None), "")
        self.assertEqual(normalize_session(""),   "")


# ──────────────────────────────────────────────────────────────────
# classify_fast_slow_tiers
# ──────────────────────────────────────────────────────────────────

class TestClassifyFastSlowTiers(unittest.TestCase):

    def _make_df(self, times, rider="DA77", circuit="PORTIMAO"):
        return pd.DataFrame({
            "rider":   [rider] * len(times),
            "circuit": [circuit] * len(times),
            "best_s":  times,
        })

    # ── n < 3 edge cases ────────────────────────────────────────

    def test_n1_is_fast(self):
        df = self._make_df([90.0])
        result = classify_fast_slow_tiers(df)
        self.assertEqual(result.iloc[0]["tier"], "FAST")

    def test_n2_first_fast_second_slow(self):
        df = self._make_df([90.0, 92.0])
        result = classify_fast_slow_tiers(df)
        tiers = result.sort_values("best_s")["tier"].tolist()
        self.assertEqual(tiers, ["FAST", "SLOW"])

    # ── n = 3 (exact 33% boundary) ──────────────────────────────

    def test_n3_classification(self):
        df = self._make_df([90.0, 91.0, 92.0])
        result = classify_fast_slow_tiers(df).sort_values("best_s").reset_index(drop=True)
        self.assertEqual(result.iloc[0]["tier"], "FAST")
        self.assertEqual(result.iloc[1]["tier"], "MED")
        self.assertEqual(result.iloc[2]["tier"], "SLOW")

    # ── REGRESSION FIXTURE — n=6, fixed input → fixed output ────
    # These expected values are frozen from the first correct run.
    # If they ever change, the algorithm has changed unintentionally.

    def test_n6_regression(self):
        """Regression: 6-session PORTIMAO DA77 set."""
        times = [92.100, 92.500, 93.000, 93.800, 94.200, 95.000]
        df = self._make_df(times)
        result = classify_fast_slow_tiers(df).sort_values("best_s").reset_index(drop=True)
        expected = ["FAST", "FAST", "MED", "MED", "SLOW", "SLOW"]
        self.assertEqual(result["tier"].tolist(), expected)

    def test_original_index_preserved(self):
        """Tier assignment uses original DataFrame index, not positional."""
        df = pd.DataFrame({
            "rider":   ["DA77", "DA77", "DA77"],
            "circuit": ["PORTIMAO"] * 3,
            "best_s":  [95.0, 92.0, 93.5],   # out-of-order
        }, index=[10, 20, 30])
        result = classify_fast_slow_tiers(df)
        self.assertEqual(result.loc[20, "tier"], "FAST")   # 92.0 = fastest
        self.assertEqual(result.loc[10, "tier"], "SLOW")   # 95.0 = slowest

    # ── Multi-group independence ─────────────────────────────────

    def test_two_riders_classified_independently(self):
        df = pd.DataFrame({
            "rider":   ["DA77", "DA77", "DA77", "JA52", "JA52", "JA52"],
            "circuit": ["PORTIMAO"] * 6,
            "best_s":  [90.0, 91.0, 92.0,    93.0, 94.0, 95.0],
        })
        result = classify_fast_slow_tiers(df)
        da77 = result[result["rider"] == "DA77"].sort_values("best_s")
        ja52 = result[result["rider"] == "JA52"].sort_values("best_s")
        self.assertEqual(da77.iloc[0]["tier"], "FAST")
        self.assertEqual(ja52.iloc[0]["tier"], "FAST")
        self.assertEqual(da77.iloc[2]["tier"], "SLOW")
        self.assertEqual(ja52.iloc[2]["tier"], "SLOW")

    def test_two_circuits_classified_independently(self):
        df = pd.DataFrame({
            "rider":   ["DA77"] * 6,
            "circuit": ["PORTIMAO", "PORTIMAO", "PORTIMAO",
                        "ASSEN",    "ASSEN",    "ASSEN"],
            "best_s":  [90.0, 91.0, 92.0,   100.0, 101.0, 102.0],
        })
        result = classify_fast_slow_tiers(df)
        assen = result[result["circuit"] == "ASSEN"].sort_values("best_s")
        self.assertEqual(assen.iloc[0]["tier"], "FAST")

    def test_does_not_mutate_input(self):
        df = self._make_df([90.0, 91.0, 92.0])
        _ = classify_fast_slow_tiers(df)
        self.assertNotIn("tier", df.columns)


# ──────────────────────────────────────────────────────────────────
# build_lap_sus_map
# ──────────────────────────────────────────────────────────────────

class TestBuildLapSusMap(unittest.TestCase):

    def _make_ls_df(self, rows):
        return pd.DataFrame(rows, columns=[
            "RIDER", "CIRCUIT", "DATE", "RUN_NO",
            "THRON_SUSF_AVG", "THRON_SUSR_AVG",
            "BRK_SUSF_AVG",   "BRK_SUSR_AVG",
            "THRON_CNT",      "BRK_CNT",       "APEX_SPD_AVG",
        ])

    def test_basic_single_run(self):
        df = self._make_ls_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1,
             105.2, 95.1, 110.3, 100.2, 5, 4, 125.0],
        ])
        result = build_lap_sus_map(df)
        key = ("DA77", "PORTIMAO", "2025-10-01", 1)
        self.assertIn(key, result)
        self.assertAlmostEqual(result[key]["thron_susF"], 105.2, places=1)
        self.assertAlmostEqual(result[key]["brk_susF"],   110.3, places=1)

    def test_circuit_normalisation_applied(self):
        df = self._make_ls_df([
            ["DA77", "WORKSHOP", "2025-10-01", 1,
             105.0, 95.0, 110.0, 100.0, 3, 3, 120.0],
        ])
        result = build_lap_sus_map(df)
        key = ("DA77", "PHILLIP ISLAND", "2025-10-01", 1)
        self.assertIn(key, result)

    def test_empty_df_returns_empty_dict(self):
        self.assertEqual(build_lap_sus_map(pd.DataFrame()), {})

    def test_missing_required_cols_returns_empty(self):
        df = pd.DataFrame({"RIDER": ["DA77"], "CIRCUIT": ["PORTIMAO"]})
        self.assertEqual(build_lap_sus_map(df), {})

    def test_zero_thron_cnt_excluded_from_thron_avg(self):
        """Rows with THRON_CNT == 0 must not contribute to thron_susF mean."""
        df = self._make_ls_df([
            # lap 1: THRON_CNT=0 → excluded
            ["DA77", "PORTIMAO", "2025-10-01", 1, 200.0, 200.0, 110.0, 100.0, 0, 2, 120.0],
            # lap 2: THRON_CNT=3 → included
            ["DA77", "PORTIMAO", "2025-10-01", 1, 100.0, 90.0,  110.0, 100.0, 3, 2, 120.0],
        ])
        result = build_lap_sus_map(df)
        key = ("DA77", "PORTIMAO", "2025-10-01", 1)
        self.assertAlmostEqual(result[key]["thron_susF"], 100.0, places=1)

    def test_multi_run_creates_separate_keys(self):
        df = self._make_ls_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1, 105.0, 95.0, 110.0, 100.0, 3, 3, 120.0],
            ["DA77", "PORTIMAO", "2025-10-01", 2, 106.0, 96.0, 111.0, 101.0, 3, 3, 122.0],
        ])
        result = build_lap_sus_map(df)
        self.assertIn(("DA77", "PORTIMAO", "2025-10-01", 1), result)
        self.assertIn(("DA77", "PORTIMAO", "2025-10-01", 2), result)


# ──────────────────────────────────────────────────────────────────
# build_lap_time_map
# ──────────────────────────────────────────────────────────────────

class TestBuildLapTimeMap(unittest.TestCase):

    def _make_lt_df(self, rows):
        return pd.DataFrame(rows, columns=[
            "rider", "circuit", "date", "run_no", "lap_time_s", "outlap",
        ])

    def test_basic_best_lap_selection(self):
        df = self._make_lt_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1, 92.5, "NO"],
            ["DA77", "PORTIMAO", "2025-10-01", 1, 91.8, "NO"],  # best
            ["DA77", "PORTIMAO", "2025-10-01", 1, 93.1, "NO"],
        ])
        result = build_lap_time_map(df)
        key = ("DA77", "PORTIMAO", "2025-10-01", 1)
        self.assertAlmostEqual(result[key], 91.8, places=3)

    def test_outlap_excluded(self):
        df = self._make_lt_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1, 85.0, "YES"],  # outlap
            ["DA77", "PORTIMAO", "2025-10-01", 1, 92.0, "NO"],
        ])
        result = build_lap_time_map(df)
        self.assertAlmostEqual(result[("DA77", "PORTIMAO", "2025-10-01", 1)], 92.0)

    def test_min_lap_s_filter(self):
        df = self._make_lt_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1, 70.0, "NO"],  # too fast → excluded
            ["DA77", "PORTIMAO", "2025-10-01", 1, 92.0, "NO"],
        ])
        result = build_lap_time_map(df, min_lap_s=80.0)
        self.assertAlmostEqual(result[("DA77", "PORTIMAO", "2025-10-01", 1)], 92.0)

    def test_max_400s_filter(self):
        df = self._make_lt_df([
            ["DA77", "PORTIMAO", "2025-10-01", 1, 401.0, "NO"],  # invalid
            ["DA77", "PORTIMAO", "2025-10-01", 1, 92.0,  "NO"],
        ])
        result = build_lap_time_map(df)
        self.assertAlmostEqual(result[("DA77", "PORTIMAO", "2025-10-01", 1)], 92.0)

    def test_circuit_normalisation(self):
        df = self._make_lt_df([
            ["DA77", "WORKSHOP", "2025-10-01", 1, 92.0, "NO"],
        ])
        result = build_lap_time_map(df)
        self.assertIn(("DA77", "PHILLIP ISLAND", "2025-10-01", 1), result)

    def test_empty_df_returns_empty_dict(self):
        self.assertEqual(build_lap_time_map(pd.DataFrame()), {})

    def test_missing_required_col_returns_empty(self):
        df = pd.DataFrame({"rider": ["DA77"], "circuit": ["PORTIMAO"]})
        self.assertEqual(build_lap_time_map(df), {})

    def test_column_name_aliases(self):
        """build_lap_time_map must accept 'rider_id' instead of 'rider'."""
        df = pd.DataFrame({
            "rider_id": ["DA77"],
            "circuit":  ["PORTIMAO"],
            "date":     ["2025-10-01"],
            "run_no":   [1],
            "lap_time_s": [92.0],
        })
        result = build_lap_time_map(df)
        self.assertIn(("DA77", "PORTIMAO", "2025-10-01", 1), result)


# ──────────────────────────────────────────────────────────────────
# join_sus_and_laptimes
# ──────────────────────────────────────────────────────────────────

class TestJoinSusAndLaptimes(unittest.TestCase):

    def test_full_match(self):
        ls_map = {
            ("DA77", "PORTIMAO", "2025-10-01", 1): {
                "thron_susF": 105.0, "thron_susR": 95.0,
                "brk_susF": 110.0, "brk_susR": 100.0, "apex_spd": 125.0,
            }
        }
        lt_best = {("DA77", "PORTIMAO", "2025-10-01", 1): 92.0}
        rows = join_sus_and_laptimes(ls_map, lt_best)
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["best_s"],    92.0)
        self.assertAlmostEqual(rows[0]["apex_susF"], 105.0)  # mapped from thron_susF
        self.assertAlmostEqual(rows[0]["brk_susF"],  110.0)

    def test_no_match_returns_empty(self):
        ls_map  = {("DA77", "PORTIMAO", "2025-10-01", 1): {}}
        lt_best = {("JA52", "ASSEN",    "2025-11-01", 1): 90.0}
        self.assertEqual(join_sus_and_laptimes(ls_map, lt_best), [])

    def test_partial_match(self):
        ls_map = {
            ("DA77", "PORTIMAO", "2025-10-01", 1): {"thron_susF": 105.0, "thron_susR": 95.0,
                                                      "brk_susF": 110.0, "brk_susR": 100.0, "apex_spd": 125.0},
            ("DA77", "PORTIMAO", "2025-10-01", 2): {"thron_susF": 106.0, "thron_susR": 96.0,
                                                      "brk_susF": 111.0, "brk_susR": 101.0, "apex_spd": 126.0},
        }
        lt_best = {
            ("DA77", "PORTIMAO", "2025-10-01", 1): 92.0,
            # run 2 exists in ls_map but NOT in lt_best → not joined
            ("DA77", "PORTIMAO", "2025-10-01", 3): 91.0,  # in lt_best only
        }
        rows = join_sus_and_laptimes(ls_map, lt_best)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run"], 1)

    def test_output_columns_present(self):
        ls_map  = {("DA77", "PORTIMAO", "2025-10-01", 1): {
            "thron_susF": 105.0, "thron_susR": 95.0,
            "brk_susF": 110.0, "brk_susR": 100.0, "apex_spd": 125.0,
        }}
        lt_best = {("DA77", "PORTIMAO", "2025-10-01", 1): 92.0}
        rows = join_sus_and_laptimes(ls_map, lt_best)
        required = {"rider", "circuit", "date", "run", "best_s",
                    "apex_susF", "apex_susR", "apex_spd", "brk_susF", "brk_susR"}
        self.assertTrue(required.issubset(rows[0].keys()))

    def test_empty_inputs(self):
        self.assertEqual(join_sus_and_laptimes({}, {}), [])
        self.assertEqual(join_sus_and_laptimes({}, {("DA77", "PORTIMAO", "2025-10-01", 1): 92.0}), [])


# ──────────────────────────────────────────────────────────────────
# End-to-end pipeline regression
# ──────────────────────────────────────────────────────────────────

class TestPipelineRegression(unittest.TestCase):
    """
    Fixed input → fixed output regression test for the full
    build_lap_sus_map → build_lap_time_map → join → classify pipeline.

    Expected output was computed from the first confirmed-correct run.
    Any change to these values signals an algorithm regression.
    """

    # ── Frozen input fixtures ────────────────────────────────────

    LAP_SUS_ROWS = [
        # RIDER, CIRCUIT, DATE, RUN_NO, THRON_SUSF, THRON_SUSR, BRK_SUSF, BRK_SUSR, THRON_CNT, BRK_CNT, APEX_SPD
        ["DA77", "PORTIMAO", "2025-10-01", 1, 105.0, 95.0, 110.0, 100.0, 5, 4, 125.0],
        ["DA77", "PORTIMAO", "2025-10-01", 2, 106.0, 96.0, 111.0, 101.0, 5, 4, 126.0],
        ["DA77", "PORTIMAO", "2025-10-01", 3, 104.0, 94.0, 109.0, 99.0,  5, 4, 124.0],
        ["DA77", "PORTIMAO", "2025-10-02", 1, 107.0, 97.0, 112.0, 102.0, 5, 4, 127.0],
        ["DA77", "PORTIMAO", "2025-10-02", 2, 103.0, 93.0, 108.0, 98.0,  5, 4, 123.0],
        ["DA77", "PORTIMAO", "2025-10-02", 3, 108.0, 98.0, 113.0, 103.0, 5, 4, 128.0],
    ]

    LAP_TIME_ROWS = [
        # rider, circuit, date, run_no, lap_time_s, outlap
        ["DA77", "PORTIMAO", "2025-10-01", 1, 92.5, "NO"],
        ["DA77", "PORTIMAO", "2025-10-01", 1, 91.8, "NO"],  # best run1 day1
        ["DA77", "PORTIMAO", "2025-10-01", 2, 93.0, "NO"],  # best run2 day1
        ["DA77", "PORTIMAO", "2025-10-01", 2, 93.2, "NO"],
        ["DA77", "PORTIMAO", "2025-10-01", 3, 92.0, "NO"],  # best run3 day1
        ["DA77", "PORTIMAO", "2025-10-01", 3, 92.4, "NO"],
        ["DA77", "PORTIMAO", "2025-10-02", 1, 91.5, "NO"],  # best run1 day2
        ["DA77", "PORTIMAO", "2025-10-02", 2, 90.8, "NO"],  # best run2 day2 (overall fastest)
        ["DA77", "PORTIMAO", "2025-10-02", 3, 92.1, "NO"],  # best run3 day2
    ]

    # ── Expected frozen output ───────────────────────────────────
    # Sorted by best_s ascending.
    EXPECTED_TIERS = {
        ("DA77", "PORTIMAO", "2025-10-02", 2): "FAST",   # 90.8  rank 0/5 = 0.00
        ("DA77", "PORTIMAO", "2025-10-02", 1): "FAST",   # 91.5  rank 1/5 = 0.20
        ("DA77", "PORTIMAO", "2025-10-01", 1): "MED",    # 91.8  rank 2/5 = 0.40
        ("DA77", "PORTIMAO", "2025-10-01", 3): "MED",    # 92.0  rank 3/5 = 0.60
        ("DA77", "PORTIMAO", "2025-10-02", 3): "SLOW",   # 92.1  rank 4/5 = 0.80
        ("DA77", "PORTIMAO", "2025-10-01", 2): "SLOW",   # 93.0  rank 5/5 = 1.00
    }

    def setUp(self):
        cols_ls = ["RIDER", "CIRCUIT", "DATE", "RUN_NO",
                   "THRON_SUSF_AVG", "THRON_SUSR_AVG",
                   "BRK_SUSF_AVG", "BRK_SUSR_AVG",
                   "THRON_CNT", "BRK_CNT", "APEX_SPD_AVG"]
        cols_lt = ["rider", "circuit", "date", "run_no", "lap_time_s", "outlap"]
        self.df_ls = pd.DataFrame(self.LAP_SUS_ROWS, columns=cols_ls)
        self.df_lt = pd.DataFrame(self.LAP_TIME_ROWS, columns=cols_lt)

    def test_full_pipeline_match_count(self):
        ls_map  = build_lap_sus_map(self.df_ls)
        lt_best = build_lap_time_map(self.df_lt)
        rows    = join_sus_and_laptimes(ls_map, lt_best)
        self.assertEqual(len(rows), 6, "Expected exactly 6 matched sessions")

    def test_full_pipeline_tier_regression(self):
        ls_map  = build_lap_sus_map(self.df_ls)
        lt_best = build_lap_time_map(self.df_lt)
        rows    = join_sus_and_laptimes(ls_map, lt_best)
        df_m    = pd.DataFrame(rows)
        df_m    = classify_fast_slow_tiers(df_m)

        for _, row in df_m.iterrows():
            key = (row["rider"], row["circuit"], row["date"], row["run"])
            expected_tier = self.EXPECTED_TIERS[key]
            self.assertEqual(
                row["tier"], expected_tier,
                f"Tier mismatch for {key}: got {row['tier']!r}, expected {expected_tier!r}"
            )

    def test_full_pipeline_best_lap_values(self):
        ls_map  = build_lap_sus_map(self.df_ls)
        lt_best = build_lap_time_map(self.df_lt)
        rows    = join_sus_and_laptimes(ls_map, lt_best)
        df_m    = pd.DataFrame(rows)

        run2_day2 = df_m[(df_m["date"] == "2025-10-02") & (df_m["run"] == 2)]
        self.assertAlmostEqual(run2_day2.iloc[0]["best_s"], 90.8, places=3)

    def test_full_pipeline_sus_values_intact(self):
        ls_map  = build_lap_sus_map(self.df_ls)
        lt_best = build_lap_time_map(self.df_lt)
        rows    = join_sus_and_laptimes(ls_map, lt_best)
        df_m    = pd.DataFrame(rows)

        run1_day1 = df_m[(df_m["date"] == "2025-10-01") & (df_m["run"] == 1)]
        self.assertAlmostEqual(run1_day1.iloc[0]["apex_susF"], 105.0, places=1)
        self.assertAlmostEqual(run1_day1.iloc[0]["brk_susF"],  110.0, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
