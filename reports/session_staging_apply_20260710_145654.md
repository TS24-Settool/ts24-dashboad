# Session Extraction Staging — apply — 2026-07-10 14:56

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-JA52 / session=ALL / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-10T14:56:54_session_extract_staging`

## 候補: 2 outing (insert対象 2 / FAIL隔離 0 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| FP-JA52-01 | FP | PROV_20260710_ROUND8_DONINGTON_FP_JA52_R1 | 15 | 90.24 | PASS | all PASS |
| FP-JA52-02 | FP | PROV_20260710_ROUND8_DONINGTON_FP_JA52_R2 | 6 | 89.96 | WARNING | stage_phase22_fill=WARNING |

## 予定/実施 行数: runs_provisional=2 / laps_provisional=21 / lap_suspension_provisional=21

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

- runs_provisional: 0 → 2
- laps_provisional: 0 → 21
- lap_suspension_provisional: 0 → 21
