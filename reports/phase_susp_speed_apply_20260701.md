# Phase Suspension Speed 派生列 apply（Tatsuki GO 受領 → 正本DB反映）— 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01「Phase Suspension Speed 派生列 apply 実行ゲート」）。
**Tatsuki が本セッションで「私の方からのGO承認します」と明示GO**（=`Phase suspension speed design GO`）→ 実行。
設計 = `reports/phase_susp_speed_metric_design_20260701.md`（§43）。Tatsuki Braking sketch 追加仕様を反映。

**結果**: 正本DB `lap_suspension` に **3フェーズ×F/R×方向 サス速度 22新列を追加のみで反映**。既存データ byte 一致・業務テーブル不変。
Workbench `🔧 3フェーズ Run比較` の Speed グラフを 6 phase×side 全てに拡張（`not available yet` 解消）。

---

## 1. 実装（本番ロジック拡張・追加のみ）

### 1a. `build_master_db.py`（extract_outing 拡張・既存算出は不変）
- `AREAS`/`_vel`/`_zone_mask`/`vf`/`vr`/`fb_mask`/`ce_mask` を再利用し、`mc_mask=MID_CORNER` を追加。
- per-lap で **`phase_spd_matrix`（PHASE_SPD_NEW_COLS 順の22値）** を算出。`_dir_stat(v,mask,positive)`:
  `dive=v>0(圧縮)` / `reb=-v(v<0,伸び)`、`avg=mean(方向 n>=5)` / `peak=p95(方向 n>=10)`、未満は NULL。
  **既存 `brk_f_dive_spd_*` は凍結**（ループから除外・上書きしない）。既存 `ce_r_spd_*`(abs) も不変。
- モジュール定数 `PHASE_SPD_NEW_COLS`（22名・唯一の真実）／ `PEAK_NMIN=10` を追加。
- `SCHEMA` の `lap_suspension` CREATE に `{', '.join(c+' REAL' for c in PHASE_SPD_NEW_COLS)}` を注入。
- `_build_lap_suspension(conn, extra_by_lapid, matrix_by_lapid)`: 22値を末尾に付与（named INSERT・placeholder 数は列数算出＝手動 `?` 誤りを排除）。
- `build_all`: `matrix_by_lapid` を収集し `_build_lap_suspension` へ渡す。

### 1b. `apply_phase_susp_speed.py`（新規・安全 apply helper・既定 dry-run）
- scratch DB（`build_master_db.py --all` で22列込み再生成）と正本を突合。
- **決定論ゲート**: `lap_suspension` の既存45列（lap_id/updated_at/22新列を除く）を lap_id JOIN・`abs(diff)<1e-6`・lap_id 集合一致で検証。1件でも不一致なら `sys.exit(1)`・正本無書込。
- `--apply` 時のみ: フルバックアップ → `ALTER ADD 22列` → scratch から lap_id で `UPDATE`（新列のみ）→ **before==after assert**（既存列 sha256 チェックサム不変・業務テーブル件数不変）→ commit。失敗で rollback。

### 1c. `create_quality_tables.py`（metric_version_log シード・管理テーブル）
- 22新列を `metric_version_log` に登録（governance / `gate_unit_semantics_registered`）。
  guard_rule に「n>=5(avg)/n>=10(peak)→NULL」「peak=p95(新)/max(既存凍結)」「相対指数・車速km/h混同禁止」、
  低解釈セル（`brk_r_dive`/`ce_f_dive` → 本命 `brk_r_reb`/`ce_f_reb`）を notes に明記。

### 1d. `ts24_workbench.py`（Speed グラフ拡張・最小差分）
- `PhaseRunCompareWidget._PHASE_SPD` を 6 slot 全て充填（Tatsuki 本命方向）:
  | slot | 列 | peak | 備考 |
  |---|---|---|---|
  | Braking F | `brk_f_dive_spd_*` | max | 既存凍結・Tatsuki AVE F-Sus-Speed |
  | Braking R | `brk_r_reb_spd_*` | p95 | **本命**（制動でリアは伸び側） |
  | Apex F | `apex_f_dive_spd_*` | p95 | 新（dive/reb ほぼ対称） |
  | Apex R | `apex_r_dive_spd_*` | p95 | 新 |
  | Exit F | `ce_f_reb_spd_*` | p95 | **本命**（立上りで前は伸び側） |
  | Exit R | `ce_r_spd_*` | max | 既存 abs・旧互換維持 |
- `_update_note` を **列存在チェック（col-guard）**化: DB に実列がある slot のみ「利用可」、無ければ `not available yet`。
  relative-index ラベル・本命方向・構造的NULL≠未整備・車速非表示 を明記。
- `_draw_speed` は既存 `_valid_xy` の `col not in rs.columns` ガードで未適用DBでも安全（無回帰）。

---

## 2. 実行結果（正本DB反映・2026-07-01）

### 2a. full-DB scratch rebuild
- `python3 build_master_db.py --all --out /tmp/ts24_scratch.db` → lap_suspension=1202・受入ゲート `Δ>1.5s=0件 ✅`。
  scratch cols=**69**（既存47 + 22新）。

### 2b. 決定論ゲート（apply 前）
- 既存45列 × 1202 lap を lap_id JOIN 突合 → **不一致 0 / lap_id 集合一致（1202=1202）**＝**PASS ✅**。
  → extract_outing 拡張は既存列を一切変えない（構成による担保を実測で確認）。

### 2c. apply（`apply_phase_susp_speed.py --apply`）
- バックアップ `02_DATABASE/_backup_phase_susp_speed_20260701_234644/`。
- **ALTER 22列 + UPDATE 1202行**。commit 前 assert: 業務テーブル件数不変・既存列 checksum 不変。
- 業務テーブル before==after: **runs 275 / laps 1202 / lap_suspension 1202 / race_results 866 / pdf_lap_times 7613**（全一致）。

### 2d. apply 後検証（正本DB read-only）
- `lap_suspension` cols=**69** / rows=**1202**。22新列すべて存在。
- **zero-leak = 0**（NEW列に literal 0.0 なし）。**n-condition = 0**（peak 非NULL は avg 非NULL を含意＝n>=10⇒n>=5）。
- 凍結列不変: `brk_f_dive_spd_avg`=1072 / `ce_r_spd_avg`=661。`metric_version_log` = 32 行（+22）。
- **★最終 integrity**: pre-apply バックアップ vs 現正本で、既存全列（凍結4速度列含む）**mismatch 0**・lap_id 集合一致・業務テーブル件数一致 → **追加のみ・既存 byte 一致を証明**。

### 2e. 新22列の分布（正本DB・全1202 lap）
| 列 | non-null | null% | mean | peak p95(max) |
|---|--:|--:|--:|--:|
| brk_f_reb / brk_r_dive / brk_r_reb | 1067/1070/1074 | ~11 | 48.6/38.5/38.1 | 良性(1.2-1.9×) |
| apex_f_dive/reb, apex_r_dive/reb | 1198 | 0.3 | 55-118 | p95で外れ値抑制（peak max 3336→p95 549 等） |
| ce_f_dive/reb, ce_r_dive/reb | 640-654 | ~46 | 61-110 | Exit 本質的希薄（既存 ce_r と整合） |

- WARNING（非ブロッキング）: `apex_f_dive_spd_avg` max=801（少数の busy MID_CORNER lap・実信号。相対指数の但し書きで扱う・`detect_susp_speed_outlier` 相当）。

### 2f. Workbench 検証
- `py_compile`（ts24_workbench/build_master_db/backfill/apply）PASS。
- **offscreen スモークテスト PASS**: df に22新列反映（72列＝69DB+pitch/heave/pitch_pct）、Speed slot 6/6 充填、
  Phase 全切替で例外なし、注記「利用可 = Braking F,R / Apex F,R / Exit F,R」（`not available yet` 解消）、
  Braking テーブル F/R spd が数値表示（旧 n/a→41/41）、**既存無回帰**（`APEX分析（基本）`/`Damping / Phase` 動作・Damping 1081行・MainWindow 7タブ）。
- **GUI 目視（最終）は Tatsuki ローカル**（`python3 ts24_workbench.py` → 🦾 Suspension/Posture → 🔧 3フェーズ Run比較 → Speed グラフで各 phase×side を確認）。

---

## 3. Multi-agent operating check（apply 後）

- **Suspension/Physics**: dive/reb を本命方向（Braking R=Reb・Exit F=Reb）で採用、低解釈セルは注記。avg 主線/p95 補助線。相対指数明記。
- **Data/Extraction**: full-DB scratch を本番ロジックで再生成、既存45列 決定論 0 不一致、lap_id JOIN。
- **DB Integration**: バックアップ→単一トランザクション ALTER+UPDATE→before==after assert→commit。追加のみ・既存 byte 一致。
- **Workbench/UI**: `_PHASE_SPD` 6 slot 拡張・col-guard・既存タブ無回帰。
- **Quality Gate**: py_compile・決定論ゲート・zero-leak 0・n-condition 0・range WARNING 記録・offscreen smoke。
- **Documentation/Handoff**: 本 report / `CLAUDE.md` §44 / Obsidian（log/handoff/current_state/INBOX Result）。
- **Supervisor**: Supabase・DB Master 再生成・origin push・新2D取込を**別承認に保持**（未実施）。

---

## 4. rollback

- **DB**: バックアップ `02_DATABASE/_backup_phase_susp_speed_20260701_234644/ts24_unified.db` を `ts24_unified.db` に戻す（SQLite `DROP COLUMN` は環境依存のため原則バックアップ復元）。
- **Code**: 当該コミットを revert。Workbench は新列が無くても `_valid_xy` col-guard で起動可（`_PHASE_SPD` を旧状態へ戻すか、列欠如で自動 degrade）。

## 5. スコープ外（未実施・別承認保持）

Supabase cleanup / sync・DB Master 再生成・origin push・新2D data 取込・指標設計外の大規模 Workbench 改修。

## 6. 成果物
- 変更: `build_master_db.py`（extract_outing/SCHEMA/_build_lap_suspension/build_all）, `ts24_workbench.py`（_PHASE_SPD/_update_note）, `create_quality_tables.py`（+22 seed）。
- 新規: `apply_phase_susp_speed.py`, 本 report。
- 正本DB: `lap_suspension` +22列（追加のみ）／`metric_version_log` +22行（管理テーブル）。バックアップ2式。
