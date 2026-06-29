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
    out = pd.DataFrame(rows)
    if out.empty:                       # no flying laps -> caller shows a notice
        return out
    out = out.sort_values("best_lap", na_position="last").reset_index(drop=True)
    if not out.empty and pd.notna(out["best_lap"].iloc[0]):
        out["gap"] = out["best_lap"] - out["best_lap"].iloc[0]
        out["position"] = np.arange(1, len(out) + 1)
    # lost potential = how much the rider left on the table (best − theoretical
    # ideal). ideal_gap = how their ideal lap ranks vs the fastest ideal lap.
    out["lost_potential"] = out["best_lap"] - out["ideal_lap"]
    if out["ideal_lap"].notna().any():
        out["ideal_gap"] = out["ideal_lap"] - out["ideal_lap"].min()
    else:
        out["ideal_gap"] = np.nan
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


# ── 5. session summary card ─────────────────────────────────────────────────
def session_summary(df: pd.DataFrame, meta: dict | None = None,
                    label: str | None = None) -> dict:
    """Headline numbers for the overview card. The session's theoretical *ideal
    lap* is the sum of the fastest T1..T4 set by ANYONE in the session — the best
    lap physically shown by the timing. Track temp / weather are not in the
    Analysis PDF, so they come back None and the UI hides them."""
    meta = meta or {}
    out = {
        "event": meta.get("event"), "circuit": meta.get("circuit"),
        "klass": meta.get("category"), "session": meta.get("session"),
        "label": label, "circuit_len_m": meta.get("circuit_len_m"),
        "track_temp": meta.get("track_temp"), "weather": meta.get("weather"),
        "riders": 0, "flying_laps": 0, "total_laps": 0,
        "best_lap": None, "best_lap_rider": None, "ideal_lap": None,
    }
    if df is None or df.empty:
        return out
    fly = df[df["is_flying"]]
    out["riders"] = int(df["rider_no"].nunique())
    out["total_laps"] = int(len(df))
    out["flying_laps"] = int(df["is_flying"].sum())
    if not fly.empty and pd.notna(fly["lap_time_s"].min()):
        best = fly["lap_time_s"].min()
        out["best_lap"] = float(best)
        out["best_lap_rider"] = _rider_label(fly.loc[fly["lap_time_s"].idxmin()])
    if not fly.empty and all(fly[s].notna().any() for s in SECTORS):
        out["ideal_lap"] = float(sum(fly[s].min() for s in SECTORS))
    return out


# ── 6. per-lap status (valid / slow / out / pit / cancelled) ────────────────
def lap_status_df(df: pd.DataFrame, slow_factor: float = 1.02) -> pd.DataFrame:
    """Add a `lap_status` column classifying every lap for review:
      cancelled · pit · out (out-lap / incomplete) · slow (flying but >slow_factor
      of the rider's median flying lap) · valid (on-pace flying lap)."""
    if df is None or df.empty:
        return df
    df = df.copy()
    med = df[df["is_flying"]].groupby("rider_no")["lap_time_s"].median()

    def _status(r):
        if bool(r.get("cancelled")):
            return "cancelled"
        if bool(r.get("pit")):
            return "pit"
        if not bool(r.get("is_flying")):
            return "out"
        m = med.get(r["rider_no"], np.nan)
        if pd.notna(m) and pd.notna(r["lap_time_s"]) and r["lap_time_s"] > m * slow_factor:
            return "slow"
        return "valid"

    df["lap_status"] = df.apply(_status, axis=1)
    return df


def lap_detail(df: pd.DataFrame, rider_no) -> pd.DataFrame:
    """One rider's laps, ordered, with lap_status — for the Lap Detail table."""
    g = lap_status_df(df)
    g = g[g["rider_no"] == rider_no]
    sort_cols = [c for c in ("run_no", "lap_no") if c in g.columns]
    return g.sort_values(sort_cols, na_position="last").reset_index(drop=True) \
        if sort_cols else g.reset_index(drop=True)


# ── 7. consistency / repeatability for one rider ────────────────────────────
def consistency_stats(df: pd.DataFrame, rider_no, pace_pct: float = 0.03) -> dict:
    """Stability metrics over a rider's flying laps. 'Pace laps' are flying laps
    within `pace_pct` of the rider's own best — this drops the race-start lap and
    obvious mistakes so std/range describe genuine repeatability."""
    fly = df[(df["rider_no"] == rider_no) & (df["is_flying"])]
    times = fly["lap_time_s"].dropna()
    out = {"flying": int(len(times)), "best": None, "top3_avg": None,
           "median": None, "pace_laps": 0, "consistency_std": None,
           "consistency_range": None, "sector_std": {}, "worst_sector": None}
    if times.empty:
        return out
    s = times.sort_values()
    best = float(s.iloc[0])
    out["best"] = best
    out["top3_avg"] = float(s.iloc[:3].mean())
    out["median"] = float(times.median())
    pace = fly[fly["lap_time_s"] <= best * (1 + pace_pct)]
    pt = pace["lap_time_s"].dropna()
    out["pace_laps"] = int(len(pt))
    if len(pt) >= 1:
        out["consistency_std"] = float(pt.std(ddof=0)) if len(pt) > 1 else 0.0
        out["consistency_range"] = float(pt.max() - pt.min())
    for sct in SECTORS:
        vals = pace[sct].dropna()
        out["sector_std"][sct] = (float(vals.std(ddof=0)) if len(vals) > 1
                                  else (0.0 if len(vals) == 1 else None))
    valid_std = {k: v for k, v in out["sector_std"].items() if v is not None}
    if valid_std:
        out["worst_sector"] = max(valid_std, key=valid_std.get)
    return out


# ── 8. head-to-head summary + plain-language diagnosis ──────────────────────
_SECTOR_HINT = {
    "T1": "braking & entry in sector 1 (start/finish → IP1)",
    "T2": "mid-corner speed in sector 2 (IP1 → IP2)",
    "T3": "change of direction in sector 3 (IP2 → IP3)",
    "T4": "drive & exit in sector 4 (IP3 → finish)",
}


def _h2h_diagnosis(total, gain, loss, eq: float = 0.03) -> str:
    if gain is None and loss is None:
        return "Not enough common sector data to compare these two riders."
    parts = []
    if gain is not None and gain[1] < -eq:
        parts.append(f"gains most in **{gain[0]}** ({gain[1]:+.3f}s)")
    if loss is not None and loss[1] > eq:
        parts.append(f"loses most in **{loss[0]}** ({loss[1]:+.3f}s)")
    if not parts:
        return "The two riders are within a few hundredths across all sectors."
    sent = "My rider " + ", but ".join(parts) + "."
    net = ("about even overall" if pd.isna(total) or abs(total) <= eq
           else (f"net **{abs(total):.3f}s faster**" if total < 0
                 else f"net **{abs(total):.3f}s slower**"))
    sent += f" Overall {net}."
    if loss is not None and loss[1] > eq:
        sent += f" Focus next run on {_SECTOR_HINT.get(loss[0], loss[0])}."
    return sent


def h2h_summary(df: pd.DataFrame, my_no, ref_no, mode: str = "best") -> dict:
    """Totals + biggest gain/loss sector + a one-line diagnosis for the H2H tab."""
    deltas = sector_deltas(df, my_no, ref_no, mode)          # my − ref, neg=faster
    pairs = [(f"T{i+1}", d) for i, d in enumerate(deltas)]
    valid = [(l, d) for l, d in pairs if pd.notna(d)]
    total = sum(d for _, d in valid) if valid else np.nan
    loss = max(valid, key=lambda t: t[1]) if valid else None   # most positive
    gain = min(valid, key=lambda t: t[1]) if valid else None   # most negative
    return {"deltas": deltas, "pairs": pairs, "total": total,
            "loss_sector": loss, "gain_sector": gain,
            "diagnosis": _h2h_diagnosis(total, gain, loss)}


# ── 9. track_segments — internal structure, ready for microsectors ──────────
def track_segments(df: pd.DataFrame, my_no, ref_no, mode: str = "best",
                   k: int = 1) -> list[dict]:
    """Ordered track segments with a signed delta + status, normalised to 0..1
    lap position. k=1 → the four official sectors; k>1 subdivides each into equal
    parts (equal-time model) so the same structure already supports microsectors."""
    strip = microsector_strip(df, my_no, ref_no, k=k, mode=mode)
    segs = []
    for _, r in strip.iterrows():
        d = r["delta_sector"] if k == 1 else r["delta"]
        if pd.isna(d):
            status = "n/a"
        elif d < -0.03:
            status = "faster"
        elif d > 0.03:
            status = "slower"
        else:
            status = "equal"
        segs.append({
            "index": int(r["ms"]), "sector": r["sector"], "part": int(r["part"]),
            "x0": float(r["x0"]), "x1": float(r["x1"]), "xc": float(r["xc"]),
            "delta": None if pd.isna(d) else float(d), "status": status,
        })
    return segs


# ── 10. structured outputs + export ─────────────────────────────────────────
def sector_times_table(df: pd.DataFrame) -> pd.DataFrame:
    """Per-rider best / average / median for each official sector (flying laps)."""
    if df is None or df.empty:
        return pd.DataFrame()
    fly = df[df["is_flying"]]
    rows = []
    for (no, name), g in fly.groupby(["rider_no", "rider_name"], dropna=False):
        row = {"rider_no": no, "rider_name": name}
        for s in SECTORS:
            row[f"best_{s}"] = g[s].min()
            row[f"avg_{s}"] = g[s].mean()
            row[f"med_{s}"] = g[s].median()
        rows.append(row)
    return pd.DataFrame(rows).sort_values("rider_no").reset_index(drop=True)


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe list of dicts (NaN/NaT -> None)."""
    if df is None or df.empty:
        return []
    return df.replace({np.nan: None}).to_dict(orient="records")


def build_session(df: pd.DataFrame, meta: dict | None = None,
                  label: str | None = None) -> dict:
    """The four structured tables the spec calls for, in one bundle:
    session_summary · classification · lap_detail · sector_times."""
    return {
        "session_summary": session_summary(df, meta, label),
        "classification": classification(df),
        "lap_detail": lap_status_df(df),
        "sector_times": sector_times_table(df),
    }


def export_json(df: pd.DataFrame, meta: dict | None = None,
                label: str | None = None) -> str:
    import json
    b = build_session(df, meta, label)
    payload = {
        "session_summary": b["session_summary"],
        "classification": _records(b["classification"]),
        "lap_detail": _records(b["lap_detail"]),
        "sector_times": _records(b["sector_times"]),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def export_csv(df: pd.DataFrame) -> str:
    """Flat per-lap CSV (with lap_status) — the most useful single export."""
    g = lap_status_df(df)
    if g is None or g.empty:
        return ""
    cols = ["rider_no", "rider_name", "team", "manufacturer", "nation", "run_no",
            "front_tyre", "rear_tyre", "lap_no", "lap_time_s",
            "t1", "t2", "t3", "t4", "speed", "pit", "cancelled",
            "is_flying", "lap_status"]
    cols = [c for c in cols if c in g.columns]
    return g[cols].to_csv(index=False)
