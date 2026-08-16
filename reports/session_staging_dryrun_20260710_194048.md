# Session Extraction Staging — dryrun — 2026-07-10 19:40

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-JA52 / session=ALL / rider=ALL / limit=-
- mode: **dryrun** / exit=0 / analysis_run_id=`2026-07-10T19:40:48_session_extract_staging`

## 候補: 3 outing (insert対象 3 / FAIL隔離 0 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| QP-JA52-01 | QP | PROV_20260710_ROUND8_DONINGTON_QP_JA52_R1 | 5 | 89.674 | PASS | all PASS |
| QP-JA52-02 | QP | PROV_20260710_ROUND8_DONINGTON_QP_JA52_R2 | 5 | 89.905 | PASS | all PASS |
| QP-JA52-03 | QP | PROV_20260710_ROUND8_DONINGTON_QP_JA52_R3 | 8 | 89.123 | PASS | all PASS |

## 予定/実施 行数: runs_provisional=3 / laps_provisional=18 / lap_suspension_provisional=18

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

- runs_provisional: 2 → 2
- laps_provisional: 21 → 21
- lap_suspension_provisional: 21 → 21
