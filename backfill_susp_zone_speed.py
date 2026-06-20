#!/usr/bin/env python3
"""
backfill_susp_zone_speed.py  (Tatsuki承認 2026-06-20)

ゾーン限定サス速度 + PH1-2リア0mm累積秒の5新カラムを、正本 ts24_unified.db の
lap_suspension に安全に反映する。全DB cutover/run_id再マップは行わない(リスク回避)。

手順:
  1. scratch DB (build_master_db.py --all で再生成) と 正本 を開く
  2. 決定論ゲート: lap_suspension の「既存数値列」を lap_id JOIN で突合。
     timestamp(updated_at)と新5列は除外。abs(diff) < TOL で完全一致を要求。
     lap_id 集合も完全一致を要求。1件でも不一致なら中断(正本は無傷)。
  3. 合格時のみ 正本.lap_suspension に5列を ALTER ADD し、scratch から lap_id で UPDATE。
  4. 検証ログ: NULL率 / 分布(min/mean/max) / peak の p95 vs max / ph12退化確認。

使い方:
  python3 backfill_susp_zone_speed.py [--scratch /tmp/ts24_scratch.db] [--target <正本>] [--apply]
  --apply 無し = ドライラン(ゲート+検証のみ、正本は変更しない)
"""
import argparse, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "02_DATABASE" / "ts24_unified.db"
DEFAULT_SCRATCH = Path("/tmp/ts24_scratch.db")
NEW_COLS = ["brk_f_dive_spd_avg", "brk_f_dive_spd_peak", "ce_r_spd_avg", "ce_r_spd_peak", "ph12_rear0_s"]
EXCLUDE = {"updated_at"}            # timestamp は決定論比較から除外
TOL = 1e-6


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _load(con, cols):
    q = f"SELECT lap_id,{','.join(cols)} FROM lap_suspension"
    out = {}
    for row in con.execute(q):
        out[row[0]] = row[1:]
    return out


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v   # 非数値(TEXT)はそのまま


def determinism_gate(scon, tcon):
    """既存数値列(timestamp/新列除外)が scratch==正本 か検証。(ok, msgs)"""
    tcols = _cols(tcon, "lap_suspension")
    scols = set(_cols(scon, "lap_suspension"))
    # 比較対象 = 正本の列 − lap_id − timestamp − 新5列。全て scratch にも存在すること。
    cmp_cols = [c for c in tcols if c != "lap_id" and c not in EXCLUDE and c not in NEW_COLS]
    missing = [c for c in cmp_cols if c not in scols]
    if missing:
        return False, [f"❌ scratch に既存列が欠落: {missing}"]
    tdata = _load(tcon, cmp_cols)
    sdata = _load(scon, cmp_cols)
    msgs = []
    tset, sset = set(tdata), set(sdata)
    if tset != sset:
        only_t = list(tset - sset)[:10]
        only_s = list(sset - tset)[:10]
        msgs.append(f"❌ lap_id集合が不一致: 正本のみ{len(tset-sset)}件{only_t} / scratchのみ{len(sset-tset)}件{only_s}")
        return False, msgs
    mism = []
    for lid in tdata:
        tv, sv = tdata[lid], sdata[lid]
        for c, a, b in zip(cmp_cols, tv, sv):
            na, nb = _num(a), _num(b)
            if isinstance(na, float) and isinstance(nb, float):
                if abs(na - nb) >= TOL:
                    mism.append((lid, c, a, b))
            else:
                if a != b:
                    mism.append((lid, c, a, b))
        if len(mism) > 50:
            break
    if mism:
        msgs.append(f"❌ 既存列に差分 {len(mism)}件(>=50で打切):")
        for lid, c, a, b in mism[:15]:
            msgs.append(f"    {lid} . {c}: 正本={a} scratch={b}")
        return False, msgs
    msgs.append(f"✅ 決定論ゲート合格: {len(tdata)}ラップ × {len(cmp_cols)}既存列, 全一致 (TOL={TOL})")
    return True, msgs


def apply_new_cols(scon, tcon):
    existing = set(_cols(tcon, "lap_suspension"))
    for c in NEW_COLS:
        if c not in existing:
            tcon.execute(f"ALTER TABLE lap_suspension ADD COLUMN {c} REAL")
    tcon.commit()
    # scratch から lap_id で UPDATE
    sdata = {lid: vals for lid, *vals in
             ((r[0], *r[1:]) for r in scon.execute(
                 f"SELECT lap_id,{','.join(NEW_COLS)} FROM lap_suspension"))}
    n = 0
    set_clause = ",".join(f"{c}=?" for c in NEW_COLS)
    for lid, vals in sdata.items():
        cur = tcon.execute(f"UPDATE lap_suspension SET {set_clause} WHERE lap_id=?", (*vals, lid))
        n += cur.rowcount
    tcon.commit()
    return n


def _pctile(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    k = (len(s) - 1) * p
    f = int(k); c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def verify(con):
    total = con.execute("SELECT COUNT(*) FROM lap_suspension").fetchone()[0]
    print(f"\n=== 検証ログ (total laps={total}) ===")
    for c in NEW_COLS:
        rows = [r[0] for r in con.execute(f"SELECT {c} FROM lap_suspension WHERE {c} IS NOT NULL")]
        nn = len(rows)
        nullpct = round(100 * (total - nn) / total, 1) if total else 0
        if rows:
            mn, mx = min(rows), max(rows)
            mean = sum(rows) / nn
            line = f"  {c:22s} 非NULL={nn:4d} NULL率={nullpct:5.1f}%  min={mn:8.2f} mean={mean:8.2f} max={mx:8.2f}"
            if c.endswith("_peak"):
                p95 = _pctile(rows, 0.95)
                line += f"  p95={p95:8.2f}  (max/p95={mx/p95:.2f}x)" if p95 else ""
            print(line)
        else:
            print(f"  {c:22s} 非NULL=0 (全NULL)")
    # ph12 退化確認
    z = con.execute("SELECT COUNT(*) FROM lap_suspension WHERE ph12_rear0_s=0.0").fetchone()[0]
    nz = con.execute("SELECT COUNT(*) FROM lap_suspension WHERE ph12_rear0_s>0.0").fetchone()[0]
    print(f"  ph12_rear0_s 退化確認: =0秒 {z}件 / >0秒 {nz}件" +
          ("  ⚠ ほぼ全0なら ≤0.3mm 微調整を検討" if nz < total * 0.1 else "  ✅ 分布あり"))
    # 信頼度との整合(参考): ce_r_spd_avg 非NULL は ce_count>=5 と概ね一致するはず
    chk = con.execute("""SELECT
            SUM(CASE WHEN ce_r_spd_avg IS NOT NULL AND ce_count<5 THEN 1 ELSE 0 END),
            SUM(CASE WHEN brk_f_dive_spd_avg IS NOT NULL AND fullbrk_count<5 THEN 1 ELSE 0 END)
        FROM lap_suspension""").fetchone()
    print(f"  整合性(参考): ce_r非NULL&ce_count<5={chk[0]}  brk_f非NULL&fullbrk_count<5={chk[1]} (0が理想)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--target", default=str(DEFAULT_TARGET))
    ap.add_argument("--apply", action="store_true", help="指定時のみ正本を更新(無指定=ドライラン)")
    a = ap.parse_args()
    scon = sqlite3.connect(a.scratch)
    tcon = sqlite3.connect(a.target)
    print(f"scratch={a.scratch}\ntarget ={a.target}\nmode   ={'APPLY' if a.apply else 'DRY-RUN'}")
    ok, msgs = determinism_gate(scon, tcon)
    for m in msgs:
        print(m)
    if not ok:
        print("\n中断: 既存データに差分のため正本を変更しません。", file=sys.stderr)
        sys.exit(1)
    if a.apply:
        n = apply_new_cols(scon, tcon)
        print(f"\n✅ 正本へ反映: {len(NEW_COLS)}列 ALTER + {n}行 UPDATE")
        verify(tcon)
    else:
        print("\n(ドライラン) ゲート合格。scratch側の検証ログを表示:")
        verify(scon)
    scon.close(); tcon.close()


if __name__ == "__main__":
    main()
