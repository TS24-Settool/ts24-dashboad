#!/usr/bin/env python3
"""
pdf_v2_scratch_gate.py — Result PDF v2 ラップ明細の scratch 生成 + Quality Gate（read-only）
=============================================================================================
設計: CLAUDE.md §31 / `reports/pdf_v2_integration_design_20260625.md` /
      Obsidian `05_DB_AUDIT/2026-06-25_pdf_v2_integration_design.md`。

何をするか:
  1. **正本DB（`02_DATABASE/ts24_unified.db`）は read-only**（`mode=ro` URI）で開き、
     `race_results` を真値基準として読むだけ（業務テーブルへは一切書かない）。
  2. `/tmp/ts24_pdf_v2_scratch.db`（隔離スクラッチ）に `pdf_lap_times_v2_staging` を作成。
  3. `pdf_result_extractor_v2.extract_pdf()`（`--all-riders` 相当）で Result PDF を抽出し、
     pdf_lap_times 互換のラップ明細（seg1..seg4/speed/local_time/is_outlap/is_pit/is_cancelled）＋
     来歴（source_file/extractor_version/generated_at）を staging へ投入。
  4. **Quality Gate G1〜G6** を (session, rider) 単位で実行し、各行に gate_status を付与:
       G1 coverage          : race_results のライダーが v2 にも居るか
       G2 lap_count 差 ≤ 1  : v2 ラップ数 vs race_results.laps
       G3 best lap 差 ≤ 0.05: v2 best(valid) vs race_results.best_lap_s（≤0.5=WARNING/>0.5=FAIL）
       G4 lap_no 重複なし
       G5 physical range    : valid lap が best×[0.90,1.60] 内（外=WARNING）
       G6 来歴必須          : source_file/extractor_version/generated_at が非NULL
  5. Gate レポート（Markdown）を `reports/pdf_v2_gate_<YYYYMMDD>.md` に出力。
  6. 正本DBの業務テーブル件数が **before==after** で不変であることを検証。

**禁止（本スクリプトは絶対に行わない）**: 正本DBへの書込、正本DB内 staging 作成、
  v2 `--write` を正本DBへ、Workbench 参照先変更、Supabase、Phase 2B、origin push。

使い方:
  python3 pdf_v2_scratch_gate.py                 # 既定: ROUND3 ASSEN を対象
  python3 pdf_v2_scratch_gate.py --all           # 07_RESULTS 全 RACE/SP/QP（Company=BSB は除外）
  python3 pdf_v2_scratch_gate.py --file F.pdf
  python3 pdf_v2_scratch_gate.py --round ROUND3 --session RACE1
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF

import pdf_result_extractor_v2 as v2

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
RESULTS_ROOT = DATA_ROOT / "07_RESULTS"
CANON_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
SCRATCH_DB = Path("/tmp/ts24_pdf_v2_scratch.db")
REPORTS_DIR = SCRIPT_DIR / "reports"

BUSINESS_TABLES = ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]

# Gate 閾値（設計 §5 / Tatsuki 採用）
G2_LAP_TOL = 1          # lap 数差 ≤ 1 = PASS
G3_BEST_PASS = 0.05     # best 差 ≤ 0.05s = PASS
G3_BEST_WARN = 0.50     # ≤ 0.50s = WARNING / それ以上 = FAIL
G5_LO, G5_HI = 0.90, 1.60  # physical range = best×[0.90, 1.60]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [GATE] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)


def ro_conn(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def business_counts() -> dict:
    conn = ro_conn(CANON_DB)
    out = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_TABLES}
    conn.close()
    return out


# ── staging スキーマ（/tmp のみ） ───────────────────────────────────────────

STAGING_DDL = """
CREATE TABLE IF NOT EXISTS pdf_lap_times_v2_staging (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    round         TEXT, circuit TEXT, session_type TEXT, date TEXT,
    position      INTEGER, rider_num INTEGER, rider_name TEXT, lap_no INTEGER,
    seg1 REAL, seg2 REAL, seg3 REAL, seg4 REAL,
    lap_time TEXT, lap_time_s REAL, speed REAL, local_time TEXT,
    is_outlap INTEGER DEFAULT 0, is_pit INTEGER DEFAULT 0, is_cancelled INTEGER DEFAULT 0,
    source_file TEXT, extractor_version TEXT, generated_at TEXT,
    gate_status TEXT, data_scope TEXT DEFAULT 'TS24_PRIVATE'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pdf_v2_staging
  ON pdf_lap_times_v2_staging(round, session_type, rider_num, lap_no, date);
"""


def fresh_scratch() -> sqlite3.Connection:
    if SCRATCH_DB.exists():
        SCRATCH_DB.unlink()
    conn = sqlite3.connect(str(SCRATCH_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript(STAGING_DDL)
    conn.commit()
    return conn


# ── PDF 収集 ────────────────────────────────────────────────────────────────

def collect_pdfs(args) -> list[Path]:
    if args.file:
        return [args.file]
    if args.all:
        pdfs = [p for p in sorted(RESULTS_ROOT.rglob("*.pdf"))
                if "Company" not in p.parts]
        return pdfs
    # 既定: ROUND3 ASSEN フォルダ
    folder = RESULTS_ROOT / "ROUND3_ASSEN_20260417"
    return sorted(folder.glob("*.pdf")) if folder.exists() else []


# ── 抽出 → staging 投入 ─────────────────────────────────────────────────────

def results_roster(pdf: Path) -> set:
    """公式 Results 分類に載る全ライダー番号（chrono 有無に関わらず）。
    chrono 区間が無いライダー（例 ROUND3/RACE1 の #73）を「results-only」と
    判定するための母集合。read-only（PDF を読むだけ）。"""
    try:
        doc = fitz.open(str(pdf))
        lines = v2.concat_pages(doc)
        doc.close()
        return set(v2.parse_results_block(lines, all_riders=True).keys())
    except Exception:
        return set()


def populate_staging(conn: sqlite3.Connection, pdfs: list[Path]) -> list[dict]:
    """各 PDF を抽出し staging へ。session メタ一覧を返す。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sessions = []
    for pdf in pdfs:
        try:
            res = v2.extract_pdf(pdf, all_riders=True)
        except Exception as e:
            log.error("抽出失敗 %s: %s", pdf.name, e)
            continue
        m = res["meta"]
        roster = results_roster(pdf)
        rnd, sess, date = m.get("round"), m.get("session_type"), m.get("date")
        n_lap = 0
        chrono_riders = set()
        for num, r in res["riders"].items():
            if r.get("laps"):
                chrono_riders.add(num)
            for lp in r["laps"]:
                conn.execute(
                    """INSERT OR IGNORE INTO pdf_lap_times_v2_staging
                       (round,circuit,session_type,date,position,rider_num,rider_name,lap_no,
                        seg1,seg2,seg3,seg4,lap_time,lap_time_s,speed,local_time,
                        is_outlap,is_pit,is_cancelled,source_file,extractor_version,generated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (rnd, m.get("circuit"), sess, date, r.get("position"), num, r.get("rider_name"),
                     lp["lap_no"], lp.get("seg1"), lp.get("seg2"), lp.get("seg3"), lp.get("seg4"),
                     lp["lap_time"], lp["lap_time_s"], lp.get("speed"), lp.get("local_time"),
                     lp.get("is_outlap", 0), lp.get("is_pit", 0), lp["is_cancelled"],
                     str(pdf), v2.EXTRACTOR_VERSION, now),
                )
                n_lap += 1
        sessions.append({"pdf": pdf, "round": rnd, "session": sess, "date": date,
                         "source": res["source"], "n_lap": n_lap,
                         "chrono_riders": chrono_riders,
                         "results_riders": roster or set(res["riders"].keys())})
    conn.commit()
    return sessions


# ── Gate ────────────────────────────────────────────────────────────────────

def worst(a: str, b: str) -> str:
    order = {"PASS": 0, "WARNING": 1, "FAIL": 2}
    return a if order[a] >= order[b] else b


def gate_session(scr: sqlite3.Connection, canon: sqlite3.Connection, meta: dict) -> dict:
    """1 セッションを Gate。rider 単位の判定リストと集計を返す。"""
    rnd, sess = meta["round"], meta["session"]
    # 真値は WorldSSP(=TS24_PRIVATE / NULL)のみ。COMPANY(=BSB)は同じ round ラベルを
    # 共有するが別シリーズ・別サーキット（例 ROUND2/RACE1: DONINGTON(BSB) vs PORTIMAO(SSP)）
    # のため除外しないと偽 FAIL になる（Result PDF は WorldSSP 公式）。
    truth = {row["rider_num"]: row for row in canon.execute(
        "SELECT rider_num, laps, best_lap_s FROM race_results "
        "WHERE round=? AND session_type=? AND COALESCE(data_scope,'') <> 'COMPANY'",
        (rnd, sess))}
    has_truth = len(truth) > 0

    # staging から rider 単位に集計
    v2rows = {}
    for row in scr.execute(
        """SELECT rider_num, lap_no, lap_time_s, is_cancelled, source_file,
                  extractor_version, generated_at
           FROM pdf_lap_times_v2_staging WHERE round=? AND session_type=?""", (rnd, sess)):
        v2rows.setdefault(row["rider_num"], []).append(row)

    results = []
    riders = set(truth) | set(v2rows) | meta["results_riders"]
    for rn in sorted(riders):
        laps = v2rows.get(rn, [])
        checks = {}
        status = "PASS"
        notes = []

        # G1 coverage
        if rn in truth and not laps:
            if rn in meta["results_riders"] and rn not in meta["chrono_riders"]:
                checks["G1"] = "FAIL"
                notes.append("results-only（chronological 区間なし＝原文PDFに per-lap データ無し）")
            else:
                checks["G1"] = "FAIL"
                notes.append("v2 完全欠落")
            status = worst(status, "FAIL")
            results.append({"rider": rn, "status": status, "checks": checks,
                            "notes": notes, "v2_laps": 0,
                            "rr_laps": truth[rn]["laps"], "rr_best": truth[rn]["best_lap_s"]})
            continue
        if not laps:
            # race_results にも居ない（PDF抽出のみ）→ 真値なし
            continue
        checks["G1"] = "PASS"

        n_total = len(laps)
        valid = [r["lap_time_s"] for r in laps if not r["is_cancelled"] and r["lap_time_s"]]
        v2_best = min(valid) if valid else None

        # G4 lap_no 重複
        lapnos = [r["lap_no"] for r in laps]
        checks["G4"] = "PASS" if len(lapnos) == len(set(lapnos)) else "FAIL"
        status = worst(status, checks["G4"])
        if checks["G4"] == "FAIL":
            notes.append("lap_no 重複")

        # G6 来歴必須
        ok6 = all(laps[0][c] for c in ("source_file", "extractor_version", "generated_at"))
        checks["G6"] = "PASS" if ok6 else "FAIL"
        status = worst(status, checks["G6"])

        if has_truth and rn in truth:
            rr_laps = truth[rn]["laps"]
            rr_best = truth[rn]["best_lap_s"]
            # G2 lap_count
            if rr_laps is not None:
                d = abs(n_total - rr_laps)
                checks["G2"] = "PASS" if d <= G2_LAP_TOL else "FAIL"
                if d > G2_LAP_TOL:
                    notes.append(f"lap数差={d}(v2 {n_total}/rr {rr_laps})")
                status = worst(status, checks["G2"])
            # G3 best
            if rr_best is not None and v2_best is not None:
                d = abs(v2_best - rr_best)
                checks["G3"] = "PASS" if d <= G3_BEST_PASS else ("WARNING" if d <= G3_BEST_WARN else "FAIL")
                if d > G3_BEST_PASS:
                    notes.append(f"best差={round(d,3)}s")
                status = worst(status, checks["G3"])
            # G5 physical range
            if v2_best:
                oor = [t for t in valid if not (v2_best * G5_LO <= t <= v2_best * G5_HI)]
                checks["G5"] = "PASS" if not oor else "WARNING"
                if oor:
                    notes.append(f"range外 {len(oor)}本")
                status = worst(status, checks["G5"])
            results.append({"rider": rn, "status": status, "checks": checks, "notes": notes,
                            "v2_laps": n_total, "v2_best": v2_best,
                            "rr_laps": rr_laps, "rr_best": rr_best})
        else:
            # v2 にあるが race_results に無い（extra）
            checks["G2"] = checks["G3"] = "NO_TRUTH"
            results.append({"rider": rn, "status": "WARNING", "checks": checks,
                            "notes": ["race_results に該当なし（extra）"],
                            "v2_laps": n_total, "v2_best": v2_best, "rr_laps": None, "rr_best": None})

    # staging の gate_status をライダー単位で反映（commit は呼び出し側 main で実施）
    for r in results:
        scr.execute(
            "UPDATE pdf_lap_times_v2_staging SET gate_status=? WHERE round=? AND session_type=? AND rider_num=?",
            (r["status"], rnd, sess, r["rider"]))

    summ = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for r in results:
        summ[r["status"]] += 1
    return {"meta": meta, "has_truth": has_truth, "results": results, "summary": summ}


# ── レポート ────────────────────────────────────────────────────────────────

def write_report(gated: list[dict], counts_before: dict, counts_after: dict) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    path = REPORTS_DIR / f"pdf_v2_gate_{day}.md"
    L = []
    L.append(f"# Result PDF v2 scratch + Gate レポート — {datetime.now():%Y-%m-%d %H:%M}")
    L.append("")
    L.append("read-only 監査。正本DBへは書込なし。scratch=`/tmp/ts24_pdf_v2_scratch.db`。")
    L.append(f"抽出器: `{v2.EXTRACTOR_VERSION}`（Gate 閾値: G2 lap差≤{G2_LAP_TOL} / "
             f"G3 best≤{G3_BEST_PASS}s(≤{G3_BEST_WARN}=WARN) / G5 range×[{G5_LO},{G5_HI}]）")
    L.append("")
    # 正本DB不変
    L.append("## 正本DB業務テーブル（不変確認）")
    L.append("")
    L.append("| table | before | after | 不変 |")
    L.append("|---|---:|---:|:--:|")
    for t in BUSINESS_TABLES:
        ok = "✅" if counts_before[t] == counts_after[t] else "❌"
        L.append(f"| {t} | {counts_before[t]} | {counts_after[t]} | {ok} |")
    L.append("")
    # 全体集計
    tot = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for g in gated:
        for k in tot:
            tot[k] += g["summary"][k]
    L.append("## 全体 Gate 集計（rider 単位）")
    L.append("")
    L.append(f"- PASS **{tot['PASS']}** / WARNING **{tot['WARNING']}** / FAIL **{tot['FAIL']}**")
    L.append("- **FAIL は正本へ採用しない**（要 Tatsuki 承認の上で別タスク）。")
    L.append("")
    # セッション別
    L.append("## セッション別")
    L.append("")
    L.append("| round | session | truth | PASS | WARN | FAIL | v2 lap rows |")
    L.append("|---|---|:--:|---:|---:|---:|---:|")
    for g in gated:
        m = g["meta"]
        L.append(f"| {m['round']} | {m['session']} | {'✓' if g['has_truth'] else '–'} | "
                 f"{g['summary']['PASS']} | {g['summary']['WARNING']} | {g['summary']['FAIL']} | {m['n_lap']} |")
    L.append("")
    # FAIL/WARNING 明細
    L.append("## FAIL / WARNING 明細")
    L.append("")
    any_issue = False
    for g in gated:
        issues = [r for r in g["results"] if r["status"] != "PASS"]
        if not issues:
            continue
        any_issue = True
        m = g["meta"]
        L.append(f"### {m['round']} / {m['session']}")
        L.append("")
        L.append("| rider | status | v2 laps | rr laps | v2 best | rr best | notes |")
        L.append("|---:|:--:|---:|---:|---:|---:|---|")
        for r in issues:
            L.append(f"| #{r['rider']} | {r['status']} | {r['v2_laps']} | "
                     f"{r.get('rr_laps','')} | {r.get('v2_best','') or ''} | {r.get('rr_best','') or ''} | "
                     f"{'; '.join(r['notes'])} |")
        L.append("")
    if not any_issue:
        L.append("（FAIL/WARNING なし）")
        L.append("")
    # ROUND3/RACE1 focus
    L.append("## 重点確認: ROUND3 / RACE1（#52 / #77 / #73）")
    L.append("")
    for g in gated:
        if g["meta"]["round"] == "ROUND3" and g["meta"]["session"] == "RACE1":
            for r in g["results"]:
                if r["rider"] in (52, 77, 73):
                    L.append(f"- #{r['rider']}: **{r['status']}** "
                             f"v2_laps={r['v2_laps']} rr_laps={r.get('rr_laps')} "
                             f"v2_best={r.get('v2_best')} rr_best={r.get('rr_best')} "
                             f"{'/ '+'; '.join(r['notes']) if r['notes'] else ''}")
            break
    L.append("")
    L.append("## 注記（解釈の前提）")
    L.append("")
    L.append("- **真値フィルタ**: `race_results` は同一 round ラベルで COMPANY(=BSB) と WorldSSP が"
             "混在する（例 ROUND2/RACE1 = DONINGTON(BSB) + PORTIMAO(SSP)）。Result PDF は WorldSSP 公式の"
             "ため、Gate 真値は `data_scope <> 'COMPANY'` で WorldSSP のみに限定している。")
    L.append("- **非 RACE セッション（SP/QP/FP/WUP）の WARNING が多い**のは、① `is_outlap`/`is_pit` を"
             "完全には導出していない（v1拡張）ため out/in ラップが G5 physical range を超える、"
             "② `race_results.laps` がレース距離基準で予選/練習のセッション周回数と意味が異なる、ため。"
             "→ 非 RACE の clean 化には is_outlap 導出 + session-type 別 Gate が次段階で必要。")
    L.append("- **FAIL の主因は results-only**（原文 PDF の Chronological にそのライダーの per-lap データが"
             "存在しない）。これは v2 パーサの欠陥ではなくソースデータの制約で、推測補完はしない（G1 FAIL=隔離）。")
    L.append("- **seg1..seg4** は「4セグ揃い & sum≈lap_time」のラップのみ充填（スタートラップ等は NULL）。"
             "ASSEN/BALATON/JEREZ の `pdf_lap_times` と全一致で較正済み。")
    L.append("")
    L.append("## 次の承認事項（Tatsuki）")
    L.append("- FAIL（特に results-only #73 系）を正本 staging に含めるか／除外するか。")
    L.append("- PASS 行のみ正本DB内 `pdf_lap_times_v2_staging` へ反映する承認（別タスク・本レポートでは未実施）。")
    L.append("- その後の Workbench 参照切替（UI 変更・別タスク・要承認）。")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description="Result PDF v2 scratch + Gate (read-only)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--file", type=Path, help="単一PDF")
    g.add_argument("--all", action="store_true", help="07_RESULTS 全 PDF（Company=BSB 除外）")
    ap.add_argument("--round", help="round で絞り込み（例 ROUND3）")
    ap.add_argument("--session", help="session_type で絞り込み（例 RACE1）")
    args = ap.parse_args()

    if not CANON_DB.exists():
        log.error("正本DBが見つかりません: %s", CANON_DB)
        sys.exit(1)

    counts_before = business_counts()
    log.info("正本DB業務テーブル(before): %s", counts_before)

    pdfs = collect_pdfs(args)
    if not pdfs:
        log.error("対象PDFなし")
        sys.exit(1)
    log.info("対象PDF: %d", len(pdfs))

    scr = fresh_scratch()
    sessions = populate_staging(scr, pdfs)

    # round/session フィルタ
    def keep(s):
        return ((not args.round or s["round"] == args.round)
                and (not args.session or s["session"] == args.session))
    sessions = [s for s in sessions if keep(s)]

    canon = ro_conn(CANON_DB)
    # gate_session が scr.connection を使うため簡易ラッパ
    scr_wrap = scr
    gated = []
    for meta in sessions:
        gated.append(gate_session(scr_wrap, canon, meta))
    scr.commit()
    canon.close()

    counts_after = business_counts()
    if counts_before != counts_after:
        log.error("業務テーブル件数が変化！ before=%s after=%s", counts_before, counts_after)
    else:
        log.info("正本DB業務テーブル(after): 不変 ✅ %s", counts_after)

    report = write_report(gated, counts_before, counts_after)
    tot = {"PASS": 0, "WARNING": 0, "FAIL": 0}
    for gg in gated:
        for k in tot:
            tot[k] += gg["summary"][k]
    log.info("Gate 集計 rider: PASS=%d WARNING=%d FAIL=%d", tot["PASS"], tot["WARNING"], tot["FAIL"])
    log.info("レポート: %s", report)
    log.info("scratch: %s", SCRATCH_DB)
    scr.close()


if __name__ == "__main__":
    main()
