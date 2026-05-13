"""
ROUND4 CSV → laps テーブルインポートスクリプト
距離ベース（4114m/lap）でラップ検出。

CSV → run_id マッピング:
  QP-RUN2  → ROUND4_BALATON_QP_DA77_R1  (クリーン、2完全ラップ)
  QP-RUN3  → ROUND4_BALATON_QP_DA77_R2  (クリーン、1完全ラップ)
  QP-RUN1 Seg1→ ROUND4_BALATON_QP_DA77_R3  (115s gap後のセグメント)
  RACE1    → ROUND4_BALATON_RACE1_DA77_R1  (16ラップ)
"""

import sqlite3, re, sys
from pathlib import Path
import pandas as pd
import numpy as np

SCRIPT_DIR = Path(__file__).parent
DB_PATH    = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
CSV_DIR    = SCRIPT_DIR.parent / "06_CSV"

LAP_LEN_M = 4114.0   # Balaton サーキット1周距離（m）
GAP_SEC   = 5.0      # ピットイン検出しきい値（秒）


def fmt_laptime(s: float) -> str:
    m   = int(s) // 60
    sec = s - m * 60
    return f"{m}:{sec:06.3f}"


def load_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "shift_jis"):
        for sep in (";", ","):
            try:
                df = pd.read_csv(path, encoding=enc, sep=sep,
                                 decimal="," if sep == ";" else ".",
                                 skiprows=[1], header=0, dtype=str)
                if len(df.columns) > 1:
                    df = df.apply(lambda col: pd.to_numeric(
                        col.str.replace(",", ".", regex=False), errors="coerce"))
                    return df
            except Exception:
                continue
    raise ValueError(f"読み込み失敗: {path}")


def detect_laps_by_distance(t, d, lap_len=LAP_LEN_M, start_offset=0):
    """
    累積距離ベースでラップ境界を検出。
    戻り値: [(lap_time_s, dist_span_m), ...]
    """
    d0  = d[0]
    d_rel = d - d0 + start_offset
    total_dist = d_rel[-1]
    n_complete = int(total_dist / lap_len)
    
    laps = []
    prev_idx = 0
    for k in range(1, n_complete + 1):
        target = k * lap_len
        idx = np.searchsorted(d_rel, target)
        if idx < len(t):
            lt = float(t[idx]) - float(t[prev_idx])
            laps.append({"lap_time_s": round(lt, 3), "dist_span_m": lap_len})
            prev_idx = idx
    return laps


def split_by_gaps(t, d, gap_sec=GAP_SEC):
    """時間ギャップでセグメントに分割。"""
    gaps = np.diff(t)
    bounds = [0] + [i + 1 for i in range(len(gaps)) if gaps[i] > gap_sec] + [len(t)]
    return [(bounds[i], bounds[i+1]) for i in range(len(bounds)-1)]


def insert_laps(conn, run_id, laps_data, date_fmt, run_info, start_lap_no=1, dry_run=False):
    circuit    = run_info["circuit"]
    session    = run_info["session"]
    rider      = run_info["rider"]
    run_no     = run_info["run_no"]
    round_s    = run_info["round"]
    session_id = f"{round_s}_{circuit}_{session}_{rider}"
    weather    = run_info.get("weather") or "DRY"
    track_temp = run_info.get("track_temp")
    air_temp   = run_info.get("air_temp")
    tyre_f     = run_info.get("tyre_front")
    tyre_r     = run_info.get("tyre_rear")
    
    inserted = 0
    for i, l in enumerate(laps_data):
        lap_no = start_lap_no + i
        lap_id = f"{run_id}_L{lap_no}"
        lt = l["lap_time_s"]
        lap_time_str = fmt_laptime(lt)
        print(f"    Lap {lap_no}: {lap_time_str}")
        if dry_run:
            continue
        conn.execute("""
            INSERT OR IGNORE INTO laps
            (lap_id, run_id, session_id, round, circuit, session, rider,
             run_no, lap_no, date, lap_time, lap_time_s, is_outlap,
             weather, air_temp, track_temp, tyre_front, tyre_rear)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (lap_id, run_id, session_id, round_s, circuit, session, rider,
              run_no, lap_no, date_fmt,
              lap_time_str, lt, 0,
              weather, air_temp, track_temp, tyre_f, tyre_r))
        inserted += 1
    return inserted


def update_perf(conn, run_id, laps_data, dry_run=False):
    """runs テーブルの perf_* を更新。"""
    times = [l["lap_time_s"] for l in laps_data]
    if not times:
        return
    best = min(times)
    avg  = round(sum(times) / len(times), 3)
    n    = len(times)
    print(f"    → best={fmt_laptime(best)}  avg={fmt_laptime(avg)}  n={n}")
    if not dry_run:
        conn.execute(
            "UPDATE runs SET perf_best_lap=?, perf_avg_lap=?, perf_n_laps=? WHERE run_id=?",
            (best, avg, n, run_id),
        )


def get_run_info(conn, run_id):
    row = conn.execute(
        "SELECT run_id, round, circuit, session, rider, run_no, "
        "weather, track_temp, air_temp, tyre_front, tyre_rear FROM runs WHERE run_id=?",
        (run_id,)
    ).fetchone()
    if row:
        return dict(row)
    return None


# ══════════════════════════════════════════════════════════════════
# メイン処理
# ══════════════════════════════════════════════════════════════════
def main():
    dry_run = "--dry-run" in sys.argv
    print(f"{'[DRY RUN] ' if dry_run else ''}DB: {DB_PATH}\n")
    
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    
    total = 0
    date_fmt = "2026-05-01"
    
    # ── 1) QP RUN2 → R1 ────────────────────────────────────────────
    csv2 = CSV_DIR / "20260501-ROUND4-QP-RUN2-DA77.csv"
    run_id = "ROUND4_BALATON_QP_DA77_R1"
    existing = conn.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (run_id,)).fetchone()[0]
    if existing:
        print(f"[QP R1] {run_id}: 既存 {existing} laps → スキップ")
    else:
        print(f"[QP R1] {run_id} ← {csv2.name}")
        df = load_csv(csv2)
        t = df["Time"].values; d = df["Dist"].values
        laps = detect_laps_by_distance(t, d)
        run_info = get_run_info(conn, run_id)
        n = insert_laps(conn, run_id, laps, date_fmt, run_info, start_lap_no=1, dry_run=dry_run)
        update_perf(conn, run_id, laps, dry_run)
        total += n
    
    # ── 2) QP RUN3 → R2 ────────────────────────────────────────────
    csv3 = CSV_DIR / "20260501-ROUND4-QP-RUN3-DA77.csv"
    run_id = "ROUND4_BALATON_QP_DA77_R2"
    existing = conn.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (run_id,)).fetchone()[0]
    if existing:
        print(f"[QP R2] {run_id}: 既存 {existing} laps → スキップ")
    else:
        print(f"\n[QP R2] {run_id} ← {csv3.name}")
        df = load_csv(csv3)
        t = df["Time"].values; d = df["Dist"].values
        laps = detect_laps_by_distance(t, d)
        run_info = get_run_info(conn, run_id)
        n = insert_laps(conn, run_id, laps, date_fmt, run_info, start_lap_no=1, dry_run=dry_run)
        update_perf(conn, run_id, laps, dry_run)
        total += n
    
    # ── 3) QP RUN1 第2セグメント → R3 ─────────────────────────────
    csv1 = CSV_DIR / "20260501-ROUND4-QP-RUN1-DA77.csv"
    run_id = "ROUND4_BALATON_QP_DA77_R3"
    existing = conn.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (run_id,)).fetchone()[0]
    if existing:
        print(f"[QP R3] {run_id}: 既存 {existing} laps → スキップ")
    else:
        print(f"\n[QP R3] {run_id} ← {csv1.name} (Seg1 after gap)")
        df = load_csv(csv1)
        t = df["Time"].values; d = df["Dist"].values
        segs = split_by_gaps(t, d)
        if len(segs) >= 2:
            s, e = segs[1]   # 2番目のセグメント
            t2 = t[s:e]; d2 = d[s:e]
            laps = detect_laps_by_distance(t2, d2)
            run_info = get_run_info(conn, run_id)
            n = insert_laps(conn, run_id, laps, date_fmt, run_info, start_lap_no=1, dry_run=dry_run)
            update_perf(conn, run_id, laps, dry_run)
            total += n
        else:
            print("  セグメント2が見つかりません")
    
    # ── 4) RACE1 → R1 ──────────────────────────────────────────────
    csv_race = CSV_DIR / "20260501-ROUND4-RACE1-DA77.csv"
    run_id = "ROUND4_BALATON_RACE1_DA77_R1"
    existing = conn.execute("SELECT COUNT(*) FROM laps WHERE run_id=?", (run_id,)).fetchone()[0]
    if existing:
        print(f"[RACE1] {run_id}: 既存 {existing} laps → スキップ")
    else:
        print(f"\n[RACE1] {run_id} ← {csv_race.name}")
        df = load_csv(csv_race)
        t = df["Time"].values; d = df["Dist"].values
        laps = detect_laps_by_distance(t, d)
        run_info = get_run_info(conn, run_id)
        n = insert_laps(conn, run_id, laps, date_fmt, run_info, start_lap_no=1, dry_run=dry_run)
        update_perf(conn, run_id, laps, dry_run)
        total += n
    
    if not dry_run:
        conn.commit()
    conn.close()
    
    print(f"\n{'[DRY RUN] ' if dry_run else ''}完了: 合計 {total} ラップ{'挿入' if not dry_run else '検出'}")


if __name__ == "__main__":
    main()
