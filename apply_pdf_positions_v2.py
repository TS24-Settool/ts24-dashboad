#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_pdf_positions_v2.py — v2 PDF抽出の順位/ベストラップを本番 race_results に反映し、
performance.session_position を再計算する。

なぜ専用スクリプトか:
  pdf_result_extractor_v2.write_to_db() は素の INSERT で、race_results に
  ローカル UNIQUE 制約が無いため再実行で重複が増える。本スクリプトは
  自然キー (round, session_type, rider_num) で UPDATE(無ければ INSERT)し冪等。

照合キーに circuit を含めない理由: 表記揺れ("PHILLIP ISLAND" 等)を避けるため。
round は1イベント=1サーキットで一意なので round+session_type+rider_num で十分。

使い方:
  python3 apply_pdf_positions_v2.py --dry-run                 # 差分プレビュー(既定: DA77/JA52)
  python3 apply_pdf_positions_v2.py --all-riders --dry-run    # 全ライダーで差分
  python3 apply_pdf_positions_v2.py --all-riders --write      # 本番反映
"""
import argparse
import re
import sqlite3
import importlib.util
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ROOT = SCRIPT_DIR.parent
DEFAULT_DB = ROOT / "02_DATABASE" / "ts24_unified.db"
RESULTS = ROOT / "07_RESULTS"

# v2 抽出器をモジュールとして読み込み
_spec = importlib.util.spec_from_file_location("v2", SCRIPT_DIR / "pdf_result_extractor_v2.py")
v2 = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(v2)
# build と同一の正規化(circuit_canon / session_canon_orig)を再利用
_bspec = importlib.util.spec_from_file_location("b", SCRIPT_DIR / "build_master_db.py")
B = importlib.util.module_from_spec(_bspec); _bspec.loader.exec_module(B)


def _round_num(r):
    m = re.search(r"(\d+)", str(r or "")); return m.group(1) if m else ""


def extract_all(all_riders):
    pdfs = sorted(RESULTS.rglob("*.pdf"))
    out = []  # (round, circuit, session_type, rider_num, position, best_lap_s, best_lap, file)
    for p in pdfs:
        try:
            res = v2.extract_pdf(p, all_riders=all_riders)
        except Exception as e:
            print(f"[WARN] 抽出失敗 {p.name}: {e}"); continue
        m = res["meta"]
        for num, r in res["riders"].items():
            out.append((m.get("round"), m.get("circuit"), m.get("session_type"),
                        num, r.get("position"), r.get("best_lap_s"), r.get("best_lap"), p.name))
    return out, len(pdfs)


def refresh_session_position(con):
    """race_results(DA77/JA52) → performance.session_position を再計算(build と同一ロジック)。"""
    pos = {}
    for rnd, circ, sess, rnum, p in con.execute(
            "SELECT round,circuit,session_type,rider_num,position FROM race_results WHERE rider_num IN (52,77)"):
        rider = "JA52" if str(rnum) == "52" else "DA77"
        pos[(rider, B.circuit_canon(circ), B.session_canon_orig(sess), _round_num(rnd))] = p
    n = 0
    for run_id, rider, circ, rnd, sess in con.execute(
            "SELECT run_id,rider,circuit,round,session FROM performance").fetchall():
        key = (rider, B.circuit_canon(circ), B.session_canon_orig(sess), _round_num(rnd))
        p = pos.get(key)
        if p is not None:
            con.execute("UPDATE performance SET session_position=? WHERE run_id=?", (p, run_id)); n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description="v2 PDF順位を race_results へ反映 + performance.session_position 更新")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--all-riders", action="store_true", help="全ライダー(既定はDA77/JA52のみ)")
    ap.add_argument("--write", action="store_true", help="DBへ書込(既定は書込なし)")
    ap.add_argument("--dry-run", action="store_true", help="書込なしで差分のみ")
    args = ap.parse_args()

    extracted, n_pdf = extract_all(args.all_riders)
    print(f"抽出: {len(extracted)} rider-rows / {n_pdf} PDFs (all_riders={args.all_riders})")

    con = sqlite3.connect(args.db)
    upd = ins = skip = changed = 0
    do_write = args.write and not args.dry_run
    for rnd, circ, sess, num, pos, bls, bl, fname in extracted:
        if rnd is None or sess is None:
            skip += 1; continue
        row = con.execute(
            "SELECT position FROM race_results WHERE round=? AND session_type=? AND rider_num=?",
            (rnd, sess, num)).fetchone()
        if row is not None:
            if pos is None and row[0] is not None:
                print(f"  [KEEP] {rnd} {sess} #{num}: v2 pos=None → 既存 {row[0]} を保持")
            elif pos is not None and row[0] != pos:
                changed += 1
                print(f"  [DIFF] {rnd} {sess} #{num}: pos {row[0]} -> {pos}  best={bl}")
            if do_write:
                # COALESCE: v2 が None の項目は既存値を保持(良いデータを消さない)
                con.execute(
                    "UPDATE race_results SET position=COALESCE(?,position), "
                    "best_lap_s=COALESCE(?,best_lap_s), best_lap=COALESCE(?,best_lap) "
                    "WHERE round=? AND session_type=? AND rider_num=?",
                    (pos, bls, bl, rnd, sess, num))
            upd += 1
        else:
            if pos is None:
                skip += 1; continue  # 順位の取れない新規行は挿入しない(ノイズ防止)
            print(f"  [NEW]  {rnd} {sess} #{num} pos={pos} best={bl} ({fname})")
            if do_write:
                con.execute(
                    "INSERT INTO race_results (round,circuit,session_type,position,rider_num,best_lap,best_lap_s,source_file) "
                    "VALUES (?,?,?,?,?,?,?,?)", (rnd, circ, sess, pos, num, bl, bls, fname))
            ins += 1

    n_perf = 0
    if do_write:
        con.commit()
        n_perf = refresh_session_position(con)
        con.commit()
    else:
        # dry-run でも更新見込み件数を表示
        n_perf = refresh_session_position(con)  # 書込はトランザクション未commitで破棄
        con.rollback()

    print(f"\n=== {'WRITE' if do_write else 'DRY-RUN'} ===")
    print(f"race_results: 既存更新 {upd} (うち順位変更 {changed}) / 新規 {ins} / スキップ {skip}")
    print(f"performance.session_position: {n_perf} 件に順位を設定")
    con.close()


if __name__ == "__main__":
    main()
