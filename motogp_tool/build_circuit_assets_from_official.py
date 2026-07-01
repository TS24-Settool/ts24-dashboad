"""
build_circuit_assets_from_official.py — generate Track-Map image assets straight
from MotoGP's own official "Circuit Information" PDF (one per event, e.g.
resources.motogp.com/files/results/2026/NED/CircuitInformation.pdf).

Unlike build_circuit_assets.py (which draws a placeholder from our bundled GPS
outline — zero licensing risk), this pulls the real Dorna-produced track graphic
and, more importantly, the REAL S/F + I1/I2/I3 timing-loop positions straight
from the PDF's vector text layer (no OCR). That replaces the "equal track
distance" sector-boundary approximation noted in circuit_map.py with the actual
official boundary points.

Licensing note (read before re-running / extending): the source PDF states its
data/results "cannot be reproduced, stored and/or transmitted ... without the
previous express consent by the copyright owner" (c) MotoGP Sports
Entertainment Group. Team decision 2026-07-01 (see CLAUDE.md): used here anyway
for this personal-use tool, with that provenance/caveat kept in each circuit's
metadata.json for the record.

How the map region + labels are found (per PDF page):
  1. Locate the text words "fl"/"i1"/"i2"/"i3"/"s" and cluster them by proximity
     (a page has 1-2 instances: a small header thumbnail + the big detailed
     map — we keep the larger one).
  2. Among the page's vector fill paths, the track "ribbon" is the one with a
     large point count (a curvy multi-segment path) and a non-trivial bbox —
     that filters out text/logo glyphs (also complex fills, but line-height
     thin) and the small coloured label boxes (simple, few points). We pick
     whichever candidate sits closest to the chosen label cluster.
  3. Crop = union(ribbon bbox, label bbox) + a little padding, rendered to PNG.
  4. Label centres -> normalised [0,1] image coordinates (fitz's page space is
     already top-left/y-down, matching the yanchor="top" image convention
     circuit_map.build_image_track_figure expects — no flip needed).

Usage:
    python -m motogp_tool.build_circuit_assets_from_official
    python -m motogp_tool.build_circuit_assets_from_official assen mugello
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import requests

from . import circuit_map, fetch_official

_CIRC_DIR = Path(__file__).parent / "circuits"
_H = {"User-Agent": "TS24-MotoGP/1.0"}

_TARGET_LABELS = {"s", "fl", "i1", "i2", "i3"}
_REQUIRED_LABELS = {"fl", "i1", "i2", "i3"}          # "s" (speed trap) is a bonus
_CLUSTER_DIST = 150     # pt: words within this radius belong to the same map
_RIBBON_MIN_SIZE = 25   # pt: excludes thin text/logo glyph fills
_RIBBON_MAX_SIZE = 350  # pt: excludes page-spanning rules/table borders

# S/F + intermediates, in lap order (FL -> I1 -> I2 -> I3 -> FL): each marks
# the END of one official sector.
_BOUNDARY_TO_SECTOR_END = {"i1": "T1", "i2": "T2", "i3": "T3", "fl": "T4"}


def discover_circuit_info_urls(years) -> dict:
    """slug -> {url, event_label, circuit_name} for the newest
    event_files.circuit_information PDF per circuit, scanning `years`
    most-recent-first (first hit per slug wins)."""
    found = {}
    for year in years:
        sid = fetch_official.season_id(year)
        if not sid:
            continue
        for ev in fetch_official.events(sid):
            url = ((ev.get("event_files") or {}).get("circuit_information") or {}).get("url")
            if not url:
                continue
            circ = ev.get("circuit") or {}
            # short_name/place/nation only — deliberately NOT circ['name'] /
            # ev['name'] (free text): e.g. Brazil's "Autódromo Internacional
            # de Goiânia..." starts with "Aut", which falsely substring-
            # matches the "AUT" (Austria) keyword since no longer/more-
            # specific keyword exists for a circuit outside our known set.
            # short_name first, nation LAST: nation is country-level and
            # wrongly wins countries with 2+ circuits (Spain: Jerez/Aragon/
            # Valencia all have nation "SPA") before the per-round short_name
            # (ARA/VAL/SPA) gets a chance to disambiguate.
            slug = (circuit_map.detect_slug(ev.get("short_name"))
                    or circuit_map.detect_slug(circ.get("place"))
                    or circuit_map.detect_slug(circ.get("nation")))
            if slug and slug not in found:
                found[slug] = {"url": url, "event_label": f"{ev.get('short_name')} {year}",
                                "circuit_name": circ.get("name")}
    return found


def _label_clusters(page) -> list[list[dict]]:
    words = page.get_text("words")
    pts = [{"label": w[4].lower(), "cx": (w[0] + w[2]) / 2, "cy": (w[1] + w[3]) / 2}
           for w in words if w[4].lower() in _TARGET_LABELS]
    n = len(pts)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if math.hypot(pts[i]["cx"] - pts[j]["cx"], pts[i]["cy"] - pts[j]["cy"]) < _CLUSTER_DIST:
                union(i, j)
    clusters: dict[int, list] = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(pts[i])
    return list(clusters.values())


def _bbox(members) -> fitz.Rect:
    xs = [m["cx"] for m in members]
    ys = [m["cy"] for m in members]
    return fitz.Rect(min(xs), min(ys), max(xs), max(ys))


def extract_map_asset(pdf_bytes: bytes):
    """{'png_bytes', 'labels': {'T1'..'T4': {x,y}}, 'speed_trap'?: {x,y}} or
    None when FL/I1/I2/I3 aren't all found (unrecognised layout -> skip, don't
    guess)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]

    clusters = [c for c in _label_clusters(page)
                if _REQUIRED_LABELS <= {m["label"] for m in c}]
    if not clusters:
        return None
    best = max(clusters, key=lambda ms: _bbox(ms).width * _bbox(ms).height)
    label_bbox = _bbox(best)
    label_center = ((label_bbox.x0 + label_bbox.x1) / 2, (label_bbox.y0 + label_bbox.y1) / 2)

    # The track ribbon isn't reliably identifiable by an absolute item-count
    # cutoff (a simple circuit's curve may need far fewer path segments than a
    # twisty one) — instead: among drawings that are plausibly track-sized and
    # centred near this label cluster, the ribbon is the most complex (highest
    # item-count) shape. Small label-box fills have few items; unrelated
    # page-spanning rules/tables are excluded by the size bounds.
    search = label_bbox + (-120, -120, 120, 120)
    cands = []
    for d in page.get_drawings():
        r = d["rect"]
        if not (_RIBBON_MIN_SIZE <= r.width <= _RIBBON_MAX_SIZE
                and _RIBBON_MIN_SIZE <= r.height <= _RIBBON_MAX_SIZE):
            continue
        c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if c not in search:
            continue
        cands.append((len(d["items"]), r))
    if not cands:
        return None

    track_rect = max(cands, key=lambda t: t[0])[1]

    pad = 12
    crop = (track_rect | label_bbox) + (-pad, -pad, pad, pad)
    crop = crop & page.rect

    scale = min(4.0, 900 / max(crop.width, crop.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=crop)

    norm = {m["label"]: {"x": (m["cx"] - crop.x0) / crop.width,
                          "y": (m["cy"] - crop.y0) / crop.height}
            for m in best}
    labels = {sector: norm[boundary] for boundary, sector in _BOUNDARY_TO_SECTOR_END.items()}
    out = {"png_bytes": pix.tobytes("png"), "labels": labels}
    if "s" in norm:
        out["speed_trap"] = norm["s"]
    return out


def build_one(slug: str, url: str, event_label: str, circuit_name: str | None) -> bool:
    r = requests.get(url, headers=_H, timeout=45)
    r.raise_for_status()
    asset = extract_map_asset(r.content)
    if asset is None:
        print(f"  [skip] {slug}: FL/I1/I2/I3 labels not found in {url}")
        return False

    d = _CIRC_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "track_map.png").write_bytes(asset["png_bytes"])

    layout = {"labels": asset["labels"]}
    if "speed_trap" in asset:
        layout["speed_trap"] = asset["speed_trap"]
    (d / "layout.json").write_text(json.dumps(layout, indent=2))

    meta = {
        "circuit_id": slug,
        "name": circuit_name or slug,
        "status": "supported",
        "source": "motogp_official_circuit_information_pdf",
        "source_url": url,
        "source_event": event_label,
        "usage": "personal_limited_user_app",
        "note": ("Track map and real S/F + I1-I3 timing-loop positions extracted "
                  "directly from MotoGP's official Circuit Information PDF (vector "
                  "text/paths, not OCR/Sporting-Maps placeholder). The source PDF "
                  "states its data/results “cannot be reproduced, stored and/or "
                  "transmitted ... without the previous express consent by the "
                  "copyright owner” (© MotoGP Sports Entertainment Group). Used "
                  "here for personal/internal analysis per team decision 2026-07-01 "
                  "(see CLAUDE.md)."),
    }
    (d / "metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"  [ok]   {slug}: {event_label}")
    return True


def main(argv):
    only = {s.lower() for s in argv} or None
    years = [2026, 2025, 2024, 2023, 2022]
    print(f"Scanning seasons {years} for event_files.circuit_information ...")
    found = discover_circuit_info_urls(years)
    if only:
        found = {slug: info for slug, info in found.items() if slug in only}
    print(f"Found {len(found)} circuit(s) with a Circuit Information PDF.")

    ok, skipped = [], []
    for slug, info in sorted(found.items()):
        try:
            if build_one(slug, info["url"], info["event_label"], info.get("circuit_name")):
                ok.append(slug)
            else:
                skipped.append(slug)
        except Exception as e:  # noqa: BLE001 — one bad circuit shouldn't kill the run
            print(f"  [error] {slug}: {e}")
            skipped.append(slug)
        time.sleep(0.3)

    missing = sorted(set(circuit_map.CIRCUIT_COORDS) - found.keys()) if not only else []
    print(f"\nDone: {len(ok)} built, {len(skipped)} skipped/failed.")
    if missing:
        print(f"Not found in {years}: {missing}")


if __name__ == "__main__":
    main(sys.argv[1:])
