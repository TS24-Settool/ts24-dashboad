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

import warnings

import requests

from .parse_analysis_pdf import _laptime_to_s
from . import circuit_map

BASE = "https://mgp-timings.teknichrono.fr/api"

# category display label -> API path token. The live API uses lowercase
# 'motogp'/'moto2'/'moto3' (verified against the project's integration tests).
CATEGORIES = [("MotoGP", "motogp"), ("Moto2", "moto2"), ("Moto3", "moto3")]
# common session short codes used in the path (case-insensitive on the server)
SESSIONS = ["FP1", "FP2", "FP3", "FP4", "PR", "P1", "P2",
            "Q1", "Q2", "WUP", "SPR", "RAC"]

_HEADERS = {"User-Agent": "TS24-MotoGP-Tool/1.0"}


def _get(url: str, timeout: int = 25):
    """GET JSON. The public mgp-timings instance has, at times, shipped an
    expired TLS certificate; since this is a public, read-only data source we
    verify normally first and fall back to unverified ONLY on a TLS error."""
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout)
    except requests.exceptions.SSLError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = requests.get(url, headers=_HEADERS, timeout=timeout, verify=False)
    r.raise_for_status()
    return r.json()


def list_events(year: int) -> list[dict]:
    """Events of a season. The season response is an object with `races` and
    `tests` arrays. Each event: {short_name, name, circuit, test}."""
    data = _get(f"{BASE}/{year}")
    if isinstance(data, dict):
        items = [(e, False) for e in (data.get("races") or [])] + \
                [(e, True) for e in (data.get("tests") or [])]
    elif isinstance(data, list):
        items = [(e, bool(e.get("test"))) for e in data]
    else:
        items = []
    out = []
    for e, is_test in items:
        sn = e.get("short_name") or e.get("shortName")
        if not sn:
            continue
        out.append({
            "short_name": sn,
            "name": e.get("name") or e.get("sponsored_name") or "",
            "circuit": e.get("circuitName") or e.get("circuit") or "",
            "test": is_test,
        })
    return out


def _sec_float(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", ".").rstrip("*"))
    except ValueError:
        return None


def analysis_to_laps(rows) -> list[dict]:
    """Convert mgp-timings analysis JSON -> our per-lap records. The endpoint
    returns {"analysis": [ ...laps... ]}; also tolerate a bare list."""
    if isinstance(rows, dict):
        rows = rows.get("analysis") or rows.get("laps") or []
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
