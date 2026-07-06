"""
parse_session_pdf.py — Parse the official MotoGP "Session" results PDF bundle.

The Session PDF (resources.motogp.com/files/results/<year>/<GP>/<class>/<ses>/
Session.pdf) packs every end-of-session document into one file:

    CLASSIFICATION AFTER n LAPS      <- official result (Pos/Pts/#/Rider/Team/
                                        Motorcycle/Total Time/Km-h/Gap) +
                                        conditions + race-direction log
    WORLD CHAMPIONSHIP CLASSIFICATION
    LAP CHART / FASTEST LAP OF EACH RIDER / EVENT BEST MAXIMUM SPEED
    CHRONOLOGICAL ANALYSIS OF PERFORMANCES   <- the same per-lap/per-sector
                                                table the standalone Analysis
                                                PDF carries
    ANALYSIS BY LAP / STARTING GRID / TOP SPEED & AVERAGE / ...

This module extracts:
  * results      — the official classification rows (incl. "Not classified" /
                   "Not finished first lap" sections), with points, total time,
                   average speed and gap
  * conditions   — track condition, air/ground temp, humidity, pole & fastest
                   lap references, race laps/distance
  * race_events  — the race-direction chronology (crashes, penalties, starts)
  * laps         — per-lap/per-sector rows, by running the proven
                   parse_analysis_pdf machinery on the embedded
                   "Chronological Analysis of Performances" pages

`parse_any_bytes()` auto-detects Session vs plain Analysis PDFs so the app can
keep a single upload widget.
"""
from __future__ import annotations

import re
import sys
import json

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None

from .parse_analysis_pdf import (
    _parse_doc, _cluster_rows, _row_tokens, _extract_meta,
    _is_upper_token, _MANUFACTURERS, _RE_INT, _RE_NATION,
)

# ── section titles (as printed on each page) ────────────────────────────────
_S_CLASSIFICATION = "CLASSIFICATION AFTER"
_S_CHRONO = "CHRONOLOGICAL ANALYSIS OF PERFORMANCES"
_S_CHAMPIONSHIP = "WORLD CHAMPIONSHIP CLASSIFICATION"
_S_LAPCHART = "LAP CHART"
_SECTION_TITLES = (
    _S_CLASSIFICATION, _S_CHAMPIONSHIP, _S_LAPCHART,
    "FASTEST LAP OF EACH RIDER", "EVENT BEST MAXIMUM SPEED", _S_CHRONO,
    "ANALYSIS BY LAP", "ROOKIE OF THE YEAR", "RIDERS PERFORMANCE",
    "OFFICIAL STARTING GRID", "TOP SPEED & AVERAGE", "FASTEST LAPS SEQUENCE",
)

# status headings inside the classification table
_STATUS_HEADINGS = {
    "not classified": "Not classified",
    "not finished first lap": "Not finished 1st lap",
    "not started": "Not started",
    "excluded": "Excluded",
    "disqualified": "Disqualified",
}

_RE_TOTALTIME = re.compile(r"^(\d{1,3})'(\d{2})\.(\d{3})$")   # 40'21.905
_RE_GAP_S = re.compile(r"^(\d{1,3})\.(\d{3})$")               # 2.004
_RE_AVGSPD = re.compile(r"^(\d{2,3})\.(\d)$")                 # 175.5
_RE_EVENT_TIME = re.compile(r"^(\d{1,2}:\d{2}'\d{2})\s+(.+)$")  # 14:02'03 RACE START


def _tt_to_s(tok: str):
    m = _RE_TOTALTIME.match(tok)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000.0


# ── page → section mapping ──────────────────────────────────────────────────
def _section_pages(doc) -> dict:
    """{'CLASSIFICATION AFTER': [0,1], 'CHRONOLOGICAL …': [9,...], ...}
    Pages without their own title (continuation pages) belong to the most
    recent titled page above them."""
    out, current = {}, None
    for i in range(doc.page_count):
        text = doc[i].get_text()
        titled = next((t for t in _SECTION_TITLES if t in text), None)
        if titled is not None:
            current = titled
        if current is not None:
            out.setdefault(current, []).append(i)
    return out


def looks_like_session_pdf(doc) -> bool:
    """True when the doc carries the official-classification section (the
    Session bundle — or a standalone Classification PDF)."""
    return any(_S_CLASSIFICATION in doc[i].get_text()
               for i in range(min(3, doc.page_count)))


# ── classification (official result) rows ───────────────────────────────────
def _parse_result_row(toks: list[str], status: str):
    """One classification row -> dict, or None when the row isn't a result
    line. Layout: [Pos [Pts] #] Given.. SURNAME.. NATION Team.. MOTORCYCLE
    TotalTime Km/h [Gap | n lap(s)] — trailing blocks optional (e.g. riders
    who never finished a lap carry no times)."""
    toks = list(toks)

    # trailing numeric block, popped right-to-left: gap → speed → total time
    gap, gap_s, laps_behind = None, None, None
    if len(toks) >= 2 and toks[-1].lower() in ("lap", "laps") \
            and _RE_INT.match(toks[-2]):
        laps_behind = int(toks[-2])
        gap = f"{laps_behind} {toks[-1].lower()}"
        toks = toks[:-2]
    elif toks and (_RE_GAP_S.match(toks[-1]) or
                   (_RE_TOTALTIME.match(toks[-1]) and len(toks) >= 2
                    and _RE_AVGSPD.match(toks[-2]))):
        gap = toks[-1]
        gap_s = _tt_to_s(gap) if "'" in gap else float(gap)
        toks = toks[:-1]
    avg_speed = None
    if toks and _RE_AVGSPD.match(toks[-1]):
        avg_speed = float(toks[-1])
        toks = toks[:-1]
    total_time, total_time_s = None, None
    if toks and _RE_TOTALTIME.match(toks[-1]):
        total_time = toks[-1]
        total_time_s = _tt_to_s(total_time)
        toks = toks[:-1]

    # leading integers: [pos, pts, no] / [pos, no] (0 points) / [no] (DNF rows)
    ints = []
    while toks and _RE_INT.match(toks[0]) and len(ints) < 3:
        ints.append(int(toks.pop(0)))
    if not ints or not toks:
        return None
    if status == "Classified":
        if len(ints) == 3:
            pos, pts, no = ints
        elif len(ints) == 2:
            pos, pts, no = ints[0], 0, ints[1]
        else:
            return None                     # a classified row always has pos+no
    else:
        if len(ints) != 1:
            return None
        pos, pts, no = None, None, ints[0]

    # identity: name runs to the first 3-letter nation token that directly
    # follows an ALL-CAPS surname token (so team codes like KTM/LCR/HRC —
    # always preceded by a mixed-case word — can't be mistaken for it)
    nat_i = next((k for k in range(1, len(toks))
                  if _RE_NATION.match(toks[k]) and _is_upper_token(toks[k - 1])),
                 None)
    if nat_i is None:
        return None
    name, nation, rest = " ".join(toks[:nat_i]), toks[nat_i], toks[nat_i + 1:]
    motorcycle = None
    if rest and rest[-1].upper() in _MANUFACTURERS:
        motorcycle = rest[-1]
        rest = rest[:-1]
    return {
        "status": status, "position": pos, "points": pts, "rider_no": no,
        "rider_name": name, "nation": nation, "team": " ".join(rest) or None,
        "motorcycle": motorcycle, "total_time": total_time,
        "total_time_s": total_time_s, "avg_speed_kmh": avg_speed,
        "gap": gap, "gap_s": gap_s, "laps_behind": laps_behind,
    }


def _parse_classification_pages(doc, pages: list[int]):
    results, status = [], "Classified"
    for p in pages:
        for row in _cluster_rows(doc[p].get_text("words")):
            toks = [t for _, t in _row_tokens(row)]
            low = " ".join(toks).lower().rstrip(":")
            if low in _STATUS_HEADINGS:
                status = _STATUS_HEADINGS[low]
                continue
            if not toks or not _RE_INT.match(toks[0]):
                continue
            r = _parse_result_row(toks, status)
            if r:
                results.append(r)
    return results


# ── conditions + race-direction log ─────────────────────────────────────────
# NOTE: the PDF's raw text stream is scrambled (two overlapping layers), so
# both parsers work on the *visual* rows from _cluster_rows, not raw text.
def _parse_conditions(doc, pages: list[int]) -> dict:
    c = {}
    rows = []
    for p in pages:
        rows += [" ".join(t for _, t in _row_tokens(r))
                 for r in _cluster_rows(doc[p].get_text("words"))]
    for line in rows:
        m = re.search(r"(?:Race|Track)\s*condition:\s*([A-Za-z/ ]+?)\s*(?:Pole|$)", line)
        if m and "condition" not in c:
            c["condition"] = m.group(1).strip()
        m = re.search(r"Air:\s*(\d+)", line)
        if m:
            c["air_c"] = int(m.group(1))
        m = re.search(r"Humidity:\s*(\d+)", line)
        if m:
            c["humidity_pct"] = int(m.group(1))
        m = re.search(r"Ground:\s*(\d+)", line)
        if m:
            c["ground_c"] = int(m.group(1))
        m = re.search(r"Pole Position:\s*(.+?)\s+(\d'\d{2}\.\d{3})\s+(\d{2,3}\.\d)", line)
        if m:
            c["pole_rider"], c["pole_time"] = m.group(1).strip(), m.group(2)
            c["pole_speed_kmh"] = float(m.group(3))
        m = re.search(r"Fastest Lap:\s*(?:Lap\s*(\d+)\s+)?(.+?)\s+(\d'\d{2}\.\d{3})\s+(\d{2,3}\.\d)",
                      line)
        if m:
            c["fastest_lap_no"] = int(m.group(1)) if m.group(1) else None
            c["fastest_rider"], c["fastest_time"] = m.group(2).strip(), m.group(3)
            c["fastest_speed_kmh"] = float(m.group(4))
        m = re.search(r"CLASSIFICATION AFTER\s+(\d+)\s+LAPS?\s*=\s*([\d.]+)\s*KM", line)
        if m:
            c["race_laps"], c["distance_km"] = int(m.group(1)), float(m.group(2))
    return c


def _parse_race_events(doc, pages: list[int]) -> list[dict]:
    out = []
    for p in pages:
        for r in _cluster_rows(doc[p].get_text("words")):
            toks = [t for _, t in _row_tokens(r)]
            m = _RE_EVENT_TIME.match(" ".join(toks))
            if m:
                out.append({"time": m.group(1), "text": m.group(2).strip()})
    return out


# ── lap chart (position per lap) ────────────────────────────────────────────
def _parse_lap_chart(doc, pages: list[int]) -> dict:
    """LAP CHART page -> {'grid': [rider_no in grid order],
    'laps': [{'lap': n, 'order': [rider_no in running order]}, ...]}.
    Riders who retire simply disappear from later rows."""
    grid, laps, seen = [], [], set()
    for p in pages:
        for r in _cluster_rows(doc[p].get_text("words")):
            toks = [t for _, t in _row_tokens(r)]
            # drop the vertical 'L a p s' axis letters clustered into the rows
            toks = [t for t in toks if not (len(t) == 1 and t.isalpha())]
            if not toks:
                continue
            if toks[0] == "Grid":
                nums = [int(t) for t in toks[1:] if t.isdigit()]
                if len(nums) >= 4:
                    grid = nums
                continue
            if not all(t.isdigit() for t in toks) or len(toks) < 5:
                continue
            lap_no, order = int(toks[0]), [int(t) for t in toks[1:]]
            if lap_no in seen or lap_no > 120:      # dedupe / sanity
                continue
            seen.add(lap_no)
            laps.append({"lap": lap_no, "order": order})
    laps.sort(key=lambda d: d["lap"])
    return {"grid": grid, "laps": laps} if laps else {}


# ── world championship classification (points per event) ────────────────────
def _parse_championship(doc, pages: list[int]) -> dict:
    """Riders' championship table -> {'events': [event codes in calendar
    order], 'riders': [{rank, rider_name, nation, points, per_event: {code:
    pts | None}}]}. Values are x-aligned to the header columns; '-' (event
    held, no points) -> 0; a missing column (event not yet held) -> absent.
    Constructor / Team pages (no 'Rider' header) are skipped."""
    events, riders, pending = [], [], None
    for p in pages:
        rows = _cluster_rows(doc[p].get_text("words"))
        header = None
        for r in rows:
            toks = _row_tokens(r)
            words = [t for _, t in toks]
            if "Rider" in words and "Points" in words and "Leader" in words:
                header = toks
                break
        if header is None:                     # constructors / teams page
            continue
        ev_cols = [(x, t) for x, t in header if re.fullmatch(r"[A-Z]{3}", t)]
        named = {t: x for x, t in header if t in ("Points", "Leader", "Prev")}
        if not events:
            events = [t for _, t in ev_cols]
        cols = [(named["Points"], "Points"), (named["Leader"], "Leader")] + \
               ([(named["Prev"], "Prev")] if "Prev" in named else []) + ev_cols
        points_x = named["Points"]

        for r in rows:
            toks = _row_tokens(r)
            words = [t for _, t in toks]
            if not toks or toks is header:
                continue
            # second identity line: 'Jorge [SPA] <sprint/race breakdown…>'
            bracket = next((t for t in words if re.fullmatch(r"\[[A-Z]{3}\]", t)),
                           None)
            if bracket and pending is not None:
                given = " ".join(t for x, t in toks
                                 if x < points_x - 15 and t != bracket)
                if given:
                    pending["rider_name"] = f"{given} {pending['rider_name']}"
                pending["nation"] = bracket.strip("[]")
                riders.append(pending)
                pending = None
                continue
            # first line: rank, SURNAME…, then x-aligned values
            if not (words[0].isdigit() and toks[0][0] < 60):
                continue
            surname = " ".join(t for x, t in toks[1:]
                               if x < points_x - 15 and not t.isdigit())
            if not surname:
                continue
            vals = {}
            for x, t in toks[1:]:
                if x < points_x - 15 or not (t == "-" or t.isdigit()):
                    continue
                col = min(cols, key=lambda c: abs(c[0] - x))
                if abs(col[0] - x) <= 14:
                    vals[col[1]] = 0 if t == "-" else int(t)
            pending = {
                "rank": int(words[0]), "rider_name": surname, "nation": None,
                "points": vals.get("Points"),
                "per_event": {ev: vals[ev] for _, ev in ev_cols if ev in vals},
            }
    if pending is not None:                    # no identity line followed
        riders.append(pending)
    return {"events": events, "riders": riders} if riders else {}


# ── meta ─────────────────────────────────────────────────────────────────────
def _session_name(page0_text: str) -> str | None:
    """The session line printed under the event title. 2026 bundles label the
    race 'GRAND PRIX' and the sprint 'TISSOT SPRINT'; older ones say 'RACE'."""
    lines = [l.strip() for l in page0_text.splitlines() if l.strip()]
    for line in lines:
        up = line.upper()
        if up in ("RACE", "GRAND PRIX"):
            return "Race"
        if up in ("SPRINT", "TISSOT SPRINT"):
            return "Sprint"
        for w in ("FREE PRACTICE", "PRACTICE", "QUALIFYING", "WARM UP", "WARM-UP"):
            if up == w or up.startswith(w + " "):
                return line.title() if line.isupper() else line
    return None


def _tidy_event(ev: str | None) -> str | None:
    """Strip the sponsor title glued onto the GP title by the two-layer PDF
    text ('…OF THE NETHERLANDSTISSOT GRAND PRIX OF TH…')."""
    if not ev:
        return ev
    # _clean_event already cut at the repeated title; drop the sponsor word the
    # overlapping text layer glued onto the venue name.
    ev = re.sub(r"TISSOT$", "", ev).strip()
    return ev or None


# ── entry points ─────────────────────────────────────────────────────────────
def parse_session_bytes(data: bytes) -> dict:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    return _parse_session_doc(fitz.open(stream=data, filetype="pdf"))


def parse_session_pdf(path) -> dict:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    return _parse_session_doc(fitz.open(str(path)))


def parse_any_bytes(data: bytes) -> dict:
    """Auto-detect: Session/Classification bundle -> full parse; otherwise the
    plain Analysis PDF path. Always returns
    {meta, laps, results, conditions, race_events, kind}."""
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required: pip install pymupdf")
    doc = fitz.open(stream=data, filetype="pdf")
    if looks_like_session_pdf(doc):
        return _parse_session_doc(doc)
    parsed = _parse_doc(doc)                       # closes doc
    parsed.update({"results": [], "conditions": {}, "race_events": [],
                   "lap_chart": {}, "championship": {}, "kind": "analysis"})
    return parsed


def _parse_session_doc(doc) -> dict:
    sections = _section_pages(doc)
    cls_pages = sections.get(_S_CLASSIFICATION, [])
    chrono_pages = sections.get(_S_CHRONO, [])

    results = _parse_classification_pages(doc, cls_pages) if cls_pages else []
    conditions = _parse_conditions(doc, cls_pages) if cls_pages else {}
    race_events = _parse_race_events(doc, cls_pages) if cls_pages else []
    lap_chart = _parse_lap_chart(doc, sections.get(_S_LAPCHART, []))
    championship = _parse_championship(doc, sections.get(_S_CHAMPIONSHIP, []))

    laps, meta = [], {}
    if chrono_pages:
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=chrono_pages[0], to_page=chrono_pages[-1])
        parsed = _parse_doc(sub)                  # proven Analysis parser
        laps, meta = parsed["laps"], parsed["meta"]

    # meta fallbacks / fixes from the classification header
    if cls_pages:
        m0 = _extract_meta(doc[cls_pages[0]].get_text(),
                           "\n".join(doc[p].get_text()
                                     for p in range(doc.page_count)))
        for k, v in m0.items():
            if not meta.get(k) and v:
                meta[k] = v
        meta["session"] = _session_name(doc[cls_pages[0]].get_text()) \
            or meta.get("session")
    meta["event"] = _tidy_event(meta.get("event"))
    if conditions.get("condition") and not meta.get("weather"):
        meta["weather"] = conditions["condition"]

    doc.close()
    return {"meta": meta, "laps": laps, "results": results,
            "conditions": conditions, "race_events": race_events,
            "lap_chart": lap_chart, "championship": championship,
            "kind": "session"}


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: parse_session_pdf.py <Session.pdf> [results_out.csv]")
        sys.exit(1)
    res = parse_session_pdf(sys.argv[1])
    print("meta:", json.dumps(res["meta"], ensure_ascii=False))
    print("conditions:", json.dumps(res["conditions"], ensure_ascii=False))
    print(f"results rows : {len(res['results'])}")
    for r in res["results"]:
        print(f"  {str(r['position'] or '-'):>3} pts={str(r['points'] or 0):>2} "
              f"#{r['rider_no']:<3} {r['rider_name']:<28} {r['nation']} "
              f"{(r['motorcycle'] or ''):<8} {(r['total_time'] or ''):<10} "
              f"gap={r['gap'] or ''}  [{r['status']}]")
    print(f"race events  : {len(res['race_events'])}")
    print(f"laps parsed  : {len(res['laps'])}")
    lc = res.get("lap_chart") or {}
    print(f"lap chart    : grid={len(lc.get('grid') or [])} riders, "
          f"{len(lc.get('laps') or [])} laps")
    ch = res.get("championship") or {}
    print(f"championship : {len(ch.get('riders') or [])} riders, "
          f"events={ch.get('events')}")
    for rd in (ch.get("riders") or [])[:5]:
        print(f"   {rd['rank']:>2} {rd['rider_name']:<26} [{rd['nation']}] "
              f"{rd['points']:>3} pts  {rd['per_event']}")
    if len(sys.argv) > 2:
        import csv
        cols = ["status", "position", "points", "rider_no", "rider_name",
                "nation", "team", "motorcycle", "total_time", "total_time_s",
                "avg_speed_kmh", "gap", "gap_s", "laps_behind"]
        with open(sys.argv[2], "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in res["results"]:
                w.writerow({c: r.get(c) for c in cols})
        print("wrote", sys.argv[2])
