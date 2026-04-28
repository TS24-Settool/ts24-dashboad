#!/usr/bin/env python3
"""
delta_analysis.py — TS24 Puccetti Racing セットアップ デルタ分析
================================================================
2つの RUN_ID を比較して、セットアップ変更前後の数値差分と
ラップタイム・サスペンション・タイヤ結果の変化を出力する。

使用方法:
  python delta_analysis.py                         ← 対話式 (RUN_ID を入力)
  python delta_analysis.py R03_ASSEN_FP_JA52_R1 R03_ASSEN_FP_JA52_R2
  python delta_analysis.py --list                  ← 利用可能な RUN_ID 一覧

出力例:
  ── SETUP DELTA ────────────────────────────────────────
  F_COMP      : 18       → 20       Δ +2
  F_REB       : 18       → 16       Δ -2
  F_OFFSET    : 5.0      → 7.0      Δ +2.0 mm
  TYRE_FRONT  : SC1      → SC2      [変更]
  ── RESULT DELTA ───────────────────────────────────────
  APEX SusF   : 40.89 mm → 39.28 mm Δ -1.61 mm ✅ (フロント沈み量 減少)
  BRAKE SusF  : 28.5  mm → 29.1  mm Δ +0.6  mm
  BEST_LAP    : 1:38.378 → 1:37.427 Δ -0.951s ✅
"""

import sys
import re
import sqlite3
from pathlib import Path

# ─────────────────────────────────────────────────────────
#  パス設定
# ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DB_PATH    = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"

# ─────────────────────────────────────────────────────────
#  セットアップ比較フィールド定義
#  (db_col, 表示名, 単位, 高い方が良い=True/悪い=True/中立=None)
# ─────────────────────────────────────────────────────────
SETUP_FIELDS = [
    # ── フォーク ──
    ("fork_type",   "Fork Type",         "",     None),
    ("f_comp",      "F Comp",            "clk",  None),
    ("f_reb",       "F Reb",             "clk",  None),
    ("f_preload",   "F Preload",         "mm",   None),
    ("f_offset",    "F Offset",          "mm",   None),
    ("f_offset2",   "F Offset2",         "mm",   None),
    ("f_oil_lvl",   "F Oil Level",       "mm",   None),
    ("f_spr_l",     "F Spring L",        "N/mm", None),
    ("f_spr_r",     "F Spring R",        "N/mm", None),
    ("f_hgt_top",   "F Height Top",      "mm",   None),
    ("f_hgt_bot",   "F Height Bot",      "mm",   None),
    ("f_tos_spr",   "F TOS Spring",      "",     None),
    ("f_tos_len",   "F TOS Length",      "mm",   None),
    # ── ショック ──
    ("shock_type",  "Shock Type",        "",     None),
    ("r_comp",      "R Comp",            "clk",  None),
    ("r_reb",       "R Reb",             "clk",  None),
    ("r_preload",   "R Preload",         "mm",   None),
    ("shock_len",   "Shock Length",      "mm",   None),
    ("link",        "Link",              "",     None),
    ("ride_hgt",    "Ride Height",       "mm",   None),
    ("swing_arm",   "Swing Arm",         "mm",   None),
    ("r_spr",       "R Spring",          "N/mm", None),
    ("r_tos_spr",   "R TOS Spring",      "",     None),
    ("r_tos_len",   "R TOS Length",      "mm",   None),
    # ── タイヤ ──
    ("tyre_front",  "Tyre Front",        "",     None),
    ("tyre_rear",   "Tyre Rear",         "",     None),
    ("f_press_out", "F Tyre Press Out",  "Bar",  None),
    ("r_press_out", "R Tyre Press Out",  "Bar",  None),
    ("f_warm_temp", "F Warm Temp",       "°C",   None),
    ("r_warm_temp", "R Warm Temp",       "°C",   None),
    # ── その他 ──
    ("weather",     "Weather",           "",     None),
    ("track_temp",  "Track Temp",        "°C",   None),
    ("air_temp",    "Air Temp",          "°C",   None),
]

RESULT_FIELDS = [
    # (db_col, 表示名, 単位, lower_is_better)
    ("apex_sus_f",      "APEX SusF",         "mm",  True),   # 小→フロント沈み量少=Good
    ("apex_sus_r",      "APEX SusR",         "mm",  None),
    ("apex_spd",        "APEX Speed",        "km/h",False),  # 大→コーナー速度高い
    ("brk_sus_f",       "BRAKE SusF",        "mm",  None),
    ("brk_sus_r",       "BRAKE SusR",        "mm",  None),
    ("brk_spd",         "BRAKE Speed",       "km/h",False),
    ("fullbrk_sus_f",   "FULL BRK SusF",     "mm",  True),
    ("fullbrk_sus_r",   "FULL BRK SusR",     "mm",  None),
    ("tyre_f_st",       "Tyre F Press (start)","Bar", None),
    ("tyre_f_en",       "Tyre F Press (end)", "Bar", None),
    ("tyre_f_delta",    "Tyre F Delta",       "Bar", None),
    ("tyre_r_st",       "Tyre R Press (start)","Bar", None),
    ("tyre_r_en",       "Tyre R Press (end)", "Bar", None),
    ("tyre_r_delta",    "Tyre R Delta",       "Bar", None),
    ("perf_best_lap",   "Best Lap",           "",    True),
    ("perf_avg_lap",    "Avg Lap",            "",    True),
    ("perf_n_laps",     "N Laps",             "",    False),
    ("perf_gap_s",      "Gap to Leader",      "s",   True),
    ("dyn_laps",        "Dynamics Laps",      "",    None),
    ("apex_count",      "APEX Count",         "",    None),
]


# ─────────────────────────────────────────────────────────
#  ユーティリティ
# ─────────────────────────────────────────────────────────
def laptime_to_sec(t):
    """'1:37.455' → 97.455、None/''/'-' → None"""
    if not t or str(t).strip() in ("", "-", "None"):
        return None
    t = str(t).strip()
    m = re.match(r"^(\d+):(\d+\.\d+)$", t)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    try:
        return float(t)
    except ValueError:
        return None


def sec_to_laptime(s):
    """97.455 → '1:37.455'"""
    if s is None:
        return "—"
    mins = int(s) // 60
    secs = s - mins * 60
    return f"{mins}:{secs:06.3f}"


def fmt_val(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def delta_str(a, b, unit="", lower_is_better=None):
    """数値差分文字列と評価マーカーを返す"""
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return "", ""
    d = fb - fa
    if abs(d) < 1e-9:
        return "0", ""
    sign = "+" if d > 0 else ""
    d_str = f"{sign}{d:.2f}".rstrip("0").rstrip(".")
    marker = ""
    if lower_is_better is True:
        marker = " ✅" if d < 0 else " ⚠️"
    elif lower_is_better is False:
        marker = " ✅" if d > 0 else " ⚠️"
    return d_str, marker


def lap_delta_str(ta, tb):
    """ラップタイム文字列同士の差分"""
    sa, sb = laptime_to_sec(ta), laptime_to_sec(tb)
    if sa is None or sb is None:
        return "", ""
    d = sb - sa
    sign = "+" if d > 0 else ""
    marker = " ✅" if d < 0 else " ⚠️"
    return f"{sign}{d:.3f}s", marker


# ─────────────────────────────────────────────────────────
#  DB クエリ
# ─────────────────────────────────────────────────────────
def fetch_run(conn, run_id):
    cur = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def list_run_ids(conn, filter_str=None):
    q = "SELECT run_id, round, circuit, session, rider, run_no FROM runs ORDER BY round, circuit, session, rider, run_no"
    rows = conn.execute(q).fetchall()
    if filter_str:
        fu = filter_str.upper()
        rows = [r for r in rows if fu in r[0].upper()]
    return rows


# ─────────────────────────────────────────────────────────
#  レポート出力
# ─────────────────────────────────────────────────────────
def print_run_info(label, run):
    print(f"\n  {label}: {run['run_id']}")
    print(f"    {run.get('round','?')} | {run.get('circuit','?')} | "
          f"{run.get('session','?')} | {run.get('rider','?')} | "
          f"Run#{run.get('run_no','?')} | {run.get('date','?')}")


def print_section(title):
    w = 70
    print(f"\n{'─' * w}")
    print(f"  {title}")
    print(f"{'─' * w}")


def print_delta_report(run_a, run_b):
    W_LABEL = 22
    W_VAL   = 12

    def row(label, va, vb, d_str="", marker="", unit=""):
        la = fmt_val(va)
        lb = fmt_val(vb)
        if unit and la != "—": la += f" {unit}"
        if unit and lb != "—": lb += f" {unit}"
        d_part = f"Δ {d_str}{unit}" if d_str not in ("", "0") else ("" if d_str == "0" else "—")
        print(f"  {label:<{W_LABEL}} {la:>{W_VAL}}  →  {lb:<{W_VAL}}  {d_part}{marker}")

    def row_text(label, va, vb):
        la, lb = fmt_val(va), fmt_val(vb)
        changed = " [変更]" if la != lb and la != "—" and lb != "—" else ""
        print(f"  {label:<{W_LABEL}} {la:>{W_VAL}}  →  {lb:<{W_VAL}}{changed}")

    # ── ヘッダー ───────────────────────────────────────────
    print("\n" + "=" * 72)
    print("  TS24 DELTA ANALYSIS REPORT")
    print("=" * 72)
    print_run_info("BASE (変更前)", run_a)
    print_run_info("COMP (変更後)", run_b)

    # ── セットアップ差分 ────────────────────────────────────
    print_section("SETUP DELTA")
    changed_count = 0
    numeric_cols = {col for col, *_ in SETUP_FIELDS if _ and _[1] not in ("", None)}

    for col, label, unit, lob in SETUP_FIELDS:
        va = run_a.get(col)
        vb = run_b.get(col)
        # 両方 None は省略
        if va is None and vb is None:
            continue
        # 値なし → —
        if isinstance(va, float) and str(va) == "nan":
            va = None
        if isinstance(vb, float) and str(vb) == "nan":
            vb = None

        # 数値
        try:
            float(va); float(vb)
            is_numeric = True
        except (TypeError, ValueError):
            is_numeric = False

        if is_numeric:
            d, mk = delta_str(va, vb, unit, lob)
            if d not in ("", "0"):
                changed_count += 1
            row(label, va, vb, d, mk, unit)
        else:
            la, lb = fmt_val(va), fmt_val(vb)
            changed = " ← 変更" if la != lb and la not in ("—","") and lb not in ("—","") else ""
            if changed:
                changed_count += 1
            print(f"  {label:<{W_LABEL}} {la:>{W_VAL}}  →  {lb:<{W_VAL}}{changed}")

    print(f"\n  セットアップ変更項目数: {changed_count}")

    # ── リザルト差分 ─────────────────────────────────────────
    print_section("RESULT DELTA")

    for col, label, unit, lob in RESULT_FIELDS:
        va = run_a.get(col)
        vb = run_b.get(col)
        if va is None and vb is None:
            continue

        # ラップタイム文字列
        if col in ("perf_best_lap", "perf_avg_lap"):
            d, mk = lap_delta_str(va, vb)
            la = fmt_val(va) or "—"
            lb = fmt_val(vb) or "—"
            d_part = f"Δ {d}" if d else "—"
            print(f"  {label:<{W_LABEL}} {la:>{W_VAL}}  →  {lb:<{W_VAL}}  {d_part}{mk}")
            continue

        try:
            fva, fvb = float(va), float(vb)
            d, mk = delta_str(va, vb, unit, lob)
            row(label, va, vb, d, mk, unit)
        except (TypeError, ValueError):
            row_text(label, va, vb)

    # ── コメント/問題 ─────────────────────────────────────────
    print_section("NOTES")
    def pnote(label, col):
        va = run_a.get(col) or "—"
        vb = run_b.get(col) or "—"
        print(f"\n  [{label}]")
        print(f"    BASE: {va}")
        print(f"    COMP: {vb}")

    pnote("問題説明 (PROBLEM DESC)",   "problem_desc")
    pnote("変更意図 (CHANGE INTENT)",  "change_intent")
    pnote("期待効果 (EXPECTED EFFECT)","expected_effect")
    pnote("結果評価 (RESULT EVAL)",    "result_eval")
    pnote("コメント (COMMENT)",        "comment")

    print("\n" + "=" * 72)
    print("  ✅ = 改善  ⚠️ = 悪化  (lower_is_better に基づく自動判定)")
    print("=" * 72 + "\n")


# ─────────────────────────────────────────────────────────
#  メイン
# ─────────────────────────────────────────────────────────
def main():
    if not DB_PATH.exists():
        print(f"[ERROR] DB が見つかりません: {DB_PATH}")
        print("  先に build_unified_db.py を実行してください。")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)

    # --list オプション
    if "--list" in sys.argv:
        filter_arg = None
        for arg in sys.argv:
            if arg.startswith("--filter="):
                filter_arg = arg.split("=", 1)[1]
        rows = list_run_ids(conn, filter_arg)
        print(f"\n利用可能な RUN_ID ({len(rows)} 件):\n")
        print(f"  {'RUN_ID':<45} {'ROUND':<8} {'CIRCUIT':<15} {'SESSION':<8} {'RIDER':<6}")
        print("  " + "─" * 85)
        for run_id, rnd, circ, sess, rider, run_no in rows:
            print(f"  {run_id:<45} {rnd or '':<8} {circ or '':<15} {sess or '':<8} {rider or '':<6}")
        conn.close()
        return

    # コマンドライン引数から RUN_ID 取得
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) >= 2:
        run_id_a = args[0].strip()
        run_id_b = args[1].strip()
    else:
        print("\n─── TS24 デルタ分析 ─────────────────────────────────────")
        print("  利用可能な RUN_ID を表示: python delta_analysis.py --list")
        print("─────────────────────────────────────────────────────────\n")
        run_id_a = input("BASE RUN_ID (変更前): ").strip()
        run_id_b = input("COMP RUN_ID (変更後): ").strip()

    if not run_id_a or not run_id_b:
        print("[ERROR] RUN_ID が入力されていません。")
        sys.exit(1)

    run_a = fetch_run(conn, run_id_a)
    run_b = fetch_run(conn, run_id_b)

    missing = []
    if run_a is None:
        missing.append(run_id_a)
    if run_b is None:
        missing.append(run_id_b)

    if missing:
        print(f"\n[ERROR] 以下の RUN_ID が DB に見つかりません:")
        for m in missing:
            print(f"  - {m}")
        print("\n  python delta_analysis.py --list で一覧を確認してください。")
        conn.close()
        sys.exit(1)

    print_delta_report(run_a, run_b)
    conn.close()


if __name__ == "__main__":
    main()
