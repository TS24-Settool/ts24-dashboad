# Round8 Donington Circuit Normalization — Apply Report

Date: 2026-07-10
Author: Claude Code
GO: **`Round8 Donington normalization GO`（Tatsuki 明示・本セッション受領）**
Readiness: `reports/round8_donington_circuit_normalization_readiness_20260710.md`（CLAUDE.md §70）
Scope: `circuit_canon` alias 追加（追加のみ）+ Round8 provisional 再生成。**canonical 業務テーブル書込なし・Round8 finalization は別 GO 据え置き・commit/push なし。**
Result: **完了・全検証 PASS。provisional Round8 = `DONINGTONPARK` → `DONINGTON` に再正規化。業務テーブル不変。**

---

## 1. コード修正（追加のみ・7ファイル・既存挙動は非Donington で不変）

circuit 正規化は共有関数でなく各所にコピー（§70a の棚卸し）。全て `BALATONPARK→BALATON` を持つが `DONINGTONPARK→DONINGTON` が欠落していた。**追加のみ**で 7ファイルにエントリを足した:

| ファイル | 種別 | 追加エントリ |
|---|---|---|
| `build_master_db.py:74` | `circuit_canon`（strip 非英数） | `"DONINGTONPARK":"DONINGTON"` |
| `cutover_db.py:39` | `circuit_canon` | `"DONINGTONPARK": "DONINGTON"` |
| `reconcile_2d_vs_original.py:33` | `circuit_canon` | `"DONINGTONPARK":"DONINGTON"` |
| `corner_phase_analysis.py:95` | `_CIRC_NORM`（空白保持） | `"DONINGTON PARK":"DONINGTON"` + `"DONINGTONPARK":"DONINGTON"` |
| `lap_overlay_extractor.py:93` | `_CIRC_NORM` | 同上 |
| `lap_suspension_stats.py:265` | `_CIRC_NORM` | 同上 |
| `parse_2d_channels.py:955` | `_CIRC_NORM` | 同上 |

- `build_master_db.py` が最重要（**provisional 経路 `session_extract_staging` と finalization 経路の両方が `bmd.circuit_canon` を共有**＝一点で両方 `DONINGTON` 化・§70b）。`cutover_db.py` は full-rebuild cutover 経路。残り5は一貫性（`_CIRC_NORM` 系は HED 由来で従前も `DONINGTON` を返すが防御的追加）。
- パッチは各ファイルにつき「対象文字列がちょうど1回・未パッチ」を assert したうえで置換（誤爆防止）。

### 検証（コード）
- `py_compile` 8ファイル（上記7 + `session_extract_staging.py`）PASS。
- 回帰 assert: `circuit_canon("DONINGTON PARK")="DONINGTON"` / `"Donington Park"="DONINGTON"` / `"DONINGTONPARK"="DONINGTON"` / `"Donington"="DONINGTON"`（不変）／ `"BALATON PARK"="BALATON"`・`"Phillip Island"="PHILLIPISLAND"`・`"Motorland Aragon"="ARAGON"`・MISANO/ASSEN 全て**不変**。`TRACK_M.get("DONINGTON")=4023`。

## 2. Round8 provisional 再生成（§70 §5.2 の regenerate 戦略）

run_id/lap_id は circuit を内包する識別子のため、in-place UPDATE ではなく **DELETE → 再 import** で再生成。

1. **pre-DELETE backup**: `02_DATABASE/_backup_donington_norm_20260710_145654/`（`ts24_unified.db` + `-wal` + `-shm`）。
2. **DELETE**（Round8 provisional のみ・`provisional_event_key='20260710-ROUND8-JA52'`）: runs/laps/lap_suspension_provisional = **2/21/21 → 0/0/0**。同一接続内で業務テーブル不変を assert してから commit。
3. **再 import**: `python3 session_extract_staging.py --apply --event 20260710-ROUND8-JA52 --required-round ROUND8 --include-awaiting`
   - `--event` filter で Round8 のみ候補化（他 awaiting_gate 混入なし・`load_queue_candidates` L118）。`--include-awaiting` で既 awaiting_gate の FP 2 outing を再候補化。DELETE 済のため manifest hash が runs_provisional に無く「新規」扱い → INSERT。
   - 結果: `circuit=DONINGTON (report=DONINGTON / .line=-)`・**FP-JA52-01 PASS**（`PROV_20260710_ROUND8_DONINGTON_FP_JA52_R1`・15 laps・best 90.24）/ **FP-JA52-02 WARNING**（`..._R2`・6 laps・best 89.96）。auto-backup `_backup_session_staging_20260710_145654/`。
   - **業務6テーブル before==after assert 合格**（286/1279/1279/866/7613・pdf_lap_times_v2_staging 7710）。ログ `reports/session_staging_apply_20260710_145654.md`。

## 3. 検証ゲート（全 PASS）

### 3a. provisional
- business: **286/1279/1279/866/7613 不変**。
- provisional: **2/21/21**。circuit = **`DONINGTON`（2/2）**。
- run_id = `PROV_20260710_ROUND8_DONINGTON_FP_JA52_R1/R2`。
- **`DONINGTONPARK` 残骸 = 0**（runs/laps/lap_suspension_provisional + 業務 runs/laps/lap_suspension すべて 0・lap_id にも無し）。

### 3b. scratch finalization gate（`build_master_db.py --all --round ROUND8 --out /tmp/...`・canonical 無書込）
- Round8 runs circuit = **`DONINGTON`（2/2）**・scratch `DONINGTONPARK` runs = **0**。
- Round8 runs=2 / laps=21（provisional と一致）。
- **受入ゲート |2D session最速 − PDF best| > 1.5s = 0件 ✅合格**。
- → **finalization も `DONINGTON` を生成**することを実証（DONINGTONPARK 二重サーキット化は解消）。scratch は削除。

### 3c. Workbench offscreen smoke
- 7タブ構築 OK。overlay 総 **1300 行**（final 1279 + provisional 21）。overlay の Donington 表記は **`DONINGTON` のみ**（`DONINGTONPARK` 0 行）。provisional circuit = `["DONINGTON"]`。既存無回帰。**GUI 最終目視は Tatsuki ローカル**。

## 4. is_outlap ④ ガードについて（補足）
- 再 import ログの `circuit P10 ref = None（本番同様 ④ガード skip）` は正常。`circuit_p10_ref` は canonical `laps JOIN runs WHERE circuit='DONINGTON'` から P10 を作るが、**canonical に DONINGTON の 2D laps はまだ無い**（既存 DONINGTON は race_results=COMPANY と 0-lap placeholder のみ）ため None＝MISANO 初回（§64/§65）と同挙動。
- 修正の本質的効果は **finalization 時**: `TRACK_M["DONINGTON"]=4023` が解決し、is_outlap ④ 単一ラップ上限ガード・track-length フロアが有効化される（修正前は `DONINGTONPARK`→None で無効化されていた）。scratch build（§3b）で受入ゲート 0件を確認済み。

## 5. rollback / スコープ外

- **rollback**:
  - コード: `git checkout -- build_master_db.py cutover_db.py reconcile_2d_vs_original.py corner_phase_analysis.py lap_overlay_extractor.py lap_suspension_stats.py parse_2d_channels.py`（追加行の revert）。
  - provisional: pre-DELETE backup `02_DATABASE/_backup_donington_norm_20260710_145654/` から復元、または再度 DELETE → （旧コードで）再 import。
  - 業務テーブルは本 apply でも無変更。
- **スコープ外（禁止遵守・未実施）**: Round8 finalization（別 GO）/ canonical 業務テーブル書込 / DB Master refresh / Supabase sync / **commit・push**（7ファイル + CLAUDE.md は working tree のみ）/ historical import_queue cleanup / Round8-only guard 変更。
- **次（別 GO）**: Round8 finalization は後続 session（QP/RACE 等）到着後に `build_master_db --round ROUND8` targeted-insert（§65 と同型）で実施。本正規化が前提条件として満たされた。
- 変更: 上記7スクリプト + `CLAUDE.md §71`。新規: 本レポート。DB: provisional のみ再生成（業務不変）。
