# Round8 Donington Circuit Normalization: Code Instruction

Date: 2026-07-10
Priority: P0 before any Round8 finalization
Scope: read-only readiness/design for `DONINGTONPARK` -> `DONINGTON` normalization
Status: queued for Claude Code

## User / Codex Context

Round8 initial provisional import succeeded after the Session Scan / Import hotfix.

Current observed provisional state:

- Event: `20260710-ROUND8-JA52`
- Session: FP
- Provisional inserted: `2 runs / 21 laps`
- Circuit stored in provisional: `DONINGTONPARK`
- Expected canonical circuit: `DONINGTON`
- Example provisional run ids:
  - `PROV_20260710_ROUND8_DONINGTONPARK_FP_JA52_R1`
  - `PROV_20260710_ROUND8_DONINGTONPARK_FP_JA52_R2`

Obsidian `FOR_CODEX.md` records this as the next high-priority issue:

- provisional `DONINGTONPARK` != canonical `DONINGTON`
- `build_master_db.TRACK_M` has `DONINGTON: 4023`
- `circuit_canon()` has `BALATONPARK -> BALATON` but not `DONINGTONPARK -> DONINGTON`
- Round8 HED says `Circuit=Donington`, `Track Length=4023`
- Report DAY1 CIRCUIT likely says `DONINGTON PARK`, which currently canonicalizes to `DONINGTONPARK`

This must be resolved before any Round8 finalization. Otherwise Round8 final data can be locked in under `DONINGTONPARK`, producing duplicate circuit names and weaker outlap/track-length logic.

## Objective

Produce a read-only readiness/design report:

- `05_SCRIPTS/reports/round8_donington_circuit_normalization_readiness_20260710.md`

The report must decide the safest implementation plan for normalizing Round8 Donington to canonical `DONINGTON`, without applying the change yet.

## Mandatory Reading

- `08_OBSIDIAN/TS24_Engineering_Knowledge/00_INBOX/FOR_CODEX.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `05_SCRIPTS/CLAUDE.md` sections 27d-2, 32b, 65, 68, 69
- `05_SCRIPTS/build_master_db.py`
- `05_SCRIPTS/session_extract_staging.py`
- `05_SCRIPTS/ts24_workbench.py`
- `05_SCRIPTS/reports/session_staging_apply_20260710_134502.md`
- `05_SCRIPTS/reports/round8_session_import_no_candidates_hotfix_20260710.md`
- `05_SCRIPTS/reports/round8_only_provisional_guard_apply_20260709.md`

## Required Checks

### 1. Confirm current Round8 provisional state

Use read-only DB access and confirm:

- `runs_provisional` / `laps_provisional` / `lap_suspension_provisional` Round8 counts;
- circuit values currently stored;
- run_id / lap_id prefixes containing `DONINGTONPARK`;
- source provenance fields for event/session/rider;
- business tables remain unchanged.

### 2. Confirm canonical Donington state

Read-only confirm:

- `TRACK_M["DONINGTON"] == 4023`;
- existing canonical rows using `DONINGTON`;
- whether any canonical business table currently uses `DONINGTONPARK`;
- BSB/COMPANY Donington rows and `data_scope` separation from WorldSSP data.

### 3. Confirm source cause

Confirm the source of `DONINGTONPARK`:

- Report `01_REPORTS/JA52/20260710-ROUND8-JA52.xlsx` DAY1 CIRCUIT value;
- HED circuit / track length from `DATA 2D/20260710-ROUND8-JA52/FP-JA52-01.MES/*.HED`;
- whether `.line` source is absent;
- exact `circuit_canon()` behavior for `DONINGTON PARK`, `DONINGTONPARK`, and `DONINGTON`.

### 4. Design the minimal fix

Default expected design:

```python
"DONINGTONPARK": "DONINGTON"
```

added to `circuit_canon()` mapping in `build_master_db.py`, matching the existing `BALATONPARK -> BALATON` precedent.

But Code must evaluate whether related local copies/helpers also need the same normalization to avoid inconsistency, for example:

- `lap_overlay_extractor.py`
- `lap_suspension_stats.py`
- any report/workbench helper that duplicates circuit aliases

Do not edit files yet in this readiness task.

### 5. Define apply strategy after GO

The readiness report must state exactly what should happen after Tatsuki approves:

- code changes required;
- whether current Round8 provisional rows should be regenerated or updated;
- if updating provisional rows, exact tables/columns affected;
- how run_id/lap_id changes are handled;
- how to keep provenance stable;
- rollback plan;
- validation gates before allowing Round8 finalization.

### 6. Round8 operations recommendation

State whether additional Round8 sessions can continue to be provisional-imported before the normalization fix.

Default recommendation:

- If more sessions arrive before the fix, they may also import as `DONINGTONPARK`;
- therefore either apply the normalization fix first, or treat all Round8 provisional rows as needing one controlled re-normalization before finalization;
- **do not finalise Round8 until this is fixed and verified.**

## Forbidden

- Do not change `circuit_canon()` yet.
- Do not rewrite provisional rows yet.
- Do not update run_id/lap_id yet.
- Do not finalise Round8.
- Do not write canonical business tables.
- Do not refresh DB Master.
- Do not sync Supabase.
- Do not commit or push.
- Do not clear historical `import_queue`.
- Do not weaken Round8-only guard.

## Deliverable Format

The report must end with:

1. recommended fix;
2. exact GO text for implementation;
3. apply order;
4. no-go conditions;
5. rollback plan;
6. whether Round8 provisional work can continue before the fix.

Suggested GO text:

```text
Round8 Donington normalization GO
```
