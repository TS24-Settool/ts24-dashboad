#!/usr/bin/env python3
"""
apply_phase_susp_speed.py  (Tatsuki GO 2026-07-01・§44)

3フェーズ×F/R×方向 サス速度 22新列を、正本 ts24_unified.db の lap_suspension に
「追加のみ」で安全反映する。既存列・既存業務テーブルは一切変更しない。

手順（backfill_susp_zone_speed.py と同じ安全設計）:
  1. scratch DB (build_master_db.py --all で再生成・22新列込み) と 正本 を開く。
  2. 決定論ゲート: lap_suspension の「既存列」(lap_id/updated_at/22新列を除く)を lap_id JOIN で突合。
     abs(diff)<TOL・lap_id 集合一致を要求。1件でも不一致なら中断（正本は無傷）。
  3. 合格時のみ 正本 DB をバックアップ → ALTER ADD 22列 → scratch から lap_id で UPDATE(新列のみ)。
  4. before==after assert: 既存列チェックサム不変・行数不変・既存4速度列不変・業務テーブル件数不変。失敗で rollback。
  5. 検証ログ: 22新列 non-null / 分布 / p95 / zero-leak / n-condition。

使い方:
  python3 apply_phase_susp_speed.py [--scratch /tmp/ts24_scratch.db] [--target <正本>] [--apply]
  --apply 無し = ドライラン（ゲート+検証のみ・正本無変更）
"""
import argparse, hashlib, importlib.util, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TARGET = ROOT / "02_DATABASE" / "ts24_unified.db"
DEFAULT_SCRATCH = Path("/tmp/ts24_scratch.db")
TOL = 1e-6

# 22新列は build_master_db の単一定義から取得（順序・名称の唯一の真実）
_spec = importlib.util.spec_from_file_location("bm", SCRIPT_DIR / "build_master_db.py")
_bm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_bm)
NEW_COLS = list(_bm.PHASE_SPD_NEW_COLS)
EXCLUDE = {"lap_id", "updated_at"}
FROZEN = ["brk_f_dive_spd_avg", "brk_f_dive_spd_peak", "ce_r_spd_avg", "ce_r_spd_peak"]
BUSINESS = ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _num(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def determinism_gate(scon, tcon):
    tcols = _cols(tcon, "lap_suspension")
    scols = set(_cols(scon, "lap_suspension"))
    cmp_cols = [c for c in tcols if c not in EXCLUDE and c not in set(NEW_COLS)]
    missing = [c for c in cmp_cols if c not in scols]
    if missing:
        return False, [f"❌ scratch に既存列が欠落: {missing}"], cmp_cols
    def load(con):
        q = f"SELECT lap_id,{','.join(cmp_cols)} FROM lap_suspension"
        return {r[0]: r[1:] for r in con.execute(q)}
    td, sd = load(tcon), load(scon)
    msgs = []
    tset, sset = set(td), set(sd)
    if tset != sset:
        msgs.append(f"❌ lap_id集合不一致: 正本のみ{len(tset-sset)} / scratchのみ{len(sset-tset)}")
        return False, msgs, cmp_cols
    mism = []
    for lid in tset:
        for c, a, b in zip(cmp_cols, td[lid], sd[lid]):
            na, nb = _num(a), _num(b)
            if isinstance(na, float) and isinstance(nb, float):
                if abs(na - nb) >= TOL:
                    mism.append((lid, c, a, b))
            elif a != b:
                mism.append((lid, c, a, b))
        if len(mism) > 50:
            break
    if mism:
        msgs.append(f"❌ 既存列に差分 {len(mism)}件:")
        for lid, c, a, b in mism[:15]:
            msgs.append(f"    {lid}.{c}: 正本={a} scratch={b}")
        return False, msgs, cmp_cols
    msgs.append(f"✅ 決定論ゲート合格: {len(td)}ラップ × {len(cmp_cols)}既存列 全一致 (TOL={TOL})")
    return True, msgs, cmp_cols


def _existing_checksum(con, cmp_cols):
    """既存列の順序付きダンプの sha256（before==after 用）。"""
    h = hashlib.sha256()
    q = f"SELECT lap_id,{','.join(cmp_cols)} FROM lap_suspension ORDER BY lap_id"
    for row in con.execute(q):
        h.update(repr(row).encode("utf-8"))
    return h.hexdigest()


def _counts(con):
    out = {}
    for t in BUSINESS:
        try:
            out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None
    return out


def _pctile(vals, p):
    if not vals:
        return None
    s = sorted(vals); k = (len(s) - 1) * p; f = int(k); c = min(f + 1, len(s) - 1)
    return round(s[f] + (s[c] - s[f]) * (k - f), 1)


def verify(con, label):
    total = con.execute("SELECT COUNT(*) FROM lap_suspension").fetchone()[0]
    print(f"\n=== 検証ログ [{label}] (total laps={total}) ===")
    zero_leak = 0
    for c in NEW_COLS:
        vals = [r[0] for r in con.execute(f"SELECT {c} FROM lap_suspension WHERE {c} IS NOT NULL")]
        nn = len(vals); nullp = round(100 * (total - nn) / total, 1) if total else 0
        z = con.execute(f"SELECT COUNT(*) FROM lap_suspension WHERE {c}=0.0").fetchone()[0]
        zero_leak += z
        if vals:
            mn, mx, me = min(vals), max(vals), sum(vals) / nn
            line = f"  {c:22s} nn={nn:4d} null%={nullp:5.1f} min={mn:7.1f} mean={me:7.1f} max={mx:8.1f}"
            if c.endswith("_peak"):
                p95 = _pctile(vals, 0.95)
                line += f" p95={p95:7.1f}"
            print(line)
        else:
            print(f"  {c:22s} nn=0 (全NULL)")
    print(f"  zero-leak(値==0.0): {zero_leak} (期待0)")
    # n-condition: peak 非NULL は avg 非NULL を含意する（p95 n>=10 => avg n>=5）
    bad = 0
    for c in NEW_COLS:
        if c.endswith("_peak"):
            a = c[:-5] + "_avg"
            bad += con.execute(
                f"SELECT COUNT(*) FROM lap_suspension WHERE {c} IS NOT NULL AND {a} IS NULL").fetchone()[0]
    print(f"  n-condition(peak非NULL&avg NULL): {bad} (期待0)")
    for c in FROZEN:
        print(f"  frozen {c} non-null={con.execute(f'SELECT COUNT({c}) FROM lap_suspension').fetchone()[0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scratch", default=str(DEFAULT_SCRATCH))
    ap.add_argument("--target", default=str(DEFAULT_TARGET))
    ap.add_argument("--apply", action="store_true", help="指定時のみ正本更新(無指定=ドライラン)")
    a = ap.parse_args()
    print(f"scratch={a.scratch}\ntarget ={a.target}\nmode   ={'APPLY' if a.apply else 'DRY-RUN'}")
    print(f"NEW_COLS={len(NEW_COLS)}")

    scon = sqlite3.connect(a.scratch)
    # ドライランは正本を read-only で開く
    if a.apply:
        tcon = sqlite3.connect(a.target)
    else:
        tcon = sqlite3.connect(f"file:{a.target}?mode=ro", uri=True)

    ok, msgs, cmp_cols = determinism_gate(scon, tcon)
    for m in msgs:
        print(m)
    if not ok:
        print("\n中断: 既存データ差分のため正本を変更しません。", file=sys.stderr)
        sys.exit(1)

    before_counts = _counts(tcon)
    before_ck = _existing_checksum(tcon, cmp_cols)
    print(f"\n業務テーブル件数(before): {before_counts}")
    print(f"既存列 checksum(before): {before_ck[:16]}…")

    if not a.apply:
        print("\n(ドライラン) ゲート合格。scratch 側の 22新列 検証:")
        verify(scon, "scratch/dry-run")
        print("\n--apply を付けると: バックアップ→ALTER ADD 22列→lap_id UPDATE→before==after assert。")
        scon.close(); tcon.close(); return

    # ── APPLY ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = Path(a.target).parent / f"_backup_phase_susp_speed_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(a.target, bdir / Path(a.target).name)
    print(f"\nバックアップ: {bdir}")

    existing = set(_cols(tcon, "lap_suspension"))
    try:
        tcon.execute("BEGIN")
        for c in NEW_COLS:
            if c not in existing:
                tcon.execute(f"ALTER TABLE lap_suspension ADD COLUMN {c} REAL")
        sdata = {r[0]: r[1:] for r in scon.execute(
            f"SELECT lap_id,{','.join(NEW_COLS)} FROM lap_suspension")}
        set_clause = ",".join(f"{c}=?" for c in NEW_COLS)
        n = 0
        for lid, vals in sdata.items():
            cur = tcon.execute(
                f"UPDATE lap_suspension SET {set_clause} WHERE lap_id=?", (*vals, lid))
            n += cur.rowcount
        # ── before==after assert（commit 前）──
        after_counts = _counts(tcon)
        after_ck = _existing_checksum(tcon, cmp_cols)
        assert after_counts == before_counts, f"業務テーブル件数変化: {before_counts} -> {after_counts}"
        assert after_ck == before_ck, "既存列が変化（ALTER/UPDATE が既存データを破壊）"
        newcols_now = set(_cols(tcon, "lap_suspension"))
        assert all(c in newcols_now for c in NEW_COLS), "新列が追加されていない"
        tcon.execute("COMMIT")
        print(f"✅ apply 成功: ALTER {len(NEW_COLS)}列 + UPDATE {n}行")
    except Exception as e:
        tcon.execute("ROLLBACK")
        print(f"❌ apply 失敗 → ROLLBACK: {e}", file=sys.stderr)
        print(f"   バックアップから復元可: {bdir}", file=sys.stderr)
        scon.close(); tcon.close()
        sys.exit(1)

    print(f"\n業務テーブル件数(after): {_counts(tcon)}  (before と一致)")
    verify(tcon, "canonical/after-apply")
    scon.close(); tcon.close()


if __name__ == "__main__":
    main()
