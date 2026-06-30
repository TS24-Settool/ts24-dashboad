"""
content_studio.py — 📣 Content Studio (admin-only)
==================================================

Turns a loaded MotoGP timing session into ready-to-post social content in a few
clicks:  analysis → Instagram/X/… post.

The studio is built around the **TS24 Rider Note brand narrative**: every post is
a 4-page carousel that teaches, not just reports —

    1. Hook      — a question / surprising headline
    2. Data      — the graph + the key numbers (proof)
    3. Learning  — the takeaway a normal rider can apply
    4. CTA       — "Analyse your own riding with TS24 Rider Note"

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

# accent + scheme palettes used by the PNG renderer
_SCHEMES = {
    "light": {
        "bg": (255, 255, 255), "fg": (17, 17, 17), "muted": (110, 116, 124),
        "accent": (0, 120, 212), "card": (244, 246, 249), "line": (224, 228, 234),
    },
    "dark": {
        "bg": (12, 14, 20), "fg": (245, 247, 250), "muted": (150, 158, 170),
        "accent": (225, 6, 0), "card": (26, 30, 40), "line": (44, 50, 62),
    },
}

# Carousel templates the user picks from
TEMPLATES = {
    "A · Photo + Graph (Light)":  {"scheme": "light", "chart": "inset"},
    "B · Graph Full Screen (Light)": {"scheme": "light", "chart": "full"},
    "C · Dark Theme":             {"scheme": "dark",  "chart": "inset"},
    "D · White Theme":            {"scheme": "light", "chart": "inset"},
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


def build_pages(cand: dict, headline: str, label: str) -> list[dict]:
    """The fixed 4-page brand narrative, filled from the candidate."""
    circuit = (st.session_state.get("mgp_circuit") or "").replace("-", " ").title()
    big = cand["data_points"][0] if cand.get("data_points") else ("", "", "")
    return [
        {"kind": "hook", "eyebrow": circuit or label, "title": headline,
         "subtitle": cand.get("rider") or "", "footer": label},
        {"kind": "data", "eyebrow": "THE DATA", "title": cand["headline_fact"],
         "data_points": cand.get("data_points", []),
         "big_value": str(big[1]), "big_label": str(big[0]), "footer": label},
        {"kind": "learning", "eyebrow": "THE LESSON", "title": "What it means for you",
         "body": cand["learning"], "footer": label},
        {"kind": "cta", "eyebrow": BRAND_NAME, "title": "Want to analyse your riding?",
         "body": f"Every rider has a hidden ideal lap.\n{BRAND_TAG}",
         "url": BRAND_URL, "footer": ""},
    ]


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
    from PIL import Image, ImageDraw, ImageFont          # noqa: F401
    return Image, ImageDraw, ImageFont


_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(ImageFont, size: int, bold: bool = False):
    paths = _FONT_CANDIDATES if bold else _FONT_CANDIDATES[::-1]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:              # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size=size)          # Pillow ≥ 10
    except Exception:                  # noqa: BLE001
        return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _num(val):
    """Best-effort float from a data-point value ('+0.122' -> 0.122, 'P5' -> None)."""
    s = str(val).strip()
    if s.startswith("P"):                          # rank position, not a magnitude
        return None
    s = s.replace("+", "").replace("s", "").replace(",", "").replace("km/h", "")
    try:
        return float(s)
    except Exception:                              # noqa: BLE001
        return None


def _draw_bars(draw, ImageFont, pal, x, y, w, h, data_points):
    """Bar chart — only meaningful when every value shares one unit (e.g. sector
    deltas in s). Caller checks unit homogeneity before calling this."""
    vals = [(lbl, abs(_num(val) or 0.0), val, unit) for lbl, val, unit in data_points]
    mx = max(v[1] for v in vals) or 1.0
    n = len(vals)
    gap = 28
    bw = (w - gap * (n - 1)) / n
    f_lbl = _font(ImageFont, 30, bold=True)
    f_val = _font(ImageFont, 30, bold=True)
    for i, (lbl, mag, raw, unit) in enumerate(vals):
        bx = x + i * (bw + gap)
        bh = max(8, (mag / mx) * (h - 90))
        by = y + (h - 90) - bh
        draw.rounded_rectangle([bx, by, bx + bw, y + (h - 90)], radius=10,
                               fill=pal["accent"])
        vt = f"{raw}{unit}"
        draw.text((bx + bw / 2 - draw.textlength(vt, font=f_val) / 2, by - 40),
                  vt, font=f_val, fill=pal["fg"])
        draw.text((bx + bw / 2 - draw.textlength(str(lbl), font=f_lbl) / 2,
                   y + h - 78), str(lbl), font=f_lbl, fill=pal["muted"])


def _draw_stat_cards(draw, ImageFont, pal, x, y, w, h, data_points):
    """Big-number stat cards in a row — used when the data points mix units
    (e.g. lap time + km/h + rank), where bar heights would mislead."""
    pts = data_points[:3] or [("", "", "")]
    n = len(pts)
    gap = 28
    cw = (w - gap * (n - 1)) / n
    f_val = _font(ImageFont, 56, bold=True)
    f_lbl = _font(ImageFont, 30, bold=True)
    for i, (lbl, val, unit) in enumerate(pts):
        cx = x + i * (cw + gap)
        draw.rounded_rectangle([cx, y, cx + cw, y + h], radius=18, fill=pal["bg"],
                               outline=pal["line"], width=2)
        vt = f"{val}{unit}"
        # shrink to fit the card
        fv = f_val
        for sz in (56, 48, 40, 34):
            fv = _font(ImageFont, sz, bold=True)
            if draw.textlength(vt, font=fv) <= cw - 32:
                break
        draw.text((cx + cw / 2 - draw.textlength(vt, font=fv) / 2, y + h / 2 - 50),
                  vt, font=fv, fill=pal["accent"])
        draw.text((cx + cw / 2 - draw.textlength(str(lbl), font=f_lbl) / 2,
                   y + h - 56), str(lbl), font=f_lbl, fill=pal["muted"])


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


def render_carousel(pages, template_key, size_key) -> list:
    """Return a list of PIL.Image carousel pages."""
    Image, ImageDraw, ImageFont = _load_pil()
    tpl = TEMPLATES.get(template_key, TEMPLATES["D · White Theme"])
    pal = _SCHEMES[tpl["scheme"]]
    W, H = SIZES.get(size_key, (1080, 1350))
    pad = 84
    imgs = []

    for idx, page in enumerate(pages):
        im = Image.new("RGB", (W, H), pal["bg"])
        d = ImageDraw.Draw(im)

        # top accent bar + page counter
        d.rectangle([0, 0, W, 14], fill=pal["accent"])
        f_eye = _font(ImageFont, 34, bold=True)
        eyebrow = str(page.get("eyebrow", "")).upper()
        d.text((pad, 70), eyebrow, font=f_eye, fill=pal["accent"])
        f_pg = _font(ImageFont, 30, bold=True)
        pg = f"{idx + 1}/{len(pages)}"
        d.text((W - pad - d.textlength(pg, font=f_pg), 70), pg,
               font=f_pg, fill=pal["muted"])

        kind = page.get("kind")
        y = 180

        if kind == "hook":
            f_t = _font(ImageFont, 96, bold=True)
            for ln in _wrap(d, page["title"], f_t, W - 2 * pad):
                d.text((pad, y), ln, font=f_t, fill=pal["fg"])
                y += 108
            if page.get("subtitle"):
                f_s = _font(ImageFont, 48, bold=True)
                d.text((pad, y + 24), page["subtitle"], font=f_s, fill=pal["accent"])

        elif kind == "data":
            f_t = _font(ImageFont, 56, bold=True)
            for ln in _wrap(d, page["title"], f_t, W - 2 * pad):
                d.text((pad, y), ln, font=f_t, fill=pal["fg"])
                y += 66
            y += 24
            big_full = (template_key.startswith("B"))
            chart_h = int(H * (0.42 if big_full else 0.34))
            dps = page.get("data_points", [])
            # bars only when ≥3 points share one unit and are all numeric;
            # otherwise stat cards (mixed units → bar heights would mislead).
            units = {u for _, _, u in dps}
            numeric = all(_num(v) is not None for _, v, _ in dps) if dps else False
            use_bars = len(dps) >= 3 and len(units) == 1 and numeric
            if use_bars:
                d.rounded_rectangle([pad, y, W - pad, y + chart_h], radius=24,
                                    fill=pal["card"])
                _draw_bars(d, ImageFont, pal, pad + 40, y + 40,
                           W - 2 * pad - 80, chart_h - 40, dps)
            else:
                _draw_stat_cards(d, ImageFont, pal, pad, y,
                                 W - 2 * pad, chart_h, dps)

        elif kind == "learning":
            f_t = _font(ImageFont, 64, bold=True)
            d.text((pad, y), page["title"], font=f_t, fill=pal["accent"])
            y += 110
            f_b = _font(ImageFont, 50)
            for para in str(page.get("body", "")).split("\n"):
                for ln in _wrap(d, para, f_b, W - 2 * pad):
                    d.text((pad, y), ln, font=f_b, fill=pal["fg"])
                    y += 64
                y += 14

        elif kind == "cta":
            f_brand = _font(ImageFont, 44, bold=True)
            d.text((pad, y), BRAND_NAME, font=f_brand, fill=pal["accent"])
            y += 90
            f_t = _font(ImageFont, 72, bold=True)
            for ln in _wrap(d, page["title"], f_t, W - 2 * pad):
                d.text((pad, y), ln, font=f_t, fill=pal["fg"])
                y += 84
            y += 20
            f_b = _font(ImageFont, 46)
            for para in str(page.get("body", "")).split("\n"):
                d.text((pad, y), para, font=f_b, fill=pal["muted"])
                y += 64
            qr = _draw_qr(Image, page.get("url", BRAND_URL), 240)
            qy = H - pad - 240
            if qr is not None:
                im.paste(qr, (pad, qy))
                f_u = _font(ImageFont, 44, bold=True)
                d.text((pad + 280, qy + 90), page.get("url", BRAND_URL),
                       font=f_u, fill=pal["fg"])
            else:
                f_u = _font(ImageFont, 52, bold=True)
                d.text((pad, qy + 90), "→ " + page.get("url", BRAND_URL),
                       font=f_u, fill=pal["accent"])

        # footer
        if page.get("footer"):
            f_f = _font(ImageFont, 26)
            d.text((pad, H - 56), str(page["footer"]), font=f_f, fill=pal["muted"])
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
               "Every post follows the brand story: **Hook → Data → Lesson → CTA**.")

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
    pages = build_pages(cand, chosen, label)
    st.markdown("#### 5 · Carousel preview  ·  Hook → Data → Lesson → CTA")
    try:
        imgs = render_carousel(pages, template, size_key)
        cols = st.columns(4)
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
                    pg = build_pages(c, hl, label)
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
