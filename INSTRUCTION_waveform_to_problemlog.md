# Claude Code 実装指示書
# タスク: 波形選択範囲 → Problem Log 自動連携（Phase 2）
# 対象ファイル: 05_SCRIPTS/ts24_workbench.py
# 前提: INSTRUCTION_distance_lap_split.md（v2）実装済み
# 作成: Cowork Claude / 2026-05-04

---

## 背景・目的

現状の Problem Log タブは「手入力フォーム」であり、Workbenchとしての価値が出ていない。
波形タブで選んだ区間を Problem Log に自動入力することで、ワークフローが完成する。

**目標ワークフロー:**
```
波形タブで LinearRegionItem を使って区間選択
↓
「📋 Problem Log へ送る」ボタンを押す
↓
Problem Log タブに自動切替 + 以下が自動入力済み:
  run_id / lap_no / time_start_s / time_end_s / distance_start_m / distance_end_m / data_source_file
↓
Tatsuki は corner / phase / tag / description だけ入力して「追加」
```

**重要制約:** 問題内容（タグ・フェーズ・説明）は自動で決めない。
自動入力するのは「どのRun / Lap / 範囲か」の座標情報のみ。

---

## 変更1: `WaveformView.__init__` に `_problem_tab` 参照を追加

`WaveformView` が `ProblemLogTab` を直接呼び出せるように参照を保持する。

**`WaveformView.__init__` の末尾（`_setup_ui()` の前後）に追加:**
```python
        self._problem_tab: "ProblemLogTab | None" = None   # ← 追加
        self._run_id_wave: str = ""                         # ← 追加（波形側のrun_id）
        self._setup_ui()
```

**`set_problem_tab()` メソッドを `WaveformView` に追加:**
```python
    def set_problem_tab(self, tab: "ProblemLogTab") -> None:
        """MainWindow から呼ばれ、Problem Log タブへの参照を設定する。"""
        self._problem_tab = tab
```

**`set_run()` の先頭に run_id 保存を追加:**
```python
    def set_run(self, run_id: str, circuit: str):
        self._run_id_wave = run_id   # ← 追加（この行を先頭に追加）
        self._circuit = circuit
        ...
```

---

## 変更2: `WaveformView._setup_ui()` に LinearRegionItem と送信ボタンを追加

### 2a. LinearRegionItem の追加

`_p_speed`, `_p_brake` など全パネルを生成した後の、
`layout.addWidget(self._plot_widget)` の**直前**に以下を挿入:

```python
            # ── LinearRegionItem（選択範囲）────────────────────────
            # Speed パネルに追加し、X リンクで全パネルに反映される
            self._region = pg.LinearRegionItem(
                values=[0.2, 0.4],
                brush=pg.mkBrush(0, 120, 212, 30),    # 薄い青
                pen=pg.mkPen("#0078D4", width=1.5),
                movable=True,
            )
            self._region.setZValue(10)
            self._p_speed.addItem(self._region)
```

### 2b. 「Problem Log へ送る」ボタンの追加

**`sel_row` レイアウト（Lap A/B のコンボボックス行）の末尾、`sel_row.addStretch()` の直前に追加:**

```python
        btn_send_log = QPushButton("📋  Problem Log へ送る")
        btn_send_log.setToolTip(
            "選択範囲（青いハイライト）の座標情報を Problem Log に自動入力します。\n"
            "Lap A の run_id / lap_no / time / distance が入力されます。"
        )
        btn_send_log.setStyleSheet(
            "QPushButton { background: #107C10; color: white; padding: 4px 12px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #0D6A0D; }"
        )
        btn_send_log.clicked.connect(self._send_to_problem_log)
        sel_row.addSpacing(24)
        sel_row.addWidget(btn_send_log)
```

---

## 変更3: `WaveformView._send_to_problem_log()` メソッドを追加

**`_draw()` メソッドの直前に挿入。**

```python
    def _send_to_problem_log(self) -> None:
        """選択範囲の座標情報を ProblemLogTab に送り、自動入力させる。"""
        if self._problem_tab is None:
            QMessageBox.warning(self, "未接続", "Problem Log タブが接続されていません。")
            return
        if not self._laps_cache:
            QMessageBox.warning(self, "データなし", "波形データがありません。先に CSV を送信してください。")
            return

        ia = self._combo_a.currentIndex()
        if ia < 0 or ia >= len(self._laps_cache):
            QMessageBox.warning(self, "Lap未選択", "Lap A を選択してください。")
            return

        lap_a = self._laps_cache[ia]
        x_start, x_end = self._region.getRegion()

        # x_start < x_end を保証
        if x_start > x_end:
            x_start, x_end = x_end, x_start

        x_mode = self._csv_x_mode

        data: dict = {
            "run_id":  self._run_id_wave,
            "lap_no":  lap_a.get("lap_no"),
            "x_mode":  x_mode,
        }

        if x_mode == "distance":
            data["distance_start_m"] = round(float(x_start), 1)
            data["distance_end_m"]   = round(float(x_end),   1)
            data["time_start_s"]     = None
            data["time_end_s"]       = None
        elif x_mode == "time":
            data["time_start_s"]     = round(float(x_start), 3)
            data["time_end_s"]       = round(float(x_end),   3)
            data["distance_start_m"] = None
            data["distance_end_m"]   = None
        else:
            # progress mode: 座標値をそのまま渡す（参考値）
            data["time_start_s"]     = round(float(x_start), 4)
            data["time_end_s"]       = round(float(x_end),   4)
            data["distance_start_m"] = None
            data["distance_end_m"]   = None

        # data_source_file: CSV ファイル名があれば取得
        data["data_source_file"] = lap_a.get("source_file", "")

        # ProblemLogTab に渡して自動入力
        self._problem_tab.prefill_from_waveform(data)

        # Problem Log タブに切り替える（MainWindow の tabs を経由）
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "_tabs"):
                idx = parent._tabs.indexOf(self._problem_tab)
                if idx >= 0:
                    parent._tabs.setCurrentIndex(idx)
                break
            parent = parent.parent()
```

---

## 変更4: `ProblemLogTab._setup_ui()` に自動入力表示エリアを追加

**フォームの先頭（`form_label = QLabel("▼ 新規問題を追加")` の直後）に追加。**

```python
        # ── 波形連携: 自動入力エリア ─────────────────────────────────
        self._wave_info_box = QWidget()
        self._wave_info_box.setStyleSheet(
            "background: #EFF6FF; border: 1px solid #0078D4;"
            " border-radius: 4px; padding: 4px;"
        )
        wave_info_lay = QVBoxLayout(self._wave_info_box)
        wave_info_lay.setContentsMargins(8, 4, 8, 4)
        wave_info_lay.setSpacing(2)

        wave_header = QLabel("📊 波形から自動入力（読み取り専用）")
        wave_header.setStyleSheet("color: #0078D4; font-weight: bold; font-size: 10px;")
        wave_info_lay.addWidget(wave_header)

        self._lbl_auto_run   = QLabel("Run: —")
        self._lbl_auto_lap   = QLabel("Lap: —")
        self._lbl_auto_range = QLabel("Range: —")
        for lbl in (self._lbl_auto_run, self._lbl_auto_lap, self._lbl_auto_range):
            lbl.setStyleSheet("color: #004578; font-size: 10px;")
            wave_info_lay.addWidget(lbl)

        btn_clear_wave = QPushButton("✕ 自動入力をクリア")
        btn_clear_wave.setFixedHeight(20)
        btn_clear_wave.setStyleSheet("font-size: 10px; color: #666;")
        btn_clear_wave.clicked.connect(self._clear_wave_prefill)
        wave_info_lay.addWidget(btn_clear_wave)

        self._wave_info_box.setVisible(False)   # 初期は非表示
        layout.addWidget(self._wave_info_box)
```

**`ProblemLogTab.__init__` の `_setup_ui()` 呼び出しの前に追加:**
```python
        # 波形から自動入力された値を保持する（_add_entry で使用）
        self._wave_prefill: dict = {}
```

---

## 変更5: `ProblemLogTab` に `prefill_from_waveform()` と `_clear_wave_prefill()` を追加

**`set_run()` メソッドの直後に追加。**

```python
    def prefill_from_waveform(self, data: dict) -> None:
        """WaveformView から呼ばれ、座標情報を自動入力する。

        data キー:
          run_id, lap_no, x_mode,
          distance_start_m, distance_end_m, time_start_s, time_end_s,
          data_source_file
        """
        self._wave_prefill = data

        # run_id が Problem Log の run_id と異なる場合は警告
        run_id = data.get("run_id", "")
        if run_id and self._run_id and run_id != self._run_id:
            QMessageBox.warning(
                self,
                "Run 不一致",
                f"波形のRun ({run_id}) と\n"
                f"Problem Log のRun ({self._run_id}) が一致しません。\n"
                "左パネルで同じ Run を選択してください。",
            )
            self._wave_prefill = {}
            return

        # 自動入力エリアを更新・表示
        self._lbl_auto_run.setText(f"Run: {run_id or '—'}")
        lap_no = data.get("lap_no")
        self._lbl_auto_lap.setText(f"Lap: {lap_no if lap_no is not None else '—'}")

        x_mode = data.get("x_mode", "")
        if x_mode == "distance":
            ds = data.get("distance_start_m")
            de = data.get("distance_end_m")
            range_str = (f"{ds:.1f}m → {de:.1f}m  ({de - ds:.1f}m)"
                         if ds is not None and de is not None else "—")
        elif x_mode == "time":
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = (f"{ts:.3f}s → {te:.3f}s  ({te - ts:.3f}s)"
                         if ts is not None and te is not None else "—")
        else:
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = f"progress {ts:.4f} → {te:.4f}" if ts is not None else "—"

        self._lbl_auto_range.setText(f"Range: {range_str}")
        self._wave_info_box.setVisible(True)

        # Lap No フォームを自動入力
        if lap_no is not None:
            self._spin_lap.setValue(int(lap_no))

        # Source を DATA に設定
        if "DATA" in [self._combo_src.itemText(i) for i in range(self._combo_src.count())]:
            self._combo_src.setCurrentText("DATA")

    def _clear_wave_prefill(self) -> None:
        """波形からの自動入力をリセットする。"""
        self._wave_prefill = {}
        self._lbl_auto_run.setText("Run: —")
        self._lbl_auto_lap.setText("Lap: —")
        self._lbl_auto_range.setText("Range: —")
        self._wave_info_box.setVisible(False)
```

---

## 変更6: `ProblemLogTab._add_entry()` を更新して6列を保存

**`_add_entry()` 内の `data = { ... }` ブロックを以下に置き換える:**

```python
        data = {
            "run_id":     self._run_id,
            "round":      self._run_meta.get("round"),
            "circuit":    self._run_meta.get("circuit"),
            "session":    self._run_meta.get("session"),
            "rider":      self._run_meta.get("rider"),
            "run_no":     self._run_meta.get("run_no"),
            "lap_no":     lap_val,
            "corner":     corner_val,
            "phase":      self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":   self._combo_sev.currentText(),
            "source":     self._combo_src.currentText(),
            # 波形自動入力フィールド（あれば上書き、なければ None）
            "distance_start_m": self._wave_prefill.get("distance_start_m"),
            "distance_end_m":   self._wave_prefill.get("distance_end_m"),
            "time_start_s":     self._wave_prefill.get("time_start_s"),
            "time_end_s":       self._wave_prefill.get("time_end_s"),
            "data_source_file": self._wave_prefill.get("data_source_file", ""),
            "analysis_note":    "",
        }
```

**`_add_entry()` 内の `self._clear_form()` の直後に追加:**
```python
        self._clear_wave_prefill()   # ← 追加: 自動入力もリセット
```

---

## 変更7: `WorkbenchDB.add_problem_log()` の INSERT SQL を更新

**変更前:**
```python
            conn.execute(
                """INSERT INTO problem_log
                   (run_id, round, circuit, session, rider, run_no, lap_no,
                    corner, phase, problem_tag, description, severity, source,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"), data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"), data.get("run_no"),
                    data.get("lap_no"), data.get("corner"), data.get("phase"),
                    data.get("problem_tag"), data.get("description"),
                    data.get("severity", "MEDIUM"), data.get("source", "OBSERVATION"),
                    "PENDING", now, now,
                ),
            )
```

**変更後（6列を追加）:**
```python
            conn.execute(
                """INSERT INTO problem_log
                   (run_id, round, circuit, session, rider, run_no, lap_no,
                    corner, phase, problem_tag, description, severity, source,
                    distance_start_m, distance_end_m, time_start_s, time_end_s,
                    data_source_file, analysis_note,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"), data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"), data.get("run_no"),
                    data.get("lap_no"), data.get("corner"), data.get("phase"),
                    data.get("problem_tag"), data.get("description"),
                    data.get("severity", "MEDIUM"), data.get("source", "OBSERVATION"),
                    data.get("distance_start_m"), data.get("distance_end_m"),
                    data.get("time_start_s"), data.get("time_end_s"),
                    data.get("data_source_file", ""), data.get("analysis_note", ""),
                    "PENDING", now, now,
                ),
            )
```

---

## 変更8: `ProblemLogTab._setup_ui()` の一覧テーブルに Range 列を追加

**`self._table.setHorizontalHeaderLabels(...)` を以下に変更:**

```python
        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Corner", "Phase", "Tag", "Description", "Severity", "Lap", "Range", "Source"]
        )
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 60)
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 220)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 40)
        self._table.setColumnWidth(7, 160)
        self._table.setColumnWidth(8, 80)
```

**`_refresh_table()` 内の列値リストを更新:**

```python
            for ci, val in enumerate([
                r.get("problem_id", ""),
                r.get("corner", "—"),
                r.get("phase", "—"),
                r.get("problem_tag", ""),
                r.get("description", ""),
                r.get("severity", ""),
                r.get("lap_no", "—"),
                _fmt_range(r),           # ← 追加
                r.get("source", ""),     # ← 追加
            ]):
```

**`_refresh_table()` の直前に `_fmt_range()` ヘルパー関数を追加:**

```python
def _fmt_range(r: dict) -> str:
    """problem_log 行の距離/時間範囲を表示文字列に変換する。"""
    ds = r.get("distance_start_m")
    de = r.get("distance_end_m")
    if ds is not None and de is not None:
        return f"{ds:.0f}→{de:.0f}m"
    ts = r.get("time_start_s")
    te = r.get("time_end_s")
    if ts is not None and te is not None:
        return f"{ts:.1f}→{te:.1f}s"
    return "—"
```

**注意:** `_fmt_range` は `ProblemLogTab` クラスの外（直前）に定義すること。

---

## 変更9: `MainWindow.__init__()` で `set_problem_tab()` を呼ぶ

**`self._tab_csv` 生成行の直後に追加:**

```python
        self._tab_wave.set_problem_tab(self._tab_problem)   # ← 追加
```

---

## 動作確認

### テスト1: 基本フロー
1. 左パネルで `ROUND3_ASSEN_FP_DA77_R1` を選択
2. 2D CSVタブで `X_F1-#77-03_DISTANCE.csv` を読み込んで「波形に送る」
3. 波形タブで Lap A を選択 → 青いハイライト（LinearRegionItem）が表示される
4. ハイライトをドラッグして範囲を選択
5. 「📋 Problem Log へ送る」をクリック
6. Problem Log タブに自動切替される

**期待結果（Problem Log タブ）:**
- 青い枠内に `Run: ROUND3_ASSEN_FP_DA77_R1` が表示
- `Lap: 1`（選択ラップ）
- `Range: 1234.5m → 2345.6m  (1111.1m)` のように距離表示
- Lap No スピンボックスが `1` に自動入力済み
- Source が `DATA` に自動設定
- Corner / Phase / Tag / Description は空（Tatsukiが入力）

### テスト2: 追加後のリセット
「追加」ボタンを押した後:
- 一覧テーブルに新行が追加される
- Range 列に距離範囲が表示される
- 自動入力エリア（青枠）が非表示にリセット

### テスト3: Run 不一致ガード
左パネルで Run X を選択、波形は Run Y のCSVを送信した状態で「送る」を押す:
- 警告ダイアログが出て自動入力されない

### テスト4: DB確認
```sql
SELECT problem_id, lap_no, distance_start_m, distance_end_m,
       time_start_s, time_end_s, data_source_file
FROM problem_log ORDER BY created_at DESC LIMIT 5;
```
- `distance_start_m` / `distance_end_m` に値が入っていること

---

## NG条件

| 症状 | 原因 |
|------|------|
| 青いハイライトが表示されない | `_region` の追加位置が `_p_speed.addItem()` まで届いていない |
| 「送る」ボタン押下後にタブが切り替わらない | `parent._tabs.indexOf(self._problem_tab)` が -1 → `MainWindow._tabs` の参照が取れていない |
| 自動入力エリアが表示されない | `_wave_info_box.setVisible(True)` が呼ばれていない / `_wave_info_box` の初期化が `_setup_ui()` より後 |
| DBに distance_start_m が保存されない | `add_problem_log()` の INSERT SQL に列が追加されていない（変更7未適用） |
| Run不一致ガードが機能しない | `prefill_from_waveform()` での `run_id` 比較が `_run_id` ではなく別変数を参照している |

---

## Git コミットメッセージ

```
feat: waveform range selection → Problem Log auto-fill (Phase 2)

- add: LinearRegionItem to WaveformView (draggable blue highlight)
- add: "📋 Problem Log へ送る" button in waveform toolbar
- add: WaveformView._send_to_problem_log() — extracts x_mode/range/lap_no
- add: WaveformView.set_problem_tab() — decoupled reference injection
- add: ProblemLogTab.prefill_from_waveform(data) — auto-fill from wave
- add: ProblemLogTab._clear_wave_prefill() — reset auto-fill area
- add: wave_info_box UI (blue frame, run/lap/range display)
- fix: WorkbenchDB.add_problem_log() INSERT includes 6 new columns
- add: _fmt_range() helper for table display
- add: Range + Source columns to problem_log table widget
- add: MainWindow.set_problem_tab() wiring
- result: run_id/lap_no/dist/time auto-filled, tag/phase/desc manual
```
