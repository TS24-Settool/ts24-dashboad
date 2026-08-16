#!/usr/bin/env python3
"""
apply_round8_provisional_clear.py — ROUND8 provisional クリア（既定 dry-run）
============================================================================
canonical 等価性を検証してから ROUND8 provisional 行（両 event key）を削除する。
CLAUDE.md §65d の Round7 provisional クリアの ROUND8 一般化（2026-07-13 Track A Phase 2）。

前提（このスクリプト内で検証・不成立なら削除しない）:
  - canonical ROUND8 = 16 runs / 144 laps / 144 lap_suspension（targeted insert 反映済み）。
  - 全 137 provisional lap が canonical に 2D 値一致（lap_time_s/susf_mean/susr_mean/
    f_dive_spd/r_dive_spd, |Δ|<=1e-6）の対応行を持つ。
  - JA52 RACE1 R1 = C106（§3c 補正済み）。

削除対象: runs/laps/lap_suspension_provisional の
  provisional_event_key IN ('20260710-ROUND8-JA52','20260710-ROUND8-DA77') → 0/0/0。

queue 遷移（ROUND8 source 限定・歴史的クリーンアップなし）:
  - ROUND8 2d_extract awaiting_gate 15件 → done（note: promoted to canonical final 20260713）
  - ROUND8 2d_extract pending 1件（WU2-#77-01・provisional 未経由）→ done
    （note: promoted via final integration, never provisional）
  - failed 4件（SX×2 / WU1-01 / WU1-02）は証拠として不変。registry incomplete（SP-77-03）不変。
  - report_import / pdf_extract の pending 行は queue consumer 未実装のため不変
    （データ自体は final integration で反映済み — apply レポートに記録）。

canonical 業務テーブルはこのクリアで一切変化しないことを assert。
"""
import argparse
import datetime
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CANON = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", "ts24_unified.db"))
EVENT_KEYS = ("20260710-ROUND8-JA52", "20260710-ROUND8-DA77")
CANON_TABLES = ("runs", "laps", "lap_suspension", "race_results", "pdf_lap_times",
                "pdf_lap_times_v2_staging", "source_file_registry",
                "data_quality_log", "analysis_run_log", "metric_version_log")
PROV_TABLES = ("runs_provisional", "laps_provisional", "lap_suspension_provisional")
EXPECT_R8 = (16, 144, 144)
RACE1_R1 = "20260710_ROUND8_DONINGTON_RACE1_JA52_R1"


def counts(con, tables):
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def prov_counts(con):
    q = "SELECT COUNT(*) FROM %s WHERE provisional_event_key IN (?,?)"
    return tuple(con.execute(q % t, EVENT_KEYS).fetchone()[0] for t in PROV_TABLES)


def equivalence_gate(con):
    msgs, ok = [], True
    r8 = (con.execute("SELECT COUNT(*) FROM runs WHERE round='ROUND8'").fetchone()[0],
          con.execute("SELECT COUNT(*) FROM laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round='ROUND8'").fetchone()[0],
          con.execute("SELECT COUNT(*) FROM lap_suspension WHERE round='ROUND8'").fetchone()[0])
    if r8 != EXPECT_R8:
        ok = False
    msgs.append(f"canonical ROUND8 shape={r8} (expect {EXPECT_R8}) -> {'PASS' if r8 == EXPECT_R8 else 'FAIL'}")

    COLS = "lap_time_s,susf_mean,susr_mean,f_dive_spd,r_dive_spd"
    total = mat = miss = 0
    for (plid,) in con.execute(
            "SELECT lap_id FROM laps_provisional WHERE provisional_event_key IN (?,?)", EVENT_KEYS):
        total += 1
        clid = plid[len("PROV_"):] if plid.startswith("PROV_") else plid
        crow = con.execute(f"SELECT {COLS} FROM laps WHERE lap_id=?", (clid,)).fetchone()
        if not crow:
            miss += 1
            continue
        prow = con.execute(f"SELECT {COLS} FROM laps_provisional WHERE lap_id=?", (plid,)).fetchone()
        if all((a is None and b is None) or
               (a is not None and b is not None and abs(a - b) <= 1e-6)
               for a, b in zip(crow, prow)):
            mat += 1
    g = (total == 137 and mat == 137 and miss == 0)
    if not g:
        ok = False
    msgs.append(f"provisional->canonical lap equivalence: total={total} matched={mat} missing={miss} "
                f"(expect 137/137/0) -> {'PASS' if g else 'FAIL'}")

    setg = con.execute("SELECT f_set_c FROM runs WHERE run_id=?", (RACE1_R1,)).fetchone()
    g2 = bool(setg) and setg[0] == "C106"
    if not g2:
        ok = False
    msgs.append(f"RACE1 R1 setting={setg[0] if setg else None} (expect C106) -> {'PASS' if g2 else 'FAIL'}")
    return ok, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    cc = sqlite3.connect(f"file:{CANON}?mode=ro", uri=True)
    ok, msgs = equivalence_gate(cc)
    print("== canonical equivalence gate ==")
    for m in msgs:
        print("  " + m)
    print("  GATE:", "ALL PASS" if ok else "FAIL")

    pc = prov_counts(cc)
    print(f"\nROUND8 provisional rows (runs/laps/ls) = {pc} (expect (15, 137, 137))")
    q2d = cc.execute(
        "SELECT status, COUNT(*) FROM import_queue WHERE target_kind='2d_extract' "
        "AND file_path LIKE '%ROUND8%' GROUP BY status").fetchall()
    print("ROUND8 2d_extract queue:", q2d)
    cc.close()

    if not args.apply:
        print("\nDRY-RUN only. Planned: DELETE provisional rows for", EVENT_KEYS,
              "\n  queue: awaiting_gate/pending 2d_extract ROUND8 -> done (failed rows kept as evidence)")
        sys.exit(0 if ok and pc == (15, 137, 137) else 2)

    if not ok or pc != (15, 137, 137):
        print("REFUSING to clear: gate failed or unexpected provisional counts.")
        sys.exit(3)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", f"_backup_round8_provclear_{ts}"))
    os.makedirs(bdir, exist_ok=True)
    con = sqlite3.connect(CANON, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        pass
    shutil.copy2(CANON, os.path.join(bdir, "ts24_unified.db"))
    for sfx in ("-wal", "-shm"):
        if os.path.exists(CANON + sfx):
            shutil.copy2(CANON + sfx, os.path.join(bdir, "ts24_unified.db" + sfx))
    print("backup ->", bdir)

    before = counts(con, CANON_TABLES)
    note = "promoted to canonical final (ROUND8 final integration 2026-07-13)"
    note_wu2 = "promoted via final integration (never provisional; zero-provisional path)"
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        con.execute("BEGIN")
        for t in PROV_TABLES:
            con.execute(f"DELETE FROM {t} WHERE provisional_event_key IN (?,?)", EVENT_KEYS)
        con.execute(
            "UPDATE import_queue SET status='done', finished_at=?, notes=? "
            "WHERE target_kind='2d_extract' AND status='awaiting_gate' AND file_path LIKE '%ROUND8%'",
            (now, note))
        n_ag = con.execute("SELECT changes()").fetchone()[0]
        con.execute(
            "UPDATE import_queue SET status='done', finished_at=?, notes=? "
            "WHERE target_kind='2d_extract' AND status='pending' AND file_path LIKE '%ROUND8%'",
            (now, note_wu2))
        n_pd = con.execute("SELECT changes()").fetchone()[0]
        if n_ag != 15 or n_pd != 1:
            raise RuntimeError(f"queue transitions unexpected: awaiting_gate->{n_ag} (exp 15) pending->{n_pd} (exp 1)")
        after = counts(con, CANON_TABLES)
        if after != before:
            raise RuntimeError(f"canonical changed by clear: {before} -> {after}")
        pcn = prov_counts(con)
        if pcn != (0, 0, 0):
            raise RuntimeError(f"provisional not fully cleared: {pcn}")
        failed_kept = con.execute(
            "SELECT COUNT(*) FROM import_queue WHERE target_kind='2d_extract' "
            "AND status='failed' AND file_path LIKE '%ROUND8%'").fetchone()[0]
        if failed_kept != 4:
            raise RuntimeError(f"failed evidence rows={failed_kept} != 4")
        con.execute("COMMIT")
        print(f"CLEARED. provisional={pcn} queue: awaiting_gate->done={n_ag} pending->done={n_pd} "
              f"failed kept={failed_kept} canonical unchanged ✅")
    except Exception as e:
        con.execute("ROLLBACK")
        print("ROLLED BACK due to:", repr(e))
        print("Restore from backup if needed:", bdir)
        con.close()
        sys.exit(3)
    con.close()


if __name__ == "__main__":
    main()
