# Round7 JA52 残session provisional apply — Readiness（Phase B-4）

- 日付: 2026-07-06
- 作成: Claude Code（委任エージェント・read-only 実行）
- 対象: `20260612-ROUND7-JA52` の残り 5 session（QP / WUP1 / WUP2 / RACE2 / RACE1）
- スクリプト: `05_SCRIPTS/session_extract_staging.py`（Phase B-2 実装、既定 dry-run・正本DB `mode=ro`）
- 前提: FP は B-2 で apply 済（provisional 3/15/15、`PROV_20260612_ROUND7_MISANO_FP_JA52_R1..R3`、queue=awaiting_gate）
- 参照: `reports/race_weekend_session_staging_apply_20260706.md`（B-2 baseline）

## 0. 目的 / ゲート

- 目的: 残り 5 session の 2D outing を provisional 3 テーブル（runs/laps/lap_suspension `_provisional`）へ隔離投入する準備確認。業務 6 テーブルは一切変更しない。
- **実装ゲート: 「Round7 remaining session provisional apply GO」受領まで apply 禁止。本書は readiness のみ（DB 無変更）。**
- git 管理: 本ディレクトリは git 非管理（`git status` → `fatal: not a git repository`）。ファイル差分管理はバックアップ方式（下記 §6）。

## 1. 現DB状態（実測・mode=ro・2026-07-06）

業務 6 テーブル:

| table | count |
|---|---:|
| runs | 275 |
| laps | 1202 |
| lap_suspension | 1202 |
| race_results | 866 |
| pdf_lap_times | 7613 |
| pdf_lap_times_v2_staging | 7710 |

provisional 3 テーブル: runs_provisional=3 / laps_provisional=15 / lap_suspension_provisional=15
（FP R1=4, R2=7, R3=4 lap、全 run quality_status=PASS）

重複チェック:
- `runs.run_id LIKE 'PROV_%'` → 0 件（正本と非衝突）
- runs_provisional 内 run_id 重複 → 0 件
- laps_provisional.lap_id と laps.lap_id の JOIN → 0 件

import_queue（Round7 JA52・target_kind='2d_extract'、計 33 件）:

| status | 件数 | 内訳 |
|---|---:|---|
| awaiting_gate | 3 | FP-01/02/03（B-2 apply 済） |
| skipped | 2 | FP-ENGINEWARMUP01/02（B-2 apply 時に確定） |
| pending | 28 | QP 7 / RACE1(R1) 8 / RACE2(R2) 4 / WUP1 4 / WUP2 5 |

## 2. session別 dry-run 再実行結果（B-2 比較）

全 dry-run は `--apply` 無し・`mode=ro`・DB 無変更を確認済（レポート内 before==after ✅）。
exit=2 は「gate FAIL outing あり（隔離・INSERT せず）」の仕様どおりで正常。

### 2.1 full event（`--event 20260612-ROUND7-JA52`、exit=2）

候補 28 outing = insert 9 / FAIL 隔離 7 / EngineWarmup skip 12 / queue 未マッチ 0。
予定行数: runs=9 / laps=64 / lap_suspension=64 → **B-2 baseline（9 outing / 64 laps）と完全一致、ドリフトなし**。
**FP は候補に出現しない**（status=awaiting_gate のため。`--include-awaiting` を付けない限り対象は pending のみ — script L98 で確認。冪等性 OK）。

### 2.2 session 別（各 `--session <S>` 単独実行）

| session | exit | insert (outing/laps) | PASS | WARNING | FAIL | EW skip | B-2 比較 |
|---|---:|---|---:|---:|---:|---:|---|
| QP | 2 | 4 / 14 | 3 | 1 | 1 | 2 | 一致・差分なし |
| WUP1 | 0 | 1 / 6 | 0 | 1 | 0 | 3 | 一致・差分なし |
| WUP2 | 0 | 2 / 6 | 2 | 0 | 0 | 3 | 一致・差分なし |
| RACE2 | 2 | 1 / 19 | 0 | 1 | 1 | 2 | 一致・差分なし |
| RACE1 | 2 | 1 / 19 | 0 | 1 | 5 | 2 | 一致・差分なし |
| **計** | — | **9 / 64** | 5 | 4 | 7 | 12 | **B-2 baseline と完全一致** |

insert 対象の run_id / lap 数 / best:

| base | run_id | laps | best | gate |
|---|---|---:|---:|:--:|
| QP-JA52-01 | PROV_20260612_ROUND7_MISANO_QP_JA52_R1 | 4 | 97.953 | PASS |
| QP-JA52-02 | PROV_20260612_ROUND7_MISANO_QP_JA52_R2 | 3 | 98.250 | PASS |
| QP-JA52-03 | PROV_20260612_ROUND7_MISANO_QP_JA52_R3 | 5 | 97.636 | PASS |
| QP-JA52-04 | PROV_20260612_ROUND7_MISANO_QP_JA52_R4 | 2 | 101.714 | WARNING (stage_phase22_fill) |
| WUP1-JA52-01 | PROV_20260612_ROUND7_MISANO_WUP1_JA52_R1 | 6 | 98.109 | WARNING (stage_phase22_fill) |
| WUP2-JA52-01 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R1 | 4 | 98.160 | PASS |
| WUP2-JA52-02 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R2 | 2 | 98.045 | PASS |
| R2-JA52-01 | PROV_20260612_ROUND7_MISANO_RACE2_JA52_R1 | 19 | 97.778 | WARNING (stage_phase22_fill) |
| R1-JA52-01 | PROV_20260612_ROUND7_MISANO_RACE1_JA52_R1 | 19 | 98.055 | WARNING (stage_phase22_fill) |

WARNING は stage_phase22_fill（Phase22 充足率）のみで、gate 仕様上 insert 対象（FAIL のみ隔離）。

## 3. 投入順と理由

**推奨順: QP → WUP1 → WUP2 → RACE2 → RACE1（session 単位・逐次・予期しない差分で停止）**

- QP 先行: insert 4 outing と最多で、run_id 採番（R1..R4）・WARNING 混在・FAIL 隔離（1 件）の全パターンを最初に検証できる。
- WUP1/WUP2: 小規模（1〜2 outing）で差分検証が容易。WUP1 は WARNING のみ、WUP2 は PASS のみ。
- RACE2 → RACE1: RACE1 は FAIL 5 件（R1-02..05, GRID01）を含む最重量 session のため最後。RACE2（FAIL 1 件）で race 系の挙動を先に確認する。
- dry-run 結果からこの順を変更すべき所見なし（inbox 提案どおりで妥当）。

## 4. 期待値（全 session 成功時）

| 対象 | before | delta | after |
|---|---:|---:|---:|
| runs_provisional | 3 | +9 | **12** |
| laps_provisional | 15 | +64 | **79** |
| lap_suspension_provisional | 15 | +64 | **79** |
| 業務 6 テーブル | §1 のとおり | ±0 | 不変（script 内 assert、違反時 rollback・exit 3） |

import_queue 期待遷移（Round7 JA52）: pending 28 → 0（awaiting_gate +9=12 / failed +7 / skipped +12=14）。

## 5. 除外の内訳と理由

### FAIL 7 件（stage_lap_count=FAIL: valid laps=0 → 隔離・INSERT せず、apply 時 queue status='failed'）

| base | session | 理由 |
|---|---|---|
| QP-JA52-05 | QP | 有効 lap 0（計測 outing 不成立） |
| R1-JA52-02 / 03 / 04 / 05 | RACE1 | 有効 lap 0（レース本走行は R1-01 のみ。短時間 outing/計測断片） |
| R1-JA52-GRID01 | RACE1 | グリッド移動のみ・有効 lap 0 |
| R2-JA52-GRID01 | RACE2 | グリッド移動のみ・有効 lap 0 |

### EngineWarmup 14 件（skip: "EngineWarmup / no valid laps"）

- 今回 pending 分 12 件: QP×2 / RACE1×2 / RACE2×2 / WUP1×3 / WUP2×3
- FP×2 件は B-2 apply 時に既に skipped 確定済 → **イベント合計 14 件で B-2 と一致**（今回の dry-run 表示が 12 なのは FP 分が候補外になったためで、差分ではない）。

## 6. Rollback（session 単位）

apply 前バックアップ: script が **apply 実行時に自動で** `02_DATABASE/_backup_session_staging_<TS>/ts24_unified.db` へフルコピーを作成する（`do_apply()` 冒頭、shutil.copy2 — コード確認済）。最終手段はこのファイルでの丸ごと復元。

session 単位 SQL rollback（`<SESSION>` = QP / WUP1 / WUP2 / RACE2 / RACE1、queue の path prefix は QP- / WUP1- / WUP2- / R2- / R1-）:

```sql
-- provisional 3 テーブルから当該 session を削除
DELETE FROM lap_suspension_provisional WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';
DELETE FROM laps_provisional           WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';
DELETE FROM runs_provisional           WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';

-- queue status を pending へ戻す（awaiting_gate/failed/skipped とも当該 apply で更新されるため一括リセット）
UPDATE import_queue
   SET status='pending', started_at=NULL, finished_at=NULL, analysis_run_id=NULL, error=NULL
 WHERE target_kind='2d_extract'
   AND file_path LIKE '%20260612-ROUND7-JA52/<PREFIX>-JA52-%'
   AND status IN ('awaiting_gate','failed','skipped');
```

注意: RACE1 の `R1-` prefix は他 session と衝突しない（フォルダ内命名は R1-/R2- のみ race 系）。FP は rollback 対象外（B-2 確定分）— FP を巻き込まないこと。

## 7. Phase C 手順（GO 受領後・session 毎）

各 session（QP → WUP1 → WUP2 → RACE2 → RACE1）で以下を繰り返す。**予期しない差分が出たら即停止・報告**。

1. dry-run: `python3 session_extract_staging.py --event 20260612-ROUND7-JA52 --session <S>` → 本書 §2.2 と同値であること（exit 0 or 2 のみ許容）
2. backup: script 自動（`_backup_session_staging_<TS>/`）— apply ログでパスを記録
3. apply: 同コマンド + `--apply`（1 トランザクション・業務 6 assert 内蔵）
4. 業務 6 不変: §1 の 6 カウント再測定 → 完全一致
5. 増分確認: provisional 3 テーブルが §4 の per-session delta どおり（QP +4/14/14、WUP1 +1/6/6、WUP2 +2/6/6、RACE2 +1/19/19、RACE1 +1/19/19）
6. dup 0: `PROV_` run_id の正本衝突 0 / provisional 内重複 0 / lap_id JOIN 0
7. quality: data_quality_log・analysis_run_log に当該 analysis_run_id の行が記録されていること、queue status 遷移（awaiting_gate/failed/skipped）確認
8. Workbench 確認: provisional overlay で当該 session の表示確認（`workbench_provisional_overlay_apply_20260706.md` 参照）

全 session 完了後: 合計が §4 の最終値（12/79/79）・queue pending 0 であることを最終確認し、apply レポートを reports/ に保存。

## 8. Multi-agent operating check

- 本 readiness は委任エージェントが read-only で実行（dry-run レポートは scratchpad へ退避し、プロジェクト内の新規ファイルは本書 1 件のみ）。
- 承認境界は不変: **apply（DB 書込）はメインセッション + Tatsuki の GO フレーズ受領後のみ**。エージェントには `--apply` を委任しない。
- dry-run は冪等・mode=ro のため並列/再実行安全。ただし apply は session 逐次（並列禁止、run_id 採番とバックアップ TS の整合のため）。
- Obsidian 運用層: apply 実施時は CURRENT_STATE / AI_HANDOFF_LATEST の更新を忘れないこと。

## 9. 未実施リスト（本 Phase 対象外・順不同）

- FAIL 7 件の救済判断（valid laps=0 の原因調査、必要なら extract パラメータ見直し）
- Report v2 provisional 連携（provisional データの Report v2 反映）
- Workbench「Session Import」ボタン実装
- Supabase 同期（provisional の扱い設計含む）
- TS24 DB Master.xlsx への反映
- git push / リモート同期（そもそも git 非管理 — 管理方針の決定含む）
- provisional → 正本 final 化（Phase D 想定・別ゲート）
- provisional クリア運用（final 化後の削除手順）

---
*Generated 2026-07-06 / read-only readiness — DB 無変更・既存ファイル無変更*
