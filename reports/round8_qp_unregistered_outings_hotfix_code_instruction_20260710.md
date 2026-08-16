# Round8 QP Unregistered Outings Hotfix: Code Instruction

Date: 2026-07-10
Priority: P0 field recovery during Round8 QP
Scope: Workbench Import/Quality zero-candidate diagnosis and safe recovery path
Mode: implement after reading this instruction

## User problem

Tatsuki saved Round8 QP session data, but Workbench still cannot reflect it into provisional data.

Workbench popup at 2026-07-10 19:09:

```text
DATA 2D/20260710-ROUND8-JA52 は存在し registry=3 / queue=3(pending=1) ですが、
session_extract_staging が候補0と判定しました。
dry-runログと「検出チェック」タブを確認してください。
```

Dry-run log:

```text
05_SCRIPTS/reports/session_import_dryrun_20260710_190918.log
[STAGE] 候補 0 件（pending 2d_extract がフィルタに一致しない）
```

## Current evidence

Filesystem has five Round8 JA52 outing folders:

```text
DATA 2D/20260710-ROUND8-JA52/FP-JA52-01.MES
DATA 2D/20260710-ROUND8-JA52/FP-JA52-02.MES
DATA 2D/20260710-ROUND8-JA52/QP-JA52-01.MES
DATA 2D/20260710-ROUND8-JA52/QP-JA52-02.MES
DATA 2D/20260710-ROUND8-JA52/QP-JA52-03.MES
```

But the canonical DB management tables currently contain only FP 2D rows and the report row for this event:

```text
import_queue:
398 awaiting_gate 2d_extract ROUND8 JA52 FP-JA52-01
399 awaiting_gate 2d_extract ROUND8 JA52 FP-JA52-02
400 pending       report_import ROUND8 JA52 20260710-ROUND8-JA52.xlsx

source_file_registry:
2d_outing ROUND8 JA52 FP-JA52-01 queued
2d_outing ROUND8 JA52 FP-JA52-02 queued
report    ROUND8 JA52 20260710-ROUND8-JA52.xlsx queued
```

There are no QP rows in `source_file_registry` or `import_queue`.

`build_master_db.discover_outings()` and `extraction_scan.py --dry-run --min-age 0` can see the new QP folders. Therefore the data is on disk and detectable, but it has not been registered into the DB management tables that `session_extract_staging.py` reads.

## Root cause

This is not a telemetry parse failure and not a Round8 guard failure.

`session_extract_staging.py` reads `import_queue` candidates, not the filesystem directly. QP folders that exist on disk but are absent from `source_file_registry` / `import_queue` will always produce candidate count 0.

The previous no-candidates hotfix handles the case where the whole event is unscanned. This new case is different:

- the event folder exists;
- the event already has some registry/queue rows from FP and report;
- newly added QP outing folders are missing from registry/queue;
- the current diagnostic sees `registry=3 / queue=3(pending=1)` and falls through to an unhelpful generic message.

The diagnostic must move from event-level counts to outing-level reconciliation.

## Race weekend workflow requirement

This is a workflow-critical and mandatory requirement from Tatsuki.

To make Workbench provisional display reliable during a race weekend, an offline raw-2D-first extraction path inside Workbench is not optional. It is a required system capability. If provisional display depends on completed Report linkage, DB Master, Supabase, or final canonical data linkage, the race-weekend workflow will fail whenever a new session folder is saved before those supporting data sources are complete.

During a race weekend, reflecting data into Workbench as provisional data must not depend on completed Report linkage or completed canonical `ts24_unified.db` original-data linkage.

Correct live workflow:

1. After each session, the engineer saves the 2D raw session folder under `DATA 2D/<event>`.
2. Workbench must be able to scan that raw folder and extract only the data required for provisional analysis.
3. The extracted provisional data must be visible in Workbench and usable for provisional Report generation during the race weekend.
4. Report/company workbook linkage and canonical DB completeness are not prerequisites for provisional display.
5. Only after the race weekend, when all sessions and supporting data are complete, provisional data may be promoted into canonical business tables through a separate explicit finalization workflow.

Therefore Code must not solve this by making QP provisional import depend on `report_import`, existing race result rows, DB Master, Supabase, or any final canonical tables.

The expected architecture is:

- `Offline Raw 2D Direct Provisional Extract` is the fallback/primary live path for race weekend operation.
- Queue/registry can remain as management and audit layers, but they must not be the only way to detect and recover a newly saved session.
- When queue/registry is stale, Workbench must be able to reconcile against raw `DATA 2D` folders and guide the user to register/stage the raw data without requiring online services or completed Report linkage.
- Canonical promotion remains a separate post-race workflow.

For live Round8:

- `report_import` rows are useful context but must not block 2D provisional extraction.
- Missing or pending report rows must not prevent raw 2D QP extraction.
- Existing FP rows in registry/queue must not hide newly saved QP outings.
- If raw 2D outing folders exist and pass file-stability checks, Workbench must provide a path to register and stage them as provisional candidates.
- Finalization from provisional to canonical must remain a separate, post-race, explicit GO operation.

## Required implementation

Update Workbench `ImportQualityTab` so zero-candidate diagnosis compares expected filesystem outings against registry/queue 2D outings for the selected event.

### 1. Add outing-level reconciliation

For `DATA 2D/<event>`:

1. Discover expected outing folders on disk using the same logic or compatible helper as the scanner uses.
2. Build expected outing keys such as:
   - `FP-JA52-01`
   - `FP-JA52-02`
   - `QP-JA52-01`
   - `QP-JA52-02`
   - `QP-JA52-03`
3. Query `source_file_registry` for `file_type='2d_outing'` rows under the event folder.
4. Query `import_queue` joined to registry for `target_kind='2d_extract'` rows under the event folder.
5. Compare by outing key, not only by event-level count.

The diagnostic result should include:

```text
expected_2d_on_disk
registered_2d
queued_2d_total
queued_2d_pending
queued_2d_awaiting_gate
missing_from_registry
missing_from_queue
non_2d_pending_rows
```

For the current case, it must explicitly identify:

```text
missing_from_registry = QP-JA52-01, QP-JA52-02, QP-JA52-03
missing_from_queue    = QP-JA52-01, QP-JA52-02, QP-JA52-03
```

### 2. Improve the popup and recovery action

When `session_extract_staging.py` returns candidate count 0:

- If the event folder exists and missing outings are found, show:

```text
QP-JA52-01 / QP-JA52-02 / QP-JA52-03 はフォルダ上に存在しますが、
registry/queue に未登録です。Session Scan を実行して管理テーブルへ登録してください。
```

- Offer a safe `Session Scan` action using the existing `_run_scan()` path.
- After scan completes, refresh the Import/Quality tab and instruct the user to run `Session Import` again.
- Do not auto-apply provisional data.
- Keep the default destructive/commit actions untouched.
- Make clear that Report linkage is not required for provisional 2D extraction.

### 3. Strengthen the Detect Check tab

The `検出チェック` tab should show an event-level 2D reconciliation row for the selected Round8 event:

```text
event=20260710-ROUND8-JA52
disk_2d=5
registry_2d=2
queue_2d=2
pending_2d=0
awaiting_gate_2d=2
missing=QP-JA52-01, QP-JA52-02, QP-JA52-03
next_action=Session Scan
```

This must be visible even when report rows exist, because report `pending` rows are not usable by session extraction.

### 4. Immediate safe field recovery

If Code is operating the local machine and Tatsuki confirms scan execution, run only the existing scan path that updates management tables. Do not apply provisional data automatically.

After scan, verify:

- QP rows appear in `source_file_registry` as `file_type='2d_outing'`.
- QP rows appear in `import_queue` as `target_kind='2d_extract'`.
- `session_extract_staging.py --event 20260710-ROUND8-JA52 --session QP --required-round ROUND8` dry-run sees only Round8 QP candidates.
- Apply remains a separate human confirmation step.

## Validation checklist

1. `python3 -m py_compile ts24_workbench.py extraction_scan.py session_extract_staging.py`
2. Reproduce current diagnosis before scan:
   - disk expected 5 outings;
   - registered/queued 2D = FP 2 only;
   - missing = QP 3.
3. Confirm zero-candidate popup names the missing QP outing folders and offers Session Scan.
4. Confirm `検出チェック` tab distinguishes report pending rows from 2D extraction candidates.
5. Confirm Round8 guard is unchanged:
   - non-Round8 event rejected;
   - empty event rejected;
   - no unfiltered apply.
6. Confirm provisional QP dry-run can be reached from raw 2D registration without requiring `report_import` completion or canonical DB finalization.
7. Confirm no business/canonical/provisional rows change during diagnosis.
8. If scan is run, confirm only management tables change before any explicit apply.

## Forbidden

- Do not weaken `--event` / `--required-round ROUND8`.
- Do not run unfiltered `session_extract_staging.py`.
- Do not auto-apply provisional rows.
- Do not finalize Round8.
- Do not write canonical business tables.
- Do not make provisional import depend on Report completion.
- Do not make provisional import depend on DB Master or canonical finalization.
- Do not run DB Master refresh.
- Do not run Supabase sync.
- Do not cleanup historical queue.
- Do not commit or push.
- Do not add a folder watcher that auto-applies data.

## Deliverable

Create:

```text
05_SCRIPTS/reports/round8_qp_unregistered_outings_hotfix_20260710.md
```

The report must include:

- root cause;
- before/after counts;
- current QP missing outing proof;
- confirmation that race-weekend provisional import is raw-2D-first and independent of Report/canonical completion;
- code changes;
- validation commands;
- explicit statement that Round8 guard and canonical DB safety remain unchanged.
