#!/usr/bin/env python3
"""
report_importer.py — Excel Report CLI インポーター
===================================================
excel_parser.py の CLI化。
01_REPORTS/ 以下の .xlsx を解析し、ts24_unified.db の
pending_sessions / pending_lap_times テーブルに書き込む。

【重要】権威源のデータは変更しない。pending_* テーブルは中間ステージング領域。
        Tatsuki が内容を確認してから runs / laps テーブルに手動で反映する。

ts24_watcher.py から自動呼び出しされるほか、手動実行も可能。

使用方法:
  python report_importer.py --file /path/to/report.xlsx
  python report_importer.py --dir  /path/to/reports/dir/
  python report_importer.py --all                        ← 01_REPORTS/ 以下を全スキャン
  python report_importer.py --status                     ← pending テーブルの件数表示
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
DATA_ROOT   = SCRIPT_DIR.parent
REPORTS_ROOT = DATA_ROOT / "01_REPORTS"
DB_PATH     = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
LOG_FILE    = SCRIPT_DIR / "watcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [REPORT] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def _ensure_tables(conn: sqlite3.Connection):
    """pending テーブルが存在しない場合は作成する（べき等）。"""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS pending_sessions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        submitted_by  TEXT,
        session_date  TEXT,
        circuit       TEXT,
        session_type  TEXT,
        rider         TEXT,
        bike_model    TEXT,
        track_temp    REAL,
        air_temp      REAL,
        f_tyre        TEXT,
        r_tyre        TEXT,
        best_lap      TEXT,
        fork_type     TEXT,
        f_spring      TEXT,
        f_preload     REAL,
        f_comp        INTEGER,
        f_reb         INTEGER,
        shock_type    TEXT,
        r_spring      REAL,
        r_preload     REAL,
        r_comp        INTEGER,
        r_reb         INTEGER,
        ride_height   REAL,
        swing_arm     INTEGER,
        status        TEXT    DEFAULT 'pending',
        source_file   TEXT,
        imported_at   TEXT    DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS pending_lap_times (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        submitted_by  TEXT,
        round_id      TEXT,
        circuit       TEXT,
        session_type  TEXT,
        rider_num     INTEGER,
        rider_name    TEXT,
        lap_no        INTEGER,
        lap_time      REAL,
        speed         REAL,
        flag          TEXT,
        is_valid      INTEGER DEFAULT 1,
        status        TEXT    DEFAULT 'pending',
        source_file   TEXT,
        imported_at   TEXT    DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()


def _already_imported(conn: sqlite3.Connection, source_file: str) -> bool:
    """同一ファイルが既にインポート済みか確認する（重複防止）。"""
    row = conn.execute(
        "SELECT id FROM pending_sessions WHERE source_file = ? LIMIT 1",
        (source_file,),
    ).fetchone()
    return row is not None


def import_excel(xlsx_path: Path, dry_run: bool = False) -> tuple[int, int]:
    """
    Excelファイルを解析してpending_*テーブルに書き込む。
    Returns: (sessions_count, laps_count)
    """
    try:
        from excel_parser import parse_report_excel
    except ImportError:
        log.error("excel_parser.py が見つかりません。同じディレクトリに置いてください。")
        return 0, 0

    log.info("解析開始: %s", xlsx_path.name)
    try:
        raw = xlsx_path.read_bytes()
    except Exception as e:
        log.error("ファイル読み込みエラー: %s — %s", xlsx_path, e)
        return 0, 0

    result = parse_report_excel(raw, submitted_by="watcher")
    for err in result.get("errors", []):
        log.warning("  parser warning: %s", err)

    sessions = result.get("sessions", [])
    laps     = result.get("laps", [])

    if not sessions:
        log.warning("  セッションデータなし: %s", xlsx_path.name)
        return 0, 0

    if dry_run:
        log.info("  [dry-run] sessions=%d, laps=%d — 書き込みスキップ",
                 len(sessions), len(laps))
        return len(sessions), len(laps)

    if not DB_PATH.exists():
        log.error("DB not found: %s", DB_PATH)
        return 0, 0

    source_file = str(xlsx_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn = sqlite3.connect(str(DB_PATH))
        _ensure_tables(conn)

        if _already_imported(conn, source_file):
            log.info("  スキップ（既インポート済み）: %s", xlsx_path.name)
            conn.close()
            return 0, 0

        for s in sessions:
            conn.execute(
                """INSERT INTO pending_sessions
                   (submitted_by, session_date, circuit, session_type, rider,
                    bike_model, track_temp, air_temp, f_tyre, r_tyre, best_lap,
                    fork_type, f_spring, f_preload, f_comp, f_reb,
                    shock_type, r_spring, r_preload, r_comp, r_reb,
                    ride_height, swing_arm, status, source_file, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    s.get("submitted_by"), s.get("session_date"), s.get("circuit"),
                    s.get("session_type"), s.get("rider"), s.get("bike_model"),
                    s.get("track_temp"), s.get("air_temp"),
                    s.get("f_tyre"), s.get("r_tyre"), s.get("best_lap"),
                    s.get("fork_type"), s.get("f_spring"), s.get("f_preload"),
                    s.get("f_comp"), s.get("f_reb"),
                    s.get("shock_type"), s.get("r_spring"), s.get("r_preload"),
                    s.get("r_comp"), s.get("r_reb"),
                    s.get("ride_height"), s.get("swing_arm"),
                    "pending", source_file, now,
                ),
            )

        for lap in laps:
            conn.execute(
                """INSERT INTO pending_lap_times
                   (submitted_by, round_id, circuit, session_type,
                    rider_num, rider_name, lap_no, lap_time, speed,
                    flag, is_valid, status, source_file, imported_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lap.get("submitted_by"), lap.get("round_id"), lap.get("circuit"),
                    lap.get("session_type"), lap.get("rider_num"), lap.get("rider_name"),
                    lap.get("lap_no"), lap.get("lap_time"), lap.get("speed"),
                    lap.get("flag", ""), lap.get("is_valid", 1),
                    "pending", source_file, now,
                ),
            )

        conn.commit()
        conn.close()
        log.info("  ✅ sessions=%d, laps=%d インポート完了: %s",
                 len(sessions), len(laps), xlsx_path.name)
        return len(sessions), len(laps)

    except Exception as e:
        log.error("  DB書き込みエラー: %s — %s", xlsx_path.name, e)
        return 0, 0


def show_status():
    """pending テーブルの件数を表示する。"""
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        return
    conn = sqlite3.connect(str(DB_PATH))
    _ensure_tables(conn)
    s = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT source_file) FROM pending_sessions"
    ).fetchone()
    l = conn.execute(
        "SELECT COUNT(*) FROM pending_lap_times"
    ).fetchone()
    conn.close()
    print(f"pending_sessions : {s[0]} rows ({s[1]} files)")
    print(f"pending_lap_times: {l[0]} rows")


def main():
    parser = argparse.ArgumentParser(description="Excel Report インポーター")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file",   type=Path, help="単一 .xlsx ファイルのパス")
    group.add_argument("--dir",    type=Path, help="フォルダ内の全 .xlsx を処理")
    group.add_argument("--all",    action="store_true",
                       help="01_REPORTS/ 以下を全スキャン")
    group.add_argument("--status", action="store_true",
                       help="pending テーブルの件数を表示")
    parser.add_argument("--dry-run", action="store_true",
                        help="DB書き込みなしで確認のみ")
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    total_s = total_l = 0

    if args.file:
        s, l = import_excel(args.file, dry_run=args.dry_run)
        total_s += s; total_l += l

    elif args.dir:
        xlsxs = sorted(args.dir.glob("*.xlsx"))
        for f in xlsxs:
            s, l = import_excel(f, dry_run=args.dry_run)
            total_s += s; total_l += l

    else:  # --all
        xlsxs = sorted(REPORTS_ROOT.rglob("*.xlsx"))
        log.info("01_REPORTS/ 全スキャン: %d ファイル", len(xlsxs))
        for f in xlsxs:
            s, l = import_excel(f, dry_run=args.dry_run)
            total_s += s; total_l += l

    log.info("合計: sessions=%d, laps=%d", total_s, total_l)


if __name__ == "__main__":
    main()
