# Round7 Targeted Insert — APPLY 実行記録（2026-07-08 Claude Code）

Tatsuki 指示「システムを正しい状態に保ち Round7 provisional を本データにする最適作業」= GO 相当。
スコープ = **DB + Workbench のみ**（final 反映 + provisional クリア）。DB Master / Supabase / origin push は対象外・別GO据え置き。

## 方式 = Option B（Round7-only build）
iCloud offload により full `--all` rebuild（非Round7 1202 ラップの materialize）が現地ネットワークで実行不能となったため、
Tatsuki 選択（AskUserQuestion）で **Round7 のみをビルドして本データ化**する Option B を採用。
MISANO は ROUND7 にのみ存在するため、Round7 イベントだけを `build_master_db` の同一ロジックで処理すれば
Round7 行は full rebuild と byte 等価（cross-source で実証）。

### コード変更（最小・追加のみ）
- `build_master_db.py`: `build_all(out_db, only_events=None)` に**イベントフィルタ**追加（default None=従来挙動不変）+ CLI `--round ROUND7`。
- `apply_round7_targeted_insert.py`: `--scratch-scope round7` モード + `cross_source_gate()` 追加（決定論非Round7ゲートの代替）。
  PASSIVE checkpoint（TRUNCATE は iCloud ロックでハングしたため）・busy_timeout・WAL-safe backup・2段ゲート。

## ビルド + ゲート（全 PASS）
- `build_master_db.py --all --round ROUND7 --out /tmp/ts24_r7only.db` → 受入ゲート |2D−PDF|>1.5s **0件合格**・Round7 **13 runs/77 laps/77 lap_suspension**。
- **cross-source ゲート**（build == full-rebuild 等価の実証）:
  - best_lap vs provisional: shared 11 / mismatch **0**。
  - **lap 2D値（lap_time_s/susf/susr/f_dive_spd/r_dive_spd）vs provisional: compared 77 / matched 77**（別コードパス由来＝2D抽出同一）。
  - best_lap vs §64 --all mapping: 11/11 一致（＝昨日の full rebuild と等価）。
  - RACE best vs race_results 公式: RACE1 98.055 vs 98.061（Δ0.006）/ RACE2 97.778 vs 97.793（Δ0.015）＝telemetry対公式の想定内。
- **content ゲート**: setup(f_spr_l) 13/13 充填・wheel-force 77行充填・best §64 mapping 一致・0-lap R2 2件存在。

## final 反映（canonical 書込・backup 付き）
- backup `02_DATABASE/_backup_round7_targeted_20260708_200025/`（+ 先行 195435 も保持）。
- placeholder `NA_MISANO_RACE1_JA52_R1` / `NA_MISANO_RACE2_JA52_R1` を **DELETE** + Round7 **13 runs/77 laps/77 lap_suspension INSERT**。
- 事後 assert（PROTECTED不変・totals・Round7 shape・content 再検証）全通過 → COMMIT。

### 独立検証（mode=ro）
- 業務: **runs 286 / laps 1279 / lap_suspension 1279**・race_results 866（不変）。
- Round7: **13/77/77**・placeholder 残 **0**・setup 13/13・wheel-force 77。
- **PROTECTED 全不変**: pdf_lap_times_v2_staging 7710 / source_file_registry 405 / import_queue 397 / data_quality_log 1340 /
  analysis_run_log 11 / metric_version_log 32 / pdf_lap_times 7613。race_lap_detail VIEW 稼働（12763）。非Round7 laps **1202 保持**。

## provisional クリア（Workbench 二重表示回避＝正しい状態化）
- backup `02_DATABASE/_backup_round7_provclear_20260708_200609/`。
- event_key `20260612-ROUND7-JA52` を 3 provisional テーブルから DELETE: **79/79/12 → 0/0/0**。
- 業務テーブル不変（286/1279/1279）・Round7 runs=13 を assert 確認。

## Workbench offscreen smoke（PASS）
- MainWindow **7タブ**構築 OK（例外なし＝overlay SQL・race_lap_detail VIEW とも finalization 後に正常）。
- overlay: 総 1279 行・**provisional 0 行・PROV_ 0 件**（⏳prov 重複なし）。
- Round7 = **final 11 run**（テレメトリ有・run_id `20260612_ROUND7_MISANO_*`）で表示。race_lap_detail ROUND7=1094。
- **GUI 最終目視は Tatsuki ローカル**（`python3 ts24_workbench.py` → 🦾 Suspension/Posture・Race Analysis で MISANO/JA52 final 確認）。

## 受容した挙動（Tatsuki 指示スコープ内・build_master_db 標準）
- **WUP2 最速ラップ 98.045 が final から落ちる**（採用 WUP2-R1=98.160・4laps / drop WUP2-R2=98.045・2laps）。Original マージの top-lap 選択仕様（全ラウンド共通）。
- placeholder 2件は ID 継承でなく件数整合（DELETE 2 / INSERT 13 のうち 0-lap R2 が 2）。

## rollback
- final: `_backup_round7_targeted_20260708_200025/` から DB 復元。
- provisional clear: `_backup_round7_provclear_20260708_200609/` から復元、または backup DB の provisional 3テーブルを event_key 限定で INSERT ... SELECT。

## スコープ外（別GO据え置き）
- DB Master(Excel) 再生成 / Supabase sync / origin push。※ §41a のとおり DB Master は race_results/2D由来のみ読むが、
  Round7 は今 runs/laps/lap_suspension に入ったため、次に `refresh_db_master_safe.py` を回せば DB Master にも Round7 が反映され得る（別GO）。

## 変更/新規ファイル
- 変更: `build_master_db.py`（event filter・追加のみ）/ `apply_round7_targeted_insert.py`（round7 scope + cross-source gate + PASSIVE checkpoint）。
- 新規: 本レポート。scratch: `/tmp/.../ts24_r7only.db`・検証 `r7_cross_validate.py`・`clear_prov.py`（scratchpad・非コミット）。
