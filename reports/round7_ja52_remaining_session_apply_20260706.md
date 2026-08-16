# Round7 JA52 残session provisional apply — 実行レポート（Phase B-4 / Phase C）

- 日付: 2026-07-06
- 実施: Claude Code（委任エージェント・Phase C 実行）
- GO: **「Round7 remaining session provisional apply GO」受領済**（Tatsuki 明示ゲート）
- 対象: `20260612-ROUND7-JA52` の残り 5 session（QP / WUP1 / WUP2 / RACE2 / RACE1）
- スクリプト: `05_SCRIPTS/session_extract_staging.py`（**既存のまま使用・コード無編集・git commit なし**）
- 手順準拠: `reports/round7_ja52_remaining_session_apply_readiness_20260706.md` §7（投入順 QP→WUP1→WUP2→RACE2→RACE1・session 毎 dry-run→apply→検証・予期しない差分で停止）

## 0. 結果サマリ

**全 5 session 成功・停止なし。** provisional 3/15/15 → **12/79/79**（readiness §4 の期待値と完全一致）。
業務 6 テーブルは全 apply 前後で不変（script 内 assert + 事後 mode=ro 再測定の二重確認）。重複 0。

## 1. session 別実行結果（dry-run / apply / 検証）

各 session とも dry-run は readiness §2.2 と**同値**（run_id・laps・best・gate 判定・exit code すべて一致・ドリフトなし）を確認してから apply を実行した。

| # | session | dry-run exit | apply exit | delta (runs/laps/susp) | prov 累計 | PASS | WARNING | FAIL隔離 | EW skip | 業務6不変 | dup(3種) |
|--:|---|---:|---:|---|---|--:|--:|--:|--:|:--:|:--:|
| 1 | QP | 2 | 2 | +4 / +14 / +14 | 7/29/29 | 3 | 1 | 1 | 2 | ✅ | 0/0/0 |
| 2 | WUP1 | 0 | 0 | +1 / +6 / +6 | 8/35/35 | 0 | 1 | 0 | 3 | ✅ | 0/0/0 |
| 3 | WUP2 | 0 | 0 | +2 / +6 / +6 | 10/41/41 | 2 | 0 | 0 | 3 | ✅ | 0/0/0 |
| 4 | RACE2 | 2 | 2 | +1 / +19 / +19 | 11/60/60 | 0 | 1 | 1 | 2 | ✅ | 0/0/0 |
| 5 | RACE1 | 2 | 2 | +1 / +19 / +19 | **12/79/79** | 0 | 1 | 5 | 2 | ✅ | 0/0/0 |
| — | **計** | — | — | **+9 / +64 / +64** | — | 5 | 4 | 7 | 12 | ✅ | 0 |

- exit 2 は「gate FAIL outing あり（隔離・INSERT せず）」の仕様どおり（readiness §2 の想定と同一）。
- dup(3種) = PROV_ run_id の正本 runs 衝突 / runs_provisional 内 run_id 重複 / laps_provisional.lap_id と laps.lap_id の JOIN。全 session 後に 0 を確認。lap_suspension_provisional の lap_id 重複も 0。

投入 run（quality_status）:

| run_id | laps | best | quality |
|---|---:|---:|:--:|
| PROV_20260612_ROUND7_MISANO_QP_JA52_R1 | 4 | 97.953 | PASS |
| PROV_20260612_ROUND7_MISANO_QP_JA52_R2 | 3 | 98.250 | PASS |
| PROV_20260612_ROUND7_MISANO_QP_JA52_R3 | 5 | 97.636 | PASS |
| PROV_20260612_ROUND7_MISANO_QP_JA52_R4 | 2 | 101.714 | WARNING (stage_phase22_fill) |
| PROV_20260612_ROUND7_MISANO_WUP1_JA52_R1 | 6 | 98.109 | WARNING (stage_phase22_fill) |
| PROV_20260612_ROUND7_MISANO_WUP2_JA52_R1 | 4 | 98.160 | PASS |
| PROV_20260612_ROUND7_MISANO_WUP2_JA52_R2 | 2 | 98.045 | PASS |
| PROV_20260612_ROUND7_MISANO_RACE2_JA52_R1 | 19 | 97.778 | WARNING (stage_phase22_fill) |
| PROV_20260612_ROUND7_MISANO_RACE1_JA52_R1 | 19 | 98.055 | WARNING (stage_phase22_fill) |

WARNING はいずれも stage_phase22_fill（Phase22 充足率・構造的 Exit NULL）のみで、gate 仕様上 insert 対象（readiness §2.2 と同一判定）。

## 2. 最終状態（mode=ro 実測）

### 2.1 業務 6 テーブル（不変・readiness §1 と完全一致）

| table | count |
|---|---:|
| runs | 275 |
| laps | 1202 |
| lap_suspension | 1202 |
| race_results | 866 |
| pdf_lap_times | 7613 |
| pdf_lap_times_v2_staging | 7710 |

### 2.2 provisional 3 テーブル

runs_provisional=**12** / laps_provisional=**79** / lap_suspension_provisional=**79**（期待値 12/79/79 一致・強制なしの実測）。

session 別 PROV_ runs（laps 内訳）: FP 3(15) / QP 4(14) / WUP1 1(6) / WUP2 2(6) / RACE1 1(19) / RACE2 1(19)。
quality_status: PASS 8 / WARNING 4。重複: 全カテゴリ 0。

### 2.3 import_queue（Round7 JA52・2d_extract 計 33 件）

| status | 件数 | readiness 期待 |
|---|---:|---:|
| pending | 0 | 0 ✅ |
| awaiting_gate | 12 | 12 ✅ |
| failed | 7 | 7 ✅ |
| skipped | 14 | 14 ✅ |

session 別遷移（apply 後実測）: QP=awaiting_gate4/failed1/skipped2、WUP1=1/0/3、WUP2=2/0/3、R2=1/1/2、R1=1/5/2、FP=3/0/2（B-2 確定・不変）。

### 2.4 品質ログ

- `data_quality_log`: 本日 `stage_*` 記録 = PASS 145 / WARNING 4 / FAIL 7（check 9 種: stage_area_rates / stage_hash_idempotent / stage_inference / stage_lap_count / stage_lap_time_range / stage_phase22_exists / stage_phase22_fill / stage_prov_id_dup / stage_zero_null_guard）。
- `analysis_run_log`: 各 apply の `session_extract_staging` run を記録（2026-07-06T15:37:02 / 15:52:21 / 16:40:33 / 17:00:19 / 17:02:12）。

## 3. バックアップ（script 自動・apply 毎フルコピー）

`02_DATABASE/_backup_session_staging_<TS>/ts24_unified.db`:

| session | backup |
|---|---|
| QP | `_backup_session_staging_20260706_153702/` |
| WUP1 | `_backup_session_staging_20260706_155221/` |
| WUP2 | `_backup_session_staging_20260706_164033/` |
| RACE2 | `_backup_session_staging_20260706_170019/` |
| RACE1 | `_backup_session_staging_20260706_170212/` |

（FP 分 `_142625/`・`_142715/` は B-2 既存。）script 生成の dry-run/apply 個別レポートは `reports/session_staging_dryrun_20260706_153435/154240/164021/165812/170053.md`・`session_staging_apply_20260706_153702/155221/164033/170019/170212.md`。

## 4. 冪等性スポットチェック

`--session WUP2 --apply` を再実行 → **候補 0 件**（queue が awaiting_gate のため pending フィルタに不一致・exit 1）→ provisional 12/79/79・業務 6 テーブルとも**完全不変**。冪等性 OK。

## 5. Workbench offscreen スモーク（QT_QPA_PLATFORM=offscreen）

| チェック | 結果 |
|---|---|
| MainWindow タブ数 | **7**（Quick Log / Problem Log / Comment Analysis / Setup Decision / Suspension·Posture / Race Analysis / Import·Quality）✅ |
| PostureAnalysisTab DataFrame | **1281 行**（final 1202 + provisional 79 = 1202+79）✅ |
| MISANO/JA52 Run リスト | **12 run**・FP3/QP4/WUP1 1/WUP2 2/RACE1 1/RACE2 1・**全て `(prov)` マーク付き** ✅ |
| final-only 無回帰（JEREZ/DA77/TEST1_DAY1） | 7 run・prov 混入なし・base_df 66 行（§48 と一致）✅ |
| Report v2 PROV guard（コード確認） | `ts24_workbench.py` L3459（`_on_create_report` の `PROV_` 検出→警告・既定 Cancel）/ L3568（`⏳ (prov)` ラベル分岐）**存置** ✅ |

GUI の最終目視は Tatsuki ローカル（`python3 ts24_workbench.py`）。

## 6. Rollback（参照・未使用）

session 単位 SQL は readiness §6 のとおり（`<SESSION>`=QP/WUP1/WUP2/RACE2/RACE1、queue prefix=QP-/WUP1-/WUP2-/R2-/R1-）:

```sql
DELETE FROM lap_suspension_provisional WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';
DELETE FROM laps_provisional           WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';
DELETE FROM runs_provisional           WHERE run_id LIKE 'PROV_20260612_ROUND7_MISANO_<SESSION>_%';
UPDATE import_queue
   SET status='pending', started_at=NULL, finished_at=NULL, analysis_run_id=NULL, error=NULL
 WHERE target_kind='2d_extract'
   AND file_path LIKE '%20260612-ROUND7-JA52/<PREFIX>-JA52-%'
   AND status IN ('awaiting_gate','failed','skipped');
```

最終手段 = §3 のバックアップから丸ごと復元。FP（B-2 確定分）は巻き込まないこと。

## 7. Multi-agent operating check

- apply は **Tatsuki の明示 GO フレーズ受領後**に委任エージェントが逐次実行（session 単位・並列禁止を遵守）。承認境界は不変。
- 使用スクリプトは既存 `session_extract_staging.py` のみ（コード編集ゼロ・新規実装ゼロ・git commit なし）。
- 各 session で dry-run→readiness 照合→apply→mode=ro 検証の順を機械的に反復。予期しない差分は発生せず停止条件に非該当。
- Quality Gate（stage_* 8+1 チェック）が FAIL 7 を全て隔離し正本・provisional 双方に非到達（FAIL は INSERT されない設計を実測確認）。
- Obsidian 運用層: CURRENT_STATE / AI_HANDOFF_LATEST の更新はメインセッション側で実施のこと（本レポート参照）。

## 8. 未実施リスト（本 Phase 対象外・各別承認）

- FAIL 7 件の救済判断（QP-05 / R1-02..05 / GRID×2 = valid laps 0 の原因調査・extract パラメータ見直し）
- Report v2 provisional 本対応（provisional モード・cover リボン / 現状は警告ガードのみ）
- Workbench「Session Import」ボタン実装
- Supabase 同期（provisional の扱い設計含む）
- TS24 DB Master.xlsx への反映
- git push / リモート同期（git 非管理 — 管理方針の決定含む）
- provisional → 正本 final 化（Phase D・別ゲート）
- provisional クリア運用（final 化後の削除手順）

---
*Generated 2026-07-06 / Phase C apply — 業務 6 テーブル不変・provisional 12/79/79・queue pending 0*
