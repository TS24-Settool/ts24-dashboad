#!/usr/bin/env python3
"""
create_quality_tables.py — TS24 Phase 1: 解析ログ・品質ログ基盤

Multi-Agent Data Quality Roadmap の Phase 1 で要求される 5 つの管理テーブルを
正本DB (02_DATABASE/ts24_unified.db) に **追加のみ** で作成する。

  - source_file_registry : いつ・どのソースファイルを検出したか
  - import_queue         : Quality Gate 待ちの処理キュー
  - analysis_run_log     : いつ・どのファイルを・どのスクリプトで・何を抽出したか
  - data_quality_log     : 品質チェック結果 (PASS / WARNING / FAIL)
  - metric_version_log   : 指標(メトリクス)の定義バージョン管理

設計原則（CLAUDE.md 準拠）:
  * 既存テーブル・既存データには一切触れない（CREATE TABLE IF NOT EXISTS のみ）。
  * DB更新前に必ずバックアップを取る（_backup_quality_tables_<TS>/）。
  * timestamp は ISO8601 文字列（既存 created_at/updated_at と同形式）。
  * 再実行しても安全（冪等）。INSERT は OR IGNORE。

run_id / lap_id 命名規則（CLAUDE.md §4.4 参照）:
  run_id = {YYYYMMDD}_{ROUND}_{CIRCUIT}_{SESSION}_{RIDER}_{RUN_NO}
  lap_id = {run_id}_L{LAP_NO}

実行: python3 create_quality_tables.py            (正本DBへ作成)
      python3 create_quality_tables.py --db <path>  (DB指定)
      python3 create_quality_tables.py --no-backup   (バックアップ省略=非推奨)
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

QUALITY_TABLES = [
    "source_file_registry",
    "import_queue",
    "analysis_run_log",
    "data_quality_log",
    "metric_version_log",
]

DDL = """
-- ============================================================
-- 1. source_file_registry : 検出されたソースファイルの台帳
-- ============================================================
CREATE TABLE IF NOT EXISTS source_file_registry (
    file_id        TEXT PRIMARY KEY,          -- 安定ID（sha256先頭 or path基準）
    file_path      TEXT NOT NULL,             -- リポジトリ相対 or 絶対パス
    file_name      TEXT NOT NULL,
    file_type      TEXT,                       -- MES/LAP/DDD/REPORT_XLSX/RESULT_PDF/CSV
    file_size      INTEGER,
    file_mtime     TEXT,                       -- ソースファイルの更新時刻(ISO)
    sha256         TEXT,                       -- 内容ハッシュ（変更検出用）
    rider          TEXT,                       -- 解析済みメタ(任意)
    circuit        TEXT,
    round          TEXT,
    session        TEXT,
    discovered_at  TEXT NOT NULL,              -- 検出時刻(ISO)
    status         TEXT NOT NULL DEFAULT 'discovered',  -- discovered/queued/extracted/archived
    notes          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_srcreg_path ON source_file_registry(file_path);
CREATE INDEX IF NOT EXISTS ix_srcreg_status ON source_file_registry(status);
CREATE INDEX IF NOT EXISTS ix_srcreg_type   ON source_file_registry(file_type);

-- ============================================================
-- 2. import_queue : Quality Gate 待ちの処理キュー
-- ============================================================
CREATE TABLE IF NOT EXISTS import_queue (
    queue_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         TEXT,                      -- -> source_file_registry.file_id
    file_path       TEXT,
    target_kind     TEXT,                      -- laps/suspension/results/comments 等
    priority        INTEGER NOT NULL DEFAULT 100,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending/processing/awaiting_gate/done/failed/skipped
    enqueued_at     TEXT NOT NULL,
    started_at      TEXT,
    finished_at     TEXT,
    analysis_run_id TEXT,                      -- -> analysis_run_log.analysis_run_id
    error           TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS ix_queue_status ON import_queue(status);
CREATE INDEX IF NOT EXISTS ix_queue_file   ON import_queue(file_id);

-- ============================================================
-- 3. analysis_run_log : 抽出/解析の実行記録（DB更新の根拠）
-- ============================================================
CREATE TABLE IF NOT EXISTS analysis_run_log (
    analysis_run_id TEXT PRIMARY KEY,          -- {YYYYMMDDTHHMMSS}_{script}
    script_name     TEXT NOT NULL,
    script_version  TEXT,                       -- git hash / 手動バージョン
    agent           TEXT,                       -- Extraction/QualityGate/DBIntegration/...
    source_file_id  TEXT,                       -- -> source_file_registry.file_id
    target_db       TEXT,                       -- scratch / unified
    target_table    TEXT,
    run_scope       TEXT,                       -- run_id / 'ALL' 等
    rows_in         INTEGER,
    rows_out        INTEGER,
    rows_inserted   INTEGER,
    rows_updated    INTEGER,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running',  -- running/success/failed/aborted
    quality_status  TEXT,                       -- PASS/WARNING/FAIL（Gate結果）
    params_json     TEXT,                       -- 起動パラメータ
    log_path        TEXT,
    error           TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS ix_arl_script ON analysis_run_log(script_name);
CREATE INDEX IF NOT EXISTS ix_arl_status ON analysis_run_log(status);
CREATE INDEX IF NOT EXISTS ix_arl_started ON analysis_run_log(started_at);

-- ============================================================
-- 4. data_quality_log : 品質チェック結果（PASS/WARNING/FAIL）
-- ============================================================
CREATE TABLE IF NOT EXISTS data_quality_log (
    qc_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_run_id TEXT,                       -- -> analysis_run_log
    check_name      TEXT NOT NULL,              -- lap_count_match/lap_time_range/pdf_vs_2d_best/null_rate/zone_sample/outlier/determinism 等
    scope           TEXT,                       -- run_id / lap_id / table / global
    scope_id        TEXT,                       -- 具体的な run_id / lap_id / テーブル名
    metric_name     TEXT,
    observed_value  TEXT,
    expected_value  TEXT,
    tolerance       TEXT,
    result          TEXT NOT NULL,              -- PASS/WARNING/FAIL
    severity        TEXT,                       -- info/warn/critical
    detail          TEXT,
    checked_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_dql_run    ON data_quality_log(analysis_run_id);
CREATE INDEX IF NOT EXISTS ix_dql_result ON data_quality_log(result);
CREATE INDEX IF NOT EXISTS ix_dql_check  ON data_quality_log(check_name);

-- ============================================================
-- 5. metric_version_log : 指標定義のバージョン管理
-- ============================================================
CREATE TABLE IF NOT EXISTS metric_version_log (
    metric_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_name     TEXT NOT NULL,             -- 例: brk_f_dive_spd_avg
    table_name      TEXT,                       -- 例: lap_suspension
    version         TEXT NOT NULL,              -- v1, v2...
    definition      TEXT,                       -- 計算式 / マスク / 概要
    units           TEXT,
    guard_rule      TEXT,                       -- n>=5 -> NULL 等
    source_script   TEXT,
    effective_from  TEXT NOT NULL,              -- 導入日(ISO)
    superseded_at   TEXT,                       -- 置換日
    superseded_by   TEXT,                       -- 後継 metric_name/version
    notes           TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_mvl_name_ver ON metric_version_log(metric_name, version);
"""

# metric_version_log の初期シード（既存 v1 指標を文書化）。INSERT OR IGNORE で冪等。
# 出典: CLAUDE.md §18 / §19
SEED_METRICS = [
    # (metric_name, table, version, definition, units, guard_rule, source_script, effective_from, notes)
    ("f_dive_spd", "laps", "v1", "ラップ全体のフロント圧縮(diving)方向サス速度ピーク。位置微分(np.gradient/dt)のmax", "mm/s(相対)", "校正済み絶対値ではない相対ダンピング速度指数。一人歩き禁止", "build_master_db.py", "2026-06-19", "§18 NEW抽出指標"),
    ("f_reb_spd", "laps", "v1", "ラップ全体のフロント伸び(rebound)方向サス速度ピーク", "mm/s(相対)", "相対指数", "build_master_db.py", "2026-06-19", "§18"),
    ("r_dive_spd", "laps", "v1", "ラップ全体のリア圧縮方向サス速度ピーク", "mm/s(相対)", "相対指数", "build_master_db.py", "2026-06-19", "§18"),
    ("r_reb_spd", "laps", "v1", "ラップ全体のリア伸び方向サス速度ピーク", "mm/s(相対)", "相対指数", "build_master_db.py", "2026-06-19", "§18"),
    ("rear_light_brk", "laps", "v1", "ブレーキ区間(BRAKE_FRONT>=5bar)で SUSP_REAR<=1mm の割合%", "%", "両ch存在時のみ", "build_master_db.py", "2026-06-19", "§18 ブレーキバランス指標"),
    ("brk_f_dive_spd_avg", "lap_suspension", "v1", "FULL_BRAKING内 フロント圧縮(v_f>0)速度の平均", "mm/s(相対)", "mask n>=5 かつ 圧縮サンプル n>=5、未満はNULL", "build_master_db.py", "2026-06-20", "§19a"),
    ("brk_f_dive_spd_peak", "lap_suspension", "v1", "FULL_BRAKING内 フロント圧縮速度の peak(max)", "mm/s(相対)", "同上。将来p95化検討", "build_master_db.py", "2026-06-20", "§19a"),
    ("ce_r_spd_avg", "lap_suspension", "v1", "CORNER_EXIT内 リアサス速度|v_r|(絶対値)の平均", "mm/s(相対)", "mask n>=5、未満はNULL", "build_master_db.py", "2026-06-20", "§19a v1は絶対値(動きの忙しさ)"),
    ("ce_r_spd_peak", "lap_suspension", "v1", "CORNER_EXIT内 リアサス速度|v_r|の peak(max)", "mm/s(相対)", "同上。peak max/p95=4.28xでp95化候補", "build_master_db.py", "2026-06-20", "§19a"),
    ("ph12_rear0_s", "lap_suspension", "v1", "PH1-2代理(BRAKE_FRONT>=0.3bar進入相)で SUSP_REAR<=0mm の累積秒", "s", "両ch存在時のみ。0秒は実測値として許容", "build_master_db.py", "2026-06-20", "§19a"),
]


def backup_db(db_path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = db_path.parent / f"_backup_quality_tables_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    dest = bdir / db_path.name
    shutil.copy2(db_path, dest)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="TS24 Phase 1: 品質ログ管理テーブル作成")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="対象DB（既定: 正本 ts24_unified.db）")
    ap.add_argument("--no-backup", action="store_true", help="バックアップを省略（非推奨）")
    ap.add_argument("--no-seed", action="store_true", help="metric_version_log の初期シードを省略")
    args = ap.parse_args()

    db_path: Path = args.db
    if not db_path.exists():
        print(f"[FATAL] DB が見つかりません: {db_path}", file=sys.stderr)
        return 1
    if db_path.stat().st_size == 0:
        print(f"[FATAL] DB が 0 バイトです（孤児ファイルの可能性）: {db_path}", file=sys.stderr)
        return 1

    print(f"[INFO] 対象DB: {db_path}")

    # 1. バックアップ
    if not args.no_backup:
        dest = backup_db(db_path)
        print(f"[INFO] バックアップ作成: {dest}")
    else:
        print("[WARN] --no-backup: バックアップを省略します")

    # 2. 作成前の状態
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    before = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    existing = [t for t in QUALITY_TABLES if t in before]
    if existing:
        print(f"[INFO] 既存の管理テーブル（保持・再作成しない）: {existing}")

    # 3. DDL 実行（IF NOT EXISTS のみ → 既存に無害）
    cur.executescript(DDL)
    conn.commit()

    # 4. metric_version_log シード（冪等）
    seeded = 0
    if not args.no_seed:
        for (name, table, ver, defi, units, guard, script, eff, notes) in SEED_METRICS:
            cur.execute(
                """INSERT OR IGNORE INTO metric_version_log
                   (metric_name, table_name, version, definition, units, guard_rule,
                    source_script, effective_from, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (name, table, ver, defi, units, guard, script, eff, notes),
            )
            seeded += cur.rowcount
        conn.commit()
        print(f"[INFO] metric_version_log シード投入: {seeded} 行（既存はスキップ）")

    # 5. 検証サマリ
    after = {r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    created = sorted(set(QUALITY_TABLES) & after)
    missing = sorted(set(QUALITY_TABLES) - after)
    print("\n=== 検証 ===")
    for t in QUALITY_TABLES:
        if t in after:
            n = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            ncols = len(cur.execute(f"PRAGMA table_info({t})").fetchall())
            print(f"  [OK]   {t:<22} cols={ncols:<3} rows={n}")
        else:
            print(f"  [FAIL] {t:<22} 作成されていません")
    print(f"\n全管理テーブル数: {len(created)}/{len(QUALITY_TABLES)}")
    if missing:
        print(f"[FATAL] 未作成: {missing}", file=sys.stderr)
        conn.close()
        return 2

    conn.close()
    print("[DONE] Phase 1 品質ログ基盤の作成が完了しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
