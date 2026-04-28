#!/usr/bin/env python3
"""
sync_lap_times.py — SQLite → Supabase lap_times 一括同期
=========================================================
実行方法:
  python3 sync_lap_times.py

処理:
  1. Supabase の lap_times を全削除
  2. SQLite の全 lap_times を 500 行ずつ挿入
=========================================================
"""

import sqlite3
import json
import math
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "ts24_config.json"
DB_PATH     = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_setup.db"
BATCH_SIZE  = 500

# id列は除外（Supabaseが自動採番）
EXCLUDE_COLS = {"id"}

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def supa_req(method, url, key, data=None, extra_headers=None):
    headers = {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }
    if extra_headers:
        headers.update(extra_headers)
    body = json.dumps(data).encode() if data is not None else None
    req  = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:300]
        return False, f"HTTP {e.code}: {msg}"
    except Exception as e:
        return False, str(e)

def delete_all(supa_url, key):
    """Supabase の lap_times を全削除"""
    url = f"{supa_url}/rest/v1/lap_times?id=gte.0"
    ok, status = supa_req("DELETE", url, key)
    return ok, status

def insert_batch(supa_url, key, rows):
    url = f"{supa_url}/rest/v1/lap_times"
    return supa_req("POST", url, key, rows)

def main():
    cfg = load_config()
    supa_url = cfg.get("supabase_url", "")
    svc_key  = cfg.get("supabase_service_key", "")

    if not supa_url or not svc_key or svc_key == "PASTE_SERVICE_ROLE_KEY_HERE":
        print("❌ Supabase設定なし。ts24_config.json を確認してください。")
        return

    if not DB_PATH.exists():
        print(f"❌ DB未発見: {DB_PATH}")
        return

    # ── SQLite 読み込み ──
    print(f"📂 SQLite 読み込み中: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    all_rows_raw = conn.execute(
        "SELECT * FROM lap_times ORDER BY round_id, session_type, rider_num, lap_no"
    ).fetchall()
    conn.close()

    col_names = [k for k in all_rows_raw[0].keys() if k not in EXCLUDE_COLS]

    def clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    rows = [
        {k: clean(row[k]) for k in col_names}
        for row in all_rows_raw
    ]
    print(f"   {len(rows)} 行を読み込みました\n")

    # ── Supabase 既存データ削除 ──
    print("🗑  Supabase の既存 lap_times を削除中...")
    ok, status = delete_all(supa_url, svc_key)
    if ok:
        print("   ✅ 削除完了\n")
    else:
        print(f"   ⚠️  削除エラー: {status}")
        print("   （既存データがない場合は正常です。続行します）\n")

    # ── バッチ挿入 ──
    total   = len(rows)
    n_batch = math.ceil(total / BATCH_SIZE)
    ok_count  = 0
    err_count = 0

    print(f"🔄 挿入開始: {total} 行 / {n_batch} バッチ")
    for i in range(n_batch):
        batch = rows[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
        ok, status = insert_batch(supa_url, svc_key, batch)
        if ok:
            ok_count += len(batch)
            print(f"  ✅ バッチ {i+1:2d}/{n_batch}: {len(batch)} 行 → OK")
        else:
            err_count += len(batch)
            print(f"  ❌ バッチ {i+1:2d}/{n_batch}: {len(batch)} 行 → {status}")

    print()
    print("=" * 50)
    print(f"完了: {ok_count} 行成功 / {err_count} 行エラー")
    if err_count == 0:
        print("✅ lap_times 同期完了！Streamlit Cloud に反映されます。")
    else:
        print("⚠️  一部エラーがあります。ログを確認してください。")

if __name__ == "__main__":
    main()
