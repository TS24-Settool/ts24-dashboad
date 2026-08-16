# Race Weekend Workbench Data Ops Hardening: Code Instruction

Date: 2026-07-10
Priority: P0 before next Round8 session
Scope: make Workbench race-weekend data operations fail-closed and self-checking
Mode: implement Workbench safety hardening; no canonical writes

## User requirement

Tatsuki requirement:

> Race weekend のワークフローに関して Workbench のデータ作業で絶対に問題が起きないよう対策して下さい。

Current Round8 FP and QP provisional import is working:

- FP provisional: 2 runs / 21 laps.
- QP provisional: 3 runs / 18 laps.
- Current provisional total: 5 runs / 39 laps / 39 lap_suspension.
- Canonical business tables remained unchanged after QP apply:
  - runs 286
  - laps 1279
  - lap_suspension 1279
  - race_results 866
  - pdf_lap_times 7613
  - pdf_lap_times_v2_staging 7710
- Round8 canonical rows remain 0.
- Canonical `PROV_%` contamination remains 0.

The system is functional, but the race-weekend workflow still has avoidable operational risk because it relies on the operator remembering the exact safe sequence:

```text
save raw 2D folder -> Session Scan -> Session Import dry-run -> human candidate check -> Apply -> verify provisional overlay -> Report v2 provisional
```

Code must harden this path so Workbench itself continuously tells the operator what is safe, what is blocked, and what action is next.

## Non-negotiable workflow model

Race weekend provisional display is raw-2D-first and offline-capable:

- Report completion is not required for provisional 2D extraction.
- DB Master is not required.
- Supabase / online services are not required.
- Canonical finalization is not required and must not happen during live session intake.
- Queue/registry are management and audit layers, but not the only way to discover newly saved raw 2D folders.
- Final promotion from provisional to canonical happens only after the race weekend and only under a separate explicit GO.

## Required implementation

Add a Workbench-side safety layer for `ImportQualityTab`.

### 1. Add `Race Weekend Status` / `Session Intake Health` panel

In the `Import / Quality` tab, add a compact status area or subtab that shows the current Round8 event state:

```text
event: 20260710-ROUND8-JA52
raw_2d_on_disk: FP=2 QP=3 total=5
registered_2d: FP=2 QP=3 total=5
queue_2d: pending=0 awaiting_gate=5 failed=0 skipped=0
provisional: FP=2 runs / 21 laps, QP=3 runs / 18 laps, total=5 / 39
canonical_round8: runs=0 laps=0 lap_suspension=0 race_results=0
report_pending_rows: 1 (not a blocker for 2D provisional)
next_action: safe / waiting for new raw 2D / or exact button to press
```

The status must be computed from local disk + SQLite only. No network. No Supabase. No DB Master.

### 2. Make the workflow fail-closed before Apply

Before enabling or running Apply, Workbench must confirm:

- event contains `ROUND8`;
- dry-run candidates are only the selected Round8 event;
- candidate sessions are explicitly listed;
- no non-Round8 candidate is present;
- no historical pending queue row is included;
- disk raw 2D outing count, queue candidate count, and dry-run candidate names are consistent;
- report pending rows are not counted as 2D candidates;
- canonical Round8 rows are still 0 unless Tatsuki has explicitly started finalization;
- expected provisional delta is shown before apply.

If any check fails, block Apply and show the exact reason.

### 3. Add a post-apply invariant check

Immediately after successful `session_extract_staging.py --apply`, Workbench must run a read-only invariant check and show a concise result:

```text
canonical unchanged: PASS
provisional delta: +3 runs / +18 laps / +18 lap_suspension
Round8 only: PASS
PROV contamination in canonical: PASS
DONINGTONPARK canonical contamination: PASS
report prerequisite not required: PASS
```

If any invariant fails, show a red failure dialog with:

- log path;
- backup path if available;
- which table changed;
- "do not continue / call Code" wording.

### 4. Add explicit session filter control

The current import can run `session=ALL`. For live race-weekend operation, this is sometimes acceptable but easy to misunderstand.

Add one of the following:

- a required session selector for `Session Import` (`FP`, `QP`, `WUP`, `RACE1`, `RACE2`, `ALL`);
- or a confirmation dialog that clearly lists candidate sessions and run counts before Apply.

Default should be safe:

- If newly detected candidates are only one session, preselect that session.
- If multiple sessions are pending, require explicit confirmation.

### 5. Strengthen raw 2D direct reconciliation

Extend `_reconcile_event_outings` or add a companion helper so Workbench can summarize by session:

```text
disk_by_session
registry_by_session
queue_by_session
provisional_by_session
missing_by_session
failed_by_session
```

Use this for both popup diagnosis and the status panel.

### 6. Add a one-click "Safety Audit" report

Add a button or menu action that writes a read-only Markdown report:

```text
05_SCRIPTS/reports/race_weekend_workbench_safety_audit_<timestamp>.md
```

The report must include:

- raw disk folders;
- registry/queue state;
- provisional state;
- canonical invariants;
- latest scan/import logs;
- recommended next action;
- explicit PASS/FAIL summary.

This is useful before every session and before leaving the circuit.

## Validation checklist

1. `PYTHONPYCACHEPREFIX=/private/tmp/ts24_pycache python3 -m py_compile ts24_workbench.py extraction_scan.py session_extract_staging.py`
2. With current Round8 data, safety panel must show:
   - disk total 5 outings;
   - provisional total 5 runs / 39 laps;
   - canonical Round8 0;
   - report pending 1 not blocking.
3. Current DB business table counts must remain:
   - runs 286
   - laps 1279
   - lap_suspension 1279
   - race_results 866
   - pdf_lap_times 7613
   - pdf_lap_times_v2_staging 7710
4. No new canonical rows.
5. No automatic Apply.
6. Round8 guard unchanged.
7. Offscreen Workbench smoke: all 7 tabs construct.
8. Generate one safety audit report and verify it is read-only.

## Forbidden

- Do not write canonical business tables.
- Do not finalize Round8.
- Do not clear provisional rows.
- Do not run DB Master refresh.
- Do not run Supabase sync.
- Do not commit or push.
- Do not add folder watcher auto-apply.
- Do not weaken `--event` / `--required-round ROUND8`.
- Do not make Report completion a prerequisite for provisional 2D extraction.

## Deliverable

Create:

```text
05_SCRIPTS/reports/race_weekend_workbench_data_ops_hardening_20260710.md
```

The deliverable must state exactly what is now impossible or blocked by Workbench, and what remains a human confirmation step.
