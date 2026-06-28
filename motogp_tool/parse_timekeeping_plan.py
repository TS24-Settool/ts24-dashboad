"""
parse_timekeeping_plan.py — read the official MotoGP "Timekeeping Points Plan"
PDF (one per event) and extract the GPS coordinates of the timing points.

The plan lists, with WGS84 GPS:
    FL  = finish line (= start/finish)
    IP1 = 1st intermediate  -> end of Sector 1 (T1)
    IP2 = 2nd intermediate  -> end of Sector 2 (T2)
    IP3 = 3rd intermediate  -> end of Sector 3 (T3)
    Speed, Pit Entry/Exit, TP0..TP4 (extra reference points)

These four points (FL, IP1, IP2, IP3) are exactly the MotoGP 4-sector boundary
positions — so they let us place the sector splits on the circuit precisely,
instead of guessing.

Rows look like:  "IP1 22 110 6.52805 E 52.96199 N"  or  "TP0 6.52734 E 52.96393 N"
"""
from __future__ import annotations

import re

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

_LABELS = ["Pit Entry", "Pit Exit", "Speed", "IP1", "IP2", "IP3", "FL",
           "TP0", "TP1", "TP2", "TP3", "TP4"]
# one regex: a known label, then (optionally id/oc ints), then  lon E  lat N
_ROW = re.compile(
    r"(Pit Entry|Pit Exit|Speed|IP1|IP2|IP3|FL|TP\d)\b[^\d]*"
    r"(?:\d+\s+\d+\s+)?"
    r"(-?\d+\.\d+)\s*E\s+(-?\d+\.\d+)\s*N",
    re.IGNORECASE)


def parse_timekeeping_text(text: str) -> dict:
    """Extract {label: (lon, lat)} from the plan's text."""
    out = {}
    for m in _ROW.finditer(text):
        label = m.group(1).upper().replace(" ", "_")
        out[label] = (float(m.group(2)), float(m.group(3)))
    return out


def parse_timekeeping_bytes(data: bytes) -> dict:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    doc = fitz.open(stream=data, filetype="pdf")
    text = "\n".join(p.get_text() for p in doc)
    doc.close()
    return parse_timekeeping_text(text)


def parse_timekeeping_pdf(path) -> dict:
    return parse_timekeeping_bytes(open(path, "rb").read())


def sector_points(plan: dict):
    """Return (FL, IP1, IP2, IP3) as (lon,lat) tuples, or None if incomplete."""
    need = ["FL", "IP1", "IP2", "IP3"]
    if all(k in plan for k in need):
        return tuple(plan[k] for k in need)
    return None


if __name__ == "__main__":
    import sys, json
    p = parse_timekeeping_pdf(sys.argv[1])
    print(json.dumps(p, indent=1))
    print("sector points (FL,IP1,IP2,IP3):", sector_points(p))
