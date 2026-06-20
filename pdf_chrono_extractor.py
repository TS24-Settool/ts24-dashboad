#!/usr/bin/env python3
"""
pdf_chrono_extractor.py — WorldSSP Chronological Analysis + Results 抽出
=========================================================================
07_RESULTS/ 以下の公式PDFから
  1. 全ライダーのラップ別セクタータイム (Chronological Analysis 1.5ページ)
  2. セッション結果 (Results 1.2ページ)  ← 既存 race_results と互換
を抽出し ts24_unified.db の pdf_lap_times / pdf_session_results テーブルへ保存。

使用方法:
  python pdf_chrono_extractor.py --all           ← 07_RESULTS/ 以下を全スキャン
  python pdf_chrono_extractor.py --file FILE.pdf
  python pdf_chrono_extractor.py --all --force   ← 既インポート済みも再処理

依存: pdfplumber  (pip install pdfplumber --break-system-packages)
"""
from __future__ import annotations
import argparse, re, sqlite3, sys, logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pdfplumber

SCRIPT_DIR   = Path(__file__).parent
DATA_ROOT    = SCRIPT_DIR.parent
RESULTS_ROOT = DATA_ROOT / "07_RESULTS"
DB_PATH      = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [CHR] %(message)s",
                    datefmt="%H:%M:%S",
                    handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)

# ── DB セットアップ ────────────────────────────────────────────────────────
DDL = """
CREATE TABLE IF NOT EXISTS pdf_lap_times (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round         TEXT,
    circuit       TEXT,
    session_type  TEXT,
    date          TEXT,
    position      INTEGER,
    rider_num     INTEGER,
    rider_name    TEXT,
    lap_no        INTEGER,
    seg1          REAL,
    seg2          REAL,
    seg3          REAL,
    seg4          REAL,
    lap_time      TEXT,
    lap_time_s    REAL,
    speed         REAL,
    local_time    TEXT,
    is_outlap     INTEGER DEFAULT 0,
    is_pit        INTEGER DEFAULT 0,
    is_cancelled  INTEGER DEFAULT 0,
    source_file   TEXT,
    imported_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS pdf_session_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round         TEXT,
    circuit       TEXT,
    session_type  TEXT,
    date          TEXT,
    position      INTEGER,
    rider_num     INTEGER,
    rider_name    TEXT,
    nationality   TEXT,
    team          TEXT,
    bike          TEXT,
    laps          INTEGER,
    total_time    TEXT,
    gap           TEXT,
    best_lap      TEXT,
    best_lap_s    REAL,
    seg1_best     REAL,
    seg2_best     REAL,
    seg3_best     REAL,
    seg4_best     REAL,
    ideal_time_s  REAL,
    top_speed     REAL,
    source_file   TEXT,
    imported_at   TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_plt_round   ON pdf_lap_times(round, session_type, rider_num);
CREATE INDEX IF NOT EXISTS idx_psr_round   ON pdf_session_results(round, session_type);
"""

def _ensure_tables(conn):
    conn.executescript(DDL)
    conn.commit()

def _already_imported(conn, source_file: str) -> bool:
    n = conn.execute(
        "SELECT COUNT(*) FROM pdf_lap_times WHERE source_file=?", (source_file,)
    ).fetchone()[0]
    return n > 0

# ── PDF メタ情報解析 ───────────────────────────────────────────────────────
_ROUND_MAP = {
    "ROUND11": "ROUND11", "ROUND12": "ROUND12",
    "ROUND1": "ROUND1", "ROUND2": "ROUND2", "ROUND3": "ROUND3",
    "ROUND4": "ROUND4", "ROUND5": "ROUND5",
}
_SESSION_MAP = {
    "Free Practice": "FP", "Superpole": "SP", "QP": "QP",
    "Race 1": "RACE1", "Race 2": "RACE2",
    "Warm Up 1": "WUP1", "Warm Up 2": "WUP2",
}

def _parse_meta(pages) -> dict:
    """1ページ目からラウンド・サーキット・セッション・日付を抽出"""
    meta = {"round": "UNK", "circuit": "UNK", "session_type": "UNK", "date": None}
    for pg in pages[:2]:
        text = pg.extract_text() or ""
        # Circuit
        m = re.search(r'([\w\s]+Circuit|Balaton Park|Phillip Island|Portimão|Assen|Aragon|Jerez|Estoril|Most)', text, re.I)
        if m:
            circ = m.group(1).strip().upper()
            circ = circ.replace("PHILLIP ISLAND CIRCUIT","PHILLIP ISLAND").replace("BALATON PARK CIRCUIT","BALATON")
            circ = circ.replace(" CIRCUIT","").replace("PORTIMÃO","PORTIMAO")
            meta["circuit"] = circ
        # Round from file path or text
        m = re.search(r'Round\s+(\d+)|ROUND\s*(\d+)', text, re.I)
        if m:
            n = int(m.group(1) or m.group(2))
            meta["round"] = f"ROUND{n}"
        # Session type
        for k, v in _SESSION_MAP.items():
            if k.lower() in text.lower():
                meta["session_type"] = v
                break
        # Date
        m = re.search(r'(\d{2}/\d{2}/\d{4})', text)
        if m:
            try:
                from datetime import datetime as dt
                meta["date"] = dt.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
            except:
                pass
        if meta["round"] != "UNK" and meta["session_type"] != "UNK":
            break
    return meta

def _lap_time_to_s(s: str) -> float | None:
    """1'43.327 or 1:43.327 → seconds"""
    s = s.strip("CP ")
    m = re.match(r"(\d+)['\:](\d+\.\d+)", s)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(s)
    except:
        return None

# ── ラップ行パース ─────────────────────────────────────────────────────────
# 例: "1 31.582 25.054 29.726 19.952 1'46.314 240,5 11:24'29.126"
_LAP_RE = re.compile(
    r"^(\d+)\s+"                          # lap_no
    r"([\d':.]+[CP]*)\s+"                 # seg1 or pit-time
    r"([\d.]+)\s+"                        # seg2
    r"([\d.]+)\s+"                        # seg3
    r"([\d.]+)\s+"                        # seg4
    r"([\d':.]+[CP]*)\s*"                 # lap_time
    r"([\d,]+)?\s*"                       # speed (optional)
    r"(\d+:\d+['\:]\d+\.\d+)?",          # local_time (optional)
    re.X
)
# アウトラップ（ラップ番号なし、セクター3つ）
_OUTLAP_RE = re.compile(
    r"^([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+"  # seg2 seg3 seg4
    r"(\d+:\d+['\:]\d+\.\d+)"              # local_time
)

def _parse_lap_line(line: str) -> dict | None:
    line = line.strip()
    m = _LAP_RE.match(line)
    if not m:
        return None
    lap_no   = int(m.group(1))
    seg1_raw = m.group(2)
    seg2     = float(m.group(3))
    seg3     = float(m.group(4))
    seg4     = float(m.group(5))
    lt_raw   = m.group(6)
    speed_s  = (m.group(7) or "").replace(",", ".")
    loc_time = m.group(8) or ""

    is_pit      = "P" in seg1_raw or "P" in lt_raw
    is_cancelled= "C" in lt_raw

    # seg1: pit出口は長い値（例 4'04.092）
    try:
        seg1 = _lap_time_to_s(seg1_raw) if "'" in seg1_raw or ":" in seg1_raw else float(seg1_raw)
    except:
        seg1 = None

    lt_s = _lap_time_to_s(lt_raw.strip("CP"))
    # lap_time 表示用
    lt_disp = lt_raw.strip("CP ").replace(":", "'").replace(".",",",1) if lt_s else lt_raw

    try:
        speed = float(speed_s) if speed_s else None
    except:
        speed = None

    return {
        "lap_no": lap_no, "seg1": seg1, "seg2": seg2, "seg3": seg3, "seg4": seg4,
        "lap_time": lt_raw.strip("CP "), "lap_time_s": lt_s,
        "speed": speed, "local_time": loc_time,
        "is_outlap": 0, "is_pit": int(is_pit), "is_cancelled": int(is_cancelled),
    }

# ── Chronological Analysis ページパース ───────────────────────────────────
# 見出し: "5° 52 J. ALCOBA (1'43.327)"
_RIDER_HDR = re.compile(r"(\d+)°\s+(\d+)\s+([\w.]+\s+[\w.]+(?:\s+[\w.]+)?)\s+\(([\d':.,]+)\)")

def _extract_chronological_page(page) -> list[dict]:
    """1ページから全ライダーのラップデータを抽出"""
    width  = page.width
    words  = page.extract_words(x_tolerance=3, y_tolerance=3)
    if not words:
        return []

    # 左右カラムに分割（ページ幅の50%を境界）
    mid = width * 0.50
    cols = {
        "left":  [w for w in words if w["x0"] < mid],
        "right": [w for w in words if w["x0"] >= mid],
    }

    all_laps = []
    for col_name, col_words in cols.items():
        # y座標でライン再構成（3px単位）
        by_y = defaultdict(list)
        for w in col_words:
            y_key = round(w["top"] / 3) * 3
            by_y[y_key].append(w)

        lines = []
        for y in sorted(by_y):
            line = " ".join(w["text"] for w in sorted(by_y[y], key=lambda w: w["x0"]))
            lines.append(line.strip())

        # ライダーセクションごとに処理
        rider_pos  = None
        rider_num  = None
        rider_name = None
        in_section = False
        after_header = False

        for line in lines:
            # ライダーヘッダー検出
            hm = _RIDER_HDR.search(line)
            if hm:
                rider_pos  = int(hm.group(1))
                rider_num  = int(hm.group(2))
                rider_name = hm.group(3).strip()
                in_section = True
                after_header = False
                continue

            if not in_section:
                continue

            # "Lap Seg.1 Seg.2 ..." ヘッダー行
            if "Lap" in line and "Seg" in line:
                after_header = True
                continue

            if not after_header:
                continue

            # アウトラップ行（数字3つ + ローカルタイム、ラップ番号なし）
            om = _OUTLAP_RE.match(line)
            if om and not re.match(r"^\d+\s+[\d'.]", line):
                all_laps.append({
                    "position": rider_pos, "rider_num": rider_num, "rider_name": rider_name,
                    "lap_no": 0, "seg1": None,
                    "seg2": float(om.group(1)), "seg3": float(om.group(2)), "seg4": float(om.group(3)),
                    "lap_time": None, "lap_time_s": None, "speed": None,
                    "local_time": om.group(4),
                    "is_outlap": 1, "is_pit": 0, "is_cancelled": 0,
                })
                continue

            # 通常ラップ行
            lp = _parse_lap_line(line)
            if lp:
                lp["position"]   = rider_pos
                lp["rider_num"]  = rider_num
                lp["rider_name"] = rider_name
                all_laps.append(lp)

    return all_laps

# ── Results ページパース (1.2) ─────────────────────────────────────────────
# 例: "5 52 J. ALCOBA ESP Kawasaki WorldSSP Team Kawasaki ZX-6R 636 1'43.327 0.362 0.016 17"
_RESULT_RE = re.compile(
    r"^(\d+)\s+(\d+)\s+"                      # pos rider_num
    r"([A-Z]\.\s*\w+(?:\s+\w+)*?)\s+"         # rider_name (abbrev)
    r"([A-Z]{2,3})\s+"                        # nationality
)

def _extract_results_page(page, session_label: str) -> list[dict]:
    """Results (1.2) ページから全ライダー結果を抽出"""
    text = page.extract_text() or ""
    if "Results" not in text and "Result" not in text:
        return []

    results = []
    lines = text.split("\n")
    for line in lines:
        line = line.strip()
        # ポジション + ライダー番号 + タイム
        m = re.match(
            r"^(\d+)\s+(\d+)\s+([\w.]+\s+[\w.]+)\s+(\w{2,3})\s+"
            r"([\w\s]+?)\s+([\w\s\-]+?)\s+"
            r"([\d':.]+)\s+([\d:.+]+)\s+([\d:.]+)\s+(\d+)",
            line
        )
        if m:
            try:
                results.append({
                    "position":   int(m.group(1)),
                    "rider_num":  int(m.group(2)),
                    "rider_name": m.group(3).strip(),
                    "nationality":m.group(4),
                    "laps":       int(m.group(10)),
                    "best_lap":   m.group(7),
                    "best_lap_s": _lap_time_to_s(m.group(7)),
                    "gap":        m.group(8),
                })
            except:
                pass
    return results

# ── PDF 1ファイル処理 ──────────────────────────────────────────────────────
def process_pdf(pdf_path: Path, conn: sqlite3.Connection, force: bool = False):
    fname = pdf_path.name
    log.info(f"処理中: {fname}")

    if not force and _already_imported(conn, fname):
        log.info(f"  スキップ（既インポート）")
        return 0

    with pdfplumber.open(pdf_path) as pdf:
        meta = _parse_meta(pdf.pages)
        log.info(f"  {meta['round']} / {meta['circuit']} / {meta['session_type']} / {meta['date']}")

        all_laps = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "Chronological Analysis" in text:
                laps = _extract_chronological_page(page)
                all_laps.extend(laps)

    if not all_laps:
        log.info(f"  ラップデータなし")
        return 0

    # 重複除去（同 rider_num + lap_no）
    seen = set()
    unique = []
    for lap in all_laps:
        key = (lap["rider_num"], lap["lap_no"])
        if key not in seen:
            seen.add(key)
            unique.append(lap)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for lap in unique:
        rows.append((
            meta["round"], meta["circuit"], meta["session_type"], meta["date"],
            lap.get("position"), lap["rider_num"], lap.get("rider_name"),
            lap["lap_no"], lap.get("seg1"), lap.get("seg2"), lap.get("seg3"), lap.get("seg4"),
            lap.get("lap_time"), lap.get("lap_time_s"), lap.get("speed"), lap.get("local_time"),
            lap.get("is_outlap", 0), lap.get("is_pit", 0), lap.get("is_cancelled", 0),
            fname, now,
        ))

    conn.executemany("""
        INSERT INTO pdf_lap_times
        (round,circuit,session_type,date,position,rider_num,rider_name,
         lap_no,seg1,seg2,seg3,seg4,lap_time,lap_time_s,speed,local_time,
         is_outlap,is_pit,is_cancelled,source_file,imported_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    conn.commit()

    log.info(f"  → {len(rows)}ラップ 保存完了")
    return len(rows)

# ── メイン ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file",  help="単一PDF")
    ap.add_argument("--all",   action="store_true", help="07_RESULTS/ 以下全スキャン")
    ap.add_argument("--force", action="store_true", help="既インポート済みも再処理")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH)
    _ensure_tables(conn)

    total = 0
    if args.file:
        total = process_pdf(Path(args.file), conn, args.force)
    elif args.all:
        pdfs = sorted(RESULTS_ROOT.rglob("*.pdf"))
        for p in pdfs:
            if "REFERENCE" not in str(p):
                total += process_pdf(p, conn, args.force)
    else:
        ap.print_help()

    log.info(f"合計 {total} ラップ処理完了")
    conn.close()

if __name__ == "__main__":
    main()
