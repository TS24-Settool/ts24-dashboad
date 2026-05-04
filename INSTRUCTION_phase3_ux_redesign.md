# Claude Code 実装指示書
# タスク: UX刷新 Phase 3 — スプリットビュー + チャンネル選択 + 左サイドバー削除
# 対象ファイル: 05_SCRIPTS/ts24_workbench.py
# 前提: Phase 2（waveform → Problem Log 自動入力）実装済み（commit cfec244）
# 作成: Cowork Claude / 2026-05-04

---

## 背景・目的

現状の問題点：
1. 左サイドバー（DB走行ツリー）が邪魔で、本来のワークフロー「CSV読込 → 波形分析 → 記録」を妨げている
2. 波形タブで範囲を選択してProblem Logへ送ると、波形が見えなくなる（タブ切替）
3. 表示チャンネルを選択できない

目標ワークフロー：
```
📂 CSVを開く（ファイルダイアログ）
↓
波形表示（チャンネル選択可）
↓
LinearRegionItem で範囲選択 →「Problem Log へ送る」
↓
右パネルがスライドイン（波形はそのまま表示）
↓
Corner / Phase / Tag / Description を入力 →「追加」
↓
DBに保存 + Problem Log テーブル更新
```

---

## 変更一覧

| # | 対象クラス | 内容 |
|---|----------|------|
| 変更1 | `MainWindow` | 左サイドバー削除 + 上部ツールバー化 |
| 変更2 | `CsvImportTab` | `load_file(path)` メソッド追加 |
| 変更3 | `WaveformView` | `GraphicsLayoutWidget` → 個別 `PlotWidget` に変更（show/hide対応） |
| 変更4 | `WaveformView` | チャンネルチェックボックス追加 |
| 変更5 | `WaveformView` | 右パネル（`_ProblemRightPanel`）+ QSplitter 化 |
| 変更6 | `_ProblemRightPanel` | 新クラス追加 — フォーム + DB保存 |
| 変更7 | `MainWindow` | 右パネルへ `set_run()` / `set_problem_tab()` を渡す |

---

## 変更1: `MainWindow` — 左サイドバー削除 + 上部ツールバー

### 削除するもの
- `left = QWidget()` とその中身すべて（title ラベル / circuit combo / tree / status label）
- `self._tree = QTreeWidget()`
- `_on_run_selected()` メソッド
- 外側の `QSplitter(left, self._tabs)` ラッパー

### 維持（簡略化）するもの
- `_on_circuit_changed()` — ツリー更新を削除し、`set_circuit()` 呼び出しのみに簡略化
- `_load_circuits()` — コンボボックスへの回路リスト追加は維持

### 追加するもの

```python
def _setup_ui(self):
    central = QWidget()
    self.setCentralWidget(central)
    root = QVBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # ── 上部ツールバー ──────────────────────────────────
    toolbar = QWidget()
    toolbar.setFixedHeight(40)
    toolbar.setStyleSheet("background: #1E1E1E; border-bottom: 1px solid #333;")
    tb_lay = QHBoxLayout(toolbar)
    tb_lay.setContentsMargins(8, 4, 8, 4)

    lbl_title = QLabel("TS24 Engineer Workbench")
    lbl_title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
    lbl_title.setStyleSheet("color: #FFFFFF;")
    tb_lay.addWidget(lbl_title)

    tb_lay.addWidget(QLabel("  Circuit:"))
    self._combo_circuit = QComboBox()
    self._combo_circuit.setFixedWidth(120)
    self._combo_circuit.setToolTip("テンプレート（コーナーマーカー）に使用")
    self._combo_circuit.currentTextChanged.connect(self._on_circuit_changed)
    tb_lay.addWidget(self._combo_circuit)

    btn_open_csv = QPushButton("📂  CSVを開く")
    btn_open_csv.setFixedHeight(28)
    btn_open_csv.setStyleSheet(
        "QPushButton { background: #0078D4; color: white; border-radius: 4px; padding: 0 12px; }"
        "QPushButton:hover { background: #106EBE; }"
    )
    btn_open_csv.clicked.connect(self._open_csv)
    tb_lay.addWidget(btn_open_csv)

    tb_lay.addStretch()

    self._lbl_status = QLabel("")
    self._lbl_status.setStyleSheet("color: #888; font-size: 10px;")
    tb_lay.addWidget(self._lbl_status)

    root.addWidget(toolbar)

    # ── タブエリア ────────────────────────────────────
    self._tabs = QTabWidget()
    self._tab_wave    = WaveformView()
    self._tab_problem = ProblemLogTab(db=self._db)
    self._tab_setup   = SetupDecisionTab(db=self._db)
    self._tab_csv     = CsvImportTab(wave_view=self._tab_wave, db=self._db)
    self._tab_wave.set_problem_tab(self._tab_problem)
    self._tabs.addTab(self._tab_wave,    "📊 波形 (Reference)")
    self._tabs.addTab(self._tab_problem, "⚠️  Problem Log")
    self._tabs.addTab(self._tab_setup,   "🔧 Setup Decision")
    self._tabs.addTab(self._tab_csv,     "📂 2D CSV")

    root.addWidget(self._tabs)

    self._load_circuits()
```

### `_open_csv()` メソッドを追加

```python
def _open_csv(self):
    """ファイルダイアログでCSVを選択し、2D CSVタブで読み込んで波形に送る。"""
    from PyQt6.QtWidgets import QFileDialog
    path, _ = QFileDialog.getOpenFileName(
        self, "CSVファイルを選択", str(Path.home()),
        "CSV files (*.csv);;All files (*)"
    )
    if not path:
        return
    self._lbl_status.setText(f"読込中: {Path(path).name}")
    try:
        self._tab_csv.load_file(path)
        self._tabs.setCurrentWidget(self._tab_wave)
        self._lbl_status.setText(f"読込完了: {Path(path).name}")
    except Exception as e:
        self._lbl_status.setText(f"エラー: {e}")
```

### `_on_circuit_changed()` を簡略化（ツリー更新なし）

```python
def _on_circuit_changed(self, circuit: str):
    """サーキット変更 — テンプレート適用のみ（ツリー更新なし）。"""
    self._tab_wave.set_circuit(circuit)
```

※ `WaveformView.set_circuit()` は現在存在しないため、**変更3 で追加する**（後述）。

### `_load_circuits()` を維持（コンボボックス用）

```python
def _load_circuits(self):
    try:
        circuits = self._db.get_circuits()
    except Exception:
        circuits = []
    self._combo_circuit.blockSignals(True)
    self._combo_circuit.clear()
    self._combo_circuit.addItems(circuits)
    self._combo_circuit.blockSignals(False)
    if circuits:
        self._on_circuit_changed(circuits[0])
```

---

## 変更2: `CsvImportTab` — `load_file()` メソッド追加

既存の CSV 読み込みフローは次の順序：
1. `_open_file()` → ファイルダイアログ → `_load_csv(path)` で `self._df` をセット
2. ユーザーが「波形に送る」ボタン → `_send()` でラップ分割 + 波形更新

外部から呼ぶ `load_file()` はこの2段階を自動で行う：

```python
def load_file(self, path: str) -> None:
    """外部から CSV パスを渡して即読み込みを実行する。"""
    p = Path(path)
    self._lbl_file.setText(p.name)
    # run_id を CSV ファイル名から生成（DB未登録の場合の fallback）
    if not self._run_id:
        self._run_id = p.stem  # 例: "DA77_R1_ASSEN_FP"
    self._load_csv(p)          # self._df をセット
    if self._df is not None:   # 読み込み成功時のみ
        self._send()           # ラップ分割 + 波形へ送信
```

---

## 変更3: `WaveformView` — 個別 `PlotWidget` に変更 + `set_circuit()` 追加

### `set_circuit()` メソッドを追加（`_on_circuit_changed()` から呼ばれる）

`WaveformView` クラスに以下を追加：

```python
def set_circuit(self, circuit: str) -> None:
    """サーキット名をセット（コーナーテンプレート適用用）。"""
    self._circuit = circuit
```

既存の `set_run(run_id, circuit)` は circuit も更新しているが、
run_id なしでサーキットだけ更新するケース（ツールバーのコンボ変更時）のために追加する。

### 目的
`GraphicsLayoutWidget` のまま行単位 show/hide は困難なため、
個別の `pg.PlotWidget` を `QVBoxLayout` に並べる方式に変更する。
X軸リンク・LinearRegionItem はそのまま維持できる。

### `_setup_ui()` 内のグラフ初期化部分を置き換え

**削除:**
```python
self._plot_widget = pg.GraphicsLayoutWidget()
self._p_speed  = self._plot_widget.addPlot(row=0, col=0, title="Speed (km/h)")
self._p_brake  = self._plot_widget.addPlot(row=1, col=0, title="Brake (bar)")
self._p_gas    = self._plot_widget.addPlot(row=2, col=0, title="Gas (%)")
self._p_suspf  = self._plot_widget.addPlot(row=3, col=0, title="SUSP_FRONT (mm)")
self._p_suspr  = self._plot_widget.addPlot(row=4, col=0, title="SUSP_REAR (mm)")
```

**追加（代替）:**
```python
# 個別 PlotWidget — show/hide 対応
self._pw_speed = pg.PlotWidget(title="Speed (km/h)")
self._pw_brake = pg.PlotWidget(title="Brake (bar)")
self._pw_gas   = pg.PlotWidget(title="Gas (%)")
self._pw_suspf = pg.PlotWidget(title="SUSP_FRONT (mm)")
self._pw_suspr = pg.PlotWidget(title="SUSP_REAR (mm)")

# 高さ比率設定
self._pw_speed.setMinimumHeight(120)
self._pw_brake.setMinimumHeight(80)
self._pw_gas.setMinimumHeight(80)
self._pw_suspf.setMinimumHeight(80)
self._pw_suspr.setMinimumHeight(80)

# X軸リンク
for pw in [self._pw_brake, self._pw_gas, self._pw_suspf, self._pw_suspr]:
    pw.setXLink(self._pw_speed)

# 後方互換: _p_speed 等のエイリアスを維持
self._p_speed = self._pw_speed.getPlotItem()
self._p_brake = self._pw_brake.getPlotItem()
self._p_gas   = self._pw_gas.getPlotItem()
self._p_suspf = self._pw_suspf.getPlotItem()
self._p_suspr = self._pw_suspr.getPlotItem()

# _all_plots: PlotWidget のタプル（.clear() / .plot() / .enableAutoRange() 対応）
self._all_plots = (
    self._pw_speed, self._pw_brake, self._pw_gas,
    self._pw_suspf, self._pw_suspr
)

# LinearRegionItem
self._region = pg.LinearRegionItem(
    values=[0, 100],
    brush=pg.mkBrush(0, 120, 212, 30),
    pen=pg.mkPen("#0078D4", width=1.5),
    movable=True,
)
self._region.setZValue(10)
self._pw_speed.addItem(self._region)

# スクロールエリアに PlotWidget を縦積み
self._wave_scroll = QScrollArea()
self._wave_scroll.setWidgetResizable(True)
self._wave_container = QWidget()
self._wave_vlay = QVBoxLayout(self._wave_container)
self._wave_vlay.setSpacing(0)
self._wave_vlay.setContentsMargins(0, 0, 0, 0)
for pw in [self._pw_speed, self._pw_brake, self._pw_gas, self._pw_suspf, self._pw_suspr]:
    self._wave_vlay.addWidget(pw)
self._wave_scroll.setWidget(self._wave_container)
```

### `_redraw()` 内の `p.clear()` 後に `_region` 再追加

既存の修正（commit e45b454）を維持：
```python
for p in self._all_plots:
    p.clear()
self._pw_speed.addItem(self._region)   # 再追加
```

※ `_all_plots` が PlotWidget になったので `p.clear()` は
`PlotWidget.clear()` を呼ぶ（内部的に `getPlotItem().clear()` に等しい）。

### `_redraw()` 内の `p.plot(...)` について
`PlotWidget.plot(x=xs, y=ys, pen=pen, name=label)` は変更なしで動作する。

---

## 変更4: `WaveformView` — チャンネルチェックボックス

### ツールバーにチェックボックスを追加

既存のツールバー（Lap A / Lap B / 表示更新 / Problem Log へ送る）の行に追記：

```python
# チャンネル表示チェックボックス
ch_label = QLabel("  チャンネル:")
ch_label.setStyleSheet("color: #AAA; font-size: 10px;")
toolbar.addWidget(ch_label)

self._ch_checks: dict[str, tuple[QCheckBox, pg.PlotWidget]] = {}
for ch_name, pw in [
    ("Speed",      self._pw_speed),
    ("Brake",      self._pw_brake),
    ("Gas",        self._pw_gas),
    ("SUSP_F",     self._pw_suspf),
    ("SUSP_R",     self._pw_suspr),
]:
    cb = QCheckBox(ch_name)
    cb.setChecked(True)
    cb.setStyleSheet("font-size: 10px;")
    cb.toggled.connect(lambda checked, w=pw: w.setVisible(checked))
    toolbar.addWidget(cb)
    self._ch_checks[ch_name] = (cb, pw)
```

※ `PlotWidget.setVisible(False)` で該当チャンネルのグラフが非表示になり、
他のチャンネルが空いたスペースを占有する。X軸リンクは維持される。

---

## 変更5: `WaveformView` — 右パネル + QSplitter 化

### レイアウト変更

`WaveformView._setup_ui()` のメインエリアを `QSplitter` に変更：

```python
# 波形エリア + 右パネルの水平 Splitter
self._wave_splitter = QSplitter(Qt.Orientation.Horizontal)

# 左: 波形スクロールエリア（変更3 で作成済みの self._wave_scroll）
self._wave_splitter.addWidget(self._wave_scroll)

# 右: Problem Log 入力パネル（初期は非表示）
self._right_panel = _ProblemRightPanel(
    db=self._db_ref,          # NOTE: WaveformView は db 参照を保持する必要がある（変更7 参照）
    on_close=self._close_right_panel,
)
self._wave_splitter.addWidget(self._right_panel)
self._wave_splitter.setStretchFactor(0, 3)
self._wave_splitter.setStretchFactor(1, 1)
self._wave_splitter.setSizes([1, 0])   # 初期: 右パネルを幅0で非表示

layout.addWidget(self._wave_splitter)
```

### `_send_to_problem_log()` を変更（タブ切替 → 右パネル表示）

```python
def _send_to_problem_log(self) -> None:
    # ... 既存の data dict 構築ロジックは変更なし ...
    
    # 右パネルに prefill（タブ切替ではなく右パネルを開く）
    self._right_panel.prefill_from_waveform(data)
    self._open_right_panel()
    
    # Problem Log タブの prefill も維持（互換性のため）
    if self._problem_tab:
        self._problem_tab.prefill_from_waveform(data)
```

### `_open_right_panel()` / `_close_right_panel()` を追加

```python
def _open_right_panel(self) -> None:
    total = self._wave_splitter.width()
    self._wave_splitter.setSizes([int(total * 0.65), int(total * 0.35)])

def _close_right_panel(self) -> None:
    total = self._wave_splitter.width()
    self._wave_splitter.setSizes([total, 0])
```

### `WaveformView.__init__()` に `db` を受け取る

```python
class WaveformView(QWidget):
    def __init__(self, db: WorkbenchDB | None = None):
        super().__init__()
        self._db_ref = db          # 右パネルに渡す
        self._problem_tab: ProblemLogTab | None = None
        # ... 既存の初期化 ...
```

---

## 変更6: `_ProblemRightPanel` — 新クラス追加

`ProblemLogTab` クラスの直前に追加する。

```python
class _ProblemRightPanel(QWidget):
    """波形タブ右側に表示する Problem Log 入力パネル。"""

    def __init__(self, db: WorkbenchDB, on_close):
        super().__init__()
        self._db = db
        self._on_close = on_close     # コールバック: WaveformView._close_right_panel
        self._wave_prefill: dict = {}
        self._run_meta: dict = {}
        self._problem_tab_ref: "ProblemLogTab | None" = None
        self._setup_ui()

    def set_problem_tab(self, tab: "ProblemLogTab") -> None:
        self._problem_tab_ref = tab

    def set_run(self, run_id: str, meta: dict) -> None:
        self._run_meta = meta

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(4)
        self.setStyleSheet("background: #1A1A2E;")

        # ── ヘッダー ─────────────────────────────
        hdr = QHBoxLayout()
        lbl_hdr = QLabel("📋 Problem Log")
        lbl_hdr.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        lbl_hdr.setStyleSheet("color: #FFF;")
        btn_close = QPushButton("×")
        btn_close.setFixedSize(20, 20)
        btn_close.setStyleSheet(
            "QPushButton { background: #444; color: #CCC; border-radius: 2px; }"
            "QPushButton:hover { background: #C00; color: #FFF; }"
        )
        btn_close.clicked.connect(self._on_close)
        hdr.addWidget(lbl_hdr)
        hdr.addStretch()
        hdr.addWidget(btn_close)
        lay.addLayout(hdr)

        # ── 波形 auto-fill ボックス ───────────────
        self._wave_info_box = QFrame()
        self._wave_info_box.setFrameShape(QFrame.Shape.Box)
        self._wave_info_box.setStyleSheet(
            "background: #001830; border: 1px solid #0078D4; border-radius: 4px;"
        )
        wave_info_lay = QVBoxLayout(self._wave_info_box)
        wave_info_lay.setContentsMargins(6, 4, 6, 4)
        wave_info_lay.setSpacing(2)
        lbl_wave_title = QLabel("📊 波形から自動入力（読み取り専用）")
        lbl_wave_title.setStyleSheet("color: #4FC3F7; font-size: 10px; font-weight: bold;")
        wave_info_lay.addWidget(lbl_wave_title)
        self._lbl_auto_run   = QLabel("Run: —")
        self._lbl_auto_lap   = QLabel("Lap: —")
        self._lbl_auto_range = QLabel("Range: —")
        for lbl in [self._lbl_auto_run, self._lbl_auto_lap, self._lbl_auto_range]:
            lbl.setStyleSheet("color: #B0BEC5; font-size: 10px;")
            wave_info_lay.addWidget(lbl)
        btn_clear_wave = QPushButton("✕ 自動入力をクリア")
        btn_clear_wave.setFixedHeight(20)
        btn_clear_wave.setStyleSheet("font-size: 10px; color: #888; background: transparent;")
        btn_clear_wave.clicked.connect(self._clear_wave_prefill)
        wave_info_lay.addWidget(btn_clear_wave)
        self._wave_info_box.setVisible(False)
        lay.addWidget(self._wave_info_box)

        # ── フォーム ──────────────────────────────
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(4)

        self._spin_lap = QSpinBox()
        self._spin_lap.setRange(0, 99)
        form.addRow("Lap No:", self._spin_lap)

        self._combo_corner = QComboBox()
        self._combo_corner.addItem("NONE")
        for i in range(1, 20):
            self._combo_corner.addItem(f"T{i}")
        form.addRow("Corner:", self._combo_corner)

        self._combo_phase = QComboBox()
        self._combo_phase.addItems(PHASES)
        form.addRow("Phase:", self._combo_phase)

        self._combo_tag = QComboBox()
        self._combo_tag.addItems(PROBLEM_TAGS)
        form.addRow("Problem Tag:", self._combo_tag)

        self._txt_desc = QTextEdit()
        self._txt_desc.setFixedHeight(80)
        self._txt_desc.setPlaceholderText("詳細説明（任意）")
        form.addRow("Description:", self._txt_desc)

        self._combo_sev = QComboBox()
        self._combo_sev.addItems(SEVERITIES)
        form.addRow("Severity:", self._combo_sev)

        self._combo_src = QComboBox()
        self._combo_src.addItems(SOURCES)
        form.addRow("Source:", self._combo_src)

        lay.addLayout(form)

        # ── ボタン行 ─────────────────────────────
        btn_row = QHBoxLayout()
        btn_add = QPushButton("追加")
        btn_add.setStyleSheet(
            "QPushButton { background: #107C10; color: white; border-radius: 4px; padding: 4px 16px; }"
            "QPushButton:hover { background: #0E6B0E; }"
        )
        btn_add.clicked.connect(self._add_entry)
        btn_clear = QPushButton("クリア")
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        lay.addLayout(btn_row)
        lay.addStretch()

    # ── Public API ──────────────────────────────────────

    def prefill_from_waveform(self, data: dict) -> None:
        self._wave_prefill = data
        run_id = data.get("run_id") or "—"
        self._lbl_auto_run.setText(f"Run: {run_id}")
        self._lbl_auto_lap.setText(f"Lap: {data.get('lap_no', '—')}")

        # Range 表示
        ds = data.get("distance_start_m")
        de = data.get("distance_end_m")
        ts = data.get("time_start_s")
        te = data.get("time_end_s")
        if ds is not None and de is not None:
            span = round(de - ds, 1)
            self._lbl_auto_range.setText(f"Range: {ds}m → {de}m ({span}m)")
        elif ts is not None and te is not None:
            span = round(te - ts, 2)
            self._lbl_auto_range.setText(f"Range: {ts}s → {te}s ({span}s)")
        else:
            self._lbl_auto_range.setText("Range: —")

        self._wave_info_box.setVisible(True)
        # Lap スピンボックスを自動設定
        lap_no = data.get("lap_no")
        if lap_no is not None:
            self._spin_lap.setValue(int(lap_no))
        # Source を DATA に自動設定
        idx = self._combo_src.findText("DATA")
        if idx >= 0:
            self._combo_src.setCurrentIndex(idx)

    # ── Private ─────────────────────────────────────────

    def _clear_wave_prefill(self) -> None:
        self._wave_prefill = {}
        self._lbl_auto_run.setText("Run: —")
        self._lbl_auto_lap.setText("Lap: —")
        self._lbl_auto_range.setText("Range: —")
        self._wave_info_box.setVisible(False)

    def _clear_form(self) -> None:
        self._spin_lap.setValue(1)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()

    def _add_entry(self) -> None:
        wp = self._wave_prefill
        meta = self._run_meta

        run_id = wp.get("run_id") or meta.get("run_id") or ""
        if not run_id:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "警告", "Run が未設定です。CSVを先に読み込んでください。")
            return

        data = {
            "run_id":            run_id,
            "round":             meta.get("round"),
            "circuit":           meta.get("circuit"),
            "session":           meta.get("session"),
            "rider":             meta.get("rider"),
            "run_no":            meta.get("run_no"),
            "lap_no":            self._spin_lap.value() or None,
            "corner":            self._combo_corner.currentText(),
            "phase":             self._combo_phase.currentText(),
            "problem_tag":       self._combo_tag.currentText(),
            "description":       self._txt_desc.toPlainText().strip(),
            "severity":          self._combo_sev.currentText(),
            "source":            self._combo_src.currentText(),
            # 波形から自動入力された座標
            "distance_start_m":  wp.get("distance_start_m"),
            "distance_end_m":    wp.get("distance_end_m"),
            "time_start_s":      wp.get("time_start_s"),
            "time_end_s":        wp.get("time_end_s"),
            "data_source_file":  wp.get("data_source_file"),
            "analysis_note":     None,
        }

        try:
            self._db.add_problem_log(data)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "DB Error", str(e))
            return

        self._clear_form()
        self._clear_wave_prefill()

        # Problem Log タブのテーブルを更新
        if self._problem_tab_ref:
            self._problem_tab_ref._refresh_table()
```

---

## 変更7: `MainWindow` — 配線更新

```python
def _setup_ui(self):
    # ... 変更1 のコードに加えて ...
    
    # WaveformView に db を渡す（変更5 で必要）
    self._tab_wave = WaveformView(db=self._db)
    self._tab_problem = ProblemLogTab(db=self._db)
    self._tab_setup   = SetupDecisionTab(db=self._db)
    self._tab_csv     = CsvImportTab(wave_view=self._tab_wave, db=self._db)
    
    # 右パネルへの参照を渡す
    self._tab_wave.set_problem_tab(self._tab_problem)
    self._tab_wave._right_panel.set_problem_tab(self._tab_problem)
```

### `_on_csv_loaded()` コールバックを CsvImportTab に追加（オプション）

CSV読み込み後に run_meta を全タブに伝播させるため、
`CsvImportTab._send()` の成功時に `on_loaded` コールバックを呼ぶ方式を採用する。

```python
# CsvImportTab.__init__ に追加
self._on_loaded: callable | None = None

# CsvImportTab._send() の最後（成功時）に追加
if self._on_loaded:
    meta = {
        "run_id":  self._run_id,
        "circuit": self._wave_view._circuit,
    }
    self._on_loaded(meta)
```

```python
# MainWindow._setup_ui() に追加
self._tab_csv._on_loaded = self._on_csv_loaded

def _on_csv_loaded(self, meta: dict) -> None:
    run_id = meta.get("run_id", "")
    self._lbl_status.setText(f"Loaded: {run_id}")
    self._tab_problem.set_run(run_id, meta)
    self._tab_setup.set_run(run_id, meta)
    self._tab_wave._right_panel.set_run(run_id, meta)
```

---

## NG 条件

| 症状 | 原因 |
|------|------|
| グラフが表示されない | `_all_plots` が PlotWidget でなく PlotItem になっている / `_wave_scroll` がレイアウトに追加されていない |
| チェックボックスで非表示にしても高さが残る | `PlotWidget.setVisible(False)` ではなく `PlotItem.setVisible()` を呼んでいる |
| 右パネルが開かない | `_wave_splitter.setSizes([0, 1])` の値が逆 / `_right_panel` が `_wave_splitter` に追加されていない |
| 右パネルの「追加」でエラー | `_run_meta` が空 / `run_id` が未設定 → `_on_csv_loaded` が呼ばれていない |
| X軸リンクが切れる | `PlotWidget.setXLink()` ではなく `getPlotItem().setXLink()` を使う（どちらでも可だが統一する） |
| LinearRegionItem が消える | `_redraw()` で `_pw_speed.addItem(self._region)` の再追加が漏れている |

---

## Git コミットメッセージ

```
feat: Phase 3 UX redesign — split view + channel selector + remove sidebar

- remove: left sidebar (run tree + circuit combo in left panel)
- add: compact top toolbar with circuit combo + "📂 CSVを開く" button
- add: CsvImportTab.load_file(path) for external CSV loading
- change: GraphicsLayoutWidget → individual PlotWidgets (show/hide support)
- add: channel checkboxes (Speed/Brake/Gas/SUSP_F/SUSP_R) in waveform toolbar
- add: _ProblemRightPanel — Problem Log form as collapsible right panel
- add: QSplitter in WaveformView (waveform left / form right)
- add: "送る" opens right panel instead of switching tabs
- add: _on_csv_loaded callback propagates run_meta to all tabs
- result: waveform visible while logging problems, channel selection available
```
