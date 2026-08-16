# Session Extraction Staging — apply — 2026-07-11 16:49

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-DA77 / session=ALL / rider=ALL / limit=-
- mode: **apply** / exit=2 / analysis_run_id=`2026-07-11T16:49:26_session_extract_staging`

## 候補: 11 outing (insert対象 7 / FAIL隔離 4 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| F1-#77-01 | FP | PROV_20260710_ROUND8_DONINGTON_FP_DA77_R1 | 13 | 89.96 | WARNING | stage_phase22_fill=WARNING |
| F1-#77-02 | FP | PROV_20260710_ROUND8_DONINGTON_FP_DA77_R2 | 6 | 90.189 | WARNING | stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| R1-#77-01 | RACE1 | PROV_20260710_ROUND8_DONINGTON_RACE1_DA77_R1 | 20 | 89.738 | WARNING | stage_phase22_fill=WARNING |
| SP-#77-01 | SP | PROV_20260710_ROUND8_DONINGTON_SP_DA77_R1 | 5 | 90.105 | WARNING | stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| SP-#77-02 | SP | PROV_20260710_ROUND8_DONINGTON_SP_DA77_R2 | 5 | 90.14 | WARNING | stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| SP-#77-03 | SP | PROV_20260710_ROUND8_DONINGTON_SP_DA77_R3 | 8 | 89.622 | WARNING | stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| SX_F1-#77-01 | SX | PROV_20260710_ROUND8_DONINGTON_SX_DA77_R1 | 13 | 89.96 | FAIL | stage_inference=FAIL; stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| SX_SP-#77-03 | SX | PROV_20260710_ROUND8_DONINGTON_SX_DA77_R2 | 8 | 89.622 | FAIL | stage_inference=FAIL; stage_area_rates=WARNING; stage_phase22_fill=WARNING |
| WU1-#77-01 | WUP1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| WU1-#77-02 | WUP1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| WU1-#77-03 | WUP1 | PROV_20260710_ROUND8_DONINGTON_WUP1_DA77_R1 | 7 | 90.105 | WARNING | stage_area_rates=WARNING; stage_phase22_fill=WARNING |

## 予定/実施 行数: runs_provisional=7 / laps_provisional=64 / lap_suspension_provisional=64

## 業務6テーブル（before / after）

| table | before | after | 不変 |
|---|---:|---:|:--:|
| runs | 286 | 286 | ✅ |
| laps | 1279 | 1279 | ✅ |
| lap_suspension | 1279 | 1279 | ✅ |
| race_results | 866 | 866 | ✅ |
| pdf_lap_times | 7613 | 7613 | ✅ |
| pdf_lap_times_v2_staging | 7710 | 7710 | ✅ |

## provisional 3テーブル（before → after）

- runs_provisional: 7 → 14
- laps_provisional: 66 → 130
- lap_suspension_provisional: 66 → 130
