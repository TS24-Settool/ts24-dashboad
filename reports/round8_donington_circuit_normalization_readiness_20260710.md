# Round8 Donington Circuit Normalization — Readiness / Design (read-only)

Date: 2026-07-10
Author: Claude Code
Priority: P0（Round8 finalization より前に必須）
Scope: **read-only readiness/design のみ**。`circuit_canon()` 変更・provisional 書換・run_id/lap_id 変更・finalization は本タスクで一切未実施。
Instruction: `05_SCRIPTS/reports/round8_donington_circuit_normalization_code_instruction_20260710.md`
参照: CLAUDE.md §27d-2 / §32b / §64-§65 / §68 / §69・`FOR_CODEX.md`（2026-07-10）・[[2d-discovery-layouts-and-anomalies]]

---

## 0. 結論（先出し）

- **推奨修正 = 最小1行**: `build_master_db.circuit_canon()` の正規化辞書に **`"DONINGTONPARK": "DONINGTON"`** を追加（既存 `"BALATONPARK":"BALATON"` と同型）。これで **provisional 経路（`session_extract_staging.py`）と finalization 経路（`build_master_db.py`）が同一関数を共有するため一点修正で両方が `DONINGTON` になる**（下記 §3.1 で実証）。
- ただし **circuit 正規化は約7ファイルに重複定義**されており（§4）、Round8 に直接効くのは `build_master_db.py` だが、**`cutover_db.py`（full-rebuild cutover 経路）にも同エントリ追加が必要**。残りの `_CIRC_NORM` 系（overlay/stats/corner_phase/parse_2d）は HED 由来で既に `DONINGTON` を返すが、一貫性のため同時追加を推奨（すべて1行・追加のみ）。
- **apply 戦略 = provisional 再生成（regenerate）** を推奨（in-place UPDATE より安全）。provisional は **2 runs / 21 laps / 21 lap_suspension** と小さく、`session_extract_staging.py` は冪等・再実行可能（§53/§57）。fix 後に Round8 provisional を DELETE → 再 import すれば run_id/lap_id が自動的に `DONINGTON` になる。
- **Round8 finalization は本修正＋検証が完了するまで実施しない**（さもないと canonical に `DONINGTONPARK` が確定し二重サーキット化）。
- GO 文言 = **`Round8 Donington normalization GO`**。

---

## 1. 現在の Round8 provisional 状態（read-only 実測）

| 項目 | 実測値 |
|---|---|
| provisional_event_key | `20260710-ROUND8-JA52` |
| runs_provisional | **2** |
| laps_provisional | **21** |
| lap_suspension_provisional | **21** |
| circuit（provisional） | **`DONINGTONPARK`**（2/2 runs） |
| run_id 例 | `PROV_20260710_ROUND8_DONINGTONPARK_FP_JA52_R1` / `_R2` |
| lap_id 例 | `PROV_20260710_ROUND8_DONINGTONPARK_FP_JA52_R1_L10` … |
| session / rider / round | FP / JA52 / ROUND8 |
| best（perf_best_lap） | R1=90.24 / R2=89.96（`1:30.24` / `1:29.96`＝Donington 4023m と整合） |
| queue（Round8） | awaiting_gate 2（取込済 FP）/ pending 1（Report xlsx 未取込） |

**業務テーブルは不変**: runs **286** / laps **1279** / lap_suspension **1279** / race_results **866**（before==after・本タスクは read-only）。

## 2. canonical 側 Donington 状態（read-only 実測）

- `build_master_db.TRACK_M["DONINGTON"] == 4023`（`build_master_db.py:702`）。**`TRACK_M` に `DONINGTONPARK` キーは無い** → `TRACK_M.get("DONINGTONPARK")` = **None**。
- canonical 業務テーブル（runs/laps/lap_suspension）に **`DONINGTONPARK` を含む run_id = 0 件**（未汚染。現時点の `DONINGTONPARK` は provisional のみ）。
- canonical の Donington:
  - `runs`: `NA_DONINGTON_RACE1_JA52_R1` / `NA_DONINGTON_RACE2_JA52_R1`（round=''・0-lap placeholder・circuit=`DONINGTON`）。
  - `race_results`: **DONINGTON 168 行・全て `data_scope='COMPANY'`（＝BSB）**。
- **重要**: `runs` / `laps` / `lap_suspension`（2D テレメトリ側）には **`data_scope` 列が無い**。COMPANY/WorldSSP の区別は **`round` + `circuit`** で行う（テレメトリ側）。`data_scope` を持つのは `race_results` のみ。
  → よって「circuit は `DONINGTON` に統一し、BSB と WorldSSP Round8 は `round`（ROUND8 vs BSB ラウンド）で分離、race_results 側は `data_scope` で分離」が正しい整理。Round8 の race_results はまだ 0 件（未 finalize）で、自然キーに round を含む（§1c）ため既存 168 COMPANY 行との衝突リスクは低い（要 finalize 時確認）。

## 3. 根本原因（確定）

| 情報源 | 値 | 正規化後 |
|---|---|---|
| Report `01_REPORTS/JA52/20260710-ROUND8-JA52.xlsx` DAY1 CIRCUIT | **`"DONINGTON PARK"`** | `circuit_canon` → **`DONINGTONPARK`** |
| HED `DATA 2D/20260710-ROUND8-JA52/FP-JA52-01.MES/FP-JA52-01.HED` | `Circuit=Donington` / `Track Length=4023` / `Event=R08 Donington` / `WSS_2026\R08_Donington.26` | （HED 経路なら）`DONINGTON` |
| `.line` ファイル | **不在**（Round8 フォルダに `*.line` なし） | `circuit_from_2d` = "" |

- `build_master_db.event_circuit()`（L166-168）= `circuit_from_report() or circuit_from_2d()` → `circuit_canon()`。Round8 は Report が存在するため **Report の "DONINGTON PARK" が採用**され、`.line`/HED は使われない。
- `circuit_canon()`（L71-76）は `re.sub(r"[^A-Z0-9]","", upper)` で空白除去 → `"DONINGTON PARK"` → `"DONINGTONPARK"`。辞書に `BALATONPARK→BALATON` はあるが **`DONINGTONPARK→DONINGTON` が無い** → 素通り。
- 確認: `circuit_canon("DONINGTON PARK")="DONINGTONPARK"` / `circuit_canon("Donington")="DONINGTON"` / `circuit_canon("DONINGTON")="DONINGTON"`。

### 3.1 provisional 経路も同じ関数を使う（＝一点修正で両経路解決）

`session_extract_staging.py:385-388`:
```python
report  = bmd._find_report(rider, rnd, date)
circ_rep = bmd.circuit_canon(bmd.circuit_from_report(report)) if report else ""
circ_2d  = bmd.circuit_canon(bmd.circuit_from_2d(ev_dir))
circuit  = circ_rep or circ_2d      # 本番 event_circuit と同順（Report 優先・.line fallback）
```
run_id = `PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}`（§20a/§52）。
→ **provisional の `circuit`／`run_id`／`lap_id` は `bmd.circuit_canon` の戻り値に直結**。`build_master_db.circuit_canon` に1行足せば、provisional 再生成でも finalization（`build_master_db --round ROUND8`・§65）でも自動的に `DONINGTON` になる。

### 3.2 影響（放置した場合）

1. `TRACK_M.get("DONINGTONPARK")=None` → `session_extract_staging.circuit_p10_ref`（L129-136）が None → **is_outlap ④ 単一ラップ上限ガード（circuit P10×1.25）が silent skip**。FP/21lap では実害小だが RACE 投入で stray/outlap 誤判定の温床。finalization（build_master_db）でも同様に track-length 依存ロジックが degrade。
2. **finalization で circuit=`DONINGTONPARK` が canonical 確定** → 既存 `DONINGTON` と二重サーキット化（Workbench circuit フィルタ二重表示・race_results との circuit JOIN 不一致・PROV→final run_id マッピングの circuit ずれ）。
3. dashboard/Excel など circuit 集計が Donington を2つに分裂表示。

## 4. 修正対象ファイルの棚卸し（circuit 正規化の重複定義）

circuit 正規化は **単一の共有関数ではなく各所にコピー**されている（既存の技術的負債）。全て `BALATONPARK→BALATON` を持つが **`DONINGTONPARK→DONINGTON` は無い**:

| ファイル:行 | 形態 | Round8 への効き方 | 修正要否 |
|---|---|---|---|
| **`build_master_db.py:71`** | `circuit_canon()` | **provisional + finalization の両方が使用**（§3.1） | **必須（第一）** |
| **`cutover_db.py:34`** | `circuit_canon()` | full-rebuild cutover 経路（§65 は targeted-insert で不使用だが将来 cutover 時に効く） | **必須（第二）** |
| `reconcile_2d_vs_original.py:27` | `circuit_canon()` | Original 照合 | 推奨（一貫性） |
| `corner_phase_analysis.py:95` | `_CIRC_NORM` | corner_phase_data.json（deprecated §4.2）・HED 由来 | 推奨 |
| `lap_overlay_extractor.py:93,221` | `_CIRC_NORM` | lap_overlay JSON（deprecated）・**HED 由来 → 既に DONINGTON** | 推奨（実害小） |
| `lap_suspension_stats.py:265,267` | `_CIRC_NORM` | lap_suspension JSON（deprecated）・**HED 由来 → 既に DONINGTON** | 推奨（実害小） |
| `parse_2d_channels.py:955` | `_CIRC_NORM` | APEX 抽出（deprecated JSON 系） | 推奨 |

- 注: `lap_overlay_extractor`/`lap_suspension_stats`/`corner_phase_analysis` は **HED の `Circuit`（="Donington"）を読む**ため、これらは修正前でも `DONINGTON` を返す（"PARK" が付くのは Report 経由の build_master_db/cutover のみ）。ただし将来 Report 由来文字列が流れた場合の防御として同一エントリ追加を推奨。
- `dashboard.py` / `domain/lap_analysis.py` / `audit_db_dump.py` / `import_all_race_results.py` / `performance_correlation.py` は PHILLIPISLAND 等の別正規化で、Donington PARK 変換は無関係（今回対象外）。
- **将来課題（別タスク）**: これら7コピーを1つの共有モジュール（例 `circuit_norm.py`）へ集約し、alias 追加を一箇所で済ませる。今回はスコープ外。

## 5. GO 後の apply 戦略（設計・本タスクでは未実施）

### 5.1 コード変更（追加のみ・既存挙動は非Donington で不変）
1. `build_master_db.circuit_canon` の辞書に `"DONINGTONPARK": "DONINGTON"` を追加。
2. `cutover_db.circuit_canon` に同エントリ追加。
3. （一貫性）`reconcile_2d_vs_original.py` / `corner_phase_analysis.py` / `lap_overlay_extractor.py` / `lap_suspension_stats.py` / `parse_2d_channels.py` の alias 辞書にも同エントリ追加。
4. `py_compile` 全対象。`circuit_canon("DONINGTON PARK")=="DONINGTON"` を assert。他サーキットの戻り値が不変であることを確認（回帰なし）。

### 5.2 既存 Round8 provisional の扱い = **再生成（推奨）**
run_id/lap_id は circuit を内包する識別子のため、`DONINGTONPARK`→`DONINGTON` 変更は run_id/lap_id 変更を伴う。**in-place UPDATE（3テーブルの circuit + run_id + lap_id を文字列置換）は識別子列を書き換えるため非推奨**。代わりに:
1. backup（`_backup_*` へ provisional 3テーブル）。
2. Round8 provisional を DELETE（`WHERE provisional_event_key='20260710-ROUND8-JA52'`・§65d と同型）→ 2/21/21 → 0/0/0。
3. `python3 session_extract_staging.py --apply --event 20260710-ROUND8-JA52 --required-round ROUND8`（fix 後）→ 冪等再取込で **circuit=`DONINGTON`・run_id=`PROV_20260710_ROUND8_DONINGTON_FP_JA52_R{n}`** を生成。
4. queue の awaiting_gate/pending 状態は再取込で再遷移（§53/§57 と同挙動）。
- provenance（intake_ts/source_manifest_hash/source_file_path/provisional_event_key）は再取込で再付与。event_key は不変。
- **業務6テーブル before==after assert**（session_extract_staging の in-transaction assert が保証）。

### 5.3 検証ゲート（finalization 前に必須）
- provisional: circuit=`DONINGTON`（2/2）・run_id/lap_id に `DONINGTONPARK` **0件**・counts 2/21/21・業務テーブル不変。
- `bmd.TRACK_M.get("DONINGTON")==4023` が解決 → is_outlap ④ガード有効化。
- scratch build `python3 build_master_db.py --all --round ROUND8 --out /tmp/ts24_r8.db`（§65b と同型）→ 受入ゲート |2D−PDF|>1.5s = 0件・Round8 circuit=`DONINGTON`・`DONINGTONPARK` 0件。
- canonical 業務テーブルに `DONINGTONPARK` が入っていないこと（現状0を維持）。

### 5.4 rollback
- code: `git checkout -- build_master_db.py cutover_db.py …`（追加1行の revert）。
- provisional: backup 復元、または再度 DELETE→（旧コードで）再取込。
- 業務テーブルは本 apply でも無変更（provisional のみ）。

## 6. Round8 追加 session の運用推奨（fix 前）

- fix 前に QP/RACE 等が届いた場合、それらも **`DONINGTONPARK` で provisional 取込される**（同じ Report 由来 circuit）。
- 推奨: **先に normalization fix を適用**（現状 FP のみ＝再生成コスト最小の今が最良）。もし fix 前に追加取込した場合は、**全 Round8 provisional をまとめて1回 controlled re-normalization（DELETE→fix→再取込）** してから finalize する。
- **Round8 finalization は本 fix + §5.3 検証が完了するまで実施しない（厳守）。**

---

## 7. Deliverable まとめ

1. **推奨修正**: `build_master_db.circuit_canon` に `"DONINGTONPARK":"DONINGTON"` 追加（+ `cutover_db.py` 同エントリ・+ 一貫性で `_CIRC_NORM` 系5ファイル）。一点修正で provisional/finalization 両経路が `DONINGTON` に（§3.1）。
2. **GO 文言**: `Round8 Donington normalization GO`。
3. **apply 順**: code 追加 → py_compile/assert → provisional backup → Round8 provisional DELETE → 再 import（DONINGTON 生成）→ §5.3 検証ゲート → （別 GO で）Round8 finalization。
4. **NO-GO 条件**: 追加サーキットの `circuit_canon` 戻り値が TRACK_M キーと不一致 / provisional 再取込で circuit≠DONINGTON / 業務テーブル差分 / scratch build 受入ゲート不合格 / run_id に DONINGTONPARK 残存。
5. **rollback**: §5.4。
6. **fix 前の Round8 provisional 継続可否**: 技術的には継続取込可（DONINGTONPARK になる）が、**finalize は不可**。追加分は fix 後に一括 re-normalization。**FP のみの今、先に fix するのが最小コストで推奨**。

## 8. スコープ外（禁止遵守・本タスクで未実施）

- `circuit_canon()` 変更なし / provisional 書換なし / run_id・lap_id 変更なし / Round8 final化なし / canonical 業務テーブル書込なし / DB Master refresh なし / Supabase なし / commit・push なし / historical import_queue cleanup なし / Round8-only guard 変更なし。
- 新規: 本レポート。変更なし（read-only）。記録: CLAUDE.md §70 / Obsidian log・CURRENT_STATE・AI_HANDOFF・INBOX Result。
