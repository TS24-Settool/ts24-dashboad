"""
parse_analysis_pdf.py — Parse the official MotoGP "Chronological Analysis of
Performances" PDF into a clean per-lap / per-sector table.

The official Analysis PDF (one per session, freely downloadable from motogp.com
and for every MotoGP / Moto2 / Moto3 session) lays each rider's run out as:

    Lap | Lap Time | T1 | T2 | T3 | T4 | Speed

where T1..T4 are the four intermediate sector times and, for full laps,
T1 + T2 + T3 + T4 == Lap Time. This is exactly the granularity needed to
compare every rider, every lap, every sector — and to build user-defined
"microsectors" by subdividing the four official sectors.

Output: a dict { "meta": {...}, "laps": [ {rider_no, rider_name, ...,
t1, t2, t3, t4, lap_time_s, speed, pit, cancelled}, ... ] }

Pure Python (PyMuPDF only). No Java / Docker / live API required — the user
downloads the session's Analysis PDF and feeds it in.
"""
from __future__ import annotations

import re
import sys
import csv
import json
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

# ── token patterns ──────────────────────────────────────────────────────────
_RE_SECTOR = re.compile(r"^(\d{1,2}\.\d{3})(\*?)$")      # 26.068  /  31.839*
_RE_SPEED = re.compile(r"^(\d{2,3}\.\d)$")               # 339.6  /  106.4
_RE_LAPTIME = re.compile(r"^(\d:?\d{0,2}'?\d{2}\.\d{3})(\*?)$")  # 1'57.714 / 2'29.580
_RE_LAPTIME_STRICT = re.compile(r"^(\d)'(\d{2})\.(\d{3})(\*?)$")  # 1'57.714
_RE_INT = re.compile(r"^\d{1,2}$")
_RE_ORDINAL = re.compile(r"^\d{1,3}(st|nd|rd|th)$")
_RE_NATION = re.compile(r"^[A-Z]{3}$")

_MANUFACTURERS = {
    "YAMAHA", "HONDA", "DUCATI", "APRILIA", "KTM", "SUZUKI", "KAWASAKI",
    "BMW", "MV", "TRIUMPH", "KALEX", "BOSCOSCURO", "HUSQVARNA", "GASGAS",
    "CFMOTO", "FANTIC", "MT", "FORWARD", "PRUSTEL", "TECH3", "Hts" ,
}

_SESSION_KEYS = ("Free Practice", "Practice", "Qualifying", "Warm Up",
                 "Warm-Up", "Race", "Sprint", "Tissot")


def _laptime_to_s(tok: str):
    """'1\\'57.714' -> 117.714  (seconds, float). Returns None if unparseable."""
    m = _RE_LAPTIME_STRICT.match(tok)
    if not m:
        return None
    minutes, secs, ms = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return minutes * 60 + secs + ms / 1000.0


def _cluster_rows(words, y_tol=5.0):
    """Group (x0,y0,...,word) tuples into visual rows by y proximity."""
    items = sorted(words, key=lambda w: (round(w[1], 1), w[0]))
    rows, cur, cur_y = [], [], None
    for w in items:
        y = w[1]
        if cur_y is None or abs(y - cur_y) <= y_tol:
            cur.append(w)
            cur_y = y if cur_y is None else cur_y
        else:
            rows.append(cur)
            cur, cur_y = [w], y
    if cur:
        rows.append(cur)
    return rows


def _row_tokens(row):
    """row -> list of (x0, token) sorted by x."""
    return sorted([(w[0], w[4]) for w in row], key=lambda t: t[0])


def _extract_meta(page0_text: str) -> dict:
    meta = {"category": None, "session": None, "event": None, "circuit_len_m": None}
    for raw in page0_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if meta["category"] is None and re.search(r"Moto(GP|2|3|E)", line):
            meta["category"] = re.search(r"Moto(?:GP|2|3|E)", line).group(0)
        if meta["session"] is None and any(k in line for k in _SESSION_KEYS) \
                and "Results and timing" not in line and "Tissot" not in line:
            meta["session"] = line
        if meta["circuit_len_m"] is None:
            m = re.search(r"(\d{3,5})\s*m\.", line)
            if m:
                meta["circuit_len_m"] = int(m.group(1))
        if meta["event"] is None and line.isupper() and len(line) > 6 \
                and "RESULTS" not in line and "ANALYSIS" not in line:
            meta["event"] = line
    return meta


def parse_analysis_pdf(path) -> dict:
    """Parse from a filesystem path."""
    return _parse_doc(fitz.open(str(path)) if fitz else None)


def parse_analysis_bytes(data: bytes) -> dict:
    """Parse from raw PDF bytes (e.g. a Streamlit file_uploader upload)."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    return _parse_doc(fitz.open(stream=data, filetype="pdf"))


def _parse_doc(doc) -> dict:
    if fitz is None or doc is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    meta = _extract_meta(doc[0].get_text())

    laps = []
    # Rider/run context persists across columns AND pages: in the two-column
    # layout a rider's runs flow down the left column then continue at the top
    # of the right column / next page with no repeated header.
    state = {"rider": {"no": None, "name": None, "team": None,
                       "manuf": None, "nation": None},
             "run_no": 0, "front": None, "rear": None}
    for page in doc:
        x_mid = page.rect.width / 2.0
        words = page.get_text("words")
        for lo, hi in ((0, x_mid), (x_mid, page.rect.width)):
            col = [w for w in words if lo <= w[0] < hi]
            if not col:
                continue
            _parse_column(_cluster_rows(col), laps, state)
    doc.close()
    return {"meta": meta, "laps": laps}


def _parse_column(rows, laps, state):
    """Walk one column top-to-bottom, tracking rider/run context in `state`
    (shared across columns and pages so cross-boundary runs stay attributed)."""
    word_rows = [[t for _, t in _row_tokens(r)] for r in rows]  # tokens per row

    for i, row in enumerate(rows):
        toks = _row_tokens(row)
        words_only = word_rows[i]
        text = " ".join(words_only)

        # ── rider header: anchored on the "Runs=.. Total laps=.." line ──
        if "Runs=" in text or any(w.startswith("Runs=") for w in words_only):
            hdr = _read_rider_header(word_rows, i)
            if hdr["no"] is not None or hdr["name"]:
                state["rider"] = hdr
                state["run_no"] = 0
                state["front"] = state["rear"] = None
            continue

        # ── run header: "Front Tyre"/"Rear Tyre" or "Run #" line ──
        if ("Front" in words_only and "Tyre" in words_only) or \
                ("Run" in words_only and "#" in words_only):
            state["run_no"] += 1
            # capture compounds like Slick-Hard
            comps = [w for w in words_only if "-" in w and any(
                k in w for k in ("Slick", "Soft", "Medium", "Hard", "Rain", "Wet"))]
            if len(comps) >= 2:
                state["front"], state["rear"] = comps[0], comps[1]
            elif len(comps) == 1:
                state["front"] = comps[0]
            continue

        # ── lap row: >= 3 sector tokens + a leading lap number ──
        sect_toks = [(x, t) for x, t in toks if _RE_SECTOR.match(t)]
        if len(sect_toks) < 3:
            continue
        ints = [(x, t) for x, t in toks if _RE_INT.match(t)]
        if not ints:
            continue
        lap_no = int(min(ints, key=lambda p: p[0])[1])  # leading int = lap number

        sectors, cancelled = [], False
        for _, t in sect_toks[:4]:
            m = _RE_SECTOR.match(t)
            sectors.append(float(m.group(1)))
            if m.group(2) == "*":
                cancelled = True
        while len(sectors) < 4:
            sectors.append(None)

        speed = None
        for _, t in toks:
            if _RE_SPEED.match(t):
                speed = float(t)
                break

        lap_time_s = None
        for _, t in toks:
            s = _laptime_to_s(t.rstrip("*"))
            if s is not None:
                lap_time_s = s
                if t.endswith("*"):
                    cancelled = True
                break

        pit = "P" in words_only

        rider = state["rider"]
        laps.append({
            "rider_no": rider["no"],
            "rider_name": rider["name"],
            "team": rider["team"],
            "manufacturer": rider["manuf"],
            "nation": rider["nation"],
            "run_no": state["run_no"] or None,
            "front_tyre": state["front"],
            "rear_tyre": state["rear"],
            "lap_no": lap_no,
            "t1": sectors[0], "t2": sectors[1], "t3": sectors[2], "t4": sectors[3],
            "speed": speed,
            "lap_time_s": lap_time_s,
            "pit": pit,
            "cancelled": cancelled,
        })


def _is_lapish(words):
    """True if a row looks like lap data (>=3 sector tokens) — never a header."""
    return sum(1 for w in words if _RE_SECTOR.match(w)) >= 3


def _name_tokens(words, nation=None):
    """Pick the rider-name tokens (e.g. 'Franco', 'MORBIDELLI') from a row,
    excluding position / number / manufacturer / nation / markers."""
    out = []
    for w in words:
        if _RE_ORDINAL.match(w) or _RE_INT.match(w):
            continue
        if w.upper() in _MANUFACTURERS:
            continue
        if nation and w == nation:
            continue
        core = w.replace("'", "").replace("-", "").replace(".", "")
        if core.isalpha() and len(core) > 1:
            out.append(w)
    return out


def _read_rider_header(word_rows, runs_idx):
    """Read the rider header above the 'Runs=' row. The header tokens
    (position, number, name, manufacturer, nation, team) may be spread across a
    few rows or merged onto one clustered row, e.g.
    ['1st','21','Franco','MORBIDELLI','YAMAHA'] then ['Petronas','Yamaha','SRT'].
    Anchor on the row carrying the position ordinal; only rider_no is essential."""
    rider = {"no": None, "name": None, "team": None, "manuf": None, "nation": None}
    lo = max(0, runs_idx - 6)

    # identity row = last non-lap row before Runs= that carries an ordinal
    ident_i = None
    for j in range(lo, runs_idx):
        w = word_rows[j]
        if not _is_lapish(w) and any(_RE_ORDINAL.match(t) for t in w):
            ident_i = j
    if ident_i is None:
        return rider

    words = word_rows[ident_i]
    nums = [t for t in words if _RE_INT.match(t)]
    if nums:
        rider["no"] = int(nums[0])
    for t in words:
        if t.upper() in _MANUFACTURERS:
            rider["manuf"] = t
            break
    for t in words:
        if _RE_NATION.match(t) and t.upper() not in _MANUFACTURERS:
            rider["nation"] = t
            break
    nm = _name_tokens(words, rider["nation"])
    # name may live on the row just above the ordinal row instead
    if not nm and ident_i - 1 >= lo:
        nm = _name_tokens(word_rows[ident_i - 1], rider["nation"])
    if nm:
        rider["name"] = " ".join(nm)

    # team = first plain row (no '=', no ordinal, not lap data) below identity
    for j in range(ident_i + 1, runs_idx):
        t = word_rows[j]
        if t and "=" not in " ".join(t) and not _is_lapish(t) \
                and not any(_RE_ORDINAL.match(x) for x in t) \
                and t[0].upper() not in _MANUFACTURERS:
            rider["team"] = " ".join(t)
            break
    return rider


# ── CLI ─────────────────────────────────────────────────────────────────────
def _flatten_csv(result, out_path):
    cols = ["rider_no", "rider_name", "manufacturer", "team", "nation", "run_no",
            "front_tyre", "rear_tyre", "lap_no", "lap_time_s",
            "t1", "t2", "t3", "t4", "speed", "pit", "cancelled"]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for lap in result["laps"]:
            w.writerow({c: lap.get(c) for c in cols})


def _validate(result):
    full = [l for l in result["laps"]
            if not l["cancelled"] and not l["pit"] and l["lap_time_s"]
            and all(l[s] is not None for s in ("t1", "t2", "t3", "t4"))]
    ok = 0
    worst = 0.0
    for l in full:
        ssum = l["t1"] + l["t2"] + l["t3"] + l["t4"]
        diff = abs(ssum - l["lap_time_s"])
        if diff < 0.05:
            ok += 1
        worst = max(worst, diff) if diff < 5 else worst
    return len(result["laps"]), len(full), ok, worst


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: parse_analysis_pdf.py <analysis.pdf> [out.csv]")
        sys.exit(1)
    src = sys.argv[1]
    res = parse_analysis_pdf(src)
    total, full, ok, worst = _validate(res)
    riders = sorted({l["rider_no"] for l in res["laps"] if l["rider_no"]})
    print("meta:", json.dumps(res["meta"], ensure_ascii=False))
    print(f"laps parsed     : {total}")
    print(f"riders detected : {len(riders)}  -> {riders}")
    print(f"full clean laps : {full}")
    print(f"checksum T1+T2+T3+T4==LapTime : {ok}/{full} within 0.05s "
          f"(worst {worst:.3f}s)")
    if len(sys.argv) > 2:
        _flatten_csv(res, sys.argv[2])
        print("wrote", sys.argv[2])
