# Claude Code 実装指示書
# タスク: Distance X軸 + Problem Log スキーマ拡張
# 対象ファイル: 05_SCRIPTS/ts24_workbench.py
# 前提: INSTRUCTION_laptime_and_lapsplit.md が実装済みであること
# 作成: Cowork Claude / 2026-05-03

---

## 背景・方針

Workbenchの目的が「Deep Analysis専用ツール」に進化した（2026-05-03 確定）。

```
2D Analyzer（正式分析）→ CSVをWorkbenchに読み込み
→ Distance軸で問題箇所を確認
→ 問題・仮説をDBに直接記録
→ 次Round判断への知見化
```

**X軸優先順位（新）:**
```
Distance (m) > Time (s) > Progress (fallback)
```

**Dist列の仕様（X_F1-#77-03_DISTANCE.csv で確認済み）:**
- 累積値（セッション通算・リセットなし）。例: 4356m → 49905m
- Lap分割後に `dist[idx] - dist[idx[0]]` で各Lap内0始まりに変換する
- Lap有効判定: `dist.max() > 10m`

---

## 変更1: CHANNEL_MAP に `distance` を追加

**場所**: `CsvImportTab.CHANNEL_MAP` dict

**変更前:**
```python
CHANNEL_MAP: dict[str, list[str]] = {
    "time":       ["time", "time2d"],
    "speed":      ["speed_front", "speed"],
    "brake":      ["brake_front"],
    "gas":        ["gas", "gas_smooth", "tps"],
    "susp_front": ["susp_front"],
    "susp_rear":  ["susp_rear"],
    "lean_angle": ["bike_angle", "lean_angle"],
}
```

**変更後:**
```python
CHANNEL_MAP: dict[str, list[str]] = {
    "time":       ["time", "time2d"],
    "distance":   ["dist", "distance"],   # ← 追加
    "speed":      ["speed_front", "speed"],
    "brake":      ["brake_front"],
    "gas":        ["gas", "gas_smooth", "tps"],
    "susp_front": ["susp_front"],
    "susp_rear":  ["susp_rear"],
    "lean_angle": ["bike_angle", "lean_angle"],
}
```

---

## 変更2: `_TARGETS` に `distance` を追加

**変更前:**
```python
_TARGETS = [
    "(ignore)", "time", "speed", "brake", "gas",
    "susp_front", "susp_rear", "lean_angle",
]
```

**変更後:**
```python
_TARGETS = [
    "(ignore)", "time", "distance", "speed", "brake", "gas",
    "susp_front", "susp_rear", "lean_angle",
]
```

---

## 変更3: `CsvImportTab._send()` — Distance X軸対応

この変更は INSTRUCTION_laptime_and_lapsplit.md 適用後の `_send()` に追加する。

### 3a: x_mode 決定ロジックを変更

**場所**: `_send()` 内、`has_time = "time" in channel_to_col` の直後

**変更前:**
```python
has_time = "time" in channel_to_col
x_mode = "time" if has_time else "progress"
```

**変更後:**
```python
has_time = "time" in channel_to_col
has_dist = "distance" in channel_to_col

# x_mode 決定（優先順位: distance > time > progress）
# distance が有効（dist.max() > 10m）なら距離軸
x_mode = "progress"
if has_time:
    x_mode = "time"
if has_dist:
    try:
        d_check = pd.to_numeric(
            df[channel_to_col["distance"]], errors="coerce"
        ).fillna(0).values
        if float(d_check.max()) > 10.0:
            x_mode = "distance"
    except Exception:
        pass
```

### 3b: 時間配列・距離配列の取得を変更

INSTRUCTION_laptime_and_lapsplit.md 適用後、以下のブロックが存在する:
```python
        # ── 時間配列の取得 ────────────────────────────────────────────
        if has_time:
            try:
                t_raw = pd.to_numeric(
                    df[channel_to_col["time"]], errors="coerce"
                ).fillna(0).values
            except Exception:
                t_raw = None
        else:
            t_raw = None

        if t_raw is None:
            x_mode = "progress"
```

このブロックを以下に**置き換える**:

```python
        # ── 時間配列の取得 ────────────────────────────────────────────
        if has_time:
            try:
                t_raw = pd.to_numeric(
                    df[channel_to_col["time"]], errors="coerce"
                ).fillna(0).values
            except Exception:
                t_raw = None
        else:
            t_raw = None

        # ── 距離配列の取得 ────────────────────────────────────────────
        d_raw = None
        if x_mode == "distance":
            try:
                d_raw = pd.to_numeric(
                    df[channel_to_col["distance"]], errors="coerce"
                ).fillna(0).values
            except Exception:
                d_raw = None
                x_mode = "time" if t_raw is not None else "progress"

        if t_raw is None and x_mode == "time":
            x_mode = "progress"
```

### 3c: 各Lap dict のX値構築を変更

INSTRUCTION_laptime_and_lapsplit.md 適用後のLap dict構築部分:

```python
            if x_mode == "time" and t_raw is not None:
                t_lap = t_raw[idx]
                x_vals = (t_lap - float(t_lap[0])).tolist()
                lap_time_s: float = round(float(t_lap[-1]) - float(t_lap[0]), 3)
            else:
                x_vals = [i / max(len(idx) - 1, 1) for i in range(len(idx))]
                lap_time_s = 0.0
```

このブロックを以下に**置き換える**:

```python
            if x_mode == "distance" and d_raw is not None:
                d_lap = d_raw[idx]
                x_vals = (d_lap - float(d_lap[0])).tolist()  # Lap内リセット
                dist_span_m = round(float(d_lap[-1]) - float(d_lap[0]), 1)
                # lap_time_s も取得（Problem Log用）
                if t_raw is not None:
                    t_lap = t_raw[idx]
                    lap_time_s: float = round(float(t_lap[-1]) - float(t_lap[0]), 3)
                else:
                    lap_time_s = 0.0
            elif x_mode == "time" and t_raw is not None:
                t_lap = t_raw[idx]
                x_vals = (t_lap - float(t_lap[0])).tolist()
                lap_time_s = round(float(t_lap[-1]) - float(t_lap[0]), 3)
                dist_span_m = 0.0
            else:
                x_vals = [i / max(len(idx) - 1, 1) for i in range(len(idx))]
                lap_time_s = 0.0
                dist_span_m = 0.0
```

### 3d: lap dict に `dist_span_m` を追加

lap dict 初期化部分を変更する:

**変更前:**
```python
            lap: dict = {
                "x": x_vals,
                "x_mode": x_mode,
                "lap_no": lap_no,
                "lap_time_s": lap_time_s,
            }
```

**変更後:**
```python
            lap: dict = {
                "x": x_vals,
                "x_mode": x_mode,
                "lap_no": lap_no,
                "lap_time_s": lap_time_s,
                "dist_span_m": dist_span_m,
            }
            # distance modeの場合、time配列もraw保存（Phase 2: Problem Log用）
            if x_mode == "distance" and t_raw is not None:
                t_lap_arr = t_raw[idx]
                lap["time_raw"] = (t_lap_arr - float(t_lap_arr[0])).tolist()
```

### 3e: 送信メッセージを更新

**変更前:**
```python
        axis_str = "Time axis (s) ✅" if x_mode == "time" else "Progress axis (0–1) ⚠"
        self._lbl_sent.setText(f"送信: {n_laps} Lap / {axis_str}")
        QMessageBox.information(
            self, "送信完了",
            f"CSV データを波形ビューに送りました。\n"
            f"検出Lap数: {n_laps}\n"
            f"X軸: {axis_str}\n\n"
            "「📊 波形 (Reference)」タブに切り替えて確認してください。",
        )
```

**変更後:**
```python
        if x_mode == "distance":
            axis_str = "Distance axis (m) ✅"
        elif x_mode == "time":
            axis_str = "Time axis (s) ✅"
        else:
            axis_str = "Progress axis (0–1) ⚠"
        self._lbl_sent.setText(f"送信: {n_laps} Lap / {axis_str}")
        QMessageBox.information(
            self, "送信完了",
            f"CSV データを波形ビューに送りました。\n"
            f"検出Lap数: {n_laps}\n"
            f"X軸: {axis_str}\n\n"
            "「📊 波形 (Reference)」タブに切り替えて確認してください。",
        )
```

---

## 変更4: `WaveformView.set_csv_laps()` — Distance モード対応

**場所**: `set_csv_laps()` 内の `if self._csv_x_mode == "time":` 分岐

**変更前:**
```python
        if self._csv_x_mode == "time":
            x_label   = "Time (s)"
            mode_text  = "X axis: Time (s)  [CSV]"
            mode_style = (
                "color: #0078D4; font-size: 10px; padding: 2px 4px;"
                " background: #EFF6FF; border-radius: 3px;"
            )
            self._lbl_warn.setVisible(False)
        else:
            x_label   = "Lap Progress (0–1)  [fallback]"
            mode_text  = "X axis: Normalized Progress (0–1)  [CSV — Time column not found]"
            mode_style = (
                "color: #797673; font-size: 10px; padding: 2px 4px;"
                " background: #FAF9F8; border-radius: 3px;"
            )
            self._lbl_warn.setVisible(True)
```

**変更後:**
```python
        if self._csv_x_mode == "distance":
            x_label   = "Distance (m)"
            mode_text  = "X axis: Distance (m)  [CSV]"
            mode_style = (
                "color: #107C10; font-size: 10px; padding: 2px 4px;"
                " background: #F0FFF0; border-radius: 3px;"
            )
            self._lbl_warn.setVisible(False)
        elif self._csv_x_mode == "time":
            x_label   = "Time (s)"
            mode_text  = "X axis: Time (s)  [CSV]"
            mode_style = (
                "color: #0078D4; font-size: 10px; padding: 2px 4px;"
                " background: #EFF6FF; border-radius: 3px;"
            )
            self._lbl_warn.setVisible(False)
        else:
            x_label   = "Lap Progress (0–1)  [fallback]"
            mode_text  = "X axis: Normalized Progress (0–1)  [CSV — Dist/Time not found]"
            mode_style = (
                "color: #797673; font-size: 10px; padding: 2px 4px;"
                " background: #FAF9F8; border-radius: 3px;"
            )
            self._lbl_warn.setVisible(True)
```

---

## 変更5: ドロップダウンラベルに距離スパンを表示

**場所**: `set_csv_laps()` のラベル生成ブロック（INSTRUCTION_laptime_and_lapsplit.md 適用後）

**変更前:**
```python
        labels = []
        for i, r in enumerate(laps):
            lap_no = r.get("lap_no", i + 1)
            lt = r.get("lap_time_s")
            lt_str = format_laptime(float(lt)) if lt else "?:??,-"
            labels.append(f"CSV Lap {lap_no}  {lt_str}")
```

**変更後:**
```python
        labels = []
        for i, r in enumerate(laps):
            lap_no = r.get("lap_no", i + 1)
            lt = r.get("lap_time_s")
            lt_str = format_laptime(float(lt)) if lt else "?:??,-"
            x_mode_r = r.get("x_mode", "progress")
            if x_mode_r == "distance":
                dist_m = r.get("dist_span_m", 0.0)
                labels.append(f"CSV Lap {lap_no}  {dist_m:.0f}m  ({lt_str})")
            else:
                labels.append(f"CSV Lap {lap_no}  {lt_str}")
```

---

## 変更6: `WaveformView._draw()` — Distance モードを Time と同様に扱う

**場所**: `_draw()` 内の `x_mode = self._csv_x_mode` が設定された後のプロット処理

Distance mode は Time mode と同じ「生の値をそのまま描画」でよい。
`_plot()` 内の既存の分岐 `if x_mode == "time"` を以下に変更する:

**変更前:**
```python
            xs = np.array(xs_raw, dtype=float) if x_mode == "time" else _normalize(xs_raw)
```

**変更後:**
```python
            xs = np.array(xs_raw, dtype=float) if x_mode in ("time", "distance") else _normalize(xs_raw)
```

---

## 変更7: Problem Log スキーマ拡張（DB migration）

### 7a: WorkbenchDB のテーブル作成SQLに新列を追加

**場所**: `WorkbenchDB.__init__()` または `_create_tables()` メソッド内の `problem_log` CREATE TABLE文

新列を末尾に追加する:
```sql
CREATE TABLE IF NOT EXISTS problem_log (
    problem_id TEXT PRIMARY KEY,
    run_id TEXT,
    round TEXT,
    circuit TEXT,
    session TEXT,
    rider TEXT,
    run_no INTEGER,
    lap_no INTEGER,
    corner TEXT,
    phase TEXT,
    problem_tag TEXT,
    description TEXT,
    severity TEXT,
    source TEXT,
    created_at TEXT,
    updated_at TEXT,
    -- Phase 2拡張列
    distance_start_m REAL,
    distance_end_m REAL,
    time_start_s REAL,
    time_end_s REAL,
    data_source_file TEXT,
    analysis_note TEXT
)
```

### 7b: 既存DBへの ALTER TABLE 自動適用

`WorkbenchDB.__init__()` または `_create_tables()` に以下のmigration処理を追加する。
既存DBには新列が存在しないため、起動時に自動追加する:

```python
def _migrate_problem_log(self, conn):
    """problem_log テーブルに Phase 2 拡張列を追加（既存DBへの後方互換対応）"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(problem_log)")}
    new_columns = [
        ("distance_start_m", "REAL"),
        ("distance_end_m",   "REAL"),
        ("time_start_s",     "REAL"),
        ("time_end_s",       "REAL"),
        ("data_source_file", "TEXT"),
        ("analysis_note",    "TEXT"),
    ]
    for col_name, col_type in new_columns:
        if col_name not in existing:
            conn.execute(
                f"ALTER TABLE problem_log ADD COLUMN {col_name} {col_type}"
            )
    conn.commit()
```

この `_migrate_problem_log()` を `_create_tables()` または `__init__()` の末尾で呼び出すこと:
```python
with self._conn() as conn:
    self._create_tables(conn)
    self._migrate_problem_log(conn)  # ← 追加
```

---

## 動作確認手順（承認済み必須チェック — 2026-05-03 確定）

`06_CSV/X_F1-#77-03_DISTANCE.csv` を使って以下5点を**全て確認**してからコミットすること:

### ✅ チェック1: Lap内Distanceが0m始まりになること
- Lap 1を選択 → 波形X軸が `0m ～ 13665m` で表示される（Assen 3周分）
- Lap 2を選択 → 波形X軸が `0m ～ 27329m` で表示される（Assen 6周分）
- **NG条件**: 4356mや22576mなど累積値から始まる場合は実装ミス
- **補足**: Assen = 4555m/周。13665 = 3×4555, 27329 = 6×4555（完全一致確認済み）

### ✅ チェック2: X軸Distance表示が正しいこと
- 「CSV Import」タブで `Dist` 列が自動的に `distance` にマッピングされる
- 「波形に送る」後、波形タブに「Distance axis (m) ✅」緑インジケーターが表示される
- X軸ラベルが `Distance (m)` になっている
- **NG条件**: Timeラベルのままや Progress表示の場合は変更6の対応漏れ

### ✅ チェック3: Lapタイムが 分:秒,00 表記になること
（INSTRUCTION_laptime_and_lapsplit.md の確認項目）
- ドロップダウンに `CSV Lap 1  13665m  (5:00,63)` 相当の表示がある
- 秒区切りが `,`（コンマ）であること。`.`（ピリオド）はNG
- **NG条件**: `(300.63s)` のように生秒数が残っている場合は format_laptime未適用

### ✅ チェック4: Problem Logに distance_start/end が保存されること
- 起動後にターミナルで確認:
  ```bash
  sqlite3 ~/Desktop/"Data TS24 Claude"/04_MES/ts24_unified.db \
    "PRAGMA table_info(problem_log);"
  ```
  `distance_start_m`, `distance_end_m`, `time_start_s`, `time_end_s`,
  `data_source_file`, `analysis_note` の6列が出力されること

### ✅ チェック5: 既存Problem Logが壊れないこと
- 既存のProblem Logレコードが Problem Log タブに表示され続けること
- 新規Problem Logの保存・削除が正常に動作すること
- ALTER TABLE は既存データを保持するため、データ消失は起きないはずだが必ず目視確認すること

---

## Git コミットメッセージ

```
feat: distance axis support + problem_log schema extension

- add: "distance" channel to CHANNEL_MAP and _TARGETS
- feat: x_mode priority Distance > Time > Progress in _send()
- feat: dist[idx] - dist[idx[0]] per-lap distance reset
- feat: WaveformView handles x_mode="distance" (green indicator)
- feat: dropdown label shows dist_span_m in distance mode
- feat: _draw() treats "distance" same as "time" (raw values)
- feat: problem_log schema +6 columns (distance_start_m, etc.)
- feat: auto-migration for existing DB via ALTER TABLE
```
