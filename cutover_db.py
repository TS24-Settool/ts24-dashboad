#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cutover_db.py — ts24_master.db(新データ) を正式DB ts24_unified.db に昇格。
新データテーブル + エンジニア手動記録テーブル(problem_log等)を統合。
旧ファイルは ts24_unified.old.db として保持。

恒久化(2026-06-18):
  - best_worst_pairs はエンジニアの手入力(cause_analysis 等)を含むため PRESERVE。
    旧 run_id 形式 ({round}_{circuit}_{session}_{rider}_R{n}) を、新 run_id
    ({date}_{round}_{circuit}_{session}_{rider}_R{n}) へ可能な範囲で再マップする。
  - lap_suspension は build_master_db 側で新 run_id を使って再生成されるため、
    ここでは旧DBから保持しない(master の値が正)。
"""
import re
import sqlite3
import shutil
from pathlib import Path

DB = Path(__file__).parent.parent / "02_DATABASE"
master  = DB / "ts24_master.db"
unified = DB / "ts24_unified.db"
newdb   = DB / "ts24_unified.new.db"

# 旧DBから保持するテーブル(エンジニア記録 + 公式リザルト + 手入力分析)
PRESERVE = ["problem_log", "setup_decision_log", "problem_library",
            "round_brief", "lap_observation_log", "race_results", "pdf_lap_times",
            "best_worst_pairs"]

# run_id を再マップするテーブル: {table: [run_id列...]}
REMAP_RUNID = {"best_worst_pairs": ["run_id_best", "run_id_worst"]}


def circuit_canon(c):
    """build_master_db.circuit_canon と同一の正規化(再マップ照合用)。"""
    u = re.sub(r"[^A-Z0-9]", "", str(c or "").upper())
    t = {"PHILIPISLAND": "PHILLIPISLAND", "PHILLIPISLAND": "PHILLIPISLAND",
         "PHILLIPISISLAND": "PHILLIPISLAND", "BALATON": "BALATON",
         "BALATONPARK": "BALATON", "MOTORLANDARAGON": "ARAGON", "ARAGON": "ARAGON",
         "WORKSHOP": "PHILLIPISLAND", "AUSTRALIA": "PHILLIPISLAND",
         "MAGNYCOURS": "MAGNYCOURS"}
    return t.get(u, u)


def _parse_old_runid(rid):
    """旧 run_id -> (round, circuit_canon, session, rider, run_no) or None。
    形式: {ROUND|TEST}x _ {CIRCUIT...} _ {SESSION} _ {RIDER} _ R{n}
    """
    if not rid:
        return None
    parts = str(rid).split("_")
    if len(parts) < 5:
        return None
    m = re.match(r"^R(\d+)$", parts[-1].upper())
    if not m:
        return None
    run_no = int(m.group(1))
    rider = parts[-2].upper()
    session = parts[-3].upper()
    rnd = parts[0].upper()
    circuit = circuit_canon("".join(parts[1:-3]))
    return (rnd, circuit, session, rider, run_no)


def _build_runid_index(con):
    """新 runs から照合キー -> run_id の索引を作る。"""
    idx = {}
    dups = set()
    for run_id, rnd, circ, sess, rider, run_no in con.execute(
            "SELECT run_id, round, circuit, session, rider, run_no FROM runs"):
        try:
            key = (str(rnd or "").upper(), circuit_canon(circ),
                   str(sess or "").upper(), str(rider or "").upper(), int(run_no))
        except (TypeError, ValueError):
            continue
        if key in idx:
            dups.add(key)
        else:
            idx[key] = run_id
    return idx, dups


def remap_best_worst(con):
    """best_worst_pairs の run_id を旧->新へ再マップ(手入力 cause_analysis は保持)。"""
    if not con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='best_worst_pairs'"
    ).fetchone():
        return
    idx, dups = _build_runid_index(con)
    valid = {r[0] for r in con.execute("SELECT run_id FROM runs")}  # 既に正しい run_id (再cutover冪等化)
    rows = con.execute("SELECT pair_id, run_id_best, run_id_worst FROM best_worst_pairs").fetchall()
    mapped = already = unmapped = 0
    for pair_id, rb, rw in rows:
        def conv(rid):
            nonlocal mapped, already, unmapped
            if rid in valid:        # 既に新 run_id (2回目以降の cutover)
                already += 1
                return rid
            k = _parse_old_runid(rid)
            new = idx.get(k) if k else None
            if new:
                mapped += 1
                return new
            unmapped += 1
            return rid  # 解決不能なら旧値を残す(分析を捨てない)
        nb, nw = conv(rb), conv(rw)
        new_pair = f"{nb}_vs_{nw}"
        con.execute(
            "UPDATE best_worst_pairs SET run_id_best=?, run_id_worst=?, pair_id=? WHERE pair_id=?",
            (nb, nw, new_pair, pair_id))
    con.commit()
    print(f"[remap] best_worst_pairs run_id: 新規マップ {mapped} / 既に正 {already} / 未解決 {unmapped}"
          f"{f' (照合キー重複 {len(dups)} 種)' if dups else ''}")


assert master.exists(), "ts24_master.db が無い"
shutil.copy(master, newdb)

con = sqlite3.connect(newdb)
con.execute(f"ATTACH DATABASE '{unified}' AS old")
old_tables = {r[0] for r in con.execute("SELECT name FROM old.sqlite_master WHERE type='table'")}
new_tables = {r[0] for r in con.execute("SELECT name FROM main.sqlite_master WHERE type='table'")}
copied = []
for t in PRESERVE:
    if t in old_tables and t not in new_tables:
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM old.{t}")
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        copied.append(f"{t}({n})")
con.commit()
con.execute("DETACH DATABASE old")

# run_id 再マップ(保持テーブルのうち run_id 参照分)
remap_best_worst(con)
con.close()

# スワップ
old_keep = DB / "ts24_unified.old.db"
if old_keep.exists():
    old_keep.unlink()
unified.rename(old_keep)
newdb.rename(unified)

con = sqlite3.connect(unified)
tabs = sorted(r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'"))
print("[cutover] 新 ts24_unified.db テーブル:")
for t in tabs:
    n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
    print(f"   {t:22} {n}")
con.close()
print("保持コピー:", copied)
print("旧DBは ts24_unified.old.db に退避済み")
