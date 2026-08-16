# Round8-only Provisional Guard: Code Instruction

Date: 2026-07-09
Priority: P0 before Round8 first session
Scope: prevent non-Round8 data from being applied into provisional tables during Round8 live workflow
Status: queued for Claude Code

## User Requirement

Tatsuki requirement:

> 必ずRound8のデータだけをPrevisionalで表示、Reportを作成できる様にして下さい

Interpretation:

- Round8 session data must be usable as provisional in Workbench and Report v2.
- Non-Round8 historical pending data must not be importable through the live provisional path.
- This must be enforced by code/guardrails, not only by human attention.

## Current Risk

The system already has:

- `Session Scan` button;
- `Session Import (staging)` button;
- `session_extract_staging.py --event/--session/--apply`;
- provisional overlay in Workbench;
- Report v2 provisional confirmation and `_PROVISIONAL_` output.

But the Workbench import button currently calls:

```text
session_extract_staging.py
session_extract_staging.py --apply
```

without `--event`.

Because historical `import_queue pending` rows still exist, an unfiltered import can present or apply old events. That is not acceptable for Round8.

## Required Outcome

Before Round8 live use, Code must ensure:

1. Provisional import can be filtered to a specific Round8 event.
2. Workbench cannot apply an unfiltered provisional import.
3. Workbench cannot apply non-Round8 candidates during Round8 mode.
4. Report v2 can only be generated from visible/selected provisional Round8 runs when Tatsuki intentionally selects them.

## Mandatory Reading

- `05_SCRIPTS/session_extract_staging.py`
- `05_SCRIPTS/ts24_workbench.py`
- `05_SCRIPTS/reports/workbench_session_import_button_20260707.md`
- `05_SCRIPTS/reports/race_weekend_live_workflow_design_20260706.md`
- `05_SCRIPTS/reports/report_v2_provisional_mode_apply_20260706.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`

## Implementation Requirement

Implement a minimal hard guard. Preferred design:

### 1. `session_extract_staging.py` apply guard

Add an apply-time guard:

- `--apply` must require an explicit `--event`.
- For Round8 live workflow, `--event` must contain `ROUND8`.
- If `--apply` is called without `--event`, exit non-zero before any write.
- If `--apply` is called with a non-Round8 event during this Round8 guard, exit non-zero before any write.

If Code decides a general future-proof flag is cleaner, acceptable alternative:

```text
--required-round ROUND8
```

Then `--apply --required-round ROUND8` must reject any candidate/event not matching ROUND8.

### 2. Workbench import UI guard

Modify `ImportQualityTab._run_import` so the import subprocess never runs unfiltered for Round8 live use.

Minimum acceptable behavior:

- ask/select/require an event key before dry-run;
- pass `--event <event_key>` to both dry-run and apply;
- reject empty event key;
- reject event keys that do not include `ROUND8` while this Round8 guard is active;
- show the event key in the confirmation dialog;
- Apply dialog must state that only this event will be applied.

If adding a full UI selector is too large, a simple modal text input for the event key is acceptable as a first-safe version.

### 3. Dry-run result guard

Before enabling/applying:

- parse or inspect dry-run output/report enough to confirm candidates are for the requested Round8 event only;
- if any candidate outside the requested event appears, block Apply.

### 4. Report behavior

Do not change Report v2 metric definitions.

Confirm that after Round8 provisional import:

- Workbench run list shows only selected/imported Round8 provisional runs when filtering to that event/rider/session;
- Report v2 provisional confirmation still appears;
- generated report filename/cover includes `PROVISIONAL`.

## Deliverables

Produce:

- `05_SCRIPTS/reports/round8_only_provisional_guard_apply_20260709.md`

Include:

1. exact code changes;
2. dry-run/apply guard behavior;
3. tests run;
4. no-write proof for rejected non-Round8 apply;
5. Round8-only successful dry-run path;
6. rollback instructions.

## Validation

Required validation:

1. `python3 -m py_compile session_extract_staging.py ts24_workbench.py`
2. `session_extract_staging.py --apply` without `--event` must fail before write.
3. `session_extract_staging.py --event <non-Round8> --apply` must fail before write while Round8 guard is active.
4. `session_extract_staging.py --event <ROUND8_EVENT>` dry-run path must work, even if there are no candidates yet.
5. Workbench import path must pass `--event <ROUND8_EVENT>` to dry-run and apply.
6. DB business counts remain unchanged in all guard-failure tests.
7. provisional tables remain unchanged in all guard-failure tests.

If no actual Round8 data exists yet, simulate only guard paths and document that successful apply validation must occur after the first real Round8 session file arrives.

## Forbidden

- Do not import historical pending data.
- Do not apply without explicit Round8 event.
- Do not update canonical business tables.
- Do not finalise Round8 data.
- Do not clear historical `import_queue`.
- Do not refresh DB Master.
- Do not sync Supabase.
- Do not commit or push.
- Do not add folder watcher automation.

