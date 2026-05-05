# Claude Code 指示書：2ライダー比較表示 + 時間オフセット機能
## 対象ファイル: `05_SCRIPTS/ts24_workbench.py`

---

## 背景・目的

現在の Workbench は「1つの CSV」内のラップAとラップB（同ライダー）を比較するのみ。  
2人のライダー（例: DA77 と JA52）のCSVを同時に読み込み、波形を重ねて比較したい。  
さらに、ラップの開始タイミングがずれている場合は **オフセットスライダーで手動位置合わせ** できるようにする。

---

## 変更対象クラス

- `WaveformView`（line 265〜）
- `MainWindow`（line ~1920〜）

---

## 変更 1 — `WaveformView.__init__()` に比較用属性とオフセット UI を追加

### 1-a. インスタンス属性（`__init__` 冒頭に追加）

`self._csv_x_mode: str = "progress"` の直後に追記:

```python
# 2ライダー比較用
self._laps_cache_b: list[dict] = []   # 比較ライダーのラップキャッシュ
self._label_a: str = ""               # プライマリライダー名（例: "DA77"）
self._label_b: str = ""               # 比較ライダー名（例: "JA52"）
self._offset_b: float = 0.0           # Bライダーの時間オフセット（秒）
```

### 1-b. コントロール行 (`sel_row`) に追加 — `sel_row.addStretch()` の直前に挿入

```python
# ── 比較ライダー表示ラベル ──────────────────────────────────
self._lbl_b_rider = QLabel("")
self._lbl_b_rider.setStyleSheet(
    "color: #FF8C00; font-weight: bold; font-size: 10px;"
    " background: #FFF3E0; padding: 2px 6px; border-radius: 3px;"
)
self._lbl_b_rider.setVisible(False)
sel_row.addSpacing(16)
sel_row.addWidget(self._lbl_b_rider)

# ── Bオフセットコントロール ────────────────────────────────
lbl_off = QLabel("  Bオフセット:")
lbl_off.setStyleSheet("font-size: 10px; color: #666;")
self._offset_spin = QDoubleSpinBox()
self._offset_spin.setRange(-600.0, 600.0)
self._offset_spin.setSingleStep(0.5)
self._offset_spin.setSuffix(" s")
self._offset_spin.setValue(0.0)
self._offset_spin.setDecimals(1)
self._offset_spin.setFixedWidth(90)
self._offset_spin.setToolTip("比較ライダー(B)の時間軸をずらして位置合わせ")
self._offset_spin.valueChanged.connect(self._on_offset_changed)

btn_reset_off = QPushButton("↺")
btn_reset_off.setFixedWidth(28)
btn_reset_off.setFixedHeight(22)
btn_reset_off.setToolTip("オフセットを 0 にリセット")
btn_reset_off.clicked.connect(lambda: self._offset_spin.setValue(0.0))

btn_clear_b = QPushButton("✕ 比較解除")
btn_clear_b.setFixedHeight(22)
btn_clear_b.setStyleSheet(
    "QPushButton { background: #797673; color: white; padding: 2px 8px;"
    " border-radius: 3px; font-size: 10px; }"
    "QPushButton:hover { background: #5C5A58; }"
)
btn_clear_b.setToolTip("比較CSVをクリア")
btn_clear_b.clicked.connect(self.clear_compare)

sel_row.addWidget(lbl_off)
sel_row.addWidget(self._offset_spin)
sel_row.addWidget(btn_reset_off)
sel_row.addSpacing(8)
sel_row.addWidget(btn_clear_b)
```

---

## 変更 2 — `WaveformView` に新メソッドを追加

`_send_to_problem_log()` メソッドの直前に追加:

```python
# ── 2ライダー比較 API ──────────────────────────────────────────────

def set_label_a(self, label: str) -> None:
    """プライマリCSV（A）のライダーラベルを設定。"""
    self._label_a = label

def set_compare_laps(self, laps_b: list[dict], label_b: str) -> None:
    """比較ライダー(B)のラップデータをセット。_combo_b を更新して再描画。"""
    self._laps_cache_b = laps_b
    self._label_b = label_b
    self._update_combo_b()
    self._lbl_b_rider.setText(f"B: {label_b}  ({len(laps_b)} laps)")
    self._lbl_b_rider.setVisible(True)
    self._draw()

def clear_compare(self) -> None:
    """比較ライダーのデータをクリアし、通常モードに戻す。"""
    self._laps_cache_b = []
    self._label_b = ""
    self._offset_b = 0.0
    self._offset_spin.setValue(0.0)
    self._lbl_b_rider.setVisible(False)
    self._update_combo_b()
    self._draw()

def _on_offset_changed(self, v: float) -> None:
    """オフセットスピンボックス変更時。"""
    self._offset_b = float(v)
    self._draw()

def _update_combo_b(self) -> None:
    """_laps_cache_b が存在する場合はそちらを、なければ _laps_cache を _combo_b に表示。"""
    src = self._laps_cache_b if self._laps_cache_b else self._laps_cache
    self._combo_b.blockSignals(True)
    self._combo_b.clear()
    for i, r in enumerate(src):
        lap_no = r.get("lap_no", i + 1)
        lt = r.get("lap_time_s")
        lt_str = f"{lt:.3f}s" if lt else "—"
        xm = r.get("x_mode", "")
        if xm == "distance":
            dist_m = float(r.get("dist_m", 0))
            self._combo_b.addItem(f"CSV Lap {lap_no}  {dist_m:.0f}m  ({lt_str})")
        else:
            self._combo_b.addItem(f"CSV Lap {lap_no}  {lt_str}")
    self._combo_b.blockSignals(False)
```

---

## 変更 3 — `WaveformView._draw()` を修正

### 3-a. lap_b の取得元とカラーを変更

現在のコード（`_draw()` 内）:
```python
lap_b = self._laps_cache[ib] if (0 <= ib < len(self._laps_cache)) else None
colors = {"a": pg.mkPen("#0078D4", width=2), "b": pg.mkPen("#E74C3C", width=1.5)}
```

↓ これを以下に置き換え:

```python
# B ラップ: 比較CSVがあればそちらから、なければ同一CSVから
if self._laps_cache_b:
    lap_b = self._laps_cache_b[ib] if (0 <= ib < len(self._laps_cache_b)) else None
    pen_b = pg.mkPen("#FF8C00", width=1.5)   # オレンジ = 比較ライダー
else:
    lap_b = self._laps_cache[ib] if (0 <= ib < len(self._laps_cache)) else None
    pen_b = pg.mkPen("#E74C3C", width=1.5)   # 赤 = 同一CSV内比較（従来）
colors = {"a": pg.mkPen("#0078D4", width=2), "b": pen_b}
```

### 3-b. `_plot()` ヘルパーにオフセット引数を追加

現在:
```python
def _plot(lap, label, pen, channel, plot_obj):
    xs_raw = _get_x(lap)
    ys_raw = _get_y(lap, channel)
    if not xs_raw or not ys_raw or len(xs_raw) != len(ys_raw):
        return
    xs = np.array(xs_raw, dtype=float) if x_mode in ("time", "distance") else _normalize(xs_raw)
    ys = np.array(ys_raw, dtype=float)
    plot_obj.plot(x=xs, y=ys, pen=pen, name=label)
```

↓ オフセット引数を追加:

```python
def _plot(lap, label, pen, channel, plot_obj, offset_x: float = 0.0):
    xs_raw = _get_x(lap)
    ys_raw = _get_y(lap, channel)
    if not xs_raw or not ys_raw or len(xs_raw) != len(ys_raw):
        return
    if x_mode in ("time", "distance"):
        xs = np.array(xs_raw, dtype=float) + offset_x
    else:
        xs = _normalize(xs_raw)
    ys = np.array(ys_raw, dtype=float)
    plot_obj.plot(x=xs, y=ys, pen=pen, name=label)
```

### 3-c. ラベルにライダー名を含める & B にオフセット適用

現在:
```python
for ch, p in _CHAN_PANELS:
    _plot(lap_a, f"A Lap{lap_a.get('lap_no', '')}", colors["a"], ch, p)
    if lap_b:
        _plot(lap_b, f"B Lap{lap_b.get('lap_no', '')}", colors["b"], ch, p)
```

↓ 以下に置き換え:

```python
label_a = f"{self._label_a + ' ' if self._label_a else ''}L{lap_a.get('lap_no', '')}"
offset_apply = self._offset_b if x_mode == "time" else 0.0

for ch, p in _CHAN_PANELS:
    _plot(lap_a, f"A:{label_a}", colors["a"], ch, p)
    if lap_b:
        label_b = f"{self._label_b + ' ' if self._label_b else ''}L{lap_b.get('lap_no', '')}"
        _plot(lap_b, f"B:{label_b}", colors["b"], ch, p, offset_x=offset_apply)
```

---

## 変更 4 — `MainWindow` にツールバーボタンと比較CSV読込メソッドを追加

### 4-a. ツールバー (`_build_toolbar` 相当箇所) に "📂 比較CSV" ボタンを追加

`btn_open_csv` (「📂 CSVを開く」ボタン) の定義直後に追記:

```python
btn_compare_csv = QPushButton("📂 比較CSV")
btn_compare_csv.setFixedHeight(28)
btn_compare_csv.setToolTip("2人目ライダーのCSVを追加して波形を重ねて表示")
btn_compare_csv.setStyleSheet(
    "QPushButton { background: #5C2D91; color: white; padding: 4px 10px;"
    " border-radius: 4px; font-weight: bold; }"
    "QPushButton:hover { background: #4A2175; }"
)
btn_compare_csv.clicked.connect(self._open_csv_compare)
tb_lay.addWidget(btn_compare_csv)
```

### 4-b. `_open_csv()` に `set_label_a()` 呼び出しを追加

`_open_csv()` 内、`parsed = self._parse_filename(stem)` の直後に追加:

```python
self._tab_wave.set_label_a(parsed.get("rider", ""))
```

### 4-c. 新メソッド `_open_csv_compare()` を `_open_csv()` の直後に追加

```python
def _open_csv_compare(self) -> None:
    """比較ライダーのCSVを読み込み、WaveformView に渡す。"""
    import pandas as pd
    import numpy as np

    default = str(Path.home() / "Desktop" / "Data TS24 Claude" / "06_CSV")
    path, _ = QFileDialog.getOpenFileName(
        self, "比較CSVファイルを選択", default,
        "CSV files (*.csv);;All files (*)"
    )
    if not path:
        return

    stem = Path(path).stem
    parsed = self._parse_filename(stem)
    label_b = parsed.get("rider", stem[:8])

    try:
        # ── CSV 読み込み（CsvImportTab と同じ文字コード試行）──────────
        df = None
        for enc in ("utf-8-sig", "shift-jis", "utf-8"):
            try:
                df = pd.read_csv(
                    path, sep=None, engine="python",
                    encoding=enc, header=0, skiprows=[1], dtype=str,
                )
                break
            except Exception:
                continue
        if df is None:
            QMessageBox.critical(self, "読込失敗", "CSV を読み込めませんでした。")
            return

        # カンマ小数点 → ドット変換 + 数値化
        df = df.apply(
            lambda col: pd.to_numeric(
                col.str.replace(",", ".", regex=False), errors="coerce"
            )
        )

        # ── チャンネル自動検出（CsvImportTab.CHANNEL_MAP と同一）────
        CHANNEL_MAP = {
            "time":       ["time", "time2d"],
            "distance":   ["dist", "distance"],
            "speed":      ["speed_front", "speed"],
            "brake":      ["brake_front"],
            "gas":        ["gas", "gas_smooth", "tps"],
            "susp_front": ["susp_front"],
            "susp_rear":  ["susp_rear"],
            "lean_angle": ["bike_angle", "lean_angle"],
        }
        cols_lower = {c.lower(): c for c in df.columns}
        col_map: dict[str, str] = {}
        for ch, aliases in CHANNEL_MAP.items():
            for alias in aliases:
                if alias in cols_lower:
                    col_map[ch] = cols_lower[alias]
                    break

        if "time" not in col_map:
            QMessageBox.warning(self, "チャンネル不足", "Time 列が検出できませんでした。")
            return

        t_raw = df[col_map["time"]].values

        # ── x_mode 判定 ────────────────────────────────────────────
        d_raw = None
        x_mode = "time"
        if "distance" in col_map:
            d_raw = df[col_map["distance"]].values
            if float(np.nanmax(d_raw)) > 10.0:
                x_mode = "distance"

        # ── 時間ギャップでセグメント分割 ──────────────────────────
        segments: list[tuple[int, int]] = []
        seg_start = 0
        for i in range(1, len(t_raw)):
            if (t_raw[i] - t_raw[i - 1]) > 5.0:
                segments.append((seg_start, i - 1))
                seg_start = i
        segments.append((seg_start, len(t_raw) - 1))

        # ── ラップデータ生成（1セグメント = 1ラップとして扱う）──────
        laps_b: list[dict] = []
        for lap_no, (s_start, s_end) in enumerate(segments, 1):
            if s_end - s_start < 10:
                continue
            if x_mode == "distance" and d_raw is not None:
                x_vals = d_raw[s_start:s_end + 1].tolist()
            else:
                x_vals = t_raw[s_start:s_end + 1].tolist()

            ch_data: dict[str, list] = {"x": x_vals}
            for ch in ["speed", "brake", "gas", "susp_front", "susp_rear", "lean_angle"]:
                if ch in col_map:
                    ch_data[ch] = df[col_map[ch]].iloc[s_start:s_end + 1].tolist()

            lt = float(t_raw[s_end]) - float(t_raw[s_start]) if x_mode == "time" else None
            laps_b.append({
                "lap_no":     lap_no,
                "lap_time_s": round(lt, 3) if lt else None,
                "x_mode":     x_mode,
                "channels":   ch_data,
                "source_file": path,
            })

        if not laps_b:
            QMessageBox.warning(self, "読込失敗", "ラップデータが検出できませんでした。")
            return

        self._tab_wave.set_compare_laps(laps_b, label_b)
        self._lbl_status.setText(
            f"比較CSV: {Path(path).name}  |  Rider B: {label_b}  |  {len(laps_b)} セグメント"
        )

    except Exception as e:
        QMessageBox.critical(self, "CSV読込エラー", str(e))
```

---

## 変更 5 — `set_laps()` に `_update_combo_b()` 呼び出しを追加

`WaveformView.set_laps()` の末尾（`self._laps_cache = laps` の後）に追記:

```python
# プライマリCSVが更新されたとき、比較CSVがなければ _combo_b も同期更新
if not self._laps_cache_b:
    self._update_combo_b()
```

---

## 動作確認手順

1. `python3 -m py_compile ts24_workbench.py` で構文チェック
2. Workbench 起動
3. 「📂 CSVを開く」で DA77 の RACE1 CSV を読み込み → 波形に送る
4. 「📂 比較CSV」（紫ボタン）で JA52 の CSV を選択
5. 波形タブで Lap A（DA77）と Lap B（JA52）が **青とオレンジ** で重ねて表示されることを確認
6. 「Bオフセット」スピンボックスを操作して波形がスライドすることを確認
7. 「↺」でオフセット 0 にリセット、「✕ 比較解除」でオレンジ線が消えることを確認

---

## 注意事項

- `_combo_b` が `_laps_cache_b` 優先になるが、**比較CSVなし時は従来通り**（同CSVの別ラップ比較）
- `_offset_spin` は `x_mode == "time"` のときのみ有効（distance/progress モードでは offset_apply = 0.0）
- `_laps_cache_b` の lap_data フォーマットは `_laps_cache` と同一（`channels` dict + `x` key）
- `set_laps()` が呼ばれる（プライマリCSV再読込）ときは比較データはそのまま保持する

---

## 変更一覧まとめ

| # | 変更箇所 | 内容 |
|---|---------|------|
| 1a | `WaveformView.__init__` | `_laps_cache_b`, `_label_a`, `_label_b`, `_offset_b` 追加 |
| 1b | `WaveformView.__init__` sel_row | `_lbl_b_rider`, `_offset_spin`, `↺`, `✕比較解除` UI 追加 |
| 2 | `WaveformView` 新メソッド | `set_label_a`, `set_compare_laps`, `clear_compare`, `_on_offset_changed`, `_update_combo_b` |
| 3a | `_draw()` | lap_b 取得元と pen_b カラー（オレンジ / 赤 切り替え）|
| 3b | `_draw()._plot()` | `offset_x: float = 0.0` 引数追加、x 軸にオフセット適用 |
| 3c | `_draw()` 呼び出し部 | ライダー名付きラベル + B に `offset_apply` 渡す |
| 4a | `MainWindow` ツールバー | 紫「📂 比較CSV」ボタン追加 |
| 4b | `_open_csv()` | `set_label_a(parsed.get("rider",""))` 呼び出し追加 |
| 4c | `MainWindow` 新メソッド | `_open_csv_compare()` 追加 |
| 5 | `WaveformView.set_laps()` | 比較CSVなし時に `_update_combo_b()` 呼び出し追加 |
