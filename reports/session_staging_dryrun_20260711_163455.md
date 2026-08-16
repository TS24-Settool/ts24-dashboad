# Session Extraction Staging — dryrun — 2026-07-11 16:34

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-JA52 / session=ALL / rider=ALL / limit=-
- mode: **dryrun** / exit=0 / analysis_run_id=`2026-07-11T16:34:55_session_extract_staging`

## 候補: 1 outing (insert対象 1 / FAIL隔離 0 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| R1-JA52-01 | RACE1 | PROV_20260710_ROUND8_DONINGTON_RACE1_JA52_R1 | 20 | 89.195 | WARNING | stage_phase22_fill=WARNING |

## 予定/実施 行数: runs_provisional=1 / laps_provisional=20 / lap_suspension_provisional=20

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

- runs_provisional: 6 → 6
- laps_provisional: 46 → 46
- lap_suspension_provisional: 46 → 46
