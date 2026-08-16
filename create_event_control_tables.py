#!/usr/bin/env python3
"""
create_event_control_tables.py — TS24 Event Control Plane Phase B-1
====================================================================
設計: CLAUDE.md §75 / reports/race_weekend_event_control_plane_readiness_20260711.md /
      reports/event_manifest_schema_proposal_20260711.json
GO  : Track B（round8_final_integration_code_instruction_20260713.md "Parallel Track B"）

Event Control Plane の管理2テーブルを対象DBへ **追加のみ** で作成する
（create_quality_tables.py 方式・CREATE TABLE IF NOT EXISTS・冪等）。

  - event_manifest     : 承認済み Event Manifest の DB ミラー（enforcement 用）。
                         status CHECK(draft/approved/active/locked/closed)、
                         **active は同時に1件のみ**（partial UNIQUE index で DB レベル強制）。
  - event_state_ledger : 追記型 state ledger（UPDATE/DELETE をトリガで拒否）。
                         state CHECK(discovered/registered/candidate_ready/staged/verified/
                         reportable/finalized/failed/warning_accepted/skipped/superseded/
                         quarantined)。receipt_json に scan/dry-run/apply の immutable receipt。

設計原則（CLAUDE.md §20 / §75 準拠）:
  * 既存テーブル・既存データには一切触れない（追加のみ・ALTER なし）。
  * DB更新前に必ずバックアップ（_backup_event_control_<TS>/）。--no-backup で省略可（非推奨）。
  * timestamp は ISO8601 文字列。再実行しても安全（冪等）。
  * ledger は業務テーブルではなく管理テーブル（business tables は不変）。

実行: python3 create_event_control_tables.py --db <path>       (既定: 正本 ts24_unified.db)
      python3 create_event_control_tables.py --db <path> --no-backup
注意: Track B フェーズでは正本DBへの適用は別GO。テストは scratch DB (--db /tmp/...) のみ。
"""
from __future__ import annotations
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "02_DATABASE" / "ts24_unified.db"

EVENT_CONTROL_TABLES = ["event_manifest", "event_state_ledger"]

LEDGER_STATES = (
    "discovered", "registered", "candidate_ready", "staged", "verified",
    "reportable", "finalized",
    "failed", "warning_accepted", "skipped", "superseded", "quarantined",
)

DDL = f"""
-- ============================================================
-- 1. event_manifest : 承認済み Event Manifest の DB ミラー
--    JSON 正本 = 02_DATABASE/event_manifests/<event_key>.json
--    （event_manifest.py が load/validate/register/activate を担う）
-- ============================================================
CREATE TABLE IF NOT EXISTS event_manifest (
    manifest_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key             TEXT NOT NULL,             -- YYYYMMDD-ROUNDx-RIDER
    weekend_key           TEXT NOT NULL,             -- YYYYMMDD-ROUNDx
    manifest_version      INTEGER NOT NULL CHECK(manifest_version >= 1),
    schema_version        INTEGER NOT NULL,
    date                  TEXT NOT NULL,             -- ISO (イベント初日)
    round                 TEXT NOT NULL,             -- ROUNDx / TESTx
    circuit               TEXT NOT NULL,             -- canonical（TRACK_M キー）
    riders_json           TEXT NOT NULL,             -- JSON array 例 ["JA52"]
    raw_2d_root           TEXT NOT NULL,             -- live scan の唯一の走査対象（ROOT 相対）
    allowed_sessions_json TEXT NOT NULL,             -- JSON array 例 ["FP","QP",...]
    status                TEXT NOT NULL
        CHECK(status IN ('draft','approved','active','locked','closed')),
    fingerprint_policy    TEXT NOT NULL DEFAULT 'content'
        CHECK(fingerprint_policy IN ('stat','content')),
    expected_outings_json TEXT,                      -- JSON array or NULL
    content_hash          TEXT NOT NULL CHECK(length(content_hash) = 64),
    approved_by           TEXT,
    approved_at           TEXT,
    activated_at          TEXT,
    source_json_path      TEXT,                      -- 由来 JSON ファイル
    raw_json              TEXT NOT NULL,             -- 登録時の JSON 全文（監査用）
    imported_at           TEXT NOT NULL,
    UNIQUE(event_key, manifest_version)
);
-- ★ exactly-one-active（DBレベル強制・partial unique index）
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_manifest_single_active
    ON event_manifest(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_event_manifest_key ON event_manifest(event_key);

-- ============================================================
-- 2. event_state_ledger : 追記型 state ledger（immutable receipts）
-- ============================================================
CREATE TABLE IF NOT EXISTS event_state_ledger (
    entry_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key             TEXT NOT NULL,
    scope                 TEXT NOT NULL
        CHECK(scope IN ('event','session','outing','manifest','source')),
    scope_id              TEXT,                      -- outing stem / session / file_id 等
    state                 TEXT NOT NULL
        CHECK(state IN ({", ".join("'" + s + "'" for s in LEDGER_STATES)})),
    prev_state            TEXT,
    reason                TEXT NOT NULL,             -- 遷移理由（必須・fail-closed の説明責任）
    actor                 TEXT NOT NULL,             -- tatsuki / claude_code / script 名
    analysis_run_id       TEXT,                      -- -> analysis_run_log
    manifest_version      INTEGER,
    manifest_content_hash TEXT,
    receipt_json          TEXT,                      -- immutable receipt（scan/dry-run/apply/backup/rollback）
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_esl_event ON event_state_ledger(event_key);
CREATE INDEX IF NOT EXISTS ix_esl_state ON event_state_ledger(state);
CREATE INDEX IF NOT EXISTS ix_esl_scope ON event_state_ledger(scope, scope_id);

-- 追記型を DB レベルで強制（UPDATE/DELETE 拒否トリガ）
CREATE TRIGGER IF NOT EXISTS trg_esl_no_update
BEFORE UPDATE ON event_state_ledger
BEGIN
    SELECT RAISE(ABORT, 'event_state_ledger is append-only (UPDATE forbidden)');
END;
CREATE TRIGGER IF NOT EXISTS trg_esl_no_delete
BEFORE DELETE ON event_state_ledger
BEGIN
    SELECT RAISE(ABORT, 'event_state_ledger is append-only (DELETE forbidden)');
END;
"""


def backup_db(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = db_path.parent / f"_backup_event_control_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):          # WAL-safe（sidecar 込み）
        src = Path(str(db_path) + suffix)
        if src.exists():
            shutil.copy2(src, bdir / src.name)
    return bdir / db_path.name


def main() -> int:
    ap = argparse.ArgumentParser(description="TS24 Event Control Plane: 管理2テーブル作成（追加のみ・冪等）")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="対象DB（既定: 正本 ts24_unified.db）")
    ap.add_argument("--no-backup", action="store_true", help="バックアップを省略（非推奨）")
    args = ap.parse_args()

    db_path: Path = args.db
    if not db_path.exists():
        print(f"[FATAL] DB が見つかりません: {db_path}", file=sys.stderr)
        return 1
    if db_path.stat().st_size == 0:
        print(f"[FATAL] DB が 0 バイトです: {db_path}", file=sys.stderr)
        return 1

    print(f"[INFO] 対象DB: {db_path}")
    if not args.no_backup:
        print(f"[INFO] バックアップ作成: {backup_db(db_path)}")
    else:
        print("[WARN] --no-backup: バックアップを省略します")

    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    before = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    existing = [t for t in EVENT_CONTROL_TABLES if t in before]
    if existing:
        print(f"[INFO] 既存の管理テーブル（保持・再作成しない）: {existing}")

    cur.executescript(DDL)
    conn.commit()

    after = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print("\n=== 検証 ===")
    ok = True
    for t in EVENT_CONTROL_TABLES:
        if t in after:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            ncols = len(cur.execute(f"PRAGMA table_info({t})").fetchall())
            print(f"  [OK]   {t:<20} cols={ncols:<3} rows={n}")
        else:
            print(f"  [FAIL] {t:<20} 作成されていません")
            ok = False
    # append-only トリガの存在確認
    trigs = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for tg in ("trg_esl_no_update", "trg_esl_no_delete"):
        print(f"  [{'OK' if tg in trigs else 'FAIL'}]   trigger {tg}")
        ok = ok and tg in trigs
    idx = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    print(f"  [{'OK' if 'ux_event_manifest_single_active' in idx else 'FAIL'}]   "
          f"index ux_event_manifest_single_active (exactly-one-active)")
    ok = ok and "ux_event_manifest_single_active" in idx
    conn.close()
    if not ok:
        return 2
    print("[DONE] Event Control Plane 管理テーブルの作成が完了しました（既存テーブル無改変）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
