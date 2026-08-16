# Round7 Finalization Method Decision — 2026-07-07

## 結論

採用推奨は **Option A: ROUND7-only targeted insert**。

Option B（cutover修正）は今回選ばない。理由は、`cutover_db.py` の PRESERVE 更新だけでなく、`pdf_lap_times_v2_staging`、`race_lap_detail` VIEW、品質フレームワーク、provisional clear、DB Master、Supabase v3まで影響範囲が広がり、既存機能を壊すリスクが高いから。

Option A は今回必要な差分（ROUND7 JA52 final 13 runs / 77 laps と placeholder 2件の置換）だけに閉じられる。既存 1202 laps、v2 staging、Race Analysis VIEW、import_queue/source_file_registry、metric_version_log を保全しやすい。

## 判断材料

停止メモ `08_OBSIDIAN/TS24_Engineering_Knowledge/05_DB_AUDIT/2026-07-07_Round7_finalization_paused.md` の通り、当初の cutover 方式は以下を消すリスクがある。

- `pdf_lap_times_v2_staging` 7710行
- `race_lap_detail` VIEW
- `source_file_registry` / `import_queue` / `data_quality_log` / `analysis_run_log` / `metric_version_log`

一方、readiness では非ROUND7 1202 laps の byte 一致、ROUND7 final 予定形 13 runs / 77 laps、placeholder 2件のみの置換が確認済み。

## Codeへの指示

Code は次の Phase A を read-only で作る。

1. `round7_full_integration_readiness_20260707.md` の scratch DB / mapping / plan を再確認する。
2. targeted insert 方式の readiness を作成する。
3. 対象差分を明示する。
   - insert: ROUND7 JA52 final runs/laps/lap_suspension
   - replace/delete: `NA_MISANO_RACE1_JA52_R1` / `NA_MISANO_RACE2_JA52_R1` の 0-lap placeholder 2件のみ
   - preserve: v2 staging / `race_lap_detail` VIEW / source registry / import_queue / quality tables / metric versions
4. 正本DBへはまだ書かない。
5. readiness がPASSした場合だけ、次ゲートを提示する。

推奨ゲート文言:

```text
Round7 targeted insert GO
```

## 禁止

- `cutover_db.py` を使った丸ごとDB swap。
- `pdf_lap_times_v2_staging` / `race_lap_detail` / quality framework の再作成前提の実行。
- provisional clear、DB Master refresh、Supabase sync の同時実行。
- 正本DB書込。書込は `Round7 targeted insert GO` 後。

## GO後の期待手順

1. 正本DB full backup。
2. scratch rebuildを再実行。
3. 非ROUND7 1202 laps byte一致を再確認。
4. ROUND7 final 13/77 を targeted insert。
5. placeholder 2件のみ削除または置換。
6. Workbench final表示確認。
7. provisional clearは別ステップ、または同GOに明示されている場合だけ実行。
8. DB Master / Supabase v3 sync はさらに別ゲート。

