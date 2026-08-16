# Session Extraction Staging — dryrun — 2026-07-06 16:58

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260612-ROUND7-JA52 / session=RACE2 / rider=ALL / limit=-
- mode: **dryrun** / exit=2 / analysis_run_id=`2026-07-06T16:58:12_session_extract_staging`

## 候補: 4 outing (insert対象 1 / FAIL隔離 1 / skip 2 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| R2-JA52-01 | RACE2 | PROV_20260612_ROUND7_MISANO_RACE2_JA52_R1 | 19 | 97.778 | WARNING | stage_phase22_fill=WARNING |
| R2-JA52-GRID01 | RACE2 | — | 0 | — | FAIL | stage_lap_count=FAIL |
| R2-JA52-ENGINEWARMUP01 | RACE2 | — | 0 | — | SKIP | EngineWarmup no valid laps |
| R2-JA52-ENGINEWARMUP02 | RACE2 | — | 0 | — | SKIP | EngineWarmup no valid laps |

## 予定/実施 行数: runs_provisional=1 / laps_provisional=19 / lap_suspension_provisional=19

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

- runs_provisional: 10 → 10
- laps_provisional: 41 → 41
- lap_suspension_provisional: 41 → 41
