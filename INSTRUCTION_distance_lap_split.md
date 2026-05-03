# Claude Code 実装指示書
# タスク: Lap分割の優先順位制御（DB駆動 最優先）
# 対象ファイル: 05_SCRIPTS/ts24_workbench.py
# 前提: INSTRUCTION_laptime_and_lapsplit.md + INSTRUCTION_distance_axis_and_db_schema.md 実装済み
# 作成: Cowork Claude / 2026-05-03  （v2: DB駆動アルゴリズム追加）

---

## 背景・方針

固定距離によるLap分割（dist >= circuit_len）は実走行ラインのばらつきとGPS誤差で
**周回ごとに距離ズレが累積する**ため、正式記録には使えない。

`ts24_unified.db` の `laps` テーブルには MESファイル処理時に記録された
**ラップごとの精確なタイムデータ**が存在する（ROUND3_ASSEN_FP_DA77_R1: 11行）。
このデータを使えば CSV を sub-0.02s 精度で回路ラップに分割できることを確認済み。

**確定した優先順位（Tatsuki / Cowork Claude 2026-05-03）:**

```
優先1: CSV内の Lap / LapNo / LapCounter / LapTrigger 列で分割  ← 最も正確
優先2: DB の laps テーブルを使ったDB駆動分割               ← 本指示書のメイン
優先3: 固定Lap Lengthで近似分割（⚠ Approximate 警告表示）
優先4: 時間ギャップ > 5s（セッション境界のみ／最終fallback）
```

**重要な注意:**
- 固定距離分割使用時は UIに `⚠ Approximate split` と表示する
- DB駆動分割が使えるのは左パネルで Run が選択されている場合のみ
- Workbenchは「Deep Analysis記録ツール」なので Lap精度が問題定義の正確さに直結する

---

## DB駆動アルゴリズムの検証結果

実データ `X_F1-#77-03_DISTANCE.csv`（= ROUND3_ASSEN_FP_DA77_R1）で検証済み:

```
DB laps table (run_id=ROUND3_ASSEN_FP_DA77_R1):
  Lap 0: is_outlap=1  → 除外
  Lap 1: 100.67s
  Lap 2: 100.25s
  Lap 3:  99.72s
  Lap 4: 105.08s  ← CSV時間ギャップ(105.09s)と一致 → gap lapとして除外
  Lap 5:  98.92s
  Lap 6:  99.13s
  Lap 7:  99.14s
  Lap 8:  98.85s
  Lap 9:  98.96s
  Lap 10: 98.79s

結果: 9 valid laps ✅  各Lap 0m→4554m
最大誤差: 0.02s（許容範囲）
```

---

## 変更1: `WorkbenchDB` に `get_laps()` メソッドを追加

**場所**: `WorkbenchDB` クラス内、`get_setup_decisions()` の後に追加。

```python
    def get_laps(self, run_id: str) -> list[dict]:
        """laps テーブルから指定 run_id の全ラップを返す。
        
        Returns list of dicts with keys: lap_no, lap_time_s, is_outlap
        """
        try:
            with sqlite3.connect(self._path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT lap_no, lap_time_s, is_outlap
                       FROM laps WHERE run_id = ? ORDER BY lap_no""",
                    (run_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []
```

---

## 変更2: `CsvImportTab.__init__` に `db` と `run_id` を追加

**変更前:**
```python
    def __init__(self, wave_view: "WaveformView", parent=None):
        super().__init__(parent)
        self._wave = wave_view
        self._df: "pd.DataFrame | None" = None
        self._col_combos: dict[str, QComboBox] = {}
        self._setup_ui()
```

**変更後:**
```python
    def __init__(self, wave_view: "WaveformView", db: "WorkbenchDB", parent=None):
        super().__init__(parent)
        self._wave = wave_view
        self._db   = db
        self._run_id: str = ""          # 左パネルで選択中の run_id
        self._df: "pd.DataFrame | None" = None
        self._col_combos: dict[str, QComboBox] = {}
        self._setup_ui()
```

**`set_run()` メソッドを追加（`_auto_detect()` の前あたりに挿入）:**
```python
    def set_run(self, run_id: str):
        """左パネルで Run が選択されたときに呼ばれる。"""
        self._run_id = run_id
        lbl = f"DB Run: {run_id}" if run_id else "DB Run: 未選択"
        # _lbl_split_mode が存在すればプレースホルダー更新
        if hasattr(self, "_lbl_split_mode"):
            current = self._lbl_split_mode.text()
            if not current or current.startswith("DB Run:"):
                self._lbl_split_mode.setText(lbl)
                self._lbl_split_mode.setStyleSheet(
                    "color: #0078D4; font-size: 10px;"
                )
```

---

## 変更3: `CsvImportTab` の CHANNEL_MAP に Lap 系列を追加

**CHANNEL_MAP に `"lap_no"` キーを追加:**
```python
    CHANNEL_MAP: dict[str, list[str]] = {
        "time":       ["time", "time2d"],
        "distance":   ["dist", "distance"],
        "lap_no":     ["lap", "lapno", "lap_no", "lapcounter", "lap_counter",
                       "laptrigger", "lap_trigger", "lapmarker", "lap_marker"],
        "speed":      ["speed_front", "speed"],
        "brake":      ["brake_front"],
        "gas":        ["gas", "gas_smooth", "tps"],
        "susp_front": ["susp_front"],
        "susp_rear":  ["susp_rear"],
        "lean_angle": ["bike_angle", "lean_angle"],
    }
```

**`_TARGETS` にも追加:**
```python
    _TARGETS = [
        "(ignore)", "time", "distance", "lap_no", "speed", "brake", "gas",
        "susp_front", "susp_rear", "lean_angle",
    ]
```

---

## 変更4: `CsvImportTab._setup_ui()` に「1周距離」入力欄と分割モード表示を追加

**挿入位置**: `self._lbl_dist` の `layout.addWidget(self._lbl_dist)` の直後、
`map_lbl = QLabel(...)` の前に挿入する。

```python
        # ── Lap分割設定（DB優先・fallback用距離入力）────────────────
        lap_len_row = QHBoxLayout()
        lap_len_row.addWidget(QLabel("1周距離 (m):"))
        self._spin_circuit_len = QSpinBox()
        self._spin_circuit_len.setRange(0, 20000)
        self._spin_circuit_len.setValue(4555)
        self._spin_circuit_len.setSingleStep(100)
        self._spin_circuit_len.setSpecialValueText("0 = 時間ギャップ法")
        self._spin_circuit_len.setToolTip(
            "DBにLapデータがない場合の近似分割基準距離（fallback）。\n"
            "左パネルでRunを選択するとDBから自動分割します。\n"
            "Assen = 4555m / 0 = 時間ギャップ法（>5s）"
        )
        self._spin_circuit_len.setFixedWidth(90)
        lap_len_row.addWidget(self._spin_circuit_len)
        self._lbl_split_mode = QLabel("DB Run: 未選択")
        self._lbl_split_mode.setStyleSheet("color: #0078D4; font-size: 10px;")
        lap_len_row.addWidget(self._lbl_split_mode)
        lap_len_row.addStretch()
        layout.addLayout(lap_len_row)
```

---

## 変更5: `CsvImportTab._send()` — Lap分割ロジックを優先順位制御に置き換え

**場所**: `_send()` 内の「時間ギャップでLap分割」ブロック全体（下記の箇所）を置き換える。

**置き換え対象（変更前）:**
```python
        # ── 時間ギャップでLap分割 ─────────────────────────────────────
        import numpy as np

        if x_mode in ("time", "distance") and t_raw is not None:
            # time[i] - time[i-1] > 5 秒の箇所でLap境界を検出
            lap_indices: list[list[int]] = []
            current: list[int] = [0]
            for i in range(1, len(t_raw)):
                if (t_raw[i] - t_raw[i - 1]) > 5.0:
                    lap_indices.append(current)
                    current = [i]
                else:
                    current.append(i)
            lap_indices.append(current)
        else:
            lap_indices = [list(range(n))]
```

**変更後（上記ブロックを以下で置き換える）:**

```python
        # ── Lap分割（優先順位制御）────────────────────────────────────
        import numpy as np

        circuit_len_m = self._spin_circuit_len.value() if hasattr(self, "_spin_circuit_len") else 0
        split_mode = "unknown"

        # ─ Step A: CSV時間ギャップでセグメント境界を検出（全優先度で共通）
        # これはセッション間の大きなギャップ（ピット等）の検出に使う
        segments: list[tuple[int, int]] = []  # (start_idx, end_idx)
        csv_gap_durations: list[float] = []
        if t_raw is not None:
            seg_start = 0
            for i in range(1, len(t_raw)):
                if (t_raw[i] - t_raw[i - 1]) > 5.0:
                    segments.append((seg_start, i - 1))
                    csv_gap_durations.append(float(t_raw[i] - t_raw[i - 1]))
                    seg_start = i
            segments.append((seg_start, len(t_raw) - 1))
        else:
            segments = [(0, n - 1)]

        lap_indices: list[list[int]] = []  # 最終的な分割結果

        # ─ 優先1: CSV内のLap列で分割 ─────────────────────────────────
        has_lap_col = "lap_no" in channel_to_col
        if has_lap_col:
            try:
                lap_col = pd.to_numeric(
                    df[channel_to_col["lap_no"]], errors="coerce"
                ).fillna(0).values.astype(int)
                cur_lap = lap_col[0]
                cur: list[int] = [0]
                for i in range(1, len(lap_col)):
                    if lap_col[i] != cur_lap:
                        lap_indices.append(cur)
                        cur = [i]
                        cur_lap = lap_col[i]
                    else:
                        cur.append(i)
                lap_indices.append(cur)
                lap_indices = [seg for seg in lap_indices if len(seg) >= 2]
                split_mode = "lap_col"
            except Exception:
                has_lap_col = False
                lap_indices = []

        # ─ 優先2: DBのlapsテーブルを使った精確分割 ─────────────────
        if not lap_indices and self._run_id and t_raw is not None:
            try:
                db_laps = self._db.get_laps(self._run_id)
                # is_outlap=1 を除外した計時ラップのみ使用
                timed_laps = [
                    (r["lap_no"], float(r["lap_time_s"]))
                    for r in db_laps
                    if not r.get("is_outlap") and r.get("lap_time_s")
                ]
                if timed_laps:
                    # CSV時間ギャップとDBラップタイムを照合してgap lapを特定
                    GAP_TOLERANCE = 2.0
                    gap_lap_nos: set[int] = set()
                    for gap_dur in csv_gap_durations:
                        for lap_no, lt in timed_laps:
                            if abs(lt - gap_dur) < GAP_TOLERANCE:
                                gap_lap_nos.add(lap_no)
                                break
                    # gap lapを除いた有効ラップリスト
                    valid_laps = [
                        (lap_no, lt)
                        for lap_no, lt in timed_laps
                        if lap_no not in gap_lap_nos
                    ]
                    if valid_laps:
                        # 各セグメント内でDBのラップタイムを累算し、
                        # np.searchsorted でCSV行番号に変換
                        result: list[list[int]] = []
                        lap_cursor = 0
                        for s_start, s_end in segments:
                            t_cursor = float(t_raw[s_start])
                            s_dur = float(t_raw[s_end]) - t_cursor
                            accumulated = 0.0
                            while lap_cursor < len(valid_laps):
                                _, lt = valid_laps[lap_cursor]
                                if accumulated + lt > s_dur + 1.0:
                                    break
                                accumulated += lt
                                lap_cursor += 1
                                t_lap_end = t_cursor + lt
                                start_i = int(np.searchsorted(t_raw, t_cursor, side="left"))
                                end_i = int(np.searchsorted(t_raw, t_lap_end, side="right")) - 1
                                end_i = min(end_i, s_end)
                                if end_i > start_i:
                                    result.append(list(range(start_i, end_i + 1)))
                                t_cursor = float(t_raw[end_i + 1]) if end_i + 1 <= s_end else t_lap_end
                        if result:
                            lap_indices = result
                            split_mode = "db_driven"
            except Exception:
                lap_indices = []

        # ─ 優先3: 固定距離での近似分割 ───────────────────────────────
        if not lap_indices and d_raw is not None and circuit_len_m > 0:
            all_segs: list[list[int]] = []
            start_dist_val = float(d_raw[0])
            cur = [0]
            for i in range(1, len(d_raw)):
                if (d_raw[i] - start_dist_val) >= circuit_len_m:
                    all_segs.append(cur)
                    cur = [i]
                    start_dist_val = float(d_raw[i])
                else:
                    cur.append(i)
            all_segs.append(cur)
            min_span = circuit_len_m * 0.5
            lap_indices = [
                seg for seg in all_segs
                if len(seg) >= 2 and (d_raw[seg[-1]] - d_raw[seg[0]]) >= min_span
            ]
            split_mode = "distance_approx"

        # ─ 優先4: 時間ギャップ法（最終fallback）────────────────────
        if not lap_indices:
            if t_raw is not None:
                for s_start, s_end in segments:
                    seg = list(range(s_start, s_end + 1))
                    if len(seg) >= 10:
                        lap_indices.append(seg)
                split_mode = "time_gap"
            else:
                lap_indices = [list(range(n))]
                split_mode = "full"

        # ─ split_mode の UI表示 ────────────────────────────────────
        mode_labels = {
            "lap_col":        ("✅ Lap列で正確分割",             "#107C10"),
            "db_driven":      ("✅ DBラップで正確分割",           "#107C10"),
            "distance_approx":("⚠ 距離で近似分割（Approximate）","#D83B01"),
            "time_gap":       ("⚠ 時間ギャップ分割",             "#797673"),
            "full":           ("— セッション全体",               "#797673"),
        }
        if hasattr(self, "_lbl_split_mode"):
            mode_txt, mode_clr = mode_labels.get(split_mode, ("", "#000"))
            self._lbl_split_mode.setText(mode_txt)
            self._lbl_split_mode.setStyleSheet(f"color: {mode_clr}; font-size: 10px;")
```

---

## 変更6: `lap` dict に `split_mode` を追加

**場所**: `_send()` 内の `lap: dict = {` 初期化部分に `"split_mode"` を追加。

```python
            lap: dict = {
                "x":           x_vals,
                "x_mode":      x_mode,
                "lap_no":      lap_no,
                "lap_time_s":  lap_time_s,
                "dist_span_m": dist_span_m,
                "split_mode":  split_mode,   # ← 追加
            }
```

---

## 変更7: `MainWindow` の `CsvImportTab` 生成と run_id 通知を更新

### 変更7a — `CsvImportTab` に `db` を渡す

**場所**: `MainWindow.__init__()` 内の `_tab_csv` 生成行

**変更前:**
```python
        self._tab_csv     = CsvImportTab(wave_view=self._tab_wave)
```

**変更後:**
```python
        self._tab_csv     = CsvImportTab(wave_view=self._tab_wave, db=self._db)
```

### 変更7b — Run選択時に `_tab_csv` にも run_id を通知

**場所**: `MainWindow._on_run_selected()` の末尾に1行追加

**変更前:**
```python
        self._tab_wave.set_run(run_id, circuit)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)
```

**変更後:**
```python
        self._tab_wave.set_run(run_id, circuit)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)
        self._tab_csv.set_run(run_id)           # ← 追加
```

---

## 動作確認

### テスト1: DB駆動分割（メインシナリオ）
1. 左パネルで `ROUND3_ASSEN_FP_DA77_R1` を選択
2. 2D CSVタブで `X_F1-#77-03_DISTANCE.csv` を開く
3. 「波形に送る」をクリック

**期待結果:**
- `✅ DBラップで正確分割` が緑で表示
- ドロップダウンに **9ラップ** が表示
- 各ラップの X軸が `0m〜4554m`
- ラップタイム表示例: `CSV Lap 1  1:40,67`

### テスト2: Run未選択 / 固定距離fallback
1. 左パネルで何も選択しない（またはDB lapsが存在しないRunを選択）
2. 1周距離を `4555` に設定して「波形に送る」

**期待結果:**
- `⚠ 距離で近似分割（Approximate）` がオレンジで表示
- 9ラップ表示（ただし距離誤差あり）

### テスト3: 1周距離を `0` に設定
- `⚠ 時間ギャップ分割` が表示
- 2セグメント（従来の動作）

### テスト4: Lap列付きCSV（将来対応）
2Dから Lap列付きでExportしたCSVを読み込む:
- `✅ Lap列で正確分割` が緑で表示

---

## NG条件

| 症状 | 原因 |
|------|------|
| `✅ DBラップで正確分割` が出ず `⚠ 距離で近似分割` になる | `set_run()` が呼ばれていない / `_run_id` が空 |
| 9ラップが2ラップになる | DB駆動ロジックが動作せず時間ギャップfallbackに落ちている |
| X軸が 0m 始まりにならない | `d_raw[seg[0]]` のリセット処理が未適用 |
| `1周距離` 欄が表示されない | 変更4の挿入位置が間違っている |
| `get_laps()` でエラー | `laps` テーブルが存在しない（migrate未実行） |

---

## Git コミットメッセージ

```
feat: DB-driven lap splitting (highest precision, priority 2)

- add: WorkbenchDB.get_laps(run_id) → laps table query
- add: CsvImportTab accepts db param + set_run(run_id) method
- feat: DB-driven split using laps table + CSV gap matching
  - detects gap laps (e.g., Lap4=105s pit stop) and skips them
  - uses np.searchsorted for exact row boundaries
  - verified: 9 laps × 0~4554m, max 0.02s error
- add: "lap_no" to CHANNEL_MAP (Lap/LapNo/LapCounter/LapTrigger)
- add: QSpinBox + split_mode label in CsvImportTab UI
- feat: priority order: Lap列 > DB driven > dist approx > time gap
- fix: MainWindow passes db to CsvImportTab, notifies set_run
- result: "✅ DBラップで正確分割" for ROUND3_ASSEN_FP_DA77_R1
```
