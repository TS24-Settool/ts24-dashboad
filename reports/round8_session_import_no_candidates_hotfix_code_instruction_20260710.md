# Round8 Session Import "No Candidates" Hotfix: Code Instruction

Date: 2026-07-10
Priority: P0 field recovery during Round8
Scope: Workbench Import/Quality diagnostics and recovery path for newly saved Round8 2D data
Status: queued for Claude Code

## User Problem

Tatsuki saved Round8 2D data but Workbench `Session Import (staging)` reported:

```text
新規取込候補はありません（queue pending 0）
```

Observed from screenshots and local checks:

- event folder exists: `DATA 2D/20260710-ROUND8-JA52`
- outing folders exist:
  - `FP-JA52-01.MES`
  - `FP-JA52-02.MES`
- Workbench import dry-run log:
  - `05_SCRIPTS/reports/session_import_dryrun_20260710_124550.log`
  - stdout: `候補 0 件（pending 2d_extract がフィルタに一致しない）`
- DB currently has no Round8 rows in `source_file_registry` / `import_queue`.
- `extraction_scan.py --dry-run --min-age 0` can discover files on disk, but dry-run does not write queue rows.

Interpretation:

- The Round8 data is on disk, but it has not been registered into the management tables yet.
- `Session Import` reads `import_queue`; it does not scan the filesystem directly.
- If the user presses Import before Session Scan has completed, or while copy/iCloud sync is still unstable, Workbench shows "no candidates" without explaining the recovery action.

## Immediate Field Instruction

Until the hotfix is implemented, Tatsuki should do this:

1. Wait until the Round8 `.MES` folders finish copying/syncing. In Finder, avoid importing while cloud/upload/progress indicators are visible.
2. In Workbench `Import / Quality`, press `Session Scan` first.
3. After scan completes, press `Session Import (staging)`.
4. Enter `20260710-ROUND8-JA52` when asked for the event.
5. Apply only if the dry-run summary shows Round8 / JA52 / expected FP session candidates.

## Mandatory Reading

- `05_SCRIPTS/extraction_scan.py`
- `05_SCRIPTS/session_extract_staging.py`
- `05_SCRIPTS/ts24_workbench.py`
- `05_SCRIPTS/reports/round8_only_provisional_guard_apply_20260709.md`
- `05_SCRIPTS/reports/round8_live_workflow_preflight_20260709.md`
- `05_SCRIPTS/reports/session_import_dryrun_20260710_124550.log`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`

## Required Outcome

Make the Workbench field workflow fail helpfully:

1. If `Session Import` for a valid Round8 event returns zero candidates, Workbench must check whether a matching event folder exists under `DATA 2D`.
2. If the folder exists but there are no `import_queue` rows for that event, show a clear message:
   - "Round8 data exists on disk but is not scanned yet."
   - "Run Session Scan first, then Import again."
3. Preferably offer a safe button/action to run `Session Scan` from that message.
4. If files are too new/unstable or iCloud placeholders are detected, tell Tatsuki to wait for copy/sync completion and retry scan.
5. Keep the existing Round8-only guard. Do not weaken `--event` / `--required-round ROUND8`.

## Implementation Requirements

### 1. Better zero-candidate diagnosis in Workbench

In `ImportQualityTab._run_import`, when dry-run exits `1`:

- keep the existing no-candidate handling;
- additionally inspect the entered event key;
- check `DATA 2D/<event_key>` existence;
- check whether `source_file_registry` / `import_queue` has rows for that event via `file_path LIKE '%<event_key>%'`;
- distinguish at least these cases:
  1. event folder missing;
  2. event folder exists but not scanned into registry/queue;
  3. event folder exists and queue exists but no pending candidates;
  4. files appear unstable / too recent / iCloud placeholder-like.

### 2. Safe recovery action

Add the smallest practical recovery:

- either a message that explicitly instructs the user to press `Session Scan`;
- or a dialog button that runs the existing `_run_scan()` and tells the user to retry Import after scan.

Do not auto-apply provisional import.

### 3. Optional CLI recovery report

Produce a short field recovery report after implementing/testing:

- `05_SCRIPTS/reports/round8_session_import_no_candidates_hotfix_20260710.md`

Include:

- root cause;
- exact code change;
- how to recover current `20260710-ROUND8-JA52`;
- tests;
- no-write proof for business tables.

## Validation

Required:

1. `python3 -m py_compile extraction_scan.py session_extract_staging.py ts24_workbench.py`
2. Verify `DATA 2D/20260710-ROUND8-JA52` exists and contains `.DDD` / `.LAP` for `FP-JA52-01` and `FP-JA52-02`.
3. Verify before scan that DB has no Round8 registry/queue rows.
4. Run `extraction_scan.py --dry-run --min-age 0` and confirm Round8 files are discoverable without DB write.
5. Test Workbench zero-candidate path shows the new helpful diagnostic.
6. If executing actual `Session Scan`, confirm only management tables change and business/provisional tables remain unchanged.
7. After scan, `Session Import` dry-run for `--event 20260710-ROUND8-JA52 --required-round ROUND8` should show only Round8 candidates, or explain exactly why not.

## Forbidden

- Do not import non-Round8 data.
- Do not remove or weaken Round8-only guard.
- Do not apply without explicit event.
- Do not write canonical business tables.
- Do not finalise Round8.
- Do not clear historical `import_queue`.
- Do not refresh DB Master.
- Do not sync Supabase.
- Do not commit or push.
- Do not add folder watcher auto-apply.
