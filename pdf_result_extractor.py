#!/usr/bin/env python3
"""
pdf_result_extractor.py — WorldSSP 公式リザルト PDF 抽出
=========================================================
pdfplumber で WorldSSP 公式 PDF から結果・セクタータイムを抽出し
ts24_unified.db の race_results テーブルに書き込む。

対象ライダー絞り込み: DA77（#77）・JA52（#52）のみ抽出。
                      --all-riders オプションで全ライダー抽出も可能。

使用方法:
  python pdf_result_extractor.py --file /path/to/result.pdf
  python pdf_result_extractor.py --dir  /path/to/07_RESULTS/
  python pdf_result_extractor.py --all                       ← 07_RESULTS/ 以下を全スキャン
  python pdf_result_extractor.py --file result.pdf --all-riders

依存: pdfplumber  (pip install pdfplumber)
"""
from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
DATA_ROOT    = SCRIPT_DIR.parent
RESULTS_ROOT = DATA_ROOT / "07_RESULTS"
DB_PATH      = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
LOG_FILE     = SCRIPT_DIR / "watcher.log"

TARGET_RIDERS = {77, 52}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [PDF] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ── テーブル作成 ──────────────────────────────────────────────────────────────

def _ensure_table(conn: sqlite3.Connection):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS race_results (
        result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
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
        race_time     TEXT,
        gap           TEXT,
        best_lap      TEXT,
        best_lap_s    REAL,
        sector1       TEXT,
        sector2       TEXT,
        sector3       TEXT,
        source_file   TEXT,
        imported_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def _already_imported(conn: sqlite3.Connection, source_file: str) -> bool:
    row = conn.execute(
        "SELECT result_id FROM race_results WHERE source_file = ? LIMIT 1",
        (source_file,),
    ).fetchone()
    return row is not None


# ── ラップタイム文字列 → 秒数変換 ────────────────────────────────────────────

def _parse_time_s(val: str | None) -> float | None:
    if not val:
        return None
    val = val.strip()
    m = re.match(r"(\d+)[:':](\d{2})[.,](\d+)", val)
    if m:
        mins = int(m.group(1))
        secs = int(m.group(2))
        frac = m.group(3)
        return round(mins * 60 + secs + float(f"0.{frac}"), 3)
    try:
        return round(float(val.replace(",", ".")), 3)
    except Exception:
        return None


# ── ファイル名からメタデータを推測 ────────────────────────────────────────────

def _meta_from_filename(pdf_path: Path) -> dict:
    """
    ファイル名からラウンド・サーキット・セッション種別を推測する。
    例: 20260417-ROUND3-ASSEN-RACE1.pdf
        WorldSSP_Race1_ASSEN_2026.pdf
    """
    name = pdf_path.stem.upper()
    meta: dict = {"round": None, "circuit": None, "session_type": None, "date": None}

    m = re.search(r"(\d{8})", name)
    if m:
        d = m.group(1)
        meta["date"] = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    for circuit in ["ASSEN", "PHILLIP_ISLAND", "JEREZ", "PORTIMAO",
                    "CREMONA", "MISANO", "MAGNY", "ESTORIL", "DONINGTON",
                    "MOST", "BARCELONA", "SAN_JUAN"]:
        if circuit.replace("_", "") in name.replace("_", ""):
            meta["circuit"] = circuit.replace("_", " ")
            break

    for stype in ["RACE2", "RACE1", "RACE", "SUPERPOLE", "QP", "SP", "FP2", "FP1", "FP"]:
        if stype in name:
            meta["session_type"] = stype
            break

    m2 = re.search(r"ROUND\s*(\d+)", name)
    if m2:
        meta["round"] = f"ROUND{m2.group(1)}"

    return meta


# ── PDF パース ────────────────────────────────────────────────────────────────

def _parse_pdf(pdf_path: Path, all_riders: bool = False) -> list[dict]:
    """
    pdfplumber でページを走査し、結果行を抽出する。
    WorldSSP 公式PDF の典型的なカラム順:
      Pos | No | Rider | Nat | Team | Bike | Laps | Time/Gap | Best Lap | S1 | S2 | S3
    """
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber がインストールされていません: pip install pdfplumber")
        return []

    meta = _meta_from_filename(pdf_path)
    results: list[dict] = []

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    for row in table:
                        if not row or len(row) < 5:
                            continue
                        rec = _parse_row(row, meta, all_riders)
                        if rec:
                            results.append(rec)
    except Exception as e:
        log.error("PDF解析エラー: %s — %s", pdf_path.name, e)

    return results


def _clean(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _parse_row(row: list, meta: dict, all_riders: bool) -> dict | None:
    """
    テーブル行を解析してレコードdictを返す。該当しない行はNoneを返す。
    """
    cleaned = [_clean(c) for c in row]

    # 先頭セルが数字（順位）かチェック
    pos_str = cleaned[0] if cleaned else None
    if not pos_str or not re.match(r"^\d+$", pos_str):
        return None

    pos = int(pos_str)

    # ライダー番号（2列目が数字）
    num_str = cleaned[1] if len(cleaned) > 1 else None
    if not num_str or not re.match(r"^\d+$", num_str):
        return None

    rider_num = int(num_str)

    if not all_riders and rider_num not in TARGET_RIDERS:
        return None

    rider_name  = cleaned[2] if len(cleaned) > 2 else None
    nationality = cleaned[3] if len(cleaned) > 3 else None
    team        = cleaned[4] if len(cleaned) > 4 else None
    bike        = cleaned[5] if len(cleaned) > 5 else None
    laps_str    = cleaned[6] if len(cleaned) > 6 else None
    race_time   = cleaned[7] if len(cleaned) > 7 else None
    best_lap    = cleaned[8] if len(cleaned) > 8 else None
    sector1     = cleaned[9]  if len(cleaned) > 9  else None
    sector2     = cleaned[10] if len(cleaned) > 10 else None
    sector3     = cleaned[11] if len(cleaned) > 11 else None

    laps = None
    if laps_str and re.match(r"^\d+$", laps_str):
        laps = int(laps_str)

    # race_time が順位 1 なら実際のタイム、それ以外は gap
    gap = None
    if pos > 1 and race_time and ("." in race_time or "'" in race_time):
        if not re.match(r"^\d+:\d{2}", race_time):
            gap = race_time
            race_time = None

    return {
        "round":        meta.get("round"),
        "circuit":      meta.get("circuit"),
        "session_type": meta.get("session_type"),
        "date":         meta.get("date"),
        "position":     pos,
        "rider_num":    rider_num,
        "rider_name":   rider_name,
        "nationality":  nationality,
        "team":         team,
        "bike":         bike,
        "laps":         laps,
        "race_time":    race_time,
        "gap":          gap,
        "best_lap":     best_lap,
        "best_lap_s":   _parse_time_s(best_lap),
        "sector1":      sector1,
        "sector2":      sector2,
        "sector3":      sector3,
    }


# ── DB 書き込み ───────────────────────────────────────────────────────────────

def _write_to_db(records: list[dict], source_file: str, dry_run: bool = False) -> int:
    if not records:
        return 0
    if dry_run:
        log.info("  [dry-run] %d 件 — 書き込みスキップ", len(records))
        return len(records)
    if not DB_PATH.exists():
        log.error("DB not found: %s", DB_PATH)
        return 0

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(str(DB_PATH))
        _ensure_table(conn)
        if _already_imported(conn, source_file):
            log.info("  スキップ（既インポート済み）")
            conn.close()
            return 0
        for r in records:
            conn.execute(
                """INSERT INTO race_results
                   (round, circuit, session_type, date, position, rider_num,
                    rider_name, nationality, team, bike, laps, race_time, gap,
                    best_lap, best_lap_s, sector1, sector2, sector3,
                    source_file, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["round"], r["circuit"], r["session_type"], r["date"],
                    r["position"], r["rider_num"], r["rider_name"],
                    r["nationality"], r["team"], r["bike"],
                    r["laps"], r["race_time"], r["gap"],
                    r["best_lap"], r["best_lap_s"],
                    r["sector1"], r["sector2"], r["sector3"],
                    source_file, now,
                ),
            )
        conn.commit()
        conn.close()
        log.info("  ✅ %d 件書き込み完了", len(records))
        return len(records)
    except Exception as e:
        log.error("  DB書き込みエラー: %s", e)
        return 0


# ── エントリーポイント ─────────────────────────────────────────────────────────

def import_pdf(pdf_path: Path, all_riders: bool = False,
               dry_run: bool = False) -> int:
    if not pdf_path.exists():
        log.error("ファイルが見つかりません: %s", pdf_path)
        return 0
    log.info("PDFインポート開始: %s", pdf_path.name)
    records = _parse_pdf(pdf_path, all_riders=all_riders)
    if not records:
        log.warning("  対象レコードなし（DA77/JA52 が含まれていない可能性）: %s",
                    pdf_path.name)
        return 0
    log.info("  対象レコード: %d 件", len(records))
    return _write_to_db(records, source_file=str(pdf_path), dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="WorldSSP PDF リザルト抽出")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=Path, help="単一PDFファイルのパス")
    group.add_argument("--dir",  type=Path, help="フォルダ内の全PDFを処理")
    group.add_argument("--all",  action="store_true",
                       help="07_RESULTS/ 以下を全スキャン")
    parser.add_argument("--all-riders", action="store_true",
                        help="全ライダーを抽出（デフォルトはDA77/JA52のみ）")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB書き込みなしで確認のみ")
    args = parser.parse_args()

    total = 0
    if args.file:
        total = import_pdf(args.file, all_riders=args.all_riders,
                           dry_run=args.dry_run)
    elif args.dir:
        for pdf in sorted(args.dir.glob("*.pdf")):
            total += import_pdf(pdf, all_riders=args.all_riders,
                                dry_run=args.dry_run)
    else:  # --all
        if not RESULTS_ROOT.exists():
            log.error("07_RESULTS/ が見つかりません: %s", RESULTS_ROOT)
            sys.exit(1)
        pdfs = sorted(RESULTS_ROOT.rglob("*.pdf"))
        log.info("07_RESULTS/ 全スキャン: %d ファイル", len(pdfs))
        for pdf in pdfs:
            total += import_pdf(pdf, all_riders=args.all_riders,
                                dry_run=args.dry_run)

    log.info("合計: %d 件インポート完了", total)


if __name__ == "__main__":
    main()
