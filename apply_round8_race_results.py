#!/usr/bin/env python3
"""
apply_round8_race_results.py — ROUND8(DONINGTON) Result PDF → race_results 反映（既定 dry-run）
=============================================================================================
CLAUDE.md §36 の apply_round7_race_results.py を ROUND8 用に一般化（2026-07-13 Track A Phase 2・
inbox 承認済みタスク）。readiness = reports/round8_final_integration_readiness_20260713.md。

ROUND8 固有の一般化点:
  - ROUND8_DIR = 07_RESULTS/ROUND8_DONINGTON_20260710（6 PDF: FP/QP/WUP1/WUP2/RACE1/RACE2）。
  - 物理レンジ = DONINGTON（~85–115s）。Round7 の MISANO 97–105s 系レンジでは ~89s ラップを
    全滅させるため必ず差し替える（readiness §8）。
  - round リテラル = ROUND8。
  - DA77 は SP を走行（QP PDF がカバー・readiness §2/§5）→ QP PDF の #77 行が session_type='QP'
    候補になる（race_results の session 語彙に SP は無い・既存慣行どおり）。

慣行（§36a と同一）:
  - RACE1/RACE2 = フルフィールド、FP/QP/WUP1/WUP2 = TS24 チーム(#77/#52)のみ。
  - 自然キー（ローカル UPSERT）= (round, session_type, rider_num)。
  - UPSERT は COALESCE（None で既存値を潰さない）。既存 ROUND8 行 = 0（衝突 0 検証済み）。

安全策:
  - 既定 dry-run（正本DB mode=ro のみ）。
  - --apply: PASSIVE wal_checkpoint → WAL-safe フルバックアップ(db+wal+shm) → busy_timeout →
    単一トランザクション → 非対象業務テーブル before==after assert（違反で rollback）。

使い方:
  python3 apply_round8_race_results.py            # dry-run（既定）
  python3 apply_round8_race_results.py --apply    # 反映（承認済み・Phase 2）
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pdf_result_extractor_v2 as v2

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
CANON_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
ROUND8_DIR = DATA_ROOT / "07_RESULTS" / "ROUND8_DONINGTON_20260710"
REPORTS_DIR = SCRIPT_DIR / "reports"
BACKUP_ROOT = DATA_ROOT / "02_DATABASE"

ROUND = "ROUND8"
EXPECTED_CANDS = 74           # RACE1 33 + RACE2 33 + FP 2 + QP 2 + WUP1 2 + WUP2 2 (readiness §7)
EXPECTED_RR_AFTER = 940       # 866 + 74

# apply で不変であるべき非対象テーブル（業務 + protected/管理）
BUSINESS_NONTARGET = [
    "runs", "laps", "lap_suspension", "pdf_lap_times", "pdf_lap_times_v2_staging",
    "runs_provisional", "laps_provisional", "lap_suspension_provisional",
    "source_file_registry", "import_queue", "data_quality_log", "analysis_run_log",
    "metric_version_log",
]
TEAM = {77, 52}
RACE_SESSIONS = {"RACE1", "RACE2"}
# 物理レンジ（DONINGTON: best ~89s。緩めの妥当域 85–115s。MISANO 用レンジは使用禁止）
BEST_LO, BEST_HI = 85.0, 115.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s [R8RR] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)


def ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ── 候補抽出 ────────────────────────────────────────────────────────────────

def build_candidates(full_nonrace: bool) -> tuple[list[dict], list[dict]]:
    """ROUND8 6 PDF から race_results 候補を生成。返り値 (candidates, lapdetail_summary)。"""
    cands: list[dict] = []
    lapsum: list[dict] = []
    pdfs = sorted(ROUND8_DIR.glob("*.pdf"))
    if len(pdfs) != 6:
        log.warning("PDF 数が 6 ではない: %d", len(pdfs))
    for pdf in pdfs:
        res = v2.extract_pdf(pdf, all_riders=True)
        m = res["meta"]
        sess = m.get("session_type")
        if m.get("round") != ROUND:
            log.error("PDF %s の round=%s ≠ %s — 候補から除外", pdf.name, m.get("round"), ROUND)
            continue
        is_race = sess in RACE_SESSIONS
        for num, r in res["riders"].items():
            keep = is_race or full_nonrace or (num in TEAM)
            if not keep:
                continue
            laps = r.get("laps", [])
            valid = [lp["lap_time_s"] for lp in laps if not lp["is_cancelled"] and lp["lap_time_s"]]
            cands.append({
                "round": m.get("round"), "circuit": m.get("circuit"), "session_type": sess,
                "date": m.get("date"), "position": r.get("position"), "rider_num": num,
                "rider_name": r.get("rider_name"), "laps": (len(laps) or None),
                "best_lap": r.get("best_lap"), "best_lap_s": r.get("best_lap_s"),
                "source_file": pdf.name, "status_flag": r.get("status"),
            })
            if is_race:
                lapsum.append({"session_type": sess, "rider_num": num,
                               "n_laps": len(laps), "v2_best": (min(valid) if valid else None),
                               "rr_best": r.get("best_lap_s")})
    return cands, lapsum


# ── 品質ゲート ──────────────────────────────────────────────────────────────

def gate_candidates(cands: list[dict], lapsum: list[dict]) -> dict:
    g = {}
    seen = {}
    dups = []
    for c in cands:
        k = (c["round"], c["session_type"], c["rider_num"])
        if k in seen:
            dups.append(k)
        seen[k] = 1
    g["dups"] = dups
    con = ro(CANON_DB)
    coll = []
    for c in cands:
        row = con.execute(
            "SELECT 1 FROM race_results WHERE round=? AND session_type=? AND rider_num=? "
            "AND COALESCE(data_scope,'')<>'COMPANY'",
            (c["round"], c["session_type"], c["rider_num"])).fetchone()
        if row:
            coll.append((c["round"], c["session_type"], c["rider_num"]))
    con.close()
    g["collisions"] = coll
    null_key = [c for c in cands if not (c["round"] and c["circuit"] and c["session_type"] and c["rider_num"])]
    null_date = [c for c in cands if not c["date"]]
    null_best = [c for c in cands if c["best_lap_s"] is None]
    bad_best = [c for c in cands if c["best_lap_s"] is not None and not (BEST_LO <= c["best_lap_s"] <= BEST_HI)]
    bad_type = [c for c in cands if (c["rider_num"] is not None and not isinstance(c["rider_num"], int))
                or (c["best_lap_s"] is not None and not isinstance(c["best_lap_s"], float))]
    g["null_key"] = null_key
    g["null_date"] = null_date
    g["null_best"] = null_best
    g["bad_best"] = bad_best
    g["bad_type"] = bad_type
    mism = [s for s in lapsum if (s["v2_best"] is not None and s["rr_best"] is not None
            and abs(s["v2_best"] - s["rr_best"]) > 0.001)]
    g["lap_best_mismatch"] = mism
    # 追加ゲート: circuit は DONINGTON のみ（DONINGTONPARK 禁止）
    g["bad_circuit"] = [c for c in cands if c["circuit"] != "DONINGTON"]
    return g


def gate_ok(g: dict) -> bool:
    hard = ("dups", "collisions", "null_key", "bad_best", "bad_type",
            "lap_best_mismatch", "bad_circuit", "null_best", "null_date")
    return all(not g[k] for k in hard)


# ── apply ───────────────────────────────────────────────────────────────────

def do_apply(cands: list[dict]) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    con0 = ro(CANON_DB)
    before = {t: con0.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_NONTARGET}
    rr_before = con0.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
    con0.close()

    bdir = BACKUP_ROOT / f"_backup_round8_rr_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    # WAL-safe backup（§65c: PASSIVE checkpoint・db+wal+shm）
    conw = sqlite3.connect(str(CANON_DB), timeout=30)
    conw.execute("PRAGMA busy_timeout=30000")
    try:
        conw.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except sqlite3.Error:
        pass
    conw.close()
    shutil.copy2(CANON_DB, bdir / CANON_DB.name)
    for sfx in ("-wal", "-shm"):
        p = Path(str(CANON_DB) + sfx)
        if p.exists():
            shutil.copy2(p, bdir / p.name)
    log.info("バックアップ: %s", bdir)

    con = sqlite3.connect(str(CANON_DB), timeout=30)
    con.execute("PRAGMA busy_timeout=30000")
    inserted = 0
    try:
        con.execute("BEGIN")
        for c in cands:
            ex = con.execute("SELECT 1 FROM race_results WHERE round=? AND session_type=? AND rider_num=?",
                             (c["round"], c["session_type"], c["rider_num"])).fetchone()
            if ex:
                con.execute(
                    "UPDATE race_results SET position=COALESCE(?,position), "
                    "best_lap=COALESCE(?,best_lap), best_lap_s=COALESCE(?,best_lap_s), "
                    "laps=COALESCE(?,laps), rider_name=COALESCE(?,rider_name), "
                    "circuit=COALESCE(?,circuit), date=COALESCE(?,date), source_file=COALESCE(?,source_file) "
                    "WHERE round=? AND session_type=? AND rider_num=?",
                    (c["position"], c["best_lap"], c["best_lap_s"], c["laps"], c["rider_name"],
                     c["circuit"], c["date"], c["source_file"],
                     c["round"], c["session_type"], c["rider_num"]))
            else:
                con.execute(
                    "INSERT INTO race_results (round,circuit,session_type,date,position,rider_num,"
                    "rider_name,laps,best_lap,best_lap_s,source_file,data_scope) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'TS24_PRIVATE')",
                    (c["round"], c["circuit"], c["session_type"], c["date"], c["position"],
                     c["rider_num"], c["rider_name"], c["laps"], c["best_lap"], c["best_lap_s"], c["source_file"]))
                inserted += 1
        after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_NONTARGET}
        if after != before:
            raise RuntimeError(f"非対象テーブルが変化: before={before} after={after}")
        rr_after = con.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
        if rr_after != EXPECTED_RR_AFTER:
            raise RuntimeError(f"race_results after={rr_after} expected {EXPECTED_RR_AFTER}")
        r8 = con.execute("SELECT COUNT(*) FROM race_results WHERE round='ROUND8'").fetchone()[0]
        if r8 != EXPECTED_CANDS:
            raise RuntimeError(f"ROUND8 rows={r8} expected {EXPECTED_CANDS}")
        con.execute("COMMIT")
    except Exception as e:
        con.rollback()
        con.close()
        log.error("apply 失敗 rollback: %r / backup=%s", e, bdir)
        return 3
    con.close()
    log.info("apply 完了: insert=%d update=%d / race_results %d→%d / 非対象不変 ✅ / backup=%s",
             inserted, len(cands) - inserted, rr_before, rr_after, bdir)
    return 0


def main():
    ap = argparse.ArgumentParser(description="ROUND8 race_results 反映（既定 dry-run）")
    ap.add_argument("--apply", action="store_true", help="正本 race_results へ実反映")
    ap.add_argument("--full-nonrace", action="store_true", help="FP/QP/WUP も全ライダー候補に（既定はチームのみ）")
    args = ap.parse_args()

    if not CANON_DB.exists() or not ROUND8_DIR.exists():
        log.error("正本DB または ROUND8 フォルダが見つかりません")
        sys.exit(1)

    cands, lapsum = build_candidates(args.full_nonrace)
    from collections import Counter
    by_sess = Counter(c["session_type"] for c in cands)
    log.info("候補: %d 行（PDF=%d）内訳=%s", len(cands), len(list(ROUND8_DIR.glob('*.pdf'))), dict(by_sess))
    if not args.full_nonrace and len(cands) != EXPECTED_CANDS:
        log.error("候補数 %d ≠ 期待 %d — STOP", len(cands), EXPECTED_CANDS)
        sys.exit(2)

    g = gate_candidates(cands, lapsum)
    log.info("Gate: dup=%d collision=%d null_key=%d null_date=%d null_best=%d bad_best=%d "
             "bad_type=%d lap_best_mismatch=%d bad_circuit=%d",
             len(g["dups"]), len(g["collisions"]), len(g["null_key"]), len(g["null_date"]),
             len(g["null_best"]), len(g["bad_best"]), len(g["bad_type"]),
             len(g["lap_best_mismatch"]), len(g["bad_circuit"]))
    if not gate_ok(g):
        for k, v in g.items():
            if v:
                log.error("GATE FAIL %s: %s", k, v[:5])
        log.error("Quality Gate FAIL — STOP（書込なし）")
        sys.exit(2)
    log.info("Quality Gate: ALL PASS")

    # team rider summary
    for c in cands:
        if c["rider_num"] in TEAM:
            log.info("  %s #%s pos=%s laps=%s best=%s", c["session_type"], c["rider_num"],
                     c["position"], c["laps"], c["best_lap_s"])

    if args.apply:
        log.warning("--apply: race_results（業務テーブル）へ書き込みます")
        sys.exit(do_apply(cands))
    log.info("DRY-RUN のみ（書込なし）。--apply で反映。")


if __name__ == "__main__":
    main()
