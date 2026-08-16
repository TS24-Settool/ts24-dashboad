# Workbench APEX / Damping Run Filter — Apply Report

Date: 2026-07-11
Priority: P1 — Workbench analysis usability
Approval: Tatsuki's 2026-07-11 request for run selection/search on both pages = approval for
this **read-only UI-only** change (Code instruction:
`reports/workbench_apex_damping_run_filter_code_instruction_20260711.md`).
Deliverable of: `00_INBOX/FOR_CLAUDE_CODE.md` 2026-07-11 未処理タスク「Workbench APEX / Damping Run Filter」.

## Summary

`🦾 Suspension/Posture` の `📊 APEX分析（基本）` と `⚙️ Damping / Phase` が、上部の Circuit
コンボだけで全 Run を混在表示していた。両ページ共通の **`🔎 Run Filter`** パネルを追加し、
Circuit → Rider → Session → Data stage → 検索可能な複数 Run 選択で、両ページの全グラフと
Damping 数値テーブルを **選択 run ID だけ**に絞れるようにした。

**変更 = `ts24_workbench.py` の `PostureAnalysisTab` のみ**（+367 / −1 行・8 ハンク・すべて当該
クラス内）。`extraction_scan.py` / `session_extract_staging.py` は無変更＝§68 ROUND8 fail-closed
intake guard は完全保持。**DB は一切開いていない**（in-memory `_df` の read-only フィルタのみ・
SQL 追加/schema 変更/書込ゼロ）。`🔧 3フェーズ Run比較`（`PhaseRunCompareWidget`）は独自
コントロールを保持し、本パネルの影響を受けない。

## 実装（`PostureAnalysisTab`）

1. **`🔎 Run Filter` 共通パネル**（新 `_build_run_filter_panel()`・内部サブタブの上に配置）:
   折りたたみトグル（▾/▸）+ `Rider` + `Session` + `Stage`(All/Final/Provisional) コンボ +
   `検索` テキスト + `全選択`/`全解除` + 状態ラベル + Run 複数選択 checkbox リスト
   （`QListWidget`・maxHeight 132px・コンパクト）。
2. **フィルタ階層**: 上部の既存 Circuit コンボ（global）→ Rider → Session → Data stage →
   検索可能 Run リスト。`_combo_circ.currentTextChanged` を `_update_all` から新
   `_rf_on_circuit` へ再配線（Circuit 変更で Rider/Session/Run を再構築してから再描画）。
3. **Run ラベル**（`_rf_run_label`）= `rider  session  Rn  (round)`、provisional は先頭に
   `⏳ … (prov)`（`PROV_` prefix / `data_stage=='provisional'` で判定）。`PhaseRunCompareWidget`
   の選択セマンティクスを踏襲（重複実装なし）。
4. **両ページへ反映**: `_filtered_df()` の末尾に `_apply_run_filter()` を追加（Rider → Session →
   Stage → 選択 run_id の順・**物理/lap-time validity の「後」**に適用）。`_update_all()` は
   APEX 4 パネル（`_draw_pitch_scatter`/`_draw_phase_space`/`_draw_radar`/`_draw_trend`）と
   Damping 3 プロット＋数値テーブル（`_draw_damping_phase`/`_fill_dp_table`）を **同一の
   `_filtered_df()`** で描くため、両ページが常に同じ選択 ID を反映する。
5. **空選択 = 明示的な空状態**: 選択 0 件 → `_filtered_df` が空 df → `_update_all` が全プロットと
   Damping 表をクリア（`_rf_clear_plots`）し、状態ラベルに「⚠ Run 未選択 — グラフ・表は空です
   （全Runへは戻しません）」を赤表示。**決して全 Run へサイレントに戻さない**（Required UX 5）。
6. **既定 = 現挙動を保持**: Circuit 選択後、スコープ内の有効 Run を**全選択**（＝従来の全 lap 表示）。
   再読込（`_load_data`）/フィルタ再構築でも選択を可能な限り保持（`prev` 集合）。Circuit 変更時は
   新スコープの Run を全選択。
7. **Data stage の区別を保持**: `data_stage` 列（§54/§55 provisional overlay 時）優先、無ければ
   `run_id` の `PROV_` prefix で final/provisional を判定。final と provisional は独立に絞れ、
   ラベルで常に区別（`⏳(prov)`）。
8. **3フェーズ Run比較の独立性**: 当該タブ表示中は共通 Run Filter を非表示
   （`_inner_tabs.currentChanged`→`_rf_on_tab_changed`・APEX(0)/Damping(1) で表示・比較(2) で非表示）。
   `PhaseRunCompareWidget` のコードとフィルタ状態は無改変。
9. **検索・全選択/全解除**: 検索は表示/非表示のみ切替（選択状態は保持）。全選択/全解除は検索絞込中は
   表示中の Run のみ対象（＝「検索一致を一括選択」）。折りたたみトグルで Run リストを隠してノートPCの
   画面を確保できる。

## 検証（すべて PASS）

- **`py_compile ts24_workbench.py`** PASS。
- **offscreen smoke**（DB は canonical のコピーに対して実行・実 DB は未オープン）:
  - MainWindow 7 タブ / PostureAnalysisTab 内部 3 タブ（`📊 APEX分析（基本）`/`⚙️ Damping / Phase`/`🔧 3フェーズ Run比較`）・例外なし。
  - Run Filter ウィジェット全て存在（panel/rider/session/stage/search/list/全選択/全解除/toggle）。
  - **既定 circuit=全サーキット** → run_list 175・全 175 選択・filtered 1200 laps・filtered run_id ⊆ 選択（leak 0）。
  - **Circuit=ASSEN** → run_list 17・全選択・filtered 102 laps・全 ASSEN・Rider `['全','DA77','JA52']`。
  - **Rider=DA77** → 62 laps / 9 runs（全 DA77）。**Session=FP** → 16 laps。
  - **空選択（全解除）** → 0 laps（全 Run へ戻らない）。**単一 Run** → その 1 run のみ 11 laps。**3 Run** → 3 run 16 laps。
  - **APEX+Damping 共有**: Damping 数値テーブル行数 16 == filtered 行数 16（両ページ同一選択 ID）。
  - **DONINGTON Provisional** → 6 prov run・ラベル `⏳ JA52  FP  R1  (ROUND8) (prov)` 等・全 `(prov)`。**Final stage** → 0 laps（ROUND8 未 finalization で正）。
  - **3フェーズ Run比較の独立** → Run Filter を全解除しても比較タブの選択 4 run は不変。
  - **タブ可視性** → 3フェーズタブで panel 非表示・APEX で表示。**refresh** で Run Filter 再構築。
- **canonical / provisional / registry / queue before==after**（`mode=ro`）:
  runs **286** / laps **1279** / lap_suspension **1279** / race_results **866** / pdf_lap_times **7613** /
  pdf_lap_times_v2_staging **7710** / runs_provisional **6** / laps_provisional **46** /
  lap_suspension_provisional **46** / source_file_registry **431** / import_queue **422**。
  **実 canonical DB は SHA-256 完全一致**（`e74bdbfe…f42cda` before==after）＝書込ゼロを実証。
- **GUI 目視（単一 Run / 複数 Run / ROUND8 provisional Run の切替でグラフ・表が変わること）は Tatsuki ローカル**（`python3 ts24_workbench.py` → 🦾 Suspension/Posture → 📊 APEX分析 / ⚙️ Damping・Phase）。

## rollback / スコープ外

- rollback: `ts24_workbench.py` の Run Filter 追加ブロックの **targeted revert**
  （`_build_run_filter_panel` / `_rf_*` / `_apply_run_filter` メソッド群と、`_setup_ui` の panel 追加・
  `_combo_circ` 再配線・`_inner_tabs.currentChanged` 接続、`_filtered_df` の `_apply_run_filter` 呼出、
  `_update_all` の空状態分岐、`_load_data` の `_rf_repopulate` 呼出）。
  ⚠ `git checkout -- ts24_workbench.py` は §48〜§76 の未コミット機能も戻るため使用しない。
  変更前スナップショット = セッション scratchpad の `ts24_workbench.py.pre_run_filter`（+367/−1 の基準）。
  DB/Excel/Supabase 無変更のため DB rollback 不要。
- スコープ外（禁止遵守・未実施）: `extraction_scan.py`/`session_extract_staging.py`/import queue/
  staging・finalization/Report 生成/metric・phase 抽出/DB schema/DB 書込（テスト含む）/DB Master/
  Supabase/commit・push。ROUND8 fail-closed intake controls（§68/§73）弱体化なし。
- 変更: `ts24_workbench.py`（`PostureAnalysisTab` のみ）。新規: 本レポート / `CLAUDE.md §77`。
