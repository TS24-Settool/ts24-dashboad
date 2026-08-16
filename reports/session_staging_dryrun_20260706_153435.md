# Session Extraction Staging — dryrun — 2026-07-06 15:34

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=QP / rider=ALL / limit=-
- mode: **dryrun** / exit=2 / analysis_run_id=`2026-07-06T15:34:35_session_extract_staging`

## 候補: 7 outing (insert対象 4 / FAIL隔離 1 / skip 2 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| QP-JA52-01 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R1 | 4 | 97.953 | PASS | all PASS |
| QP-JA52-02 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R2 | 3 | 98.25 | PASS | all PASS |
| QP-JA52-03 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R3 | 5 | 97.636 | PASS | all PASS |
| QP-JA52-04 | QP | PROV_20260612_ROUND7_MISANO_QP_JA52_R4 | 2 | 101.714 | WARNING | stage_phase22_fill=WARNING |
| QP-JA52-05 | QP | — | 0 | — | FAIL | stage_lap_count=FAIL |
| QP-JA52-ENGINEWARMUP01 | QP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| QP-JA52-ENGINEWARMUP02 | QP | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=4 / laps_provisional=14 / lap_suspension_provisional=14

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

- runs_provisional: 3 → 3
- laps_provisional: 15 → 15
- lap_suspension_provisional: 15 → 15
