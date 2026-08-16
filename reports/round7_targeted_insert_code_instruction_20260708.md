# Round7 Targeted Insert Code Instruction — 2026-07-08

## Tatsuki request

Tatsuki requested: Round7 data should be migrated from provisional to final data.

Interpretation:

- Use the approved safer method: **Option A / ROUND7-only targeted insert**.
- Do **not** use `cutover_db.py` full DB swap.
- Do **not** run DB Master refresh or Supabase sync in the same step unless a later explicit GO includes them.

## Required gate

Write operations to `02_DATABASE/ts24_unified.db` still require an explicit final gate:

```text
Round7 targeted insert GO
```

This instruction asks Code to prepare and, after the exact GO, execute the targeted insert path. If the exact gate has not been issued in the Code session, Code must stop after readiness and ask Tatsuki for it.

## Target outcome

Move Round7 JA52 from provisional tables into canonical final tables while preserving every non-target table and view.

Expected final target from readiness:

- Insert final Round7 JA52 into:
  - `runs`
  - `laps`
  - `lap_suspension`
- Expected final Round7 shape:
  - `13 runs`
  - `77 laps`
  - `77 lap_suspension`
- Replace/delete only the two 0-lap placeholders:
  - `NA_MISANO_RACE1_JA52_R1`
  - `NA_MISANO_RACE2_JA52_R1`
- Preserve:
  - existing non-Round7 1202 laps byte-for-byte
  - `pdf_lap_times_v2_staging`
  - `race_lap_detail` VIEW
  - `source_file_registry`
  - `import_queue`
  - `data_quality_log`
  - `analysis_run_log`
  - `metric_version_log`
  - all Supabase state

## Mandatory reading

1. `05_SCRIPTS/CLAUDE.md`
2. `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
3. `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
4. `08_OBSIDIAN/TS24_Engineering_Knowledge/05_DB_AUDIT/2026-07-07_Round7_finalization_paused.md`
5. `05_SCRIPTS/reports/round7_finalization_method_decision_20260707.md`
6. `05_SCRIPTS/reports/round7_full_integration_readiness_20260707.md`
7. `05_SCRIPTS/reports/round7_full_integration_mapping_20260707.csv`
8. `05_SCRIPTS/reports/round7_full_integration_plan_20260707.sql`
9. `05_SCRIPTS/build_master_db.py`
10. `05_SCRIPTS/reconcile_2d_vs_original.py`

## Phase A — readiness before any write

Code must first produce a fresh read-only readiness report:

```text
05_SCRIPTS/reports/round7_targeted_insert_readiness_20260708.md
```

It must include:

1. Current DB counts:
   - `runs`
   - `laps`
   - `lap_suspension`
   - `race_results`
   - `runs_provisional`
   - `laps_provisional`
   - `lap_suspension_provisional`
   - `pdf_lap_times_v2_staging`
   - `source_file_registry`
   - `import_queue`
2. Round7 current state:
   - final `runs/laps/lap_suspension` Round7 counts must still be 0/0/0 before apply.
   - provisional must still be 12/79/79.
   - `race_results` Round7 must still be 74.
   - `pdf_lap_times_v2_staging` Round7 PASS must still be 1094.
3. Fresh scratch rebuild:
   - rebuild to `/tmp`, not canonical.
   - confirm final Round7 target = 13/77/77.
   - confirm non-Round7 existing 1202 laps are byte-identical.
4. Targeted insert design:
   - list exact final `run_id`s to insert.
   - list exact placeholder rows to remove/replace.
   - list exact canonical tables to write.
   - prove no writes to v2 staging, views, quality tables, import queue, DB Master, or Supabase.
5. Rollback plan:
   - full DB backup path.
   - targeted rollback SQL or restore-from-backup procedure.
6. Verification plan:
   - post-apply counts.
   - Workbench final display expectation.
   - provisional clear status.

## Phase B — after exact GO only

Only after Tatsuki gives:

```text
Round7 targeted insert GO
```

Code may:

1. Create a full backup of `02_DATABASE/ts24_unified.db`.
2. Re-run scratch rebuild and deterministic gates.
3. Apply targeted insert to canonical `runs/laps/lap_suspension`.
4. Remove/replace only the two 0-lap placeholders.
5. Verify:
   - `runs` total expected: 286
   - `laps` total expected: 1279
   - `lap_suspension` total expected: 1279
   - Round7 final expected: 13 runs / 77 laps / 77 lap_suspension
   - non-Round7 1202 laps unchanged
   - `pdf_lap_times_v2_staging` remains 7710
   - `race_lap_detail` VIEW still exists and returns Round7 PASS rows
   - quality/import framework tables still exist and counts are preserved unless explicitly documented
6. Record results in:
   - `05_SCRIPTS/reports/round7_targeted_insert_apply_20260708.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/log.md`

## Provisional clear

Provisional clear should be handled carefully.

Default instruction:

- Do **not** clear `runs_provisional/laps_provisional/lap_suspension_provisional` during the targeted insert unless Code includes it in the readiness and Tatsuki explicitly confirms it in the GO scope.

Recommended sequence:

1. targeted insert final data
2. Workbench confirms final Round7 display
3. separate `Round7 provisional clear GO`

## Explicitly forbidden

- Do not use `cutover_db.py` for this migration.
- Do not rebuild/swap the whole canonical DB.
- Do not drop or recreate `pdf_lap_times_v2_staging`.
- Do not drop or recreate `race_lap_detail` unless strictly necessary and explicitly documented.
- Do not update `source_file_registry`, `import_queue`, `data_quality_log`, `analysis_run_log`, or `metric_version_log`.
- Do not run `refresh_db_master_safe.py`.
- Do not run `sync_to_supabase.py`.
- Do not push to origin.

