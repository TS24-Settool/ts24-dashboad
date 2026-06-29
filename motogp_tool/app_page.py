"""
app_page.py — the "MotoGP Performance Analysis" Streamlit page.

Mobile-friendly. Reads an official MotoGP "Analysis" PDF (uploaded by the user,
or a bundled demo session), then lets you:
  * see the all-riders classification (best lap + best sectors + ideal lap)
  * compare any rider head-to-head vs a reference rider, per sector
  * see WHERE on the lap time is lost via a colour-coded microsector track strip

Entry point: render_motogp_page()
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from . import engine
from . import circuit_map
from . import fetch_official
from .parse_analysis_pdf import parse_analysis_bytes

_DATA_DIR = Path(__file__).parent / "data"


# ── small helpers ───────────────────────────────────────────────────────────
def _fmt_lap(s):
    if pd.isna(s):
        return "—"
    m = int(s // 60)
    return f"{m}'{s - 60*m:06.3f}" if m else f"{s:.3f}"


def _fmt_delta(d):
    return "—" if pd.isna(d) else f"{d:+.3f}"


@st.cache_data(show_spinner=False)
def _parse_pdf_cached(data: bytes):
    parsed = parse_analysis_bytes(data)
    df = engine.laps_to_df(parsed)
    meta = parsed["meta"]
    slug = circuit_map.detect_slug(meta.get("event")) or circuit_map.detect_slug(meta.get("session"))
    return df, engine.session_label(meta), slug


@st.cache_data(show_spinner=False)
def _load_demo(name: str):
    df = pd.read_csv(_DATA_DIR / name)
    return engine.prepare_df(df)


@st.cache_data(show_spinner=False, ttl=3600)
def _of_events(year: int):
    sid = fetch_official.season_id(year)
    return (sid, fetch_official.events(sid)) if sid else (None, [])


@st.cache_data(show_spinner=False, ttl=3600)
def _of_categories(event_uuid: str):
    return fetch_official.categories(event_uuid)


@st.cache_data(show_spinner=False, ttl=3600)
def _of_sessions(event_uuid: str, category_uuid: str):
    return fetch_official.sessions(event_uuid, category_uuid)


@st.cache_data(show_spinner="Fetching official session…", ttl=1800)
def _of_fetch(ev_uuid, ev_test, ev_short, ses_uuid, year, ev_label, ses_label):
    event = {"id": ev_uuid, "test": ev_test, "short_name": ev_short}
    return fetch_official.fetch_session(year, event, None, {"id": ses_uuid},
                                        ev_label, ses_label)


def _rider_no_from_label(cls: pd.DataFrame, label: str):
    row = cls[cls.apply(lambda r: engine._rider_label(r) == label, axis=1)]
    return row["rider_no"].iloc[0] if not row.empty else None


# ── main entry ──────────────────────────────────────────────────────────────
def render_motogp_page():
    st.markdown('<p class="section-title">🏍 MotoGP Performance Analysis</p>',
                unsafe_allow_html=True)
    st.caption("Official timing → every rider · every lap · every sector. "
               "Upload a session's **Analysis PDF** (motogp.com → Results → Analysis) "
               "or open the demo.")

    df, label = _data_source()
    if df is None or df.empty:
        st.info("⬆️ Upload an **Analysis** PDF (MotoGP / Moto2 / Moto3) or tap "
                "**Open demo session** to explore.")
        return

    st.success(f"**{label}**  —  {df['rider_no'].nunique()} riders · "
               f"{int(df['is_flying'].sum())} flying laps")

    cls = engine.classification(df)
    if cls.empty:
        st.warning("No valid laps for this session. The source may not have it "
                   "yet (very recent / not-yet-published events are often empty). "
                   "Try an earlier **Year** (e.g. 2025 or 2024), a different "
                   "**Session**, or the **MotoGP** class — or upload the official "
                   "Analysis PDF directly.")
        return

    tab_cls, tab_h2h, tab_map, tab_lap = st.tabs(
        ["🏁 Classification", "⚔️ Head-to-Head", "🗺️ Track Map", "📊 Lap Detail"])

    with tab_cls:
        _tab_classification(cls)
    with tab_h2h:
        _tab_head_to_head(df, cls)
    with tab_map:
        _tab_track_map(df, cls)
    with tab_lap:
        _tab_lap_detail(df, cls)


# ── data source (upload / demo) ─────────────────────────────────────────────
def _data_source():
    up = st.file_uploader("Analysis PDF", type=["pdf"], label_visibility="collapsed")
    c1, c2 = st.columns(2)
    demo = c1.button("▶︎ Open demo session", use_container_width=True)
    if c2.button("✖︎ Clear", use_container_width=True):
        st.session_state.pop("mgp_df", None)
        st.session_state.pop("mgp_label", None)
        st.rerun()

    if up is not None:
        try:
            df, label, slug = _parse_pdf_cached(up.getvalue())
            st.session_state["mgp_df"] = df
            st.session_state["mgp_label"] = label
            st.session_state["mgp_circuit"] = slug
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not parse this PDF: {e}")
            st.caption("Make sure it is the **Analysis / Chronological Analysis "
                       "of Performances** PDF (not the Classification PDF).")

    if demo:
        try:
            df = _load_demo("demo_qatar_motogp_fp1.csv")
            st.session_state["mgp_df"] = df
            st.session_state["mgp_label"] = "DEMO · MotoGP · Qatar · Free Practice 1"
            st.session_state["mgp_circuit"] = "losail"
        except Exception as e:  # noqa: BLE001
            st.error(f"Demo unavailable: {e}")

    _online_fetch_ui()
    return st.session_state.get("mgp_df"), st.session_state.get("mgp_label", "")


def _online_fetch_ui():
    """Fetch a session from the OFFICIAL MotoGP timing backend (PulseLive) and
    parse its official Analysis PDF. Reliable for any completed session."""
    with st.expander("🌐 Fetch online — official MotoGP / Moto2 / Moto3 timing"):
        year = st.selectbox("Year", list(range(2026, 2004, -1)), key="of_year")
        try:
            _, evs = _of_events(year)
        except Exception as e:  # noqa: BLE001
            st.caption(f"Official timing API unreachable ({e}).")
            return
        if not evs:
            st.caption("No events found for this year.")
            return
        evl = [f"{e.get('short_name') or '?'} — {e.get('name') or ''}"
               + (" (TEST)" if e.get("test") else "") for e in evs]
        ei = st.selectbox("Event", range(len(evs)), format_func=lambda i: evl[i],
                          key="of_ev")
        ev = evs[ei]
        try:
            cats = _of_categories(ev["id"])
        except Exception as e:  # noqa: BLE001
            st.caption(f"Could not list classes ({e}).")
            return
        if not cats:
            st.caption("No classes for this event yet.")
            return
        cl = [c.get("name", "?") for c in cats]
        ci = st.selectbox("Class", range(len(cats)), format_func=lambda i: cl[i],
                          key="of_cls")
        cat = cats[ci]
        try:
            sess = _of_sessions(ev["id"], cat["id"])
        except Exception as e:  # noqa: BLE001
            st.caption(f"Could not list sessions ({e}).")
            return
        if not sess:
            st.caption("No sessions for this class yet.")
            return
        sl = [fetch_official.session_label(s) for s in sess]
        si = st.selectbox("Session", range(len(sess)), format_func=lambda i: sl[i],
                          key="of_ses")
        if st.button("⬇️ Fetch session", use_container_width=True, key="of_go",
                     type="primary"):
            try:
                df, label, slug = _of_fetch(ev["id"], bool(ev.get("test")),
                                            ev.get("short_name") or "",
                                            sess[si]["id"], year, evl[ei], sl[si])
                if df is None or df.empty:
                    st.warning("No Analysis PDF for this session yet (very recent "
                               "events publish a few hours after the session).")
                else:
                    st.session_state["mgp_df"] = df
                    st.session_state["mgp_label"] = label
                    st.session_state["mgp_circuit"] = slug
                    st.rerun()
            except Exception as e:  # noqa: BLE001
                st.error(f"Fetch failed: {e}")


# ── tab: classification ─────────────────────────────────────────────────────
def _tab_classification(cls: pd.DataFrame):
    show = pd.DataFrame({
        "Pos": cls.get("position"),
        "No": cls["rider_no"],
        "Rider": cls["rider_name"],
        "Bike": cls.get("manufacturer"),
        "Best Lap": cls["best_lap"].map(_fmt_lap),
        "Gap": cls.get("gap", pd.Series([np.nan] * len(cls))).map(
            lambda d: "" if pd.isna(d) or d == 0 else f"+{d:.3f}"),
        "Ideal": cls["ideal_lap"].map(_fmt_lap),
        "T1": cls["best_t1"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T2": cls["best_t2"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T3": cls["best_t3"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T4": cls["best_t4"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "Top kph": cls["top_speed"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
        "Laps": cls["laps"],
    })
    st.dataframe(show, hide_index=True, use_container_width=True)
    st.caption("**Ideal** = sum of each rider's best T1–T4 (theoretical best lap). "
               "Green/red sector colours appear in Head-to-Head & Track Map.")


# ── tab: head-to-head ───────────────────────────────────────────────────────
def _rider_pickers(cls: pd.DataFrame, key: str):
    opts = engine.rider_options(cls)
    c1, c2 = st.columns(2)
    my = c1.selectbox("My rider", opts, index=0, key=f"{key}_my")
    ref_default = 1 if len(opts) > 1 else 0
    ref = c2.selectbox("Reference (compare vs)", opts, index=ref_default, key=f"{key}_ref")
    mode = st.radio("Basis", ["best", "avg", "median"], horizontal=True, key=f"{key}_mode")
    return _rider_no_from_label(cls, my), _rider_no_from_label(cls, ref), mode, my, ref


def _tab_head_to_head(df, cls):
    my_no, ref_no, mode, my_lbl, ref_lbl = _rider_pickers(cls, "h2h")
    if my_no is None or ref_no is None:
        return
    tbl = engine.sector_delta_table(df, my_no, ref_no)
    sub = tbl[tbl["mode"] == mode].reset_index(drop=True)
    total = sub["delta"].sum(skipna=True)

    st.markdown(f"**{my_lbl}**  vs  **{ref_lbl}**  ·  basis: *{mode}*")
    m1, m2 = st.columns(2)
    m1.metric("Σ sector delta", f"{total:+.3f} s",
              help="Sum of the four sector deltas (my rider − reference).")
    m2.metric("Verdict", "faster ▲" if total < 0 else ("equal" if abs(total) < 0.03 else "slower ▼"))

    # coloured sector bar chart
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=sub["sector"], y=sub["delta"],
        marker_color=[engine.delta_colour(d) for d in sub["delta"]],
        text=[_fmt_delta(d) for d in sub["delta"]], textposition="outside",
    ))
    fig.add_hline(y=0, line_width=1.5, line_dash="dot", line_color="#666")
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Δ time vs ref (s)  ·  negative = faster",
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        font=dict(family="Arial", color="#111"),
    )
    fig.update_yaxes(autorange="reversed", gridcolor="#E5E7EB", zeroline=False)
    st.plotly_chart(fig, use_container_width=True)

    disp = pd.DataFrame({
        "Sector": sub["sector"],
        f"{my_lbl}": sub["mine"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        f"{ref_lbl}": sub["ref"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "Δ": sub["delta"].map(_fmt_delta),
    })
    st.dataframe(disp, hide_index=True, use_container_width=True)


# ── tab: track map (microsector strip) ──────────────────────────────────────
def _tab_track_map(df, cls):
    my_no, ref_no, mode, my_lbl, ref_lbl = _rider_pickers(cls, "map")
    if my_no is None or ref_no is None:
        return
    deltas = engine.sector_deltas(df, my_no, ref_no, mode)      # 4 REAL sectors
    labels = ["T1", "T2", "T3", "T4"]

    st.markdown(f"Where **{my_lbl}** gains / loses vs **{ref_lbl}**  ·  "
                f"4 official sectors  ·  basis *{mode}*")

    # pick circuit geometry: auto from session, else let the user choose
    slug = st.session_state.get("mgp_circuit")
    avail = circuit_map.available_slugs()
    sel = st.selectbox("Circuit layout", ["(auto)"] + avail,
                       index=(["(auto)"] + avail).index(slug) if slug in avail else 0)
    use_slug = slug if sel == "(auto)" else sel

    _gps_trace_ui(use_slug)                       # upload GPS trace -> real layout
    circ = st.session_state.get(f"trace_{use_slug}") or _resolve_circuit(use_slug)
    if circ is not None and not circ.get("ordered", True):
        # map-traced layout: show the real shape + official timing markers, and
        # the exact per-sector deltas as a strip (the curve can't be reliably
        # sector-coloured because a traced outline isn't in racing order).
        st.plotly_chart(circuit_map.build_shape_figure(circ), use_container_width=True)
        st.caption(f"Real **{use_slug}** shape with the official timing points "
                   "(FL/IP1/IP2/IP3) from the Timekeeping Plan. Per-sector deltas "
                   "below. For a sector-coloured curve, upload a **GPS lap trace** "
                   "above (a GPS lap is in racing order).")
        _sector_strip(deltas, labels)
    elif circ is not None:
        _timing_plan_ui(use_slug, circ)          # upload plan -> exact boundaries
        bounds, sf_off = _sector_boundary_ui(use_slug)
        fig = circuit_map.build_track_figure(circ, deltas, bounds=bounds,
                                             labels=labels, start_offset=sf_off)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"**{use_slug}** layout. Colour = real timing delta per sector. "
                   "For **exact** splits, upload the official Timekeeping Points "
                   "Plan above; or set S/F + boundaries by hand below.")
    else:
        _sector_strip(deltas, labels)
        st.caption("No layout available yet — upload a GPS lap trace above to draw "
                   "the real circuit, or the analysis above is fully usable as a "
                   "strip.")

    _colour_legend()
    valid = [(l, d) for l, d in zip(labels, deltas) if d == d]  # drop NaN
    if valid:
        worst = max(valid, key=lambda t: t[1])
        if worst[1] > 0.03:
            st.warning(f"Biggest loss: **{worst[0]}** → {_fmt_delta(worst[1])}s")


@st.cache_data(show_spinner="Fetching circuit layout…", ttl=86400)
def _osm_circuit_cached(slug):
    return circuit_map.fetch_osm(slug)


def _resolve_circuit(slug):
    """Bundled geometry first; else fetch from OpenStreetMap (works on Cloud)."""
    if not slug:
        return None
    c = circuit_map.load_circuit(slug)
    if c is not None:
        return c
    try:
        return _osm_circuit_cached(slug)
    except Exception:
        return None


def _stitch_linestrings(lines):
    """Join OSM/GeoJSON LineStrings into one continuous path of (lon,lat)."""
    lines = [list(l) for l in lines if l and len(l) >= 2]
    if not lines:
        return []
    lines.sort(key=len, reverse=True)
    chain = lines.pop(0)
    tol = 3e-4 ** 2  # ~30m
    d2 = lambda a, b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
    changed = True
    while changed and lines:
        changed = False
        for i, l in enumerate(lines):
            if d2(chain[-1], l[0]) <= tol:
                chain += l[1:]; lines.pop(i); changed = True; break
            if d2(chain[-1], l[-1]) <= tol:
                chain += l[::-1][1:]; lines.pop(i); changed = True; break
            if d2(chain[0], l[-1]) <= tol:
                chain = l[:-1] + chain; lines.pop(i); changed = True; break
            if d2(chain[0], l[0]) <= tol:
                chain = l[::-1][:-1] + chain; lines.pop(i); changed = True; break
    return chain


def _parse_gps_trace(up):
    """Extract (lon, lat) points from a GPX, CSV, or GeoJSON lap/track file."""
    name = up.name.lower()
    data = up.getvalue()
    if name.endswith((".geojson", ".json")):
        import json
        try:
            obj = json.loads(data)
        except Exception:  # noqa: BLE001
            return []
        feats = obj.get("features", [obj]) if isinstance(obj, dict) else []
        lines = []
        for f in feats:
            g = (f.get("geometry") or f) if isinstance(f, dict) else {}
            t, c = g.get("type"), g.get("coordinates")
            if t == "LineString":
                lines.append(c)
            elif t == "MultiLineString":
                lines.extend(c)
            elif t == "Polygon" and c:
                lines.append(c[0])
        return [(p[0], p[1]) for p in _stitch_linestrings(lines) if len(p) >= 2]
    if name.endswith(".gpx"):
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(data)
        except Exception:  # noqa: BLE001
            return []
        pts = []
        for el in root.iter():
            if el.tag.split("}")[-1] in ("trkpt", "rtept", "wpt"):
                lon, lat = el.get("lon"), el.get("lat")
                if lon and lat:
                    pts.append((float(lon), float(lat)))
        return pts
    import io
    try:
        df = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
    except Exception:  # noqa: BLE001
        return []
    cols = {str(c).strip().lower(): c for c in df.columns}
    loncol = next((cols[k] for k in ("lon", "longitude", "lng", "long", "x",
                                     "gps_lon", "v_gps_lon") if k in cols), None)
    latcol = next((cols[k] for k in ("lat", "latitude", "y",
                                     "gps_lat", "v_gps_lat") if k in cols), None)
    if not (loncol and latcol):
        return []
    sub = df[[loncol, latcol]].dropna()
    return list(zip(sub[loncol].astype(float), sub[latcol].astype(float)))


def _gps_trace_ui(slug):
    """Upload a GPS lap trace (GPX/CSV) to draw the real circuit layout."""
    with st.expander("🛰️ Draw the real layout — upload a GPS lap trace (GPX / CSV)"):
        st.caption("One lap of GPS (longitude/latitude) from telemetry draws the "
                   "exact circuit. Then the Timekeeping Plan places exact splits.")
        if st.session_state.get(f"trace_{slug}") is not None:
            if st.button("✖ Remove uploaded layout", key=f"trace_rm_{slug}"):
                for k in (f"trace_{slug}", f"trace_h_{slug}"):
                    st.session_state.pop(k, None)
                st.rerun()
        up = st.file_uploader("GPX / CSV / GeoJSON (lon-lat) — e.g. an OSM raceway export",
                              type=["gpx", "csv", "geojson", "json"],
                              key=f"trace_up_{slug}")
        if up is None:
            return
        if st.session_state.get(f"trace_h_{slug}") == hash(up.getvalue()):
            return
        pts = _parse_gps_trace(up)
        circ = circuit_map.outline_from_lonlat(pts, slug) if pts else None
        if circ is None:
            st.error("Couldn't find enough longitude/latitude points in that file.")
            return
        st.session_state[f"trace_{slug}"] = circ
        st.session_state[f"trace_h_{slug}"] = hash(up.getvalue())
        st.success(f"Layout drawn from {len(pts)} GPS points.")
        st.rerun()


def _timing_plan_ui(slug, circ):
    """Upload the official Timekeeping Points Plan PDF -> place S/F + the three
    sector splits exactly on FL / IP1 / IP2 / IP3."""
    from .parse_timekeeping_plan import parse_timekeeping_bytes, sector_points
    with st.expander("📐 Exact boundaries — upload official Timekeeping Points Plan"):
        up = st.file_uploader("Timekeeping Points Plan PDF (contains FL/IP1/IP2/IP3 GPS)",
                              type=["pdf"], key=f"tk_{slug}")
        if up is None:
            st.caption("MotoGP publishes this per event. It sets S/F and the 3 "
                       "sector splits to the real timing positions — no guessing.")
            return
        try:
            plan = parse_timekeeping_bytes(up.getvalue())
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not read plan: {e}")
            return
        sp = sector_points(plan)
        if not sp:
            st.error("FL/IP1/IP2/IP3 not found in this PDF — is it the Timekeeping "
                     "Points Plan?")
            return
        off, bnds = circuit_map.boundaries_from_timing(circ, *sp)
        skey, bkey = f"sf_{slug}", f"bounds_{slug}"
        new_sf = int(round(off * 100))
        new_b = [int(round(b * 100)) for b in bnds]
        sig = (new_sf, tuple(new_b))
        if st.session_state.get(f"{bkey}_applied") != sig:
            st.session_state[f"{skey}_s"] = new_sf
            st.session_state[skey] = new_sf
            for i, b in enumerate(new_b):
                st.session_state[f"{bkey}_{i+1}"] = b
            st.session_state[bkey] = sorted(new_b)
            st.session_state[f"{bkey}_applied"] = sig
            st.success(f"Exact boundaries applied — S/F at {new_sf}%, sector splits "
                       f"(IP1/IP2/IP3) at {new_b}% of the lap.")
            st.rerun()
        st.success(f"Using official plan: S/F {new_sf}%, IP1/IP2/IP3 at {new_b}%.")


def _sector_boundary_ui(slug):
    """Per-circuit, user-defined sector boundaries (% of lap distance).
    Defaults to equal quarters; persisted per circuit for the session."""
    key = f"bounds_{slug}"
    skey = f"sf_{slug}"
    default = st.session_state.get(key, [25, 50, 75])
    with st.expander("⚙️ Define S/F & sector boundaries", expanded=True):
        sf = st.slider("S/F · lap start position (% around the lap)", 0, 99,
                       int(st.session_state.get(skey, 0)), key=f"{skey}_s",
                       help="Rotate the black S/F marker to the real start/finish "
                            "line. Turn numbers stay fixed — line S/F up using them.")
        st.session_state[skey] = sf
        st.caption("Then set where each sector ends (% of lap from S/F):")
        c1, c2, c3 = st.columns(3)
        b1 = c1.slider("T1│T2", 1, 98, int(default[0]), key=f"{key}_1")
        b2 = c2.slider("T2│T3", 2, 99, int(default[1]), key=f"{key}_2")
        b3 = c3.slider("T3│T4", 3, 99, int(default[2]), key=f"{key}_3")
        st.session_state[key] = sorted([b1, b2, b3])
        if st.button("↺ Reset", key=f"{key}_rst"):
            for k in (f"{key}_1", f"{key}_2", f"{key}_3", key, f"{skey}_s", skey):
                st.session_state.pop(k, None)
            st.rerun()
    return [v / 100.0 for v in sorted([b1, b2, b3])], sf / 100.0


def _sector_strip(deltas, labels):
    fig = go.Figure()
    for i, (lab, d) in enumerate(zip(labels, deltas)):
        fig.add_shape(type="rect", x0=i / 4, x1=(i + 1) / 4, y0=0, y1=1,
                      line=dict(color="#FFFFFF", width=1),
                      fillcolor=engine.delta_colour(d), layer="below")
        fig.add_annotation(x=(i + 0.5) / 4, y=0.5, text=f"{lab}\n{_fmt_delta(d)}",
                           showarrow=False, font=dict(size=11, color="#111"))
    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False, range=[0, 1])
    fig.update_layout(height=120, margin=dict(l=6, r=6, t=6, b=6),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF")
    st.plotly_chart(fig, use_container_width=True)


def _colour_legend():
    items = [("#1B9E3E", "faster"), ("#9AA0A6", "≈ equal"),
             ("#F2C200", "small loss"), ("#E8800A", "bigger loss"),
             ("#D62728", "biggest loss")]
    chips = "".join(
        f"<span style='display:inline-block;width:12px;height:12px;background:{c};"
        f"border-radius:2px;margin:0 4px 0 10px;vertical-align:middle'></span>"
        f"<span style='font-size:11px;color:#444'>{t}</span>" for c, t in items)
    st.markdown(f"<div style='margin-top:2px'>{chips}</div>", unsafe_allow_html=True)


# ── tab: lap detail ─────────────────────────────────────────────────────────
def _tab_lap_detail(df, cls):
    opts = engine.rider_options(cls)
    lbl = st.selectbox("Rider", opts, index=0, key="lap_rider")
    no = _rider_no_from_label(cls, lbl)
    g = df[df["rider_no"] == no].sort_values("lap_no")
    if g.empty:
        st.info("No laps for this rider.")
        return
    show = pd.DataFrame({
        "Lap": g["lap_no"],
        "Run": g.get("run_no"),
        "Lap Time": g["lap_time_s"].map(_fmt_lap),
        "T1": g["t1"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T2": g["t2"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T3": g["t3"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "T4": g["t4"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "Speed": g["speed"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
        "Flag": g.apply(lambda r: ("PIT" if r["pit"] else "")
                        + (" ✗" if r["cancelled"] else "")
                        + ("" if r["is_flying"] else " out"), axis=1),
    })
    st.dataframe(show, hide_index=True, use_container_width=True)
    best = g[g["is_flying"]]["lap_time_s"].min()
    st.caption(f"Best flying lap: **{_fmt_lap(best)}**  ·  {int(g['is_flying'].sum())} "
               f"flying / {len(g)} total laps")
