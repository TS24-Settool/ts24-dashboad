# Post-Round7 Downstream Sync Readiness: Code Instruction

Date: 2026-07-09
Scope: read-only readiness for DB Master refresh, Supabase sync, and origin push decision
Status: queued for Claude Code

## Background

Round7 provisional to final is complete.

Current canonical counts:

- `runs` = 286
- `laps` = 1279
- `lap_suspension` = 1279
- `race_results` = 866
- `runs/laps/lap_suspension_provisional` = 0 / 0 / 0

Report v2 Tier1 report-only feedback fixes are also complete.

The next downstream work should not start by writing to Excel, Supabase, or git. First, Code must produce a readiness package that states exactly what will change, what is already current, what is stale, and what GO text is required.

## Mandatory Reading

Read these first:

- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/00_INBOX/FOR_CLAUDE_CODE.md`
- `05_SCRIPTS/CLAUDE.md` sections 1c, 29, 61, 65, 67
- `05_SCRIPTS/reports/round7_targeted_insert_apply_20260708.md`
- `05_SCRIPTS/reports/report_v2_feedback_report_only_apply_20260708.md`
- `05_SCRIPTS/reports/db_master_refresh_readiness_20260629.md`
- `05_SCRIPTS/reports/db_master_online_sync_audit_20260702.md`
- `05_SCRIPTS/reports/supabase_v2_migration_readiness_20260707.md`
- `05_SCRIPTS/reports/supabase_v2_schema_revision_20260707.md`
- `05_SCRIPTS/refresh_db_master_safe.py`
- `05_SCRIPTS/supabase_audit.py`
- `05_SCRIPTS/sync_to_supabase.py`

## Objective

Produce:

- `05_SCRIPTS/reports/post_round7_downstream_sync_readiness_20260709.md`

This readiness must decide the safest next downstream path after Round7 finalization:

1. DB Master refresh readiness.
2. Supabase current v3 sync/audit readiness.
3. Supabase v2 schema timing recommendation.
4. origin push readiness.
5. import_queue historical cleanup ordering.

## Required Checks

### 1. Local canonical state

Use read-only DB access and confirm:

- current counts for `runs`, `laps`, `lap_suspension`, `race_results`;
- Round7 final counts;
- provisional tables are empty for Round7;
- protected tables remain present and non-dropped:
  - `pdf_lap_times_v2_staging`;
  - `race_lap_detail`;
  - `source_file_registry`;
  - `import_queue`;
  - quality tables;
  - `metric_version_log`.

### 2. DB Master readiness

Do not run `refresh_db_master_safe.py` yet.

Read the wrapper and determine:

- exact workbook path;
- backup path and rollback procedure;
- Excel-open lock behavior;
- expected sheets and row/column impacts after Round7 finalization;
- whether Report v2 Tier1 changes affect DB Master at all.

If ready, propose GO text:

```text
DB Master refresh GO
```

### 3. Supabase current v3 readiness

Do not run `sync_to_supabase.py`.
Do not run any write/upsert/delete.

Read `sync_to_supabase.py` and `supabase_audit.py`.

Determine:

- which four current v3 mirror tables would receive Round7 final changes;
- expected upsert counts if known;
- whether deletes are needed or forbidden;
- whether `race_results` is already current from the earlier Round7 result import;
- whether `lap_times_2d` and `sessions_2d` need sync after finalizing Round7 2D;
- what read-only audit can be run before any sync.

If ready, propose GO text:

```text
Supabase current v3 sync GO
```

### 4. Supabase v2 timing

Do not execute v2 DDL.

State whether G1 `Supabase v2 schema GO` should happen before or after current v3 sync.

Default recommendation should be conservative:

- keep current v3 mirror healthy first;
- then proceed to v2 G1 separately.

### 5. origin push readiness

Do not push.

Inspect git state and summarize:

- current branch;
- uncommitted tracked files;
- important untracked files;
- which changes are operational code vs reports/samples/Obsidian;
- whether any generated artifacts should be excluded from commit.

If ready, propose separate GO text:

```text
origin push readiness GO
```

Do not actually commit or push under this task unless Tatsuki explicitly asks.

### 6. import_queue cleanup ordering

Review the existing queue cleanup task and state whether it should happen:

- before Supabase sync;
- after Supabase sync;
- before next race weekend;
- or only after a separate `queue cleanup GO`.

Default: keep it separate and do not update `import_queue` during this readiness.

## Forbidden

- canonical DB writes;
- DB Master refresh;
- Excel writes;
- Supabase upsert/sync/delete/DDL;
- `sync_to_supabase.py` execution;
- `refresh_db_master_safe.py` execution;
- origin commit or push;
- import_queue updates;
- metric or extraction changes;
- Report v2 changes.

## Deliverable Format

The readiness report must end with:

1. Recommended next GO text.
2. Execution order.
3. Explicit no-go conditions.
4. Rollback plan for each future write step.
5. Open questions for Tatsuki, if any.

