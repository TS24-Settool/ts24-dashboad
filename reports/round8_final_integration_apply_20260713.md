# ROUND8 Final Integration — Phase 2/3 Apply Report

Date: 2026-07-13
Agent: Track A Phase 2 execution agent (Fable 5)
Authorization: Tatsuki inbox task 2026-07-13 (P0, 実行承認済) — local canonical DB apply + Workbench verification.
Ground truth: `reports/round8_final_integration_readiness_20260713.md` (Phase 1 audit) + supervisor decision on §3c.
Out of scope (未実施・FORBIDDEN のまま): Supabase / DB Master / git commit-push / 歴史的 queue クリーンアップ / CLAUDE.md・Obsidian 更新（supervisor 担当）/ pdf_lap_times_v2_staging への ROUND8 反映（別スコープ）。

Canonical DB: `02_DATABASE/ts24_unified.db`
- sha256 BEFORE (== Phase 1 audit と同一・無変更を確認してから着手): `2eedecbd04f822e835a917e9fc4256907996acee5b5194229d8b530834a5cc22`
- sha256 AFTER (3 apply 完了後): `977baad8c4e9b02f7471977b307a135c60d221ba4ef0389b1b8fe1a1ed47088d`

---

## 1. 実行サマリ（strict order で実施）

| # | Step | Tool | Result |
|---|---|---|---|
| 0 | Scratch 再構築 + Phase 1 ゲート再検証 | `build_master_db.py --all --round ROUND8 --out /tmp/ts24_r8_scratch.db` | 受入ゲート 0件 PASS / DONINGTON only / 137/137 provisional 一致 |
| 1 | dry-run（両ツール） | `apply_round8_targeted_insert.py` / `apply_round8_race_results.py` | ALL PASS（証跡 §7） |
| 2 | race_results apply | `apply_round8_race_results.py --apply` | insert=74 / update=0 / 866→940 / 非対象不変 ✅ |
| 3 | telemetry targeted insert | `apply_round8_targeted_insert.py --scratch /tmp/ts24_r8_scratch.db --apply` | +16 runs / +144 laps / +144 ls → 302/1423/1423、全 invariant PASS |
| 4 | provisional clear | `apply_round8_provisional_clear.py --apply` | prov 15/137/137 → 0/0/0、canonical 不変 ✅ |
| 5 | Workbench Phase 3 検証 | offscreen smoke（§6） | ALL PASS |

新規作成ツール（3本・いずれも既定 dry-run / 明示列リスト / 単一トランザクション / WAL-safe backup / PASSIVE checkpoint / busy_timeout=30000 / invariant 失敗で自動 ROLLBACK）:
- `05_SCRIPTS/apply_round8_race_results.py`（§36 Round7 版の一般化: ROUND8 dir・DONINGTON 物理レンジ 85–115s・round リテラル）
- `05_SCRIPTS/apply_round8_targeted_insert.py`（§65 Round7 版の一般化: SX 除外・RACE2=0 assert・§3c 補正・placeholder DELETE なし）
- `05_SCRIPTS/apply_round8_provisional_clear.py`（canonical 等価性ゲート付きクリア）

`ts24_workbench.py` は無変更（別エージェントの extraction_scan.py / session_extract_staging.py 差分はスコープ外として無視）。

## 2. Before / After counts

### 2a. テーブル別

| table | before | after | Δ | 備考 |
|---|---:|---:|---:|---|
| runs | 286 | **302** | +16 | ROUND8 telemetry |
| laps | 1279 | **1423** | +144 | |
| lap_suspension | 1279 | **1423** | +144 | |
| race_results | 866 | **940** | +74 | ROUND8 6 PDF（RACE2 official 含む） |
| pdf_lap_times | 7613 | 7613 | 0 | protected・不変 assert PASS |
| pdf_lap_times_v2_staging | 7710 | 7710 | 0 | protected（ROUND8 v2 staging はスコープ外） |
| metric_version_log | 32 | 32 | 0 | protected |
| source_file_registry | 439 | 439 | 0 | protected |
| data_quality_log | 4042 | 4042 | 0 | protected |
| analysis_run_log | 24 | 24 | 0 | protected |
| race_lap_detail (VIEW) | 12763 | 12763 | 0 | VIEW intact |
| runs_provisional | 15 | **0** | −15 | ROUND8 event key のみ削除 |
| laps_provisional | 137 | **0** | −137 | |
| lap_suspension_provisional | 137 | **0** | −137 | |
| import_queue | 430 | 430 | 0行 | 状態遷移のみ（§5） |

### 2b. ROUND8 telemetry — rider × session（canonical 実測）

| rider | session | runs | laps | best_lap_s | source |
|---|---|---:|---:|---:|---|
| JA52 | FP | 2 | 21 | 89.960 | ORIGINAL+2D |
| JA52 | QP | 3 | 18 | 89.123 | ORIGINAL+2D |
| JA52 | WUP1 | 1 | 7 | 89.202 | ORIGINAL+2D |
| JA52 | WUP2 | 1 | 7 | 89.994 | ORIGINAL+2D |
| JA52 | RACE1 | **1** | 20 | 89.195 | ORIGINAL+2D（§3c 補正済 C106） |
| DA77 | FP | 2 | 19 | 89.960 | 2D_ONLY |
| DA77 | SP | 3 | 18 | 89.622 | 2D_ONLY |
| DA77 | WUP1 | 1 | 7 | 90.105 | 2D_ONLY |
| DA77 | WUP2 | 1 | 7 | 89.885 | 2D_ONLY（provisional 未経由・staging dry-run 照合済） |
| DA77 | RACE1 | 1 | 20 | 89.738 | 2D_ONLY |
| **計** | | **16** | **144** | | lap_suspension も 144（run 毎 laps==ls 一致） |

### 2c. ROUND8 race_results — session 別（74行）

| session_type | rows | 備考 |
|---|---:|---|
| FP | 2 | チームのみ #52 pos11 89.954 / #77 pos12 89.961 |
| QP | 2 | #52 pos4 89.128 / #77 pos13 89.622（DA77 の SP は QP PDF がカバー — readiness §2/§5 のマッピング通り session_type='QP'） |
| WUP1 | 2 | #52 pos3 89.206 / #77 pos21 90.109 |
| WUP2 | 2 | #52 pos24 89.997 / #77 pos19 89.888 |
| RACE1 | 33 | フルフィールド。#52 pos3 89.205 / #77 pos12 89.739 |
| RACE2 | 33 | フルフィールド（official PDF のみ・telemetry なし）。#52 pos6 89.040 / #77 pos14 89.493 |

自然キー (round, session_type, rider_num)・既存衝突 0・INSERT 74 / UPDATE 0・data_scope='TS24_PRIVATE'。

## 3. Assert / invariant 結果（全 PASS）

Dry-run ゲート（targeted insert・G1–G8）:
- G1 circuit: non-DONINGTON=0, %PARK%=0 → PASS
- G2 scratch RACE2 runs=0 → PASS
- G3 provisional lap 突合: compared=137 matched=137 prov_total=137 → PASS（lap_time_s/susf_mean/susr_mean/f_dive_spd/r_dive_spd, |Δ|≤1e-6）
- G4 DA77 WUP2 vs staging dry-run: n_laps=7 best=89.885 → PASS
- G5 best_lap_s 期待表（16 runs, ±0.001）mismatch=0 → PASS
- G6 setup: JA52 NULL-setup=0 / DA77 with-setup=0（2D_ONLY exempt）→ PASS
- G7 §3c 材料: ghost R2 = C106/0 laps, R1 = 20 laps → PASS
- G8 canonical 事前状態: ROUND8=(0,0,0), NA_ rows present, totals 286/1279/1279 → PASS
- schema: 3テーブル列集合一致（lap_suspension は §44 ALTER により物理順のみ相違 — 明示列名 INSERT で順序非依存）

Apply 内 invariant（トランザクション内・違反で自動 ROLLBACK、発火なし）:
- protected 12テーブル/VIEW count 不変（race_results はこの段階で 940 スナップショット）
- totals = 302/1423/1423、ROUND8 shape = (16,144,144)
- ROUND8 RACE2 rows（runs/laps/ls）= 0/0/0、session='SX' = 0、run_id LIKE '%\_SX\_%' = 0
- circuit = DONINGTON のみ、DONINGTONPARK = 0
- orphan laps=0 / orphan ls=0 / duplicate run_id=0 / duplicate lap_id=0 / ROUND8 各 run で laps==lap_suspension
- JA52 RACE1 = 正確に 1 run、setup (f_set_c,f_spr_l,f_spr_r,r_spr) = ('C106','9','9','84')、ghost R2 不存在
- NA_DONINGTON_RACE1/RACE2_JA52_R1（2025-era, C104）無変更で存在
- RACE1 R1 の 20 lap_suspension 行の wf_* 6列 = C106 再計算値と完全一致
- 非 ROUND8 行 byte-identity: 3テーブル全列 sha256 スナップショット before==after

Provisional clear ゲート:
- canonical ROUND8 = (16,144,144) PASS / 137 provisional lap 全てが canonical に値一致の対応行 PASS / RACE1 R1=C106 PASS
- クリア後: prov (0,0,0)、canonical 全業務テーブル count 不変、queue failed 4件保持

事後 read-only 再検証（apply 後 + 最終再確認 2回実施）: totals 302/1423/1423/940、ROUND8 16/144/144/74、RACE2 0、SX 0、prov 0/0/0、PROV_ 0、PARK 0、protected 7613/7710/32、RACE1 R1-only C106+comment、NA rows C104 intact — **ALL PASS**。

## 4. §3c 補正の証跡（supervisor decision 実装）

問題: Original の 2025 BSB Donington RACE1/RACE2 行（C104）が 2026 ROUND8 行（C106）と自然キー完全衝突（RIDER,CIRCUIT,SESSION,RUN — Original に round/date 列なし）。scratch build は RACE1 telemetry R1 に 2025 C104 を誤付与し、正しい 2026 C106 を 0-lap ORIGINAL-only ghost R2 に付けていた。

実装（原本 Data_Base_TS24_ORIGINAL.xlsx は読み取り専用・無変更）:
1. **R1 に C106 payload を接合して insert**: ghost R2 の ORIG_FIELDS 33列（weather〜tyre_rear）を R1 行に差し替え。telemetry 値（n_laps=20, best 89.195, comment=Report RACE1 コメント）は R1 のまま。
2. **ghost R2（20260710_ROUND8_DONINGTON_RACE1_JA52_R2）は insert しない**（2025 重複行のアーティファクト）。
3. **既存 canonical NA_DONINGTON_RACE1/RACE2_JA52_R1（2025-era, round='', C104, 0 laps）は無削除・無変更**。
4. **RACE2 telemetry は不在のまま** — 2026 C106 RACE2 setup は canonical 上未表現（documented; Race2 2D 到着後の finalization で扱う）。

**wf_* の扱い（再計算を実施）**: C104 と C106 でバネレートが実際に異なる（C104: F 8.5/9.0 → fspr=8.75, R 90 / C106: F 9.0/9.0 → fspr=9.0, R 84）。scratch は R1 の 20 lap の wf_* を C104 レートで計算していたため、insert 時に build_master_db._build_lap_suspension と同一式で **C106 レートにより再計算**した:
- WF_F = susp_mm × (f_spr_l+f_spr_r)/2 = susp × **9.0**（対象: wf_f_apex_n / wf_f_brk_n / wf_f_ce_n ← apex/brk/ce_susF_avg）
- WF_R = susp_mm × r_spr × 0.5 = susp × **42.0**（対象: wf_r_apex_n / wf_r_brk_n / wf_r_ce_n ← apex/brk/ce_susR_avg）
- 丸めも同一（Python round(…,1)）。apply 内 assert で 20行全列一致を検証（サンプル: apex_susF 64.1→576.9, apex_susR 11.28→473.8 = ×9.0/×42.0 一致）。

Canonical 実測（after）: `20260710_ROUND8_DONINGTON_RACE1_JA52_R1` = 20 laps / best 89.195 / C106 / f_spr 9,9 / r_spr 84 / rider comment 保持。ROUND8 RACE1 JA52 R2 = 0行。

## 5. Rejected / 非対象ソース（全件・理由付き）

| Source | 処置 | 理由 / 終端状態 |
|---|---|---|
| SX_F1-#77-01.MES (+zip) | **除外**（insert せず） | FAIL 隔離済み partial フォルダ・F1-#77-01 の telemetry 重複（13 laps, 89.960）。queue status=**failed 保持**（証拠） |
| SX_SP-#77-03.MES (+zip) | **除外** | 同上・SP-#77-03 重複（8 laps, 89.622）。queue **failed 保持** |
| WU1-#77-01.MES | **除外** | zero-valid-lap（out-lap のみ 4.1MB）。queue **failed 保持** |
| WU1-#77-02.MES | **除外** | zero-valid-lap。queue **failed 保持** |
| SP-77-03（# なし名称変種） | **除外** | registry status=**incomplete 保持**・分析CSV混入の非標準重複フォルダ・queue 未投入のまま |
| RACE1 ghost R2（scratch 内） | **insert せず** | §3c: 2025 Original 重複行アーティファクト（0-lap） |
| JA52/DA77 Race2 .MES | **不存在**（宣言済み欠落） | RACE2 telemetry = 0 を hard assert。official PDF は race_results に反映済み |
| DA77 ROUND8 Report | 不存在 | 2D_ONLY パス（setup/wf NULL）— 従来ラウンドと同一慣行 |

Queue 遷移（ROUND8 source 限定・歴史的変更なし）:
- 2d_extract awaiting_gate 15件 → **done**（note: promoted to canonical final 20260713）
- 2d_extract pending 1件（WU2-#77-01・provisional 未経由）→ **done**（note: promoted via final integration, never provisional）
- 2d_extract failed 4件 → **不変**（証拠保持）
- report_import 1件・pdf_extract 4件の pending → **不変**（queue consumer 経路未実装のため。データ自体は本 final integration で反映済み: Report→targeted insert 経由 / PDF→race_results 経由。WUP2/RACE2 PDF はそもそも未 queue） 

## 6. Phase 3 — Workbench 検証（QT_QPA_PLATFORM=offscreen・ts24_workbench.py 無変更）

証跡: `reports/round8_workbench_smoke_20260713.log` — **ALL WORKBENCH CHECKS PASS**

- **7 タブ全構築 OK**: ⚡Quick Log / 📋Problem Log / 💬Comment Analysis / 🔧Setup Decision / 🦾Suspension/Posture / 🏁Race Analysis / 📥Import/Quality（各 refresh() も例外なし）
- **DONINGTON final 可視**: Posture overlay df = 1423行・data_stage 全て 'final'・PROV_ 行 0。DONINGTON = 144 laps / 16 runs / sessions FP,QP,SP,WUP1,WUP2,RACE1。Run Filter の DONINGTON run リスト = 16件・⏳(prov) ラベル 0・重複 0。
- **Race2 は telemetry を出せない**: DONINGTON スコープの session コンボに RACE2 が存在しない（選択不能）。overlay df の DONINGTON×RACE2 行 = 0（Race1/provisional 行の漏出経路なし — provisional はDB上 0行）。
- **チャート表示 139/144 laps の説明**: 5 laps（FP-JA52-R2 L7, RACE1-DA77 L20, RACE1-JA52 L19, WUP2-DA77 L7, WUP2-JA52 L7 = 全て in-lap）は FULL_BRAKING ゾーンサンプルなし（brk_susF_avg NULL）のため、既存の物理 validity フィルタ（NaN 除外）でチャートから隠れる。**DB には 144 laps 全て存在**・全ラウンド共通の既存表示挙動であり欠損ではない。
- **Race Analysis の ROUND8 実際の表示（事実のみ）**: Race Analysis のラップ明細ソースは `race_lap_detail` VIEW（v2 staging PASS + legacy pdf_lap_times）。ROUND8 行は **v2 staging にも pdf_lap_times にも 0**（ROUND8 の v2 staging apply は本スコープ外・未実施）。そのため **round コンボに ROUND8 自体が出現せず**、Race Analysis では ROUND8 RACE1/RACE2 のラップ明細は現状表示されない。ROUND8 の official 結果（RACE2 フルフィールド 33行含む）は race_results テーブルに存在し、他タブ（Performance 等の race_results 参照系）からは利用可能。⇒ Race2 が Race1/provisional データを表示する経路は存在しない（fail-safe に不可視）。ラップ明細を Race Analysis に出すには別承認の pdf_v2_scratch_gate → apply_pdf_v2_staging 経路が必要（readiness §8 の手順どおり）。

## 7. Dry-run / apply 証跡ファイル

- `reports/round8_targeted_insert_dryrun_20260713.log`（GATES ALL PASS・plan 16/144/144）
- `reports/round8_race_results_dryrun_20260713.log`（74候補・Gate ALL PASS）
- `reports/round8_provclear_dryrun_pre_20260713.log`（apply 前 fail-closed 動作確認 EXIT=2）
- `reports/round8_race_results_apply_20260713.log`
- `reports/round8_targeted_insert_apply_20260713.log`
- `reports/round8_provclear_dryrun_post_20260713.log` / `reports/round8_provclear_apply_20260713.log`
- `reports/round8_workbench_smoke_20260713.log`

## 8. バックアップと正確な rollback 手順

各 write 段の直前に PASSIVE wal_checkpoint 後、db+wal+shm の 3ファイルをフルコピー（WAL-safe）:

| 段階 | バックアップ（02_DATABASE/ 配下） | 復元するとどうなるか |
|---|---|---|
| race_results apply 前 | `_backup_round8_rr_20260713_010310/` | 全 3 apply 取り消し（Phase 1 監査時点 = sha 2eedecbd… に戻る） |
| telemetry insert 前 | `_backup_round8_targeted_20260713_010320/` | telemetry + provisional clear 取り消し（race_results 940 は保持） |
| provisional clear 前 | `_backup_round8_provclear_20260713_010332/` | provisional 15/137/137 と queue 状態のみ復元 |

Rollback コマンド（Workbench 等の DB writer を全て閉じてから・<DIR> に上表のディレクトリ名）:
```bash
cd "/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE"
rm -f ts24_unified.db ts24_unified.db-wal ts24_unified.db-shm
cp "<DIR>/ts24_unified.db"      ts24_unified.db
cp "<DIR>/ts24_unified.db-wal"  ts24_unified.db-wal   # 存在する場合
cp "<DIR>/ts24_unified.db-shm"  ts24_unified.db-shm   # 存在する場合
```

## 9. Tatsuki への follow-up note

> Original の 2025 BSB Donington RACE1/RACE2 行 (C104) は ROUND8 行と自然キー衝突するため、原本側での区別 (例: CIRCUIT を DONINGTON_BSB25 に改名) を推奨 — 原本は読み取り専用のため Code は変更していない。Race2 2D 到着後の finalization 時に同じ衝突が再発する点に注意。

補足: 今回は supervisor decision により apply ツール側で補正（RACE1 R1 へ C106 接合・ghost R2 非投入・wf_* C106 再計算）した。Race2 2D が届いた時点で原本が未修正だと、Race2 の telemetry R1 にまた 2025 C104 が付く同一機構が発火する。2026 C106 の RACE2 setup は現状 canonical 上に未表現（NA_DONINGTON_RACE2_JA52_R1 は 2025 C104 のまま保全）。

## 10. 残タスク（別承認・別スコープ）

- ROUND8 の pdf_lap_times_v2_staging 反映（`pdf_v2_scratch_gate.py --all` → `apply_pdf_v2_staging.py`）→ Race Analysis に ROUND8 ラップ明細が出るようになる
- Race2 2D 到着後の finalization（§9 の衝突注意）
- CLAUDE.md / Obsidian（CURRENT_STATE, AI_HANDOFF_LATEST, log, inbox Result）更新 = supervisor 担当
- Supabase / DB Master / git push = FORBIDDEN のまま

---

## 11. 追補（2026-07-13 追加実行）— ROUND8 v2 staging 反映（Race Analysis 可視化）

Coordinator 指示: code instruction の「approved v2 path」経由の Result PDF ラップ明細反映と
Phase 3 item 4（Race2 Race Analysis = official/PDF データ）を完了させる。§10 の残タスク 1 を本セッションで実施済み。

### 11a. Gate（read-only・/tmp scratch）

`python3 pdf_v2_scratch_gate.py --all`（正本 mode=ro・業務テーブル before==after 不変 ✅・対象 PDF 57本）:
- 全体: rider-session PASS=556 / WARNING=1076 / FAIL=16（真値 = race_results 940、ROUND8 +74 反映済みのため ROUND8 が判定可能に）
- **ROUND8 RACE1: PASS 31 riders（552 lap行）/ WARNING 2**・**RACE2: PASS 32 riders（562 lap行）/ WARNING 1**
- チーム: RACE1 #52 PASS 19laps best 89.205 / #77 PASS 19laps 89.739、RACE2 #52 PASS 19laps 89.040 / #77 PASS 19laps 89.493 — race_results と完全一致
- **既存ラウンド回帰 0**: 全 prior round×RACE の新 scratch PASS 行数 == canonical staging 現行行数（ROUND1〜ROUND7/11/12 全一致、17区分）
- Gate レポート: `reports/pdf_v2_gate_20260713.md`

### 11b. staging dry-run

`python3 apply_pdf_v2_staging.py`（既定 RACE1,RACE2 × PASS）:
- 候補 = **8824 行**（= 既存 7710 の自然キー同値 REPLACE + **ROUND8 新規 1114**）/ 524 rider-session / seg 充填 6165
- 検査: 自然キー重複 0 / date NULL 0 / lap_time_s NULL 0 / 来歴欠落 0 / **物理レンジ外 0**
- 物理レンジは rider-session best 相対（best×[0.90,1.60]）で race_results 由来の実測 best を基準にした相対判定 — 固定絶対レンジではなく、DONINGTON ~89s ラップはそのまま PASS（拒否なし・STOP 条件非該当）

### 11c. apply

- 事前 WAL-safe バックアップ（PASSIVE checkpoint → db+wal+shm）: `02_DATABASE/_backup_round8_v2staging_20260713_075631/`
- ツール自体のバックアップ（main db のみ）: `02_DATABASE/_backup_pdf_v2_staging_20260713_075640/`
- `python3 apply_pdf_v2_staging.py --apply` → staging 8824 行・業務テーブル不変 assert ✅（ログ: `reports/round8_v2staging_apply_20260713.log`）

事後検証（mode=ro）:
- 業務テーブル不変: runs 302 / laps 1423 / lap_suspension 1423 / race_results 940 / pdf_lap_times 7613 — 全 PASS
- pdf_lap_times_v2_staging: 7710 → **8824**（+1114、非 ROUND8 行 7710 不変）
- `race_lap_detail` VIEW: 12763 → **13877**。ROUND8 = **1114 行**（RACE1 552×31 riders / RACE2 562×32 riders、全て source_tag='v2'）。チーム #52/#77 各 19 laps × RACE1/RACE2
- provisional 0/0/0 のまま・PROV_ 0

### 11d. Workbench（offscreen 再検証）

- Race Analysis round コンボに **ROUND8 出現**、session = RACE1/RACE2
- **ROUND8 RACE2 選択 → PDF 由来ラップ明細 562行/32 riders 表示**（#52 19laps best 89.040 / #77 19laps 89.493）、_refresh_charts() 例外なし
- telemetry 捏造なし: Suspension/Posture は DONINGTON 144 laps / 16 runs のまま・**RACE2 telemetry 0 行**・PROV_ 0（Race2 の Sus/Posture は引き続き absent/pending）

### 11e. Rollback（本追補分のみ）

```bash
# 方法A（推奨・staging は追加のみなので ROUND8 行を削除すれば元どおり）
sqlite3 "/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db" \
  "DELETE FROM pdf_lap_times_v2_staging WHERE round='ROUND8';"   # 8824 → 7710

# 方法B（フル復元）
cd "/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE"
rm -f ts24_unified.db ts24_unified.db-wal ts24_unified.db-shm
cp _backup_round8_v2staging_20260713_075631/ts24_unified.db* .
```

（§10 の残タスク 1 は完了。Race2 2D finalization / CLAUDE.md・Obsidian 更新 / Supabase / DB Master / push は引き続き別スコープ。）
