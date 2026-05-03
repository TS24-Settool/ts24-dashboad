"""
services/data_loader.py — Framework-agnostic data loading utilities
====================================================================
No Streamlit dependency. Loads DataFrames from SQLite, Excel, or JSON.
The @st.cache_data wrappers that call these functions live in dashboard.py.

# PRODUCT-CANDIDATE: D_DATA_LOADER — This entire module.
"""

import sqlite3
from pathlib import Path

import pandas as pd


# ── Numeric coercion helpers ─────────────────────────────────────

_DYN_NUM_COLS = [
    "APEX Count", "APEX Spd (km/h)", "APEX SusF (mm)", "APEX SusR (mm)",
    "APEX WhlF (N)", "APEX WhlR (N)", "APEX ax (m/s²)",
    "Pit Count", "Pit Spd (km/h)", "Pit SusF (mm)", "Pit SusR (mm)",
    "Brk Count", "Brk Spd (km/h)", "Brk SusF (mm)", "Brk SusR (mm)",
]

_LAP_SUS_NUM_COLS = [
    "LAP_TIME_S", "APEX_CNT", "APEX_SPD_AVG", "APEX_SUSF_AVG", "APEX_SUSR_AVG",
    "BRK_CNT", "BRK_SPD_AVG", "BRK_SUSF_AVG", "BRK_SUSR_AVG",
    "FULLBRK_CNT", "FULLBRK_SUSF", "FULLBRK_SUSR",
    "LAP_SUSF_MEAN", "LAP_SUSF_MIN", "LAP_SUSF_MAX", "LAP_SUSR_MEAN",
    "RUN_NO", "LAP_NO",
]


def coerce_dynamics_numerics(df: pd.DataFrame) -> pd.DataFrame:
    """Cast DYNAMICS_ANALYSIS numeric columns; keep Date as string.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    for c in _DYN_NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)
    return df


def coerce_lap_suspension(df: pd.DataFrame) -> pd.DataFrame:
    """Upper-case columns, coerce numeric LAP_SUSPENSION cols, drop blank rows.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    df.columns = [c.upper() for c in df.columns]
    for c in _LAP_SUS_NUM_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(how="all").reset_index(drop=True)


# ── SQLite helpers ───────────────────────────────────────────────

def sql_to_df(conn: sqlite3.Connection, query: str) -> pd.DataFrame:
    """Execute a query on a SQLite connection and return a DataFrame.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    cur = conn.execute(query)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=cols)


# ── DYNAMICS_ANALYSIS + LAP_TIMES loaders ───────────────────────

def load_dynamics_from_excel(excel_path: Path) -> tuple:
    """Load DYNAMICS_ANALYSIS and LAP_TIMES sheets from the master Excel file.

    Returns:
        (df_dynamics, df_lap_times) — either may be an empty DataFrame on error.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    try:
        df_dyn = pd.read_excel(str(excel_path), sheet_name="DYNAMICS_ANALYSIS", header=1)
        df_dyn = coerce_dynamics_numerics(
            df_dyn.dropna(subset=["Rider"]).reset_index(drop=True)
        )
    except Exception:
        df_dyn = pd.DataFrame()

    try:
        df_lt = pd.read_excel(str(excel_path), sheet_name="LAP_TIMES", header=1)
        df_lt = df_lt.dropna(how="all").reset_index(drop=True)
    except Exception:
        df_lt = pd.DataFrame()

    return df_dyn, df_lt


def load_dynamics_from_json(dyn_path: Path, lt_path: Path) -> tuple:
    """Load DYNAMICS_ANALYSIS and LAP_TIMES from JSON fallback files.

    Keeps date strings as-is (convert_dates=False) so they match
    the string format used elsewhere for join operations.

    Returns:
        (df_dynamics, df_lap_times) — either may be an empty DataFrame on error.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    try:
        df_dyn = (
            pd.read_json(str(dyn_path), convert_dates=False)
            if dyn_path.exists()
            else pd.DataFrame()
        )
        if not df_dyn.empty:
            df_dyn = coerce_dynamics_numerics(df_dyn)
    except Exception:
        df_dyn = pd.DataFrame()

    try:
        df_lt = (
            pd.read_json(str(lt_path), convert_dates=False)
            if lt_path.exists()
            else pd.DataFrame()
        )
    except Exception:
        df_lt = pd.DataFrame()

    return df_dyn, df_lt


# ── LAP_SUSPENSION loaders ───────────────────────────────────────

def load_lap_suspension_from_excel(excel_path: Path) -> pd.DataFrame:
    """Load LAP_SUSPENSION sheet from master Excel.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    try:
        df = pd.read_excel(str(excel_path), sheet_name="LAP_SUSPENSION", header=1)
        return coerce_lap_suspension(df)
    except Exception:
        return pd.DataFrame()


def load_lap_suspension_from_sqlite(db_path: Path) -> pd.DataFrame:
    """Load lap_suspension table from a SQLite database.

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    try:
        conn = sqlite3.connect(str(db_path))
        df = pd.read_sql(
            "SELECT * FROM lap_suspension ORDER BY round, circuit, session, rider, run_no, lap_no",
            conn,
        )
        conn.close()
        return coerce_lap_suspension(df)
    except Exception:
        return pd.DataFrame()


def load_lap_suspension_from_json(json_path: Path) -> pd.DataFrame:
    """Load lap_suspension_data from JSON fallback (Streamlit Cloud).

    # PRODUCT-CANDIDATE: D_DATA_LOADER
    """
    try:
        df = pd.read_json(str(json_path), convert_dates=False)
        return coerce_lap_suspension(df)
    except Exception:
        return pd.DataFrame()
