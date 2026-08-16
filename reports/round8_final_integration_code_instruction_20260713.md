# Code Instruction — ROUND8 final DB integration, Race2 telemetry hold

Date: 2026-07-13  
Priority: P0  
Authorization from Tatsuki: inspect all newly saved ROUND8 sources, update the local canonical DB with every valid available dataset, update Workbench with all valid final data **except Race2 2D/telemetry**, and in parallel build the hardened post-Round8 event-control system required to prevent the failures discovered during Round8.

## Source state confirmed by Codex

- Report: `01_REPORTS/JA52/20260710-ROUND8-JA52.xlsx` (updated 2026-07-12 19:10).
- Original: `04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx` (updated 2026-07-12 19:10).
- Result PDFs: FP, QP, WUP1, RACE1, WUP2 and RACE2 are present under `07_RESULTS/ROUND8_DONINGTON_20260710/`; WUP2 and RACE2 were added 2026-07-13.
- Raw 2D exists for both riders through the available sessions. Current event folders contain FP/QP or SP/WUP1/WUP2/RACE1 data.
- **No Race2 `.MES` folder exists for JA52 or DA77. This is the only declared missing source.**
- Current local DB has canonical ROUND8 telemetry = 0. Provisional ROUND8 currently has 15 runs / 137 laps / 137 suspension rows:
  - JA52: FP 2/21, QP 3/18, WUP1 1/7, WUP2 1/7, RACE1 1/20.
  - DA77: FP 2/19, SP 3/18, WUP1 1/7, RACE1 1/20.

## Required interpretation of the Race2 hold

The hold applies **only** to Race2 raw-2D-derived telemetry and its Workbench telemetry presentation.

- Import and validate the Race2 Result PDF into the appropriate official/PDF canonical tables (`race_results`, `pdf_lap_times` and/or the approved v2 path) if the extractor and quality gates pass.
- Do not fabricate Race2 runs, laps, suspension values, run numbers, setup linkage or placeholders to make Workbench look complete.
- Do not promote any Race2 row into canonical `runs`, `laps`, or `lap_suspension` without an actual Race2 2D source.
- Workbench must not show Race2 as final telemetry and must not silently reuse Race1/provisional data. A clear unavailable/pending state is acceptable if the current UI exposes the session.
- All other valid ROUND8 sessions must be finalized and made available in Workbench.

## Execution order

### Phase 1 — mandatory read-only closure audit

1. Re-read the Obsidian state and the design in `08_OBSIDIAN/TS24_Engineering_Knowledge/04_SYSTEM_DESIGN/2026-07-11_Round8_Closure_and_Round9_Readiness.md`.
2. Inventory every ROUND8 source by rider/session/type/hash/mtime. Detect duplicate outing names (notably DA77 SP variants), zero-lap folders, unknown `SX_*` folders, and missing Report coverage. Never infer acceptance from folder presence alone.
3. Run the approved extractors in dry-run/scratch mode against:
   - both raw 2D event folders;
   - the updated JA52 Report;
   - updated `Data_Base_TS24_ORIGINAL.xlsx`;
   - all six Result PDFs.
4. Produce a session/source matrix with statuses: valid-finalizable, official-PDF-only, rejected-with-reason, and missing. Race2 must be `official-PDF-only / telemetry pending`.
5. Build a ROUND8-only scratch DB using the same canonical `build_master_db` logic used for Round7 finalization. Confirm circuit is exactly `DONINGTON`, never `DONINGTONPARK`.
6. Cross-check Report ↔ Original ↔ Result PDF ↔ scratch 2D for rider/session/run/lap counts, best laps, setup fields, and official race results. Any unexplained mismatch is NO-GO.
7. Save the readiness result to `05_SCRIPTS/reports/round8_final_integration_readiness_20260713.md` before writes.

### Phase 2 — canonical local DB apply (authorized, only after all gates pass)

Use the Round7 targeted-insert method as the reference, generalized safely for ROUND8. Do not use an unscoped full cutover.

1. Take a WAL-safe full backup of `02_DATABASE/ts24_unified.db` immediately before each write stage.
2. Apply validated Result PDF data for every session, including Race2, through the existing official/PDF canonical pipeline. Preserve non-ROUND8 rows and protected tables/views.
3. Insert the ROUND8-only scratch telemetry into canonical `runs`, `laps`, `lap_suspension` for all valid available non-Race2 sessions only.
4. Race2 telemetry insert count must be exactly zero. Add a hard assertion for this condition.
5. Use explicit column lists, one transaction, deterministic event filters, before/after protected-table checks, orphan/duplicate checks, lap↔suspension equality, source hashes, and rollback on any failed invariant.
6. Remove ROUND8 provisional rows only after the equivalent non-Race2 canonical content is verified. Do not clear evidence needed to reconcile rejected/failed sources; document their terminal queue/quality state.
7. Do not mass-clean historical queue entries. Any queue changes must be ROUND8 source-specific and justified in the report.

### Phase 3 — Workbench verification

1. No special Race2 telemetry implementation or fake placeholder.
2. Offscreen smoke all Workbench tabs and confirm DONINGTON final data appears for all finalized non-Race2 sessions/riders.
3. Confirm no duplicate final+provisional runs, no `PROV_` rows in canonical tables, and no `DONINGTONPARK` residue.
4. Confirm Race2 Race Analysis may use validated official/PDF data where that is the established source, but Suspension/Posture telemetry for Race2 remains absent/pending.
5. Confirm selecting Race2 cannot surface Race1 rows or stale provisional rows.

## Acceptance gates

- Every saved ROUND8 file is inventoried with hash and disposition; no silent skip.
- Result PDF coverage includes FP/QP/WUP1/WUP2/RACE1/RACE2.
- Race2 official results/PDF data are present after apply if extraction gates pass.
- Race2 canonical telemetry = 0 and Workbench Race2 telemetry = unavailable/pending.
- All valid non-Race2 ROUND8 telemetry is canonical final and visible in Workbench.
- Canonical/provisional duplication = 0; orphan laps/suspension = 0; duplicate run IDs = 0.
- Non-ROUND8 canonical content and all protected tables/views remain unchanged except explicitly approved shared official-result refresh effects.
- Backups and exact rollback commands are recorded.

## Deliverables and documentation

- `05_SCRIPTS/reports/round8_final_integration_readiness_20260713.md`
- `05_SCRIPTS/reports/round8_final_integration_apply_20260713.md`
- Update `05_SCRIPTS/CLAUDE.md`, Obsidian `log.md`, `CURRENT_STATE.md`, `03_AI_HANDOFF/AI_HANDOFF_LATEST.md`, and the Result section of the inbox task.
- Report exact before/after counts by table/session/rider and list every rejected source with reason.

## Parallel Track B — hardened race-weekend system (explicitly authorized)

This track runs alongside the final-integration work, but must be isolated from the production DB apply path. Use the existing designs as the baseline:

- `08_OBSIDIAN/TS24_Engineering_Knowledge/04_SYSTEM_DESIGN/2026-07-11_Race_Weekend_Event_Control_Plane.md`
- `08_OBSIDIAN/TS24_Engineering_Knowledge/04_SYSTEM_DESIGN/2026-07-11_Round8_Closure_and_Round9_Readiness.md`
- `05_SCRIPTS/reports/race_weekend_event_control_plane_readiness_20260711.md`
- `05_SCRIPTS/reports/round8_live_intake_p0_operations_gate_20260711.md`

### Isolation rule

- Track A owns the real ROUND8 source audit and canonical DB apply.
- Track B must use fixtures, temporary event roots and scratch DB copies until Track A finalization and Workbench verification are complete.
- Track B may implement code concurrently, but must not run migration/schema/runtime experiments against the production DB or alter the Round8 source folders.
- Do not merge a Track B behavior change into the production Workbench path before its full adversarial acceptance suite passes and Track A has a stable rollback point.

### Required implementation scope

Implement the previously designed Event Control Plane in gated phases B-1 → B-2 → B-3.

1. **Event Manifest and State Ledger**
   - Versioned, content-hashed manifest with one active event, explicit event key/date/round/circuit/riders/raw roots/allowed sessions/status/schema version.
   - Lock/activation semantics and operator approval record.
   - Ledger states: discovered → registered → candidate_ready → staged → verified → reportable → finalized, plus explicit WARNING/FAIL/SKIP branches.
   - Immutable receipts for scan, dry-run, apply, expected deltas, source fingerprints, backup and rollback.

2. **Event-scoped Scan**
   - Live scan reads only manifest-declared roots; global historical scan becomes a separate maintenance command/UI action.
   - Disk, registry, queue and candidate selection must agree on event + rider + session + outing stem + content fingerprint.
   - A copied-but-incomplete folder, changing file size/hash, unknown session or event-external source fails closed without contaminating the live queue.

3. **Fail-closed Import/Apply**
   - Active event and required round are mandatory in both Workbench and direct CLI apply; omission or mismatch is a hard refusal.
   - Deterministic run identity cannot be batch-relative. Repeated scans/imports are idempotent.
   - Same-name/same-content is a no-op; same-name/different-content is a conflict requiring explicit resolution, never silent overwrite.
   - Pre-apply collision checks compare candidates to canonical and provisional run IDs and expected deltas before any write.
   - Use a single transaction plus WAL-safe backup/restore verification and durable failure receipts.

4. **Workbench safety/control UI**
   - Show active event, manifest hash/version, source completeness, queue counts scoped to the event, current ledger state and last successful receipt.
   - Separate `Live Event Scan` from `Historical Maintenance Scan` visually and operationally.
   - Dry-run dialog must show the exact source files, fingerprints, rider/session/run mapping, predicted inserts/updates/skips and stop reasons.
   - Apply remains explicit confirmation with default Cancel. Status/Safety Audit verifies post-apply invariants.
   - Missing Race2 2D must be represented as `telemetry pending`, while official/PDF Race2 data remains independently available.

5. **Round9 readiness and configuration**
   - Remove hard-coded Round8 behavior; derive the active round/event only from the validated manifest.
   - Provide a Round9 manifest template and a pre-event activation checklist without activating a real Round9 event yet.
   - Preserve backward read compatibility with existing final/provisional data and reports.

### Mandatory adversarial tests

All must run on fixtures/scratch DB and fail closed where expected:

- zero or multiple active manifests;
- tampered manifest/hash/version;
- event-external and historical pending candidates;
- direct CLI apply without active event/required round;
- same outing imported twice;
- same path/name with changed content;
- two batches that would previously generate the same run ID;
- partially copied/changing 2D folder;
- unknown session aliases and zero-valid-lap outing;
- crash/interruption before backup, during transaction and after commit before receipt;
- canonical/provisional duplication, orphan lap/suspension and predicted-delta mismatch;
- Result PDF available while 2D is missing (current Race2 case).

### Track B acceptance

- No global scan side effect in live mode.
- No unscoped CLI apply path.
- No silent overwrite or ambiguous run identity.
- Every state transition is attributable to source hash, event manifest and receipt.
- Production DB is byte/content unchanged by the Track B test suite.
- Existing Workbench tabs, provisional/final distinction and Report v2 behavior pass regression tests.
- Deliver `05_SCRIPTS/reports/race_weekend_event_control_plane_apply_20260713.md` and `05_SCRIPTS/reports/round9_readiness_acceptance_20260713.md`.

## Still forbidden / separate authorization

- Supabase sync or cleanup, DB Master refresh/export, origin commit/push, metric/phase definition changes, and destructive historical queue cleanup.
- If the current code cannot safely perform a ROUND8-only targeted insert, implement and dry-run the minimal generalized tool first, document it, and stop before an unsafe write.
