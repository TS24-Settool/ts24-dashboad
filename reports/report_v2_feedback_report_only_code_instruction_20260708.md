# Report v2 Feedback Phase B: Report-only Implementation Instruction

Date: 2026-07-08
Scope: Report v2 presentation/filter changes only
Status: instruction queued, implementation requires explicit GO

## Source

Read first:

- `05_SCRIPTS/reports/report_v2_feedback_audit_20260708.md`
- `05_SCRIPTS/reports/report_v2_feedback_code_instruction_20260708.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/08_REPORT_NOTES/2026-07-08_Report_Feedback.md`

## Objective

Prepare the Tier 1 Report v2 fixes recommended by the Phase A audit.

This task is about preventing the current report from misleading the user. It is not a DB, extraction, or metric-definition task.

## Current Technical Conclusion

The `Sus_Speed` Braking/Apex inversion is real and systemic, but the Phase A audit classified it as a phase-window artifact, not a computation bug.

Current `brk_f_dive_spd_avg` measures the deep-stroke / settled braking dwell, not the initial braking dive-in transient. Therefore the report must stop presenting it as an intuitive "front dive speed under braking" value.

## Phase B0: Read-only Implementation Plan

Before editing code, produce:

- `05_SCRIPTS/reports/report_v2_feedback_report_only_plan_20260708.md`

The plan must specify exact proposed changes, touched functions, screenshots/sample output targets, rollback, and validation.

Mandatory proposed changes:

1. Rename/annotate the Sus_Speed labels so Braking F-Dive is explicitly described as deep-stroke / settled-window.
2. Add a short report note explaining that `Sus_Speed` is an uncalibrated relative damping-speed index and not directly comparable to Ohlins low/high-speed force-vs-velocity maps.
3. Fix or clearly disclose the peak reducer asymmetry:
   - legacy Braking peak currently uses max;
   - newer Apex/Exit peaks use p95.
4. Improve F/R suspension position readability using small multiples as the preferred design.
   - Dual Y-axis is allowed only if the plan justifies why small multiples are not practical.
5. Add report-only slow-lap filtering design with mandatory page-2 disclosure:
   - exact filter rule;
   - excluded lap list;
   - exclusion reason per lap;
   - "no laps filtered" statement if none are excluded.

## Phase B1: Implementation Gate

Do not edit implementation files until Tatsuki gives the exact approval:

```text
Report v2 feedback report-only GO
```

After GO, keep the implementation minimal and likely limited to:

- `05_SCRIPTS/suspension_report.py`
- `05_SCRIPTS/ts24_workbench.py` only if the report button or preview text must change

## Required Validation After GO

1. `python3 -m py_compile suspension_report.py ts24_workbench.py`
2. Generate a sample Report v2 PDF/PPTX for MISANO JA52 after Round7 finalization.
3. Confirm filename no longer carries `_PROVISIONAL_` for final data.
4. Confirm page-2 filter disclosure appears.
5. Confirm F/R position readability is improved.
6. Confirm DB counts are unchanged before/after.
7. Record results in:
   - `05_SCRIPTS/reports/report_v2_feedback_report_only_apply_20260708.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
   - `08_OBSIDIAN/TS24_Engineering_Knowledge/log.md`

## Forbidden

- canonical DB writes;
- adding or changing metric definitions;
- changing `build_master_db.py` metric formulas;
- changing phase masks;
- adding brake-onset dive columns;
- DB Master refresh;
- Supabase sync or DDL;
- origin push;
- silent filtering without page-2 disclosure.

If the work requires any extraction or DB metric change, stop and request:

```text
Suspension speed extraction fix GO
```
