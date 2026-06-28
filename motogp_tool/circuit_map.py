"""
circuit_map.py — render the delta heat on the REAL circuit layout.

Geometry comes from the open track-atlas project (per-circuit GeoJSON outline +
start/finish), bundled under motogp_tool/circuits/. We project lon/lat to a
local equal-aspect plane, orient the lap at start/finish, split the lap into the
4 OFFICIAL sectors by track distance, and colour each by the rider's delta.

Honesty note: MotoGP's free data has only 4 real sector times, and the exact
on-track position of each intermediate is not published — so sector *boundaries*
here are placed by equal track distance (approximate). The *colour* of each
sector is real timing data. Sub-sector ("microsector") colouring is intentionally
NOT done, because there is no finer measurement to base it on.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

from . import engine

_CIRC_DIR = Path(__file__).parent / "circuits"

# Every MotoGP circuit -> (lat, lon) of the venue. Used to fetch the track
# outline from OpenStreetMap (Overpass) at runtime when no geometry is bundled.
CIRCUIT_COORDS = {
    "losail": (25.490, 51.453), "mugello": (43.997, 11.371),
    "portimao": (37.231, -8.627), "barcelona": (41.570, 2.261),
    "circuit-of-the-americas": (30.134, -97.641), "red-bull-ring": (47.223, 14.764),
    "silverstone": (52.071, -1.015), "jerez": (36.708, -6.033),
    "assen": (52.961, 6.524), "sachsenring": (50.791, 12.690),
    "misano": (43.961, 12.684), "aragon": (41.082, -0.210),
    "le-mans": (47.956, 0.207), "mandalika": (-8.905, 116.305),
    "termas": (-27.521, -64.916), "motegi": (36.534, 140.227),
    "buriram": (14.957, 103.088), "phillip-island": (-38.502, 145.234),
    "sepang": (2.760, 101.738), "valencia": (39.488, -0.628),
    "balaton": (46.880, 17.700), "sokol": (43.060, 76.920),
    "brno": (49.203, 16.451), "buddh": (28.350, 77.535),
}

# event-name / country-code keyword -> circuit slug
_EVENT_SLUG = {
    "QATAR": "losail", "LOSAIL": "losail", "DOHA": "losail", "QAT": "losail",
    "ITALIAN": "mugello", "ITALY": "mugello", "MUGELLO": "mugello", "ITA": "mugello",
    "PORTUG": "portimao", "PORTIM": "portimao", "ALGARVE": "portimao", "POR": "portimao",
    "CATALU": "barcelona", "BARCELONA": "barcelona", "CAT": "barcelona",
    "AMERICA": "circuit-of-the-americas", "AUSTIN": "circuit-of-the-americas", "AME": "circuit-of-the-americas",
    "AUSTRIA": "red-bull-ring", "STYRIA": "red-bull-ring", "RED BULL": "red-bull-ring", "AUT": "red-bull-ring",
    "BRITISH": "silverstone", "SILVERSTONE": "silverstone", "GREAT BRITAIN": "silverstone", "GBR": "silverstone",
    "JEREZ": "jerez", "SPANISH": "jerez", "SPAIN": "jerez", "SPA": "jerez",
    "DUTCH": "assen", "ASSEN": "assen", "NETHERLAND": "assen", "NED": "assen", "NLD": "assen",
    "GERMAN": "sachsenring", "SACHSEN": "sachsenring", "GER": "sachsenring", "DEU": "sachsenring",
    "MISANO": "misano", "MARINO": "misano", "EMILIA": "misano", "RSM": "misano", "SMR": "misano", "EMI": "misano",
    "ARAGON": "aragon", "ARA": "aragon", "TERUEL": "aragon",
    "FRENCH": "le-mans", "LE MANS": "le-mans", "FRANCE": "le-mans", "FRA": "le-mans",
    "INDONESIA": "mandalika", "MANDALIKA": "mandalika", "IDN": "mandalika", "INA": "mandalika",
    "ARGENTIN": "termas", "TERMAS": "termas", "ARG": "termas",
    "JAPAN": "motegi", "MOTEGI": "motegi", "JPN": "motegi",
    "THAI": "buriram", "BURIRAM": "buriram", "CHANG": "buriram", "THA": "buriram",
    "AUSTRALIA": "phillip-island", "PHILLIP": "phillip-island", "AUS": "phillip-island",
    "MALAYSIA": "sepang", "SEPANG": "sepang", "MYS": "sepang", "MAL": "sepang",
    "VALENCIA": "valencia", "RICARDO TORMO": "valencia", "VAL": "valencia", "CForVALENCIANA": "valencia",
    "BALATON": "balaton", "HUNGAR": "balaton", "HUN": "balaton",
    "KAZAKH": "sokol", "SOKOL": "sokol", "KAZ": "sokol",
    "BRNO": "brno", "CZECH": "brno", "CZE": "brno",
    "INDIA": "buddh", "BUDDH": "buddh", "IND": "buddh",
}


def detect_slug(event_or_circuit: str | None) -> str | None:
    ev = (event_or_circuit or "").upper()
    # longest keywords first so "RED BULL" beats stray short codes
    for kw in sorted(_EVENT_SLUG, key=len, reverse=True):
        if kw in ev:
            return _EVENT_SLUG[kw]
    return None


def bundled_slugs() -> list[str]:
    return sorted(p.stem for p in _CIRC_DIR.glob("*.json")) if _CIRC_DIR.exists() else []


def available_slugs() -> list[str]:
    """All circuits the picker can offer: bundled geometry + OSM-fetchable."""
    return sorted(set(bundled_slugs()) | set(CIRCUIT_COORDS))


def load_circuit(slug: str):
    """Return {'slug','pts'(Nx2 projected, lap-ordered, closed)} or None."""
    p = _CIRC_DIR / f"{slug}.json"
    if not p.exists():
        return None
    raw = json.load(open(p))
    outline = np.asarray(raw["outline"], dtype=float)        # [N,2] lon,lat
    if len(outline) < 8:
        return None
    lat0 = float(outline[:, 1].mean())
    k = math.cos(math.radians(lat0))
    P = np.column_stack([outline[:, 0] * k, outline[:, 1]])  # projected

    sf = raw.get("start_finish")
    if sf:
        sf = np.asarray(sf, dtype=float)
        ll = sf.mean(axis=0) if sf.ndim == 2 else sf      # Point or LineString
        sfp = np.array([ll[0] * k, ll[1]])
        start = int(np.argmin(((P - sfp) ** 2).sum(axis=1)))
        P = np.roll(P, -start, axis=0)
    if not np.allclose(P[0], P[-1]):
        P = np.vstack([P, P[0]])                              # close the loop

    corners = []
    for c in raw.get("corners", []):
        lo = c.get("lonlat")
        if lo:
            corners.append({"n": c.get("n"), "frac": c.get("frac"),
                            "xy": [lo[0] * k, lo[1]]})
    return {"slug": slug, "pts": P, "name": raw.get("slug", slug),
            "corners": corners}


def _lap_cumfrac(P: np.ndarray):
    seg = np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum / cum[-1]


def _sector_index_ranges(P: np.ndarray, bounds):
    """Split the closed lap polyline at the given internal boundary fractions
    (e.g. [0.25, 0.5, 0.75]) -> len(bounds)+1 contiguous index ranges."""
    cf = _lap_cumfrac(P)
    edges = [0.0] + sorted(float(b) for b in bounds) + [1.0]
    ranges = []
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        idx = np.where((cf >= lo) & (cf <= hi))[0]
        if len(idx) < 2:
            j = int(np.argmin(np.abs(cf - (lo + hi) / 2)))
            idx = np.array([max(0, j - 1), j])
        ranges.append(idx)
    return ranges


def _roll_start(P: np.ndarray, start_offset: float) -> np.ndarray:
    """Rotate the closed lap so the start/finish moves by `start_offset` of the
    lap distance (corners are absolute, so they stay put)."""
    if not start_offset:
        return P
    cf = _lap_cumfrac(P)
    j = int(np.argmin(np.abs(cf - (start_offset % 1.0))))
    Q = P[:-1] if np.allclose(P[0], P[-1]) else P
    Q = np.roll(Q, -j, axis=0)
    return np.vstack([Q, Q[0]])


def build_track_figure(circuit: dict, sector_deltas, bounds=None,
                       labels=None, show_turns=True, start_offset=0.0) -> go.Figure:
    """Colour the real layout by sector. `bounds` = internal boundary fractions
    (len = len(sector_deltas)-1); defaults to equal split. `start_offset` rotates
    where the S/F / lap start sits (fraction of lap distance)."""
    P = _roll_start(circuit["pts"], start_offset)
    n = len(sector_deltas)
    if not bounds:
        bounds = [i / n for i in range(1, n)]
    ranges = _sector_index_ranges(P, bounds)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=P[:, 0], y=P[:, 1], mode="lines",
                             line=dict(color="#E5E7EB", width=12),
                             hoverinfo="skip", showlegend=False))
    for i, idx in enumerate(ranges):
        seg = P[idx]
        d = sector_deltas[i] if i < len(sector_deltas) else float("nan")
        lab = (labels[i] if labels and i < len(labels) else f"T{i+1}")
        txt = f"{lab}: {'—' if d is None or (isinstance(d,float) and math.isnan(d)) else f'{d:+.3f}s'}"
        fig.add_trace(go.Scatter(
            x=seg[:, 0], y=seg[:, 1], mode="lines",
            line=dict(color=engine.delta_colour(d), width=7),
            name=txt, hoverinfo="name", showlegend=False))
        mid = seg[len(seg) // 2]
        fig.add_annotation(x=mid[0], y=mid[1], text=lab, showarrow=False,
                           font=dict(size=12, color="#111", family="Arial"),
                           bgcolor="rgba(255,255,255,0.7)")
    # turn-number markers (guides for placing boundaries)
    if show_turns and circuit.get("corners"):
        cx = [c["xy"][0] for c in circuit["corners"]]
        cy = [c["xy"][1] for c in circuit["corners"]]
        ct = [str(c["n"]) for c in circuit["corners"]]
        fig.add_trace(go.Scatter(x=cx, y=cy, mode="markers+text",
                                 marker=dict(size=13, color="#FFFFFF",
                                             line=dict(color="#111", width=1)),
                                 text=ct, textfont=dict(size=8, color="#111"),
                                 textposition="middle center",
                                 hoverinfo="text", showlegend=False))
    # sector-boundary markers on track
    cf = _lap_cumfrac(P)
    for b in bounds:
        j = int(np.argmin(np.abs(cf - b)))
        fig.add_trace(go.Scatter(x=[P[j, 0]], y=[P[j, 1]], mode="markers",
                                 marker=dict(size=10, color="#111", symbol="line-ns",
                                             line=dict(width=3, color="#111")),
                                 hoverinfo="skip", showlegend=False))
    # start/finish marker
    fig.add_trace(go.Scatter(x=[P[0, 0]], y=[P[0, 1]], mode="markers+text",
                             marker=dict(size=12, color="#111", symbol="square"),
                             text=["S/F"], textposition="top center",
                             hoverinfo="skip", showlegend=False))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, visible=False)
    fig.update_xaxes(visible=False)
    fig.update_layout(height=460, margin=dict(l=4, r=4, t=4, b=4),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      hovermode="closest")
    return fig
