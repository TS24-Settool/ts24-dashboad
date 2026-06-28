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
        st.warning("No clean flying laps found in this session.")
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

    return st.session_state.get("mgp_df"), st.session_state.get("mgp_label", "")


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

    circ = circuit_map.load_circuit(use_slug) if use_slug else None
    if circ is not None:
        fig = circuit_map.build_track_figure(circ, deltas, labels)
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Real **{use_slug}** layout. Colour per sector = real timing "
                   "delta. Sector *boundaries* are placed by equal track distance "
                   "(MotoGP does not publish intermediate positions), so treat the "
                   "split points as approximate — the colour is real.")
    else:
        _sector_strip(deltas, labels)
        st.caption("No bundled layout matched this circuit — showing the 4 real "
                   "sectors as a strip. (Bundled layouts: "
                   f"{', '.join(avail) or '—'}.)")

    _colour_legend()
    valid = [(l, d) for l, d in zip(labels, deltas) if d == d]  # drop NaN
    if valid:
        worst = max(valid, key=lambda t: t[1])
        if worst[1] > 0.03:
            st.warning(f"Biggest loss: **{worst[0]}** → {_fmt_delta(worst[1])}s")
    st.info("ℹ️ MotoGP's free timing has only 4 real sectors per lap — there is no "
            "finer measurement, so we do **not** fake sub-sector splits. Feed a "
            "mini-sector / GPS source and the tool will show real microsectors.")


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
