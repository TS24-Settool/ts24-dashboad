#!/usr/bin/env python3
"""
audit_pdf_lap_extraction.py — Result PDF 抽出精度監査（read-only）

目的: Workbench `Race Analysis` が参照する `pdf_lap_times`（旧抽出）と、正式リザルト
`race_results`（v2 順位反映済み）の整合を read-only で監査し、ラップ明細の欠落・不足・
best_lap 乖離を定量化して Markdown レポートにする。v2 統合の前段。

━━━ 鉄則（厳守 / このスクリプトは絶対に書き込まない） ━━━━━━━━━━━━━━━━━━━━━━━━━
- SQLite は `file:...?mode=ro` で開く。INSERT/UPDATE/DELETE/commit を一切持たない。
- 公式PDFを再パースする場合も `pdf_result_extractor_v2.extract_pdf()` のみ使用し、
  `write_to_db()` は呼ばない（pdf_lap_times_v2 等への書込なし）。
- pdf_lap_times / race_results を更新・削除しない。Supabase もWorkbench参照先も変更しない。
- 出力は `reports/pdf_lap_extraction_audit_<YYYYMMDD>.md` のみ。

確認済みの構造（コード監査）:
- Workbench RaceAnalysisTab は `pdf_lap_times` のみ参照（ts24_workbench.py L4518/4935/4984/5132…）。
  ライダー一覧も `SELECT DISTINCT rider_num FROM pdf_lap_times` なので、pdf_lap_times に
  行が無いライダーは選択肢に出ない＝「空欄」になる。
- pdf_result_extractor_v2.write_to_db() はラップ明細を `pdf_lap_times_v2` に書く設計
  （L461/L504）だが、正本DBに `pdf_lap_times_v2` は存在しない（未書込）。
- apply_pdf_positions_v2.py は race_results の position/best_lap のみ UPSERT。ラップ明細は触らない。
  → race_results は v2 反映済み・pdf_lap_times は旧抽出、という不整合。
"""
import argparse
import datetime as _dt
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).resolve().parent
DB_PATH     = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
RESULTS_DIR = SCRIPT_DIR.parent / "07_RESULTS"
REPORTS_DIR = SCRIPT_DIR / "reports"

TEAM = {77, 52}            # TS24 のライダー（#77 / #52）
BEST_DIFF_THRESH = 0.5     # best_lap 乖離の閾値 [s]
MAX_REPARSE = 6            # PDF 再パースの上限（runtime 抑制・silent cap 回避でログ表示）


def ro_conn():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def scope_sessions(conn, rnd, ses, all_):
    q = "SELECT DISTINCT round, session_type FROM race_results"
    cond, params = [], []
    if not all_:
        if rnd:
            cond.append("round=?"); params.append(rnd)
        if ses:
            cond.append("session_type=?"); params.append(ses)
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY round, session_type"
    return [(r[0], r[1]) for r in conn.execute(q, params)]


def rr_riders(conn, rnd, ses):
    """race_results の (round,session) のライダー集計。"""
    rows = conn.execute(
        """SELECT rider_num, MAX(rider_name), MIN(position), MAX(laps), MIN(best_lap_s)
           FROM race_results WHERE round=? AND session_type=? AND rider_num IS NOT NULL
           GROUP BY rider_num""", (rnd, ses)).fetchall()
    return {r[0]: {"name": r[1], "pos": r[2], "laps": r[3], "best": r[4]} for r in rows}


def pl_riders(conn, rnd, ses):
    """pdf_lap_times の (round,session) のライダー集計（フラグ別 + valid best）。"""
    rows = conn.execute(
        """SELECT rider_num,
                  COUNT(*) AS total,
                  SUM(COALESCE(is_outlap,0)) AS outlaps,
                  SUM(COALESCE(is_pit,0)) AS pits,
                  SUM(COALESCE(is_cancelled,0)) AS cancelled,
                  COUNT(CASE WHEN COALESCE(is_outlap,0)=0 AND COALESCE(is_cancelled,0)=0
                             THEN 1 END) AS valid_cnt,
                  MIN(CASE WHEN COALESCE(is_outlap,0)=0 AND COALESCE(is_cancelled,0)=0
                           THEN lap_time_s END) AS best_valid
           FROM pdf_lap_times WHERE round=? AND session_type=? AND rider_num IS NOT NULL
           GROUP BY rider_num""", (rnd, ses)).fetchall()
    return {r[0]: {"total": r[1], "outlaps": r[2], "pits": r[3], "cancelled": r[4],
                   "valid": r[5], "best": r[6]} for r in rows}


def build_pdf_index():
    """07_RESULTS 配下の PDF を basename(lower) -> path で索引。"""
    idx = {}
    if RESULTS_DIR.exists():
        for p in RESULTS_DIR.rglob("*"):
            if p.is_file() and p.suffix.lower() == ".pdf":
                idx.setdefault(p.name.lower(), p)
    return idx


def reparse_v2(pdf_path, log):
    """pdf_result_extractor_v2.extract_pdf のみ使用（write_to_db は呼ばない）。"""
    try:
        from pdf_result_extractor_v2 import extract_pdf
        res = extract_pdf(pdf_path, all_riders=True)
        out = {}
        for num, r in res.get("riders", {}).items():
            laps = r.get("laps", [])
            valid = [lp for lp in laps if not lp.get("is_cancelled")]
            best = min((lp["lap_time_s"] for lp in valid
                        if lp.get("lap_time_s") is not None), default=None)
            out[num] = {"laps": len(laps), "valid": len(valid), "best": best,
                        "name": r.get("rider_name"), "pos": r.get("position")}
        return out, res.get("source")
    except Exception as e:  # noqa: BLE001 (監査は失敗しても続行)
        log(f"  [WARN] v2 reparse 失敗 {pdf_path.name}: {e}")
        return None, None


def fmt(v, nd=3):
    return "—" if v is None else (f"{v:.{nd}f}" if isinstance(v, float) else str(v))


def main():
    ap = argparse.ArgumentParser(description="Result PDF 抽出精度監査（read-only）")
    ap.add_argument("--round", dest="rnd", help="対象 round（例 ROUND3）")
    ap.add_argument("--session", dest="ses", help="対象 session（例 RACE1）")
    ap.add_argument("--all", action="store_true", help="全 (round,session) を監査")
    ap.add_argument("--no-pdf", action="store_true", help="PDF 再パースをしない（DB のみ）")
    ap.add_argument("--date", help="出力ファイルの日付 YYYYMMDD（既定: 今日）")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[ERROR] DB なし: {DB_PATH}", file=sys.stderr); return 1
    date_str = args.date or _dt.date.today().strftime("%Y%m%d")
    REPORTS_DIR.mkdir(exist_ok=True)

    msgs = []
    def log(m):
        print(m, flush=True); msgs.append(m)

    conn = ro_conn()
    sessions = scope_sessions(conn, args.rnd, args.ses, args.all)
    scope_txt = "ALL" if args.all or (not args.rnd and not args.ses) else \
                f"round={args.rnd or '*'} session={args.ses or '*'}"
    log(f"[audit] scope={scope_txt} sessions={len(sessions)}")

    # ── 集計 ──
    cov_rows = []          # (round, ses, n_rr, n_pl, n_missing, team77, team52)
    missing_team = []      # (round, ses, rider, name)
    lap_mismatch = []      # (round, ses, rider, name, rr_laps, pl_valid, pl_total)
    best_diff = []         # (round, ses, rider, name, rr_best, pl_best, diff)
    flag_tot = {"outlaps": 0, "pits": 0, "cancelled": 0}
    total_missing_field = 0

    for rnd, ses in sessions:
        rr = rr_riders(conn, rnd, ses)
        pl = pl_riders(conn, rnd, ses)
        missing = sorted(set(rr) - set(pl))
        total_missing_field += len(missing)
        def teamcell(t):
            return ("rr+pl" if t in rr and t in pl else
                    "rr only" if t in rr else
                    "pl only" if t in pl else "—")
        cov_rows.append((rnd, ses, len(rr), len(pl), len(missing),
                         teamcell(77), teamcell(52)))
        for t in sorted(TEAM):
            if t in rr and t not in pl:
                missing_team.append((rnd, ses, t, rr[t]["name"]))
        for num in sorted(set(rr) & set(pl)):
            v = pl[num]
            flag_tot["outlaps"] += v["outlaps"] or 0
            flag_tot["pits"] += v["pits"] or 0
            flag_tot["cancelled"] += v["cancelled"] or 0
            rl = rr[num]["laps"]
            if rl is not None and v["valid"] is not None and v["valid"] != rl:
                lap_mismatch.append((rnd, ses, num, rr[num]["name"], rl, v["valid"], v["total"]))
            rb, pb = rr[num]["best"], v["best"]
            if rb is not None and pb is not None and abs(rb - pb) > BEST_DIFF_THRESH:
                best_diff.append((rnd, ses, num, rr[num]["name"], rb, pb, abs(rb - pb)))

    # ── レポート ──
    L = []
    L.append(f"# Result PDF Lap Extraction Audit — {date_str}")
    L.append("")
    L.append(f"read-only 監査（SQLite `mode=ro` / DB 書込なし）。scope = **{scope_txt}**、対象 {len(sessions)} セッション。")
    L.append("")
    L.append("## 0. 結論（コード監査・確定事項）")
    L.append("")
    L.append("- Workbench `RaceAnalysisTab` は **`pdf_lap_times` のみ参照**（`ts24_workbench.py` L4518 ほか）。")
    L.append("  ライダー一覧も `SELECT DISTINCT rider_num FROM pdf_lap_times`（L4983-4987）のため、")
    L.append("  `pdf_lap_times` に行が無いライダー（例 #77 ROUND3/RACE1）は **選択肢に出ず空欄に見える**。")
    L.append("- `pdf_result_extractor_v2.write_to_db()` はラップ明細を **`pdf_lap_times_v2`** に書く設計（L461/L504）。")
    L.append("  だが正本DBに `pdf_lap_times_v2` は **存在しない**（v2 の `--laps --write` は正本へ未実行）。")
    L.append("- `apply_pdf_positions_v2.py` は `race_results` の position/best_lap を自然キー UPSERT するのみ。")
    L.append("  **ラップ明細（pdf_lap_times）は更新しない** → race_results=v2反映済 / pdf_lap_times=旧抽出 の不一致。")
    L.append("- 旧 `pdf_result_extractor.py` は `race_results` のみINSERT（pdf_lap_times を作らない）。")
    L.append("  現行 `pdf_lap_times` は別ビルド経路由来で、ライダー網羅・lap数ともに不完全。")
    L.append("")

    L.append("## 1. Coverage summary（race_results vs pdf_lap_times）")
    L.append("")
    L.append("| round | session | rr riders | pl riders | missing(rr→pl) | #77 | #52 |")
    L.append("|---|---|---:|---:|---:|---|---|")
    for r in cov_rows:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |")
    L.append("")
    L.append(f"- race_results にあって pdf_lap_times に無いライダー（全 field 合計）: **{total_missing_field}**")
    L.append("")

    L.append("## 2. Team riders（#77 / #52）が pdf_lap_times に欠落しているセッション")
    L.append("")
    if missing_team:
        L.append("| round | session | rider | name |")
        L.append("|---|---|---:|---|")
        for r in missing_team:
            L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    else:
        L.append("（スコープ内では team rider の欠落なし）")
    L.append("")

    L.append("## 3. Lap-count 不一致（pdf valid != race_results.laps / 共通ライダー）")
    L.append("")
    L.append(f"対象 {len(lap_mismatch)} 件。pdf valid = is_outlap=0 かつ is_cancelled=0 の行数。")
    L.append("")
    lm = sorted(lap_mismatch, key=lambda x: (x[4] or 0) - (x[5] or 0), reverse=True)
    show = lm[:50]
    L.append("| round | session | rider | name | rr.laps | pl.valid | pl.total |")
    L.append("|---|---|---:|---|---:|---:|---:|")
    for r in show:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[6])} |")
    if len(lm) > len(show):
        L.append("")
        L.append(f"（先頭 {len(show)} 件のみ表示。全 {len(lm)} 件。差が大きい順）")
    L.append("")

    L.append(f"## 4. best_lap_s 乖離（|race_results.best - pdf valid MIN| > {BEST_DIFF_THRESH}s）")
    L.append("")
    bd = sorted(best_diff, key=lambda x: x[6], reverse=True)
    L.append(f"対象 {len(bd)} 件。")
    L.append("")
    L.append("| round | session | rider | name | rr.best_s | pl.best_s | diff_s |")
    L.append("|---|---|---:|---|---:|---:|---:|")
    for r in bd[:50]:
        L.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {fmt(r[4])} | {fmt(r[5])} | {fmt(r[6])} |")
    if len(bd) > 50:
        L.append("")
        L.append(f"（先頭 50 件のみ表示。全 {len(bd)} 件）")
    L.append("")

    # ── 5. ROUND3/RACE1/#77 具体例 ──
    L.append("## 5. 具体例: ROUND3 / RACE1 / #77")
    L.append("")
    rr3 = conn.execute("""SELECT rider_num, rider_name, position, laps, best_lap_s, source_file
                          FROM race_results WHERE round='ROUND3' AND session_type='RACE1'
                          AND rider_num=77""").fetchall()
    pl3 = conn.execute("""SELECT COUNT(*) FROM pdf_lap_times
                          WHERE round='ROUND3' AND session_type='RACE1' AND rider_num=77""").fetchone()[0]
    L.append(f"- race_results: {rr3 if rr3 else '（なし）'}")
    L.append(f"- pdf_lap_times の #77 行数: **{pl3}**")
    src = rr3[0][5] if rr3 else None

    # ── 6. PDF 再パース（best-effort・上限あり） ──
    L.append("")
    L.append("## 6. v2 再パース比較（extract_pdf のみ・書込なし）")
    L.append("")
    if args.no_pdf:
        L.append("`--no-pdf` 指定のため再パースをスキップ。")
    else:
        idx = build_pdf_index()
        # ROUND3/RACE1 の #77 は常に試行（headline）。続いてスコープ内を上限まで。
        targets = []
        if src and src.lower() in idx:
            targets.append(("ROUND3", "RACE1", idx[src.lower()]))
        # スコープ各セッションの source_file を解決（重複・既追加を除外）
        seen_paths = {t[2] for t in targets}
        for rnd, ses in sessions:
            sf = conn.execute("""SELECT source_file FROM race_results
                                 WHERE round=? AND session_type=? AND source_file IS NOT NULL
                                 LIMIT 1""", (rnd, ses)).fetchone()
            if sf and sf[0] and sf[0].lower() in idx:
                p = idx[sf[0].lower()]
                if p not in seen_paths:
                    targets.append((rnd, ses, p)); seen_paths.add(p)
            if len(targets) >= MAX_REPARSE:
                break
        skipped = max(0, len(sessions) - (len(targets) - (1 if (src and src.lower() in idx) else 0)))
        L.append(f"再パース対象: {len(targets)} PDF（上限 {MAX_REPARSE}）。")
        if len(sessions) + (1 if src else 0) > len(targets):
            L.append(f"※ runtime 抑制のため一部スキップ（silent cap 回避のため明記）。全 scope={len(sessions)} セッション。")
        L.append("")
        L.append("| round | session | rider | v2.laps | v2.valid | v2.best_s | pl rows(DB) |")
        L.append("|---|---|---:|---:|---:|---:|---:|")
        for rnd, ses, p in targets:
            v2, source = reparse_v2(p, log)
            if v2 is None:
                L.append(f"| {rnd} | {ses} | — | (parse失敗) | | | |")
                continue
            # team riders を中心に提示（無ければ先頭数件）
            riders_show = [n for n in (77, 52) if n in v2] or sorted(v2)[:3]
            for n in riders_show:
                db_rows = conn.execute("""SELECT COUNT(*) FROM pdf_lap_times
                                          WHERE round=? AND session_type=? AND rider_num=?""",
                                       (rnd, ses, n)).fetchone()[0]
                d = v2[n]
                L.append(f"| {rnd} | {ses} | {n} | {fmt(d['laps'])} | {fmt(d['valid'])} | "
                         f"{fmt(d['best'])} | {db_rows} |")
    L.append("")

    # ── 7. フラグ集計 ──
    L.append("## 7. is_outlap / is_pit / is_cancelled の扱い（pdf_lap_times・共通ライダー集計）")
    L.append("")
    L.append(f"- is_outlap=1 行: {flag_tot['outlaps']} / is_pit=1 行: {flag_tot['pits']} / is_cancelled=1 行: {flag_tot['cancelled']}")
    L.append("- Workbench のライダー一覧は `SELECT DISTINCT rider_num FROM pdf_lap_times`（フラグ無関係）。")
    L.append("  → 欠落の主因はフラグ除外ではなく **行自体の不在/不足**（§1-§3）。")
    L.append("")

    # ── 8. 推奨次作業 ──
    L.append("## 8. 推奨する次作業（いずれも要 Tatsuki 承認・本監査では未実施）")
    L.append("")
    L.append("1. **v2 を scratch table 化 + Gate**（推奨・最も安全）: `pdf_result_extractor_v2` で全 RACE/QP 等を")
    L.append("   `--all-riders --laps` 抽出し、`/tmp` か scratch DB の `pdf_lap_times_v2` に投入。")
    L.append("   `race_results.laps`/`best_lap_s` と突合する Gate（lap数一致・best乖離<閾値）を PASS した分のみ採用。")
    L.append("2. **Workbench を v2/scratch 参照可能にする**: Gate 通過後、`RaceAnalysisTab` の参照を")
    L.append("   `pdf_lap_times`（旧）→ 検証済みテーブルへ切替（UI 切替は別タスク・要承認）。")
    L.append("3. **旧 pdf_lap_times の直接修正は非推奨**: 取りこぼし由来で出所不明。上書きより Gate 付き再構築が安全。")
    L.append("   どうしても旧を使う場合も、まず本監査の不一致をゼロにする再抽出が前提。")
    L.append("")
    L.append("> 本監査は read-only。pdf_lap_times / race_results / Supabase / Workbench 参照先はいずれも未変更。")

    conn.close()
    out_path = REPORTS_DIR / f"pdf_lap_extraction_audit_{date_str}.md"
    out_path.write_text("\n".join(L) + "\n", encoding="utf-8")
    log(f"[out] {out_path}")
    log(f"[summary] missing_team={len(missing_team)} lap_mismatch={len(lap_mismatch)} "
        f"best_diff={len(best_diff)} field_missing={total_missing_field}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
