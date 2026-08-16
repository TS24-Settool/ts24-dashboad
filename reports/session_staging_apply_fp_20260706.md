# Session Extraction Staging — apply — 2026-07-06 14:26

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=FP / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-06T14:26:25_session_extract_staging`

## 候補: 5 outing (insert対象 3 / FAIL隔離 0 / skip 2 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| FP-JA52-01 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R1 | 4 | 99.429 | PASS | all PASS |
| FP-JA52-02 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R2 | 7 | 98.791 | PASS | all PASS |
| FP-JA52-03 | FP | PROV_20260612_ROUND7_MISANO_FP_JA52_R3 | 4 | 98.364 | PASS | all PASS |
| FP-JA52-ENGINEWARMUP01 | FP | — | 0 | — | SKIP | EngineWarmup no valid laps |
| FP-JA52-ENGINEWARMUP02 | FP | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=3 / laps_provisional=15 / lap_suspension_provisional=15

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

- runs_provisional: None → 3
- laps_provisional: None → 15
- lap_suspension_provisional: None → 15
