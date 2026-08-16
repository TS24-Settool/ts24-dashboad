# Session Extraction Staging — apply — 2026-07-06 16:40

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=WUP2 / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-06T16:40:33_session_extract_staging`

## 候補: 5 outing (insert対象 2 / FAIL隔離 0 / skip 3 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| WUP2-JA52-01 | WUP2 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R1 | 4 | 98.16 | PASS | all PASS |
| WUP2-JA52-02 | WUP2 | PROV_20260612_ROUND7_MISANO_WUP2_JA52_R2 | 2 | 98.045 | PASS | all PASS |
| WUP2-JA52-ENGINEWARMUP01 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP2-JA52-ENGINEWARMUP02 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP2-JA52-ENGINEWARMUP03 | WUP2 | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=2 / laps_provisional=6 / lap_suspension_provisional=6

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

- runs_provisional: 8 → 10
- laps_provisional: 35 → 41
- lap_suspension_provisional: 35 → 41
