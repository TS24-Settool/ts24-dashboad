#!/usr/bin/env python3
"""
TS24 Supabase Audit — local 正本 DB と Supabase の read-only 整合監査

設計書: reports/supabase_audit_design_20260621.md（§1c 自然キー準拠）
位置づけ: local `02_DATABASE/ts24_unified.db` と Supabase の件数・自然キー差分を
          読み取り専用で比較し、cleanup SQL 案を生成する。Phase 2B には進まない。

━━━ 鉄則（厳守） ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- local は SELECT のみ（SQLite を mode=ro URI で接続）。
- remote は HTTP GET のみ（POST/PUT/PATCH/DELETE を一切持たない）。
- 自動削除・自動 sync をしない。cleanup は .sql 案として出力するだけ（実行は Tatsuki が手動）。
- 書き込んでよいのは reports/ 配下のレポート(.md)と提案(.sql)のみ。
- 比較の local 正本は常に `ts24_unified.db`（TS24 DB Master.xlsx は派生物で対象外）。
- canonical DB / Supabase / Excel / JSON は変更しない。

対象テーブルと自然キー（§1c）:
  race_results  ← race_results        : round_no, circuit, session_type, rider_no, position
  lap_times     ← pdf_lap_times       : round_id, circuit, session_type, rider_num, lap_no
  sessions_2d   ← runs (fork_type!=NULL): round, circuit, session_type, rider, run_no, date
  lap_times_2d  ← laps JOIN runs       : round, circuit, session_type, rider, run_no, lap_no, date

local 投影は sync_to_supabase.py と同一ロジック（同じ源テーブル・別名・WHERE）を複製している。
（sync_to_supabase.py を import するとモジュール実行で実 upsert(POST) が走るため import しない。
  sync 側の投影 SELECT を変更した場合は、本ファイルの AUDIT_SPECS も合わせて更新すること。）

出力:
  reports/supabase_audit_YYYYMMDD.md
  reports/cleanup_proposal_YYYYMMDD.sql   （remote_extra の DELETE 案のみ・手動実行用）

終了コード: 0=差分なし / 2=差分あり / 1=エラー
"""
import argparse
import datetime as _dt
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
DB_PATH     = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
CFG_PATH    = SCRIPT_DIR / "ts24_config.json"
REPORTS_DIR = SCRIPT_DIR / "reports"

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── 監査対象テーブル仕様（sync_to_supabase.py の投影と一致させること） ──
# keys     : Supabase 側カラム名（= local SELECT の別名）。自然キー（§1c）。
# date_keys: ISO 日付として正規化するキー（シーズン跨ぎ衝突回避のため必須）。
# sql      : local 「sync されるべき行集合」を再現する SELECT（生テーブル直比較は偽差分）。
AUDIT_SPECS = [
    {
        "table": "race_results",
        "keys": ["round_no", "circuit", "session_type", "rider_no", "position"],
        "date_keys": [],
        "sql": """
            SELECT round AS round_no, circuit, session_type,
                   rider_num AS rider_no, position
            FROM race_results
        """,
    },
    {
        "table": "lap_times",
        "keys": ["round_id", "circuit", "session_type", "rider_num", "lap_no"],
        "date_keys": [],
        "sql": """
            SELECT round AS round_id, circuit, session_type, rider_num, lap_no
            FROM pdf_lap_times
        """,
    },
    {
        "table": "sessions_2d",
        "keys": ["round", "circuit", "session_type", "rider", "run_no", "date"],
        "date_keys": ["date"],
        "sql": """
            SELECT round, circuit, session AS session_type, rider, run_no, date
            FROM runs
            WHERE fork_type IS NOT NULL
        """,
    },
    {
        "table": "lap_times_2d",
        "keys": ["round", "circuit", "session_type", "rider", "run_no", "lap_no", "date"],
        "date_keys": ["date"],
        "sql": """
            SELECT r.round, r.circuit, r.session AS session_type, r.rider,
                   r.run_no, l.lap_no, r.date
            FROM laps l
            JOIN runs r ON l.run_id = r.run_id
            WHERE l.lap_time_s IS NOT NULL
        """,
    },
]


# ── 正規化（local/remote を apples-to-apples に揃える） ──
def norm(v, is_date=False):
    """キー値を比較用の正規表現へ。None は None のまま（tuple 内 None==None=NULLS NOT DISTINCT）。"""
    if v is None:
        return None
    if is_date:
        # local runs.date='20250221' / remote(date型)='2025-02-21' を数字のみ8桁に統一
        digits = "".join(ch for ch in str(v) if ch.isdigit())
        return digits[:8] if len(digits) >= 8 else (digits or str(v).strip())
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    s = str(v).strip()
    try:                                               # 数値文字列 '77' / '3.0' を '77' / '3' に揃える
        f = float(s)
        return str(int(f)) if f.is_integer() else repr(f)
    except ValueError:
        return s                                       # 'ASSEN' / 'ROUND1' 等はそのまま


def _row_get(row, k):
    # sqlite3.Row も dict も扱えるよう統一
    try:
        return row[k]
    except (KeyError, IndexError):
        return None


def make_tuple(row, spec):
    dk = set(spec["date_keys"])
    return tuple(norm(_row_get(row, k), k in dk) for k in spec["keys"])


# ── local（SELECT only / mode=ro） ──
def local_keyset(conn, spec):
    keyset = set()
    raw = 0
    for row in conn.execute(spec["sql"]):
        raw += 1
        keyset.add(make_tuple(row, spec))
    return keyset, raw


# ── remote（GET only / PostgREST ページング） ──
def remote_rows(base_url, headers, table, keys, timeout, page=1000):
    """自然キー列のみ GET。(rows, total_from_header) を返す。GET 以外は使用しない。"""
    url = f"{base_url}/rest/v1/{table}"
    select = ",".join(keys)
    rows, offset, total = [], 0, None
    while True:
        h = dict(headers)
        h["Range-Unit"] = "items"
        h["Range"] = f"{offset}-{offset + page - 1}"
        h["Prefer"] = "count=exact"
        r = requests.get(url, headers=h, params={"select": select}, timeout=timeout)
        if r.status_code not in (200, 206):
            raise RuntimeError(f"GET {table} -> {r.status_code}: {r.text[:200]}")
        batch = r.json()
        rows.extend(batch)
        cr = r.headers.get("Content-Range", "")
        if total is None and "/" in cr and cr.split("/")[-1].isdigit():
            total = int(cr.split("/")[-1])
        if len(batch) < page:
            break
        offset += page
        if total is not None and offset >= total:
            break
    return rows, total


# ── SQL リテラル（cleanup 提案用・手動実行） ──
def sql_literal(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def emit_delete(table, keys, original):
    conds = [f"{k} IS NOT DISTINCT FROM {sql_literal(original.get(k))}" for k in keys]
    return (f"DELETE FROM {table}\n  WHERE " + "\n    AND ".join(conds) + ";")


def audit_table(conn, base_url, headers, spec, timeout):
    """1テーブルを監査。dict（差分・サンプル・extra原値）を返す。"""
    local_keys, local_raw = local_keyset(conn, spec)
    rrows, remote_total = remote_rows(base_url, headers, spec["table"], spec["keys"], timeout)

    remote_keys = {}
    for rr in rrows:
        t = make_tuple(rr, spec)
        remote_keys.setdefault(t, rr)        # 先勝ちで原値を保持（DELETE 案用）

    rk = set(remote_keys.keys())
    extra = rk - local_keys                  # remote にあって local に無い → cleanup 候補
    missing = local_keys - rk                # local にあって remote に無い → 再 sync 候補（削除しない）
    return {
        "table": spec["table"],
        "keys": spec["keys"],
        "count_local": len(local_keys),
        "local_raw": local_raw,
        "count_remote": len(rk),
        "remote_total": remote_total if remote_total is not None else len(rrows),
        "extra": sorted(extra),
        "missing": sorted(missing),
        "extra_original": [remote_keys[t] for t in sorted(extra)],
    }


# ── レポート出力 ──
def write_report(path, results, date_str, sample, errors):
    L = []
    L.append(f"# Supabase Audit — {date_str}")
    L.append("")
    L.append("read-only 監査（local SELECT / remote GET のみ）。自動削除・自動 sync なし。")
    L.append("")
    L.append(f"- local 正本: `02_DATABASE/ts24_unified.db`")
    L.append(f"- local 投影: `sync_to_supabase.py` と同一ロジック（生テーブル直比較ではない）")
    L.append(f"- 自然キー: CLAUDE.md §1c / NULLS NOT DISTINCT 正規化")
    L.append("")
    L.append("## サマリ")
    L.append("")
    L.append("| table | local | remote(uniq) | remote(total) | remote_extra | missing | remote/local |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for r in results:
        ratio = (r["count_remote"] / r["count_local"]) if r["count_local"] else 0.0
        L.append(f"| {r['table']} | {r['count_local']} | {r['count_remote']} | "
                 f"{r['remote_total']} | {len(r['extra'])} | {len(r['missing'])} | {ratio:.2f} |")
    L.append("")
    if errors:
        L.append("## エラー（監査未完了テーブル）")
        L.append("")
        for t, e in errors:
            L.append(f"- `{t}`: {e}")
        L.append("")
    for r in results:
        L.append(f"## {r['table']}")
        L.append("")
        L.append(f"- 自然キー: `{', '.join(r['keys'])}`")
        L.append(f"- local 投影行(raw): {r['local_raw']} / dedup 後キー: {r['count_local']}")
        L.append(f"- remote uniq キー: {r['count_remote']} / remote 総数(header): {r['remote_total']}")
        L.append(f"- **remote_extra**（online のみ・cleanup 候補）: {len(r['extra'])}")
        L.append(f"- **missing**（local のみ・再 sync 候補／削除しない）: {len(r['missing'])}")
        L.append("")
        if r["extra"]:
            L.append(f"remote_extra サンプル（最大 {sample}）:")
            L.append("")
            L.append("```text")
            for t in r["extra"][:sample]:
                L.append(" | ".join("NULL" if x is None else str(x) for x in t))
            L.append("```")
            L.append("")
        if r["missing"]:
            L.append(f"missing サンプル（最大 {sample}）:")
            L.append("")
            L.append("```text")
            for t in r["missing"][:sample]:
                L.append(" | ".join("NULL" if x is None else str(x) for x in t))
            L.append("```")
            L.append("")
    total_extra = sum(len(r["extra"]) for r in results)
    total_missing = sum(len(r["missing"]) for r in results)
    L.append("## 総評")
    L.append("")
    L.append(f"- remote_extra 合計: {total_extra}"
             f"（cleanup 提案 = `cleanup_proposal_{date_str}.sql`）")
    L.append(f"- missing 合計: {total_missing}（`sync_to_supabase.py` 再実行で解消。**削除ではない**）")
    L.append("- cleanup SQL は提案のみ。SELECT で確認してから Tatsuki が Supabase 上で手動実行する。")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_cleanup_sql(path, results, date_str):
    L = []
    L.append(f"-- Supabase cleanup 提案（remote_extra のみ） — {date_str}")
    L.append("-- 生成: supabase_audit.py（read-only 監査）。")
    L.append("-- ⚠️ 自動実行禁止。各 DELETE の前に必ず SELECT で対象を確認し、Tatsuki が手動実行すること。")
    L.append("-- remote_extra = Supabase にあって local 正本(ts24_unified.db)の sync 投影に存在しない行。")
    L.append("-- NULLS NOT DISTINCT 対応のため IS NOT DISTINCT FROM を使用。")
    L.append("")
    any_rows = False
    for r in results:
        L.append(f"-- ===== {r['table']}: remote_extra {len(r['extra'])} 件 =====")
        if not r["extra"]:
            L.append("-- （差分なし）")
            L.append("")
            continue
        any_rows = True
        keys = r["keys"]
        for orig in r["extra_original"]:
            # 確認用 SELECT（コメント）→ DELETE 案
            sel_conds = " AND ".join(f"{k} IS NOT DISTINCT FROM {sql_literal(orig.get(k))}"
                                     for k in keys)
            L.append(f"-- SELECT * FROM {r['table']} WHERE {sel_conds};")
            L.append(emit_delete(r["table"], keys, orig))
            L.append("")
    if not any_rows:
        L.append("-- 全テーブルで remote_extra なし。削除対象なし。")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="TS24 Supabase read-only audit（削除しない）")
    ap.add_argument("--table", help="単一テーブルのみ監査（既定: 全4テーブル）")
    ap.add_argument("--sample", type=int, default=20, help="レポートのサンプル件数（既定20）")
    ap.add_argument("--no-sql", action="store_true", help="cleanup_proposal.sql を生成しない")
    ap.add_argument("--date", help="出力ファイルの日付 YYYYMMDD（既定: 今日）")
    ap.add_argument("--timeout", type=int, default=60, help="HTTP タイムアウト秒（既定60）")
    args = ap.parse_args()

    date_str = args.date or _dt.date.today().strftime("%Y%m%d")
    specs = [s for s in AUDIT_SPECS if (not args.table or s["table"] == args.table)]
    if not specs:
        print(f"[ERROR] 未知のテーブル: {args.table}", file=sys.stderr)
        return 1

    if not DB_PATH.exists():
        print(f"[ERROR] DB が見つからない: {DB_PATH}", file=sys.stderr)
        return 1
    cfg = json.loads(CFG_PATH.read_text())
    base_url = cfg["supabase_url"].rstrip("/")
    service_key = cfg["supabase_service_key"]
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}

    # SQLite は read-only URI で接続（local への書込を物理的に不可能にする）
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    print("=" * 55)
    print("  TS24 Supabase Audit  (read-only / 削除しない)")
    print("=" * 55)

    results, errors = [], []
    for spec in specs:
        try:
            print(f"[audit] {spec['table']} ...", flush=True)
            res = audit_table(conn, base_url, headers, spec, args.timeout)
            results.append(res)
            print(f"   local={res['count_local']} remote={res['count_remote']} "
                  f"extra={len(res['extra'])} missing={len(res['missing'])}")
        except Exception as e:
            errors.append((spec["table"], str(e)))
            print(f"   [ERROR] {spec['table']}: {e}", file=sys.stderr)
    conn.close()

    REPORTS_DIR.mkdir(exist_ok=True)
    md_path = REPORTS_DIR / f"supabase_audit_{date_str}.md"
    write_report(md_path, results, date_str, args.sample, errors)
    print(f"\n[out] {md_path}")
    if not args.no_sql:
        sql_path = REPORTS_DIR / f"cleanup_proposal_{date_str}.sql"
        write_cleanup_sql(sql_path, results, date_str)
        print(f"[out] {sql_path}")

    total_diff = sum(len(r["extra"]) + len(r["missing"]) for r in results)
    if errors:
        return 1
    return 2 if total_diff else 0


if __name__ == "__main__":
    sys.exit(main())
