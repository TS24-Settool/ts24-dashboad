# Session Extraction Staging — apply — 2026-07-12 11:14

- DB: `/Users/ts24/Desktop/Data TS24 Claude/02_DATABASE/ts24_unified.db` / event=20260710-ROUND8-JA52 / session=ALL / rider=ALL / limit=-
- mode: **apply** / exit=0 / analysis_run_id=`2026-07-12T11:14:10_session_extract_staging`

## 候補: 1 outing (insert対象 1 / FAIL隔離 0 / skip 0 / queue未マッチ 0)

| base | session | run_id | laps | best(valid) | gate | checks |
|---|---|---|---:|---:|:--:|---|
| WUP2-JA52-01 | WUP2 | PROV_20260710_ROUND8_DONINGTON_WUP2_JA52_R1 | 7 | 89.994 | WARNING | stage_phase22_fill=WARNING |

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

- runs_provisional: 14 → 15
- laps_provisional: 130 → 137
- lap_suspension_provisional: 130 → 137
