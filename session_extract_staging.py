#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
session_extract_staging.py — Race Weekend Session Extraction Staging（既定 dry-run）
=====================================================================================
設計: CLAUDE.md §50/§52 / `reports/race_weekend_session_staging_readiness_20260706.md`
DDL : `reports/race_weekend_session_staging_ddl_20260706.sql`（固定・verbatim 実行）
GO  : `Session staging implementation GO`（2026-07-06 受領）

Race Weekend 中にセッション直後の 2D outing だけを抽出し、正本DB内の provisional 3テーブル
（runs_provisional / laps_provisional / lap_suspension_provisional）へ staging する。

安全原則:
  - **既定は dry-run**（`--apply` 無しでは正本DBを `mode=ro` でしか開かない）。
  - 業務6テーブル（runs/laps/lap_suspension/race_results/pdf_lap_times/pdf_lap_times_v2_staging）
    は一切変更しない。apply 時は 1トランザクション内で before==after を assert（違反→rollback・exit 3）。
  - 2D パーサは二重実装しない: `build_master_db.py` の本番関数
    （discover_outings/gated_outings/extract_outing/session_canon_2d/circuit_from_*）を import 再利用。
    唯一の薄い再実装 = is_outlap の provisional 向けラッパ（readiness §2e）。
  - run_id = PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n} / lap_id = {run_id}_L{lap_no}
  - INSERT OR REPLACE（自然キー run_id/lap_id）= 冪等・再実行安全。
  - WF 6列 + lap_susF_min、runs の setup 33列 + comment は NULL のまま（0 代用禁止・readiness §3b）。

使い方:
  python3 session_extract_staging.py --event 20260612-ROUND7-JA52                # dry-run（全 session）
  python3 session_extract_staging.py --event 20260612-ROUND7-JA52 --session FP   # dry-run（FP のみ）
  python3 session_extract_staging.py --event 20260612-ROUND7-JA52 --session FP --apply

Event Control Plane 統合（§75 B-3・2026-07-13・後方互換）:
  - 対象DBに event_manifest テーブルがあり active manifest が存在する場合:
      * --apply で --required-round 省略時は active manifest の round を自動採用。
      * --apply の --event は active manifest の event_key と一致必須（不一致=exit 4）。
      * run_no は **outing stem 末尾の連番から決定論採番**（バッチ相対採番を廃止・P0-2）。
        既存 provisional/canonical run_id との衝突は content hash 照合し、
        同名同内容=冪等 no-op / 同名異内容=明示 conflict FAIL（silent overwrite 禁止）。
  - manifest 未導入DB（テーブル無し）ではすべて従来動作（explicit フラグ運用は不変）。
    ただし **--apply で --required-round が解決できない場合は exit 4**（P0-1 CLI 穴の閉鎖）。
  - --deterministic-runid で manifest 無しでも決定論採番を強制可能（検証用）。
  - apply の backup は WAL-safe（db + -wal + -shm）。event_state_ledger が存在すれば
    apply_started / apply_committed / failed の耐久 receipt を追記（テーブル無し=従来動作）。

exit code: 0=成功 / 1=候補なし・事前チェック失敗 / 2=quality gate FAIL あり（隔離・部分成功）/
           3=apply 中 業務テーブル assert 違反→rollback /
           4=guard 違反（書込前に中止・--apply に --event 必須 / --required-round 不一致 /
             active manifest 不整合・required round 解決不能）
"""
from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
CANON_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
REPORTS_DIR = SCRIPT_DIR / "reports"
DDL_FILE = REPORTS_DIR / "race_weekend_session_staging_ddl_20260706.sql"
BACKUP_ROOT = DATA_ROOT / "02_DATABASE"

BUSINESS_TABLES = ["runs", "laps", "lap_suspension", "race_results",
                   "pdf_lap_times", "pdf_lap_times_v2_staging"]
PROV_TABLES = ["runs_provisional", "laps_provisional", "lap_suspension_provisional"]

# ── 本番抽出関数の import（二重実装禁止・readiness §2） ─────────────────────
_spec = importlib.util.spec_from_file_location("bmd", SCRIPT_DIR / "build_master_db.py")
bmd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bmd)

EVENT_RE = bmd.EVENT_RE
SETUP_COLS = bmd.SETUP_COLS                    # 33 setup 列（provisional では全 NULL）
PHASE_SPD_NEW_COLS = bmd.PHASE_SPD_NEW_COLS    # §44 の 22列
KNOWN_SESSIONS = {"FP", "QP", "WUP1", "WUP2", "RACE1", "RACE2", "SP"}
TEST_SESSION_RE = re.compile(r"^TEST\d+_DAY\d+$")

NOW_ISO = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
ANALYSIS_RUN_ID = f"{NOW_ISO}_session_extract_staging"


def log(msg: str):
    print(f"[STAGE] {msg}")


def ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ── Event Control Plane 統合（§75 B-3・後方互換: テーブル無し=従来動作） ──────

_STEM_NUM_RE = re.compile(r"(\d+)\s*$")


def deterministic_run_no(base: str):
    """outing stem 末尾の連番 → 決定論 run_no（例 FP-JA52-02 → 2 / SP-#77-03 → 3）。
    連番が無い stem は None（fail-closed: 決定論採番不能=conflict 扱い）。"""
    m = _STEM_NUM_RE.search(base or "")
    return int(m.group(1)) if m else None


def _load_evm():
    """event_manifest モジュール（同ディレクトリ）を遅延 import。"""
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("event_manifest", SCRIPT_DIR / "event_manifest.py")
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_manifest_context(args) -> dict:
    """対象DBの active event manifest を read-only で解決。
    返り値: dict(manifest=dict|None, error=str|None, evm=module|None)
      - event control テーブル無し / active 0件 → manifest=None（従来動作）
      - active 複数 / DB ミラー改竄 → error（apply は fail-closed で exit 4）"""
    ctx = dict(manifest=None, error=None, evm=None)
    if not (SCRIPT_DIR / "event_manifest.py").exists():
        return ctx
    try:
        evm = _load_evm()
        ctx["evm"] = evm
    except Exception as e:
        ctx["error"] = f"event_manifest module load failed: {e}"
        return ctx
    try:
        conn = ro(Path(args.db))
    except Exception:
        return ctx
    try:
        if not evm.tables_exist(conn):
            return ctx
        n = conn.execute("SELECT COUNT(*) FROM event_manifest WHERE status='active'").fetchone()[0]
        if n == 0:
            return ctx
        ctx["manifest"] = evm.get_active_manifest(conn)
    except Exception as e:
        ctx["error"] = str(e)
    finally:
        conn.close()
    return ctx


def ledger_receipt(args, ctx: dict, event_key: str, state: str, reason: str, receipt: dict):
    """event_state_ledger への耐久 receipt（短命コネクション・即 commit）。
    テーブル未作成 / モジュール不在なら何もしない（後方互換）。失敗しても apply を壊さない。"""
    evm = ctx.get("evm") if ctx else None
    if evm is None:
        return None
    m = ctx.get("manifest") or {}
    try:
        return evm.ledger_append_durable(
            args.db, event_key, scope="event", scope_id=args.session or None,
            state=state, reason=reason, actor="session_extract_staging.py",
            analysis_run_id=ANALYSIS_RUN_ID,
            manifest_version=m.get("manifest_version"),
            manifest_content_hash=m.get("content_hash"),
            receipt=receipt)
    except Exception as e:
        log(f"⚠ ledger 記録失敗（処理は継続）: {e}")
        return None


def business_counts(conn: sqlite3.Connection) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_TABLES}


def provisional_counts(conn: sqlite3.Connection) -> dict:
    out = {}
    for t in PROV_TABLES:
        try:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            out[t] = None  # 未作成
    return out


# ── 入力: import_queue pending 2d_extract（registry JOIN） ───────────────────

def load_queue_candidates(conn: sqlite3.Connection, args) -> list[dict]:
    statuses = ["pending"] + (["awaiting_gate"] if args.include_awaiting else [])
    ph = ",".join("?" for _ in statuses)
    rows = conn.execute(f"""
        SELECT q.queue_id, q.file_id, q.file_path, q.status AS q_status,
               r.sha256, r.rider AS reg_rider, r.round AS reg_round, r.status AS reg_status
          FROM import_queue q JOIN source_file_registry r ON q.file_id = r.file_id
         WHERE q.target_kind='2d_extract' AND q.status IN ({ph})
         ORDER BY q.file_path""", statuses).fetchall()
    cand = []
    for r in rows:
        p = Path(r["file_path"])
        # イベントフォルダ = DATA 2D 直下の EVENT_RE マッチ
        ev_dir = None
        for parent in p.parents:
            if EVENT_RE.match(parent.name):
                ev_dir = parent
                break
        if ev_dir is None:
            continue
        if args.event and ev_dir.name != args.event:
            continue
        if args.source_file and args.source_file not in str(p):
            continue
        cand.append(dict(queue_id=r["queue_id"], file_id=r["file_id"], ddd_path=str(p),
                         sha256=r["sha256"], reg_rider=r["reg_rider"], event_dir=ev_dir))
    return cand


# ── is_outlap 薄ラッパ（readiness §2e・本番 _recompute_is_outlap と同値の①②③＋条件付き④）──

def circuit_p10_ref(conn: sqlite3.Connection, circuit: str):
    """正本 laps からサーキット基準 P10。該当 circuit の canonical laps が無ければ None（④ skip）。"""
    tl = bmd.TRACK_M.get(circuit)
    floor = tl / (bmd.MAX_AVG_KMH / 3.6) if tl else None
    lst = []
    for (lt,) in conn.execute(
            "SELECT l.lap_time_s FROM laps l JOIN runs r USING(run_id) "
            "WHERE r.circuit=? AND l.lap_time_s IS NOT NULL", (circuit,)):
        if floor is not None and lt < floor:
            continue
        lst.append(lt)
    if not lst:
        return None
    lst.sort()
    return lst[max(0, len(lst) // 10)]


def recompute_is_outlap_provisional(laps: list[dict], circuit: str, mes_file: str, ref):
    """laps = [{lap_time_s, ...}]（1 outing=1 run 分）。判定式は本番 _recompute_is_outlap と同値。
    ① 物理下限 stray（TRACK_M/200km/h） ② GRID/FORMATION（mes_file） ③ 相対 run_min×1.15
    ④ 単一ラップ上限ガード（circuit P10×1.25）— ref=None（canonical 0 laps）なら本番同様 silent skip。"""
    tl = bmd.TRACK_M.get(circuit)
    floor = tl / (bmd.MAX_AVG_KMH / 3.6) if tl else None
    is_grid = "GRID" in mes_file.upper() or "FORMATION" in mes_file.upper()
    flags = {}
    clean = []
    for l in laps:
        t = l["lap_time_s"]
        if t is None:
            flags[l["lap_no"]] = 1
            continue
        if (floor is not None and t < floor) or is_grid:
            flags[l["lap_no"]] = 1
        else:
            clean.append((l["lap_no"], t))
    if clean:
        mn = min(t for _, t in clean)
        for ln, t in clean:
            out = 1 if t > mn * 1.15 else 0
            if len(clean) == 1 and ref and t > ref * 1.25:
                out = 1
            flags[ln] = out
    return flags


# ── Quality gate（readiness §5・outing 単位・FAIL は隔離） ────────────────────

def quality_gate(o: dict, existing_hashes: set, existing_run_ids: set,
                 batch_run_ids: set, batch_lap_ids: set) -> list[tuple]:
    """returns [(check_name, result, detail)]。o は extraction 済み outing dict。"""
    checks = []
    res = o.get("result")
    base_u = o["base"].upper()

    # 1) lap count（EngineWarmup は skip 記録＝gate 対象外で呼び出し側処理）
    nlaps = res["nlaps"] if res else 0
    checks.append(("stage_lap_count", "PASS" if nlaps > 0 else "FAIL", f"valid laps={nlaps}"))
    if nlaps == 0:
        return checks

    # 2) rider / session / circuit 推定
    ok2 = True
    det2 = []
    if o["reg_rider"] and o["ev_rider"] and o["reg_rider"] != o["ev_rider"]:
        ok2 = False
        det2.append(f"rider mismatch reg={o['reg_rider']} folder={o['ev_rider']}")
    sess = o["session"]
    if not (sess in KNOWN_SESSIONS or TEST_SESSION_RE.match(sess or "")):
        ok2 = False
        det2.append(f"unknown session prefix -> {sess!r}")
    if not o["circuit"]:
        ok2 = False
        det2.append("circuit inference empty")
    checks.append(("stage_inference", "PASS" if ok2 else "FAIL",
                   "; ".join(det2) or f"rider={o['ev_rider']} session={sess} circuit={o['circuit']}"))

    # 3) lap_time 分布（is_outlap 除外後 best が 60–300s 外=FAIL、個別レンジ外=WARNING）
    valid = [l for l in res["laps"] if o["outlap_flags"].get(l["lap_no"], 0) == 0]
    best = min((l["lap_time_s"] for l in valid), default=None)
    out_of_range = [l["lap_no"] for l in valid if not (60.0 <= l["lap_time_s"] <= 300.0)]
    if best is None or not (60.0 <= best <= 300.0):
        checks.append(("stage_lap_time_range", "FAIL", f"best={best} outside 60-300s"))
    elif out_of_range:
        checks.append(("stage_lap_time_range", "WARNING",
                       f"best={best} OK / laps outside 60-300s: {out_of_range}"))
    else:
        checks.append(("stage_lap_time_range", "PASS", f"best={best} / {len(valid)} valid laps"))

    # 4) braking/apex/exit 成立率
    rates = {}
    for area in ("FULL_BRAKING", "MID_CORNER", "CORNER_EXIT"):
        n_pos = sum(1 for l in res["laps"] if l["metrics"][area]["n"] > 0)
        rates[area] = n_pos / len(res["laps"])
    det4 = " ".join(f"{a}={r:.0%}" for a, r in rates.items())
    if all(r == 0 for r in rates.values()):
        checks.append(("stage_area_rates", "FAIL", "all areas 0%: " + det4))
    elif any(r == 0 for r in rates.values()):
        checks.append(("stage_area_rates", "WARNING", det4))
    else:
        checks.append(("stage_area_rates", "PASS", det4))

    # 5) §44 22列: 存在必須（FAIL）・非NULL成立率は WARNING 記録のみ（Exit 系 ~46% NULL は本質）
    bad_len = [l["lap_no"] for l in res["laps"]
               if len(l.get("phase_spd_matrix") or ()) != len(PHASE_SPD_NEW_COLS)]
    if bad_len:
        checks.append(("stage_phase22_exists", "FAIL", f"matrix len != 22 on laps {bad_len}"))
    else:
        tot = len(res["laps"]) * len(PHASE_SPD_NEW_COLS)
        nn = sum(1 for l in res["laps"] for v in l["phase_spd_matrix"] if v is not None)
        checks.append(("stage_phase22_exists", "PASS", f"22/22 cols; non-null {nn}/{tot} ({nn/tot:.0%})"))
        checks.append(("stage_phase22_fill", "WARNING" if nn < tot else "PASS",
                       f"non-null rate {nn/tot:.0%}（Exit 系の構造 NULL は本質・情報記録のみ）"))

    # 6) zero≠NULL ガード（n<5/n<10 セルに 0.0 が入っていない。ph12_rear0_s の 0.0 は実測値=許容）
    zero_cells = []
    for l in res["laps"]:
        for k in ("brk_f_dive_spd_avg", "brk_f_dive_spd_peak", "ce_r_spd_avg", "ce_r_spd_peak"):
            if l.get(k) == 0.0:
                zero_cells.append((l["lap_no"], k))
        for k, v in zip(PHASE_SPD_NEW_COLS, l.get("phase_spd_matrix") or ()):
            if v == 0.0:
                zero_cells.append((l["lap_no"], k))
    checks.append(("stage_zero_null_guard", "FAIL" if zero_cells else "PASS",
                   f"0.0 cells={zero_cells[:10]}" if zero_cells else "no 0.0 in guarded cells"))

    # 7) PROV run_id/lap_id 重複（バッチ内=FAIL・既存 provisional は REPLACE 対象として報告のみ）
    dup_batch = o["run_id"] in batch_run_ids or any(lid in batch_lap_ids for lid in o["lap_ids"])
    exists = o["run_id"] in existing_run_ids
    checks.append(("stage_prov_id_dup", "FAIL" if dup_batch else "PASS",
                   ("batch duplicate!" if dup_batch else "no batch dup")
                   + (f" / run_id exists in provisional (INSERT OR REPLACE)" if exists else "")))

    # 8) source hash 冪等
    if o["sha256"] and o["sha256"] in existing_hashes:
        checks.append(("stage_hash_idempotent", "PASS",
                       "same source_manifest_hash already ingested → REPLACE（行は増えない）"))
    else:
        checks.append(("stage_hash_idempotent", "PASS", "new source_manifest_hash"))
    return checks


def gate_status(checks: list[tuple]) -> str:
    if any(c[1] == "FAIL" for c in checks):
        return "FAIL"
    if any(c[1] == "WARNING" for c in checks):
        return "WARNING"
    return "PASS"


# ── 行組み立て（readiness §2c/§3b） ──────────────────────────────────────────

def _fmt_lap(s):
    if s is None:
        return None
    m = int(s // 60)
    return f"{m}:{s - 60 * m:06.3f}"


RUNS_PROV_COLS = (["run_id", "rider", "circuit", "round", "session", "run_no", "date",
                   "event_id", "source", "has_2d", "n_laps", "best_lap_s", "perf_best_lap",
                   "comment"] + SETUP_COLS + ["updated_at", "created_at"])
LAPS_PROV_COLS = ["lap_id", "run_id", "lap_no", "lap_time_s", "susf_mean", "susf_max",
                  "susr_mean", "mes_file", "f_dive_spd", "f_reb_spd", "r_dive_spd",
                  "r_reb_spd", "rear_light_brk", "is_outlap", "created_at", "updated_at"]
LS_PROV_COLS = (["lap_id", "run_id", "round", "circuit", "session", "rider", "run_no",
                 "lap_no", "date", "lap_time_s", "lap_time_fmt",
                 "apex_count", "apex_spd_avg", "apex_susF_avg", "apex_susR_avg",
                 "wf_f_apex_n", "wf_r_apex_n",
                 "brk_count", "brk_spd_avg", "brk_susF_avg", "brk_susR_avg",
                 "wf_f_brk_n", "wf_r_brk_n",
                 "fullbrk_count", "fullbrk_susF", "fullbrk_susR",
                 "ce_count", "ce_spd_avg", "ce_susF_avg", "ce_susR_avg",
                 "wf_f_ce_n", "wf_r_ce_n",
                 "f_dive_spd", "f_reb_spd", "r_dive_spd", "r_reb_spd", "rear_light_brk",
                 "lap_susF_mean", "lap_susF_min", "lap_susF_max", "lap_susR_mean",
                 "updated_at",
                 "brk_f_dive_spd_avg", "brk_f_dive_spd_peak",
                 "ce_r_spd_avg", "ce_r_spd_peak", "ph12_rear0_s"]
                + PHASE_SPD_NEW_COLS)
PROV_META_COLS = ["data_stage", "intake_ts", "source_manifest_hash", "source_file_path",
                  "provisional_event_key", "quality_status"]


def build_rows(o: dict) -> dict:
    """1 outing → runs/laps/lap_suspension provisional 行。WF 6列・lap_susF_min・setup 33列は NULL。"""
    res = o["result"]
    prov = ("provisional", NOW_ISO, o["sha256"], str(o["mes_path"]), o["event_key"], o["quality_status"])
    valid = [l for l in res["laps"] if o["outlap_flags"].get(l["lap_no"], 0) == 0]
    best = min((l["lap_time_s"] for l in valid), default=None)
    run_row = ([o["run_id"], o["ev_rider"], o["circuit"], o["round"], o["session"],
                o["run_no"], o["date"], o["event_key"], "2D_PROVISIONAL", 1,
                len(res["laps"]), best, best, None]
               + [None] * len(SETUP_COLS) + [NOW_ISO, NOW_ISO]) + list(prov)
    lap_rows, ls_rows = [], []
    mes_file = f"{o['base']}.MES"
    for l in res["laps"]:
        lap_id = f"{o['run_id']}_L{l['lap_no']}"
        flg = o["outlap_flags"].get(l["lap_no"], 0)
        lap_rows.append((lap_id, o["run_id"], l["lap_no"], l["lap_time_s"],
                         l["susf_mean"], l["susf_max"], l["susr_mean"], mes_file,
                         l["f_dive_spd"], l["f_reb_spd"], l["r_dive_spd"], l["r_reb_spd"],
                         l["rear_light_brk"], flg, NOW_ISO, NOW_ISO) + prov)
        mc, fb, ce = (l["metrics"]["MID_CORNER"], l["metrics"]["FULL_BRAKING"],
                      l["metrics"]["CORNER_EXIT"])
        ls_rows.append((lap_id, o["run_id"], o["round"], o["circuit"], o["session"],
                        o["ev_rider"], o["run_no"], l["lap_no"], o["date"],
                        l["lap_time_s"], _fmt_lap(l["lap_time_s"]),
                        mc["n"], mc["speed"], mc["susf"], mc["susr"], None, None,   # wf NULL
                        fb["n"], fb["speed"], fb["susf"], fb["susr"], None, None,   # wf NULL
                        fb["n"], fb["susf"], fb["susr"],
                        ce["n"], ce["speed"], ce["susf"], ce["susr"], None, None,   # wf NULL
                        l["f_dive_spd"], l["f_reb_spd"], l["r_dive_spd"], l["r_reb_spd"],
                        l["rear_light_brk"],
                        l["susf_mean"], None, l["susf_max"], l["susr_mean"],       # lap_susF_min NULL
                        NOW_ISO,
                        l["brk_f_dive_spd_avg"], l["brk_f_dive_spd_peak"],
                        l["ce_r_spd_avg"], l["ce_r_spd_peak"], l["ph12_rear0_s"])
                       + tuple(l["phase_spd_matrix"]) + prov)
    return dict(run=run_row, laps=lap_rows, ls=ls_rows)


def insert_stmt(table: str, cols: list[str]) -> str:
    allc = cols + PROV_META_COLS
    return (f"INSERT OR REPLACE INTO {table} ({','.join(allc)}) "
            f"VALUES ({','.join('?' * len(allc))})")


# ── パイプライン本体 ─────────────────────────────────────────────────────────

def run_pipeline(args, det_ctx: dict | None = None) -> dict:
    """候補収集→抽出→gate。DB は read-only でしか触らない（apply は呼び出し側）。
    det_ctx（§75 B-3）: dict(manifest=..., deterministic=bool)。None/deterministic=False なら
    従来動作（バッチ相対 run_no 採番）と完全同一。"""
    deterministic = bool(det_ctx and det_ctx.get("deterministic"))
    manifest = det_ctx.get("manifest") if det_ctx else None
    conn = ro(Path(args.db))
    before_biz = business_counts(conn)
    before_prov = provisional_counts(conn)
    cands = load_queue_candidates(conn, args)
    if not cands:
        conn.close()
        return dict(status="no_candidates", before_biz=before_biz, before_prov=before_prov,
                    outings=[], skipped=[], unmatched=[])

    # イベント単位に整理
    by_event = defaultdict(list)
    for c in cands:
        by_event[c["event_dir"]].append(c)

    # 既存 provisional の hash/run_id（冪等チェック用）
    existing_hashes, existing_run_ids = set(), set()
    if before_prov["runs_provisional"] is not None:
        existing_hashes = {r[0] for r in conn.execute(
            "SELECT DISTINCT source_manifest_hash FROM runs_provisional") if r[0]}
        existing_run_ids = {r[0] for r in conn.execute("SELECT run_id FROM runs_provisional")}

    # 決定論モード: 既存 provisional の run_id→(hash, stem) と canonical run_id（衝突検査 P0-2）
    existing_prov_map, canonical_run_ids = {}, set()
    if deterministic:
        if before_prov["runs_provisional"] is not None:
            existing_prov_map = {
                r[0]: (r[1], Path(r[2] or "").name)
                for r in conn.execute("SELECT run_id, source_manifest_hash, source_file_path "
                                      "FROM runs_provisional")}
        canonical_run_ids = {r[0] for r in conn.execute("SELECT run_id FROM runs")}

    outings_all, skipped, unmatched = [], [], []
    for ev_dir, ev_cands in sorted(by_event.items()):
        m = EVENT_RE.match(ev_dir.name)
        date, rnd, rider = m.group(1), m.group(2).upper(), m.group(3).upper().replace("JA25", "JA52")
        report = bmd._find_report(rider, rnd, date)
        circ_rep = bmd.circuit_canon(bmd.circuit_from_report(report)) if report else ""
        circ_2d = bmd.circuit_canon(bmd.circuit_from_2d(ev_dir))
        circuit = circ_rep or circ_2d          # 本番 event_circuit と同順（Report 優先・.line fallback）
        log(f"event {ev_dir.name}: circuit={circuit} (report={circ_rep or '-'} / .line={circ_2d or '-'}) "
            f"queue candidates={len(ev_cands)}")
        p10 = circuit_p10_ref(conn, circuit)
        log(f"  circuit P10 ref = {p10}（None は本番同様 ④ガード skip）")

        # 本番 gated_outings（ev dict は 'dir' キーのみ使用）
        gated = bmd.gated_outings({"dir": ev_dir}, circuit)
        ddd_map = {str(mp / f"{b}.DDD"): (mp, b) for mp, b in gated}
        matched = []
        for c in ev_cands:
            hit = ddd_map.get(c["ddd_path"])
            if hit is None:
                unmatched.append(c["ddd_path"])
                continue
            mp, b = hit
            sess = bmd.session_canon_2d(b, rnd)
            if args.session and sess != args.session:
                continue
            if args.rider and rider != args.rider:
                continue
            matched.append(dict(c, mes_path=mp, base=b, session=sess, date=date,
                                round=rnd, ev_rider=rider, circuit=circuit,
                                event_key=ev_dir.name, p10=p10))
        if args.limit:
            matched = matched[: args.limit]

        # run_no 採番:
        #   従来（deterministic=False）= session 内時系列（base 名 sort）バッチ相対採番（挙動不変）
        #   決定論（deterministic=True・§75 B-3 P0-2）= outing stem 末尾連番から採番。
        #     stem に連番なし / session 内で同一連番の別 stem = fail-closed（conflict FAIL）。
        by_sess = defaultdict(list)
        for o in matched:
            by_sess[o["session"]].append(o)
        for sess in sorted(by_sess):
            group = sorted(by_sess[sess], key=lambda x: x["base"])
            if deterministic:
                # 事前に stem→連番を解決し、群内の連番衝突を fail-closed で隔離
                nums = {o["base"]: deterministic_run_no(o["base"]) for o in group}
                by_num = defaultdict(list)
                for b, n in nums.items():
                    if n is not None:
                        by_num[n].append(b)
                dup_nums = {n for n, bs in by_num.items() if len(bs) > 1}
                for o in group:
                    n = nums[o["base"]]
                    conflict = None
                    if n is None:
                        conflict = f"outing stem {o['base']!r} に決定論連番なし（末尾数字必須）"
                    elif n in dup_nums:
                        conflict = (f"session {sess} 内で run_no={n} が複数 stem に衝突: "
                                    f"{sorted(by_num[n])}")
                    if conflict:
                        o["result"] = None
                        o["run_no"] = None
                        o["run_id"] = None
                        o["lap_ids"] = []
                        o["outlap_flags"] = {}
                        o["checks"] = [("stage_run_identity", "FAIL", conflict)]
                        o["quality_status"] = "FAIL"
                        o["disposition"] = "fail"
                        outings_all.append(o)
                        log(f"  identity {o['base']}: FAIL（{conflict}）→ 隔離・抽出せず")
                        continue
                    log(f"  extract {o['base']} (session={sess}, deterministic R{n}) ...")
                    res = bmd.extract_outing(o["mes_path"], o["base"])
                    o["result"] = res
                    if res is None or not res["laps"]:
                        if "ENGINEWARMUP" in o["base"].upper():
                            o["disposition"] = "skip_enginewarmup"
                            skipped.append(o)
                            log(f"    -> no valid laps (EngineWarmup) → skip 記録")
                            continue
                        o["run_no"] = None
                        o["run_id"] = None
                        o["lap_ids"] = []
                        o["outlap_flags"] = {}
                        o["checks"] = [("stage_lap_count", "FAIL",
                                        "no valid laps (extract_outing None/0)")]
                        o["quality_status"] = "FAIL"
                        o["disposition"] = "fail"
                        outings_all.append(o)
                        log(f"    -> no valid laps → FAIL 隔離")
                        continue
                    o["run_no"] = n
                    o["run_id"] = (f"PROV_{o['date']}_{o['round']}_{o['circuit']}_"
                                   f"{o['session']}_{o['ev_rider']}_R{n}")
                    o["lap_ids"] = [f"{o['run_id']}_L{l['lap_no']}" for l in res["laps"]]
                    o["outlap_flags"] = recompute_is_outlap_provisional(
                        res["laps"], o["circuit"], f"{o['base']}.MES", o["p10"])
                    outings_all.append(o)
                continue
            run_no = 0
            for o in group:
                log(f"  extract {o['base']} (session={sess}) ...")
                res = bmd.extract_outing(o["mes_path"], o["base"])
                o["result"] = res
                if res is None or not res["laps"]:
                    if "ENGINEWARMUP" in o["base"].upper():
                        o["disposition"] = "skip_enginewarmup"
                        skipped.append(o)
                        log(f"    -> no valid laps (EngineWarmup) → skip 記録")
                        continue
                    # 有効ラップ 0 → gate FAIL 扱い
                    o["run_no"] = None
                    o["run_id"] = None
                    o["lap_ids"] = []
                    o["outlap_flags"] = {}
                    o["checks"] = [("stage_lap_count", "FAIL", "no valid laps (extract_outing None/0)")]
                    o["quality_status"] = "FAIL"
                    o["disposition"] = "fail"
                    outings_all.append(o)
                    log(f"    -> no valid laps → FAIL 隔離")
                    continue
                run_no += 1
                o["run_no"] = run_no
                o["run_id"] = (f"PROV_{o['date']}_{o['round']}_{o['circuit']}_"
                               f"{o['session']}_{o['ev_rider']}_R{run_no}")
                o["lap_ids"] = [f"{o['run_id']}_L{l['lap_no']}" for l in res["laps"]]
                o["outlap_flags"] = recompute_is_outlap_provisional(
                    res["laps"], o["circuit"], f"{o['base']}.MES", o["p10"])
                outings_all.append(o)

    # gate（採番後・バッチ全体で dup 検査）
    batch_run_ids, batch_lap_ids = set(), set()
    n_fail = 0
    for o in outings_all:
        if o.get("disposition") == "fail":       # extraction 0 laps / identity conflict
            n_fail += 1
            continue
        o["checks"] = quality_gate(o, existing_hashes, existing_run_ids,
                                   batch_run_ids, batch_lap_ids)
        if deterministic:
            # §75 B-3 P0-2: 既存 provisional/canonical run_id との衝突を fail-closed 検査
            stem_file = f"{o['base']}.MES"
            # (a) canonical 衝突（PROV_ を外した run_id が canonical に存在 = 既に finalized）
            canon_id = (o["run_id"] or "").replace("PROV_", "", 1)
            if canon_id in canonical_run_ids:
                o["checks"].append(("stage_canonical_conflict", "FAIL",
                                    f"canonical runs に {canon_id} が既存（finalized 済イベントへの "
                                    f"provisional 再取込は禁止）"))
            # (b) 既存 provisional 衝突（同名: 同内容=no-op / 異内容=conflict）
            elif o["run_id"] in existing_prov_map:
                ex_hash, ex_stem = existing_prov_map[o["run_id"]]
                if ex_hash == o["sha256"] and ex_stem == stem_file:
                    o["checks"].append(("stage_run_identity", "PASS",
                                        "same run_id + same content hash + same source stem "
                                        "→ idempotent no-op（書込なし）"))
                    if gate_status(o["checks"]) != "FAIL":
                        o["quality_status"] = gate_status(o["checks"])
                        o["disposition"] = "noop"
                        log(f"  gate {o['base']}: {o['quality_status']} (run_id={o['run_id']}) "
                            f"→ idempotent no-op")
                        continue
                else:
                    o["checks"].append(("stage_run_id_conflict", "FAIL",
                                        f"run_id {o['run_id']} が既存 provisional と衝突し内容が異なる"
                                        f"（existing hash={ex_hash} stem={ex_stem} / "
                                        f"new hash={o['sha256']} stem={stem_file}）"
                                        f"→ 明示 conflict・silent overwrite 禁止・書込なし"))
            # (c) manifest allowed_sessions（active manifest があるときのみ）
            if manifest is not None and o.get("event_key") == manifest.get("event_key"):
                if o["session"] not in set(manifest["allowed_sessions"]):
                    o["checks"].append(("stage_session_allowed", "FAIL",
                                        f"session {o['session']!r} は manifest allowed_sessions "
                                        f"{manifest['allowed_sessions']} 外"))
        o["quality_status"] = gate_status(o["checks"])
        o["disposition"] = "fail" if o["quality_status"] == "FAIL" else "insert"
        if o["disposition"] == "insert":
            batch_run_ids.add(o["run_id"])
            batch_lap_ids.update(o["lap_ids"])
        else:
            n_fail += 1
        best = min((l["lap_time_s"] for l in o["result"]["laps"]
                    if o["outlap_flags"].get(l["lap_no"], 0) == 0), default=None)
        log(f"  gate {o['base']}: {o['quality_status']} (run_id={o['run_id']}, "
            f"laps={o['result']['nlaps']}, best={best})")

    conn.close()
    return dict(status="ok", before_biz=before_biz, before_prov=before_prov,
                outings=outings_all, skipped=skipped, unmatched=unmatched, n_fail=n_fail)


# ── apply（--apply 時のみ・1トランザクション・業務6テーブル assert） ─────────

def do_apply(args, pipe: dict, ctx: dict | None = None) -> int:
    # ── 書込前 最終ガード（多層防御・round8_only_provisional_guard 2026-07-09）──
    #    enforce_apply_guard() が main で先に検査するが、do_apply でも候補単位で再検査し
    #    backup/DDL/INSERT の前に必ず fail-closed する（正本DB・provisional とも一切書かない）。
    if not args.event:
        log("❌ GUARD: apply には明示 --event が必要です（unfiltered apply 禁止）。書込なしで中止。")
        return 4
    if not args.required_round:
        log("❌ GUARD: apply には required round が必要です（--required-round 指定 or "
            "active event manifest から解決）。書込なしで中止。")
        return 4
    if args.required_round:
        rr = args.required_round.strip().upper()
        offenders = sorted({(o.get("event_key"), (o.get("round") or "").upper())
                            for o in (pipe["outings"] + pipe["skipped"])
                            if (o.get("round") or "").upper() != rr})
        if offenders:
            log(f"❌ GUARD: apply 中止 — --required-round {rr} 以外の候補が混入: {offenders}。書込なしで中止。")
            return 4
    inserts = [o for o in pipe["outings"] if o["disposition"] == "insert"]
    fails = [o for o in pipe["outings"] if o["disposition"] == "fail"]
    noops = [o for o in pipe["outings"] if o["disposition"] == "noop"]

    # 事前フルバックアップ（WAL-safe: db + -wal + -shm sidecar・§75 B-3）
    bdir = BACKUP_ROOT / f"_backup_session_staging_{TS}"
    bdir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(args.db) + suffix)
        if src.exists():
            shutil.copy2(src, bdir / src.name)
    log(f"バックアップ作成（WAL-safe）: {bdir / Path(args.db).name}")

    ddl = DDL_FILE.read_text(encoding="utf-8")
    before = pipe["before_biz"]

    # 耐久 receipt: apply_started（backup 後・書込前に別トランザクションで commit・
    # 中断時は apply_started のみ残る = 起動時検出可能。テーブル無しなら no-op）
    expected = dict(runs=len(inserts), laps=sum(len(o["lap_ids"]) for o in inserts),
                    ls=sum(len(o["lap_ids"]) for o in inserts))
    ledger_receipt(
        args, ctx or {}, args.event, state="candidate_ready", reason="apply_started",
        receipt=dict(phase="apply_started", event=args.event, session=args.session,
                     required_round=args.required_round, expected_delta=expected,
                     backup_dir=str(bdir),
                     candidates=[dict(run_id=o["run_id"], stem=o["base"], hash=o["sha256"],
                                      laps=len(o["lap_ids"])) for o in inserts],
                     noops=[o["run_id"] for o in noops],
                     fails=[o["base"] for o in fails]))

    conn = sqlite3.connect(args.db)
    try:
        conn.executescript(ddl)                 # 固定 DDL verbatim（IF NOT EXISTS 冪等）
        n_runs = n_laps = n_ls = 0
        for o in inserts:
            rows = build_rows(o)
            conn.execute(insert_stmt("runs_provisional", RUNS_PROV_COLS), rows["run"])
            conn.executemany(insert_stmt("laps_provisional", LAPS_PROV_COLS), rows["laps"])
            conn.executemany(insert_stmt("lap_suspension_provisional", LS_PROV_COLS), rows["ls"])
            n_runs += 1
            n_laps += len(rows["laps"])
            n_ls += len(rows["ls"])
            conn.execute("UPDATE import_queue SET status='awaiting_gate', started_at=?, "
                         "finished_at=?, analysis_run_id=?, error=NULL WHERE queue_id=?",
                         (NOW_ISO, NOW_ISO, ANALYSIS_RUN_ID, o["queue_id"]))
        for o in noops:
            # 冪等 no-op（同名同内容）: 行は書かず queue のみ awaiting_gate に整合
            conn.execute("UPDATE import_queue SET status='awaiting_gate', started_at=?, "
                         "finished_at=?, analysis_run_id=?, error=NULL WHERE queue_id=?",
                         (NOW_ISO, NOW_ISO, ANALYSIS_RUN_ID, o["queue_id"]))
        for o in fails:
            fail_det = "; ".join(f"{c[0]}:{c[2]}" for c in o.get("checks", []) if c[1] == "FAIL")
            conn.execute("UPDATE import_queue SET status='failed', started_at=?, finished_at=?, "
                         "analysis_run_id=?, error=? WHERE queue_id=?",
                         (NOW_ISO, NOW_ISO, ANALYSIS_RUN_ID, fail_det or "gate FAIL", o["queue_id"]))
        for o in pipe["skipped"]:
            conn.execute("UPDATE import_queue SET status='skipped', started_at=?, finished_at=?, "
                         "analysis_run_id=?, error=? WHERE queue_id=?",
                         (NOW_ISO, NOW_ISO, ANALYSIS_RUN_ID,
                          "EngineWarmup / no valid laps (skip)", o["queue_id"]))
        # data_quality_log（apply 時のみ書込・readiness §4）
        for o in pipe["outings"] + pipe["skipped"]:
            scope_id = o.get("run_id") or o["base"]
            for (name, result, det) in o.get("checks", []) or [
                    ("stage_lap_count", "PASS", "skip: EngineWarmup no valid laps")]:
                conn.execute(
                    "INSERT INTO data_quality_log(analysis_run_id,check_name,scope,scope_id,"
                    "observed_value,result,severity,detail,checked_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (ANALYSIS_RUN_ID, name, "outing", scope_id, None, result,
                     "INFO" if result == "PASS" else result, det, NOW_ISO))
        conn.execute(
            "INSERT OR REPLACE INTO analysis_run_log(analysis_run_id,agent,script_name,"
            "started_at,finished_at,status,rows_inserted,rows_updated,notes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ANALYSIS_RUN_ID, "claude_code", "session_extract_staging.py", NOW_ISO, NOW_ISO,
             "success", n_runs + n_laps + n_ls, 0,
             f"provisional staging event={args.event} session={args.session or 'ALL'} "
             f"runs={n_runs} laps={n_laps} ls={n_ls} fail={len(fails)} skip={len(pipe['skipped'])}"))
        # 業務6テーブル before==after assert（同一トランザクション内）
        after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_TABLES}
        if after != before:
            conn.rollback()
            log(f"❌ 業務テーブル件数が変化！rollback。before={before} after={after}")
            conn.close()
            ledger_receipt(args, ctx or {}, args.event, state="failed",
                           reason="apply aborted: business-table invariant violated (rollback)",
                           receipt=dict(phase="apply_failed", before=before, after=after,
                                        backup_dir=str(bdir)))
            return 3
        conn.commit()
        prov_after = provisional_counts(conn)
        log(f"apply 完了: runs_provisional +{n_runs} / laps_provisional +{n_laps} / "
            f"lap_suspension_provisional +{n_ls}（INSERT OR REPLACE・冪等）")
        log(f"provisional 件数: {prov_after}")
        log(f"業務6テーブル不変 assert 合格: {after}")
        pipe["after_biz"] = after
        pipe["after_prov"] = prov_after
        pipe["applied"] = dict(runs=n_runs, laps=n_laps, ls=n_ls)
    except Exception as e:
        conn.rollback()
        conn.close()
        log(f"❌ apply 失敗 rollback: {e}")
        ledger_receipt(args, ctx or {}, args.event, state="failed",
                       reason=f"apply exception (rolled back): {e}",
                       receipt=dict(phase="apply_failed", error=str(e), backup_dir=str(bdir)))
        raise
    conn.close()
    # 耐久 receipt: apply_committed（commit 後・実デルタ + invariant 結果。
    # commit 後〜receipt 前の中断は apply_started との突合で検出可能）
    ledger_receipt(
        args, ctx or {}, args.event, state="staged", reason="apply_committed",
        receipt=dict(phase="apply_committed", expected_delta=expected,
                     actual_delta=dict(runs=n_runs, laps=n_laps, ls=n_ls),
                     business_unchanged=True, business_counts=after,
                     provisional_counts=prov_after, backup_dir=str(bdir),
                     noops=[o["run_id"] for o in noops],
                     fails=[o["base"] for o in fails]))
    return 2 if fails else 0


# ── レポート出力 ─────────────────────────────────────────────────────────────

def write_report(args, pipe: dict, mode: str, exit_code: int) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    p = Path(args.report) if args.report else REPORTS_DIR / f"session_staging_{mode}_{TS}.md"
    L = [f"# Session Extraction Staging — {mode} — {datetime.now():%Y-%m-%d %H:%M}", ""]
    L.append(f"- DB: `{args.db}` / event={args.event or 'ALL'} / session={args.session or 'ALL'} "
             f"/ rider={args.rider or 'ALL'} / limit={args.limit or '-'}")
    L.append(f"- mode: **{mode}** / exit={exit_code} / analysis_run_id=`{ANALYSIS_RUN_ID}`")
    L.append("")
    outs = pipe["outings"]
    ins = [o for o in outs if o["disposition"] == "insert"]
    fails = [o for o in outs if o["disposition"] == "fail"]
    L.append(f"## 候補: {len(outs) + len(pipe['skipped'])} outing "
             f"(insert対象 {len(ins)} / FAIL隔離 {len(fails)} / skip {len(pipe['skipped'])} "
             f"/ queue未マッチ {len(pipe['unmatched'])})")
    L.append("")
    L.append("| base | session | run_id | laps | best(valid) | gate | checks |")
    L.append("|---|---|---|---:|---:|:--:|---|")
    for o in sorted(outs, key=lambda x: (x["session"], x["base"])):
        res = o.get("result")
        nl = res["nlaps"] if res else 0
        best = min((l["lap_time_s"] for l in (res["laps"] if res else [])
                    if o["outlap_flags"].get(l["lap_no"], 0) == 0), default=None)
        ck = "; ".join(f"{c[0]}={c[1]}" for c in o.get("checks", []) if c[1] != "PASS") or "all PASS"
        L.append(f"| {o['base']} | {o['session']} | {o.get('run_id') or '—'} | {nl} | "
                 f"{best or '—'} | {o['quality_status']} | {ck} |")
    for o in pipe["skipped"]:
        L.append(f"| {o['base']} | {o['session']} | — | 0 | — | SKIP | EngineWarmup no valid laps |")
    L.append("")
    exp_laps = sum(len(o["lap_ids"]) for o in ins)
    L.append(f"## 予定/実施 行数: runs_provisional={len(ins)} / laps_provisional={exp_laps} / "
             f"lap_suspension_provisional={exp_laps}")
    L.append("")
    L.append("## 業務6テーブル（before / after）")
    L.append("")
    L.append("| table | before | after | 不変 |")
    L.append("|---|---:|---:|:--:|")
    after = pipe.get("after_biz") or pipe["before_biz"]
    for t in BUSINESS_TABLES:
        ok = "✅" if pipe["before_biz"][t] == after[t] else "❌"
        L.append(f"| {t} | {pipe['before_biz'][t]} | {after[t]} | {ok} |")
    L.append("")
    L.append("## provisional 3テーブル（before → after）")
    L.append("")
    ap = pipe.get("after_prov") or pipe["before_prov"]
    for t in PROV_TABLES:
        L.append(f"- {t}: {pipe['before_prov'][t]} → {ap[t]}")
    L.append("")
    if pipe["unmatched"]:
        L.append("## queue にあるが gated_outings に無いパス（NOISE/GRID 等）")
        for u in pipe["unmatched"]:
            L.append(f"- {u}")
        L.append("")
    p.write_text("\n".join(L), encoding="utf-8")
    return p


# ── Round8-only guard（P0・2026-07-09 / round8_only_provisional_guard_code_instruction）──────
def enforce_apply_guard(args, ctx: dict | None = None):
    """書込前ガード（fail-closed）。違反時は exit 4（正本DB・provisional とも一切書かない）。
      A) --apply は明示 --event 必須（unfiltered apply 禁止 → 歴史的 pending の誤 apply 防止）。
      B) --required-round 指定時、--event の round が一致しないと中止（Round8 以外の provisional 取込防止）。
      C) §75 B-3 P0-1: --apply で --required-round 省略時は active event manifest から round を解決。
         解決不能（manifest 無し）= exit 4。active manifest 不整合（複数 active / DB ミラー改竄）= exit 4。
         active manifest がある場合、--event は manifest.event_key と一致必須（event-external apply 禁止）。
      manifest 未導入DB + 明示フラグの従来運用（--event + --required-round）は不変。
    dry-run/apply の前（run_pipeline より前）に呼ぶ。do_apply 内でも候補単位で再検査する（多層防御）。
    """
    if args.apply and not args.event:
        log("❌ GUARD: --apply には明示 --event が必要です（unfiltered apply は禁止）。書込なしで中止。")
        sys.exit(4)
    manifest = (ctx or {}).get("manifest")
    if args.apply and (ctx or {}).get("error"):
        log(f"❌ GUARD: active event manifest の解決に失敗（fail-closed）: {ctx['error']}。書込なしで中止。")
        sys.exit(4)
    if args.apply and manifest is not None:
        if args.event != manifest["event_key"]:
            log(f"❌ GUARD: --event {args.event} が active manifest の event_key "
                f"{manifest['event_key']} と不一致（event-external apply 禁止）。書込なしで中止。")
            sys.exit(4)
        if args.session and args.session not in manifest["allowed_sessions"]:
            log(f"❌ GUARD: --session {args.session} は active manifest の allowed_sessions "
                f"{manifest['allowed_sessions']} 外。書込なしで中止。")
            sys.exit(4)
        if not args.required_round:
            args.required_round = manifest["round"]
            log(f"GUARD: --required-round 未指定 → active manifest から {args.required_round} を解決。")
    if args.apply and not args.required_round:
        log("❌ GUARD: --apply には --required-round が必要です（明示指定 or 対象DBの active "
            "event manifest から解決）。どちらも無い apply は禁止（P0-1）。書込なしで中止。")
        sys.exit(4)
    if args.required_round:
        rr = args.required_round.strip().upper()
        if args.event:
            m = EVENT_RE.match(args.event)
            ev_round = m.group(2).upper() if m else ""
            if ev_round != rr:
                log(f"❌ GUARD: --event {args.event}（round={ev_round or '?'}）が "
                    f"--required-round {rr} と不一致。書込なしで中止。")
                sys.exit(4)
        elif args.apply:
            log(f"❌ GUARD: --apply --required-round {rr} には一致する --event が必要です。書込なしで中止。")
            sys.exit(4)


def main():
    ap = argparse.ArgumentParser(description="Session Extraction Staging（既定 dry-run）")
    ap.add_argument("--db", default=str(CANON_DB))
    ap.add_argument("--event", default=None, help="イベントフォルダ名 例 20260612-ROUND7-JA52")
    ap.add_argument("--rider", default=None)
    ap.add_argument("--session", default=None, help="canonical session 例 FP/QP/RACE1")
    ap.add_argument("--source-file", default=None, help="単一 outing のパス部分一致")
    ap.add_argument("--apply", action="store_true", help="正本DBへ実反映（既定は dry-run/ro）")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--report", default=None, help="出力 md パス上書き")
    ap.add_argument("--include-awaiting", action="store_true",
                    help="awaiting_gate も候補に含める（冪等再実行の検証用）")
    ap.add_argument("--required-round", default=None,
                    help="apply/dry-run を指定ラウンドの event に限定するガード（例 ROUND8）。"
                         "設定時、--event の round が不一致だと書込前に exit 4（Round8以外の provisional 取込防止）。"
                         "--apply で未指定の場合は対象DBの active event manifest から自動解決（解決不能=exit 4）。")
    ap.add_argument("--deterministic-runid", action="store_true",
                    help="run_no を outing stem 末尾連番から決定論採番（§75 B-3 P0-2）。"
                         "対象DBに active event manifest がある場合は自動で有効。")
    args = ap.parse_args()

    if not Path(args.db).exists():
        log(f"DB が見つかりません: {args.db}")
        sys.exit(1)
    if not DDL_FILE.exists():
        log(f"固定 DDL が見つかりません: {DDL_FILE}")
        sys.exit(1)

    # active event manifest（あれば）を解決 → guard / 決定論採番へ（無ければ従来動作）
    ctx = resolve_manifest_context(args)
    if ctx.get("manifest") is not None:
        m = ctx["manifest"]
        log(f"active event manifest: {m['event_key']} v{m['manifest_version']} "
            f"round={m['round']} hash={m['content_hash'][:12]}…")
    ctx["deterministic"] = bool(args.deterministic_runid or ctx.get("manifest") is not None)
    if ctx["deterministic"]:
        log("run_no 採番 = deterministic（outing stem 末尾連番・衝突は fail-closed）")

    enforce_apply_guard(args, ctx)     # 書込前 fail-closed ガード（違反→exit 4・run_pipeline も走らせない）

    pipe = run_pipeline(args, ctx)
    if pipe["status"] == "no_candidates":
        log("候補 0 件（pending 2d_extract がフィルタに一致しない）")
        sys.exit(1)

    mode = "apply" if args.apply else "dryrun"
    if args.apply:
        code = do_apply(args, pipe, ctx)
        if code == 3:
            write_report(args, pipe, mode, 3)
            sys.exit(3)
    else:
        # dry-run: ro で after を再取得（無変更の証明）
        conn = ro(Path(args.db))
        pipe["after_biz"] = business_counts(conn)
        pipe["after_prov"] = provisional_counts(conn)
        conn.close()
        code = 2 if pipe["n_fail"] else 0
        log("dry-run 完了（正本DBは mode=ro・無変更）")

    rep = write_report(args, pipe, mode, code)
    log(f"レポート: {rep}")
    if code == 2:
        log("⚠ gate FAIL の outing あり（隔離・INSERT せず）→ exit 2")
    sys.exit(code)


if __name__ == "__main__":
    main()
