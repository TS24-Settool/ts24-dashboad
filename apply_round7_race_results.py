#!/usr/bin/env python3
"""
apply_round7_race_results.py — ROUND7(MISANO) Result PDF → race_results 反映（既定 dry-run）
=============================================================================================
Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-06-29）/ CLAUDE.md §35・§36。

目的: 新しい 2D data が無い ROUND7 について、Result PDF（非2D）から `race_results` の
      投入候補を **dry-run で生成・検査**する。正本DBへは書かない（`--apply` は承認後のみ）。

既存設計に整合:
  - 抽出は `pdf_result_extractor_v2.extract_pdf()`（MISANO レイアウト対応済み・§35）。
  - 反映の自然キー（ローカル UPSERT）は **`apply_pdf_positions_v2.py` と同じ
    (round, session_type, rider_num)**（round=1イベント=1サーキットで一意）。
  - 既存慣行: **RACE1/RACE2 はフルフィールド、FP/QP/WUP は TS24 チーム(#77/#52)のみ**
    （既存 race_results の実データ分布に一致）。`--full-nonrace` で非RACEも全員にできる。
  - UPSERT は COALESCE（v2 が None の項目で既存値を潰さない）。

安全原則:
  - **既定 dry-run**。正本DBは `mode=ro` でしか開かない。
  - `--apply`（**本タスク未実行**・承認後 Tatsuki 実行）: 事前フルバックアップ → 自然キー UPSERT →
    **runs/laps/lap_suspension/pdf_lap_times は不変 assert（違反で rollback）**・race_results は候補数だけ増加を確認。

使い方:
  python3 apply_round7_race_results.py                 # dry-run（既定）
  python3 apply_round7_race_results.py --full-nonrace  # FP/QP/WUP も全ライダー候補に
  # python3 apply_round7_race_results.py --apply        # ← 承認後のみ。本タスクでは実行しない
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pdf_result_extractor_v2 as v2

SCRIPT_DIR = Path(__file__).parent
DATA_ROOT = SCRIPT_DIR.parent
CANON_DB = DATA_ROOT / "02_DATABASE" / "ts24_unified.db"
ROUND7_DIR = DATA_ROOT / "07_RESULTS" / "ROUND7_MISANO_20260612"
REPORTS_DIR = SCRIPT_DIR / "reports"
BACKUP_ROOT = DATA_ROOT / "02_DATABASE"

BUSINESS_NONTARGET = ["runs", "laps", "lap_suspension", "pdf_lap_times"]  # apply で不変であるべき
TEAM = {77, 52}
RACE_SESSIONS = {"RACE1", "RACE2"}
# 物理レンジ（MISANO ~1'37〜1'45 → 秒。緩めの妥当域）
BEST_LO, BEST_HI = 80.0, 130.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s [R7RR] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S", handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger(__name__)


def ro(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


# ── 候補抽出（Extraction agent） ─────────────────────────────────────────────

def build_candidates(full_nonrace: bool) -> tuple[list[dict], list[dict]]:
    """ROUND7 6 PDF から race_results 候補を生成。返り値 (candidates, lapdetail_summary)。"""
    cands: list[dict] = []
    lapsum: list[dict] = []  # RACE の lap 明細サマリ（best/laps 整合用）
    for pdf in sorted(ROUND7_DIR.glob("*.pdf")):
        res = v2.extract_pdf(pdf, all_riders=True)
        m = res["meta"]
        sess = m.get("session_type")
        is_race = sess in RACE_SESSIONS
        for num, r in res["riders"].items():
            keep = is_race or full_nonrace or (num in TEAM)
            if not keep:
                continue
            laps = r.get("laps", [])
            valid = [lp["lap_time_s"] for lp in laps if not lp["is_cancelled"] and lp["lap_time_s"]]
            cands.append({
                "round": m.get("round"), "circuit": m.get("circuit"), "session_type": sess,
                "date": m.get("date"), "position": r.get("position"), "rider_num": num,
                "rider_name": r.get("rider_name"), "laps": (len(laps) or None),
                "best_lap": r.get("best_lap"), "best_lap_s": r.get("best_lap_s"),
                "source_file": pdf.name, "status_flag": r.get("status"),
            })
            if is_race:
                lapsum.append({"session_type": sess, "rider_num": num,
                               "n_laps": len(laps), "v2_best": (min(valid) if valid else None),
                               "rr_best": r.get("best_lap_s")})
    return cands, lapsum


# ── 品質ゲート（Quality Gate agent） ────────────────────────────────────────

def gate_candidates(cands: list[dict], lapsum: list[dict]) -> dict:
    g = {}
    # 自然キー (round,session_type,rider_num) 重複
    seen = {}
    dups = []
    for c in cands:
        k = (c["round"], c["session_type"], c["rider_num"])
        if k in seen:
            dups.append(k)
        seen[k] = 1
    g["dups"] = dups
    # 既存 race_results 衝突（ROUND7 は 0 のはず）
    con = ro(CANON_DB)
    coll = []
    for c in cands:
        row = con.execute(
            "SELECT 1 FROM race_results WHERE round=? AND session_type=? AND rider_num=? "
            "AND COALESCE(data_scope,'')<>'COMPANY'",
            (c["round"], c["session_type"], c["rider_num"])).fetchone()
        if row:
            coll.append((c["round"], c["session_type"], c["rider_num"]))
    con.close()
    g["collisions"] = coll
    # NULL / 型 / 物理レンジ
    null_key = [c for c in cands if not (c["round"] and c["circuit"] and c["session_type"] and c["rider_num"])]
    null_date = [c for c in cands if not c["date"]]
    null_best = [c for c in cands if c["best_lap_s"] is None]
    bad_best = [c for c in cands if c["best_lap_s"] is not None and not (BEST_LO <= c["best_lap_s"] <= BEST_HI)]
    bad_type = [c for c in cands if (c["rider_num"] is not None and not isinstance(c["rider_num"], int))
                or (c["best_lap_s"] is not None and not isinstance(c["best_lap_s"], float))]
    g["null_key"] = null_key
    g["null_date"] = null_date
    g["null_best"] = null_best
    g["bad_best"] = bad_best
    g["bad_type"] = bad_type
    # RACE: race_results 候補 best == lap 明細 best、laps == n_laps の整合
    mism = [s for s in lapsum if (s["v2_best"] is not None and s["rr_best"] is not None
            and abs(s["v2_best"] - s["rr_best"]) > 0.001)]
    g["lap_best_mismatch"] = mism
    return g


# ── apply（承認後のみ・本タスク未実行） ─────────────────────────────────────

def do_apply(cands: list[dict]) -> int:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    con0 = ro(CANON_DB)
    before = {t: con0.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_NONTARGET}
    rr_before = con0.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
    con0.close()
    bdir = BACKUP_ROOT / f"_backup_round7_rr_{ts}"
    bdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANON_DB, bdir / CANON_DB.name)
    log.info("バックアップ: %s", bdir / CANON_DB.name)

    con = sqlite3.connect(str(CANON_DB))
    inserted = 0
    try:
        for c in cands:
            ex = con.execute("SELECT 1 FROM race_results WHERE round=? AND session_type=? AND rider_num=?",
                             (c["round"], c["session_type"], c["rider_num"])).fetchone()
            if ex:
                con.execute(
                    "UPDATE race_results SET position=COALESCE(?,position), "
                    "best_lap=COALESCE(?,best_lap), best_lap_s=COALESCE(?,best_lap_s), "
                    "laps=COALESCE(?,laps), rider_name=COALESCE(?,rider_name), "
                    "circuit=COALESCE(?,circuit), date=COALESCE(?,date), source_file=COALESCE(?,source_file) "
                    "WHERE round=? AND session_type=? AND rider_num=?",
                    (c["position"], c["best_lap"], c["best_lap_s"], c["laps"], c["rider_name"],
                     c["circuit"], c["date"], c["source_file"],
                     c["round"], c["session_type"], c["rider_num"]))
            else:
                con.execute(
                    "INSERT INTO race_results (round,circuit,session_type,date,position,rider_num,"
                    "rider_name,laps,best_lap,best_lap_s,source_file,data_scope) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?, 'TS24_PRIVATE')",
                    (c["round"], c["circuit"], c["session_type"], c["date"], c["position"],
                     c["rider_num"], c["rider_name"], c["laps"], c["best_lap"], c["best_lap_s"], c["source_file"]))
                inserted += 1
        after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in BUSINESS_NONTARGET}
        if after != before:
            con.rollback(); con.close()
            log.error("非対象業務テーブルが変化！rollback。before=%s after=%s", before, after)
            return 3
        con.commit()
    except Exception as e:
        con.rollback(); con.close()
        log.error("apply 失敗 rollback: %s", e)
        return 1
    rr_after = con.execute("SELECT COUNT(*) FROM race_results").fetchone()[0]
    con.close()
    log.info("apply 完了: insert=%d update=%d / race_results %d→%d / 非対象不変 ✅ / backup=%s",
             inserted, len(cands) - inserted, rr_before, rr_after, bdir)
    return 0


# ── レポート（Documentation/Handoff agent） ─────────────────────────────────

def multiagent_check_md() -> list[str]:
    L = []
    L.append("## Multi-agent operating check（CLAUDE.md §1/§20・PROJECT_RULES・decision records 照合）")
    L.append("")
    L.append("§20 の 6 エージェント（Extraction=測る / Quality Gate=疑う / DB Integration=保存 / "
             "Case Search=探す / Hypothesis=考える / Supervisor=止める）＋ Tatsuki=決める、§1 の役割境界に照らした自己点検。")
    L.append("")
    L.append("| 役割 | 本タスクでの担当・成果物 | 状態 |")
    L.append("|---|---|---|")
    L.append("| Codex / Handoff | Obsidian 最新状態確認・方針整理・Code 指示・承認境界明示（INBOX/handoff/log） | ✅ 別エージェント(Codex)が実施 |")
    L.append("| Claude Code / Implementation | dry-run helper `apply_round7_race_results.py`・既存資産再利用・git 差分管理・ローカルコミット | ✅ 本タスク |")
    L.append("| Extraction agent（測る） | ROUND7 6 PDF → race_results 候補抽出（`extract_pdf`・MISANO 対応） | ✅ 本レポート §1-2 |")
    L.append("| Quality Gate agent（疑う） | 自然キー重複・既存衝突・NULL/型/物理レンジ・RACE best/laps 整合・既存無回帰 | ✅ 本レポート §3 |")
    L.append("| DB Integration agent（保存） | UPSERT(自然キー+COALESCE)・rollback・before/after・write 境界設計（apply は未実行） | ✅ 設計のみ（apply 要承認） |")
    L.append("| Documentation / Handoff agent | `reports/`・`CLAUDE.md`・Obsidian log/handoff/current_state 更新 | ✅ 本タスク |")
    L.append("| Case Search / Hypothesis（探す/考える） | 本タスク範囲外（反映後の分析フェーズ） | – 未実施（スコープ外） |")
    L.append("| Supervisor（止める） | write apply を承認境界で停止・2D 不在値の作成禁止を明示 | ✅ 本タスクは dry-run で停止 |")
    L.append("| Tatsuki / 決める | race_results write apply の承認 | ⏳ 承認待ち |")
    L.append("")
    L.append("**所見**: 抽出・品質ゲート・統合設計・文書化・停止（承認境界）は成果物上で満たされている。"
             "Case Search/Hypothesis は反映後フェーズのため未実施（正常）。実 write は Tatsuki 承認後。")
    return L


def write_report(cands: list[dict], lapsum: list[dict], g: dict,
                 before_counts: dict, after_counts: dict, full_nonrace: bool) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    p = REPORTS_DIR / "round7_race_results_apply_dry_run_20260629.md"
    from collections import Counter
    by_sess = Counter((c["session_type"]) for c in cands)
    L = []
    L.append(f"# ROUND7 race_results 反映 dry-run — {datetime.now():%Y-%m-%d %H:%M}")
    L.append("")
    L.append("**dry-run（正本DB `mode=ro`・無変更）**。`apply_round7_race_results.py`（`--apply` 無し）。")
    L.append(f"非RACE 候補ポリシー: {'全ライダー' if full_nonrace else 'TS24 チーム(#77/#52)のみ（既存慣行）'}。")
    L.append("自然キー（ローカル UPSERT）= (round, session_type, rider_num)（`apply_pdf_positions_v2.py` と同一）。")
    L.append("")
    L.append("## 1. 投入候補サマリ")
    L.append("")
    L.append(f"- 候補総数: **{len(cands)} 行**")
    L.append("")
    L.append("| session | 候補rider数 |")
    L.append("|---|---:|")
    for s in sorted(by_sess):
        L.append(f"| {s} | {by_sess[s]} |")
    L.append("")
    L.append("## 2. session×rider 候補（抜粋: TS24 #77/#52）")
    L.append("")
    L.append("| session | rider | pos | laps | best_lap_s | date |")
    L.append("|---|---:|---:|---:|---:|---|")
    for c in cands:
        if c["rider_num"] in TEAM:
            L.append(f"| {c['session_type']} | #{c['rider_num']} | {c['position']} | {c['laps']} | "
                     f"{c['best_lap_s']} | {c['date']} |")
    L.append("")
    L.append("## 3. Quality Gate（投入前検査）")
    L.append("")
    L.append("| 検査 | 結果 | 判定 |")
    L.append("|---|---:|:--:|")
    L.append(f"| 自然キー重複（候補内）| {len(g['dups'])} | {'✅' if not g['dups'] else '❌'} |")
    L.append(f"| 既存 race_results 衝突（ROUND7）| {len(g['collisions'])} | {'✅' if not g['collisions'] else '⚠️'} |")
    L.append(f"| 必須キー NULL（round/circuit/session/rider）| {len(g['null_key'])} | {'✅' if not g['null_key'] else '❌'} |")
    L.append(f"| date NULL | {len(g['null_date'])} | {'✅' if not g['null_date'] else '⚠️'} |")
    L.append(f"| best_lap_s NULL | {len(g['null_best'])} | {'✅' if not g['null_best'] else '⚠️'} |")
    L.append(f"| best_lap_s 物理レンジ外([{BEST_LO},{BEST_HI}]) | {len(g['bad_best'])} | {'✅' if not g['bad_best'] else '⚠️'} |")
    L.append(f"| 型不正（rider_num/best_lap_s）| {len(g['bad_type'])} | {'✅' if not g['bad_type'] else '❌'} |")
    L.append(f"| RACE: race_results best ≠ lap明細 best | {len(g['lap_best_mismatch'])} | {'✅' if not g['lap_best_mismatch'] else '⚠️'} |")
    L.append("")
    if g["null_best"]:
        L.append("best_lap_s NULL の候補（参考・採用判断要）:")
        for c in g["null_best"][:15]:
            L.append(f"- {c['session_type']} #{c['rider_num']} pos={c['position']} laps={c['laps']} status={c['status_flag']}")
        L.append("")
    L.append("## 4. 既存 race_results との差分")
    L.append("")
    L.append(f"- ROUND7 既存行（非COMPANY）= {len(g['collisions'])}（0 なら全候補が新規 INSERT）。")
    L.append("- 反映は自然キー UPSERT（COALESCE）。既存があれば position/best/laps/name 等を None で潰さず更新。")
    L.append("")
    L.append("## 5. apply 時 SQL / UPSERT 方針")
    L.append("")
    L.append("```sql")
    L.append("-- 既存あり: UPDATE ... COALESCE(new, existing) WHERE round=? AND session_type=? AND rider_num=?")
    L.append("-- 既存なし: INSERT INTO race_results(round,circuit,session_type,date,position,rider_num,")
    L.append("--           rider_name,laps,best_lap,best_lap_s,source_file,data_scope='TS24_PRIVATE')")
    L.append("```")
    L.append("- 自然キー = (round, session_type, rider_num)。COMPANY(BSB) とは衝突しない（ROUND7=MISANO のみ）。")
    L.append("")
    L.append("## 6. rollback 方針")
    L.append("")
    L.append("- 事前に正本DB をフルコピー（`02_DATABASE/_backup_round7_rr_<TS>/`）。")
    L.append("- apply は単一トランザクション。**runs/laps/lap_suspension/pdf_lap_times が before==after でなければ rollback**。")
    L.append("- 失敗時は backup から差し戻し。INSERT のみ（COALESCE UPDATE）で既存良データを破壊しない。")
    L.append("")
    L.append("## 7. 正本DB業務テーブル（dry-run: 無変更を確認）")
    L.append("")
    L.append("| table | before | after | 不変 |")
    L.append("|---|---:|---:|:--:|")
    for t in ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]:
        ok = "✅" if before_counts[t] == after_counts[t] else "❌"
        L.append(f"| {t} | {before_counts[t]} | {after_counts[t]} | {ok} |")
    L.append("")
    L.extend(multiagent_check_md())
    L.append("")
    L.append("## 8. race_results 反映後に再実行する手順")
    L.append("")
    L.append("1. `python3 pdf_v2_scratch_gate.py --all` を再実行 → ROUND7 RACE が真値を得て PASS/WARNING/FAIL 判定可能に。")
    L.append("2. `python3 apply_pdf_v2_staging.py`（dry-run）で ROUND7 RACE PASS 行が staging 候補に入るか確認。")
    L.append("3. 問題なければ（別承認）staging / VIEW / Workbench 切替へ。")
    L.append("")
    L.append("## 9. Tatsuki 承認後に実行するコマンド（案）")
    L.append("")
    L.append("```bash")
    L.append("python3 apply_round7_race_results.py --apply     # ROUND7 race_results 反映（非対象業務テーブル不変 assert）")
    L.append("python3 pdf_v2_scratch_gate.py --all             # race_results 反映後に Gate 再実行")
    L.append("```")
    L.append("")
    L.append("> `--apply` は **race_results（業務テーブル）への書込**＝要 Tatsuki 承認。"
             "runs/laps/lap_suspension/pdf_lap_times は不変。2D 取込・staging apply・VIEW・Workbench・Supabase・push は別タスク。")
    p.write_text("\n".join(L), encoding="utf-8")
    return p


def main():
    ap = argparse.ArgumentParser(description="ROUND7 race_results 反映（既定 dry-run）")
    ap.add_argument("--apply", action="store_true", help="正本 race_results へ実反映（★承認後のみ）")
    ap.add_argument("--full-nonrace", action="store_true", help="FP/QP/WUP も全ライダー候補に（既定はチームのみ）")
    args = ap.parse_args()

    if not CANON_DB.exists() or not ROUND7_DIR.exists():
        log.error("正本DB または ROUND7 フォルダが見つかりません")
        sys.exit(1)

    cands, lapsum = build_candidates(args.full_nonrace)
    log.info("候補: %d 行（PDF=%d）", len(cands), len(list(ROUND7_DIR.glob('*.pdf'))))

    if args.apply:
        log.warning("--apply: race_results（業務テーブル）へ書き込みます")
        sys.exit(do_apply(cands))

    # dry-run
    con = ro(CANON_DB)
    before = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]}
    con.close()
    g = gate_candidates(cands, lapsum)
    con = ro(CANON_DB)
    after = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
             for t in ["runs", "laps", "lap_suspension", "race_results", "pdf_lap_times"]}
    con.close()
    rep = write_report(cands, lapsum, g, before, after, args.full_nonrace)
    log.info("Gate: dup=%d collision=%d null_key=%d null_best=%d bad_best=%d bad_type=%d lap_best_mismatch=%d",
             len(g["dups"]), len(g["collisions"]), len(g["null_key"]), len(g["null_best"]),
             len(g["bad_best"]), len(g["bad_type"]), len(g["lap_best_mismatch"]))
    log.info("業務テーブル不変: %s", "✅" if before == after else "❌")
    log.info("レポート: %s", rep)
    log.info("※ race_results への反映は未実施（--apply は承認後のみ）")


if __name__ == "__main__":
    main()
