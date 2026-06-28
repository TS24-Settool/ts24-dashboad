#!/usr/bin/env python3
"""
apply_pdf_v2_staging.py — Result PDF v2 PASS 行の正本 staging 反映（既定 dry-run）
==================================================================================
設計: CLAUDE.md §33 / `reports/pdf_v2_canonical_staging_plan_20260627.md`。
入力: `/tmp/ts24_pdf_v2_scratch.db`（`pdf_v2_scratch_gate.py` が生成・Gate 済み）。
反映先(承認後): 正本DB `02_DATABASE/ts24_unified.db` 内の **新規** `pdf_lap_times_v2_staging`
              （既存業務テーブルは ALTER も書込もしない＝追加のみ）。

**安全原則:**
  - **既定は dry-run**（`--apply` 無し）。dry-run では正本DBを `mode=ro` でしか開かない。
  - dry-run は「投入予定の集計・自然キー重複・NULL/物理レンジ異常・来歴完全性」を検証し、
    実行予定の SQL を `reports/` に出力するだけ。**正本DBは一切変更しない**。
  - `--apply` パス（**本タスクでは実行禁止**・承認後に Tatsuki が実行）:
    事前フルバックアップ → `CREATE TABLE IF NOT EXISTS` + UNIQUE INDEX → PASS 行を INSERT OR REPLACE →
    **業務テーブル件数 before==after を assert**（変化したら rollback）。
    **VIEW `race_lap_detail` はここでは作らない**（別承認・SQL は出力のみ）。

対象初期値: `session_type IN ('RACE1','RACE2')` かつ `gate_status='PASS'`（RACE 先行）。

使い方:
  python3 apply_pdf_v2_staging.py                 # dry-run（既定・正本DB read-only）
  python3 apply_pdf_v2_staging.py --sessions RACE1,RACE2 --gate PASS
  # python3 apply_pdf_v2_staging.py --apply        # ← 承認後のみ。本タスクでは実行しない
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
CANON_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
SCRATCH_DB = Path("/tmp/ts24_pdf_v2_scratch.db")
REPORTS_DIR = SCRIPT_DIR / "reports"
BACKUP_ROOT = DATA_ROOT / "02_DATABASE"

BUSINESS_TABLES = ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]
STAGING_TABLE = "pdf_lap_times_v2_staging"

# staging が持つ列（scratch と一致）
STAGING_COLS = [
    "round", "circuit", "session_type", "date", "position", "rider_num", "rider_name",
    "lap_no", "seg1", "seg2", "seg3", "seg4", "lap_time", "lap_time_s", "speed",
    "local_time", "is_outlap", "is_pit", "is_cancelled",
    "source_file", "extractor_version", "generated_at", "gate_status", "data_scope",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [APPLY] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)


# ── SQL 生成（純関数・レビュー用に分離） ────────────────────────────────────

def ddl_staging() -> str:
    return f"""CREATE TABLE IF NOT EXISTS {STAGING_TABLE} (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round TEXT, circuit TEXT, session_type TEXT, date TEXT,
    position INTEGER, rider_num INTEGER, rider_name TEXT, lap_no INTEGER,
    seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,
    lap_time TEXT, lap_time_s REAL, speed REAL, local_time TEXT,
    is_outlap INTEGER DEFAULT 0, is_pit INTEGER DEFAULT 0, is_cancelled INTEGER DEFAULT 0,
    source_file TEXT, extractor_version TEXT, generated_at TEXT,
    gate_status TEXT, data_scope TEXT DEFAULT 'TS24_PRIVATE'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pdf_v2_staging
  ON {STAGING_TABLE}(round, session_type, rider_num, lap_no, date);"""


def ddl_view(gate_levels: list[str]) -> str:
    """Workbench 切替用 VIEW（別承認・本スクリプトでは実行しない。SQL 出力のみ）。"""
    lvl = ", ".join(f"'{g}'" for g in gate_levels)
    return f"""-- 別タスク・別承認で作成（apply_pdf_v2_staging は VIEW を作らない）
CREATE VIEW IF NOT EXISTS race_lap_detail AS
SELECT round,circuit,session_type,date,position,rider_num,rider_name,lap_no,
       seg1,seg2,seg3,seg4,lap_time,lap_time_s,speed,local_time,
       is_outlap,is_pit,is_cancelled,
       source_file, extractor_version, gate_status, 'v2' AS source_tag
  FROM {STAGING_TABLE}
 WHERE gate_status IN ({lvl})
UNION ALL
SELECT p.round,p.circuit,p.session_type,p.date,p.position,p.rider_num,p.rider_name,p.lap_no,
       p.seg1,p.seg2,p.seg3,p.seg4,p.lap_time,p.lap_time_s,p.speed,p.local_time,
       p.is_outlap,p.is_pit,p.is_cancelled,
       p.source_file, NULL AS extractor_version, NULL AS gate_status, 'legacy' AS source_tag
  FROM pdf_lap_times p
 WHERE NOT EXISTS (
   SELECT 1 FROM {STAGING_TABLE} s
    WHERE s.round=p.round AND s.session_type=p.session_type
      AND s.rider_num=p.rider_num AND s.gate_status IN ({lvl}));"""


def insert_sql() -> str:
    cols = ", ".join(STAGING_COLS)
    ph = ", ".join("?" for _ in STAGING_COLS)
    return f"INSERT OR REPLACE INTO {STAGING_TABLE} ({cols}) VALUES ({ph})"


# ── 集計・検証（read-only） ──────────────────────────────────────────────────

def ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


def business_counts() -> dict:
    c = ro(CANON_DB)
    out = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_TABLES}
    c.close()
    return out


def candidate_where(sessions: list[str], gates: list[str]) -> tuple[str, list]:
    s_ph = ",".join("?" for _ in sessions)
    g_ph = ",".join("?" for _ in gates)
    return (f"session_type IN ({s_ph}) AND gate_status IN ({g_ph})",
            list(sessions) + list(gates))


def analyze(scr: sqlite3.Connection, sessions: list[str], gates: list[str]) -> dict:
    where, params = candidate_where(sessions, gates)
    g = scr.execute
    n_rows = g(f"SELECT COUNT(*) FROM {STAGING_TABLE} WHERE {where}", params).fetchone()[0]
    n_rs = g(f"SELECT COUNT(*) FROM (SELECT 1 FROM {STAGING_TABLE} WHERE {where} "
             f"GROUP BY round,session_type,rider_num)", params).fetchone()[0]
    n_seg = g(f"SELECT COUNT(*) FROM {STAGING_TABLE} WHERE {where} AND seg1 IS NOT NULL", params).fetchone()[0]
    # 自然キー重複（候補集合内）
    dups = g(f"""SELECT round,session_type,rider_num,lap_no,date,COUNT(*) c
                 FROM {STAGING_TABLE} WHERE {where}
                 GROUP BY round,session_type,rider_num,lap_no,date HAVING c>1""", params).fetchall()
    # 異常検査
    null_date = g(f"SELECT COUNT(*) FROM {STAGING_TABLE} WHERE {where} AND (date IS NULL OR date='')", params).fetchone()[0]
    null_lt = g(f"SELECT COUNT(*) FROM {STAGING_TABLE} WHERE {where} AND lap_time_s IS NULL", params).fetchone()[0]
    bad_prov = g(f"""SELECT COUNT(*) FROM {STAGING_TABLE} WHERE {where}
                     AND (source_file IS NULL OR extractor_version IS NULL OR generated_at IS NULL)""", params).fetchone()[0]
    # 物理レンジ異常: valid(=is_cancelled=0) lap が rider-session best の [0.9,1.6] 外
    range_bad = g(f"""
        WITH cand AS (SELECT * FROM {STAGING_TABLE} WHERE {where}),
             best AS (SELECT round,session_type,rider_num, MIN(lap_time_s) b
                        FROM cand WHERE is_cancelled=0 AND lap_time_s IS NOT NULL
                        GROUP BY round,session_type,rider_num)
        SELECT COUNT(*) FROM cand c JOIN best b
          ON c.round=b.round AND c.session_type=b.session_type AND c.rider_num=b.rider_num
        WHERE c.is_cancelled=0 AND c.lap_time_s IS NOT NULL
          AND (c.lap_time_s < b.b*0.90 OR c.lap_time_s > b.b*1.60)""", params).fetchone()[0]
    per_round = g(f"""SELECT round, session_type,
                        COUNT(*) rows,
                        COUNT(DISTINCT rider_num) riders,
                        SUM(CASE WHEN seg1 IS NOT NULL THEN 1 ELSE 0 END) seg_rows
                      FROM {STAGING_TABLE} WHERE {where}
                      GROUP BY round, session_type ORDER BY round, session_type""", params).fetchall()
    return dict(n_rows=n_rows, n_rs=n_rs, n_seg=n_seg, dups=dups, null_date=null_date,
                null_lt=null_lt, bad_prov=bad_prov, range_bad=range_bad, per_round=per_round)


def fetch_candidates(scr: sqlite3.Connection, sessions: list[str], gates: list[str]) -> list[tuple]:
    where, params = candidate_where(sessions, gates)
    cols = ", ".join(STAGING_COLS)
    rows = scr.execute(f"SELECT {cols} FROM {STAGING_TABLE} WHERE {where} "
                       f"ORDER BY round,session_type,rider_num,lap_no", params).fetchall()
    return [tuple(r) for r in rows]


# ── レポート / SQL 出力 ──────────────────────────────────────────────────────

def write_sql_file(gates: list[str]) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    p = REPORTS_DIR / "pdf_v2_staging_ddl_20260627.sql"
    body = [
        "-- Result PDF v2 staging DDL（レビュー用・apply_pdf_v2_staging.py が dry-run 出力）",
        "-- 1) staging テーブル + UNIQUE INDEX（apply 時に実行）",
        ddl_staging(),
        "",
        "-- 2) INSERT 文テンプレート（apply 時に PASS 行を bind 実行）",
        insert_sql() + ";",
        "",
        "-- 3) Workbench 切替用 VIEW（★別タスク・別承認。apply_pdf_v2_staging では実行しない）",
        ddl_view(gates),
        "",
    ]
    p.write_text("\n".join(body), encoding="utf-8")
    return p


def write_dryrun_report(a: dict, sessions: list[str], gates: list[str],
                        before: dict, after: dict, sql_path: Path) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    p = REPORTS_DIR / "pdf_v2_staging_dry_run_20260627.md"
    L = []
    L.append(f"# Result PDF v2 staging 反映 dry-run — {datetime.now():%Y-%m-%d %H:%M}")
    L.append("")
    L.append("**dry-run（正本DBは `mode=ro`・無変更）**。`apply_pdf_v2_staging.py`（`--apply` 無し）。")
    L.append(f"対象: `session_type IN {tuple(sessions)}` かつ `gate_status IN {tuple(gates)}`。"
             f" 入力 scratch=`{SCRATCH_DB}`。反映先(承認後)=正本DB内 **新規** `{STAGING_TABLE}`。")
    L.append("")
    L.append("## 投入予定サマリ")
    L.append("")
    L.append(f"- 投入予定 lap 行数: **{a['n_rows']}**")
    L.append(f"- 投入予定 rider-session 数: **{a['n_rs']}**")
    L.append(f"- seg 充填行: {a['n_seg']}（{(a['n_seg']/a['n_rows']*100 if a['n_rows'] else 0):.1f}%・"
             "スタートラップ等は NULL=正常）")
    L.append("")
    L.append("## 検証（投入前チェック）")
    L.append("")
    L.append("| 検査 | 結果 | 判定 |")
    L.append("|---|---:|:--:|")
    L.append(f"| 自然キー重複（候補内） | {len(a['dups'])} | {'✅' if not a['dups'] else '❌'} |")
    L.append(f"| date NULL/空 行 | {a['null_date']} | {'✅' if a['null_date']==0 else '⚠️'} |")
    L.append(f"| lap_time_s NULL 行 | {a['null_lt']} | {'✅' if a['null_lt']==0 else '⚠️'} |")
    L.append(f"| 来歴欠落行（source/extractor/generated）| {a['bad_prov']} | {'✅' if a['bad_prov']==0 else '❌'} |")
    L.append(f"| 物理レンジ外 valid lap（best×[0.9,1.6]） | {a['range_bad']} | {'✅' if a['range_bad']==0 else '⚠️'} |")
    L.append("")
    if a["dups"]:
        L.append("⚠️ 自然キー重複（要確認）:")
        for d in a["dups"][:20]:
            L.append(f"- {tuple(d)}")
        L.append("")
    L.append("## ラウンド×セッション別 内訳")
    L.append("")
    L.append("| round | session | rows | riders | seg_rows |")
    L.append("|---|---|---:|---:|---:|")
    for r in a["per_round"]:
        L.append(f"| {r['round']} | {r['session_type']} | {r['rows']} | {r['riders']} | {r['seg_rows']} |")
    L.append("")
    L.append("## 正本DB業務テーブル（dry-run: 無変更を確認）")
    L.append("")
    L.append("| table | before | after | 不変 |")
    L.append("|---|---:|---:|:--:|")
    for t in BUSINESS_TABLES:
        ok = "✅" if before[t] == after[t] else "❌"
        L.append(f"| {t} | {before[t]} | {after[t]} | {ok} |")
    L.append("")
    L.append("## 生成 SQL")
    L.append("")
    L.append(f"- レビュー用 SQL: `{sql_path.relative_to(SCRIPT_DIR)}`")
    L.append("  （staging DDL + UNIQUE INDEX + INSERT テンプレート + 参考 VIEW。VIEW は別承認・本スクリプト不実行）")
    L.append("")
    L.append("## 承認後に Tatsuki が実行するコマンド（案）")
    L.append("")
    L.append("```bash")
    L.append("# 1) RACE PASS を正本 staging へ反映（事前バックアップ + before==after assert 付き）")
    L.append("python3 apply_pdf_v2_staging.py --apply")
    L.append("# 2) （別承認）Workbench 切替用 VIEW を作成 → その後 Workbench を RACE_LAP_SRC=race_lap_detail に")
    L.append("#    VIEW SQL は reports/pdf_v2_staging_ddl_20260627.sql の (3) を参照")
    L.append("```")
    L.append("")
    L.append("> `--apply` は正本DBへ書き込む（新規 staging テーブル作成 + INSERT）。"
             "業務テーブルは不変（before==after を assert・違反時 rollback）。VIEW 作成と Workbench 切替は別タスク・別承認。")
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ── apply パス（承認後のみ・本タスクでは実行しない） ─────────────────────────

def do_apply(sessions: list[str], gates: list[str]) -> int:
    """正本DBへ staging を作成し PASS 行を反映。業務テーブル不変を assert。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    before = business_counts()
    # 事前バックアップ（フル DB コピー）
    bdir = BACKUP_ROOT / f"_backup_pdf_v2_staging_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANON_DB, bdir / CANON_DB.name)
    log.info("バックアップ作成: %s", bdir / CANON_DB.name)

    scr = ro(SCRATCH_DB)
    rows = fetch_candidates(scr, sessions, gates)
    scr.close()

    conn = sqlite3.connect(str(CANON_DB))
    try:
        conn.executescript(ddl_staging())
        conn.executemany(insert_sql(), rows)
        # 業務テーブル不変 assert（同一接続内）
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_TABLES}
        if after != before:
            conn.rollback()
            log.error("業務テーブル件数が変化！rollback。before=%s after=%s", before, after)
            return 3
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.error("apply 失敗 rollback: %s", e)
        conn.close()
        return 1
    n_staging = conn.execute(f"SELECT COUNT(*) FROM {STAGING_TABLE}").fetchone()[0]
    conn.close()
    log.info("apply 完了: %s 行（業務テーブル不変・バックアップ=%s）", n_staging, bdir)
    return 0


def main():
    ap = argparse.ArgumentParser(description="Result PDF v2 PASS 行の正本 staging 反映（既定 dry-run）")
    ap.add_argument("--apply", action="store_true",
                    help="正本DBへ実反映（★承認後のみ。既定は dry-run）")
    ap.add_argument("--sessions", default="RACE1,RACE2", help="対象 session_type（カンマ区切り）")
    ap.add_argument("--gate", default="PASS", help="対象 gate_status（カンマ区切り）")
    args = ap.parse_args()
    sessions = [s.strip() for s in args.sessions.split(",") if s.strip()]
    gates = [g.strip() for g in args.gate.split(",") if g.strip()]

    if not CANON_DB.exists():
        log.error("正本DBが見つかりません: %s", CANON_DB)
        sys.exit(1)
    if not SCRATCH_DB.exists():
        log.error("scratch が見つかりません: %s（先に `python3 pdf_v2_scratch_gate.py --all`）", SCRATCH_DB)
        sys.exit(1)

    if args.apply:
        log.warning("--apply: 正本DBへ書き込みます（新規 staging のみ・業務テーブル不変 assert）")
        sys.exit(do_apply(sessions, gates))

    # ── dry-run（既定）──
    before = business_counts()
    scr = ro(SCRATCH_DB)
    a = analyze(scr, sessions, gates)
    scr.close()
    after = business_counts()  # dry-run は無変更のはず

    sql_path = write_sql_file(gates)
    rep = write_dryrun_report(a, sessions, gates, before, after, sql_path)

    log.info("dry-run: 投入予定 %s 行 / %s rider-session（seg充填 %s）",
             a["n_rows"], a["n_rs"], a["n_seg"])
    log.info("検証: dup=%d null_date=%d null_lt=%d bad_prov=%d range_bad=%d",
             len(a["dups"]), a["null_date"], a["null_lt"], a["bad_prov"], a["range_bad"])
    log.info("業務テーブル不変: %s", "✅" if before == after else "❌ 変化あり")
    log.info("レポート: %s", rep)
    log.info("SQL: %s", sql_path)
    log.info("※ 正本DBへの反映は未実施（--apply は承認後のみ）")


if __name__ == "__main__":
    main()
