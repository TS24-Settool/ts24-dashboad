"""
fetch.py — automatic data retrieval from the public mgp-timings API
(the open-source GitHub project fabricepipart/mgp-timings, hosted at
https://mgp-timings.teknichrono.fr). No manual PDF upload needed.

The /analysis endpoint returns, per lap, the same per-sector data we parse from
the official PDF, so the rest of the engine is unchanged. Covers MotoGP / Moto2
/ Moto3 from 2005 onward.

Note: this makes outbound HTTPS calls. It works wherever the app has internet
(e.g. Streamlit Cloud). Pure functions here; Streamlit caching is added by the
caller.
"""
from __future__ import annotations

import requests

from .parse_analysis_pdf import _laptime_to_s
from . import circuit_map

BASE = "https://mgp-timings.teknichrono.fr/api"

# category display label -> API path token (per project README)
CATEGORIES = [("MotoGP", "GP"), ("Moto2", "MOTO2"), ("Moto3", "MOTO3")]
# common session short codes used in the path
SESSIONS = ["FP1", "FP2", "FP3", "FP4", "PR", "P1", "P2",
            "Q1", "Q2", "WUP", "SPR", "RAC"]

_HEADERS = {"User-Agent": "TS24-MotoGP-Tool/1.0"}


def _get(url: str, timeout: int = 25):
    r = requests.get(url, headers=_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def list_events(year: int) -> list[dict]:
    """Events of a season. Each: {short_name, name, circuitName, test}."""
    data = _get(f"{BASE}/{year}")
    out = []
    for e in data if isinstance(data, list) else []:
        out.append({
            "short_name": e.get("short_name") or e.get("shortName"),
            "name": e.get("name") or e.get("sponsored_name") or "",
            "circuit": e.get("circuitName") or "",
            "test": bool(e.get("test")),
        })
    return [e for e in out if e["short_name"]]


def _sec_float(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", ".").rstrip("*"))
    except ValueError:
        return None


def analysis_to_laps(rows: list) -> list[dict]:
    """Convert mgp-timings LapAnalysis JSON -> our per-lap records."""
    laps = []
    for r in rows or []:
        secs = sorted(r.get("sectors") or [], key=lambda s: s.get("sectorNumber", 0))
        svals = [_sec_float(s.get("time")) for s in secs][:4]
        while len(svals) < 4:
            svals.append(None)
        laps.append({
            "rider_no": r.get("number"),
            "rider_name": r.get("rider"),
            "team": r.get("team"),
            "manufacturer": r.get("motorcycle"),
            "nation": r.get("nation"),
            "run_no": None,
            "front_tyre": r.get("frontTyre"),
            "rear_tyre": r.get("backTyre"),
            "lap_no": r.get("lapNumber"),
            "t1": svals[0], "t2": svals[1], "t3": svals[2], "t4": svals[3],
            "speed": r.get("maxSpeed"),
            "lap_time_s": _laptime_to_s(str(r.get("time", "")).rstrip("*")),
            "pit": bool(r.get("pit")),
            "cancelled": bool(r.get("cancelled")) or bool(r.get("unfinished")),
        })
    return laps


def fetch_session(year: int, event_short: str, cat_token: str, session: str):
    """Return (laps_records, label, circuit_slug) for one session."""
    url = f"{BASE}/{year}/{event_short}/{cat_token}/{session}/analysis"
    rows = _get(url)
    laps = analysis_to_laps(rows)
    cat_label = next((d for d, t in CATEGORIES if t == cat_token), cat_token)
    label = f"{cat_label} · {event_short} {year} · {session}"
    slug = circuit_map.detect_slug(event_short) or circuit_map.detect_slug(label)
    return laps, label, slug
