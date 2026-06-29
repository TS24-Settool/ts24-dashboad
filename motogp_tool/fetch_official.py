"""
fetch_official.py — fetch sessions from the OFFICIAL MotoGP timing backend
(PulseLive results API, the same source motogp.com uses), then parse the
official "Analysis" PDF with our own parser.

This is far more reliable than third-party re-parsers: PulseLive always has the
data for completed sessions, and our parser is the one that already handles the
official PDF (proven on a real race: 25 riders / 422 flying laps).

Flow:  /seasons -> /events -> /categories -> /sessions ->
       /session/{uuid}/classification  (-> files.analysis PDF URL)  -> parse

Makes outbound HTTPS calls; works wherever there is internet (Streamlit Cloud).
"""
from __future__ import annotations

import warnings

import requests

from .parse_analysis_pdf import parse_analysis_bytes
from . import engine, circuit_map

BASE = "https://api.motogp.pulselive.com/motogp/v1/results"
_H = {"User-Agent": "TS24-MotoGP/1.0"}
CLASS_ORDER = {"MotoGP": 0, "Moto2": 1, "Moto3": 2, "MotoE": 3}


def _get(url, _binary=False, **params):
    """GET (JSON or bytes) with a TLS-expired fallback for resilience."""
    try:
        r = requests.get(url, params=params or None, headers=_H, timeout=45)
    except requests.exceptions.SSLError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = requests.get(url, params=params or None, headers=_H, timeout=45,
                             verify=False)
    r.raise_for_status()
    return r.content if _binary else r.json()


def seasons():
    return _get(f"{BASE}/seasons")                         # [{id, year, current}]


def season_id(year: int):
    for s in seasons():
        if s.get("year") == year:
            return s["id"]
    return None


def events(season_uuid: str):
    evs = _get(f"{BASE}/events", seasonUuid=season_uuid)
    return evs if isinstance(evs, list) else []


def categories(event_uuid: str):
    cats = _get(f"{BASE}/categories", eventUuid=event_uuid)
    cats = cats if isinstance(cats, list) else []
    return sorted(cats, key=lambda c: CLASS_ORDER.get(_class_name(c), 9))


def _class_name(cat: dict) -> str:
    n = (cat.get("name") or "").strip()
    for k in CLASS_ORDER:
        if k.lower() in n.lower():
            return k
    return n


def sessions(event_uuid: str, category_uuid: str):
    ss = _get(f"{BASE}/sessions", eventUuid=event_uuid, categoryUuid=category_uuid)
    return ss if isinstance(ss, list) else []


def session_label(s: dict) -> str:
    t = s.get("type", "")
    n = s.get("number")
    return f"{t}{n}" if n not in (None, 0, "") else t


def analysis_pdf_url(session_uuid: str, test: bool = False):
    res = _get(f"{BASE}/session/{session_uuid}/classification",
               test=str(bool(test)).lower())
    return ((res or {}).get("files") or {}).get("analysis")


def fetch_session(year, event, category, session, event_label="", sess_label=""):
    """event/category/session are PulseLive dicts (need their 'id' + flags).
    Returns (df, label, circuit_slug)."""
    url = analysis_pdf_url(session["id"], test=bool(event.get("test")))
    if not url:
        return None, None, None
    pdf = _get(url, _binary=True)
    parsed = parse_analysis_bytes(pdf)
    df = engine.laps_to_df(parsed)
    meta = parsed["meta"]
    label = engine.session_label(meta) or \
        f"{event_label} {year} · {sess_label}".strip()
    slug = (circuit_map.detect_slug(meta.get("event"))
            or circuit_map.detect_slug(event.get("short_name"))
            or circuit_map.detect_slug(event_label))
    return df, label, slug
