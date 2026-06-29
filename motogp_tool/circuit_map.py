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
    """All circuits the picker can offer: bundled geometry + image assets +
    OSM-fetchable."""
    return sorted(set(bundled_slugs()) | set(image_asset_slugs())
                  | set(CIRCUIT_COORDS))


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
    timing = None
    if raw.get("timing_points"):
        timing = {n: [v[0] * k, v[1]] for n, v in raw["timing_points"].items()}
    return {"slug": slug, "pts": P, "name": raw.get("slug", slug),
            "corners": corners, "timing": timing,
            "ordered": raw.get("ordered", True)}


def outline_from_lonlat(coords, slug: str = "custom"):
    """Build a circuit dict from a GPS lap trace (list of (lon, lat))."""
    a = np.asarray([c for c in coords if c and len(c) == 2], dtype=float)
    if len(a) < 10:
        return None
    # light decimation for very dense traces (keep ~600 pts)
    if len(a) > 800:
        a = a[:: max(1, len(a) // 600)]
    k = math.cos(math.radians(float(a[:, 1].mean())))
    P = np.column_stack([a[:, 0] * k, a[:, 1]])
    if not np.allclose(P[0], P[-1]):
        P = np.vstack([P, P[0]])
    return {"slug": slug, "pts": P, "name": slug, "corners": []}


def _lap_cumfrac(P: np.ndarray):
    seg = np.sqrt((np.diff(P, axis=0) ** 2).sum(axis=1))
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum / cum[-1]


def _proj_factor(P: np.ndarray) -> float:
    return math.cos(math.radians(float(P[:, 1].mean())))


def _point_frac(P: np.ndarray, lon: float, lat: float) -> float:
    """Lap-distance fraction of the outline vertex nearest a GPS point."""
    k = _proj_factor(P)
    q = np.array([lon * k, lat])
    j = int(np.argmin(((P - q) ** 2).sum(axis=1)))
    return float(_lap_cumfrac(P)[j])


def boundaries_from_timing(circuit: dict, fl, ip1, ip2, ip3):
    """Given the official timing GPS (FL, IP1, IP2, IP3), return
    (start_offset, [b1, b2, b3]) so S/F sits on FL and the three sector splits
    sit on IP1/IP2/IP3 — exact MotoGP 4-sector boundaries, no guessing."""
    P = circuit["pts"]
    f_fl = _point_frac(P, *fl)
    rel = [( _point_frac(P, *ip) - f_fl) % 1.0 for ip in (ip1, ip2, ip3)]
    return f_fl, sorted(rel)


_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _overpass(query: str):
    import requests
    for url in _OVERPASS:
        try:
            r = requests.get(url, params={"data": query},
                             headers={"User-Agent": "TS24-MotoGP/1.0"}, timeout=40)
            r.raise_for_status()
            return r.json()
        except Exception:
            continue
    return None


def _stitch_ways(ways, nodes):
    """Join raceway ways (which may be split into segments) into the longest
    continuous chain of node ids."""
    chains = [list(w["nodes"]) for w in ways if len(w.get("nodes", [])) > 1]
    if not chains:
        return []
    chains.sort(key=len, reverse=True)
    chain = chains.pop(0)
    changed = True
    while changed and chains:
        changed = False
        for i, c in enumerate(chains):
            if c[0] == chain[-1]:
                chain += c[1:]; chains.pop(i); changed = True; break
            if c[-1] == chain[-1]:
                chain += c[::-1][1:]; chains.pop(i); changed = True; break
            if c[-1] == chain[0]:
                chain = c[:-1] + chain; chains.pop(i); changed = True; break
            if c[0] == chain[0]:
                chain = c[::-1][:-1] + chain; chains.pop(i); changed = True; break
    return [n for n in chain if n in nodes]


def fetch_osm(slug: str):
    """Fetch a circuit outline from OpenStreetMap (Overpass) at runtime, for
    circuits without bundled geometry. Tries several mirrors and stitches split
    track segments. Requires internet (works on Streamlit Cloud)."""
    coords = CIRCUIT_COORDS.get(slug)
    if not coords:
        return None
    lat, lon = coords
    q = (f"[out:json][timeout:30];way[highway=raceway]"
         f"(around:4000,{lat},{lon});(._;>;);out;")
    data = _overpass(q)
    if not data:
        return None
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data.get("elements", [])
             if e["type"] == "node"}
    ways = [e for e in data.get("elements", []) if e["type"] == "way"
            and len(e.get("nodes", [])) > 1]
    if not ways:
        return None
    seq = _stitch_ways(ways, nodes)
    if len(seq) < 20:                       # fall back to the single longest way
        w = max(ways, key=lambda w: len(w["nodes"]))
        seq = [n for n in w["nodes"] if n in nodes]
    if len(seq) < 20:
        return None
    outline = np.array([nodes[n] for n in seq], dtype=float)
    k = math.cos(math.radians(float(outline[:, 1].mean())))
    P = np.column_stack([outline[:, 0] * k, outline[:, 1]])
    if not np.allclose(P[0], P[-1]):
        P = np.vstack([P, P[0]])
    return {"slug": slug, "pts": P, "name": slug, "corners": []}


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


def build_shape_figure(circuit: dict) -> go.Figure:
    """Draw the real circuit shape + official timing-point markers (FL/IP1/IP2/
    IP3), without sector-colouring the curve. Used for map-traced layouts whose
    point order is not racing order (so arc-length sectors aren't reliable)."""
    P = circuit["pts"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=P[:, 0], y=P[:, 1], mode="lines",
                             line=dict(color="#0078D4", width=6),
                             hoverinfo="skip", showlegend=False))
    timing = circuit.get("timing") or {}
    nice = {"FL": "S/F", "IP1": "IP1 · end T1", "IP2": "IP2 · end T2",
            "IP3": "IP3 · end T3"}
    for nm in ("FL", "IP1", "IP2", "IP3"):
        if nm in timing:
            x, y = timing[nm]
            sf = nm == "FL"
            fig.add_trace(go.Scatter(
                x=[x], y=[y], mode="markers+text",
                marker=dict(size=13 if sf else 11,
                            color="#111" if sf else "#FFFFFF",
                            symbol="square" if sf else "circle",
                            line=dict(color="#111", width=2)),
                text=[" " + nice.get(nm, nm)], textposition="middle right",
                textfont=dict(size=10, color="#111"),
                hoverinfo="text", showlegend=False))
    fig.update_yaxes(scaleanchor="x", scaleratio=1, visible=False)
    fig.update_xaxes(visible=False)
    fig.update_layout(height=440, margin=dict(l=4, r=4, t=4, b=4),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      hovermode="closest")
    return fig


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


# ── image-based Track Map assets (Sporting Maps-style background) ────────────
# A circuit may ship an image asset at circuits/<slug>/ :
#   track_map.png  · the track drawn as a background image
#   layout.json    · normalised S/F + T1..T4 labels + corners (+ optional
#                    outline_norm / sector_bounds so we can colour sector ARCS)
#   metadata.json  · provenance incl. source_url (kept for licensing review)
# Build one from bundled GPS with: python -m motogp_tool.build_circuit_assets <slug>

def load_image_asset(slug: str):
    """Return {'slug','png_path','layout','metadata'} for circuits/<slug>/ or
    None when no image asset is present."""
    if not slug:
        return None
    d = _CIRC_DIR / slug
    png, lay, meta = d / "track_map.png", d / "layout.json", d / "metadata.json"
    if not (png.exists() and lay.exists()):
        return None
    return {"slug": slug,
            "png_path": str(png),
            "layout": json.load(open(lay)),
            "metadata": json.load(open(meta)) if meta.exists() else {}}


def image_asset_slugs() -> list[str]:
    """Circuits that have image-asset files on disk (may not be vetted)."""
    if not _CIRC_DIR.exists():
        return []
    return sorted(p.name for p in _CIRC_DIR.iterdir()
                  if p.is_dir() and (p / "track_map.png").exists()
                  and (p / "layout.json").exists())


def track_map_registry() -> dict:
    """slug -> metadata for circuits whose image asset is explicitly marked ready
    (metadata 'status' in {'supported','ready'}). ONLY these render an image Track
    Map; every other circuit falls back to the sector-comparison bar. The status
    gate keeps half-finished assets (a draft outline, a wrong-orientation image)
    from ever reaching users."""
    reg = {}
    for slug in image_asset_slugs():
        a = load_image_asset(slug)
        meta = (a or {}).get("metadata", {}) or {}
        if str(meta.get("status", "")).lower() in ("supported", "ready"):
            reg[slug] = meta
    return reg


def supported_track_map_slugs() -> list[str]:
    return sorted(track_map_registry().keys())


def is_track_map_supported(slug) -> bool:
    return bool(slug) and slug in track_map_registry()


def _hex_to_rgba(h: str, a: float = 0.85) -> str:
    h = h.lstrip("#")
    if len(h) != 6:
        return f"rgba(154,160,166,{a})"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{a})"


def _fmt_d(d) -> str:
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return "—"
    return f"{d:+.3f}s"


def build_image_track_figure(asset: dict, sector_deltas, labels=None,
                             show_turns=True) -> go.Figure:
    """Render a circuit's PNG as the background and overlay S/F, corner numbers,
    and the T1..T4 sectors coloured by `sector_deltas` (my − ref). When the asset
    carries `outline_norm`+`sector_bounds` the track itself is coloured per sector
    (arcs); otherwise coloured markers are placed at the T1..T4 label positions
    (so a hand-placed real Sporting Maps image still works)."""
    from PIL import Image
    lay = asset["layout"]
    n = len(sector_deltas)
    fig = go.Figure()
    fig.add_layout_image(dict(
        source=Image.open(asset["png_path"]), xref="x", yref="y",
        x=0, y=0, sizex=1, sizey=1, xanchor="left", yanchor="top",
        sizing="stretch", layer="below"))

    on = lay.get("outline_norm")
    bounds = lay.get("sector_bounds")
    arcs_drawn = False
    if on and bounds and len(bounds) == n + 1:
        N = len(on)
        for i in range(n):
            i0, i1 = int(bounds[i] * N), min(N, int(bounds[i + 1] * N) + 1)
            seg = on[i0:i1]
            if len(seg) < 2:
                continue
            d = sector_deltas[i]
            lab = labels[i] if labels and i < len(labels) else f"T{i+1}"
            fig.add_trace(go.Scatter(
                x=[p[0] for p in seg], y=[p[1] for p in seg], mode="lines",
                line=dict(color=engine.delta_colour(d), width=9),
                name=f"{lab}: {_fmt_d(d)}", hoverinfo="name", showlegend=False))
        arcs_drawn = True

    lbls = lay.get("labels", {})
    for i in range(n):
        pos = lbls.get(f"T{i+1}")
        if not pos:
            continue
        d = sector_deltas[i]
        lab = labels[i] if labels and i < len(labels) else f"T{i+1}"
        if not arcs_drawn:                       # no arcs -> coloured sector dot
            fig.add_trace(go.Scatter(
                x=[pos["x"]], y=[pos["y"]], mode="markers",
                marker=dict(size=22, color=engine.delta_colour(d),
                            line=dict(color="#222", width=1)),
                name=f"{lab}: {_fmt_d(d)}", hoverinfo="name", showlegend=False))
        fig.add_annotation(x=pos["x"], y=pos["y"], text=f"<b>{lab}</b>",
                           showarrow=False, font=dict(size=12, color="#111"),
                           bgcolor=_hex_to_rgba(engine.delta_colour(d), 0.85),
                           bordercolor="#333", borderwidth=1)

    if show_turns and lay.get("corners"):
        cs = lay["corners"]
        fig.add_trace(go.Scatter(
            x=[c["x"] for c in cs], y=[c["y"] for c in cs], mode="markers+text",
            marker=dict(size=12, color="#FFFFFF", line=dict(color="#111", width=1)),
            text=[str(c.get("n")) for c in cs],
            textfont=dict(size=8, color="#111"), textposition="middle center",
            hoverinfo="text", showlegend=False))

    sf = lay.get("start_finish")
    if sf:
        fig.add_trace(go.Scatter(
            x=[sf["x"]], y=[sf["y"]], mode="markers+text",
            marker=dict(size=13, color="#111", symbol="square"),
            text=["S/F"], textposition="top center", hoverinfo="skip",
            showlegend=False))

    fig.update_xaxes(visible=False, range=[0, 1], constrain="domain")
    fig.update_yaxes(visible=False, range=[1, 0], scaleanchor="x", scaleratio=1)
    fig.update_layout(height=520, margin=dict(l=4, r=4, t=4, b=4),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      hovermode="closest")
    return fig


def fetch_sportingmaps(slug: str, dest=None):
    """Hook for sourcing a circuit's Track Map from Sporting Maps.

    The MotoGP page (sportingmaps.com/motorsports/motogp) is an interactive JS map
    with no public per-circuit PNG, and the layouts are a commercial product, so
    there is no clean automated download today. The working path is to render the
    asset locally from bundled GPS (build_circuit_assets.build_asset), or to drop a
    licensed track_map.png into circuits/<slug>/. The intended source URL is kept
    in each circuit's metadata.json for a future licensing review."""
    raise NotImplementedError(
        "No public Sporting Maps image endpoint. Run "
        "`python -m motogp_tool.build_circuit_assets %s` to generate the asset "
        "from bundled GPS, or add a licensed track_map.png to circuits/%s/."
        % (slug, slug))
