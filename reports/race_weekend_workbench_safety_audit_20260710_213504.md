# Race Weekend Workbench Safety Audit — 20260710_213504

- event: `20260710-ROUND8-JA52`
- generated: 2026-07-10T21:35:04 / ImportQualityTab 🛡 Safety Audit（read-only・DB は SELECT のみ）
- 書込は本 .md 1ファイルのみ（canonical / provisional / 管理テーブル無変更）

## 1. raw disk outing（session 別）
- FP (2): FP-JA52-01, FP-JA52-02
- QP (3): QP-JA52-01, QP-JA52-02, QP-JA52-03
- total: 5 outing

## 2. registry / queue 状態（ROUND8・status 別）
| layer | kind | status | count |
|---|---|---|---:|
| registry | — | queued | 6 |
| queue | 2d_extract | awaiting_gate | 5 |
| queue | report_import | pending | 1 |

- queue_2d: pending=0 awaiting_gate=5 failed=0 skipped=0 / report pending=1（2D 候補外・not a blocker）

## 3. provisional 状態（session 別）
| session | runs | laps | quality_status |
|---|---:|---:|---|
| FP | 2 | 21 | PASS×1, WARNING×1 |
| QP | 3 | 18 | PASS×3 |

- total: 5 runs / 39 laps

## 4. canonical invariants
| table | count |
|---|---:|
| runs | 286 |
| laps | 1279 |
| lap_suspension | 1279 |
| race_results | 866 |
| pdf_lap_times | 7613 |
| pdf_lap_times_v2_staging | 7710 |

- ROUND8 rows: runs=0 / laps(run_id LIKE)=0 / lap_suspension=0 / race_results=0 → **PASS**（2D 系 3 テーブルは finalization 前は 0 であるべき）
- canonical runs の PROV_ 汚染 = 0 → **PASS**
- canonical DONINGTONPARK 汚染 = 0 → **PASS**

## 5. 最新の scan / import ログ（reports/ 各最新3件）
- session_scan: session_scan_20260706_135617.log, session_scan_20260710_134347.log, session_scan_20260710_194019.log
- session_import_dryrun: session_import_dryrun_20260710_191056.log, session_import_dryrun_20260710_194006.log, session_import_dryrun_20260710_194048.log
- session_import_apply: session_import_apply_20260710_134502.log, session_import_apply_20260710_194050.log

## 6. recommended next action
- safe / waiting for new raw 2D

## 7. PASS/FAIL summary
| check | result | detail |
|---|---|---|
| raw disk outing の registry/queue 登録 | PASS | — |
| canonical ROUND8 = 0（runs/laps/lap_suspension） | PASS | runs=0 laps=0 lap_suspension=0 |
| canonical PROV_ 汚染 = 0 | PASS | runs PROV_=0 |
| canonical DONINGTONPARK 汚染 = 0 | PASS | runs+lap_suspension DONINGTONPARK=0 |
| report prerequisite not required（2D provisional の前提でない） | PASS | report pending=1（not a blocker） |
