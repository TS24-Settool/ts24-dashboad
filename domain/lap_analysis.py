"""
domain/lap_analysis.py — Core lap and suspension analysis logic
================================================================
Pure Python, no Streamlit dependency.
All functions here are suitable for use in a backend API, CLI tool,
or commercial product without modification.

# PRODUCT-CANDIDATE: A_NORMALIZE | B_APEX | C_SETUP_TARGET — This entire module.
"""

import pandas as pd


# ── Circuit / session normalization ──────────────────────────────

def normalize_circuit(c: str) -> str:
    """Normalize circuit name to a canonical uppercase string.

    # PRODUCT-CANDIDATE: A_NORMALIZE
    """
    c = str(c or "").upper().strip()
    if c in ("PHILLIPISLAND", "PHILLIP ISLAND", "PHI", "AUSTRALIA", "WORKSHOP", "PHILLIP_ISLAND"):
        return "PHILLIP ISLAND"
    return c


def normalize_session(s: str) -> str:
    """Map raw session type strings to canonical codes.

    # PRODUCT-CANDIDATE: A_NORMALIZE
    """
    s = str(s or "").upper().strip()
    m = {
        "WUP": "WUP", "WUP1": "WUP", "WUP2": "WUP",
        "FP":  "FP",  "FP1":  "FP",  "FP2":  "FP",  "L1": "FP", "L2": "FP",
        "QP":  "QP",  "QP1":  "QP",  "QP2":  "QP",
        "SP":  "SP",
        "RACE1": "RACE1", "RACE2": "RACE2",
        "TEST_D1": "TEST_D1", "TEST_D2": "TEST_D2",
    }
    return m.get(s, s)


# ── Tier classification (FAST / MED / SLOW) ──────────────────────

def classify_fast_slow_tiers(
    df: pd.DataFrame,
    group_cols: tuple = ("rider", "circuit"),
    sort_col: str = "best_s",
) -> pd.DataFrame:
    """Classify sessions into FAST / MED / SLOW within each group.

    FAST = fastest 33 %, SLOW = slowest 33 %, MED = middle.
    When a group has fewer than 3 sessions, rank 0 = FAST, rest = SLOW.

    Args:
        df:         DataFrame with at least `group_cols` + `sort_col`.
        group_cols: Columns to group by (default: rider × circuit).
        sort_col:   Column to rank on ascending (default: best lap time).

    Returns:
        Copy of df with a ``tier`` column added.

    # PRODUCT-CANDIDATE: C_SETUP_TARGET
    """
    df = df.copy()
    df["tier"] = "MED"
    for _, idx in df.groupby(list(group_cols)).groups.items():
        sub = df.loc[idx].sort_values(sort_col)
        n = len(sub)
        idxs = list(sub.index)
        for rank, orig_idx in enumerate(idxs):
            pct = rank / max(n - 1, 1)
            if n < 3:
                t = "FAST" if rank == 0 else "SLOW"
            elif pct <= 0.33:
                t = "FAST"
            elif pct >= 0.67:
                t = "SLOW"
            else:
                t = "MED"
            df.at[orig_idx, "tier"] = t
    return df


# ── Suspension map builders ──────────────────────────────────────

def build_lap_sus_map(df_ls: pd.DataFrame, normalize_circuit_fn=None) -> dict:
    """Build a keyed mapping of per-run suspension averages from LAP_SUSPENSION data.

    Key:   (rider, circuit_normalized, date_str, run_no_int)
    Value: dict with keys thron_susF, thron_susR, brk_susF, brk_susR, apex_spd

    Args:
        df_ls:               LAP_SUSPENSION DataFrame (columns upper-cased).
        normalize_circuit_fn: Optional callable; defaults to normalize_circuit.

    Returns:
        dict mapping (rider, circuit, date, run) → suspension stat averages.

    # PRODUCT-CANDIDATE: B_APEX
    """
    if normalize_circuit_fn is None:
        normalize_circuit_fn = normalize_circuit

    ls_map: dict = {}
    if df_ls.empty:
        return ls_map

    for nc in [
        "THRON_SUSF_AVG", "THRON_SUSR_AVG", "BRK_SUSF_AVG", "BRK_SUSR_AVG",
        "THRON_CNT", "BRK_CNT", "APEX_SPD_AVG", "APEX_CNT",
    ]:
        if nc in df_ls.columns:
            df_ls[nc] = pd.to_numeric(df_ls[nc], errors="coerce")

    grp_cols = [c for c in ["RIDER", "CIRCUIT", "DATE", "RUN_NO"] if c in df_ls.columns]
    if len(grp_cols) != 4:
        return ls_map

    for gkey, gdf in df_ls.groupby(grp_cols):
        rider_g, circ_g, date_g, run_g = gkey
        circ_n = normalize_circuit_fn(circ_g)
        date_s = str(date_g or "")
        try:
            run_i = int(run_g or 0)
        except Exception:
            run_i = 0

        g_thron = gdf[gdf["THRON_CNT"] > 0] if "THRON_CNT" in gdf.columns else gdf
        g_brk   = gdf[gdf["BRK_CNT"]   > 0] if "BRK_CNT"   in gdf.columns else gdf

        ls_map[(rider_g, circ_n, date_s, run_i)] = {
            "thron_susF": g_thron["THRON_SUSF_AVG"].dropna().mean() if not g_thron.empty else None,
            "thron_susR": g_thron["THRON_SUSR_AVG"].dropna().mean() if not g_thron.empty else None,
            "brk_susF":   g_brk["BRK_SUSF_AVG"].dropna().mean()    if not g_brk.empty   else None,
            "brk_susR":   g_brk["BRK_SUSR_AVG"].dropna().mean()    if not g_brk.empty   else None,
            "apex_spd":   gdf["APEX_SPD_AVG"].dropna().mean()       if "APEX_SPD_AVG" in gdf.columns else None,
        }

    return ls_map


def build_lap_time_map(
    df_lt: pd.DataFrame,
    normalize_circuit_fn=None,
    min_lap_s: float = 80.0,
) -> dict:
    """Build a keyed mapping of best lap time (seconds) per run from LAP_TIMES data.

    Key:   (rider, circuit_normalized, date_str, run_no_int)
    Value: float — best valid lap time in seconds

    Args:
        df_lt:                LAP_TIMES DataFrame (column names case-insensitive).
        normalize_circuit_fn: Optional callable; defaults to normalize_circuit.
        min_lap_s:            Minimum plausible lap time (seconds) to include.

    Returns:
        dict mapping (rider, circuit, date, run) → best lap time (s).

    # PRODUCT-CANDIDATE: B_APEX
    """
    if normalize_circuit_fn is None:
        normalize_circuit_fn = normalize_circuit

    if df_lt.empty:
        return {}

    def _col(candidates):
        return next((c for c in df_lt.columns if str(c).lower() in candidates), None)

    lt_rider_col  = _col(("rider", "rider_id"))
    lt_circ_col   = _col(("circuit", "circ"))
    lt_date_col   = _col(("date", "session_date"))
    lt_run_col    = _col(("run", "run_no", "run no"))
    lt_ts_col     = _col(("lap_time_s", "laptime_s", "lap time s", "time (s)"))
    lt_outlap_col = _col(("outlap", "is_outlap", "out_lap", "outlap?"))

    if not all([lt_rider_col, lt_circ_col, lt_date_col, lt_run_col, lt_ts_col]):
        return {}

    lt_map: dict = {}
    for _, lr in df_lt.iterrows():
        rider = str(lr[lt_rider_col] or "")
        if not rider:
            continue
        if lt_outlap_col and str(lr.get(lt_outlap_col, "")).upper() == "YES":
            continue
        ts = lr[lt_ts_col]
        if not isinstance(ts, (int, float)) or ts < min_lap_s or ts > 400:
            continue
        circ = normalize_circuit_fn(lr[lt_circ_col])
        date = str(lr[lt_date_col] or "")
        try:
            run = int(lr[lt_run_col] or 0)
        except Exception:
            run = 0
        lt_map.setdefault((rider, circ, date, run), []).append(float(ts))

    return {k: min(v) for k, v in lt_map.items()}


def join_sus_and_laptimes(ls_map: dict, lt_best: dict) -> list:
    """Join suspension map with best lap times into a list of session dicts.

    Only sessions present in both maps are included.

    Args:
        ls_map:   Output of build_lap_sus_map().
        lt_best:  Output of build_lap_time_map().

    Returns:
        List of dicts suitable for pd.DataFrame(rows).
        Columns: rider, circuit, date, run, best_s,
                 apex_susF, apex_susR, apex_spd, brk_susF, brk_susR.

    # PRODUCT-CANDIDATE: B_APEX
    """
    rows = []
    for key, best_s in lt_best.items():
        if key not in ls_map:
            continue
        ld = ls_map[key]
        rider, circ, date, run = key
        rows.append({
            "rider":    rider,
            "circuit":  circ,
            "date":     date,
            "run":      run,
            "best_s":   best_s,
            "apex_susF": ld.get("thron_susF"),   # THR_ON definition
            "apex_susR": ld.get("thron_susR"),
            "apex_whlF": None,
            "apex_whlR": None,
            "apex_spd":  ld.get("apex_spd"),
            "brk_susF":  ld.get("brk_susF"),
            "brk_susR":  ld.get("brk_susR"),
            "brk_spd":   None,
        })
    return rows
