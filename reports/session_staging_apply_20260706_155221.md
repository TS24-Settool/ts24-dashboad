# Session Extraction Staging — apply — 2026-07-06 15:52

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=WUP1 / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-06T15:52:21_session_extract_staging`

## 候補: 4 outing (insert対象 1 / FAIL隔離 0 / skip 3 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| WUP1-JA52-01 | WUP1 | PROV_20260612_ROUND7_MISANO_WUP1_JA52_R1 | 6 | 98.109 | WARNING | stage_phase22_fill=WARNING |
| WUP1-JA52-ENGINEWARMUP01 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP1-JA52-ENGINEWARMUP02 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| WUP1-JA52-ENGINEWARMUP03 | WUP1 | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=1 / laps_provisional=6 / lap_suspension_provisional=6

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

- runs_provisional: 7 → 8
- laps_provisional: 29 → 35
- lap_suspension_provisional: 29 → 35
