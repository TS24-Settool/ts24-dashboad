#!/usr/bin/env python3
"""
apply_round8_targeted_insert.py — ROUND8(DONINGTON) provisional → final targeted insert
=======================================================================================
CLAUDE.md §65 の apply_round7_targeted_insert.py を ROUND8 用に一般化（2026-07-13 Track A
Phase 2・inbox 承認済みタスク）。readiness = reports/round8_final_integration_readiness_20260713.md。

SAFETY MODEL
------------
- 既定 DRY-RUN（--apply なし）: 正本DBは mode=ro のみ・無書込。
- 書込は canonical 業務テーブル runs / laps / lap_suspension への INSERT のみ。
  DELETE は一切しない（NA_DONINGTON_* 2025-era 行は UNTOUCHED — supervisor decision）。
- protected テーブル（race_results / pdf_lap_times / v2_staging / registry / queue /
  quality logs / metric_version_log / provisional 3テーブル / race_lap_detail VIEW）不変 assert。
- 失敗 invariant があれば ROLLBACK。

ROUND8 固有ルール（supervisor decision・readiness §3b/§3c/§7/§8）
----------------------------------------------------------------
1. SX 除外: session='SX'（SX_F1/SX_SP 汚染 2 runs/21 laps）は絶対に insert しない。
   inserted run_id に '_SX_' が含まれたら FAIL。
2. RACE2 hold: inserted rows の session='RACE2' はゼロでなければ FAIL。
3. §3c 補正（Original 2025 BSB Donington 重複キー起因の setup 誤付与）:
   - JA52 RACE1 telemetry R1 は scratch では C104(2025) を持つ → ghost R2 の C106(2026)
     setup payload（ORIG_FIELDS 33列）に差し替えて insert する。
   - 0-lap ghost RACE1 R2（20260710_ROUND8_DONINGTON_RACE1_JA52_R2）は insert しない。
   - R1 の 20 lap_suspension 行の wf_* 6列は C106 バネレートで再計算する
     （WF_F = susF×(f_spr_l+f_spr_r)/2 = susF×9.0, WF_R = susR×r_spr×0.5 = susR×42.0。
      build_master_db._build_lap_suspension と同一式・同一 round(…,1)）。
   - 既存 canonical NA_DONINGTON_RACE1/RACE2_JA52_R1（2025-era, round='', C104）は削除しない。
4. RACE2 telemetry は不在のまま（2026 C106 RACE2 setup は未表現 — documented, telemetry pending）。

期待値: +16 runs / +144 laps / +144 lap_suspension → totals 302 / 1423 / 1423。

Usage:
    python3 apply_round8_targeted_insert.py --scratch /tmp/ts24_r8_scratch.db          # dry-run
    python3 apply_round8_targeted_insert.py --scratch /tmp/ts24_r8_scratch.db --apply  # write
"""
import argparse
import datetime
import hashlib
import os
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CANON = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", "ts24_unified.db"))

ROUND = "ROUND8"
GHOST_R2 = "20260710_ROUND8_DONINGTON_RACE1_JA52_R2"      # 0-lap ORIGINAL-only ghost — NOT inserted
RACE1_R1 = "20260710_ROUND8_DONINGTON_RACE1_JA52_R1"      # gets the C106 payload from GHOST_R2
NA_ROWS = ("NA_DONINGTON_RACE1_JA52_R1", "NA_DONINGTON_RACE2_JA52_R1")  # 2025-era, untouched

TARGET_TABLES = ("runs", "laps", "lap_suspension")
PROTECTED = ("race_results", "pdf_lap_times", "pdf_lap_times_v2_staging",
             "source_file_registry", "import_queue", "data_quality_log",
             "analysis_run_log", "metric_version_log",
             "runs_provisional", "laps_provisional", "lap_suspension_provisional",
             "race_lap_detail")
EXPECT_INSERT = (16, 144, 144)
EXPECT_FINAL = {"runs": 302, "laps": 1423, "lap_suspension": 1423}
EXPECT_METRIC_VERSION_LOG = 32
EXPECT_PDF_LAP_TIMES = 7613
EXPECT_V2_STAGING = 7710

# Original 由来 setup 列（build_master_db.ORIG_FIELDS と同一・§3c payload swap の対象）
ORIG_SETUP_COLS = [
    "weather", "track_temp", "air_temp", "fork_type", "f_set_c", "f_set_r",
    "f_tos_spring", "f_tos_length", "f_spr_l", "f_spr_r", "f_preload",
    "f_oil_level", "f_comp", "f_reb", "f_offset", "f_offset2",
    "f_hgt_top", "f_hgt_bot", "shock_type", "r_set_c", "r_set_r", "r_spr",
    "r_preload", "r_comp", "r_reb", "r_tos_spring", "r_tos_length",
    "shock_len", "link", "ride_hgt", "swing_arm", "tyre_front", "tyre_rear",
]
# wf_* 再計算対象（lap_suspension）: (wf_col, susp_source_col, front?)
WF_MAP = [
    ("wf_f_apex_n", "apex_susF_avg", True), ("wf_r_apex_n", "apex_susR_avg", False),
    ("wf_f_brk_n", "brk_susF_avg", True), ("wf_r_brk_n", "brk_susR_avg", False),
    ("wf_f_ce_n", "ce_susF_avg", True), ("wf_r_ce_n", "ce_susR_avg", False),
]

# scratch 由来の期待 best_lap_s（16 insert runs・2026-07-13 scratch 実測 = readiness §3/§6 整合）
EXPECT_BEST = {
    "20260710_ROUND8_DONINGTON_FP_JA52_R1": 90.240,
    "20260710_ROUND8_DONINGTON_FP_JA52_R2": 89.960,
    "20260710_ROUND8_DONINGTON_QP_JA52_R1": 89.674,
    "20260710_ROUND8_DONINGTON_QP_JA52_R2": 89.905,
    "20260710_ROUND8_DONINGTON_QP_JA52_R3": 89.123,
    "20260710_ROUND8_DONINGTON_WUP1_JA52_R1": 89.202,
    "20260710_ROUND8_DONINGTON_WUP2_JA52_R1": 89.994,
    "20260710_ROUND8_DONINGTON_RACE1_JA52_R1": 89.195,
    "20260710_ROUND8_DONINGTON_FP_DA77_R1": 89.960,
    "20260710_ROUND8_DONINGTON_FP_DA77_R2": 90.189,
    "20260710_ROUND8_DONINGTON_SP_DA77_R1": 90.105,
    "20260710_ROUND8_DONINGTON_SP_DA77_R2": 90.140,
    "20260710_ROUND8_DONINGTON_SP_DA77_R3": 89.622,
    "20260710_ROUND8_DONINGTON_WUP1_DA77_R1": 90.105,
    "20260710_ROUND8_DONINGTON_WUP2_DA77_R1": 89.885,
    "20260710_ROUND8_DONINGTON_RACE1_DA77_R1": 89.738,
}
# DA77 WUP2 は provisional 双子なし → staging dry-run 実測で照合（readiness §2/§8.6）
DA77_WUP2_RUN = "20260710_ROUND8_DONINGTON_WUP2_DA77_R1"
DA77_WUP2_LAPS, DA77_WUP2_BEST = 7, 89.885
PROV_EVENT_KEYS = ("20260710-ROUND8-JA52", "20260710-ROUND8-DA77")


def cols(con, t):
    return [r[1] for r in con.execute(f"PRAGMA table_info({t})")]


def counts(con):
    d = {}
    for t in TARGET_TABLES + PROTECTED:
        try:
            d[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            d[t] = None
    return d


def r8_counts(con):
    runs = con.execute("SELECT COUNT(*) FROM runs WHERE round=?", (ROUND,)).fetchone()[0]
    laps = con.execute("SELECT COUNT(*) FROM laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round=?", (ROUND,)).fetchone()[0]
    susp = con.execute("SELECT COUNT(*) FROM lap_suspension WHERE round=?", (ROUND,)).fetchone()[0]
    return (runs, laps, susp)


def non_r8_hash(con):
    """非 ROUND8 canonical 行の byte-identity 検証用ハッシュ（3テーブル）。"""
    h = hashlib.sha256()
    for t, key, where in (
            ("runs", "run_id", "COALESCE(round,'')!='ROUND8'"),
            ("laps", "lap_id", "run_id NOT IN (SELECT run_id FROM runs WHERE round='ROUND8')"),
            ("lap_suspension", "lap_id", "COALESCE(round,'')!='ROUND8'")):
        cs = ",".join(cols(con, t))
        for row in con.execute(f"SELECT {cs} FROM {t} WHERE {where} ORDER BY {key}"):
            h.update(repr(row).encode())
    return h.hexdigest()


def wf_expected(susp, front):
    """build_master_db._build_lap_suspension と同一式（C106: fspr=9.0, r_spr=84 → ×42.0）。"""
    if susp is None:
        return None
    return round(susp * 9.0, 1) if front else round(susp * 42.0, 1)


def plan_insert(sc):
    """scratch から insert 対象を決定。返り値 (run_ids, msgs, ok)。"""
    msgs, ok = [], True
    all_r8 = [r[0] for r in sc.execute(
        "SELECT run_id FROM runs WHERE round=? ORDER BY rider, session, run_no", (ROUND,))]
    sx = [r for r in all_r8 if "_SX_" in r]
    ins = [r for r in all_r8 if "_SX_" not in r and r != GHOST_R2]
    msgs.append(f"scratch ROUND8 runs={len(all_r8)} / SX excluded={len(sx)} {sx} / "
                f"ghost excluded=1 [{GHOST_R2}] / to insert={len(ins)}")
    if len(ins) != EXPECT_INSERT[0]:
        ok = False
        msgs.append(f"FAIL: insert run count {len(ins)} != {EXPECT_INSERT[0]}")
    lap_n = sc.execute(
        f"SELECT COUNT(*) FROM laps WHERE run_id IN ({','.join('?'*len(ins))})", ins).fetchone()[0]
    ls_n = sc.execute(
        f"SELECT COUNT(*) FROM lap_suspension WHERE run_id IN ({','.join('?'*len(ins))})", ins).fetchone()[0]
    msgs.append(f"laps to insert={lap_n} lap_suspension to insert={ls_n} (expect {EXPECT_INSERT[1]}/{EXPECT_INSERT[2]})")
    if lap_n != EXPECT_INSERT[1] or ls_n != EXPECT_INSERT[2]:
        ok = False
        msgs.append("FAIL: lap counts mismatch")
    ghost_laps = sc.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (GHOST_R2,)).fetchone()[0]
    if ghost_laps != 0:
        ok = False
        msgs.append(f"FAIL: ghost R2 has {ghost_laps} laps (expected 0) — not a pure Original artifact")
    return ins, msgs, ok


def scratch_gates(cc, sc, ins):
    """dry-run/apply 前の scratch 検証ゲート群。"""
    msgs, ok = [], True

    # G1: circuit 正規化
    bad_circ = sc.execute("SELECT COUNT(*) FROM runs WHERE round=? AND circuit!='DONINGTON'", (ROUND,)).fetchone()[0]
    park = sc.execute("SELECT COUNT(*) FROM runs WHERE round=? AND circuit LIKE '%PARK%'", (ROUND,)).fetchone()[0]
    if bad_circ or park:
        ok = False
    msgs.append(f"G1 circuit: non-DONINGTON={bad_circ} PARK={park} -> {'PASS' if not (bad_circ or park) else 'FAIL'}")

    # G2: RACE2 = 0
    r2 = sc.execute("SELECT COUNT(*) FROM runs WHERE round=? AND session='RACE2'", (ROUND,)).fetchone()[0]
    if r2:
        ok = False
    msgs.append(f"G2 scratch RACE2 runs={r2} -> {'PASS' if not r2 else 'FAIL'}")

    # G3: cross-source — provisional lap 突合 137/137（2D 抽出同一性の実証）
    COLS = "lap_time_s,susf_mean,susr_mean,f_dive_spd,r_dive_spd"
    cmpd = mat = 0
    for (lid,) in sc.execute("SELECT lap_id FROM laps WHERE run_id IN "
                             "(SELECT run_id FROM runs WHERE round=?)", (ROUND,)):
        prow = cc.execute(f"SELECT {COLS} FROM laps_provisional WHERE lap_id=?", ("PROV_" + lid,)).fetchone()
        if not prow:
            continue
        srow = sc.execute(f"SELECT {COLS} FROM laps WHERE lap_id=?", (lid,)).fetchone()
        cmpd += 1
        if all((a is None and b is None) or
               (a is not None and b is not None and abs(a - b) <= 1e-6)
               for a, b in zip(srow, prow)):
            mat += 1
    prov_total = cc.execute(
        "SELECT COUNT(*) FROM laps_provisional WHERE provisional_event_key IN (?,?)",
        PROV_EVENT_KEYS).fetchone()[0]
    if not (cmpd == mat == prov_total == 137):
        ok = False
    msgs.append(f"G3 provisional lap match: compared={cmpd} matched={mat} prov_total={prov_total} "
                f"(expect 137/137/137) -> {'PASS' if cmpd == mat == prov_total == 137 else 'FAIL'}")

    # G4: DA77 WUP2（provisional 双子なし）は staging dry-run 実測で照合
    row = sc.execute("SELECT n_laps, best_lap_s FROM runs WHERE run_id=?", (DA77_WUP2_RUN,)).fetchone()
    g4 = bool(row) and row[0] == DA77_WUP2_LAPS and row[1] is not None and abs(row[1] - DA77_WUP2_BEST) <= 0.001
    if not g4:
        ok = False
    msgs.append(f"G4 DA77 WUP2 vs staging dry-run: n_laps={row[0] if row else None} "
                f"best={row[1] if row else None} (expect {DA77_WUP2_LAPS}/{DA77_WUP2_BEST}) -> {'PASS' if g4 else 'FAIL'}")

    # G5: best_lap_s 期待表（16 runs）
    bad = []
    for rid in ins:
        exp = EXPECT_BEST.get(rid)
        row = sc.execute("SELECT best_lap_s FROM runs WHERE run_id=?", (rid,)).fetchone()
        got = row[0] if row else None
        if exp is None or got is None or abs(got - exp) > 0.001:
            bad.append((rid, got, exp))
    if bad:
        ok = False
    msgs.append(f"G5 best_lap_s vs expectation table: mismatch={len(bad)} -> {'PASS' if not bad else 'FAIL ' + str(bad[:3])}")

    # G6: content — JA52 setup 充填 / DA77 は 2D_ONLY で NULL が正（Round7 gate の ROUND8 一般化）
    ja_null = [r[0] for r in sc.execute(
        "SELECT run_id FROM runs WHERE round=? AND rider='JA52' AND f_spr_l IS NULL "
        "AND run_id IN (%s)" % ",".join("?" * len(ins)), (ROUND, *ins))]
    da_setup = [r[0] for r in sc.execute(
        "SELECT run_id FROM runs WHERE round=? AND rider='DA77' AND f_spr_l IS NOT NULL", (ROUND,))]
    g6 = not ja_null and not da_setup
    if not g6:
        ok = False
    msgs.append(f"G6 setup: JA52 NULL-setup={len(ja_null)} DA77 with-setup={len(da_setup)} "
                f"(expect 0/0; DA77=2D_ONLY exempt) -> {'PASS' if g6 else 'FAIL'}")

    # G7: §3c — ghost R2 が C106 を持つこと（swap 材料の存在確認）・R1 は 2D 保持
    r2row = sc.execute("SELECT f_set_c, f_spr_l, f_spr_r, r_spr, n_laps FROM runs WHERE run_id=?", (GHOST_R2,)).fetchone()
    r1row = sc.execute("SELECT f_set_c, n_laps, best_lap_s FROM runs WHERE run_id=?", (RACE1_R1,)).fetchone()
    g7 = (r2row and r2row[0] == "C106" and r2row[4] == 0 and r1row and r1row[1] == 20)
    if not g7:
        ok = False
    msgs.append(f"G7 §3c material: ghost R2 setting={r2row[0] if r2row else None} laps={r2row[4] if r2row else None} "
                f"(expect C106/0) / R1 laps={r1row[1] if r1row else None} (expect 20) -> {'PASS' if g7 else 'FAIL'}")

    # G8: canonical 事前状態 — ROUND8 = 0 / NA_ rows present / totals
    pre_r8 = r8_counts(cc)
    na_present = all(cc.execute("SELECT 1 FROM runs WHERE run_id=?", (p,)).fetchone() for p in NA_ROWS)
    pre = counts(cc)
    g8 = (pre_r8 == (0, 0, 0) and na_present
          and pre["runs"] == 286 and pre["laps"] == 1279 and pre["lap_suspension"] == 1279)
    if not g8:
        ok = False
    msgs.append(f"G8 canonical pre-state: ROUND8={pre_r8} NA_rows={na_present} totals="
                f"{pre['runs']}/{pre['laps']}/{pre['lap_suspension']} -> {'PASS' if g8 else 'FAIL'}")

    return ok, msgs


def build_rows(sc, ins):
    """scratch から insert 行を構築（§3c 補正込み）。返り値 {table: (colnames, [rowtuple])}。"""
    sc.row_factory = sqlite3.Row
    out = {}
    run_cols = [r[1] for r in sc.execute("PRAGMA table_info(runs)")]
    ghost = dict(sc.execute("SELECT * FROM runs WHERE run_id=?", (GHOST_R2,)).fetchone())
    run_rows = []
    for rid in ins:
        row = dict(sc.execute("SELECT * FROM runs WHERE run_id=?", (rid,)).fetchone())
        if rid == RACE1_R1:
            for c in ORIG_SETUP_COLS:          # §3c: C106 payload from ghost R2
                row[c] = ghost[c]
        run_rows.append(tuple(row[c] for c in run_cols))
    out["runs"] = (run_cols, run_rows)

    lap_cols = [r[1] for r in sc.execute("PRAGMA table_info(laps)")]
    lap_rows = [tuple(dict(r)[c] for c in lap_cols) for r in sc.execute(
        f"SELECT * FROM laps WHERE run_id IN ({','.join('?'*len(ins))}) ORDER BY lap_id", ins)]
    out["laps"] = (lap_cols, lap_rows)

    ls_cols = [r[1] for r in sc.execute("PRAGMA table_info(lap_suspension)")]
    ls_rows = []
    for r in sc.execute(
            f"SELECT * FROM lap_suspension WHERE run_id IN ({','.join('?'*len(ins))}) ORDER BY lap_id", ins):
        d = dict(r)
        if d["run_id"] == RACE1_R1:            # §3c: wf_* を C106 レートで再計算
            for wf_col, src_col, front in WF_MAP:
                d[wf_col] = wf_expected(d[src_col], front)
        ls_rows.append(tuple(d[c] for c in ls_cols))
    out["lap_suspension"] = (ls_cols, ls_rows)
    return out


def post_asserts(con, pre_counts, pre_hash):
    """apply トランザクション内の事後 invariant。失敗で RuntimeError → ROLLBACK。"""
    after = counts(con)
    for t in PROTECTED:
        if pre_counts.get(t) != after.get(t):
            raise RuntimeError(f"PROTECTED changed: {t} {pre_counts.get(t)}->{after.get(t)}")
    if after["pdf_lap_times"] != EXPECT_PDF_LAP_TIMES:
        raise RuntimeError(f"pdf_lap_times={after['pdf_lap_times']} != {EXPECT_PDF_LAP_TIMES}")
    if after["pdf_lap_times_v2_staging"] != EXPECT_V2_STAGING:
        raise RuntimeError(f"v2_staging={after['pdf_lap_times_v2_staging']} != {EXPECT_V2_STAGING}")
    if after["metric_version_log"] != EXPECT_METRIC_VERSION_LOG:
        raise RuntimeError(f"metric_version_log={after['metric_version_log']} != {EXPECT_METRIC_VERSION_LOG}")
    view = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='view' AND name='race_lap_detail'").fetchone()[0]
    if view != 1:
        raise RuntimeError("race_lap_detail VIEW missing")
    for t in TARGET_TABLES:
        if after[t] != EXPECT_FINAL[t]:
            raise RuntimeError(f"{t} total={after[t]} expected {EXPECT_FINAL[t]}")
    r8 = r8_counts(con)
    if r8 != EXPECT_INSERT:
        raise RuntimeError(f"ROUND8 shape={r8} expected {EXPECT_INSERT}")
    # RACE2 / SX / circuit
    for q, exp, nm in (
            ("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND session='RACE2'", 0, "RACE2 runs"),
            ("SELECT COUNT(*) FROM lap_suspension WHERE round='ROUND8' AND session='RACE2'", 0, "RACE2 ls"),
            ("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND session='SX'", 0, "SX runs"),
            ("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND run_id LIKE '%\\_SX\\_%' ESCAPE '\\'", 0, "SX run_id"),
            ("SELECT COUNT(*) FROM lap_suspension WHERE round='ROUND8' AND session='SX'", 0, "SX ls"),
            ("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND circuit!='DONINGTON'", 0, "non-DONINGTON"),
            ("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND circuit LIKE '%PARK%'", 0, "DONINGTONPARK"),
            ("SELECT COUNT(*) FROM laps l JOIN runs r ON l.run_id=r.run_id WHERE r.round='ROUND8' AND r.session='RACE2'", 0, "RACE2 laps")):
        got = con.execute(q).fetchone()[0]
        if got != exp:
            raise RuntimeError(f"invariant {nm}: {got} != {exp}")
    # orphans / duplicates / lap<->suspension per run
    orph = con.execute("SELECT COUNT(*) FROM laps WHERE run_id NOT IN (SELECT run_id FROM runs)").fetchone()[0]
    orph2 = con.execute("SELECT COUNT(*) FROM lap_suspension WHERE run_id NOT IN (SELECT run_id FROM runs)").fetchone()[0]
    dup = con.execute("SELECT COUNT(*) - COUNT(DISTINCT run_id) FROM runs").fetchone()[0]
    dupl = con.execute("SELECT COUNT(*) - COUNT(DISTINCT lap_id) FROM laps").fetchone()[0]
    if orph or orph2 or dup or dupl:
        raise RuntimeError(f"orphans/dups: laps_orphan={orph} ls_orphan={orph2} run_dup={dup} lap_dup={dupl}")
    mism = con.execute("""
        SELECT COUNT(*) FROM (
          SELECT r.run_id,
                 (SELECT COUNT(*) FROM laps l WHERE l.run_id=r.run_id) a,
                 (SELECT COUNT(*) FROM lap_suspension s WHERE s.run_id=r.run_id) b
          FROM runs r WHERE r.round='ROUND8') WHERE a!=b""").fetchone()[0]
    if mism:
        raise RuntimeError(f"laps != lap_suspension for {mism} ROUND8 runs")
    # §3c: RACE1 JA52 = exactly 1 run, C106, no R2; NA rows untouched
    r1n = con.execute("SELECT COUNT(*) FROM runs WHERE round='ROUND8' AND rider='JA52' AND session='RACE1'").fetchone()[0]
    if r1n != 1:
        raise RuntimeError(f"ROUND8 JA52 RACE1 runs={r1n} != 1")
    setg = con.execute("SELECT f_set_c, f_spr_l, f_spr_r, r_spr FROM runs WHERE run_id=?", (RACE1_R1,)).fetchone()
    if setg != ("C106", "9", "9", "84"):
        raise RuntimeError(f"RACE1 R1 setup={setg} != ('C106','9','9','84')")
    if con.execute("SELECT COUNT(*) FROM runs WHERE run_id=?", (GHOST_R2,)).fetchone()[0]:
        raise RuntimeError("ghost RACE1 R2 was inserted")
    for p in NA_ROWS:
        row = con.execute("SELECT f_set_c FROM runs WHERE run_id=?", (p,)).fetchone()
        if not row or row[0] != "C104":
            raise RuntimeError(f"NA row {p} touched/missing: {row}")
    # §3c: wf_* on R1 laps must equal C106 recompute
    badwf = 0
    for r in con.execute(
            "SELECT apex_susF_avg,apex_susR_avg,brk_susF_avg,brk_susR_avg,ce_susF_avg,ce_susR_avg,"
            "wf_f_apex_n,wf_r_apex_n,wf_f_brk_n,wf_r_brk_n,wf_f_ce_n,wf_r_ce_n "
            "FROM lap_suspension WHERE run_id=?", (RACE1_R1,)):
        exp = (wf_expected(r[0], True), wf_expected(r[1], False), wf_expected(r[2], True),
               wf_expected(r[3], False), wf_expected(r[4], True), wf_expected(r[5], False))
        if tuple(r[6:12]) != exp:
            badwf += 1
    if badwf:
        raise RuntimeError(f"wf_* C106 recompute mismatch on {badwf} RACE1 R1 laps")
    # non-ROUND8 byte identity
    if non_r8_hash(con) != pre_hash:
        raise RuntimeError("non-ROUND8 rows changed (hash mismatch)")
    return after, r8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not os.path.exists(args.scratch):
        print("ERROR: scratch not found:", args.scratch)
        sys.exit(1)

    cc = sqlite3.connect(f"file:{CANON}?mode=ro", uri=True)
    sc = sqlite3.connect(f"file:{args.scratch}?mode=ro", uri=True)

    pre = counts(cc)
    print("== canonical BEFORE ==")
    for t in TARGET_TABLES + PROTECTED:
        print(f"  {t:32s} {pre[t]}")
    print("  ROUND8 (runs/laps/susp) =", r8_counts(cc), "(expect (0, 0, 0))")

    ins, pmsgs, pok = plan_insert(sc)
    print("\n== insert plan ==")
    for m in pmsgs:
        print("  " + m)

    gok, gmsgs = scratch_gates(cc, sc, ins)
    print("\n== gates ==")
    for m in gmsgs:
        print("  " + m)
    ok = pok and gok
    print("  GATES OVERALL:", "ALL PASS" if ok else "FAIL")

    # schema identity（列集合。物理順は §44 ALTER 追加で canonical 側が異なるが、
    # INSERT は明示列名リストなので順序非依存 — 集合一致を要求）
    for t in TARGET_TABLES:
        a, b = cols(cc, t), cols(sc, t)
        if set(a) != set(b):
            ok = False
            print(f"  SCHEMA MISMATCH on {t}: only-canon={set(a)-set(b)} only-scratch={set(b)-set(a)}")
        elif a != b:
            print(f"  schema {t}: same column set, different physical order (OK — named INSERT)")

    print("\n== planned writes ==")
    print(f"  INSERT {EXPECT_INSERT[0]} runs / {EXPECT_INSERT[1]} laps / {EXPECT_INSERT[2]} lap_suspension")
    for rid in ins:
        tag = "  [§3c: C106 payload + wf recompute]" if rid == RACE1_R1 else ""
        print(f"    + {rid}{tag}")
    print(f"  NOT inserted: {GHOST_R2} (0-lap ghost), 2× SX runs (21 laps)")
    print(f"  DELETE: none (NA_DONINGTON_* untouched)")
    print("  UNTOUCHED protected:", ", ".join(PROTECTED))

    if not args.apply:
        print("\nDRY-RUN only. No canonical write.")
        cc.close(); sc.close()
        sys.exit(0 if ok else 2)

    if not ok:
        print("\nREFUSING to apply: gates FAILED.")
        cc.close(); sc.close()
        sys.exit(3)

    rows = build_rows(sc, ins)
    cc.close(); sc.close()

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.normpath(os.path.join(ROOT, "..", "02_DATABASE", f"_backup_round8_targeted_{ts}"))
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

    pre_counts = counts(con)
    pre_hash = non_r8_hash(con)
    try:
        con.execute("BEGIN")
        for t in TARGET_TABLES:
            colnames, rws = rows[t]
            ph = ",".join("?" * len(colnames))
            con.executemany(f"INSERT INTO {t} ({','.join(colnames)}) VALUES ({ph})", rws)
        after, r8 = post_asserts(con, pre_counts, pre_hash)
        con.execute("COMMIT")
        print(f"APPLIED. ROUND8 shape={r8} totals runs={after['runs']} laps={after['laps']} "
              f"susp={after['lap_suspension']}")
    except Exception as e:
        con.execute("ROLLBACK")
        print("ROLLED BACK due to:", repr(e))
        print("Restore from backup if needed:", bdir)
        con.close()
        sys.exit(3)
    con.close()


if __name__ == "__main__":
    main()
