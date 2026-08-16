#!/usr/bin/env python3
"""
Round7 JA52 provisional -> final targeted insert (Option A).

SAFETY MODEL
------------
- Default is DRY-RUN (no --apply): canonical DB is opened read-only (mode=ro),
  nothing is written. Prints exactly what --apply would do.
- Writes ONLY canonical business tables `runs` / `laps` / `lap_suspension`,
  and ONLY the Round7 rows (INSERT) + the two 0-lap placeholders (DELETE).
- Does NOT touch: pdf_lap_times_v2_staging, race_lap_detail VIEW,
  source_file_registry, import_queue, data_quality_log, analysis_run_log,
  metric_version_log, runs_provisional/laps_provisional/lap_suspension_provisional,
  Supabase, DB Master. (Provisional clear = separate GO.)
- Does NOT use cutover_db.py. Does NOT rebuild/swap the whole DB.

PRECONDITION (must be produced fresh, outside this script)
----------------------------------------------------------
A fresh scratch rebuild at --scratch, produced by:
    build_master_db.py --all --out <scratch.db>
and the deterministic gate (r7_gate.py) must be ALL PASS:
    - runs/laps/lap_suspension schema identical
    - non-Round7 preserved rows byte-identical (excl created_at/updated_at)
    - Round7 final shape == 13 runs / 77 laps / 77 lap_suspension
This script re-verifies the gate internally and REFUSES to apply otherwise.

Usage:
    python3 apply_round7_targeted_insert.py --scratch /tmp/scratch.db            # dry-run
    python3 apply_round7_targeted_insert.py --scratch /tmp/scratch.db --apply    # write (after GO)
"""
import argparse, os, shutil, sqlite3, sys, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
CANON = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", "ts24_unified.db"))
PLACEHOLDERS = ("NA_MISANO_RACE1_JA52_R1", "NA_MISANO_RACE2_JA52_R1")
TARGET_TABLES = ("runs", "laps", "lap_suspension")
PROTECTED = ("pdf_lap_times_v2_staging", "race_lap_detail", "source_file_registry",
             "import_queue", "data_quality_log", "analysis_run_log", "metric_version_log",
             "runs_provisional", "laps_provisional", "lap_suspension_provisional",
             "race_results", "pdf_lap_times")
TS_COLS = {"created_at", "updated_at", "intake_ts"}
EXPECT_FINAL = {"runs": 286, "laps": 1279, "lap_suspension": 1279}
EXPECT_R7 = (13, 77, 77)
# Expected best_lap_s per data-bearing final Round7 run (§64 mapping). The two
# 0-lap Original-only RACE R2 rows legitimately have best_lap_s NULL, so they
# are NOT in this dict. Used to prove the scratch rows are the merged FINAL rows.
EXPECT_BEST = {
    "20260612_ROUND7_MISANO_FP_JA52_R1": 99.429,
    "20260612_ROUND7_MISANO_FP_JA52_R2": 98.791,
    "20260612_ROUND7_MISANO_FP_JA52_R3": 98.364,
    "20260612_ROUND7_MISANO_QP_JA52_R1": 97.953,
    "20260612_ROUND7_MISANO_QP_JA52_R2": 98.250,
    "20260612_ROUND7_MISANO_QP_JA52_R3": 97.636,
    "20260612_ROUND7_MISANO_QP_JA52_R4": 101.714,
    "20260612_ROUND7_MISANO_WUP1_JA52_R1": 98.109,
    "20260612_ROUND7_MISANO_WUP2_JA52_R1": 98.160,
    "20260612_ROUND7_MISANO_RACE1_JA52_R1": 98.055,
    "20260612_ROUND7_MISANO_RACE2_JA52_R1": 97.778,
}
# The two 0-lap Original-only RACE R2 rows that replace the placeholders.
EXPECT_ZERO_LAP = ("20260612_ROUND7_MISANO_RACE1_JA52_R2",
                   "20260612_ROUND7_MISANO_RACE2_JA52_R2")


def cols(con, t):
    return [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]


def counts(con):
    d = {}
    for t in TARGET_TABLES + PROTECTED:
        try:
            d[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except sqlite3.Error:
            d[t] = None
    return d


def r7_counts(con):
    runs = con.execute("SELECT COUNT(*) FROM runs WHERE round='ROUND7'").fetchone()[0]
    laps = con.execute("SELECT COUNT(*) FROM laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round='ROUND7'").fetchone()[0]
    susp = con.execute("SELECT COUNT(*) FROM lap_suspension WHERE round='ROUND7'").fetchone()[0]
    return (runs, laps, susp)


def deterministic_gate(cc, sc):
    """Return (ok, messages). Non-Round7 preserved rows must be byte-identical."""
    msgs = []
    ok = True
    for t in TARGET_TABLES:
        if cols(cc, t) != cols(sc, t):
            ok = False
            msgs.append("SCHEMA MISMATCH on %s" % t)
    # value identity for preserved (non-placeholder, non-Round7) rows
    for t, key in (("runs", "run_id"), ("laps", "lap_id"), ("lap_suspension", "lap_id")):
        vcols = [c for c in cols(cc, t) if c not in TS_COLS and c != key]
        if t == "laps":
            cwhere = "WHERE run_id NOT IN ('%s','%s')" % PLACEHOLDERS
            swhere = "WHERE run_id NOT IN (SELECT run_id FROM runs WHERE round='ROUND7')"
        elif t == "runs":
            cwhere = "WHERE run_id NOT IN ('%s','%s')" % PLACEHOLDERS
            swhere = "WHERE round!='ROUND7'"
        else:
            cwhere = "WHERE run_id NOT IN ('%s','%s')" % PLACEHOLDERS
            swhere = "WHERE round!='ROUND7'"
        cmap = {r[0]: tuple(r[1:]) for r in cc.execute("SELECT %s,%s FROM %s %s" % (key, ",".join(vcols), t, cwhere))}
        smap = {r[0]: tuple(r[1:]) for r in sc.execute("SELECT %s,%s FROM %s %s" % (key, ",".join(vcols), t, swhere))}
        miss = set(cmap) - set(smap); extra = set(smap) - set(cmap)
        mism = sum(1 for k in (set(cmap) & set(smap)) if cmap[k] != smap[k])
        if miss or extra or mism:
            ok = False
        msgs.append("gate %s: preserved=%d missing=%d extra=%d value_mismatch=%d -> %s"
                    % (t, len(cmap), len(miss), len(extra), mism, "PASS" if not (miss or extra or mism) else "FAIL"))
    shape = r7_counts(sc)
    if shape != EXPECT_R7:
        ok = False
    msgs.append("scratch Round7 shape=%s (expect %s) -> %s" % (shape, EXPECT_R7, "PASS" if shape == EXPECT_R7 else "FAIL"))
    return ok, msgs


def content_gate(con):
    """Prove the Round7 rows are the merged FINAL rows (setup + WF filled, best matches),
    not NULL-setup provisional-like rows. Returns (ok, messages). Queries round='ROUND7'."""
    msgs = []
    ok = True
    # 1) all 13 Round7 runs must have setup (f_spr_l) populated => Original merge happened
    null_setup = [r[0] for r in con.execute(
        "SELECT run_id FROM runs WHERE round='ROUND7' AND f_spr_l IS NULL")]
    if null_setup:
        ok = False
    msgs.append("setup(f_spr_l) NULL among Round7 runs=%d -> %s%s"
                % (len(null_setup), "PASS" if not null_setup else "FAIL",
                   (" " + str(null_setup[:3])) if null_setup else ""))
    # 2) wheel-force must be populated on Round7 lap_suspension (final vs provisional NULL)
    wf_filled = con.execute(
        "SELECT COUNT(*) FROM lap_suspension WHERE round='ROUND7' AND wf_f_apex_n IS NOT NULL").fetchone()[0]
    if wf_filled == 0:
        ok = False
    msgs.append("Round7 lap_suspension with wf_f_apex_n populated=%d (expect >=1) -> %s"
                % (wf_filled, "PASS" if wf_filled >= 1 else "FAIL"))
    # 3) best_lap_s of data-bearing runs matches mapping
    bad = []
    for rid, exp in EXPECT_BEST.items():
        row = con.execute("SELECT best_lap_s FROM runs WHERE run_id=?", (rid,)).fetchone()
        got = row[0] if row else None
        if got is None or abs(got - exp) > 0.001:
            bad.append((rid, got, exp))
    if bad:
        ok = False
    msgs.append("best_lap_s mismatch vs mapping=%d -> %s%s"
                % (len(bad), "PASS" if not bad else "FAIL", (" " + str(bad[:3])) if bad else ""))
    # 4) the two 0-lap Original-only R2 rows exist with 0 laps
    for rid in EXPECT_ZERO_LAP:
        n = con.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (rid,)).fetchone()[0]
        present = con.execute("SELECT 1 FROM runs WHERE run_id=? AND round='ROUND7'", (rid,)).fetchone()
        if not present or n != 0:
            ok = False
            msgs.append("zero-lap row %s present=%s laps=%d -> FAIL" % (rid, bool(present), n))
    return ok, msgs


def cross_source_gate(cc, sc):
    """Option-B validation: prove the Round7-only scratch build == a full --all build for
    ROUND7, by triangulating against provisional (same 2D source, different code path) and
    the §64 --all mapping. Used when the scratch has no non-Round7 rows to byte-compare."""
    msgs = []; ok = True
    # best_lap vs provisional (session,run_no keyed)
    prov = {}
    for r in cc.execute("SELECT session,run_no,best_lap_s FROM runs_provisional "
                        "WHERE provisional_event_key='20260612-ROUND7-JA52'"):
        prov[(r[0], r[1])] = r[2]
    fin = {}
    for r in sc.execute("SELECT session,run_no,best_lap_s FROM runs WHERE round='ROUND7'"):
        fin[(r[0], r[1])] = r[2]
    bmis = 0
    for k, pb in prov.items():
        if k in fin and fin[k] is not None and pb is not None and abs(fin[k] - pb) > 0.001:
            bmis += 1
    if bmis: ok = False
    msgs.append("best_lap vs provisional: shared=%d mismatch=%d -> %s"
                % (len([k for k in prov if k in fin]), bmis, "PASS" if not bmis else "FAIL"))
    # lap-level 2D-derived values vs provisional (strongest check)
    COLS = ["lap_time_s", "susf_mean", "susr_mean", "f_dive_spd", "r_dive_spd"]
    scols = ",".join(COLS)
    cmp = mat = 0
    for (lid,) in sc.execute("SELECT lap_id FROM laps WHERE run_id IN "
                             "(SELECT run_id FROM runs WHERE round='ROUND7')"):
        prow = cc.execute("SELECT %s FROM laps_provisional WHERE lap_id=?" % scols, ("PROV_" + lid,)).fetchone()
        if not prow:
            continue
        srow = sc.execute("SELECT %s FROM laps WHERE lap_id=?" % scols, (lid,)).fetchone()
        cmp += 1
        good = True
        for a, b in zip(srow, prow):
            if a is None and b is None:
                continue
            if a is None or b is None or abs(a - b) > 1e-6:
                good = False; break
        if good:
            mat += 1
    if cmp == 0 or mat != cmp:
        ok = False
    msgs.append("lap 2D-values vs provisional: compared=%d matched=%d -> %s"
                % (cmp, mat, "PASS" if (cmp > 0 and mat == cmp) else "FAIL"))
    return ok, msgs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", required=True, help="scratch rebuild DB (build_master_db --all [--round ROUND7] --out)")
    ap.add_argument("--scratch-scope", choices=["full", "round7"], default="full",
                    help="'full'=--all scratch (deterministic non-R7 gate); 'round7'=--round ROUND7 scratch (cross-source gate)")
    ap.add_argument("--apply", action="store_true", help="perform write (requires Round7 targeted insert GO)")
    args = ap.parse_args()

    if not os.path.exists(args.scratch):
        print("ERROR: scratch DB not found: %s" % args.scratch); sys.exit(1)

    # --- read-only verification against scratch ---
    cc = sqlite3.connect("file:%s?mode=ro" % CANON, uri=True)
    sc = sqlite3.connect("file:%s?mode=ro" % args.scratch, uri=True)

    pre = counts(cc)
    pre_r7 = r7_counts(cc)
    print("== canonical BEFORE ==")
    for t in TARGET_TABLES:
        print("  %-26s %s" % (t, pre[t]))
    print("  Round7 (runs/laps/susp) =", pre_r7, "(expect 0/0/0)")
    print("  placeholders present:", [p for p in PLACEHOLDERS
          if cc.execute("SELECT 1 FROM runs WHERE run_id=?", (p,)).fetchone()])

    if args.scratch_scope == "full":
        ok, msgs = deterministic_gate(cc, sc)
        print("\n== deterministic gate (non-Round7 byte-identity vs canonical) ==")
        for m in msgs:
            print("  " + m)
        print("  GATE OVERALL:", "ALL PASS" if ok else "FAIL")
    else:  # round7-only scratch: no non-Round7 rows to compare; use cross-source instead
        # still verify Round7 shape from scratch
        shape = r7_counts(sc)
        ok = (shape == EXPECT_R7)
        print("\n== round7-only scratch (deterministic non-R7 gate N/A) ==")
        print("  scratch Round7 shape=%s (expect %s) -> %s" % (shape, EXPECT_R7, "PASS" if ok else "FAIL"))
        xok, xmsgs = cross_source_gate(cc, sc)
        print("\n== cross-source gate (build == full-rebuild for ROUND7) ==")
        for m in xmsgs:
            print("  " + m)
        print("  CROSS-SOURCE GATE:", "ALL PASS" if xok else "FAIL")
        ok = ok and xok

    # content-completeness gate on the scratch Round7 rows (setup/WF/best populated)
    cok, cmsgs = content_gate(sc)
    print("\n== content gate (scratch Round7 rows) ==")
    for m in cmsgs:
        print("  " + m)
    print("  CONTENT GATE:", "ALL PASS" if cok else "FAIL")
    ok = ok and cok

    # rows that would be inserted (counts derived from scratch, not hardcoded)
    ins_runs = [r[0] for r in sc.execute("SELECT run_id FROM runs WHERE round='ROUND7' ORDER BY session,run_no")]
    sr = r7_counts(sc)
    print("\n== planned writes ==")
    print("  DELETE from runs (+ any child laps/lap_suspension): %s" % list(PLACEHOLDERS))
    print("  INSERT %d Round7 runs, %d laps, %d lap_suspension:" % (sr[0], sr[1], sr[2]))
    for rid in ins_runs:
        print("    +", rid)
    print("  UNTOUCHED protected tables:", ", ".join(PROTECTED))

    if not args.apply:
        print("\nDRY-RUN only. No canonical write. Re-run with --apply after 'Round7 targeted insert GO'.")
        cc.close(); sc.close(); return

    # ---------------- APPLY PATH (write) ----------------
    if not ok:
        print("\nREFUSING to apply: deterministic gate FAILED."); cc.close(); sc.close(); sys.exit(3)
    cc.close(); sc.close()

    print("\nNOTE: close any other DB writer (Workbench / Streamlit) before applying.")
    ts = os.environ.get("R7_TS") or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", "_backup_round7_targeted_%s" % ts))
    os.makedirs(backup_dir, exist_ok=True)

    con = sqlite3.connect(CANON, timeout=30)
    con.execute("PRAGMA busy_timeout=30000")  # retry instead of instant 'database is locked'
    # flush WAL frames into the main file (PASSIVE = never blocks on other connections,
    # unlike TRUNCATE which can hang if iCloud/another process holds the DB)
    try:
        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        pass
    # WAL-safe backup: main file + sidecars if present
    shutil.copy2(CANON, os.path.join(backup_dir, "ts24_unified.db"))
    for sfx in ("-wal", "-shm"):
        if os.path.exists(CANON + sfx):
            shutil.copy2(CANON + sfx, os.path.join(backup_dir, "ts24_unified.db" + sfx))
    print("backup ->", backup_dir)

    con.execute("ATTACH DATABASE ? AS scr", (args.scratch,))
    before = counts(con)
    try:
        con.execute("BEGIN")
        # delete placeholders (children first, defensively)
        for p in PLACEHOLDERS:
            con.execute("DELETE FROM lap_suspension WHERE run_id=?", (p,))
            con.execute("DELETE FROM laps WHERE run_id=?", (p,))
            con.execute("DELETE FROM runs WHERE run_id=?", (p,))
        # insert Round7 rows from scratch (explicit column lists = schema already gated identical)
        for t in TARGET_TABLES:
            colnames = ",".join(cols(con, t))
            if t == "laps":
                con.execute("INSERT INTO %s (%s) SELECT %s FROM scr.laps l "
                            "WHERE l.run_id IN (SELECT run_id FROM scr.runs WHERE round='ROUND7')"
                            % (t, colnames, colnames))
            else:
                con.execute("INSERT INTO %s (%s) SELECT %s FROM scr.%s WHERE round='ROUND7'"
                            % (t, colnames, colnames, t))
        # invariance asserts on protected tables
        after = counts(con)
        for t in PROTECTED:
            if before.get(t) != after.get(t):
                raise RuntimeError("PROTECTED table changed: %s %s->%s" % (t, before.get(t), after.get(t)))
        r7 = r7_counts(con)
        if r7 != EXPECT_R7:
            raise RuntimeError("Round7 shape after insert=%s expected %s" % (r7, EXPECT_R7))
        for t in TARGET_TABLES:
            if after[t] != EXPECT_FINAL[t]:
                raise RuntimeError("%s total=%s expected %s" % (t, after[t], EXPECT_FINAL[t]))
        # content-completeness: inserted Round7 rows must be the merged FINAL rows
        cok2, cmsgs2 = content_gate(con)
        if not cok2:
            raise RuntimeError("content gate FAILED after insert: %s" % "; ".join(cmsgs2))
        con.execute("COMMIT")
        print("APPLIED. Round7 shape=%s totals runs=%d laps=%d susp=%d"
              % (r7, after["runs"], after["laps"], after["lap_suspension"]))
    except Exception as e:
        con.execute("ROLLBACK")
        print("ROLLED BACK due to:", repr(e))
        print("Restore from backup if needed:", backup_dir)
        con.close(); sys.exit(3)
    con.close()


if __name__ == "__main__":
    main()
