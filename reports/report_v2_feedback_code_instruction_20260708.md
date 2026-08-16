# Report v2 Feedback: Code Instruction

Date: 2026-07-08
Scope: read-only audit first
Priority: after the current Round7 targeted insert reaches a safe checkpoint, unless only read-only inspection is performed

## Source

Obsidian note:

- `08_OBSIDIAN/TS24_Engineering_Knowledge/08_REPORT_NOTES/2026-07-08_Report_Feedback.md`

Reference report:

- `suspension_report_v2_MISANO_JA52_ALL_PROVISIONAL_20260708_164053.pdf`

## Objective

Review the Report v2 feedback and determine the next concrete changes without rebuilding the whole TS24 system.

The main concern is not visual polish. The P0 question is whether the current Sus_Speed values in the report are technically correct, because Tatsuki's engineering expectation conflicts with the displayed Braking vs Apex values.

## Mandatory Reading

Read these before making recommendations:

- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/08_REPORT_NOTES/2026-07-08_Report_Feedback.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/11_ENGINEERING_KNOWLEDGE/Suspension_Damping.md`
- `05_SCRIPTS/reports/phase_susp_speed_metric_design_20260701.md`
- `05_SCRIPTS/suspension_report.py`
- `05_SCRIPTS/ts24_workbench.py`
- `05_SCRIPTS/build_master_db.py`
- `05_SCRIPTS/apply_phase_susp_speed.py`
- `05_SCRIPTS/backfill_susp_zone_speed.py`

## Phase A: Read-only Audit

Produce:

- `05_SCRIPTS/reports/report_v2_feedback_audit_20260708.md`

Required sections:

1. Current report path, input data source, and whether it is provisional/final.
2. Exact current Report v2 metric mapping for position and Sus_Speed.
3. Sus_Speed anomaly audit:
   - compare Braking, Apex, and Exit distributions for MISANO JA52;
   - verify phase masks (`FULL_BRAKING`, `MID_CORNER`, `CORNER_EXIT`);
   - verify F/R direction, compression/rebound sign, unit, resampling interval, `avg`, `peak`, and sample-count behavior;
   - recompute at least 2-3 representative laps from source traces where possible;
   - show trace evidence for phase windows, F/R position, and F/R velocity over time.
4. Ohlins definition lookup:
   - search local files for Ohlins Setting Bank Excel/PDF;
   - if found, map its low/high speed, compression, and rebound definitions to TS24 columns;
   - if not found, report exactly what was searched and stop before changing semantics.
5. Lap filter proposal:
   - propose deterministic report-only filtering for slow outlier laps;
   - list candidate exclusion reasons, such as out lap, in lap, formation/first-lap behavior, or lap-time outlier versus session median;
   - require page-2 disclosure of applied filter and excluded lap list.
6. Visualization proposal:
   - evaluate dual Y axes versus normalized index or F/R small multiples;
   - call out any risk of misleading interpretation.
7. Recommendation:
   - no issue found / report-only fix / metric label fix / extraction logic defect / phase mask defect;
   - minimal implementation plan;
   - required approval text if implementation changes metrics or extraction logic.

## Phase B: Implementation Gate

Do not implement metric or extraction changes during Phase A.

If the audit recommends a report-only visualization/filter change, wait for:

```text
Report v2 feedback report-only GO
```

If the audit proves a metric definition, phase mask, or 2D extraction defect, wait for a stronger explicit approval:

```text
Suspension speed extraction fix GO
```

## Guardrails

Forbidden during this task:

- canonical DB writes;
- provisional clear;
- Round7 targeted insert changes;
- DB Master refresh;
- Supabase sync or DDL;
- origin push;
- changing metric definitions without audit evidence;
- rebuilding the whole system;
- silent report filtering without page-2 disclosure.

Round7 note:

- The current Round7 provisional to final work remains the active priority.
- This task can run read-only in parallel only if it does not interfere with Round7 materialize/rebuild/apply work.

