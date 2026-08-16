# Workbench Create Suspension Report PowerPoint MVP — Readiness Report

- **日付:** 2026-07-02
- **担当:** Claude Code
- **タスク:** `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）— Workbench に `Create Report` を追加し、
  サスペンション関連データを PowerPoint `.pptx` で自動確認できる MVP を作る。
- **結論:** **必須依存（`python-pptx` / `matplotlib`）が両方とも未インストールのため、タスク規定に従い
  ネットワーク install をせず本 readiness report を作成して停止**。正本DB・コード・Excel・Obsidian（記録以外）は無変更。
- **HEAD:** `5651d97`（local・未push）/ 正本DB `02_DATABASE/ts24_unified.db`（`lap_suspension` 1202行/69列）。

---

## 1. 依存確認結果

`python3`（システム Python・venv 無し）で確認。

| 依存 | 要否 | 状態 | バージョン |
|---|---|---|---|
| `python-pptx` | **必須（PPTX 生成）** | ❌ 未インストール | — |
| `matplotlib` | **必須（グラフ画像化）** | ❌ 未インストール | — |
| `numpy` | 必須（数値処理） | ✅ あり | 2.0.2 |
| `pandas` | 必須（集計） | ✅ あり | 2.3.3 |
| `PyQt6` | 必須（Workbench 本体） | ✅ あり | 6.10.2 |
| `pyqtgraph` | 必須（既存グラフ） | ✅ あり | 0.13.7 |

- `requirements_workbench.txt` は現在 `PyQt6 / pyqtgraph / pandas / openpyxl` のみ。`python-pptx`・`matplotlib`
  は記載も導入もされていない。
- **2つの必須依存が欠落 → タスクの停止条件に合致。** 実装（Workbench 改修・helper 追加・pptx 生成）は行わない。

---

## 2. 環境で確認した事実（設計の根拠・read-only）

停止するが、承認後に即着手できるよう、実装対象を read-only で確認済み。

### 2a. 正本DB `lap_suspension`（1202行 / 69列）
- タスク §6 が指定する列は**全て実在**（`brk_susF_avg`〜`ce_r_spd_avg` を含む18列を検査 → 全 OK）。
  §44 で追加した 3フェーズ×F/R 方向別 22列も反映済み。
- **`lap_suspension` は per-lap 非正規化テーブルで、メタ列を自己内包**:
  `run_id / lap_id / rider / circuit / session / round / run_no / lap_no / lap_time_s / fullbrk_count / ce_count`
  が全て存在（サンプル: `PHILLIPISLAND / JA52 / RACE2 / run_no=1 / lap_no=2 / 148.785s`）。
  → **MVP は `SELECT * FROM lap_suspension` だけで完結でき、`laps`/`runs` への JOIN は必須ではない**
  （タスク §6 の JOIN 要件は lap_time/run/session/rider/circuit を得るためだが、全て本テーブルに存在する）。
  `race_lap_detail` は不要（MVP は 2D 由来 `lap_suspension` を優先、というタスク方針と整合）。

### 2b. Workbench 構造（`ts24_workbench.py` 6910行）
- `PostureAnalysisTab`（🦾 Suspension/Posture）内に内部 `QTabWidget`。第3サブタブ
  **`🔧 3フェーズ Run比較` = `PhaseRunCompareWidget`**（L3059〜）。
- `PhaseRunCompareWidget` は既にフィルタ状態と選択 Run を保持しており、`Create Report` から**そのまま再利用できる**:
  - `self._df`：親 `PostureAnalysisTab._load_data()` が `set_dataframe()` で共有（全小文字化済み・pitch/heave 付与済み）。
  - `_base_df()`（L3440）：Circuit / Rider / Session フィルタ + lap_time レンジ（60–300s）適用済みの DataFrame を返す。
  - `_checked_run_ids()`（L3431）：Run 選択リストでチェック中の `run_id` リストを返す。
  - フィルタ getter：`_combo_circ / _combo_rider / _combo_sess / _combo_phase / _combo_metric`。
  - 定数：`_PHASE_POS`（位置列）/ `_PHASE_SPD`（速度列・6 slot 充填済み）/ `_PHASE_COLORS`
    （Braking `#C0392B` / Apex `#0078D4` / Exit `#2E9E4F`）。
- **出力先 `05_SCRIPTS/reports/pptx/` は未作成**（実装時に生成する。今回は作らない）。
- 既存の report helper / pptx 生成コードは**存在しない**（新規追加になる）。

---

## 3. 必要 dependency（承認後に install するもの）

**ネットワーク install は承認境界**（`00_INBOX/FOR_CLAUDE_CODE.md` の承認の境界・§27d-2）。Tatsuki の明示承認後に実施する。

```text
python-pptx>=0.6.23      # PPTX 生成（1.x 系でも可。API 互換）
matplotlib>=3.7.0        # グラフを Agg で PNG 化してスライドに貼付
```

`requirements_workbench.txt` への追記案（承認後）:

```diff
 PyQt6>=6.6.0
 pyqtgraph>=0.13.0
 pandas>=2.0.0
 openpyxl>=3.1.0
+python-pptx>=0.6.23
+matplotlib>=3.7.0
```

インストール例（macOS・システム Python。要承認）:

```bash
python3 -m pip install "python-pptx>=0.6.23" "matplotlib>=3.7.0"
```

> 注: matplotlib は依存に numpy を含むが既に 2.0.2 が入っており競合しない見込み。install 後に
> `python3 -c "import pptx, matplotlib; print(pptx.__version__, matplotlib.__version__)"` で疎通確認する。

---

## 4. 実装可能範囲（依存が揃った前提）

| 範囲 | 依存 | 可否 |
|---|---|---|
| DB read-only 集計（Run/Lap/フェーズ別 position/speed の avg/p95、NULL率、best/median lap、coverage） | pandas（済） | ✅ 依存無しでも可 |
| グラフ画像生成（lap point / Run trend / avg 主線・p95 補助線） | matplotlib（要install）or pyqtgraph（済・§7 代替案） | ⚠ matplotlib 推奨 |
| PowerPoint `.pptx` 生成（10スライド・画像貼付・表） | **python-pptx（要install・代替困難）** | ❌ 現状不可 |
| Workbench に `Create Report` ボタン追加・例外処理・既存無回帰 | PyQt6（済） | ✅ 可（ただし pptx 生成が動かないと無意味） |

- **律速は `python-pptx`。** これが無いと成果物（.pptx）が出せないため、install 承認が実装の前提。
- グラフだけは matplotlib 無しでも pyqtgraph の `ImageExporter` で代替可能（§7）だが、タスクは matplotlib `Agg` を
  指定しており、GUI 非依存・実装容易性の点でも matplotlib 導入を推奨する。

---

## 5. 最小設計（承認 + install 後の実装青写真）

### 5a. モジュール構成
- 新規 **`05_SCRIPTS/suspension_report.py`**（単体テストしやすい純関数 + 生成関数に分離）:
  - `load_lap_suspension(db_path, circuit, rider, session, run_ids) -> pd.DataFrame`
    （`sqlite3` を `file:...?mode=ro` の read-only URI で接続。`SELECT * FROM lap_suspension` → フィルタ）。
  - `summarize_session(df) -> dict`（Run数 / Lap数 / best / median / coverage）。
  - `phase_position_stats(df, phase) -> dict` / `phase_speed_stats(df, phase) -> dict`
    （avg = mean、p95 = 既存 peak 列、NULL率、sample不足フラグ）。
  - `run_compare_table(df, run_ids) -> list[list]`（Run別 主要 position/speed）。
  - `data_quality(df) -> dict`（NULL率・構造的NULL＝Exit希薄・外れ値 warning）。
  - `make_chart_png(kind, df, ...) -> Path`（matplotlib `Agg`。Braking/Apex/Exit は `_PHASE_COLORS` と色一貫）。
  - `build_pptx(context, out_dir) -> Path`（python-pptx。10スライド組立・画像貼付・表）。
- **`build_pptx` / `make_chart_png` は import guard 付き**（`try: import pptx / matplotlib` → 無ければ
  `ReportUnavailableError` を送出し、Workbench 側で「PowerPoint 生成には python-pptx / matplotlib が必要です」と
  message box 表示）。→ アプリは落とさない。

### 5b. Workbench 側（`ts24_workbench.py`・最小差分）
- `PhaseRunCompareWidget` のフィルタバー（`_setup_ui` の `fb` レイアウト）に
  **`📄 Create Report` ボタン**を1つ追加（`fb.addStretch()` の前）。
- ハンドラ `_on_create_report()`:
  1. `df = self._base_df()`（フィルタ済）、`run_ids = self._checked_run_ids()`。
  2. `run_ids` が空なら message box で「Run を1つ以上選択してください」。
  3. `suspension_report.build_report(...)` を呼ぶ（内部で 5a を組立）。
  4. 成功 → status text / message box に出力パス表示。失敗 → 例外を捕捉し message box（**落とさない**）。
- 既存 `_PHASE_POS / _PHASE_SPD / _PHASE_COLORS` を helper へ渡し、UI とレポートの定義を一致させる。
- MVP フォールバック：フィルタ状態が使えれば使う。難しければ Circuit / Rider / Session / Run を簡易選択して生成
  （タスク §3 準拠）。今回の設計は既存フィルタ再利用で足りる。

### 5c. スライド構成（タスク §4 準拠・10枚）
1. Title（Circuit / Rider / Session / selected Runs / generated_at）
2. Session Summary（Run数・Lap数・best・median・coverage）
3. Braking Suspension Position（F/R avg・lap point・Run trend）
4. Braking Suspension Speed（F `brk_f_dive_spd_*` / R `brk_r_reb_spd_*` の avg/p95）
5. Apex Suspension Position
6. Apex Suspension Speed（`apex_f/r_dive/reb_spd_*` avg/p95）
7. Exit Suspension Position
8. Exit Suspension Speed（F `ce_f_reb_spd_*` / R `ce_r_dive/reb_spd_*` avg/p95。`ce_r_spd_*` は abs legacy と注記）
9. Run Compare Table（Run別 Braking/Apex/Exit の主要 position/speed）
10. Data Quality（NULL率・sample不足・構造的NULL・外れ値 warning）

### 5d. データ対象列（タスク §6 準拠）
- **Position:** `brk_susF_avg` `brk_susR_avg` `apex_susF_avg` `apex_susR_avg` `ce_susF_avg` `ce_susR_avg`
- **Speed（avg/peak）:** `brk_f_dive_spd_*` `brk_r_reb_spd_*` `apex_f_dive_spd_*` `apex_f_reb_spd_*`
  `apex_r_dive_spd_*` `apex_r_reb_spd_*` `ce_f_reb_spd_*` `ce_r_dive_spd_*` `ce_r_reb_spd_*` `ce_r_spd_*`（legacy abs）
- **メタ:** `rider / circuit / session / run_no / lap_no / lap_time_s / round`（`lap_suspension` に内包）+
  信頼度 `fullbrk_count / ce_count`。

### 5e. グラフ・注記方針（タスク §5 準拠）
- matplotlib `Agg`（GUI 非依存）で PNG 化 → `add_picture`。
- Braking/Apex/Exit の色は一貫（`_PHASE_COLORS`）。avg = 主線 / p95・peak = 補助線。
- **サス速度は `relative damping-speed index (mm/s, uncalibrated)` と全スライドに注記**。
- **車速（km/h）とサス速度を混同しない**（`*_spd_avg` の車速系は使わない）。
- `NULL`（データ欠落）と `not available`（構造的に存在しない）を区別して表示。

### 5f. 出力
- ディレクトリ: `05_SCRIPTS/reports/pptx/`（実装時に作成）。
- ファイル名: `suspension_report_<circuit>_<rider>_<session>_<YYYYMMDD_HHMMSS>.pptx`（timestamp 付き・上書きしない）。

### 5g. 実装後の検証（タスク §8 準拠）
- `python3 -m py_compile ts24_workbench.py suspension_report.py`
  （macOS の cache 権限対策で `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache` を付ける）。
- CLI or 内部関数でサンプル pptx を1本生成 → 存在 & サイズ>0 → python-pptx で読み戻し slide 数確認。
- offscreen smoke（`QT_QPA_PLATFORM=offscreen`）: Workbench 起動 → `PostureAnalysisTab` → `🔧 3フェーズ Run比較`
  → `Create Report` ボタン存在 → 既存グラフ無回帰。
- GUI 目視は Tatsuki ローカル。

---

## 6. Multi-agent operating check（本 readiness 段階）

| エージェント | 状況 |
|---|---|
| Suspension/Physics | スライド内容（position=バネ/ジオメトリ、speed=ダンピング、車速と非混同、Exit希薄の構造）を設計に反映済み |
| Data | `lap_suspension` 自己内包を確認し JOIN 不要と判定。read-only（`mode=ro`）方針・legacy abs 列の注記を定義 |
| Report/PPT | 10スライド構成・画像貼付・表・slide 数検証を設計。**python-pptx 欠落を検出**（実装ブロッカー） |
| Workbench/UI | ボタン設置場所（フィルタバー）・例外は message box・既存無回帰の最小差分を設計 |
| Quality | py_compile / pptx 生成 / slide 数 / offscreen smoke の検証手順を定義。**matplotlib 欠落を検出** |
| Documentation/Handoff | 本 readiness / CLAUDE.md §45 / Obsidian（log・handoff・CURRENT_STATE・Result）を更新 |
| Supervisor | **ネットワーク install を承認境界として停止**。DB write / Supabase / DB Master / origin push / 新2D を保留 |

---

## 7. 代替案（参考・非推奨だが技術的には可能）

- **チャートのみ matplotlib 無しで生成:** `pyqtgraph.exporters.ImageExporter` で PlotWidget を PNG 化できる
  （`QApplication` が必要・offscreen 可）。ただし PPTX 本体の代替にはならない。
- **python-pptx 無しで .pptx を手組み:** OOXML（zip+XML）を手書きすれば理論上可能だが、**MVP には過剰・脆弱で非推奨**。
- **結論:** どちらも本命にせず、`python-pptx` + `matplotlib` の正規導入を推奨（タスクの `Agg` 指定とも一致）。

---

## 8. スコープ外 / 次ゲート

- 本作業で**していないこと**: ネットワーク install / Workbench 改修 / helper 追加 / pptx 生成 / DB schema 変更 /
  正本DB 書込 / Supabase / DB Master 再生成 / origin push / 新2D取込。
- **rollback:** コード・正本DB とも無変更のため rollback 不要（成果物は本 readiness と Obsidian/CLAUDE 記録のみ）。
- **次ゲート（Tatsuki 承認）:** 「`python-pptx` / `matplotlib` を install してよい」の明示承認。
  承認後、本 §5 設計で `suspension_report.py` 実装 + Workbench `Create Report` 追加 + 検証 → 実装レポート
  `reports/workbench_suspension_report_mvp_20260702.md` を作成する。

---

## 9. 成果物

- `05_SCRIPTS/reports/workbench_suspension_report_readiness_20260702.md`（本ファイル）
- `05_SCRIPTS/CLAUDE.md` §45（追記）
- Obsidian: `log.md` / `03_AI_HANDOFF/AI_HANDOFF_LATEST.md` / `CURRENT_STATE.md` / `00_INBOX/FOR_CLAUDE_CODE.md`（Result）
