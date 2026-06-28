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
    return {"slug": slug, "pts": P, "name": raw.get("slug", slug)}


def _sector_index_ranges(P: np.ndarray, n: int = 4):
    """Split the closed lap polyline into n contiguous index ranges of equal
    track distance. Returns list of index arrays (sharing boundary vertices)."""
    seg = np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    bounds = [total * i / n for i in range(n + 1)]
    ranges = []
    for i in range(n):
        lo, hi = bounds[i], bounds[i + 1]
        idx = np.where((cum >= lo) & (cum <= hi))[0]
        if len(idx) < 2:                                      # guarantee a drawable segment
            j = int(np.argmin(np.abs(cum - (lo + hi) / 2)))
            idx = np.array([max(0, j - 1), j])
        ranges.append(idx)
    return ranges


def build_track_figure(circuit: dict, sector_deltas, labels=None) -> go.Figure:
    """sector_deltas = [d_T1..d_T4] (my - ref, seconds). Colour the real layout."""
    P = circuit["pts"]
    ranges = _sector_index_ranges(P, len(sector_deltas))
    fig = go.Figure()
    # faint full outline underneath
    fig.add_trace(go.Scatter(x=P[:, 0], y=P[:, 1], mode="lines",
                             line=dict(color="#E5E7EB", width=11),
                             hoverinfo="skip", showlegend=False))
    for i, idx in enumerate(ranges):
        seg = P[idx]
        d = sector_deltas[i]
        lab = (labels[i] if labels else f"T{i+1}")
        txt = f"{lab}: {'—' if d is None or (isinstance(d,float) and math.isnan(d)) else f'{d:+.3f}s'}"
        fig.add_trace(go.Scatter(
            x=seg[:, 0], y=seg[:, 1], mode="lines",
            line=dict(color=engine.delta_colour(d), width=7),
            name=txt, hoverinfo="name", showlegend=False))
        # sector label at its midpoint
        mid = seg[len(seg) // 2]
        fig.add_annotation(x=mid[0], y=mid[1], text=lab, showarrow=False,
                           font=dict(size=11, color="#111", family="Arial"),
                           bgcolor="rgba(255,255,255,0.6)")
    # start/finish marker
    fig.add_trace(go.Scatter(x=[P[0, 0]], y=[P[0, 1]], mode="markers+text",
                             marker=dict(size=11, color="#111", symbol="square"),
                             text=["S/F"], textposition="top center",
                             hoverinfo="skip", showlegend=False))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, visible=False)
    fig.update_xaxes(visible=False)
    fig.update_layout(height=430, margin=dict(l=4, r=4, t=4, b=4),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      hovermode="closest")
    return fig
