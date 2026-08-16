# Race Weekend workflow Phase C: Session Extraction Staging 実装 + 限定 apply — 2026-07-06

- 種別: **Phase C 実装 + 限定 apply**（Tatsuki 明示ゲート **`Session staging implementation GO`** 受領済み）
- 設計元: `reports/race_weekend_session_staging_readiness_20260706.md`（§52）/
  DDL = `reports/race_weekend_session_staging_ddl_20260706.sql`（**固定 DDL を verbatim 実行**・再設計なし）/
  `reports/race_weekend_live_workflow_design_20260706.md` §3 Stage 2
- 新規: **`session_extract_staging.py`** + 正本DB内 provisional 3テーブル + 本レポート + 実行ログ md 群
- **既存ファイル無変更**: ts24_workbench.py / build_master_db.py / extraction_scan.py 等は一切編集していない
  （ts24_workbench.py の git `M` は §48/§51 の既存未コミット差分＝readiness §1 記録と同一。mtime 13:49 は本作業開始 14:23 より前）。
  git commit なし。

---

## 1. 実装サマリ（`session_extract_staging.py`・約530行）

| 構成要素 | 関数 | 概要 |
|---|---|---|
| 本番関数 import | 冒頭（importlib で `build_master_db.py` を bmd としてロード） | `discover_outings`/`gated_outings`/`extract_outing`/`session_canon_2d`/`circuit_from_report`/`circuit_from_2d`/`circuit_canon`/`_find_report`/`TRACK_M`/`PHASE_SPD_NEW_COLS`/`SETUP_COLS` を再利用。**2D パーサ二重実装ゼロ** |
| 入力 | `load_queue_candidates()` | `import_queue` の `status='pending' AND target_kind='2d_extract'` を registry JOIN（file_path/sha256）。`--event/--rider/--session/--source-file/--limit` でフィルタ。`--include-awaiting` で awaiting_gate も対象（冪等再実行検証用） |
| is_outlap 薄ラッパ | `circuit_p10_ref()` / `recompute_is_outlap_provisional()` | 本番 `_recompute_is_outlap` と同値の ①物理下限（TRACK_M/200km/h）②GRID/FORMATION ③相対 run_min×1.15。④circuit P10 ガードは正本 laps に当該サーキット 0 行なら本番同様 silent skip（MISANO=0 行→skip 実測） |
| Quality gate | `quality_gate()` / `gate_status()` | readiness §5 の 8 チェック（`stage_lap_count`/`stage_inference`/`stage_lap_time_range`/`stage_area_rates`/`stage_phase22_exists`/`stage_phase22_fill`/`stage_zero_null_guard`/`stage_prov_id_dup`/`stage_hash_idempotent`）。FAIL outing は INSERT せず隔離。EngineWarmup 0 laps は FAIL でなく skip 記録。ph12_rear0_s=0.0 は実測値として zero-guard 除外 |
| 行組み立て | `build_rows()` / `insert_stmt()` / `_fmt_lap()` | runs_provisional（setup 33列+comment=NULL・source='2D_PROVISIONAL'・n_laps/best_lap_s 算出）/ laps_provisional / lap_suspension_provisional（62 populated 列・**WF 6列 + lap_susF_min = NULL**・0 代用禁止）+ provenance 6列（data_stage/intake_ts/source_manifest_hash=registry.sha256/source_file_path=.MES dir/provisional_event_key/quality_status） |
| ID 規約 | `run_pipeline()` 内採番 | `run_id = PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}`（event+session 内で base 名時系列順＝本番 2D_ONLY パスと同挙動）/ `lap_id = {run_id}_L{lap_no}` |
| dry-run | `run_pipeline()` + `write_report()` | **既定 dry-run**。正本DBは `mode=ro` でのみ open。候補・gate 判定・予定行数・業務6テーブル before/after を md 出力 |
| apply | `do_apply()` | フルDBバックアップ `02_DATABASE/_backup_session_staging_<TS>/` → 固定 DDL executescript（IF NOT EXISTS 冪等）→ `INSERT OR REPLACE`（run_id/lap_id 自然キー）→ queue 遷移（PASS/WARNING→`awaiting_gate`・FAIL→`failed`・EngineWarmup→`skipped`）→ `data_quality_log`（stage_*・apply 時のみ）+ `analysis_run_log` 1行 → **同一トランザクション内で業務6テーブル before==after assert（違反→rollback・exit 3）** → commit |
| exit code | `main()` | 0=成功 / 1=候補なし・事前チェック失敗 / 2=gate FAIL あり（隔離・部分成功）/ 3=assert 違反 rollback |

CLI: `--db`（既定=正本）`--event` `--rider` `--session` `--source-file` `--apply` `--limit` `--report` `--include-awaiting`

構文チェック: `python3 -m py_compile session_extract_staging.py build_master_db.py` → **PASS**。

## 2. 実行結果

### 2a. 全イベント dry-run（Round7 JA52・33 outing・read-only・安全確認のみ）

`python3 session_extract_staging.py --event 20260612-ROUND7-JA52` → exit 2（FAIL 隔離あり=想定通り）
レポート: `reports/session_staging_dryrun_all_20260706.md`

- 候補 **33 outing**（queue pending 2d_extract 33 と完全一致・未マッチ 0）
- circuit 推定 = **MISANO**（Report=MISANO / `.line` fallback=MISANO 両経路一致）・circuit P10 ref=None（正本 MISANO 0 laps → ④ガード skip＝本番同挙動）
- 内訳: **insert 対象 12**（PASS 8 / WARNING 4）・**FAIL 隔離 7**・**EngineWarmup skip 14**

| session | insert (PASS/WARN) | FAIL | skip | 予定 laps |
|---|---|---:|---:|---:|
| FP    | 3 (3/0) | 0 | 2 | 15 |
| QP    | 4 (3/1) | 1 (QP-05 有効ラップ0) | 2 | 14 |
| RACE1 | 1 (0/1) | 5 (R1-02〜05 有効ラップ0 + GRID01) | 2 | 19 |
| RACE2 | 1 (0/1) | 1 (GRID01) | 2 | 19 |
| WUP1  | 1 (0/1) | 0 | 3 | 6 |
| WUP2  | 2 (2/0) | 0 | 3 | 6 |
| 計    | **12** | **7** | **14** | **79** |

- WARNING は全て `stage_phase22_fill`（§44 22列の非NULL成立率<100%・Exit 系構造 NULL＝readiness §5#5 の情報記録）。FAIL は全て `stage_lap_count`（有効ラップ0）。
- 予定行数: runs_provisional=12 / laps_provisional=79 / lap_suspension_provisional=79（**本タスクでは insert しない**・33 一括 apply 禁止遵守）
- 業務6テーブル before==after（275/1202/1202/866/7613/7710）✅

### 2b. 限定 dry-run（FP のみ）

`--event 20260612-ROUND7-JA52 --session FP` → exit 0
レポート: `reports/session_staging_dryrun_fp_20260706.md`

- **5 outing**（readiness §6 の FP5 と一致）= insert 3（全 PASS）/ skip 2（ENGINEWARMUP01/02）
- FP-01: 4 laps best 99.429 / FP-02: 7 laps best 98.791 / FP-03: 4 laps best 98.364
- 予定行数 3 / 15 / 15。業務6テーブル不変 ✅

### 2c. ★限定 apply（FP のみ・初回 provisional 書込）

`--event 20260612-ROUND7-JA52 --session FP --apply` → **exit 0**
レポート: `reports/session_staging_apply_fp_20260706.md` / バックアップ: `02_DATABASE/_backup_session_staging_20260706_142625/ts24_unified.db`

| テーブル | before | after | 判定 |
|---|---:|---:|:--:|
| runs | 275 | 275 | ✅ 不変 |
| laps | 1202 | 1202 | ✅ 不変 |
| lap_suspension | 1202 | 1202 | ✅ 不変 |
| race_results | 866 | 866 | ✅ 不変 |
| pdf_lap_times | 7613 | 7613 | ✅ 不変 |
| pdf_lap_times_v2_staging | 7710 | 7710 | ✅ 不変 |
| **runs_provisional** | 0（未作成） | **3** | 新規 |
| **laps_provisional** | 0（未作成） | **15** | 新規 |
| **lap_suspension_provisional** | 0（未作成） | **15** | 新規 |

- 業務6テーブルは件数 assert（トランザクション内）に加え、**バックアップ vs apply 後の全行 sha256 照合で 6/6 IDENTICAL**（byte 同値を実証）。
- 自然キー重複: run_id 0 / lap_id 0（laps・ls 両方）。
- quality_status: 3 run / 15 lap すべて **PASS**。
- NULL 規約検証: runs_provisional の setup 33列 + comment = 全 NULL（違反0）/ lap_suspension_provisional の **WF 6列 + lap_susF_min = 全 NULL（違反0）**。0 代用なし。
- is_outlap（薄ラッパ①②③適用）: 15 laps 中 valid 12 / outlap 3。
- run_id 実例: `PROV_20260612_ROUND7_MISANO_FP_JA52_R1`（R1〜R3・時系列順）。
- queue 遷移: FP-01/02/03 → `awaiting_gate`（done は final 化時のみ・§22 準拠）、ENGINEWARMUP01/02 → `skipped`。
- `data_quality_log` に `stage_*` 29行（apply 時のみ書込）、`analysis_run_log` に success 1行。
- テーブル形状: runs_provisional 55列（49+6）/ laps_provisional 22列（16+6）/ lap_suspension_provisional 75列（69+6）＝固定 DDL どおり。

### 2d. 冪等性再実行

`--apply --include-awaiting`（同一 FP スコープ・queue は awaiting_gate のため検証フラグで再投入）→ exit 0

- provisional 件数 **3 / 15 / 15 のまま不変**（INSERT OR REPLACE・行は増えない）・重複 0
- `stage_hash_idempotent` が「同一 source_manifest_hash 取込済→REPLACE」を検知
- 業務6テーブル不変（275/1202/1202/866/7613/7710）✅
- レポート: `reports/session_staging_apply_fp_rerun_20260706.md` / バックアップ `_backup_session_staging_20260706_142715/`

### 2e. Workbench 回帰（offscreen smoke・Workbench 無改修）

- `QT_QPA_PLATFORM=offscreen` で `MainWindow(db)` 構築 → **7 タブ**
  （⚡ Quick Log / 📋 Problem Log / 💬 Comment Analysis / 🔧 Setup Decision / 🦾 Suspension/Posture / 🏁 Race Analysis / 📥 Import / Quality）→ PASS・無回帰。
- `ts24_workbench.py` は本タスクで**未編集**（overlay=Task 5 は別承認のまま）。GUI 最終目視は Tatsuki ローカル。

## 3. rollback

```sql
-- (a) 全撤去（業務テーブル無影響・DDL ファイル末尾コメントと同一）
DROP TABLE IF EXISTS lap_suspension_provisional;
DROP TABLE IF EXISTS laps_provisional;
DROP TABLE IF EXISTS runs_provisional;
-- （index は DROP TABLE で同時に消える）

-- (b) イベント単位クリア（final 化後の通常運用）
DELETE FROM lap_suspension_provisional WHERE provisional_event_key='20260612-ROUND7-JA52';
DELETE FROM laps_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';
DELETE FROM runs_provisional           WHERE provisional_event_key='20260612-ROUND7-JA52';

-- (c) queue の巻き戻し（再処理可能化）
UPDATE import_queue SET status='pending', started_at=NULL, finished_at=NULL,
       analysis_run_id=NULL, error=NULL
 WHERE target_kind='2d_extract' AND file_path LIKE '%20260612-ROUND7-JA52%FP-%';
```

- フル差し戻し: `02_DATABASE/_backup_session_staging_20260706_142625/ts24_unified.db` から DB ごと復元も可能。
- 業務テーブルは構造上到達しない（別テーブル + before==after assert + sha256 実証の三重確認）。

## 4. Multi-agent operating check

- **Extraction**: 本番 `discover_outings`/`gated_outings`/`extract_outing`/`session_canon_2d`/circuit 推定を import 再利用。パーサ二重実装ゼロ（再実装は is_outlap 薄ラッパのみ・readiness §2e 通り）。
- **Quality Gate**: dry-run 既定・8 チェック・FAIL 7 outing を隔離（INSERT 0 行）・`data_quality_log` へ stage_* 記録・0≠NULL 厳守（zero-leak 0 実測）。
- **DB Integrity**: provisional 3テーブル分離・UNIQUE 自然キー・INSERT OR REPLACE 冪等（再実行で 3/15/15 不変）・業務6テーブル before==after assert + sha256 6/6 IDENTICAL・フルバックアップ2世代・rollback=DROP/DELETE。
- **Operations**: 初回 apply は **FP 1 session 限定（3 run/15 laps）**。33 outing 一括は dry-run のみで未 insert（禁止遵守）。
- **Supervisor**: Workbench/Report/Supabase/DB Master/push/final 化には未到達（下記 §5）。
- **Documentation**: 本レポート + 実行 md 4本 + CLAUDE.md/Obsidian 記録は親セッションで反映。
- **Tatsuki=決める**: 残 session（QP/RACE1/RACE2/WUP1/WUP2）の apply は別 GO。

## 5. 未実施リスト（本タスクのスコープ外・各別承認）

- Workbench overlay（`PostureAnalysisTab._load_data` の final+provisional UNION・⏳ prov マーク）= Task 5
- Report v2 provisional モード（cover リボン・filename トークン）= Task 6
- **残 session の apply**（QP 4 / RACE1 1 / RACE2 1 / WUP1 1 / WUP2 2 = insert 候補 9 outing・64 laps。dry-run 検証済み・段階投入は別 GO）
- FAIL 7 outing（QP-05・R1-02〜05・GRID×2＝有効ラップ0）の原因確認（現状は隔離のみ・queue は pending のまま）
- Supabase sync / remote_extra 24 cleanup
- DB Master 再生成
- origin push（session_extract_staging.py ほか未コミット）
- final 化（full rebuild + 決定論ゲート + cutover + provisional クリア）
