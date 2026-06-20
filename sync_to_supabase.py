#!/usr/bin/env python3
"""
TS24 Supabase Sync — SQLite → Supabase upsert
新スキーマ対応版 (2026-06-18 再構築後)

同期対象（local ts24_unified.db → online）:
  race_results   ← race_results              (公式リザルト / v2 PDF順位)
  lap_times      ← pdf_lap_times             (PDFラップ明細)
  sessions_2d    ← runs                      (2D/MES セットアップ単位)
  lap_times_2d   ← laps (+runs)              (2D/MES ラップ単位)

⚠️ 再構築でスキーマが変更されたため、旧 sync の以下を廃止/修正:
  - sessions      : 源テーブル ts24_sessions が廃止 → 同期対象から除外
  - chassis_geometry : テーブル廃止 → 同期対象から除外
  - runs の列名修正: f_tos_spr → f_tos_spring、runs.data_scope は廃止 →
    runs/laps 由来は data_scope を 'TS24_PRIVATE' リテラルで付与。

conflict_col（= Supabase 側 UNIQUE INDEX。自然キー upsert で idempotent）:
  race_results : (round_no, circuit, session_type, rider_no, position)
  lap_times    : (round_id, circuit, session_type, rider_num, lap_no)
  sessions_2d  : (round, circuit, session_type, rider, run_no, date)
  lap_times_2d : (round, circuit, session_type, rider, run_no, lap_no, date)
  ※ date を含める理由: 同一 round 番号がシーズンを跨いで再利用される
    (例 ROUND1 PHILLIP ISLAND が 2025/2026 両方に存在)。date 無しだと
    natural key が衝突し ON CONFLICT が「同一行を2度更新」エラー(21000)になる。
"""
import json, sqlite3
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DB_PATH    = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
CFG_PATH   = SCRIPT_DIR / "ts24_config.json"

with open(CFG_PATH) as f:
    cfg = json.load(f)

SUPABASE_URL = cfg["supabase_url"]
SERVICE_KEY  = cfg["supabase_service_key"]

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

BASE_HEADERS = {
    "apikey":        SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=merge-duplicates,return=minimal",
}


def to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def to_int(v):
    if v is None:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def upsert(table: str, rows: list, conflict_col: str = None,
           batch: int = 500) -> int:
    """Supabase REST upsert。conflict_col 指定時は ?on_conflict= を使用。"""
    if not rows:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if conflict_col:
        url += f"?on_conflict={conflict_col}"
    total = 0
    errors = 0
    for i in range(0, len(rows), batch):
        chunk = rows[i:i+batch]
        r = requests.post(url, headers=BASE_HEADERS, json=chunk, timeout=60)
        if r.status_code not in (200, 201):
            errors += 1
            print(f"  [ERROR] {table} batch {i//batch+1}: "
                  f"{r.status_code} {r.text[:200]}")
            if errors >= 3:
                print(f"  エラーが続くため {table} の同期を中断")
                break
        else:
            total += len(chunk)
            print(f"  [{table}] batch {i//batch+1}: {len(chunk)} rows OK")
    return total


def has_table(conn, name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def cols_of(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("=" * 55)
print("  TS24 Supabase Sync  v3 (新スキーマ)")
print("=" * 55)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. race_results
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[1/4] race_results 同期中...")
scope_rr = "data_scope" if "data_scope" in cols_of(conn, "race_results") else "'TS24_PRIVATE'"
rows = conn.execute(f"""
    SELECT
        round        AS round_no,
        circuit,
        session_type,
        date         AS event_date,
        position,
        rider_num    AS rider_no,
        rider_name,
        laps,
        gap          AS gap_to_top,
        best_lap_s   AS best_lap,
        COALESCE({scope_rr}, 'TS24_PRIVATE') AS data_scope
    FROM race_results
""").fetchall()
rr = []
for row in rows:
    d = dict(row)
    d['gap_to_top'] = to_float(d.get('gap_to_top'))
    d['best_lap']   = to_float(d.get('best_lap'))
    rr.append(d)
n = upsert("race_results", rr,
           conflict_col="round_no,circuit,session_type,rider_no,position", batch=200)
print(f"  → {n} / {len(rr)} 行完了")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. lap_times  (←SQLite pdf_lap_times)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[2/4] lap_times 同期中...")
scope_pl = "data_scope" if "data_scope" in cols_of(conn, "pdf_lap_times") else "'TS24_PRIVATE'"
rows = conn.execute(f"""
    SELECT
        round        AS round_id,
        circuit,
        session_type,
        rider_num,
        rider_name,
        lap_no,
        seg1, seg2, seg3, seg4,
        lap_time_s   AS lap_time,
        speed,
        COALESCE({scope_pl}, 'TS24_PRIVATE') AS data_scope
    FROM pdf_lap_times
""").fetchall()
lt = [dict(r) for r in rows]
n = upsert("lap_times", lt,
           conflict_col="round_id,circuit,session_type,rider_num,lap_no", batch=500)
print(f"  → {n} / {len(lt)} 行完了")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. sessions_2d  (←SQLite runs — 2D/MES セットアップ単位)
#   列名修正: fork_spec ← f_tos_spring (旧 f_tos_spr 誤記)、data_scope はリテラル
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[3/4] sessions_2d 同期中...")
rows = conn.execute("""
    SELECT
        round,
        circuit,
        session              AS session_type,
        rider,
        date,
        run_no,
        fork_type            AS fork,
        f_set_c              AS fork_comp,
        f_set_r              AS fork_reb,
        CAST(f_offset AS TEXT)||'/'||CAST(f_offset2 AS TEXT) AS fork_offset,
        f_tos_spring         AS fork_spec,
        shock_type           AS shock,
        r_set_c||'/'||r_set_r AS shock_spec,
        tyre_front           AS tyre_f,
        tyre_rear            AS tyre_r,
        track_temp,
        air_temp,
        perf_best_lap        AS best_lap,
        best_lap_s,
        'TS24_PRIVATE'       AS data_scope
    FROM runs
    WHERE fork_type IS NOT NULL
""").fetchall()
S2D_INT_COLS = {'fork_comp', 'fork_reb', 'run_no'}
s2d = []
for row in rows:
    d = dict(row)
    for col in S2D_INT_COLS:
        d[col] = to_int(d.get(col))
    d['best_lap']   = to_float(d.get('best_lap'))
    d['best_lap_s'] = to_float(d.get('best_lap_s'))
    s2d.append(d)
n = upsert("sessions_2d", s2d,
           conflict_col="round,circuit,session_type,rider,run_no,date", batch=200)
print(f"  → {n} / {len(s2d)} 行完了")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. lap_times_2d  (←SQLite laps — 2D/MES ラップ単位)
#   data_scope はリテラル(runs に列なし)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n[4/4] lap_times_2d 同期中...")
rows = conn.execute("""
    SELECT
        r.round,
        r.circuit,
        r.session            AS session_type,
        r.rider,
        r.date,
        r.run_no,
        l.lap_no,
        l.lap_time_s         AS lap_time,
        l.lap_time_s,
        l.is_outlap,
        r.tyre_front         AS tyre_f,
        r.tyre_rear          AS tyre_r,
        'TS24_PRIVATE'       AS data_scope
    FROM laps l
    JOIN runs r ON l.run_id = r.run_id
    WHERE l.lap_time_s IS NOT NULL
""").fetchall()
lt2d = [dict(r) for r in rows]
n = upsert("lap_times_2d", lt2d,
           conflict_col="round,circuit,session_type,rider,run_no,lap_no,date", batch=500)
print(f"  → {n} / {len(lt2d)} 行完了")

conn.close()
print("\n" + "=" * 55)
print("  完了!  (sessions / chassis_geometry は新スキーマでは同期対象外)")
print("=" * 55)
