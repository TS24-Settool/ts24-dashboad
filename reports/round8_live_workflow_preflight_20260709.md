# Round8 Live Workflow Preflight

**Date:** 2026-07-09 (Round8 starts 2026-07-10)
**Scope:** READ-ONLY operational preflight. No canonical write, no apply, no queue update, no Workbench UI change (the guard UI change was a separate P0 task §68), no DB Master, no Supabase, no commit/push.
**Instruction:** `reports/round8_live_workflow_preflight_code_instruction_20260709.md`

## Answers to the 7 questions

**1. Is the Round8 live provisional workflow implemented?** — **Yes.** Scan → Import(staging) → provisional overlay → Report v2 provisional are all built and previously verified (CLAUDE.md §51/§53/§55/§57/§60/§62), and as of today the import path is round-guarded (§68).

**2. Fully automatic or button-driven?** — **Button-driven, intentionally.** Saving a 2D file does **not** import it. There is **no folder watcher / auto-apply**. The operator must run `Session Scan`, then `Session Import (staging)`, then confirm Apply. This is deliberate for iCloud/partial-copy safety (§22/§24a).

**3. Exact steps after each Round8 session** — see the field checklist below (§Round8 session checklist).

**4. What can go wrong from historical `import_queue` pending?** — Today `import_queue` has **pending=364**, all **historical** (breakdown: TEST5=50, ROUND2=45, unresolved=41, ROUND1=38, ROUND5=35, ROUND6=29, ROUND4=28, TEST1=25, ROUND3=24, TEST2=15, … — **zero ROUND8**). An *unfiltered* import (old behavior) would have surfaced/applied those 364 as provisional candidates = mass mis-apply of already-final events.

**5. How is accidental import of old pending prevented?** — **Now enforced by code (§68), not human attention:**
- `ts24_workbench.py` `ImportQualityTab.REQUIRED_ROUND = "ROUND8"`. The `Session Import (staging)` button requires an event key containing `ROUND8` (rejects empty / non-ROUND8) and passes `--event <ev> --required-round ROUND8` to **both** dry-run and apply.
- `session_extract_staging.py`: `--apply` requires `--event` (else exit 4); `--required-round ROUND8` rejects any non-ROUND8 event/candidate before any write (two layers: pre-pipeline + pre-backup).
- Verified: guard-failure paths exit 4 with **business+provisional counts unchanged** (§68b). So the 364 historical pending can no longer reach provisional via the button.

**6. Exact NO-GO condition for pressing Apply** — Do **not** press Apply unless the dry-run summary references **only the current Round8 event/session/rider** (event `20260710-ROUND8-...`). If the dry-run shows any non-Round8 base/event, or an unexpected lap count, **Cancel** (default). With §68, a non-ROUND8 event is already rejected before dry-run; the human NO-GO check remains a second line of defense on the *candidate list* shown in the dialog.

**7. What to verify after Apply** — (a) dialog shows `provisional +N runs/laps`; (b) Workbench `🦾 Suspension/Posture → 🔧 3フェーズ Run比較`, filter to MISANO?/BALATON?/the Round8 circuit → runs appear as `⏳ ... (prov)` only; (c) `Create Report v2` → provisional confirmation dialog appears → generated filename/cover carries `PROVISIONAL`; (d) business table counts unchanged (the apply asserts this in-transaction, exit 3 + rollback on violation).

## Confirmed implemented capabilities (code-verified)

| Capability | Evidence |
|---|---|
| `Session Scan` button | `ts24_workbench.py` `_run_scan` (L6821), `_btn_scan` |
| `Session Import (staging)` button | `_run_import` (L6927), `_btn_import` — now round-guarded (§68) |
| `session_extract_staging.py --event/--session/--apply` | argparse present; **+ new `--required-round`** (§68) |
| provisional overlay (final + `lap_suspension_provisional`) | `_load_data` UNION on `sqlite_master` check (L3955-3971), fallback to legacy |
| provisional runs visibly marked | `_run_label` → `⏳ {label} (prov)` for `PROV_` run_id (L3573) |
| Report v2 provisional confirm + `_PROVISIONAL_` | `_on_create_report` PROV_ detection + confirm dialog (L3461-3468); `suspension_report._detect_provisional` / cover ribbon / filename token (§60) |
| Tier1 label/filter still apply to provisional | Tier1 changes live in `suspension_report.py` (§67) and are format-agnostic — they apply to provisional reports too (deep-stroke/settled labels, small multiples, slow-lap filter+page-2 disclosure, Öhlins/peak notes) |

## Operational limitation (state clearly)
- Saving a file alone does **not** import it. No folder-watcher auto-apply exists.
- The operator must run **Scan → Import → confirm Apply**. Intentional for iCloud / copy-in-progress safety.

## Round8 session field checklist
1. Ensure the 2D copy is **complete** — no `.icloud` / `~$` / `.partial` / `._` files in the event folder.
2. Event folder follows `YYYYMMDD-ROUND8-<RIDER>` (e.g. `20260710-ROUND8-JA52`). *(This folder already exists.)*
3. Workbench `📥 Import / Quality` → **`Session Scan`** (registers the new outings into `import_queue`).
4. **`Session Import (staging)`** → enter/confirm the Round8 event when prompted (pre-filled with the detected ROUND8 event).
5. In the **dry-run** dialog, confirm event / session / rider / lap counts are the **new Round8 session only**.
6. Press **Apply only** when candidates are the new Round8 session (default is Cancel).
7. Confirm Workbench shows `⏳ ... (prov)` for the new runs (and final runs unchanged).
8. `Create Report v2` → accept the **provisional** confirmation.
9. Confirm the report filename/cover shows `PROVISIONAL`.

## Recommended first-session path (belt-and-suspenders)
The §68 Workbench guard is sufficient for safe button use. For maximum control on the **very first** Round8 session, the Code operator may instead run the CLI explicitly:
```text
python3 session_extract_staging.py --event 20260710-ROUND8-JA52 --session <FP|QP|...> --required-round ROUND8            # dry-run
python3 session_extract_staging.py --event 20260710-ROUND8-JA52 --session <SESSION> --required-round ROUND8 --apply      # after visual confirm
```
This scopes to a single session and shows the full candidate list in the terminal before Apply.

## Notes
- No UI change was made in this preflight (the round guard was implemented under the separate P0 task §68).
- Downstream sync (DB Master / Supabase / push) is a separate read-only readiness task (`post_round7_downstream_sync_readiness_20260709.md`, pending).
- Successful **real-data** provisional apply can only be validated after the first Round8 2D file arrives and `Session Scan` registers ROUND8 candidates (currently 0 for the ROUND8 folder).
