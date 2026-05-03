"""
ts24_unified.db に PROBLEM_LOG と SETUP_DECISION_LOG テーブルを追加する。
既存テーブルは変更しない。べき等（何度実行しても同じ結果）。

実行方法:
  python create_workbench_tables.py
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "02_DATABASE" / "ts24_unified.db"

SQL_PROBLEM_LOG = """
CREATE TABLE IF NOT EXISTS problem_log (
    problem_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT,
    round         TEXT,
    circuit       TEXT,
    session       TEXT,
    rider         TEXT,
    run_no        INTEGER,
    lap_no        INTEGER,
    corner        TEXT,
    phase         TEXT,
    problem_tag   TEXT,
    description   TEXT,
    severity      TEXT    DEFAULT 'MEDIUM',
    source        TEXT    DEFAULT 'OBSERVATION',
    export_status TEXT    DEFAULT 'PENDING',
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    DEFAULT (datetime('now','localtime'))
)
"""

SQL_SETUP_DECISION_LOG = """
CREATE TABLE IF NOT EXISTS setup_decision_log (
    decision_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id_from     TEXT,
    run_id_to       TEXT,
    round           TEXT,
    circuit         TEXT,
    session         TEXT,
    rider           TEXT,
    change_type     TEXT,
    component       TEXT,
    from_value      TEXT,
    to_value        TEXT,
    rationale       TEXT,
    expected_effect TEXT,
    actual_effect   TEXT,
    result_eval     TEXT,
    export_status   TEXT    DEFAULT 'PENDING',
    created_at      TEXT    DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    DEFAULT (datetime('now','localtime'))
)
"""


def create_tables():
    if not DB_PATH.exists():
        print(f"❌ DB not found: {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SQL_PROBLEM_LOG)
    conn.execute(SQL_SETUP_DECISION_LOG)
    conn.commit()

    # 確認
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"✅ Tables in {DB_PATH.name}: {tables}")
    print("   problem_log and setup_decision_log are ready.")


if __name__ == "__main__":
    create_tables()
