# Round8-only Provisional Guard — Apply

**Date:** 2026-07-09
**Priority:** P0 (before Round8 first session)
**GO:** Tatsuki requirement「必ずRound8のデータだけをPrevisionalで表示、Reportを作成できる様にして下さい」+ INBOX P0 task (no separate GO gate; the instruction is the authorization). Forbidden list honored — no canonical write, no historical-pending apply, no queue cleanup, no DB Master, no Supabase, **no commit/push**, no folder watcher.
**Instruction:** `reports/round8_only_provisional_guard_code_instruction_20260709.md`
**Design:** cleaner `--required-round` flag (instruction-endorsed alternative), enforced with **two guard layers** (fail-closed) + a Workbench UI guard.
**Changed:** `session_extract_staging.py`, `ts24_workbench.py`. No DB/Excel/Supabase change.

## 1. Exact code changes

### `session_extract_staging.py`
- New `--required-round <ROUND>` CLI arg.
- New `enforce_apply_guard(args)` (Layer 1, fail-fast, called in `main()` **before** `run_pipeline`):
  - **A)** `--apply` without `--event` → `sys.exit(4)` (blocks the previously-unfiltered apply that could touch historical pending).
  - **B)** `--required-round RR` set and `--event`'s round (via `EVENT_RE`) ≠ RR → `sys.exit(4)`.
- New candidate-level guard at the **top of `do_apply`** (Layer 2, before backup/DDL/INSERT):
  - `--event` missing → return 4.
  - any candidate/skip whose `round` ≠ `--required-round` → return 4 (defense-in-depth if `--event` filtering ever regresses).
- Exit code `4` added to the module docstring = "Round8 guard 違反（書込前に中止）".

### `ts24_workbench.py` — `ImportQualityTab`
- Added `QInputDialog` import.
- New class constant `REQUIRED_ROUND = "ROUND8"` (bump to `"ROUND9"` next round).
- New `_guess_event_key(req)` → best-effort default event from `DATA 2D/` (returns e.g. `20260710-ROUND8-JA52` if present, else "").
- `_run_import` now, **before** any subprocess:
  - prompts for the event key via `QInputDialog.getText` (pre-filled with the guessed ROUND8 event);
  - rejects **cancel** (return, DB unchanged), **empty** event (warning, no run), and any event **not containing `ROUND8`** (warning, no run);
  - passes `--event <ev> --required-round ROUND8` to **both** the dry-run and the apply subprocess;
  - confirmation dialog shows the target event and states "Apply はこの event のみ・ROUND8 限定".

## 2. Guard behavior (dry-run / apply)

| Invocation | Result |
|---|---|
| `--apply` (no `--event`) | **exit 4**, no write (Layer 1 A) |
| `--apply --event <ROUND7…> --required-round ROUND8` | **exit 4**, no write (Layer 1 B) |
| `--event <ROUND7…> --required-round ROUND8` (dry-run) | **exit 4**, no write (Layer 1 B, event-level) |
| `--event <ROUND8…> --required-round ROUND8` (dry-run) | runs read-only; exit 1 if no candidates yet |
| `--apply --event <ROUND8…> --required-round ROUND8` | applies **only** that ROUND8 event's PASS candidates; exit 1 if none |
| bare dry-run (no args) | still allowed read-only (dry-run never writes); `--apply` is the only path the guard blocks |

## 3. Tests run (2026-07-09)

`python3 -m py_compile session_extract_staging.py ts24_workbench.py` → **PASS**.

CLI (exit codes captured cleanly):
- `--apply` (no event) → **exit 4** ✅
- `--apply --event 20260612-ROUND7-JA52 --required-round ROUND8` → **exit 4** ✅
- `--event 20260612-ROUND7-JA52 --required-round ROUND8` (dry-run) → **exit 4** ✅
- `--event 20260710-ROUND8-JA52 --required-round ROUND8` (dry-run) → **exit 1** (no candidates yet) ✅
- `--apply --event 20260710-ROUND8-JA52 --required-round ROUND8` → **exit 1**, no write ✅

Workbench offscreen (mocked `QInputDialog`/`QMessageBox`/`subprocess.run`, `ImportQualityTab._run_import`):
- valid `20260710-ROUND8-JA52` → **1** subprocess call carrying `--event 20260710-ROUND8-JA52 --required-round ROUND8` ✅
- empty event → **0** calls, warning shown ✅
- non-ROUND8 `20260612-ROUND7-JA52` → **0** calls, warning shown ✅
- dialog cancel → **0** calls ✅
- `REQUIRED_ROUND == "ROUND8"`; `_guess_event_key("ROUND8")` → `20260710-ROUND8-JA52` (folder exists).

## 4. No-write proof (rejected non-Round8 / unfiltered apply)

Business + provisional counts **before == after** across all guard-failure runs:

| table | before | after |
|---|---:|---:|
| runs | 286 | 286 |
| laps | 1279 | 1279 |
| lap_suspension | 1279 | 1279 |
| race_results | 866 | 866 |
| runs_provisional | 0 | 0 |
| laps_provisional | 0 | 0 |
| lap_suspension_provisional | 0 | 0 |

Layer 1 exits before `run_pipeline` (which is read-only anyway); Layer 2 returns before the backup/DDL/INSERT. No backup dir is created on a guard-blocked apply.

## 5. Round8-only successful dry-run path

`session_extract_staging.py --event 20260710-ROUND8-JA52 --required-round ROUND8` passes both guard layers and runs the normal read-only pipeline. Today it returns exit 1 (no queued 2d_extract candidates for that event yet — the folder exists but Session Scan has not registered outings). **Successful apply validation must be repeated after the first real Round8 session file arrives and `Session Scan` registers ROUND8 candidates** (per instruction §Validation note).

Live path (Round8 weekend): Workbench `Session Scan` → `Session Import (staging)` → enter/confirm the `20260710-ROUND8-JA52` event → dry-run (only ROUND8 candidates) → Apply confirm → provisional overlay `⏳ …(prov)` → Report v2 (cover/filename `PROVISIONAL`). Report v2 metric definitions unchanged.

## 6. Rollback

- `git checkout -- session_extract_staging.py ts24_workbench.py` (both are the only changes; no DB/Excel/Supabase to undo).
- Or remove: the `--required-round` arg + `enforce_apply_guard` + `do_apply` guard block in the script; the `REQUIRED_ROUND`/`_guess_event_key`/event-prompt + `guard_args` in the Workbench; revert the two subprocess arg lists and the confirmation dialog text; drop the `QInputDialog` import.

## Scope-out / forbidden (all honored)
No canonical business-table write, no historical-pending apply, no Round8 finalisation, no import_queue cleanup, no DB Master refresh, no Supabase, no commit/push, no folder-watcher automation. **GUI final visual check is Tatsuki local** (Workbench `Session Import (staging)` → event prompt).
