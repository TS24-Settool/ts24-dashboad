"""
content_studio.py — 📣 Content Studio (admin-only)
==================================================

Turns a loaded MotoGP timing session into ready-to-post social content in a few
clicks:  analysis → Instagram/X/… post.

The studio is built around the **TS24 Rider Note brand narrative**: an editorial
carousel (magazine style — heavy condensed headlines, highlight boxes, real
charts with annotation callouts, a dark takeaway bar) that teaches, not just
reports —

    1. Cover    — a photo (editor-supplied) + the headline (a surprising fact)
    2..N Charts — real per-lap charts (pace / sector / top-speed) + the lesson
    last CTA    — "Analyse your own riding with TS24 Rider Note" + QR

Pipeline exposed in the UI:
    pick theme → AI editor-in-chief ranks angles → AI headlines (★ rated)
    → template → auto-built carousel (editable) → caption + hashtags
    → per-platform copy → 1-click PNG export (carousel pages at IG/Story/Square)
    → engagement prediction → Weekly Content batch.

AI is optional. Without a Claude API key everything still works from
data-driven fallback copy; the key just upgrades headlines / caption / story.

Entry point: render_content_studio(df, cls, label, *, api_key="", is_admin=False)

No hard dependency on Pillow/qrcode at import time — they are imported lazily
inside the render helpers so the rest of the dashboard keeps working even if the
optional packages are not installed yet.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from . import engine
from .app_page import _fmt_lap, seconds_to_lap_time_label

try:                                   # AI is optional
    from services.claude_client import call_claude
except Exception:                      # noqa: BLE001
    call_claude = None


# ════════════════════════════════════════════════════════════════════════════
# Brand constants
# ════════════════════════════════════════════════════════════════════════════
BRAND_NAME   = "TS24 Rider Note"
BRAND_URL    = "ts24ridernote.com"
BRAND_TAG    = "Analyse your own riding."

# Carousel paper styles the user picks from (mapped to _PAPER_BG in the renderer)
TEMPLATES = {
    "A · Cream (editorial)":  {"paper": "cream"},
    "B · Cream + full chart": {"paper": "cream"},
    "C · Dark":               {"paper": "dark"},
    "D · White":              {"paper": "white"},
}

# Export canvas sizes (w, h)
SIZES = {
    "Instagram Portrait 1080×1350": (1080, 1350),
    "Square 1080×1080":             (1080, 1080),
    "Story / Reel 1080×1920":       (1080, 1920),
}

THEMES = [
    "Race Summary", "Rider Comparison", "Top Speed", "Consistency",
    "Sector Analysis", "Ideal Lap", "AI Story", "Tyre / Pace Drop", "Custom",
]

PLATFORMS = ["Instagram", "X", "Facebook", "Threads", "LinkedIn", "Note", "Blog"]


# ════════════════════════════════════════════════════════════════════════════
# 1. Data → story candidates  (the "editor-in-chief" raw material)
# ════════════════════════════════════════════════════════════════════════════
def _rl(row) -> str:
    return engine._rider_label(row)


def _short_name(label: str) -> str:
    """'#5 Johann Zarco' -> 'Johann Zarco'  ·  '#5 ZARCO J.' -> 'Zarco'."""
    s = re.sub(r"^#\d+\s*", "", str(label or "")).strip()
    return s or str(label or "Rider")


def _consistency_for(df, no):
    try:
        return engine.consistency_stats(df, no)
    except Exception:                  # noqa: BLE001
        return {}


def build_candidates(df: pd.DataFrame, cls: pd.DataFrame, label: str) -> list[dict]:
    """Score every viable "angle" for this session. Each candidate carries the
    facts the headline / data page / learning are built from, plus an
    interest score (0-100) the AI-editor uses to rank them.

    A candidate dict:
        theme, score, headline_fact(str), hook(str), data_points[(lbl,val,unit)],
        learning(str), rider(str|None)
    """
    out: list[dict] = []
    if cls is None or cls.empty:
        return out

    circuit = (st.session_state.get("mgp_circuit") or "").replace("-", " ").title()
    top = cls.iloc[0]
    best_lap = top["best_lap"]
    fastest = _short_name(_rl(top))

    # ── Race / Session Summary ───────────────────────────────────────────────
    gap2 = cls["gap"].iloc[1] if len(cls) > 1 and "gap" in cls else np.nan
    dp = [("Pole", _fmt_lap(best_lap), ""), ("Riders", int(len(cls)), "")]
    if pd.notna(gap2):
        dp.append(("Gap to P2", f"{gap2:+.3f}", "s"))
    out.append({
        "theme": "Race Summary", "rider": fastest,
        "score": 55,
        "headline_fact": f"{fastest} tops {circuit or 'the session'} — {_fmt_lap(best_lap)}",
        "hook": f"Who was really fastest at {circuit or 'this round'}?",
        "data_points": dp,
        "learning": "The headline lap rarely tells the whole story — break it down "
                    "by sector to see where it was actually won.",
    })

    # ── Ideal lap / lost potential — pick the biggest loser in the top group ──
    lp = cls.dropna(subset=["lost_potential"]).copy()
    if not lp.empty:
        lp = lp[lp.get("position", pd.Series(range(1, len(lp) + 1))) <= 10]
        if not lp.empty:
            row = lp.loc[lp["lost_potential"].idxmax()]
            lost = float(row["lost_potential"])
            nm = _short_name(_rl(row))
            score = int(min(95, 50 + lost * 60))      # bigger gap = more interesting
            out.append({
                "theme": "Ideal Lap", "rider": nm,
                "score": score,
                "headline_fact": f"{nm} left {lost:.3f}s on the table",
                "hook": f"Why wasn't {nm}'s best lap actually their best?",
                "data_points": [
                    ("Best lap", _fmt_lap(row["best_lap"]), ""),
                    ("Ideal lap", _fmt_lap(row["ideal_lap"]), ""),
                    ("Lost potential", f"{lost:.3f}", "s"),
                ],
                "learning": "Your *ideal lap* stitches together your fastest sectors. "
                            "The gap to it is free time — found by stringing a clean "
                            "lap together, not by riding harder.",
            })

    # ── Top speed vs lap-time mismatch — the signature TS24 angle ────────────
    if "rank_delta" in cls and cls["rank_delta"].notna().any():
        rd = cls.dropna(subset=["rank_delta"]).copy()
        rd = rd[rd.get("position", pd.Series(range(1, len(rd) + 1))) <= 12]
        if not rd.empty:
            # large positive rank_delta = much quicker on clock than top speed
            row = rd.loc[rd["rank_delta"].astype(float).idxmin()]   # most negative = fast lap, slow speed
            delta = int(row["rank_delta"]) if pd.notna(row["rank_delta"]) else 0
            nm = _short_name(_rl(row))
            if delta <= -2:
                out.append({
                    "theme": "Top Speed", "rider": nm,
                    "score": int(min(96, 60 + abs(delta) * 8)),
                    "headline_fact": f"{nm} was faster than the speed trap suggests",
                    "hook": f"{nm} wasn't fastest in a straight line. So how?",
                    "data_points": [
                        ("Top speed", f"{row['top_speed']:.1f}", "km/h"),
                        ("Speed rank", f"P{int(row['speed_rank'])}", ""),
                        ("Lap rank", f"P{int(row['position'])}", ""),
                    ],
                    "learning": "Corner speed beats horsepower. Carrying more speed "
                                "through the apex pays back everywhere — not just on "
                                "the straight.",
                })

    # ── Consistency — quietest, most repeatable rider in the top group ───────
    cons_rows = []
    for _, r in cls.head(8).iterrows():
        cs = _consistency_for(df, r["rider_no"])
        std = cs.get("consistency_std")
        if std is not None and cs.get("pace_laps", 0) >= 3:
            cons_rows.append((std, r, cs))
    if cons_rows:
        std, r, cs = min(cons_rows, key=lambda t: t[0])
        nm = _short_name(_rl(r))
        out.append({
            "theme": "Consistency", "rider": nm,
            "score": int(min(90, 45 + (0.4 - min(std, 0.4)) * 110)),
            "headline_fact": f"{nm} strung it together — ±{std:.3f}s over {cs.get('pace_laps', 0)} laps",
            "hook": f"Fast is easy once. {nm} did it every lap.",
            "data_points": [
                ("Pace spread", f"±{std:.3f}", "s"),
                ("Pace laps", cs.get("pace_laps", 0), ""),
                ("Best", _fmt_lap(cs.get("best")), ""),
            ],
            "learning": "Race pace is consistency, not heroics. A tight lap-time "
                        "spread beats one hot lap and three messy ones.",
        })

    # ── Sector analysis — H2H of P1 vs P2 (where the gap lives) ──────────────
    if len(cls) >= 2:
        my_no, ref_no = cls.iloc[1]["rider_no"], cls.iloc[0]["rider_no"]
        try:
            h = engine.h2h_summary(df, my_no, ref_no, "best")
            deltas = h.get("deltas", [])
            if deltas and any(pd.notna(d) for d in deltas):
                worst = max([(i, d) for i, d in enumerate(deltas) if pd.notna(d)],
                            key=lambda t: t[1])
                nm = _short_name(_rl(cls.iloc[1]))
                ref = _short_name(_rl(cls.iloc[0]))
                out.append({
                    "theme": "Sector Analysis", "rider": nm,
                    "score": 62,
                    "headline_fact": f"{nm} lost the lap in T{worst[0] + 1} ({worst[1]:+.3f}s)",
                    "hook": f"{nm} vs {ref}: one corner decided it.",
                    "data_points": [(f"T{i + 1}", f"{d:+.3f}" if pd.notna(d) else "—", "s")
                                    for i, d in enumerate(deltas)],
                    "learning": "Most lap-time lives in one or two corners. Find your "
                                "worst sector before you change anything on the bike.",
                })
        except Exception:              # noqa: BLE001
            pass

    # ── Pace drop / "tyre" angle — degradation across the fastest rider's run ─
    try:
        rs = engine.run_summary(df, top["rider_no"])
        if rs is not None and not rs.empty and len(rs) >= 1:
            longest = rs.loc[rs["valid_laps"].idxmax()]
            if int(longest["valid_laps"]) >= 4:
                out.append({
                    "theme": "Tyre / Pace Drop", "rider": fastest,
                    "score": 48,
                    "headline_fact": f"{fastest}'s pace held over {int(longest['valid_laps'])} laps",
                    "hook": f"Could {fastest} keep it up as the tyre dropped?",
                    "data_points": [
                        ("Best", seconds_to_lap_time_label(longest["best_lap"]), ""),
                        ("Avg", seconds_to_lap_time_label(longest["avg_valid"]), ""),
                        ("Spread", f"±{longest['consistency']:.3f}"
                         if pd.notna(longest["consistency"]) else "—", "s"),
                    ],
                    "learning": "A long run tells you about the tyre, not the lap. "
                                "Watch how the last laps compare to the first.",
                })
    except Exception:                  # noqa: BLE001
        pass

    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def _candidate_for_theme(cands: list[dict], theme: str) -> dict | None:
    if theme in ("AI Story", "Custom"):
        return cands[0] if cands else None
    for c in cands:
        if c["theme"] == theme:
            return c
    return cands[0] if cands else None


def stars(score: int) -> str:
    n = max(1, min(5, round(score / 20)))
    return "★" * n + "☆" * (5 - n)


# ════════════════════════════════════════════════════════════════════════════
# 2. Copy generation  (AI with data fallback)
# ════════════════════════════════════════════════════════════════════════════
def _extract_json(text: str):
    """Pull the first JSON object/array out of an LLM reply."""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body = m.group(1) if m else text
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = body.find(opener), body.rfind(closer)
        if i != -1 and j != -1 and j > i:
            try:
                return json.loads(body[i:j + 1])
            except Exception:          # noqa: BLE001
                continue
    return None


def _fact_block(cand: dict, label: str) -> str:
    dp = "; ".join(f"{l}={v}{u}" for l, v, u in cand.get("data_points", []))
    return (f"Session: {label}\nAngle: {cand['theme']}\n"
            f"Rider: {cand.get('rider') or '-'}\n"
            f"Key fact: {cand['headline_fact']}\nData: {dp}\n"
            f"Built-in learning: {cand['learning']}")


def ai_headlines(api_key: str, cand: dict, label: str, custom: str = "") -> list[dict]:
    """Return [{'text','score'}] headline options. AI when available, else
    data-driven fallback."""
    fallback = [
        {"text": cand["headline_fact"], "score": cand["score"]},
        {"text": cand["hook"], "score": max(40, cand["score"] - 8)},
    ]
    if not (api_key and call_claude):
        return fallback
    sys = ("You are a motorsport social-media editor for a rider-coaching brand. "
           "Write punchy, curiosity-driven Instagram headlines (max 8 words). "
           "No clickbait lies — only what the data supports.")
    usr = (_fact_block(cand, label)
           + (f"\nUser request: {custom}" if custom else "")
           + "\n\nReturn JSON: a list of 4 objects "
             '{"text": "<headline>", "score": <1-100 predicted appeal>}. '
             "Order best first.")
    raw = call_claude(api_key, usr, sys, max_tokens=600)
    data = _extract_json(raw)
    if isinstance(data, list) and data:
        cleaned = []
        for d in data[:4]:
            if isinstance(d, dict) and d.get("text"):
                cleaned.append({"text": str(d["text"]).strip().strip('"'),
                                "score": int(d.get("score", cand["score"]))})
        if cleaned:
            return cleaned
    return fallback


# one line colour per rider overlaid on a chart (matches the dashboard)
_RIDER_COLORS = [(27, 158, 62), (31, 119, 180), (214, 39, 40)]   # green / blue / red


def _circuit_name(label: str) -> str:
    c = (st.session_state.get("mgp_circuit") or "").replace("-", " ").strip()
    return c.title() if c else (label.split("·")[1].strip() if "·" in label else label)


def _top_riders(cls, n: int = 3) -> list[tuple]:
    """[(rider_no, legend_label '#79 Ai OGURA', short 'Ogura'), ...] top-n by pos."""
    out = []
    for _, r in cls.head(n).iterrows():
        out.append((r["rider_no"], _rl(r), _short_name(_rl(r))))
    return out


def _despike(xs, ys, k=3.5):
    """Drop robust outliers (out/in laps) so a marketing chart stays clean on
    any session. Keeps points within k robust-σ of the median; falls back to
    the raw series if that would leave too few."""
    if len(ys) < 4:
        return xs, ys
    a = np.asarray(ys, dtype=float)
    med = np.median(a)
    mad = np.median(np.abs(a - med))
    if mad <= 0:
        return xs, ys
    keep = np.abs(a - med) <= k * 1.4826 * mad
    if keep.sum() < 3:
        return xs, ys
    return [xs[i] for i in range(len(xs)) if keep[i]], \
           [ys[i] for i in range(len(ys)) if keep[i]]


def _series_from(df, riders, ycol, *, flying=True, statuses=None) -> list[dict]:
    """Per-lap series for a chart: one dict {name,color,x,y} per rider."""
    series = []
    for i, (no, legend, _short) in enumerate(riders):
        try:
            g = engine.lap_detail(df, no)
        except Exception:              # noqa: BLE001
            g = None
        if g is None or g.empty or ycol not in g.columns:
            continue
        sub = g
        if statuses is not None and "lap_status" in sub.columns:
            sub = sub[sub["lap_status"].isin(statuses)]
        elif flying and "is_flying" in sub.columns:
            sub = sub[sub["is_flying"]]
        sub = sub[sub[ycol].notna()].sort_values("lap_no")
        if sub.empty:
            continue
        xs = [int(v) for v in sub["lap_no"]]
        ys = [float(v) for v in sub[ycol]]
        xs, ys = _despike(xs, ys)
        series.append({"name": legend, "color": _RIDER_COLORS[i % 3],
                       "x": xs, "y": ys})
    return series


def _extremum_annotation(series, primary_idx, *, want_min, fmt, text):
    """A single data-true callout on the primary rider's best point."""
    if primary_idx >= len(series) or not series[primary_idx]["y"]:
        return []
    s = series[primary_idx]
    j = (min if want_min else max)(range(len(s["y"])), key=lambda k: s["y"][k])
    return [{"x": s["x"][j], "y": s["y"][j], "color": _RIDER_COLORS[0],
             "text": f"{text}\n{fmt(s['y'][j])}"}]


def _chart_page(cand, df, cls, label) -> dict:
    """Turn a candidate into a chart-driven insight page (falls back to stat
    cards / text when a time-series isn't meaningful for the theme)."""
    theme = cand["theme"]
    riders = _top_riders(cls, 3)
    hi = cand.get("rider") or ""
    base = {"kind": "insight", "eyebrow": theme.upper(), "title": cand["headline_fact"],
            "highlight": hi, "hi_color": "green", "takeaway": cand.get("learning"),
            "footer": label}

    if theme == "Top Speed":
        s = _series_from(df, riders, "speed", flying=True)
        base.update(eyebrow="THE PROOF · TOP SPEED",
                    chart={"type": "lines", "series": s, "y_fmt": "plain",
                           "unit": " km/h", "y_title": "Speed (km/h)",
                           "annotations": _extremum_annotation(
                               s, 0, want_min=False, fmt=lambda v: f"{v:.0f} km/h",
                               text="HIGHEST TOP SPEED")})
        return base

    if theme == "Sector Analysis":
        dps = cand.get("data_points", [])
        worst = max(range(len(dps)), key=lambda k: _num(dps[k][1]) or -9) if dps else 1
        scol = f"t{worst + 1}"
        s = _series_from(df, riders, scol, flying=True)
        base.update(eyebrow=f"WHERE THE RACE WAS WON · SECTOR {worst + 1}",
                    hi_color="green",
                    chart={"type": "lines", "series": s, "y_fmt": "plain",
                           "unit": "s", "y_title": f"T{worst + 1} (s)",
                           "annotations": _extremum_annotation(
                               s, 0, want_min=True, fmt=lambda v: f"{v:.3f}s",
                               text="FASTEST HERE")})
        return base

    if theme in ("Race Summary", "AI Story", "Consistency", "Tyre / Pace Drop"):
        s = _series_from(df, riders, "lap_time_s", statuses=["valid", "slow"])
        base.update(eyebrow="RACE PACE · LAP TIME", hi_color="pink",
                    chart={"type": "lines", "series": s, "y_fmt": "laptime",
                           "unit": "", "y_title": "Lap time",
                           "annotations": _extremum_annotation(
                               s, 0, want_min=True, fmt=seconds_to_lap_time_label,
                               text="FASTEST LAP")})
        return base

    # Ideal Lap & everything else → big-number stat cards
    base.update(stat_cards=[{"value": str(v), "label": str(l), "unit": str(u)}
                            for l, v, u in cand.get("data_points", [])[:3]])
    return base


def build_pages(cand: dict, headline: str, label: str,
                df=None, cls=None, cands=None) -> list[dict]:
    """Editorial carousel: photo cover → chart insights → CTA.

    When df/cls are given, the insight pages carry REAL per-lap charts (lap-time,
    sector, top-speed) like the published Rider Note posts. Without them it still
    produces a valid cover + stat-card page + CTA."""
    circuit = _circuit_name(label)
    cover = {
        "kind": "cover", "eyebrow": "RIDER NOTE · DATA ANALYSIS",
        "tag": f"{circuit} · MotoGP Race Analysis".upper(),
        "title": headline, "highlight": cand.get("rider") or "",
        "subtitle": cand.get("hook") or "", "footer": ""}

    insights: list[dict] = []
    if df is not None and cls is not None and not cls.empty:
        insights.append(_chart_page(cand, df, cls, label))
        # supporting angles → the multi-page "story" (distinct themes, chart-first)
        order = ["Race Summary", "Sector Analysis", "Top Speed", "Consistency",
                 "Tyre / Pace Drop", "Ideal Lap"]
        pool = sorted(cands or [], key=lambda c: order.index(c["theme"])
                      if c["theme"] in order else 99)
        for c in pool:
            if len(insights) >= 3:
                break
            if c["theme"] == cand["theme"]:
                continue
            insights.append(_chart_page(c, df, cls, label))
    else:
        big = cand["data_points"][0] if cand.get("data_points") else ("", "", "")
        insights.append({
            "kind": "insight", "eyebrow": "THE DATA", "title": cand["headline_fact"],
            "highlight": cand.get("rider") or "", "hi_color": "green",
            "stat_cards": [{"value": str(v), "label": str(l), "unit": str(u)}
                           for l, v, u in cand.get("data_points", [])[:3]],
            "takeaway": cand.get("learning"), "footer": label})

    cta = {"kind": "cta", "eyebrow": BRAND_NAME, "title": "Want to analyse your riding?",
           "highlight": "", "body": "Every rider has a hidden ideal lap.\n" + BRAND_TAG,
           "url": BRAND_URL, "footer": ""}
    return [cover] + insights + [cta]


def ai_caption(api_key: str, cand: dict, headline: str, label: str,
               platform: str, custom: str = "") -> dict:
    """Return {'caption','hashtags'[list]} for a platform. AI then fallback."""
    nm = cand.get("rider") or "This rider"
    base = (f"{headline}.\n\n{cand['headline_fact']}.\n{cand['learning']}\n\n"
            f"Would your riding show the same pattern?\n"
            f"↓ Analyse your own riding with {BRAND_NAME}.")
    base_tags = _fallback_tags(cand)
    fallback = {"caption": _platform_trim(base, platform), "hashtags": base_tags}

    if not (api_key and call_claude):
        return fallback
    sys = (f"You are the social editor for {BRAND_NAME}, a brand that teaches "
           "everyday riders to get faster through data. Voice: insightful, "
           "encouraging, never arrogant. Always end with a soft CTA to analyse "
           "their own riding. Adapt length & tone to the platform.")
    usr = (_fact_block(cand, label) + f"\nChosen headline: {headline}\n"
           f"Platform: {platform}"
           + (f"\nUser request: {custom}" if custom else "")
           + "\n\nReturn JSON {\"caption\": \"<post body>\", "
             "\"hashtags\": [\"#tag\", ...]}. "
             f"{_platform_hint(platform)}")
    raw = call_claude(api_key, usr, sys, max_tokens=900)
    data = _extract_json(raw)
    if isinstance(data, dict) and data.get("caption"):
        tags = data.get("hashtags") or base_tags
        tags = [t if str(t).startswith("#") else f"#{t}" for t in tags][:30]
        return {"caption": str(data["caption"]).strip(), "hashtags": tags}
    return fallback


def _fallback_tags(cand: dict) -> list[str]:
    tags = ["#MotoGP", "#TS24RiderNote", "#Motorcycle", "#TrackDay",
            "#RaceData", "#GoFaster"]
    nm = cand.get("rider")
    if nm:
        tags.insert(1, "#" + re.sub(r"[^A-Za-z0-9]", "", nm))
    extra = {"Top Speed": "#TopSpeed", "Consistency": "#Consistency",
             "Sector Analysis": "#SectorTime", "Ideal Lap": "#IdealLap"}.get(cand["theme"])
    if extra:
        tags.append(extra)
    return tags[:12]


def _platform_hint(platform: str) -> str:
    return {
        "Instagram": "Instagram carousel caption: 2-4 short paragraphs, line breaks, "
                     "8-15 hashtags at the end.",
        "X": "X/Twitter: under 280 characters, 1-2 hashtags only.",
        "Facebook": "Facebook: conversational, 1-3 short paragraphs, few hashtags.",
        "Threads": "Threads: casual and concise, under 500 chars, minimal hashtags.",
        "LinkedIn": "LinkedIn: a professional insight angle (data/learning), 3-5 "
                    "hashtags, no hype.",
        "Note": "note.com style blog intro: a reflective Japanese-blog tone is fine; "
                "longer, no hashtag spam.",
        "Blog": "Blog: a short article intro with a clear takeaway, no hashtags.",
    }.get(platform, "")


def _platform_trim(text: str, platform: str) -> str:
    if platform == "X":
        return text[:270].rsplit("\n", 1)[0]
    if platform in ("Threads",):
        return text[:480]
    return text


# ════════════════════════════════════════════════════════════════════════════
# 3. Engagement prediction (heuristic; AI optional)
# ════════════════════════════════════════════════════════════════════════════
def predict_engagement(cand: dict, headline: str, api_key: str = "") -> dict:
    score = cand["score"]
    reasons = []
    h = headline.lower()
    if any(w in h for w in ("why", "how", "?", "wasn't", "left", "hidden", "really")):
        score += 6
        reasons.append("Curiosity-gap headline → people stop scrolling.")
    if cand["theme"] in ("Top Speed", "Ideal Lap"):
        score += 5
        reasons.append("Counter-intuitive finding → high save/share rate.")
    if len(headline.split()) > 11:
        score -= 8
        reasons.append("Headline is long — tighten it for the feed.")
    score = int(max(20, min(98, score)))
    verdict = ("People will save this." if score >= 75 else
               "Solid — worth posting." if score >= 55 else
               "Simplify the hook before posting.")
    return {"score": score, "verdict": verdict,
            "reasons": reasons or ["Clear, on-brand teaching post."]}


# ════════════════════════════════════════════════════════════════════════════
# 4. PNG carousel renderer (Pillow)
# ════════════════════════════════════════════════════════════════════════════
def _load_pil():
    from PIL import Image, ImageDraw, ImageFont           # noqa: F401
    return Image, ImageDraw, ImageFont


# ── editorial brand tokens ───────────────────────────────────────────────────
from pathlib import Path as _Path
_FONT_DIR = _Path(__file__).parent / "assets" / "fonts"

_INK   = (24, 24, 24)
_CREAM = (243, 239, 228)
_PAPER = (255, 255, 255)
_GOLD  = (196, 156, 62)
_GREEN = (32, 166, 90)
_PINK  = (231, 30, 120)
_RED   = (210, 66, 48)
_MUTED = (128, 126, 120)
_GRID  = (228, 224, 213)
_DARK  = (18, 18, 18)
_HI = {"gold": _GOLD, "green": _GREEN, "pink": _PINK, "red": _RED}

# template → paper colour for the insight/CTA pages
_PAPER_BG = {
    "A · Cream (editorial)": _CREAM,
    "B · Cream + full chart": _CREAM,
    "C · Dark": _DARK,
    "D · White": _PAPER,
}

_SYS_FALLBACK = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_CACHE: dict = {}
_FONT_FILE = {"display": "Anton-Regular.ttf", "label": "Oswald.ttf",
              "body": "Archivo.ttf"}


def _font(kind: str, size: int, weight: int | None = None):
    """kind: 'display' (Anton, headlines) · 'label' (Oswald, eyebrows/numbers) ·
    'body' (Archivo, copy). weight applies to the two variable fonts."""
    key = (kind, size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    f = None
    try:
        f = ImageFont.truetype(str(_FONT_DIR / _FONT_FILE[kind]), size)
        if weight is not None:
            try:
                f.set_variation_by_axes([weight] if kind == "label" else [weight, 100])
            except Exception:          # noqa: BLE001
                pass
    except Exception:                  # noqa: BLE001
        for p in _SYS_FALLBACK:
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:          # noqa: BLE001
                continue
        if f is None:
            f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _tw(d, s, f):
    return d.textlength(str(s), font=f)


def _wrap(d, text, font, max_w):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _tw(d, trial, font) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _num(val):
    """Best-effort float from a data-point value ('+0.122' → 0.122, 'P5' → None)."""
    s = str(val).strip()
    if s.startswith("P"):
        return None
    s = s.replace("+", "").replace("s", "").replace(",", "").replace("km/h", "")
    try:
        return float(s)
    except Exception:                  # noqa: BLE001
        return None


def _rr(d, box, r, **kw):
    d.rounded_rectangle([round(v) for v in box], radius=r, **kw)


def _draw_qr(Image, url, box):
    try:
        import qrcode
        qr = qrcode.QRCode(border=1, box_size=10)
        qr.add_data(f"https://{url}")
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        return img.resize((box, box))
    except Exception:                  # noqa: BLE001
        return None


# ── headline with highlight boxes ────────────────────────────────────────────
def _hi_tokens(title, highlight):
    words = str(title).split()
    if not highlight:
        return [(w, False) for w in words]
    hw = str(highlight).split()
    low = [w.lower().strip(".,'") for w in words]
    hl = [w.lower().strip(".,'") for w in hw]
    idx = -1
    for s in range(len(words) - len(hl) + 1):
        if low[s:s + len(hl)] == hl:
            idx = s
            break
    return [(w, idx != -1 and idx <= k < idx + len(hl)) for k, w in enumerate(words)]


def _wrap_tokens(d, tokens, font, max_w):
    lines, cur, curw, sw = [], [], 0, _tw(d, " ", font) + 4
    for word, hi in tokens:
        w = _tw(d, word, font)
        add = w if not cur else curw + sw + w
        if add <= max_w or not cur:
            cur.append((word, hi))
            curw = add
        else:
            lines.append(cur)
            cur, curw = [(word, hi)], w
    if cur:
        lines.append(cur)
    return lines


def _draw_headline(d, x, y, tokens, font, max_w, line_h, base_col, hi_col):
    """Wrapped ALL-CAPS display headline; consecutive highlighted words get one
    filled box (white text). Returns the y just below the last line."""
    sw = _tw(d, " ", font) + 4
    bb = d.textbbox((0, 0), "HZg", font=font)
    for line in _wrap_tokens(d, tokens, font, max_w):
        pos, cx = [], x
        for word, hi in line:
            w = _tw(d, word, font)
            pos.append((word, hi, cx, w))
            cx += w + sw
        j = 0
        while j < len(pos):                       # highlight boxes first (merge runs)
            if pos[j][1]:
                k = j
                while k + 1 < len(pos) and pos[k + 1][1]:
                    k += 1
                bx0, bx1 = pos[j][2], pos[k][2] + pos[k][3]
                _rr(d, [bx0 - 9, y + bb[1] - 5, bx1 + 9, y + bb[3] + 9], 7, fill=hi_col)
                j = k + 1
            else:
                j += 1
        for word, hi, cx, w in pos:
            d.text((cx, y), word, font=font, fill=(255, 255, 255) if hi else base_col)
        y += line_h
    return y


def _eyebrow(d, x, y, text, color, size=26, tracking=4):
    f = _font("label", size, 600)
    cx = x
    for ch in str(text).upper():
        d.text((cx, y), ch, font=f, fill=color)
        cx += _tw(d, ch, f) + (tracking if ch != " " else tracking + 6)
    return size + 8


def _logo(d, x, y, on_dark):
    """TS24. mark in a gold-outlined box. Returns its width."""
    f = _font("label", 34, 700)
    txt = "TS24"
    tw = _tw(d, txt, f) + _tw(d, ".", f)
    padx, h = 16, 50
    box_w = tw + 2 * padx
    _rr(d, [x, y, x + box_w, y + h], 8, outline=_GOLD, width=3)
    ink = (255, 255, 255) if on_dark else _INK
    d.text((x + padx, y + 5), txt, font=f, fill=ink)
    d.text((x + padx + _tw(d, txt, f), y + 5), ".", font=f, fill=_GOLD)
    return box_w


def _counter(d, x_right, y, idx, n, color):
    f = _font("label", 28, 600)
    s = f"{idx + 1}/{n}"
    d.text((x_right - _tw(d, s, f), y), s, font=f, fill=color)


def _chrome(d, W, pad, idx, n, on_dark, top_rule):
    if top_rule:
        d.rectangle([0, 0, W, 9], fill=_GOLD)
    lw = _logo(d, pad, 48, on_dark)
    _counter(d, W - pad, 58, idx, n, _MUTED if not on_dark else (210, 210, 210))
    return lw


# ── charts ───────────────────────────────────────────────────────────────────
def _xticks(a, b, n=6):
    step = max(1, round((b - a) / n))
    t, v = [], int(a)
    while v <= b:
        t.append(v)
        v += step
    return t


def _line_chart(d, box, series, y_fmt, unit, y_title, annotations):
    x0, y0, x1, y1 = box
    _rr(d, box, 22, fill=_PAPER, outline=_GRID, width=2)
    if not series:
        f = _font("label", 30, 500)
        d.text((x0 + 30, (y0 + y1) // 2 - 15), "No lap data available",
               font=f, fill=_MUTED)
        return

    # top row: y-axis title, then the rider legend (matches the print layout)
    fl = _font("label", 24, 600)
    lx, ly = x0 + 30, y0 + 24
    if y_title:
        ft0 = _font("label", 24, 700)
        d.text((lx, ly), y_title, font=ft0, fill=_INK)
        lx += _tw(d, y_title, ft0) + 34
    for s in series:
        d.line([(lx, ly + 13), (lx + 24, ly + 13)], fill=s["color"], width=5)
        d.ellipse([lx + 8, ly + 6, lx + 16, ly + 14], fill=s["color"])
        d.text((lx + 32, ly), s["name"], font=fl, fill=_INK)
        lx += 32 + _tw(d, s["name"], fl) + 28

    pl, pr, pt, pb = x0 + 104, x1 - 34, y0 + 70, y1 - 52
    allx = [v for s in series for v in s["x"]]
    ally = [v for s in series for v in s["y"]]
    xmin, xmax = min(allx), max(allx)
    ymin, ymax = min(ally), max(ally)
    if ymax == ymin:
        ymax = ymin + 1
    pad = (ymax - ymin) * 0.14
    ymin, ymax = ymin - pad, ymax + pad
    if xmax == xmin:
        xmax = xmin + 1

    def sx(v):
        return pl + (v - xmin) / (xmax - xmin) * (pr - pl)

    def sy(v):
        return pb - (v - ymin) / (ymax - ymin) * (pb - pt)

    ft = _font("label", 22, 500)
    for k in range(5):
        yy = ymin + (ymax - ymin) * k / 4
        py = sy(yy)
        d.line([(pl, py), (pr, py)], fill=_GRID, width=1)
        lab = (seconds_to_lap_time_label(yy) if y_fmt == "laptime"
               else f"{yy:.1f}")
        d.text((pl - 12 - _tw(d, lab, ft), py - 12), lab, font=ft, fill=_MUTED)
    for xv in _xticks(xmin, xmax):
        px = sx(xv)
        d.text((px - _tw(d, str(xv), ft) / 2, pb + 12), str(xv), font=ft, fill=_MUTED)

    for s in series:
        pts = [(sx(a), sy(b)) for a, b in zip(s["x"], s["y"])]
        if len(pts) >= 2:
            d.line(pts, fill=s["color"], width=4, joint="curve")
        for px, py in pts:
            d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=s["color"])

    def _callout(px, py, text, color):
        f1 = _font("label", 22, 700)
        f2 = _font("label", 19, 500)
        head, _, sub = str(text).partition("\n")
        w = max(_tw(d, head, f1), _tw(d, sub, f2)) + 24
        h = 30 + (24 if sub else 0)
        bx = min(max(px - w / 2, pl + 4), pr - w - 4)
        by = py - h - 24 if py - h - 24 > pt else py + 22
        d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=color, width=3)
        d.line([(px, py), (bx + w / 2, by + (h if by < py else 0))], fill=color, width=2)
        _rr(d, [bx, by, bx + w, by + h], 8, fill=color)
        d.text((bx + 12, by + 5), head, font=f1, fill=(255, 255, 255))
        if sub:
            d.text((bx + 12, by + 30), sub, font=f2, fill=(255, 255, 255))

    for a in (annotations or []):
        _callout(sx(a["x"]), sy(a["y"]), a["text"], a.get("color", _GREEN))


def _stat_cards(d, box, cards, accent):
    x0, y0, x1, y1 = box
    n = len(cards) or 1
    gap = 24
    cw = (x1 - x0 - gap * (n - 1)) / n
    for i, c in enumerate(cards):
        cx = x0 + i * (cw + gap)
        first = i == 0
        _rr(d, [cx, y0, cx + cw, y1], 20,
            fill=(236, 246, 240) if first else _PAPER,
            outline=accent if first else _GRID, width=2)
        val = str(c["value"]) + (c.get("unit") or "")
        sz = 76
        for sz in (76, 64, 54, 46, 38):
            fv = _font("display", sz)
            if _tw(d, val, fv) <= cw - 30:
                break
        col = accent if first else _INK
        d.text((cx + cw / 2 - _tw(d, val, fv) / 2, y0 + (y1 - y0) / 2 - sz * 0.72),
               val, font=fv, fill=col)
        fll = _font("label", 24, 600)
        lab = str(c["label"]).upper()
        while _tw(d, lab, fll) > cw - 20 and len(lab) > 4:
            lab = lab[:-2]
        d.text((cx + cw / 2 - _tw(d, lab, fll) / 2, y1 - 52), lab, font=fll, fill=_MUTED)


def _takeaway(d, box, text, emph, hi_col, on_dark):
    x0, y0, x1, y1 = box
    _rr(d, box, 16, fill=(38, 38, 42) if on_dark else _DARK)
    f = _font("body", 30, 600)
    inner, maxw = x0 + 28, (x1 - x0) - 56
    lines = _wrap(d, text, f, maxw)[:3]
    ty = y0 + ((y1 - y0) - len(lines) * 40) / 2
    hw = {w.lower().strip(".,") for w in (emph or [])}
    for ln in lines:
        cx = inner
        for word in ln.split():
            col = hi_col if word.lower().strip(".,") in hw else (238, 238, 238)
            d.text((cx, ty), word, font=f, fill=col)
            cx += _tw(d, word + " ", f)
        ty += 40


# ── cover photo ──────────────────────────────────────────────────────────────
def _cover_fit(Image, photo, W, H):
    img = Image.open(io.BytesIO(photo)).convert("RGB")
    scale = max(W / img.width, H / img.height)
    nw, nh = int(img.width * scale) + 1, int(img.height * scale) + 1
    img = img.resize((nw, nh))
    left, top = (nw - W) // 2, (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def _darken(Image, base):
    W, H = base.size
    ys = np.arange(H) / H
    a_top = np.clip((0.22 - ys) / 0.22, 0, 1) * 150
    a_bot = np.clip((ys - 0.40) / 0.60, 0, 1) * 225
    col = np.clip(np.maximum(a_top, a_bot), 0, 238).astype("uint8")
    mask = Image.fromarray(np.repeat(col[:, None], W, axis=1), mode="L")
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), base, mask)


def _cover_bg(Image, photo, W, H):
    if photo:
        try:
            return _darken(Image, _cover_fit(Image, photo, W, H))
        except Exception:          # noqa: BLE001
            pass
    base = Image.new("RGB", (W, H), (16, 17, 20))
    ys = np.arange(H) / H
    col = (18 + ys * 10).astype("uint8")
    arr = np.stack([col, col, (col + 6)], axis=-1)
    arr = np.repeat(arr[:, None, :], W, axis=1)
    return Image.fromarray(arr, "RGB")


# ── page renderers ───────────────────────────────────────────────────────────
def _render_cover(Image, ImageDraw, page, W, H, pad, photo, idx, n):
    im = _cover_bg(Image, photo, W, H)
    d = ImageDraw.Draw(im)
    lw = _logo(d, pad, 54, True)
    _eyebrow(d, pad + lw + 22, 68, page.get("eyebrow", ""), (232, 232, 232), size=24)
    _counter(d, W - pad, 60, idx, n, (225, 225, 225))

    # bottom stack — measured from the base up
    tag = str(page.get("tag", "")).upper()
    ftag = _font("label", 24, 700)
    tokens = _hi_tokens(str(page.get("title", "")).upper(), str(page.get("highlight", "")).upper())
    fh = _font("display", 86)
    lh = 92
    lines = _wrap_tokens(d, tokens, fh, W - 2 * pad)
    hl_h = len(lines) * lh
    sub = page.get("subtitle") or ""
    fsub = _font("body", 33, 500)
    sub_lines = _wrap(d, sub, fsub, W - 2 * pad)[:2] if sub else []
    sub_h = len(sub_lines) * 42

    base_y = H - 96
    y = base_y - sub_h - (24 if sub_lines else 0) - hl_h - 26 - 46
    # tag pill
    tw = _tw(d, tag, ftag)
    _rr(d, [pad, y, pad + tw + 34, y + 42], 6, fill=_GOLD)
    d.text((pad + 17, y + 8), tag, font=ftag, fill=_INK)
    y += 46 + 26
    y = _draw_headline(d, pad, y, tokens, fh, W - 2 * pad, lh, (255, 255, 255), _GOLD)
    y += 24
    for ln in sub_lines:
        d.text((pad, y), ln, font=fsub, fill=(226, 226, 226))
        y += 42
    return im


def _render_insight(Image, ImageDraw, page, W, H, pad, bg, idx, n):
    on_dark = bg == _DARK
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    _chrome(d, W, pad, idx, n, on_dark, top_rule=True)
    base_col = (245, 245, 245) if on_dark else _INK

    y = 142
    y += _eyebrow(d, pad, y, page.get("eyebrow", ""), _GOLD, size=25) + 14
    tokens = _hi_tokens(str(page.get("title", "")).upper(), str(page.get("highlight", "")).upper())
    hi_col = _HI.get(page.get("hi_color", "green"), _GREEN)
    fh = _font("display", 58)
    y = _draw_headline(d, pad, y, tokens, fh, W - 2 * pad, 64, base_col, hi_col) + 22

    take = page.get("takeaway")
    bar_h = 150 if take else 0
    bar_top = H - 70 - bar_h
    area = (pad, y, W - pad, bar_top - 24)

    if page.get("chart"):
        c = page["chart"]
        _line_chart(d, area, c["series"], c.get("y_fmt", "plain"),
                    c.get("unit", ""), c.get("y_title", ""), c.get("annotations"))
    elif page.get("stat_cards"):
        cards = page["stat_cards"]
        band = (area[0], area[1], area[2], min(area[3], area[1] + 320))
        _stat_cards(d, band, cards, hi_col)

    if take:
        _takeaway(d, (pad, bar_top, W - pad, H - 70), take,
                  [page.get("highlight", "")], hi_col, on_dark)
    return im


def _render_cta(Image, ImageDraw, page, W, H, pad, bg, idx, n):
    on_dark = bg == _DARK
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    _chrome(d, W, pad, idx, n, on_dark, top_rule=True)
    base_col = (245, 245, 245) if on_dark else _INK

    y = 200
    y += _eyebrow(d, pad, y, BRAND_NAME, _GOLD, size=26) + 24
    tokens = _hi_tokens(str(page.get("title", "")).upper(), "ANALYSE")
    fh = _font("display", 72)
    y = _draw_headline(d, pad, y, tokens, fh, W - 2 * pad, 80, base_col, _GREEN) + 30
    fb = _font("body", 34, 500)
    for para in str(page.get("body", "")).split("\n"):
        for ln in _wrap(d, para, fb, W - 2 * pad):
            d.text((pad, y), ln, font=fb, fill=_MUTED)
            y += 46
        y += 8

    url = page.get("url", BRAND_URL)
    qr = _draw_qr(Image, url, 250)
    qy = H - pad - 250
    if qr is not None:
        im.paste(qr, (pad, qy))
        d.text((pad + 286, qy + 96), url, font=_font("label", 40, 600), fill=base_col)
    else:
        fu = _font("label", 46, 700)
        ty = qy + 96
        d.polygon([(pad, ty + 6), (pad, ty + 34), (pad + 24, ty + 20)], fill=_GREEN)
        d.text((pad + 40, ty), url, font=fu, fill=_GREEN)
    return im


def render_carousel(pages, template_key, size_key, photo=None) -> list:
    """Return a list of PIL.Image editorial carousel pages."""
    Image, ImageDraw, ImageFont = _load_pil()
    bg = _PAPER_BG.get(template_key, _CREAM)
    W, H = SIZES.get(size_key, (1080, 1350))
    pad = 64
    n = len(pages)
    imgs = []
    for idx, page in enumerate(pages):
        kind = page.get("kind")
        if kind == "cover":
            im = _render_cover(Image, ImageDraw, page, W, H, pad, photo, idx, n)
        elif kind == "cta":
            im = _render_cta(Image, ImageDraw, page, W, H, pad, bg, idx, n)
        else:
            im = _render_insight(Image, ImageDraw, page, W, H, pad, bg, idx, n)
        imgs.append(im)
    return imgs


def carousel_zip(imgs, base: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, im in enumerate(imgs, 1):
            b = io.BytesIO()
            im.save(b, format="PNG")
            z.writestr(f"{base}_page{i}.png", b.getvalue())
    return buf.getvalue()


# ════════════════════════════════════════════════════════════════════════════
# 5. Streamlit UI
# ════════════════════════════════════════════════════════════════════════════
def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (text or "ts24").lower()).strip("_") or "ts24"


def render_content_studio(df, cls, label, *, api_key: str = "", is_admin: bool = False):
    if not is_admin:
        st.warning("🔒 Content Studio is available to administrators only.")
        return

    st.markdown('<p class="section-title">📣 Content Studio</p>',
                unsafe_allow_html=True)
    st.caption(f"Turn this session into ready-to-post content for **{BRAND_NAME}**. "
               "Analysis → Instagram post in a few clicks. "
               "Editorial carousel: **Cover photo → real charts → CTA**, in the "
               "published Rider Note style.")

    if cls is None or cls.empty:
        st.info("Load a session (upload / online fetch / demo) first — Content "
                "Studio builds posts from the classified laps.")
        return

    cands = build_candidates(df, cls, label)
    if not cands:
        st.info("Not enough classified data in this session to build a post.")
        return

    ai_on = bool(api_key and call_claude)
    st.caption(("🤖 AI copywriting **on** (Claude key set)." if ai_on else
                "✍️ AI copywriting **off** — using data-driven copy. Add a Claude "
                "API key in ⚙️ Settings to upgrade headlines & captions."))

    # ── AI editor-in-chief: rank the angles ──────────────────────────────────
    with st.expander("🧠 AI Editor-in-Chief — what's most interesting?", expanded=True):
        st.caption("Ranked by predicted social appeal (data heuristics).")
        for c in cands[:6]:
            cc1, cc2, cc3 = st.columns([2, 5, 2])
            cc1.markdown(f"**{c['theme']}**")
            cc2.markdown(c["headline_fact"])
            cc3.markdown(f"{stars(c['score'])}  `{c['score']}`")

    st.divider()

    # ── 1) theme ─────────────────────────────────────────────────────────────
    top_theme = cands[0]["theme"]
    c1, c2 = st.columns([3, 2])
    theme = c1.selectbox("1 · Create post about", THEMES,
                         index=THEMES.index("AI Story"), key="cs_theme",
                         help="“AI Story” uses the editor-in-chief's top pick.")
    custom = ""
    if theme == "Custom":
        custom = c1.text_input("Describe the post you want", key="cs_custom",
                               placeholder="e.g. focus on rookie of the weekend")
    if theme == "AI Story":
        c1.caption(f"Top pick → **{top_theme}**")

    cand = _candidate_for_theme(cands, theme)
    if cand is None:
        st.info("No angle available for that theme in this session.")
        return

    template = c2.selectbox("2 · Template", list(TEMPLATES.keys()),
                            index=0, key="cs_template")
    size_key = c2.selectbox("3 · Size", list(SIZES.keys()), index=0, key="cs_size")

    # cover photo (page 1 background) — supplied by the editor per post
    photo_up = st.file_uploader(
        "Cover photo (page 1 background) — optional, use a shot that fits the story",
        type=["jpg", "jpeg", "png", "webp"], key="cs_cover_photo")
    photo_bytes = photo_up.getvalue() if photo_up is not None else None
    if photo_bytes is None:
        st.caption("No cover photo yet → page 1 uses a dark fallback. "
                   "Drop in a rider/bike photo for the published look.")

    # ── 2) headlines ─────────────────────────────────────────────────────────
    st.markdown("#### 4 · Headline")
    sig = f"{theme}|{custom}|{cand['headline_fact']}"
    if st.session_state.get("cs_hl_sig") != sig or st.button(
            "🔄 Regenerate headlines", key="cs_hl_btn"):
        with st.spinner("Writing headlines…"):
            st.session_state["cs_headlines"] = ai_headlines(api_key, cand, label, custom)
        st.session_state["cs_hl_sig"] = sig
    headlines = st.session_state.get("cs_headlines") or ai_headlines("", cand, label)
    opts = [f"{h['text']}   ·   {stars(h['score'])}" for h in headlines]
    pick = st.radio("Pick a headline", opts, key="cs_hl_pick")
    chosen = headlines[opts.index(pick)]["text"]
    chosen = st.text_input("Edit headline", value=chosen, key="cs_hl_edit")

    # ── 3) carousel preview ──────────────────────────────────────────────────
    pages = build_pages(cand, chosen, label, df, cls, cands)
    st.markdown("#### 5 · Carousel preview  ·  Cover → Charts → CTA")
    try:
        imgs = render_carousel(pages, template, size_key, photo=photo_bytes)
        cols = st.columns(len(imgs) or 1)
        for i, im in enumerate(imgs):
            cols[i].image(im, caption=f"Page {i + 1}", use_container_width=True)
    except ModuleNotFoundError:
        imgs = None
        st.warning("🖼️ Image export needs **Pillow**. Add `Pillow` to "
                   "requirements.txt (already listed) and redeploy. Showing the "
                   "text structure instead.")
        for i, p in enumerate(pages, 1):
            st.markdown(f"**Page {i} — {p['kind'].title()}**: {p.get('title','')}")
    except Exception as e:              # noqa: BLE001
        imgs = None
        st.error(f"Couldn't render the carousel: {e}")

    # ── 4) downloads ─────────────────────────────────────────────────────────
    if imgs:
        base = _slugify(f"{BRAND_NAME}_{cand['theme']}_{label}")
        d1, d2 = st.columns(2)
        d1.download_button("⬇️ Download all pages (ZIP)", carousel_zip(imgs, base),
                           file_name=f"{base}.zip", mime="application/zip",
                           use_container_width=True, key="cs_zip")
        # individual PNGs
        with d2.popover("⬇️ Individual PNGs", use_container_width=True):
            for i, im in enumerate(imgs, 1):
                b = io.BytesIO()
                im.save(b, format="PNG")
                st.download_button(f"Page {i}.png", b.getvalue(),
                                   file_name=f"{base}_page{i}.png", mime="image/png",
                                   key=f"cs_png_{i}")

    st.divider()

    # ── 5) caption + hashtags per platform ───────────────────────────────────
    st.markdown("#### 6 · Caption & hashtags")
    platform = st.radio("Post to", PLATFORMS, horizontal=True, key="cs_platform")
    csig = f"{sig}|{chosen}|{platform}"
    if st.session_state.get("cs_cap_sig") != csig or st.button(
            "🔄 Regenerate caption", key="cs_cap_btn"):
        with st.spinner("Writing caption…"):
            st.session_state["cs_caption"] = ai_caption(api_key, cand, chosen, label,
                                                        platform, custom)
        st.session_state["cs_cap_sig"] = csig
    capd = st.session_state.get("cs_caption") or ai_caption("", cand, chosen, label, platform)

    cap_txt = st.text_area("Caption", value=capd["caption"], height=200, key="cs_cap_txt")
    tags = " ".join(capd["hashtags"])
    tag_txt = st.text_input("Hashtags", value=tags, key="cs_cap_tags")
    full = (cap_txt + "\n\n" + tag_txt).strip()
    st.download_button("⬇️ Download caption (.txt)", full,
                       file_name=f"{_slugify(label)}_{platform.lower()}_caption.txt",
                       mime="text/plain", key="cs_cap_dl")
    st.code(full, language=None)

    # ── 6) engagement prediction ─────────────────────────────────────────────
    st.markdown("#### 7 · Predicted engagement")
    pe = predict_engagement(cand, chosen, api_key)
    pc1, pc2 = st.columns([1, 3])
    pc1.metric("Score", f"{pe['score']}%")
    pc1.caption(stars(pe["score"]))
    pc2.success("👍 " + pe["verdict"]) if pe["score"] >= 55 else pc2.warning(
        "✏️ " + pe["verdict"])
    for r in pe["reasons"]:
        pc2.caption("• " + r)

    st.divider()

    # ── 7) Weekly Content batch ──────────────────────────────────────────────
    with st.expander("🚀 Weekly Content — generate a batch from this session"):
        st.caption("One click → a week of posts from the top angles "
                   "(carousel pages + captions), ready to schedule.")
        n = st.slider("How many posts", 2, min(6, len(cands)), min(4, len(cands)),
                      key="cs_weekly_n")
        if st.button("🚀 Generate Weekly Content", key="cs_weekly_btn",
                     type="primary"):
            buf = io.BytesIO()
            built = 0
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                prog = st.progress(0.0)
                for k, c in enumerate(cands[:n]):
                    hl = ai_headlines(api_key, c, label)[0]["text"]
                    pg = build_pages(c, hl, label, df, cls, cands)
                    folder = f"{k + 1:02d}_{_slugify(c['theme'])}"
                    try:
                        ims = render_carousel(pg, template, size_key)
                        for i, im in enumerate(ims, 1):
                            b = io.BytesIO()
                            im.save(b, format="PNG")
                            z.writestr(f"{folder}/page{i}.png", b.getvalue())
                    except Exception:  # noqa: BLE001
                        pass
                    capd = ai_caption(api_key, c, hl, label, "Instagram")
                    z.writestr(f"{folder}/caption.txt",
                               capd["caption"] + "\n\n" + " ".join(capd["hashtags"]))
                    built += 1
                    prog.progress((k + 1) / n)
            st.session_state["cs_weekly_zip"] = buf.getvalue()
            st.success(f"✅ Built {built} posts.")
        if st.session_state.get("cs_weekly_zip"):
            st.download_button("⬇️ Download Weekly Content (ZIP)",
                               st.session_state["cs_weekly_zip"],
                               file_name=f"{_slugify(label)}_weekly_content.zip",
                               mime="application/zip", key="cs_weekly_dl")

    st.caption(f"Posts follow the {BRAND_NAME} narrative so every carousel ends "
               "with a clear call to analyse one's own riding. Admin-only.")
