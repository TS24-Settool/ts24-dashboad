"""
build_circuit_assets.py — generate Track-Map *image assets* for the MotoGP page.

Each MotoGP circuit can have an image-based Track Map asset:

    circuits/<slug>/track_map.png   the track drawn as a background image
    circuits/<slug>/layout.json     normalised S/F + T1..T4 labels + corners + arcs
    circuits/<slug>/metadata.json   provenance (keeps the Sporting Maps source_url)

This builder renders that PNG from the racing-ordered GPS outline we already bundle
(circuits/<slug>.json), so the feature works today with zero licensing risk. The
metadata records `source_url` for Sporting Maps as the *intended* source for a
future swap: to use the real Sporting Maps artwork, just drop its image in as
track_map.png and adjust layout.json — the loader/renderer don't care where the
PNG came from (when an image lacks `outline_norm`, the renderer falls back to
placing coloured T1..T4 markers at the label positions instead of arcs).

Usage:
    python -m motogp_tool.build_circuit_assets mugello
    python -m motogp_tool.build_circuit_assets mugello --size 1200
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

_CIRC_DIR = Path(__file__).parent / "circuits"

# Where Sporting Maps art is *intended* to come from (kept for future cleanup /
# licensing review — see the user's brief). The current PNG is generated locally.
SPORTINGMAPS_URL = "https://www.sportingmaps.com/motorsports/motogp"

_PRETTY = {
    "mugello": "Mugello Circuit",
    "losail": "Lusail International Circuit",
    "portimao": "Algarve International Circuit",
    "barcelona": "Circuit de Barcelona-Catalunya",
    "circuit-of-the-americas": "Circuit of the Americas",
    "red-bull-ring": "Red Bull Ring",
    "silverstone": "Silverstone Circuit",
    "assen": "TT Circuit Assen",
}


def _project(outline):
    """lon/lat -> equirectangular X,Y (metres-ish, north up)."""
    lat0 = sum(p[1] for p in outline) / len(outline)
    k = math.cos(math.radians(lat0))
    X = [p[0] * k for p in outline]
    Y = [p[1] for p in outline]
    return X, Y, k


def build_asset(slug: str, size: int = 1000, margin: int = 110,
                track_width: int = 16) -> dict:
    """Render circuits/<slug>.json -> circuits/<slug>/{track_map.png,layout.json,
    metadata.json}. Returns the layout dict."""
    src = _CIRC_DIR / f"{slug}.json"
    if not src.exists():
        raise FileNotFoundError(f"no bundled outline for '{slug}' ({src})")
    raw = json.load(open(src))
    outline = raw["outline"]
    N = len(outline)
    if N < 8:
        raise ValueError(f"'{slug}' outline too short ({N} points)")

    X, Y, k = _project(outline)
    xmin, xmax, ymin, ymax = min(X), max(X), min(Y), max(Y)
    spanx, spany = (xmax - xmin) or 1e-9, (ymax - ymin) or 1e-9
    W = H = int(size)
    scale = min((W - 2 * margin) / spanx, (H - 2 * margin) / spany)
    ox = (W - spanx * scale) / 2.0
    oy = (H - spany * scale) / 2.0

    def to_px(i):
        px = ox + (X[i] - xmin) * scale
        py = oy + (ymax - Y[i]) * scale          # flip Y so north is up
        return (px, py)

    pts = [to_px(i) for i in range(N)]
    if pts[0] != pts[-1]:
        pts.append(pts[0])                       # close the loop visually
    norm = [(round(px / W, 4), round(py / H, 4)) for px, py in pts]

    # render the neutral tarmac band (coloured sector arcs are drawn at runtime)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.line(pts, fill=(170, 177, 186, 255), width=track_width + 6, joint="curve")
    d.line(pts, fill=(120, 128, 138, 255), width=track_width, joint="curve")
    out_dir = _CIRC_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    img.save(out_dir / "track_map.png")

    # anchors from the geometry
    def nearest_idx(lonlat):
        x, y = lonlat[0] * k, lonlat[1]
        return min(range(N), key=lambda i: (X[i] - x) ** 2 + (Y[i] - y) ** 2)

    cx = sum(p[0] for p in norm) / len(norm)
    cy = sum(p[1] for p in norm) / len(norm)

    def outward(nx, ny, amt):
        vx, vy = nx - cx, ny - cy
        m = math.hypot(vx, vy) or 1.0
        return (round(min(0.97, max(0.03, nx + vx / m * amt)), 4),
                round(min(0.97, max(0.03, ny + vy / m * amt)), 4))

    sf_idx = nearest_idx(raw.get("start_finish") or outline[0])
    sf = {"x": norm[sf_idx][0], "y": norm[sf_idx][1]}

    # T1..T4 label anchors at the mid-point of each (default equal-quarter) sector
    mids = [0.125, 0.375, 0.625, 0.875]
    labels = {}
    for i, frac in enumerate(mids):
        nx, ny = norm[int(frac * N) % N]
        lx, ly = outward(nx, ny, 0.075)
        labels[f"T{i + 1}"] = {"x": lx, "y": ly}

    corners = []
    for c in raw.get("corners", []):
        nx, ny = norm[nearest_idx(c["lonlat"])]
        ax, ay = outward(nx, ny, 0.045)
        corners.append({"n": c.get("n"), "x": ax, "y": ay})

    layout = {
        "image": "track_map.png",
        "width": W, "height": H,
        "origin": "top_left", "coords": "normalized_0_1",
        "start_finish": sf,
        "labels": labels,
        "sectors": [{"id": f"T{i + 1}", "color_key": f"sector_t{i + 1}"}
                    for i in range(4)],
        "sector_bounds": [0.0, 0.25, 0.5, 0.75, 1.0],
        "outline_norm": norm,
        "corners": corners,
    }
    json.dump(layout, open(out_dir / "layout.json", "w"), indent=2)

    metadata = {
        "circuit_id": slug,
        "name": _PRETTY.get(slug, slug.replace("-", " ").title()),
        "source": "generated_from_bundled_gps_outline",
        "intended_source": "Sporting Maps",
        "source_url": SPORTINGMAPS_URL,
        "usage": "personal_limited_user_app",
        "note": ("Placeholder track image rendered from the bundled racing-line "
                 "GPS outline (OSM-derived). To use the Sporting Maps artwork, "
                 "replace track_map.png and adjust layout.json; keep source_url "
                 "for licensing review before any public/commercial release."),
    }
    json.dump(metadata, open(out_dir / "metadata.json", "w"), indent=2,
              ensure_ascii=False)
    return layout


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    size = 1000
    if "--size" in sys.argv:
        size = int(sys.argv[sys.argv.index("--size") + 1])
    if not args:
        print("usage: python -m motogp_tool.build_circuit_assets <slug> [--size N]")
        sys.exit(1)
    for slug in args:
        lay = build_asset(slug, size=size)
        print(f"built circuits/{slug}/  ·  {len(lay['outline_norm'])} pts  ·  "
              f"S/F {lay['start_finish']}  ·  {len(lay['corners'])} corners")
