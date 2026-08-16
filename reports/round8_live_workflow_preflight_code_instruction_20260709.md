# Round8 Live Workflow Preflight: Code Instruction

Date: 2026-07-09
Scope: read-only / operational preflight before Round8 sessions
Status: queued for Claude Code

## Objective

Confirm that after a Round8 session, newly saved 2D data can be taken into the provisional workflow and shown in Workbench, then used to generate a provisional Report v2.

Important distinction:

- The system is not designed as "save file and fully automatic import".
- The current safe workflow is button-driven:
  1. save 2D data under `DATA 2D/<event>/`;
  2. Workbench `Import / Quality` -> `Session Scan`;
  3. Workbench `Session Import (staging)` -> dry-run confirmation -> Apply only if the candidates are the new Round8 outing(s);
  4. Workbench Suspension/Posture refresh shows `PROV_...` / `⏳ ...(prov)`;
  5. `Create Report v2` asks for provisional confirmation and generates a `_PROVISIONAL_` report.

## Mandatory Reading

- `05_SCRIPTS/reports/race_weekend_live_workflow_design_20260706.md`
- `05_SCRIPTS/reports/workbench_provisional_overlay_apply_20260706.md`
- `05_SCRIPTS/reports/report_v2_provisional_mode_apply_20260706.md`
- `05_SCRIPTS/reports/workbench_session_import_button_20260707.md`
- `05_SCRIPTS/reports/report_v2_feedback_report_only_apply_20260708.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/CURRENT_STATE.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/03_AI_HANDOFF/AI_HANDOFF_LATEST.md`
- `05_SCRIPTS/session_extract_staging.py`
- `05_SCRIPTS/extraction_scan.py`
- `05_SCRIPTS/ts24_workbench.py`

## Required Deliverable

Produce:

- `05_SCRIPTS/reports/round8_live_workflow_preflight_20260709.md`

The report must answer:

1. Is the Round8 live provisional workflow implemented?
2. Is it fully automatic or button-driven?
3. What exact steps should Tatsuki perform after each session?
4. What can go wrong because of historical `import_queue` pending rows?
5. How should Code/Workbench prevent accidental import of old pending data?
6. What is the exact no-go condition for pressing Apply?
7. What should be verified after Apply?

## Required Checks

### 1. Confirm implemented capabilities

Verify from code/docs:

- `Session Scan` button exists.
- `Session Import (staging)` button exists.
- `session_extract_staging.py` supports `--event`, `--session`, and `--apply`.
- Workbench overlays `lap_suspension_provisional` with final `lap_suspension`.
- provisional runs are visibly marked in Run selection.
- Report v2 has provisional confirmation and `_PROVISIONAL_` filename/cover behavior.
- Report v2 Tier1 label/filter changes still apply to provisional reports.

### 2. Confirm operational limitation

State clearly:

- saving a file alone does not import it;
- no folder watcher auto-apply is enabled;
- user must run Scan then Import and confirm Apply;
- this is intentional for iCloud/copy-in-progress safety.

### 3. Historical pending risk

Review current `import_queue` status.

Known risk from Task 4:

- historical pending rows can produce old insert candidates if unfiltered;
- Apply should not be pressed unless the dry-run summary clearly references the current Round8 event/session/rider only.

If Code finds that Workbench's import button still runs `session_extract_staging.py --apply` without an event filter, highlight it as a Round8 operational risk and recommend either:

- Code operator uses CLI with explicit `--event <ROUND8_EVENT>` / `--session <SESSION>` for the first Round8 session; or
- Workbench import UI is updated later to pass an event/session filter after a separate GO.

Do not implement that UI change in this preflight unless explicitly approved.

### 4. Round8 session checklist

Create a concise field checklist:

1. Ensure 2D copy is complete, no `.icloud`/partial files.
2. Use the expected event folder naming pattern.
3. Click `Session Scan`.
4. Click `Session Import (staging)`.
5. In the dry-run dialog, confirm event/session/rider/lap counts.
6. Press Apply only when candidates are the new Round8 session.
7. Confirm Workbench shows `⏳ ... (prov)`.
8. Generate Report v2 and accept provisional confirmation.
9. Confirm report filename/cover shows `PROVISIONAL`.

## Forbidden

- Do not write canonical business tables.
- Do not run `session_extract_staging.py --apply` on historical pending rows.
- Do not clear or update `import_queue`.
- Do not change Workbench UI.
- Do not add folder watcher automation.
- Do not refresh DB Master.
- Do not sync Supabase.
- Do not commit or push.

