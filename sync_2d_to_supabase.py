#!/usr/bin/env python3
"""
sync_2d_to_supabase.py — 2Dデータ → Supabase 一括同期
==========================================================
事前準備:
  Supabase SQL Editor で create_2d_tables.sql を実行してください

実行方法:
  python3 sync_2d_to_supabase.py

処理:
  1. 02_DATABASE/all_sessions.json を読み込み
  2. sessions_2d テーブルへ upsert (171セッション)
  3. lap_times_2d テーブルへ upsert (634ラップ)
==========================================================
"""

import json
import math
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "ts24_config.json"
CACHE_FILE  = SCRIPT_DIR.parent / "02_DATABASE" / "all_sessions.json"
BATCH_SIZE  = 200

# ── Config ────────────────────────────────────────────────────────
def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}

# ── Supabase API ──────────────────────────────────────────────────
def supa_req(method, url, key, data=None):
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:400]
        return False, f"HTTP {e.code}: {msg}"
    except Exception as e:
        return False, str(e)

CONFLICT_COLS = {
    "sessions_2d":  "round,date,circuit,session_type,rider,run_no",
    "lap_times_2d": "round,date,session_type,rider,run_no,lap_no",
}

DEDUP_KEYS = {
    "sessions_2d":  ("round", "date", "circuit", "session_type", "rider", "run_no"),
    "lap_times_2d": ("round", "date", "session_type", "rider", "run_no", "lap_no"),
}

def dedup_records(table, records):
    """Remove duplicate rows (same conflict key) keeping last occurrence."""
    key_cols = DEDUP_KEYS.get(table)
    if not key_cols:
        return records
    seen = {}
    for r in records:
        k = tuple(r.get(c) for c in key_cols)
        seen[k] = r          # later row overwrites earlier duplicate
    deduped = list(seen.values())
    removed = len(records) - len(deduped)
    if removed:
        print(f"  ℹ️  Deduped {removed} duplicate rows from {table}")
    return deduped

def upsert_batch(supa_url, key, table, rows):
    """Upsert (INSERT ... ON CONFLICT DO UPDATE) via Supabase REST."""
    on_conflict = CONFLICT_COLS.get(table, "")
    url = f"{supa_url}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    return supa_req("POST", url, key, rows)

def count_table(supa_url, key, table):
    url = f"{supa_url}/rest/v1/{table}?select=id&limit=1"
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Prefer":        "count=exact",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            cnt_hdr = resp.getheader("Content-Range", "")
            # Content-Range: 0-0/1234
            if "/" in cnt_hdr:
                return int(cnt_hdr.split("/")[-1])
            return len(json.loads(resp.read()))
    except Exception:
        return -1

# ── Data helpers ──────────────────────────────────────────────────
def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v == "" or v == "N/A":
        return None
    return v

def _parse_date(d):
    if not d:
        return None
    try:
        datetime.strptime(d, "%Y-%m-%d")
        return d
    except Exception:
        return None

def _rider_num(rider_str):
    """'JA52' → 52, 'DA77' → 77"""
    m_map = {"JA52": 52, "DA77": 77}
    return m_map.get(rider_str, None)

def sessions_to_records(sessions):
    """Convert all_sessions.json entries → sessions_2d rows."""
    records = []
    for s in sessions:
        records.append({
            "round":        _clean(s.get("round")),
            "circuit":      _clean(s.get("circuit")),
            "date":         _parse_date(s.get("date")),
            "session_type": _clean(s.get("session_type")),
            "rider":        _clean(s.get("rider")),
            "run_no":       s.get("run_no", 1),
            "total_laps":   s.get("total_laps", 0),
            "best_lap":     _clean(s.get("best_lap")),
            "best_lap_s":   _clean(s.get("best_lap_s")),
            "avg_lap_s":    _clean(s.get("avg_lap_s")),
            "condition":    _clean(s.get("condition")),
            "air_temp":     _clean(str(s.get("air_temp", "")) if s.get("air_temp") is not None else None),
            "track_temp":   _clean(str(s.get("track_temp", "")) if s.get("track_temp") is not None else None),
            "fork":         _clean(s.get("fork")),
            "fork_spec":    _clean(s.get("fork_spec")),
            "fork_comp":    _clean(s.get("fork_comp")),
            "fork_reb":     _clean(s.get("fork_reb")),
            "shock":        _clean(s.get("shock")),
            "shock_spec":   _clean(s.get("shock_spec")),
            "fork_offset":  _clean(str(s.get("offset", "")) if s.get("offset") is not None else None),
            "tyre_f":       _clean(s.get("tyre_f")),
            "tyre_r":       _clean(s.get("tyre_r")),
            "tyre_f_press": _clean(str(s.get("tyre_f_press", "")) if s.get("tyre_f_press") is not None else None),
            "tyre_r_press": _clean(str(s.get("tyre_r_press", "")) if s.get("tyre_r_press") is not None else None),
            "tyre_f_laps":  _clean(str(s.get("tyre_f_laps", "")) if s.get("tyre_f_laps") is not None else None),
            "tyre_r_laps":  _clean(str(s.get("tyre_r_laps", "")) if s.get("tyre_r_laps") is not None else None),
            "tyre_f_temp":  _clean(str(s.get("tyre_f_temp", "")) if s.get("tyre_f_temp") is not None else None),
            "tyre_r_temp":  _clean(str(s.get("tyre_r_temp", "")) if s.get("tyre_r_temp") is not None else None),
        })
    return records

def laps_to_records(sessions):
    """Convert all_sessions.json laps → lap_times_2d rows."""
    records = []
    for s in sessions:
        for lap in s.get("laps", []):
            records.append({
                "round":        _clean(s.get("round")),
                "circuit":      _clean(s.get("circuit")),
                "date":         _parse_date(s.get("date")),
                "session_type": _clean(s.get("session_type")),
                "rider":        _clean(s.get("rider")),
                "run_no":       s.get("run_no", 1),
                "lap_no":       lap.get("lap_no", 0),
                "lap_time":     _clean(lap.get("lap_time")),
                "lap_time_s":   _clean(lap.get("lap_time_s")),
                "is_outlap":    bool(lap.get("is_outlap", False)),
                "condition":    _clean(s.get("condition")),
                "tyre_f":       _clean(s.get("tyre_f")),
                "tyre_r":       _clean(s.get("tyre_r")),
            })
    return records

# ── Main ──────────────────────────────────────────────────────────
def sync_table(supa_url, key, table, records, label):
    records = dedup_records(table, records)
    total   = len(records)
    n_batch = math.ceil(total / BATCH_SIZE) if total > 0 else 0
    ok_cnt  = 0
    err_cnt = 0

    print(f"\n📤 Syncing {label}: {total} rows in {n_batch} batches...")
    for i in range(n_batch):
        batch = records[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        ok, status = upsert_batch(supa_url, key, table, batch)
        if ok:
            ok_cnt += len(batch)
            print(f"  ✅ Batch {i+1:2d}/{n_batch}: {len(batch)} rows → OK")
        else:
            err_cnt += len(batch)
            print(f"  ❌ Batch {i+1:2d}/{n_batch}: {len(batch)} rows → {status}")

    return ok_cnt, err_cnt


def main():
    print("=" * 55)
    print("  TS24 Puccetti — 2D Data → Supabase Sync")
    print("=" * 55)

    # ── Config
    cfg = load_config()
    supa_url = cfg.get("supabase_url", "").rstrip("/")
    svc_key  = cfg.get("supabase_service_key", "")

    if not supa_url or not svc_key or "PASTE" in svc_key:
        print("\n❌ Supabase設定なし。ts24_config.json を確認してください。")
        return

    # ── Load cache
    if not CACHE_FILE.exists():
        print(f"\n❌ キャッシュ未発見: {CACHE_FILE}")
        print("   先に import_2d_data.command を実行してください。")
        return

    sessions = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    print(f"\n📂 Loaded {len(sessions)} sessions from cache")
    total_laps = sum(len(s.get("laps", [])) for s in sessions)
    print(f"   Total laps: {total_laps}")

    # ── Check tables exist & count existing rows
    print(f"\n🔍 Checking Supabase tables...")
    existing_counts = {}
    for tbl in ["sessions_2d", "lap_times_2d"]:
        cnt = count_table(supa_url, svc_key, tbl)
        existing_counts[tbl] = cnt
        if cnt == -1:
            print(f"  ⚠️  {tbl}: cannot reach (table may not exist yet)")
            print(f"       → Run create_2d_tables.sql in Supabase SQL Editor first!")
        else:
            print(f"  {'⚠️ ' if cnt > 0 else '✅'} {tbl}: {cnt} existing rows")

    # ── Ask whether to clear first if data already exists
    has_existing = any(v > 0 for v in existing_counts.values() if v != -1)
    do_clear = False
    if has_existing:
        print("\n  ⚠️  Tables already contain data.")
        print("  Choose:")
        print("    [c] Clear existing data then insert fresh")
        print("    [u] Upsert (merge / overwrite duplicates)")
        print("    [q] Quit")
        choice = input("  Your choice [c/u/q]: ").strip().lower()
        if choice == "q":
            print("Aborted.")
            return
        do_clear = (choice == "c")
    else:
        print()
        confirm = input("Continue with insert? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    # ── Optional: clear tables before insert
    if do_clear:
        print("\n🗑  Clearing existing data...")
        for tbl in ["lap_times_2d", "sessions_2d"]:
            url_del = f"{supa_url}/rest/v1/{tbl}?id=gte.0"
            headers_del = {
                "apikey":        svc_key,
                "Authorization": f"Bearer {svc_key}",
            }
            req_del = urllib.request.Request(url_del, headers=headers_del, method="DELETE")
            try:
                with urllib.request.urlopen(req_del, timeout=30) as r:
                    print(f"  ✅ {tbl}: cleared")
            except urllib.error.HTTPError as e:
                print(f"  ⚠️  {tbl}: {e.code} {e.read().decode()[:100]}")
            except Exception as e:
                print(f"  ⚠️  {tbl}: {e}")

    # ── Sync sessions_2d
    session_records = sessions_to_records(sessions)
    ok1, err1 = sync_table(supa_url, svc_key, "sessions_2d", session_records, "sessions_2d")

    # ── Sync lap_times_2d
    lap_records = laps_to_records(sessions)
    ok2, err2 = sync_table(supa_url, svc_key, "lap_times_2d", lap_records, "lap_times_2d")

    # ── Summary
    print()
    print("=" * 55)
    print(f"  sessions_2d : {ok1} OK / {err1} errors")
    print(f"  lap_times_2d: {ok2} OK / {err2} errors")
    if err1 == 0 and err2 == 0:
        print("\n  ✅ 2D data sync complete!")
        print("     Streamlit dashboard will reflect the data.")
    else:
        print("\n  ⚠️  Some errors occurred. Check logs above.")
    print("=" * 55)


if __name__ == "__main__":
    main()
