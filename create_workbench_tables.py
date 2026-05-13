"""
ts24_unified.db に PROBLEM_LOG / SETUP_DECISION_LOG / v2.0テーブルを追加する。
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


SQL_ANALYSIS_NOTE = """
CREATE TABLE IF NOT EXISTS analysis_note (
    note_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT    NOT NULL,
    circuit       TEXT,
    rider         TEXT,
    session       TEXT,
    note_type     TEXT    DEFAULT 'GENERAL',
    title         TEXT,
    body          TEXT,
    data_source   TEXT,
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    DEFAULT (datetime('now','localtime'))
)
"""

SQL_RESULT_VALIDATION = """
CREATE TABLE IF NOT EXISTS result_validation (
    validation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER,
    run_id_validate TEXT,
    circuit         TEXT,
    rider           TEXT,
    hypothesis      TEXT,
    observed        TEXT,
    conclusion      TEXT,
    verdict         TEXT    DEFAULT 'PENDING',
    created_at      TEXT    DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    DEFAULT (datetime('now','localtime'))
)
"""

SQL_KNOWLEDGE_CASES = """
CREATE TABLE IF NOT EXISTS knowledge_cases (
    case_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    circuit       TEXT,
    symptom_tag   TEXT,
    root_cause    TEXT,
    solution      TEXT,
    confidence    TEXT    DEFAULT 'LOW',
    evidence_runs TEXT,
    created_at    TEXT    DEFAULT (datetime('now','localtime')),
    updated_at    TEXT    DEFAULT (datetime('now','localtime'))
)
"""


def create_tables():
    if not DB_PATH.exists():
        print(f"❌ DB not found: {DB_PATH}")
        return
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SQL_PROBLEM_LOG)
    conn.execute(SQL_SETUP_DECISION_LOG)
    conn.execute(SQL_ANALYSIS_NOTE)
    conn.execute(SQL_RESULT_VALIDATION)
    conn.execute(SQL_KNOWLEDGE_CASES)
    conn.commit()

    # 確認
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"✅ Tables in {DB_PATH.name}: {tables}")
    print("   problem_log, setup_decision_log, analysis_note, result_validation, knowledge_cases ready.")


if __name__ == "__main__":
    create_tables()
