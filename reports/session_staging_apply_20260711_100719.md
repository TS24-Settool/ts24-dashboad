# Session Extraction Staging — apply — 2026-07-11 10:07

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-JA52 / session=ALL / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-11T10:07:19_session_extract_staging`

## 候補: 1 outing (insert対象 1 / FAIL隔離 0 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| WUP1-JA52-01 | WUP1 | PROV_20260710_ROUND8_DONINGTON_WUP1_JA52_R1 | 7 | 89.202 | PASS | all PASS |

## 予定/実施 行数: runs_provisional=1 / laps_provisional=7 / lap_suspension_provisional=7

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

- runs_provisional: 5 → 6
- laps_provisional: 39 → 46
- lap_suspension_provisional: 39 → 46
