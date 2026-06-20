# Reconcile — ORIGINAL ↔ DB (RUN_LOG)

_Generated 2026-06-05 · read-only diff, no files mutated._

> ## ✅ 判定結果（2026-06-05 Tatsuki 承認）
>
> 検出された **24 件の不一致はすべて補正対象外**。DB を正とする。
> - **タイヤ NEW/USED 表記差（18 件）** → DB が詳細。DB を残す。
> - **AIR_TEMP / TRACK_TEMP（6 件）** → 原本が空欄。DB の実測値を残す。
>
> 確定ルール: 「原本が勝つのは原本に明示的な値があるときのみ。原本の空欄・DB の付加情報は DB を残す。」
> （`05_SCRIPTS/CLAUDE.md` §1b に正式記載）
>
> → **Part A-4 の DB 補正は実施不要（補正件数 0）。原本・DB ともに無変更。**

## Inputs

| Source | Path | Rows |
|---|---|---|
| ORIGINAL (権威源) | `04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx` (sheet `DATA`) | 235 |
| DB | `02_DATABASE/TS24 DB Master.xlsx` (sheet `RUN_LOG`) | 235 |

Key = `(RIDER, CIRCUIT_norm, SESSION.strip().upper(), RUN)`. Circuit aliases normalised per Part A-2.

## Summary

| Bucket | Count |
|---|---|
| **Field mismatches** (same key, value differs) | **24** |
| In ORIGINAL only (DB lacks the row) | 0 |
| In DB only (out of original's coverage — informational, see note) | 0 |
| Duplicate keys inside ORIGINAL | 12 |
| Duplicate keys inside DB | 12 |

> **Important:** ORIGINAL is the authoritative source within its coverage window. Rows that
> exist in DB but not in ORIGINAL are NOT mismatches — they are simply outside the original's
> updated range (e.g. ROUND 3+ that were never back-filled into the original). Per Part A-4,
> those are explicitly out of scope for correction.

## Mismatches by field

| Field | Count |
|---|---|
| `TYRE_FRONT` | 9 |
| `TYRE_REAR` | 9 |
| `AIR_TEMP` | 3 |
| `TRACK_TEMP` | 3 |

## Detailed mismatches

Each row is a single field that differs. ORIGINAL = authoritative; DB = current Master.xlsx RUN_LOG.

| Rider | Circuit | Session | Run | Field | ORIGINAL | DB |
|---|---|---|---|---|---|---|
| JA52 | ARAGON | FP | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | FP | 1 | `TYRE_REAR` | SC1 | SC1 NEW |
| JA52 | ARAGON | FP | 2 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | FP | 2 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | QP | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | QP | 1 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | QP | 2 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | QP | 2 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | QP | 3 | `TYRE_FRONT` | SC1 | SC1 USED |
| JA52 | ARAGON | QP | 3 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | RACE1 | 1 | `AIR_TEMP` | — | 28 |
| JA52 | ARAGON | RACE1 | 1 | `TRACK_TEMP` | — | 45.6 |
| JA52 | ARAGON | RACE1 | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | RACE1 | 1 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | RACE2 | 1 | `AIR_TEMP` | — | 28.7 |
| JA52 | ARAGON | RACE2 | 1 | `TRACK_TEMP` | — | 48 |
| JA52 | ARAGON | RACE2 | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | RACE2 | 1 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | WUP1 | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | WUP1 | 1 | `TYRE_REAR` | SC0 | SC0 NEW |
| JA52 | ARAGON | WUP2 | 1 | `AIR_TEMP` | — | 21 |
| JA52 | ARAGON | WUP2 | 1 | `TRACK_TEMP` | — | 27 |
| JA52 | ARAGON | WUP2 | 1 | `TYRE_FRONT` | SC1 | SC1 NEW |
| JA52 | ARAGON | WUP2 | 1 | `TYRE_REAR` | SC0 | SC0 NEW |

## Keys present in ORIGINAL but missing from DB (0)

None.

## Keys present in DB but absent from ORIGINAL (0)

None.

## Duplicate keys inside ORIGINAL (12)

Same (RIDER, CIRCUIT, SESSION, RUN) tuple appeared twice. Investigate before any correction.

| Rider | Circuit | Session | Run |
|---|---|---|---|
| JA52 | PHILIP ISLAND | RACE1 | 1 |
| JA52 | PHILIP ISLAND | RACE2 | 1 |
| JA52 | PORTIMAO | RACE1 | 1 |
| JA52 | PORTIMAO | RACE2 | 1 |
| JA52 | ASSEN | RACE1 | 1 |
| JA52 | ASSEN | RACE2 | 1 |
| JA52 | BALATON | RACE1 | 1 |
| JA52 | BALATON | RACE2 | 1 |
| JA52 | MOST | RACE1 | 1 |
| JA52 | MOST | RACE2 | 1 |
| JA52 | ARAGON | RACE1 | 1 |
| JA52 | ARAGON | RACE2 | 1 |

## Duplicate keys inside DB (12)

| Rider | Circuit | Session | Run |
|---|---|---|---|
| JA52 | PHILIP ISLAND | RACE1 | 1 |
| JA52 | PHILIP ISLAND | RACE2 | 1 |
| JA52 | PORTIMAO | RACE1 | 1 |
| JA52 | PORTIMAO | RACE2 | 1 |
| JA52 | ASSEN | RACE1 | 1 |
| JA52 | ASSEN | RACE2 | 1 |
| JA52 | BALATON | RACE1 | 1 |
| JA52 | BALATON | RACE2 | 1 |
| JA52 | MOST | RACE1 | 1 |
| JA52 | MOST | RACE2 | 1 |
| JA52 | ARAGON | RACE1 | 1 |
| JA52 | ARAGON | RACE2 | 1 |

## Next step

1. **Tatsuki review** — confirm each mismatch row is genuinely a DB error (and not e.g. a typo
   in the original or a units discrepancy you'd like to keep).
2. After confirmation, Part A-4 will overwrite the listed DB cells with ORIGINAL values,
   then re-run `build_unified_db.py` to push the corrected snapshot into `ts24_unified.db`.
3. Rows in "DB only" are explicitly left untouched.
