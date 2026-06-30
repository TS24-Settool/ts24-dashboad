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


def seconds_to_lap_time_label(seconds) -> str:
    """Lap time in seconds -> `M'SS.mmm` (e.g. 100.720 -> 1'40.720, 63.5 -> 1'03.500).
    Missing values -> "". Internal numbers stay float; this is display-only and is
    the single helper used for lap-time axes / hovers across the app."""
    if seconds is None or (isinstance(seconds, float) and pd.isna(seconds)):
        return ""
    s = float(seconds)
    if s < 0:
        return ""
    m = int(s // 60)
    return f"{m}'{s - 60 * m:06.3f}"


def _laptime_ticks(ymin: float, ymax: float, max_ticks: int = 6):
    """Nice `M'SS.mmm` y-axis ticks spanning [ymin, ymax]."""
    span = max(ymax - ymin, 0.001)
    raw = span / max_ticks
    step = next((s for s in (0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20) if s >= raw), 20)
    start = (ymin // step) * step
    vals, v = [], start
    while v <= ymax + step:
        vals.append(round(v, 3))
        v += step
    return vals, [seconds_to_lap_time_label(v) for v in vals]


@st.cache_data(show_spinner=False)
def _parse_pdf_cached(data: bytes):
    parsed = parse_analysis_bytes(data)
    df = engine.laps_to_df(parsed)
    meta = parsed["meta"]
    slug = circuit_map.detect_slug(meta.get("event")) or circuit_map.detect_slug(meta.get("session"))
    return df, engine.session_label(meta), slug, meta


def _session_meta(label: str | None):
    """Return the parsed PDF meta for the overview card, or a minimal dict
    derived from the session label when meta is unavailable (e.g. online/demo)."""
    meta = st.session_state.get("mgp_meta")
    if meta:
        return meta
    parts = [p.strip() for p in (label or "").split("·")] if label else []

    def _get(i):
        return parts[i] if i < len(parts) and parts[i] else None

    return {"category": _get(0), "event": _get(1), "session": _get(2),
            "circuit": None, "circuit_len_m": None,
            "track_temp": None, "weather": None}


def _slug(text: str) -> str:
    """Filesystem-safe slug from a label: lowercase, non-alnum -> '_'."""
    import re
    s = re.sub(r"[^a-z0-9]+", "_", (text or "session").lower()).strip("_")
    return s or "session"


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


@st.cache_data(show_spinner="Loading the latest race…", ttl=1800)
def _latest_race(cls_name: str = "MotoGP"):
    """Most recent completed race for a class (auto-load on login)."""
    secs = fetch_official.seasons()
    years = sorted({s.get("year") for s in secs if s.get("year")}, reverse=True)
    for year in years[:2]:                       # this season, then last
        sid = next((s["id"] for s in secs if s.get("year") == year), None)
        if not sid:
            continue
        # Only completed GP rounds (skip tests + not-yet-run races). Without the
        # FINISHED filter, mid-season the latest 8-by-date are all future events,
        # so the scan would skip every completed round and fall back to last year.
        evs = [e for e in fetch_official.events(sid)
               if not e.get("test")
               and (e.get("status") or "").upper() == "FINISHED"]
        evs.sort(key=lambda e: e.get("date_end") or e.get("date_start") or "", reverse=True)
        for ev in evs[:8]:
            try:
                cats = fetch_official.categories(ev["id"])
                cat = next((c for c in cats if cls_name.lower() in (c.get("name") or "").lower()), None)
                if not cat:
                    continue
                sess = fetch_official.sessions(ev["id"], cat["id"])
                rac = next((s for s in sess if (s.get("type") or "").upper() == "RAC"), None)
                if not rac:
                    continue
                df, label, slug = fetch_official.fetch_session(
                    year, ev, cat, rac, ev.get("name", ""), "RAC")
                if df is not None and not df.empty:
                    return df, label, slug
            except Exception:  # noqa: BLE001
                continue
    return None, None, None


def _auto_load_once():
    """On first visit after login, auto-download the latest race."""
    if st.session_state.get("mgp_df") is not None or st.session_state.get("mgp_auto_tried"):
        return
    st.session_state["mgp_auto_tried"] = True
    try:
        df, label, slug = _latest_race("MotoGP")
    except Exception:  # noqa: BLE001
        return
    if df is not None and not df.empty:
        st.session_state["mgp_df"] = df
        st.session_state["mgp_label"] = label
        st.session_state["mgp_circuit"] = slug


def _rider_no_from_label(cls: pd.DataFrame, label: str):
    row = cls[cls.apply(lambda r: engine._rider_label(r) == label, axis=1)]
    return row["rider_no"].iloc[0] if not row.empty else None


# ── main entry ──────────────────────────────────────────────────────────────
def render_motogp_page():
    st.markdown('<p class="section-title">🏍 MotoGP Performance Analysis</p>',
                unsafe_allow_html=True)
    st.caption("Official timing → every rider · every lap · every sector.  "
               "·  build: **review-tools v12** (lap/sector/speed 3-rider compare · "
               "run review v2 · top-speed · session review · image track maps)")

    _auto_load_once()                            # auto-download latest race
    df, label = _data_source()
    if df is None or df.empty:
        st.info("⬆️ Upload an **Analysis** PDF (MotoGP / Moto2 / Moto3) or tap "
                "**Open demo session** to explore.")
        return

    _session_overview(df, label)

    cls = engine.classification(df)
    if cls.empty:
        st.warning("No valid laps for this session. The source may not have it "
                   "yet (very recent / not-yet-published events are often empty). "
                   "Try an earlier **Year** (e.g. 2025 or 2024), a different "
                   "**Session**, or the **MotoGP** class — or upload the official "
                   "Analysis PDF directly.")
        return

    tab_rev, tab_cls, tab_h2h, tab_map, tab_lap, tab_run = st.tabs(
        ["📋 Session Review", "🏁 Classification", "⚔️ Head-to-Head",
         "🗺️ Track Map", "📊 Lap Detail", "🏎️ Run Review"])

    with tab_rev:
        _tab_session_review(df, cls)
    with tab_cls:
        _tab_classification(cls)
    with tab_h2h:
        _tab_head_to_head(df, cls)
    with tab_map:
        _tab_track_map(df, cls)
    with tab_lap:
        _tab_lap_detail(df, cls)
    with tab_run:
        _tab_run_review(df, cls)


# ── session overview cards + export ─────────────────────────────────────────
def _session_overview(df, label):
    s = engine.session_summary(df, _session_meta(label), label)

    head = s.get("event") or label or "Session"
    sub_bits = []
    if s.get("circuit"):
        sub_bits.append(s["circuit"])
    if s.get("circuit_len_m"):
        sub_bits.append(f"{s['circuit_len_m']:,} m")
    sub = "  ·  ".join(sub_bits)
    st.markdown(f"#### {head}")
    if sub:
        st.caption(sub)

    # First KPI row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Class", s.get("klass") or "—")
    c2.metric("Session", s.get("session") or "—")
    c3.metric("Riders", s.get("riders") or 0)
    c4.metric("Flying laps", s.get("flying_laps") or 0)

    # Second KPI row — best / ideal lap
    d1, d2, d3 = st.columns(3)
    d1.metric("Best lap", _fmt_lap(s.get("best_lap")))
    if s.get("best_lap_rider"):
        d1.caption(s["best_lap_rider"])
    d2.metric("Ideal lap", _fmt_lap(s.get("ideal_lap")))
    d2.caption("fastest T1–T4 by anyone")
    d3.metric("Total laps", s.get("total_laps") or 0)

    # Track temp / weather — keep the code path, show only when present
    extra = []
    if s.get("track_temp") is not None:
        extra.append(f"Track {s['track_temp']}°C")
    if s.get("weather") is not None:
        extra.append(str(s["weather"]))
    if extra:
        st.caption("  ·  ".join(extra))

    _export_ui(df, label)


def _export_ui(df, label):
    meta = _session_meta(label)
    base = _slug(label)
    with st.expander("⬇️ Export session data (JSON / CSV)"):
        c1, c2 = st.columns(2)
        try:
            c1.download_button("JSON", engine.export_json(df, meta, label),
                               file_name=f"{base}.json",
                               mime="application/json",
                               use_container_width=True, key="exp_json")
        except Exception as e:  # noqa: BLE001
            c1.caption(f"JSON unavailable: {e}")
        try:
            c2.download_button("CSV (per-lap)", engine.export_csv(df),
                               file_name=f"{base}.csv",
                               mime="text/csv",
                               use_container_width=True, key="exp_csv")
        except Exception as e:  # noqa: BLE001
            c2.caption(f"CSV unavailable: {e}")


# ── data source (upload / demo) ─────────────────────────────────────────────
def _data_source():
    up = st.file_uploader("Analysis PDF", type=["pdf"], label_visibility="collapsed")
    c1, c2 = st.columns(2)
    demo = c1.button("▶︎ Open demo session", use_container_width=True)
    if c2.button("✖︎ Clear", use_container_width=True):
        st.session_state.pop("mgp_df", None)
        st.session_state.pop("mgp_label", None)
        st.session_state.pop("mgp_meta", None)
        st.rerun()

    if up is not None:
        try:
            df, label, slug, meta = _parse_pdf_cached(up.getvalue())
            st.session_state["mgp_df"] = df
            st.session_state["mgp_label"] = label
            st.session_state["mgp_circuit"] = slug
            st.session_state["mgp_meta"] = meta
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


# ── tab: session review (one-screen summary) ────────────────────────────────
def _gap_delta(gap):
    """st.metric delta string for a lap gap; None hides the delta."""
    if gap is None:
        return None
    if abs(gap) < 0.0005:
        return "class best"
    return f"{gap:+.3f}s"


def _tab_session_review(df, cls):
    opts = engine.rider_options(cls)
    if not opts:
        st.info("No classified riders for this session.")
        return
    c1, c2 = st.columns(2)
    my = c1.selectbox("My rider", opts, index=0, key="rev_my")
    my_no = _rider_no_from_label(cls, my)
    rec_no = engine.recommend_reference(cls, my_no)
    ref_pick = c2.selectbox("Compare vs", ["(auto: recommended)"] + opts, index=0,
                            key="rev_ref")
    ref_no = rec_no if ref_pick.startswith("(auto") else _rider_no_from_label(cls, ref_pick)

    r = engine.session_review(df, cls, my_no, ref_no)
    if r is None:
        st.info("No data for this rider.")
        return

    st.markdown(f"### {r['rider']}")
    sub = "  ·  ".join([x for x in [
        r.get("team"), r.get("bike"),
        (f"P{r['position']}" if r.get("position") else None)]
        if isinstance(x, str) and x])
    if sub:
        st.caption(sub)
    if r.get("ref"):
        if ref_pick.startswith("(auto"):
            st.caption(f"Compared vs **{r['ref']}**  ·  auto-selected: the rider one "
                       "place ahead — your nearest target. Override with **Compare vs**.")
        else:
            st.caption(f"Compared vs **{r['ref']}**  ·  manually selected.")

    # pace vs the class
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Best lap", _fmt_lap(r["best_lap"]), _gap_delta(r["best_gap"]),
              delta_color="inverse")
    k1.caption(f"vs Class Best {_fmt_lap(r['class_best'])}")
    k2.metric("Ideal lap", _fmt_lap(r["ideal_lap"]), _gap_delta(r["ideal_gap"]),
              delta_color="inverse")
    k2.caption(f"vs Class Ideal {_fmt_lap(r['class_ideal'])}")
    k3.metric("Lost potential",
              "—" if r["lost_potential"] is None else f"{r['lost_potential']:.3f}s")
    k3.caption("Best − Ideal")
    k4.metric("Pace spread",
              "—" if r["consistency_std"] is None else f"±{r['consistency_std']:.3f}s")
    k4.caption(f"over {r.get('pace_laps', 0)} pace laps")

    # where the time is, vs the reference
    g1, g2 = st.columns(2)
    loss, gain = r["biggest_loss"], r["biggest_gain"]
    g1.metric("Biggest sector loss",
              _sector_lbl(loss) if loss and loss[1] > 0 else "—")
    g2.metric("Biggest sector gain",
              _sector_lbl(gain) if gain and gain[1] < 0 else "—")

    # top speed in context (read alongside the sectors, not on its own)
    ts = engine.top_speed_review(df, cls, my_no)
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Top speed",
              "—" if ts["top_speed"] is None else f"{ts['top_speed']:.1f} km/h")
    t2.metric("vs Class Best",
              "—" if ts["speed_gap"] is None else f"{ts['speed_gap']:+.1f} km/h",
              delta_color="off")
    t3.metric("Top-speed rank",
              "—" if ts["speed_rank"] is None else f"P{ts['speed_rank']}")
    t4.metric("Lap − Speed rank",
              "—" if ts["rank_delta"] is None else f"{ts['rank_delta']:+d}",
              help="Lap-time rank minus top-speed rank. Large + = quicker in a "
                   "straight line than on the clock (look at the corners).")
    if ts.get("insight"):
        st.caption("🛈 " + ts["insight"])

    if r.get("focus_text"):
        st.info("🎯 " + r["focus_text"])
    if r.get("consistency_warning"):
        st.warning("📉 " + r["consistency_warning"])
    st.caption("Auto-picks the rider one place ahead as the comparison target. "
               "Open **Head-to-Head** or **Lap Detail** for the full breakdown.")


# ── tab: classification ─────────────────────────────────────────────────────
def _clean_str(v):
    return "" if (v is None or (isinstance(v, float) and pd.isna(v))) else str(v)


def _gap_str(d):
    return "" if pd.isna(d) or d == 0 else f"+{d:.3f}"


def _sec_str(v):
    return f"{v:.3f}" if pd.notna(v) else "—"


def _tab_classification(cls: pd.DataFrame):
    # Rider highlight selector
    opts = engine.rider_options(cls)
    pick = st.selectbox("Highlight my rider / team", opts, index=0,
                        key="cls_highlight") if opts else None
    pick_no = _rider_no_from_label(cls, pick) if pick else None
    pick_team = None
    if pick_no is not None:
        prow = cls[cls["rider_no"] == pick_no]
        if not prow.empty:
            pick_team = _clean_str(prow["team"].iloc[0]).strip() or None

    # column order: identity → pace → sectors → theoretical → laps
    show = pd.DataFrame({
        "Pos": cls.get("position"),
        "No": cls["rider_no"],
        "Rider": cls["rider_name"].map(_clean_str),
        "Team": cls.get("team", pd.Series([None] * len(cls))).map(_clean_str),
        "Bike": cls.get("manufacturer", pd.Series([None] * len(cls))).map(_clean_str),
        "Best Lap": cls["best_lap"].map(_fmt_lap),
        "Gap": cls.get("gap", pd.Series([np.nan] * len(cls))).map(_gap_str),
        "T1": cls["best_t1"].map(_sec_str),
        "T2": cls["best_t2"].map(_sec_str),
        "T3": cls["best_t3"].map(_sec_str),
        "T4": cls["best_t4"].map(_sec_str),
        "Top Speed": cls["top_speed"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
        "Spd Rk": cls.get("speed_rank", pd.Series([pd.NA] * len(cls))).map(
            lambda v: f"P{int(v)}" if pd.notna(v) else "—"),
        "Lap−Spd": cls.get("rank_delta", pd.Series([pd.NA] * len(cls))).map(
            lambda v: f"{int(v):+d}" if pd.notna(v) else "—"),
        "Ideal": cls["ideal_lap"].map(_fmt_lap),
        "Ideal Gap": cls.get("ideal_gap", pd.Series([np.nan] * len(cls))).map(_gap_str),
        "Lost": cls.get("lost_potential", pd.Series([np.nan] * len(cls))).map(
            lambda d: "" if pd.isna(d) else f"+{d:.3f}"),
        "Laps": cls["laps"],
    })

    # which rows to highlight (selected rider + teammates)
    teams = cls.get("team", pd.Series([None] * len(cls))).map(
        lambda v: _clean_str(v).strip())
    nos = cls["rider_no"]
    mine_mask = (nos == pick_no).to_numpy() if pick_no is not None else \
        np.zeros(len(cls), dtype=bool)
    team_mask = (teams == pick_team).to_numpy() if pick_team else \
        np.zeros(len(cls), dtype=bool)

    # session-fastest sector value per column (column min) for green highlight
    fastest = {f"T{i}": cls[f"best_t{i}"].min() for i in range(1, 5)}

    def _style_row(row):
        styles = [""] * len(row)
        i = row.name
        if mine_mask[i]:
            styles = ["background-color:#FFF3CD;font-weight:700"] * len(row)
        elif team_mask[i]:
            styles = ["background-color:#FFFBEA"] * len(row)
        return styles

    def _style_fastest(col):
        if col.name not in fastest:
            return [""] * len(col)
        target = fastest[col.name]
        out = []
        for i in range(len(col)):
            raw = cls[f"best_t{col.name[1]}"].iloc[i]
            out.append("background-color:#C6F6D5;font-weight:700"
                       if pd.notna(raw) and pd.notna(target) and abs(raw - target) < 1e-6
                       else "")
        return out

    sty = (show.style
           .apply(_style_row, axis=1)
           .apply(_style_fastest, axis=0))
    colcfg = {
        "Rider": st.column_config.TextColumn(width="medium"),
        "Team": st.column_config.TextColumn(width="medium"),
        "Best Lap": st.column_config.TextColumn(width="small"),
        "Pos": st.column_config.TextColumn(width="small"),
        "No": st.column_config.TextColumn(width="small"),
    }
    st.dataframe(sty, hide_index=True, use_container_width=True,
                 column_config=colcfg)
    st.caption("**Ideal** = sum of each rider's best T1–T4 (theoretical best lap). "
               "**Lost** = Lost potential (Best − Ideal, time left on the table). "
               "**Spd Rk** = top-speed rank · **Lap−Spd** = lap-time position − "
               "speed rank (large **+** = faster in a straight line than on the "
               "clock → likely corner/sector loss; mind slipstream, gearing & "
               "traffic, not just power). Green cell = session-fastest sector. "
               "Highlighted row = selected rider (teammates lightly shaded).")


# ── tab: head-to-head ───────────────────────────────────────────────────────
def _rider_pickers(cls: pd.DataFrame, key: str):
    opts = engine.rider_options(cls)
    c1, c2 = st.columns(2)
    my = c1.selectbox("My rider", opts, index=0, key=f"{key}_my")
    ref_default = 1 if len(opts) > 1 else 0
    ref = c2.selectbox("Reference (compare vs)", opts, index=ref_default, key=f"{key}_ref")
    mode = st.radio("Basis", ["best", "avg", "median"], horizontal=True, key=f"{key}_mode")
    st.caption("**Basis** — *best*: each rider's fastest in each sector (theoretical "
               "ceiling) · *avg*: mean over flying laps (race pace) · *median*: "
               "typical lap, ignores one-off mistakes.")
    return _rider_no_from_label(cls, my), _rider_no_from_label(cls, ref), mode, my, ref


def _sector_lbl(s):
    """('T2', -0.15) -> 'T2 −0.150s'  (None -> '—')."""
    if not s:
        return "—"
    return f"{s[0]} {s[1]:+.3f}s"


def _tab_head_to_head(df, cls):
    my_no, ref_no, mode, my_lbl, ref_lbl = _rider_pickers(cls, "h2h")
    if my_no is None or ref_no is None:
        return

    h = engine.h2h_summary(df, my_no, ref_no, mode)
    total = h["total"]

    st.markdown(f"**{my_lbl}**  vs  **{ref_lbl}**  ·  basis: *{mode}*")

    # Three summary cards
    m1, m2, m3 = st.columns(3)
    if pd.isna(total):
        verdict = "—"
        total_str = "—"
    else:
        verdict = ("faster ▲" if total < -0.03 else
                   ("slower ▼" if total > 0.03 else "even"))
        total_str = f"{total:+.3f} s"
    m1.metric("Σ delta", total_str, verdict,
              help="Sum of the four sector deltas (my rider − reference). "
                   "Negative = faster.")
    gain = h["gain_sector"]
    loss = h["loss_sector"]
    m2.metric("Biggest gain", _sector_lbl(gain) if gain and gain[1] < 0 else "—")
    m3.metric("Biggest loss", _sector_lbl(loss) if loss and loss[1] > 0 else "—")

    # coloured sector bar chart
    labels = ["T1", "T2", "T3", "T4"]
    deltas = h["deltas"]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=deltas,
        marker_color=[engine.delta_colour(d) for d in deltas],
        text=[_fmt_delta(d) for d in deltas], textposition="outside",
    ))
    fig.add_hline(y=0, line_width=1.5, line_dash="dot", line_color="#666")
    fig.update_layout(
        height=300, margin=dict(l=10, r=10, t=10, b=10),
        yaxis_title="Δ time vs ref (s)  ·  negative = faster",
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        font=dict(family="Arial", color="#111"),
    )
    fig.update_yaxes(autorange="reversed", gridcolor="#E5E7EB", zeroline=False)
    st.plotly_chart(fig, use_container_width=True, key="h2h_bar",
                    config={"displayModeBar": False})

    # plain-language diagnosis
    if h.get("diagnosis"):
        st.info(h["diagnosis"])

    # top speed read alongside the sector deltas
    sd = h.get("speed_delta")
    if sd is not None:
        st.markdown(f"**Top speed:** {sd:+.1f} km/h  ·  "
                    f"{my_lbl} {h['speed_my']:.1f} vs {ref_lbl} {h['speed_ref']:.1f}")
    if h.get("speed_note"):
        st.caption("🛈 " + h["speed_note"])

    # per-sector mine / ref / Δ table
    tbl = engine.sector_delta_table(df, my_no, ref_no)
    sub = tbl[tbl["mode"] == mode].reset_index(drop=True)
    disp = pd.DataFrame({
        "Sector": sub["sector"],
        f"{my_lbl}": sub["mine"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        f"{ref_lbl}": sub["ref"].map(lambda v: f"{v:.3f}" if pd.notna(v) else "—"),
        "Δ": sub["delta"].map(_fmt_delta),
    })
    st.dataframe(disp, hide_index=True, use_container_width=True)


# ── tab: track map (microsector strip) ──────────────────────────────────────
def _asset_source_caption(asset):
    """Show provenance for an image track-map asset — keeps the Sporting Maps
    source_url visible for a future licensing review (per the brief)."""
    meta = asset.get("metadata", {}) or {}
    bits = [f"**{meta.get('name') or asset.get('slug')}** track map"]
    if meta.get("intended_source"):
        bits.append(f"intended source: {meta['intended_source']}")
    if meta.get("source") and meta.get("source") != meta.get("intended_source"):
        bits.append(f"current asset: {meta['source']}")
    cap = "  ·  ".join(bits) + "."
    if meta.get("source_url"):
        cap += f"  Source: {meta['source_url']}"
    st.caption(cap)


def _track_loss_gain(labels, deltas):
    valid = [(l, d) for l, d in zip(labels, deltas) if d == d]   # drop NaN
    if not valid:
        return
    best = min(valid, key=lambda t: t[1])
    worst = max(valid, key=lambda t: t[1])
    if best[1] < -0.03:
        st.success(f"Biggest gain: **{best[0]}** → {_fmt_delta(best[1])}s")
    if worst[1] > 0.03:
        st.warning(f"Biggest loss: **{worst[0]}** → {_fmt_delta(worst[1])}s")


def _tab_track_map(df, cls):
    my_no, ref_no, mode, my_lbl, ref_lbl = _rider_pickers(cls, "map")
    if my_no is None or ref_no is None:
        return
    deltas = engine.sector_deltas(df, my_no, ref_no, mode)      # 4 REAL sectors
    labels = ["T1", "T2", "T3", "T4"]

    st.markdown(f"Where **{my_lbl}** gains / loses vs **{ref_lbl}**  ·  "
                f"4 official sectors  ·  basis *{mode}*")

    # Only circuits with a vetted image asset get a real track map. Everything
    # else shows the sector-comparison bar — never a half-baked GPS layout.
    supported = circuit_map.supported_track_map_slugs()
    auto_slug = st.session_state.get("mgp_circuit")            # inferred from session
    auto_ok = circuit_map.is_track_map_supported(auto_slug)
    auto_lbl = f"(auto: {auto_slug})" if auto_ok else "(auto)"
    sel = st.selectbox("Circuit", [auto_lbl] + supported, index=0, key="map_circuit")
    use_slug = auto_slug if sel == auto_lbl else sel

    if circuit_map.is_track_map_supported(use_slug):
        try:
            asset = circuit_map.load_image_asset(use_slug)
            fig = circuit_map.build_image_track_figure(asset, deltas, labels=labels)
            st.plotly_chart(fig, use_container_width=True, key="map_image",
                            config={"displayModeBar": False})
            _asset_source_caption(asset)
        except Exception as e:  # noqa: BLE001 — never crash the tab on a bad asset
            _sector_strip(deltas, labels)
            st.caption(f"⚠️ Couldn't render the track map for **{use_slug}** "
                       f"({e}). Showing the sector comparison only.")
    else:
        _sector_strip(deltas, labels)
        if not use_slug:
            st.caption("🗺️ Couldn't identify this session's circuit — showing the "
                       "sector comparison only.")
        else:
            st.caption(f"🗺️ Track map asset not available for **{use_slug}** yet — "
                       "showing the sector comparison only.")

    _colour_legend()
    _track_loss_gain(labels, deltas)


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
    st.plotly_chart(fig, use_container_width=True, key="map_sector_strip",
                    config={"displayModeBar": False})


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
_STATUS_COLOUR = {
    "valid": "#1B9E3E", "slow": "#E8800A", "out": "#9AA0A6",
    "pit": "#1F77B4", "cancelled": "#D62728",
}

# one colour per rider when overlaying up to 3 on the lap-time trend
_CMP_COLOURS = ["#1B9E3E", "#1F77B4", "#D62728"]


def _multi_rider_lap_trend(df, riders, key):
    """Overlay the valid/slow lap-time trend of up to 3 riders. One line per rider
    (coloured by rider), M'SS.mmm y-axis & hover."""
    fig = go.Figure()
    allv = []
    for i, (no, lab) in enumerate(riders):
        g = engine.lap_detail(df, no)
        if g is None or g.empty:
            continue
        pace = g[g["lap_status"].isin(["valid", "slow"])].sort_values("lap_no")
        v = pace["lap_time_s"].dropna()
        if v.empty:
            continue
        allv += list(v)
        fig.add_trace(go.Scatter(
            x=pace["lap_no"], y=pace["lap_time_s"], mode="lines+markers", name=lab,
            line=dict(color=_CMP_COLOURS[i % len(_CMP_COLOURS)], width=1.6),
            marker=dict(size=6),
            customdata=[seconds_to_lap_time_label(x) for x in pace["lap_time_s"]],
            hovertemplate=lab + "<br>Lap %{x}<br>%{customdata}<extra></extra>"))
    if not allv:
        st.caption("No valid laps to plot for the selected riders.")
        return
    ymin, ymax = min(allv), max(allv)
    pad = max((ymax - ymin) * 0.10, 0.20)
    tickvals, ticktext = _laptime_ticks(ymin, ymax)
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=24, b=10),
                      xaxis_title="Lap", plot_bgcolor="#FFFFFF",
                      paper_bgcolor="#FFFFFF",
                      legend=dict(orientation="h", y=1.14), font=dict(color="#111"))
    fig.update_xaxes(gridcolor="#EEE")
    fig.update_yaxes(title="Lap time", tickvals=tickvals, ticktext=ticktext,
                     range=[ymin - pad, ymax + pad], gridcolor="#EEE")
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


def _multi_rider_speed_trend(df, riders, key):
    """Overlay speed-trap (km/h, flying laps) of up to 3 riders, one line each."""
    fig = go.Figure()
    any_data = False
    for i, (no, lab) in enumerate(riders):
        g = engine.lap_detail(df, no)
        if g is None or g.empty:
            continue
        fl = g[g["is_flying"]] if "is_flying" in g.columns else g
        fl = fl[fl["speed"].notna()].sort_values("lap_no")
        if fl.empty:
            continue
        any_data = True
        fig.add_trace(go.Scatter(
            x=fl["lap_no"], y=fl["speed"], mode="lines+markers", name=lab,
            line=dict(color=_CMP_COLOURS[i % len(_CMP_COLOURS)], width=1.6),
            marker=dict(size=5),
            hovertemplate=lab + "<br>Lap %{x}<br>%{y:.1f} km/h<extra></extra>"))
    if not any_data:
        st.caption("No speed data for the selected riders.")
        return
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=24, b=10),
                      yaxis_title="Speed (km/h)", xaxis_title="Lap",
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                      legend=dict(orientation="h", y=1.14), font=dict(color="#111"))
    fig.update_xaxes(gridcolor="#EEE")
    fig.update_yaxes(gridcolor="#EEE")
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


def _multi_rider_sector_trends(df, riders):
    """2×2 small charts (T1–T4); each overlays the selected riders for that
    sector (one line per rider) so 3-rider sector comparison stays readable."""
    data = []
    for i, (no, lab) in enumerate(riders):
        g = engine.lap_detail(df, no)
        if g is None or g.empty:
            continue
        fl = g[g["is_flying"]] if "is_flying" in g.columns else g
        data.append((lab, _CMP_COLOURS[i % len(_CMP_COLOURS)], fl.sort_values("lap_no")))
    if not data:
        st.caption("No sector data for the selected riders.")
        return
    sectors = [("t1", "T1"), ("t2", "T2"), ("t3", "T3"), ("t4", "T4")]
    for row in range(2):
        cols = st.columns(2)
        for c in range(2):
            scol, slab = sectors[row * 2 + c]
            with cols[c]:
                fig = go.Figure()
                for lab, colour, fl in data:
                    if scol not in fl.columns:
                        continue
                    sub = fl[fl[scol].notna()]
                    if sub.empty:
                        continue
                    fig.add_trace(go.Scatter(
                        x=sub["lap_no"], y=sub[scol], mode="lines+markers", name=lab,
                        line=dict(color=colour, width=1.4), marker=dict(size=4),
                        hovertemplate=lab + " " + slab
                                      + "<br>Lap %{x}<br>%{y:.3f}s<extra></extra>"))
                fig.update_layout(
                    height=220, margin=dict(l=8, r=8, t=28, b=8),
                    title=dict(text=slab + " (s)", x=0.02, font=dict(size=13)),
                    plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                    showlegend=(row == 0 and c == 0),
                    legend=dict(orientation="h", y=1.28, font=dict(size=10)),
                    font=dict(color="#111"))
                fig.update_xaxes(gridcolor="#EEE")
                fig.update_yaxes(gridcolor="#EEE")
                st.plotly_chart(fig, use_container_width=True,
                                key=f"lap_sector_multi_{scol}",
                                config={"displayModeBar": False})


def _tab_lap_detail(df, cls):
    opts = engine.rider_options(cls)
    lbl = st.selectbox("Rider", opts, index=0, key="lap_rider")
    no = _rider_no_from_label(cls, lbl)
    cmp_lbls = st.multiselect(
        "Compare riders on the trends (optional, up to 2 more)",
        [o for o in opts if o != lbl], max_selections=2, key="lap_cmp")
    cmp_riders = [(no, lbl)] + [(_rider_no_from_label(cls, x), x) for x in cmp_lbls]
    ld = engine.lap_detail(df, no)
    if ld is None or ld.empty:
        st.info("No laps for this rider.")
        return
    cs = engine.consistency_stats(df, no)

    # Top stat cards
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Best", _fmt_lap(cs.get("best")))
    c2.metric("Top 3 avg", _fmt_lap(cs.get("top3_avg")))
    c3.metric("Median", _fmt_lap(cs.get("median")))
    std = cs.get("consistency_std")
    c4.metric("Pace spread", "—" if std is None else f"±{std:.3f}s")
    c4.caption(f"over {cs.get('pace_laps', 0)} pace laps")
    rng = cs.get("consistency_range")
    c5.metric("Range", "—" if rng is None else f"{rng:.3f}s")
    ws = cs.get("worst_sector")
    if ws:
        sstd = (cs.get("sector_std") or {}).get(ws)
        st.caption(f"Most variable sector: **{ws.upper()}**"
                   + (f" (±{sstd:.3f}s)" if sstd is not None else ""))

    # Lap-time trend — valid/slow laps only, so out/pit laps don't blow up the
    # y-range. Y axis & hover use M'SS.mmm (matches the rest of the app).
    fly = ld[ld["is_flying"]] if "is_flying" in ld.columns else ld
    st.markdown("**Lap-time trend**")
    pace = ld[ld["lap_status"].isin(["valid", "slow"])].sort_values("lap_no")
    yv = pace["lap_time_s"].dropna()
    if cmp_lbls:
        _multi_rider_lap_trend(df, cmp_riders, "lap_trend_multi")
        st.caption("Valid / slow laps of the selected riders overlaid (one line per "
                   "rider, M'SS.mmm). The stat cards and table below are for the "
                   "primary rider only.")
    elif yv.empty:
        st.caption("No valid laps to plot for this rider.")
    else:
        trend = go.Figure()
        trend.add_trace(go.Scatter(
            x=pace["lap_no"], y=pace["lap_time_s"], mode="lines",
            line=dict(color="#CBD5E1", width=1.5), showlegend=False,
            hoverinfo="skip"))
        for status in ("valid", "slow"):
            grp = pace[pace["lap_status"] == status]
            if grp.empty:
                continue
            trend.add_trace(go.Scatter(
                x=grp["lap_no"], y=grp["lap_time_s"], mode="markers", name=status,
                marker=dict(size=8, color=_STATUS_COLOUR.get(status, "#666")),
                customdata=[seconds_to_lap_time_label(v) for v in grp["lap_time_s"]],
                hovertemplate="Lap %{x}<br>Lap time: %{customdata}<extra>"
                              + status + "</extra>"))
        ymin, ymax = float(yv.min()), float(yv.max())
        pad = max((ymax - ymin) * 0.10, 0.20)
        tickvals, ticktext = _laptime_ticks(ymin, ymax)
        trend.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="Lap",
            plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
            legend=dict(orientation="h", y=1.12), font=dict(color="#111"))
        trend.update_xaxes(gridcolor="#EEE")
        trend.update_yaxes(title="Lap time", tickvals=tickvals, ticktext=ticktext,
                           range=[ymin - pad, ymax + pad], gridcolor="#EEE")
        st.plotly_chart(trend, use_container_width=True, key="lap_trend",
                        config={"displayModeBar": False})
        st.caption("Shows valid / slow laps only (out / pit laps excluded so the "
                   "scale stays readable). Full list in the table below.")

    # Sector trend — single rider = 4 lines; comparing = one small chart per sector
    st.markdown("**Sector trend (flying laps)**  ·  T1–T4 in seconds")
    if cmp_lbls:
        _multi_rider_sector_trends(df, cmp_riders)
    elif not fly.empty:
        sec_fig = go.Figure()
        sec_colours = {"t1": "#1F77B4", "t2": "#2CA02C",
                       "t3": "#FF7F0E", "t4": "#D62728"}
        for s in ("t1", "t2", "t3", "t4"):
            if s in fly.columns:
                sec_fig.add_trace(go.Scatter(
                    x=fly["lap_no"], y=fly[s], mode="lines+markers",
                    name=s.upper(),
                    line=dict(color=sec_colours[s], width=1.5),
                    marker=dict(size=5)))
        sec_fig.update_layout(
            height=300, margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="Sector time (s)", xaxis_title="Lap",
            plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
            legend=dict(orientation="h", y=1.12), font=dict(color="#111"))
        sec_fig.update_xaxes(gridcolor="#EEE")
        sec_fig.update_yaxes(gridcolor="#EEE")
        st.plotly_chart(sec_fig, use_container_width=True, key="lap_sector_trend",
                        config={"displayModeBar": False})

    # Speed: best-lap speed vs the rider's max speed-trap
    sp = engine.speed_profile(df, no)
    p1, p2, p3 = st.columns(3)
    p1.metric("Best-lap speed",
              "—" if sp["best_lap_speed"] is None else f"{sp['best_lap_speed']:.1f} km/h")
    if sp.get("best_lap_no"):
        p1.caption(f"on lap {sp['best_lap_no']}")
    p2.metric("Max speed",
              "—" if sp["max_speed"] is None else f"{sp['max_speed']:.1f} km/h")
    if sp.get("max_speed_lap_no"):
        p2.caption(f"on lap {sp['max_speed_lap_no']}")
    p3.metric("Best lap = max speed?",
              "—" if sp["coincide"] is None else ("Yes" if sp["coincide"] else "No"))
    st.markdown("**Speed trend (flying laps)**  ·  speed-trap, km/h")
    if cmp_lbls:
        _multi_rider_speed_trend(df, cmp_riders, "lap_speed_trend_multi")
    elif not fly.empty and fly["speed"].notna().any():
        spd_fig = go.Figure()
        spd_fig.add_trace(go.Scatter(
            x=fly["lap_no"], y=fly["speed"], mode="lines+markers",
            line=dict(color="#6B46C1", width=1.5), marker=dict(size=5),
            showlegend=False,
            hovertemplate="Lap %{x}<br>%{y:.1f} km/h<extra></extra>"))
        spd_fig.update_layout(
            height=240, margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="Speed (km/h)", xaxis_title="Lap",
            plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", font=dict(color="#111"))
        spd_fig.update_xaxes(gridcolor="#EEE")
        spd_fig.update_yaxes(gridcolor="#EEE")
        st.plotly_chart(spd_fig, use_container_width=True, key="lap_speed_trend",
                        config={"displayModeBar": False})
    st.caption("Speed-trap depends on slipstream, corner exit, gearing and traffic "
               "— read it with the sectors, not on its own. Max speed on a "
               "non-best lap often means a tow.")

    # Lap table with Status, non-valid rows greyed
    show = pd.DataFrame({
        "Lap": ld["lap_no"],
        "Run": ld.get("run_no"),
        "Lap Time": ld["lap_time_s"].map(_fmt_lap),
        "T1": ld["t1"].map(_sec_str),
        "T2": ld["t2"].map(_sec_str),
        "T3": ld["t3"].map(_sec_str),
        "T4": ld["t4"].map(_sec_str),
        "Speed": ld["speed"].map(lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
        "Status": ld["lap_status"],
    })
    statuses = ld["lap_status"].to_numpy()

    def _grey_rows(row):
        st_val = statuses[row.name]
        if st_val == "valid":
            return [""] * len(row)
        return ["color:#9AA0A6;background-color:#F4F4F5"] * len(row)

    sty = show.style.apply(_grey_rows, axis=1)
    st.dataframe(sty, hide_index=True, use_container_width=True)
    st.caption(f"Best flying lap: **{_fmt_lap(cs.get('best'))}**  ·  "
               f"{cs.get('flying', 0)} flying / {len(ld)} total laps. "
               "Greyed rows = out / pit / cancelled / slow.")


# ── tab: run review (per-stint, F1-style) ───────────────────────────────────
def _run_laptime_trend(sub, key):
    """Compact M'SS.mmm lap-time trend for one run's laps (valid/slow only)."""
    pace = sub[sub["lap_status"].isin(["valid", "slow"])].sort_values("lap_no")
    yv = pace["lap_time_s"].dropna()
    if yv.empty:
        st.caption("No valid laps in this run.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=pace["lap_no"], y=pace["lap_time_s"], mode="lines",
                             line=dict(color="#CBD5E1", width=1.5),
                             hoverinfo="skip", showlegend=False))
    for status in ("valid", "slow"):
        grp = pace[pace["lap_status"] == status]
        if grp.empty:
            continue
        fig.add_trace(go.Scatter(
            x=grp["lap_no"], y=grp["lap_time_s"], mode="markers+text", name=status,
            marker=dict(size=9, color=_STATUS_COLOUR.get(status, "#666")),
            text=[seconds_to_lap_time_label(v) for v in grp["lap_time_s"]],
            textposition="top center", textfont=dict(size=9),
            customdata=[seconds_to_lap_time_label(v) for v in grp["lap_time_s"]],
            hovertemplate="Lap %{x}<br>%{customdata}<extra>" + status + "</extra>"))
    ymin, ymax = float(yv.min()), float(yv.max())
    pad = max((ymax - ymin) * 0.12, 0.20)
    tickvals, ticktext = _laptime_ticks(ymin, ymax)
    fig.update_layout(height=260, margin=dict(l=10, r=10, t=20, b=10),
                      xaxis_title="Lap", plot_bgcolor="#FFFFFF",
                      paper_bgcolor="#FFFFFF", showlegend=False,
                      font=dict(color="#111"))
    fig.update_xaxes(gridcolor="#EEE")
    fig.update_yaxes(title="Lap time", tickvals=tickvals, ticktext=ticktext,
                     range=[ymin - pad, ymax + pad], gridcolor="#EEE")
    st.plotly_chart(fig, use_container_width=True, key=key,
                    config={"displayModeBar": False})


def _tab_run_review(df, cls):
    opts = engine.rider_options(cls)
    if not opts:
        st.info("No classified riders for this session.")
        return
    lbl = st.selectbox("Rider", opts, index=0, key="run_rider")
    no = _rider_no_from_label(cls, lbl)
    summary = engine.run_summary(df, no)
    if summary.empty:
        st.info("No complete runs for this rider yet — a run needs consecutive "
                "valid laps (out / pit / cancelled laps only split runs).")
        return

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Runs**  ·  out / pit laps excluded from the numbers")
        show = pd.DataFrame({
            "Run": summary["run_id"],
            "Laps": summary["laps"],
            "Valid": summary["valid_laps"],
            "Best": summary["best_lap"].map(seconds_to_lap_time_label),
            "Avg": summary["avg_valid"].map(seconds_to_lap_time_label),
            "Median": summary["median_valid"].map(seconds_to_lap_time_label),
            "Consistency": summary["consistency"].map(
                lambda v: f"±{v:.3f}" if pd.notna(v) else "—"),
            "T1": summary["best_t1"].map(_sec_str),
            "T2": summary["best_t2"].map(_sec_str),
            "T3": summary["best_t3"].map(_sec_str),
            "T4": summary["best_t4"].map(_sec_str),
            "Max kph": summary["max_speed"].map(
                lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
            "Avg kph": summary["avg_speed"].map(
                lambda v: f"{v:.1f}" if pd.notna(v) else "—"),
            "Note": summary["note"],
        })
        strong = summary["is_strongest"].to_numpy()
        cons = summary["consistency"].to_numpy()
        fastest = {f"T{i}": summary[f"best_t{i}"].min() for i in range(1, 5)}

        def _row(r):
            return (["background-color:#E8F5E9;font-weight:700"] * len(r)
                    if strong[r.name] else [""] * len(r))

        def _cons_cell(col):
            if col.name != "Consistency":
                return [""] * len(col)
            out = []
            for v in cons:
                out.append("" if pd.isna(v) else
                           "background-color:#C6F6D5" if v <= 0.15 else
                           "background-color:#FFF3CD" if v <= 0.30 else
                           "background-color:#FDE0E0")
            return out

        def _fast(col):
            if col.name not in fastest:
                return [""] * len(col)
            t = fastest[col.name]
            out = []
            for i in range(len(col)):
                raw = summary[f"best_t{col.name[1]}"].iloc[i]
                out.append("background-color:#C6F6D5;font-weight:700"
                           if pd.notna(raw) and pd.notna(t) and abs(raw - t) < 1e-6
                           else "")
            return out

        sty = (show.style.apply(_row, axis=1)
               .apply(_cons_cell, axis=0).apply(_fast, axis=0))
        st.dataframe(sty, hide_index=True, use_container_width=True)
        st.caption("Green row = strongest run (needs **2+ valid laps**). "
                   "Consistency needs 2+ valid laps (else **—**): green ≤0.15 · "
                   "amber ≤0.30 · red >0.30 s. Green sector = best across runs.")

    with right:
        st.markdown("**Session brief — all runs**")
        st.info("🏁 " + engine.run_brief(df, no, cls))
        st.caption("Whole-session view. A run needs 2+ valid laps to count as the "
                   "strongest; a single-lap run is only ever the *quickest lap*.")

    st.divider()
    run_ids = [int(x) for x in summary["run_id"]]
    default = (int(summary.loc[summary["is_strongest"].idxmax(), "run_id"])
               if summary["is_strongest"].any() else run_ids[0])
    sel = st.selectbox("Selected run", run_ids,
                       index=run_ids.index(default), key="run_sel")
    d = engine.run_detail(df, no, sel)
    st.info("🔎 **Selected run** — " + engine.selected_run_brief(df, no, sel, cls))

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Best lap", _fmt_lap(d["best_lap"]))
    if d.get("best_lap_no"):
        m1.caption(f"lap {d['best_lap_no']}")
    m2.metric("Avg valid", _fmt_lap(d["avg_valid"]))
    bva = (d["best_lap"] - d["avg_valid"]
           if d["best_lap"] is not None and d["avg_valid"] is not None else None)
    m3.metric("Best vs avg", "—" if bva is None else f"{bva:+.3f}s")
    m4.metric("Consistency",
              "—" if d["consistency"] is None else f"±{d['consistency']:.3f}s")

    s1, s2 = st.columns(2)
    im, lo = d.get("improved_most"), d.get("lost_most")
    s1.metric("Improved most", im.upper() if im else "—",
              help="Sector where the rider found the most time from the first to "
                   "the best lap of this run.")
    s2.metric("Lost most", lo.upper() if lo else "—",
              help="Sector with the largest average-vs-best gap this run "
                   "(most to gain by tidying up).")

    # top speed for this run (read with the sectors, not on its own)
    sp1, sp2, sp3, sp4 = st.columns(4)
    sp1.metric("Max speed",
               "—" if d["max_speed"] is None else f"{d['max_speed']:.1f} km/h")
    if d.get("max_speed_lap"):
        sp1.caption(f"lap {d['max_speed_lap']}")
    sp2.metric("Avg speed",
               "—" if d["avg_speed"] is None else f"{d['avg_speed']:.1f} km/h")
    sp3.metric("Best-lap speed",
               "—" if d["best_lap_speed"] is None else f"{d['best_lap_speed']:.1f} km/h")
    coincide = (d.get("max_speed_lap") is not None and d.get("best_lap_no") is not None
                and d["max_speed_lap"] == d["best_lap_no"])
    sp4.metric("Max speed on best lap?",
               "—" if d.get("max_speed_lap") is None else ("Yes" if coincide else "No"))
    st.caption("Speed depends on slipstream, corner exit, gearing and traffic — "
               "read it with the sectors, not on its own.")

    cL, cR = st.columns(2)
    with cL:
        st.markdown("**Lap-time trend (this run)**")
        _run_laptime_trend(d["laps"], key="run_lap_trend")
    with cR:
        st.markdown("**Sector trend (this run)**  ·  seconds")
        rg = d["laps"]
        pace = rg[rg["lap_status"].isin(["valid", "slow"])].sort_values("lap_no")
        if pace.empty:
            st.caption("No valid laps in this run.")
        else:
            sec_fig = go.Figure()
            sec_colours = {"t1": "#1F77B4", "t2": "#2CA02C",
                           "t3": "#FF7F0E", "t4": "#D62728"}
            for s in ("t1", "t2", "t3", "t4"):
                sec_fig.add_trace(go.Scatter(
                    x=pace["lap_no"], y=pace[s], mode="lines+markers",
                    name=s.upper(), line=dict(color=sec_colours[s], width=1.5),
                    marker=dict(size=5)))
            sec_fig.update_layout(
                height=260, margin=dict(l=10, r=10, t=20, b=10),
                xaxis_title="Lap", yaxis_title="Sector time (s)",
                plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
                legend=dict(orientation="h", y=1.15), font=dict(color="#111"))
            sec_fig.update_xaxes(gridcolor="#EEE")
            sec_fig.update_yaxes(gridcolor="#EEE")
            st.plotly_chart(sec_fig, use_container_width=True,
                            key="run_sector_trend",
                            config={"displayModeBar": False})
