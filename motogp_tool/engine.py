"""
engine.py — MotoGP performance-analysis engine.

Turns parsed Analysis-PDF laps into the tables the UI needs:
  * a clean per-lap DataFrame (with out-lap flagging)
  * an all-riders classification (best lap + theoretical best from best sectors)
  * head-to-head sector deltas (Avg / Best / Median) between two riders
  * a microsector strip: the 4 official sectors optionally subdivided into k
    equal parts, mapped to a 0..1 track position with a signed delta per part.

All sector numbers (T1..T4) are *real* measured data from the official timing.
Microsector subdivision (k > 1) is an explicit equal-time model used only to
place colour on the track strip — it is labelled as such in the UI.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SECTORS = ["t1", "t2", "t3", "t4"]


# ── 1. normalise ────────────────────────────────────────────────────────────
def laps_to_df(parsed: dict) -> pd.DataFrame:
    """parsed = {'meta':..., 'laps':[...]} -> tidy DataFrame with is_outlap."""
    return prepare_df(pd.DataFrame(parsed.get("laps", [])))


def prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived columns (sector_sum, is_outlap, is_flying) to a raw laps
    DataFrame — works for both parsed PDFs and loaded demo CSVs."""
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    for c in SECTORS + ["lap_time_s", "speed"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("pit", "cancelled"):
        if c in df:
            df[c] = df[c].astype(str).str.lower().isin(["true", "1", "1.0"]) \
                if df[c].dtype == object else df[c].fillna(False).astype(bool)
        else:
            df[c] = False

    # sector sum (only when all four present)
    df["sector_sum"] = df[SECTORS].sum(axis=1, min_count=4)

    # A lap is a clean "flying" lap when it is not a pit/cancelled lap, has all
    # four sectors, and the lap time matches the sector sum (out-laps include
    # the rolling pit-exit time, so their lap_time >> sector_sum).
    has_all = df[SECTORS].notna().all(axis=1)
    matches = (df["sector_sum"] - df["lap_time_s"]).abs() < 0.10
    df["is_outlap"] = ~(has_all & matches & ~df["pit"].fillna(False)
                        & ~df["cancelled"].fillna(False))
    df["is_flying"] = ~df["is_outlap"]
    return df


def session_label(meta: dict) -> str:
    bits = [meta.get("category"), meta.get("event"), meta.get("session")]
    return "  ·  ".join(b for b in bits if b)


# ── 2. classification ───────────────────────────────────────────────────────
def classification(df: pd.DataFrame) -> pd.DataFrame:
    """Per-rider summary: best lap, best of each sector, theoretical best lap."""
    if df.empty:
        return df
    fly = df[df["is_flying"]]
    rows = []
    for (no, name), g in fly.groupby(["rider_no", "rider_name"], dropna=False):
        best_lap = g["lap_time_s"].min()
        best_sec = {s: g[s].min() for s in SECTORS}
        ideal = sum(v for v in best_sec.values() if pd.notna(v)) \
            if all(pd.notna(v) for v in best_sec.values()) else np.nan
        rows.append({
            "rider_no": no, "rider_name": name,
            "team": g["team"].dropna().iloc[0] if g["team"].notna().any() else None,
            "manufacturer": g["manufacturer"].dropna().iloc[0] if g["manufacturer"].notna().any() else None,
            "best_lap": best_lap,
            "ideal_lap": ideal,
            "laps": int(len(g)),
            "top_speed": g["speed"].max(),
            **{f"best_{s}": best_sec[s] for s in SECTORS},
        })
    out = pd.DataFrame(rows).sort_values("best_lap", na_position="last").reset_index(drop=True)
    if not out.empty and pd.notna(out["best_lap"].iloc[0]):
        out["gap"] = out["best_lap"] - out["best_lap"].iloc[0]
        out["position"] = np.arange(1, len(out) + 1)
    return out


def rider_options(cls: pd.DataFrame) -> list[str]:
    """Display labels for rider pickers, in classification order."""
    if cls.empty:
        return []
    return [_rider_label(r) for _, r in cls.iterrows()]


def _rider_label(row) -> str:
    no = row.get("rider_no")
    nm = row.get("rider_name") or "?"
    return f"#{int(no)} {nm}" if pd.notna(no) else str(nm)


# ── 3. representative sector times for a rider ──────────────────────────────
def rider_sectors(df: pd.DataFrame, rider_no, mode: str = "best") -> dict:
    """Representative T1..T4 for one rider across their flying laps.
    mode in {'best','avg','median'}."""
    fly = df[(df["is_flying"]) & (df["rider_no"] == rider_no)]
    agg = {"best": "min", "avg": "mean", "median": "median"}[mode]
    return {s: getattr(fly[s], agg)() if not fly.empty else np.nan for s in SECTORS}


def sector_deltas(df: pd.DataFrame, my_no, ref_no, mode: str = "best") -> list:
    """[d_T1..d_T4] = (my - ref) per official sector. NaN where unavailable."""
    mine = rider_sectors(df, my_no, mode)
    ref = rider_sectors(df, ref_no, mode)
    return [(mine[s] - ref[s]) if (pd.notna(mine[s]) and pd.notna(ref[s])) else np.nan
            for s in SECTORS]


def sector_delta_table(df: pd.DataFrame, my_no, ref_no) -> pd.DataFrame:
    """Per-sector Avg/Best/Median delta (my - ref). Negative = my rider faster."""
    rows = []
    for mode in ("best", "avg", "median"):
        mine = rider_sectors(df, my_no, mode)
        ref = rider_sectors(df, ref_no, mode)
        for s in SECTORS:
            rows.append({"sector": s.upper(), "mode": mode,
                         "mine": mine[s], "ref": ref[s],
                         "delta": (mine[s] - ref[s]) if pd.notna(mine[s]) and pd.notna(ref[s]) else np.nan})
    return pd.DataFrame(rows)


# ── 4. microsector strip ────────────────────────────────────────────────────
def microsector_strip(df: pd.DataFrame, my_no, ref_no,
                      k: int = 1, mode: str = "best") -> pd.DataFrame:
    """Build the track strip: each of the 4 official sectors split into k equal
    parts. Returns one row per microsector with x0/x1 in 0..1 track-position and
    a signed delta (my - ref). With k=1 this is pure real-sector resolution;
    k>1 spreads each sector's delta evenly across its parts (equal-time model)."""
    mine = rider_sectors(df, my_no, mode)
    ref = rider_sectors(df, ref_no, mode)
    seg = 1.0 / (4 * k)
    rows = []
    idx = 0
    for si, s in enumerate(SECTORS):
        d = (mine[s] - ref[s]) if (pd.notna(mine[s]) and pd.notna(ref[s])) else np.nan
        for j in range(k):
            rows.append({
                "ms": idx + 1,
                "sector": s.upper(),
                "part": j + 1,
                "x0": idx * seg,
                "x1": (idx + 1) * seg,
                "xc": (idx + 0.5) * seg,
                "delta": d / k if pd.notna(d) else np.nan,      # time lost in this part
                "delta_sector": d,                               # full real-sector delta
                "mine": mine[s] / k if pd.notna(mine[s]) else np.nan,
                "ref": ref[s] / k if pd.notna(ref[s]) else np.nan,
            })
            idx += 1
    return pd.DataFrame(rows)


def delta_colour(d: float, eq: float = 0.03) -> str:
    """Image-6 style colour key for a signed delta (seconds, my - ref)."""
    if pd.isna(d):
        return "#CCCCCC"
    if d < -eq:
        return "#1B9E3E"      # faster (you gain)
    if abs(d) <= eq:
        return "#9AA0A6"      # ~equal
    if d < 0.10:
        return "#F2C200"      # small loss
    if d < 0.20:
        return "#E8800A"      # bigger loss
    return "#D62728"          # biggest loss
