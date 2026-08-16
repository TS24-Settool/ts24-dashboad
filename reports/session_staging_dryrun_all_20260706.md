# Session Extraction Staging — dryrun — 2026-07-06 14:24

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=ALL / rider=ALL / limit=-
- mode: **dryrun** / exit=2 / analysis_run_id=`2026-07-06T14:24:28_session_extract_staging`

## 候補: 33 outing (insert対象 12 / FAIL隔離 7 / skip 14 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| FP-JA52-01 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R1 | 4 | 99.429 | PASS | all PASS |
| FP-JA52-02 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R2 | 7 | 98.791 | PASS | all PASS |
| FP-JA52-03 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R3 | 4 | 98.364 | PASS | all PASS |
| QP-JA52-01 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R1 | 4 | 97.953 | PASS | all PASS |
| QP-JA52-02 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R2 | 3 | 98.25 | PASS | all PASS |
| QP-JA52-03 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R3 | 5 | 97.636 | PASS | all PASS |
| QP-JA52-04 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R4 | 2 | 101.714 | WARNING | stage_phase22_fill=WARNING |
| QP-JA52-05 | QP | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R1-JA52-01 | RACE1 | PROV_20260612_ROUND7_MISANO_RACE1_JA52_R1 | 19 | 98.055 | WARNING | stage_phase22_fill=WARNING |
| R1-JA52-02 | RACE1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R1-JA52-03 | RACE1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R1-JA52-04 | RACE1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R1-JA52-05 | RACE1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R1-JA52-GRID01 | RACE1 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R2-JA52-01 | RACE2 | PROV_20260612_ROUND7_MISANO_RACE2_JA52_R1 | 19 | 97.778 | WARNING | stage_phase22_fill=WARNING |
| R2-JA52-GRID01 | RACE2 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| WUP1-JA52-01 | WUP1 | PROV_20260612_ROUND7_MISANO_WUP1_JA52_R1 | 6 | 98.109 | WARNING | stage_phase22_fill=WARNING |
| WUP2-JA52-01 | WUP2 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R1 | 4 | 98.16 | PASS | all PASS |
| WUP2-JA52-02 | WUP2 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R2 | 2 | 98.045 | PASS | all PASS |
| FP-JA52-ENGINEWARMUP01 | FP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| FP-JA52-ENGINEWARMUP02 | FP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| QP-JA52-ENGINEWARMUP01 | QP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| QP-JA52-ENGINEWARMUP02 | QP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| R1-JA52-ENGINEWARMUP01 | RACE1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| R1-JA52-ENGINEWARMUP02 | RACE1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| R2-JA52-ENGINEWARMUP01 | RACE2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| R2-JA52-ENGINEWARMUP02 | RACE2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP1-JA52-ENGINEWARMUP01 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP1-JA52-ENGINEWARMUP02 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP1-JA52-ENGINEWARMUP03 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP2-JA52-ENGINEWARMUP01 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP2-JA52-ENGINEWARMUP02 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP2-JA52-ENGINEWARMUP03 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=12 / laps_provisional=79 / lap_suspension_provisional=79

## 業務6テーブル（before / after）

| table | before | after | 不変 |
|---|---:|---:|:--:|
| runs | 275 | 275 | ✅ |
| laps | 1202 | 1202 | ✅ |
| lap_suspension | 1202 | 1202 | ✅ |
| race_results | 866 | 866 | ✅ |
| pdf_lap_times | 7613 | 7613 | ✅ |
| pdf_lap_times_v2_staging | 7710 | 7710 | ✅ |

## provisional 3テーブル（before → after）

- runs_provisional: None → None
- laps_provisional: None → None
- lap_suspension_provisional: None → None
