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
    # top-speed rank (1 = fastest) and lap-vs-speed rank delta. A large positive
    # rank_delta (lap position worse than speed rank) hints at corner/sector loss
    # — NOT necessarily engine power (slipstream / gearing / traffic also count).
    if out["top_speed"].notna().any():
        out["speed_rank"] = out["top_speed"].rank(ascending=False,
                                                   method="min").astype("Int64")
    else:
        out["speed_rank"] = pd.array([pd.NA] * len(out), dtype="Int64")
    out["rank_delta"] = out["position"].astype("Int64") - out["speed_rank"]
    return out


def rider_options(cls: pd.DataFrame) -> list[str]:
    """Display labels for rider pickers, in classification order."""
    if cls.empty:
        return []
    return [_rider_label(r) for _, r in cls.iterrows()]


def _rider_label(row) -> str:
    no = row.get("rider_no")
    nm = row.get("rider_name")
    nm = nm.strip() if isinstance(nm, str) and nm.strip() else "?"   # never "nan"
    return f"#{int(no)} {nm}" if pd.notna(no) else nm


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
    sp_my, sp_ref = rider_top_speed(df, my_no), rider_top_speed(df, ref_no)
    sp_delta = (sp_my - sp_ref) if sp_my is not None and sp_ref is not None else None
    out = {"deltas": deltas, "pairs": pairs, "total": total,
           "loss_sector": loss, "gain_sector": gain,
           "diagnosis": _h2h_diagnosis(total, gain, loss),
           "speed_my": sp_my, "speed_ref": sp_ref, "speed_delta": sp_delta,
           "speed_note": None}
    out["speed_note"] = _h2h_speed_note(out)
    return out


def rider_top_speed(df: pd.DataFrame, rider_no):
    """Best speed-trap reading over the rider's flying laps (km/h), or None."""
    g = df[(df["rider_no"] == rider_no) & (df["is_flying"])]
    v = g["speed"].max() if "speed" in g else np.nan
    return None if pd.isna(v) else float(v)


def _h2h_speed_note(h: dict):
    sd = h.get("speed_delta")
    if sd is None:
        return None
    note = f"{sd:+.1f} km/h top speed"
    loss = h.get("loss_sector")
    if loss and loss[1] > 0.03:
        note += f", but {loss[1]:+.3f}s slower in {loss[0]}"
    note += "."
    if abs(sd) >= 1.0:
        note += (" Top speed reflects slipstream, corner exit, gearing and traffic "
                 "— not engine power alone.")
    return note


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


# ── 11. one-screen Session Review summary ───────────────────────────────────
def _f(v):
    """-> float or None (drops NaN)."""
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def _opt_str(v):
    """-> a non-empty string, or None. Coerces NaN / numbers / blanks to None so
    display code can safely join the result (NaN is truthy and would crash join)."""
    if isinstance(v, str):
        return v.strip() or None
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def recommend_reference(cls: pd.DataFrame, rider_no):
    """Who to compare against: the rider one place ahead in classification (the
    nearest target). If the rider is already P1, suggest P2 (the nearest threat).
    Returns a rider_no or None."""
    if cls is None or cls.empty or "position" not in cls:
        return None
    order = cls.sort_values("position")
    me = order[order["rider_no"] == rider_no]
    if me.empty or pd.isna(me["position"].iloc[0]):
        return None
    pos = int(me["position"].iloc[0])
    target = order[order["position"] == (2 if pos <= 1 else pos - 1)]
    return int(target["rider_no"].iloc[0]) if not target.empty else None


def _field_consistency_median(df: pd.DataFrame, cls: pd.DataFrame):
    stds = []
    for no in cls["rider_no"].dropna().unique():
        c = consistency_stats(df, no)
        if c.get("consistency_std") is not None:
            stds.append(c["consistency_std"])
    return float(np.median(stds)) if stds else None


def session_review(df: pd.DataFrame, cls: pd.DataFrame, rider_no,
                   ref_no=None, mode: str = "best") -> dict | None:
    """Everything needed for a one-screen review of one rider: pace vs the class,
    where they lose/gain vs the recommended reference, repeatability, and a plain
    suggested focus. Auto-picks a reference (rider one place ahead) when ref_no is
    None."""
    if cls is None or cls.empty:
        return None
    row = cls[cls["rider_no"] == rider_no]
    if row.empty:
        return None
    row = row.iloc[0]
    if ref_no is None:
        ref_no = recommend_reference(cls, rider_no)

    best, ideal = row.get("best_lap"), row.get("ideal_lap")
    class_best = cls["best_lap"].min()
    class_ideal = cls["ideal_lap"].min() if cls["ideal_lap"].notna().any() else np.nan
    leader = cls.sort_values("position").iloc[0] if "position" in cls else None
    cs = consistency_stats(df, rider_no)

    out = {
        "rider_no": int(rider_no), "rider": _rider_label(row),
        "team": _opt_str(row.get("team")), "bike": _opt_str(row.get("manufacturer")),
        "position": int(row["position"]) if pd.notna(row.get("position")) else None,
        "best_lap": _f(best), "class_best": _f(class_best),
        "class_best_rider": _rider_label(leader) if leader is not None else None,
        "best_gap": _f(best - class_best) if pd.notna(best) and pd.notna(class_best) else None,
        "ideal_lap": _f(ideal), "class_ideal": _f(class_ideal),
        "ideal_gap": _f(ideal - class_ideal) if pd.notna(ideal) and pd.notna(class_ideal) else None,
        "lost_potential": _f(row.get("lost_potential")),
        "ref_no": int(ref_no) if ref_no is not None else None, "ref": None,
        "biggest_loss": None, "biggest_gain": None, "diagnosis": None,
        "consistency_std": cs.get("consistency_std"),
        "consistency_range": cs.get("consistency_range"),
        "pace_laps": cs.get("pace_laps"), "worst_sector": cs.get("worst_sector"),
        "consistency_warning": None, "focus_text": None,
    }
    if ref_no is not None:
        ref_row = cls[cls["rider_no"] == ref_no]
        if not ref_row.empty:
            out["ref"] = _rider_label(ref_row.iloc[0])
        h = h2h_summary(df, rider_no, ref_no, mode)
        out["biggest_loss"] = h["loss_sector"]
        out["biggest_gain"] = h["gain_sector"]
        out["diagnosis"] = h["diagnosis"]

    # consistency warning: notably less repeatable than the field
    field_med = _field_consistency_median(df, cls)
    std = cs.get("consistency_std")
    if std is not None and field_med is not None and field_med > 0 \
            and std > max(field_med * 1.3, field_med + 0.08):
        ws = (cs.get("worst_sector") or "").upper()
        out["consistency_warning"] = (
            f"Less consistent than the field (±{std:.3f}s vs field ±{field_med:.3f}s)"
            + (f" — most scatter in {ws}." if ws else "."))

    out["focus_text"] = _focus_text(out)
    return out


def _lap_str(s) -> str:
    """seconds -> M'SS.mmm (display only; engine-side mirror of the UI helper)."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return "—"
    s = float(s)
    m = int(s // 60)
    return f"{m}'{s - 60 * m:06.3f}"


# ── 12. run / stint segmentation + run review ───────────────────────────────
def assign_runs(df: pd.DataFrame, rider_no, slow_break: float = 1.15) -> pd.DataFrame:
    """One rider's laps (ordered) with run_id + run_lap_index. A run is a maximal
    streak of valid/slow laps; out/pit/cancelled laps — and any flying lap slower
    than slow_break × the rider's median (an in-lap / big mistake) — are dividers
    (run_id = None) used only to split runs, not analysed."""
    g = lap_detail(df, rider_no).reset_index(drop=True)
    if g.empty:
        g["run_id"] = pd.Series(dtype="object")
        g["run_lap_index"] = pd.Series(dtype="object")
        return g
    fly = g[g["is_flying"]]
    med = fly["lap_time_s"].median() if not fly.empty else None
    rid, rli, cur, idx, in_run = [], [], 0, 0, False
    for _, r in g.iterrows():
        very_slow = (med is not None and pd.notna(r["lap_time_s"])
                     and r["lap_time_s"] > med * slow_break)
        divider = r["lap_status"] in ("out", "pit", "cancelled") or very_slow
        if divider:
            in_run = False
            rid.append(None)
            rli.append(None)
        else:
            if not in_run:
                cur += 1
                idx = 0
                in_run = True
            idx += 1
            rid.append(cur)
            rli.append(idx)
    g["run_id"] = rid
    g["run_lap_index"] = rli
    return g


def run_detail(df: pd.DataFrame, rider_no, run_id) -> dict:
    """Per-run numbers for one run: best/avg, per-sector best/avg, and the sectors
    where the rider improved most (first valid lap → best) and loses most
    (avg − best scatter)."""
    g = assign_runs(df, rider_no)
    rg = g[g["run_id"] == run_id].sort_values("run_lap_index")
    out = {"run_id": run_id, "laps": rg, "best_lap": None, "best_lap_no": None,
           "avg_valid": None, "median_valid": None, "consistency": None,
           "sector_best": {}, "sector_avg": {}, "lost_most": None,
           "improved_most": None}
    if rg.empty:
        return out
    times = rg["lap_time_s"].dropna()
    if not times.empty:
        out["best_lap"] = float(times.min())
        out["best_lap_no"] = int(rg.loc[times.idxmin(), "lap_no"])
    valid = rg[rg["lap_status"] == "valid"]
    base = valid if not valid.empty else rg
    vt = base["lap_time_s"].dropna()
    if not vt.empty:
        out["avg_valid"] = float(vt.mean())
        out["median_valid"] = float(vt.median())
        out["consistency"] = float(vt.std(ddof=0)) if len(vt) > 1 else 0.0
    first = base.iloc[0]
    gaps, improv = {}, {}
    for s in SECTORS:
        sb, sa = base[s].min(), base[s].mean()
        out["sector_best"][s] = None if pd.isna(sb) else float(sb)
        out["sector_avg"][s] = None if pd.isna(sa) else float(sa)
        if pd.notna(sb) and pd.notna(sa):
            gaps[s] = sa - sb
        if pd.notna(first[s]) and pd.notna(sb):
            improv[s] = first[s] - sb
    if gaps:
        out["lost_most"] = max(gaps, key=gaps.get)
    if improv and len(base) > 1:
        out["improved_most"] = max(improv, key=improv.get)
    return out


def _run_note(detail: dict, strongest: bool) -> str:
    bits = []
    if strongest:
        bits.append("strongest")
    if detail.get("best_lap_no"):
        bits.append(f"best L{detail['best_lap_no']}")
    if detail.get("lost_most"):
        bits.append(f"weak {detail['lost_most'].upper()}")
    if detail.get("consistency") is not None and detail["consistency"] <= 0.15:
        bits.append("consistent")
    return " · ".join(bits)


def run_summary(df: pd.DataFrame, rider_no) -> pd.DataFrame:
    """One row per run for the Run Review table."""
    g = assign_runs(df, rider_no)
    runs = g[g["run_id"].notna()]
    if runs.empty:
        return pd.DataFrame()
    rows = []
    for rid, rg in runs.groupby("run_id"):
        valid = rg[rg["lap_status"] == "valid"]
        times = rg["lap_time_s"].dropna()
        vt = valid["lap_time_s"].dropna()
        row = {
            "run_id": int(rid), "laps": int(len(rg)), "valid_laps": int(len(valid)),
            "best_lap": float(times.min()) if not times.empty else np.nan,
            "best_lap_no": int(rg.loc[times.idxmin(), "lap_no"]) if not times.empty else None,
            "avg_valid": float(vt.mean()) if not vt.empty else np.nan,
            "median_valid": float(vt.median()) if not vt.empty else np.nan,
            "consistency": (float(vt.std(ddof=0)) if len(vt) > 1
                            else (0.0 if len(vt) == 1 else np.nan)),
            "top_speed": float(rg["speed"].max()) if rg["speed"].notna().any() else np.nan,
        }
        for s in SECTORS:
            row[f"best_{s}"] = float(rg[s].min()) if rg[s].notna().any() else np.nan
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("run_id").reset_index(drop=True)
    strongest_idx = out["best_lap"].idxmin() if out["best_lap"].notna().any() else -1
    out["is_strongest"] = out.index == strongest_idx
    out["note"] = [
        _run_note(run_detail(df, rider_no, int(r["run_id"])), bool(r["is_strongest"]))
        for _, r in out.iterrows()]
    return out


def run_brief(df: pd.DataFrame, rider_no) -> str:
    """Auto engineer/rider brief across the session's runs."""
    s = run_summary(df, rider_no)
    if s.empty:
        return "No complete runs to review yet (need consecutive valid laps)."
    strong = s.loc[s["best_lap"].idxmin()] if s["best_lap"].notna().any() else s.iloc[0]
    rid = int(strong["run_id"])
    d = run_detail(df, rider_no, rid)
    out = f"Run {rid} was the strongest run"
    if pd.notna(strong.get("best_lap")):
        out += f" ({_lap_str(strong['best_lap'])})"
    out += ". "
    if d.get("best_lap_no"):
        out += f"Best lap came on lap {d['best_lap_no']}. "
    lost = d.get("lost_most")
    if lost:
        out += (f"Main loss remains {lost.upper()}. "
                f"Focus next run on {_SECTOR_HINT.get(lost.upper(), lost.upper())}.")
    else:
        out += "Pace was well balanced across the sectors."
    return out


def _focus_text(o: dict) -> str:
    """Plain next-run guidance from the review numbers."""
    loss = o.get("biggest_loss")
    bits = []
    if o.get("best_gap") and o["best_gap"] > 0.001:
        tgt = f" of {o['class_best_rider']}" if o.get("class_best_rider") else ""
        bits.append(f"{o['best_gap']:.3f}s off the class best{tgt}")
    if loss and loss[1] > 0.03:
        ref = o.get("ref") or "the reference"
        bits.append(f"biggest loss vs {ref} is in {loss[0]} ({loss[1]:+.3f}s)")
    if o.get("lost_potential") and o["lost_potential"] > 0.15:
        bits.append(f"{o['lost_potential']:.3f}s left on the table (best vs ideal)")
    if not bits:
        return "Strong, balanced session — no single obvious weakness to chase."
    text = "Focus next run: " + "; ".join(bits) + "."
    if loss and loss[1] > 0.03:
        text += f" Priority — {_SECTOR_HINT.get(loss[0], loss[0])}."
    return text


# ── top-speed analysis (read alongside lap/sector times, never alone) ────────
def sector_gaps_vs_class(df: pd.DataFrame, cls: pd.DataFrame, rider_no):
    """Per-sector gap of the rider's best sector vs the field's best of that
    sector (positive = slower than the field). Returns (gaps, worst_sectors)."""
    if cls is None or cls.empty:
        return {}, []
    row = cls[cls["rider_no"] == rider_no]
    if row.empty:
        return {}, []
    row = row.iloc[0]
    gaps = {}
    for s in SECTORS:
        cb, rb = cls[f"best_{s}"].min(), row.get(f"best_{s}")
        if pd.notna(cb) and pd.notna(rb):
            gaps[s] = float(rb - cb)
    worst = sorted([s for s in gaps if gaps[s] > 0.03], key=lambda s: -gaps[s])
    return gaps, [s.upper() for s in worst[:2]]


def top_speed_review(df: pd.DataFrame, cls: pd.DataFrame, rider_no) -> dict:
    """Top-speed context for one rider: value, gap to class best, speed rank, and
    how that rank compares to their lap-time rank — with a cautious insight."""
    out = {"top_speed": None, "class_best_speed": None, "speed_gap": None,
           "speed_rank": None, "lap_rank": None, "rank_delta": None, "insight": None}
    if cls is None or cls.empty:
        return out
    row = cls[cls["rider_no"] == rider_no]
    if row.empty:
        return out
    row = row.iloc[0]
    ts, cbest = row.get("top_speed"), cls["top_speed"].max()
    out["top_speed"] = None if pd.isna(ts) else float(ts)
    out["class_best_speed"] = None if pd.isna(cbest) else float(cbest)
    if pd.notna(ts) and pd.notna(cbest):
        out["speed_gap"] = float(ts - cbest)                 # <= 0
    out["speed_rank"] = int(row["speed_rank"]) if pd.notna(row.get("speed_rank")) else None
    out["lap_rank"] = int(row["position"]) if pd.notna(row.get("position")) else None
    if out["speed_rank"] is not None and out["lap_rank"] is not None:
        out["rank_delta"] = out["lap_rank"] - out["speed_rank"]
    out["insight"] = _speed_insight(df, cls, rider_no, out)
    return out


def _speed_insight(df, cls, rider_no, ts) -> str | None:
    sr, lr, rd = ts["speed_rank"], ts["lap_rank"], ts["rank_delta"]
    if sr is None or lr is None:
        return None
    _, worst = sector_gaps_vs_class(df, cls, rider_no)
    where = "/".join(worst) if worst else None
    cap = max(3, len(cls) // 4)
    if rd is not None and rd >= 3 and sr <= cap:
        s = f"High top speed (P{sr}) but lap time only P{lr}"
        s += f" — time is lost in {where}." if where else "."
        return s + (" Look at corner speed, lines and gearing (and slipstream / "
                    "traffic), not engine power.")
    if rd is not None and rd <= -3:
        s = f"Lap time (P{lr}) is stronger than the top-speed rank (P{sr})"
        s += f"; biggest sector loss is {where}." if where else "."
        return s + (" Carrying corner speed well; a tow or gearing can flatter "
                    "straight-line figures.")
    if where:
        return (f"Top speed P{sr}, lap time P{lr}. Biggest sector loss vs the "
                f"field is {where} — confirm against slipstream / traffic.")
    return f"Top speed P{sr}, lap time P{lr} — well matched."


def speed_profile(df: pd.DataFrame, rider_no) -> dict:
    """Best-lap speed vs the rider's max speed-trap, and whether they're the same
    lap (max speed on a non-best lap often means a tow or a lift-and-coast lap)."""
    out = {"top_speed": None, "best_lap_no": None, "best_lap_speed": None,
           "max_speed": None, "max_speed_lap_no": None, "coincide": None}
    fly = df[(df["rider_no"] == rider_no) & (df["is_flying"])]
    if fly.empty:
        return out
    sp = fly["speed"].dropna()
    if not sp.empty:
        out["max_speed"] = float(sp.max())
        out["max_speed_lap_no"] = int(fly.loc[sp.idxmax(), "lap_no"])
        out["top_speed"] = out["max_speed"]
    lt = fly["lap_time_s"].dropna()
    if not lt.empty:
        bi = lt.idxmin()
        out["best_lap_no"] = int(fly.loc[bi, "lap_no"])
        bs = fly.loc[bi, "speed"]
        out["best_lap_speed"] = None if pd.isna(bs) else float(bs)
    if out["best_lap_no"] is not None and out["max_speed_lap_no"] is not None:
        out["coincide"] = bool(out["best_lap_no"] == out["max_speed_lap_no"])
    return out
