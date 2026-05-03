# Claude Code 実装指示書
# タスク: Lapタイム表示フォーマット + 時間ギャップLap分割
# 対象ファイル: 05_SCRIPTS/ts24_workbench.py
# 作成: Cowork Claude / 2026-05-03

---

## 背景

2D CSVインポートタブ (CsvImportTab) に以下3つの問題がある:

1. **`best_lap_s` 列エラー** → DB左パネルが空のまま（回帰バグ）
2. **Lapタイム表示が生秒数** → `406.16s` ではなく `6:46,16` と表示すべき
3. **Lap分割未実装** → 時間ギャップ>5s でLap境界を検出し、複数Lapに分割すべき

---

## 変更1: `best_lap_s` → `perf_best_lap` の修正（3箇所）

### 変更1a — SQL クエリ（circuit指定あり）

**場所**: `WorkbenchDB.get_runs()` メソッド内、1つ目のSQL

**変更前:**
```python
                    """SELECT run_id, circuit, session, rider, run_no, best_lap_s
                       FROM runs WHERE circuit = ? ORDER BY session, rider, run_no""",
```

**変更後:**
```python
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs WHERE circuit = ? ORDER BY session, rider, run_no""",
```

### 変更1b — SQL クエリ（全件）

**場所**: `WorkbenchDB.get_runs()` メソッド内、2つ目のSQL

**変更前:**
```python
                    """SELECT run_id, circuit, session, rider, run_no, best_lap_s
                       FROM runs ORDER BY circuit, session, rider, run_no"""
```

**変更後:**
```python
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs ORDER BY circuit, session, rider, run_no"""
```

### 変更1c — ツリー表示での参照

**場所**: `ProblemLogTab._refresh_run_tree()` メソッド内の `best` 変数

**変更前:**
```python
                best = r.get("best_lap_s")
                best_str = f"{best:.3f}s" if best else "—"
```

**変更後:**
```python
                best = r.get("perf_best_lap")
                best_str = format_laptime(float(best)) if best else "—"
```

---

## 変更2: `format_laptime()` 関数を追加

**場所**: 定数ブロック (`RESULT_EVALS = [...]`) の直後、DB クラスの前に挿入。

具体的には以下のコメント行の直前に挿入:
```python
# ════════════════════════════════════════════════════════════════════
# DB アクセス層
```

**挿入するコード:**
```python
# ════════════════════════════════════════════════════════════════════
# ユーティリティ
# ════════════════════════════════════════════════════════════════════

def format_laptime(sec: float) -> str:
    """秒数を 分:秒,00 形式に変換する。
    
    例: 97.45  → "1:37,45"
        100.203 → "1:40,20"
        65.0    → "1:05,00"
    
    ルール:
    - 内部では常に float 秒で計算・比較すること
    - この関数は表示専用。戻り値を数値演算に使ってはならない
    """
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:05.2f}".replace(".", ",")


```

---

## 変更3: `CsvImportTab._send()` — 時間ギャップLap分割の実装

**場所**: `CsvImportTab._send()` メソッド全体を置き換える。

現在の `_send()` は単一Lapしか生成しない。以下のロジックで複数Lapに分割する:

### 分割アルゴリズム

```
time配列を走査し、time[i] - time[i-1] > 5 の箇所でLap境界とする
各Lap内で time_reset = time - time[0] を計算し、X軸を0始まりにする
```

**変更前（`_send()` 末尾付近の lap 生成 + `set_csv_laps` 呼び出しブロック）:**

```python
        # Build X
        if has_time:
            try:
                t = pd.to_numeric(df[channel_to_col["time"]], errors="coerce").fillna(0).values
                x_vals: list = (t - float(t[0])).tolist()
                lap_time_s: "float | None" = round(float(t[-1]) - float(t[0]), 3)
            except Exception:
                x_mode = "progress"
                x_vals = [i / max(n - 1, 1) for i in range(n)]
                lap_time_s = None
        else:
            x_vals = [i / max(n - 1, 1) for i in range(n)]
            lap_time_s = None

        lap: dict = {"x": x_vals, "x_mode": x_mode, "lap_no": 1}
        if lap_time_s is not None:
            lap["lap_time_s"] = lap_time_s

        for ch_name, col_name in channel_to_col.items():
            if ch_name == "time" or col_name not in df.columns:
                continue
            try:
                lap[ch_name] = pd.to_numeric(
                    df[col_name], errors="coerce"
                ).fillna(0).tolist()
            except Exception:
                pass

        self._wave.set_csv_laps([lap])

        axis_str = "Time axis (s) ✅" if x_mode == "time" else "Progress axis (0–1) ⚠"
        self._lbl_sent.setText(f"送信: {axis_str}")
        QMessageBox.information(
            self, "送信完了",
            f"CSV データを波形ビューに送りました。\n"
            f"X軸: {axis_str}\n\n"
            "「📊 波形 (Reference)」タブに切り替えて確認してください。",
        )
```

**変更後（上記ブロックを以下で置き換える）:**

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

        # ── 時間ギャップでLap分割 ─────────────────────────────────────
        import numpy as np

        if x_mode == "time" and t_raw is not None:
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
            # time列なし → 全体を1Lapとして progress軸
            lap_indices = [list(range(n))]

        # ── 各Lap dict を構築 ─────────────────────────────────────────
        laps: list[dict] = []
        for lap_no, idx in enumerate(lap_indices, start=1):
            if len(idx) < 2:
                continue  # 短すぎるLapは無視

            if x_mode == "time" and t_raw is not None:
                t_lap = t_raw[idx]
                x_vals = (t_lap - float(t_lap[0])).tolist()
                lap_time_s: float = round(float(t_lap[-1]) - float(t_lap[0]), 3)
            else:
                x_vals = [i / max(len(idx) - 1, 1) for i in range(len(idx))]
                lap_time_s = 0.0

            lap: dict = {
                "x": x_vals,
                "x_mode": x_mode,
                "lap_no": lap_no,
                "lap_time_s": lap_time_s,
            }

            for ch_name, col_name in channel_to_col.items():
                if ch_name == "time" or col_name not in df.columns:
                    continue
                try:
                    vals = pd.to_numeric(
                        df[col_name], errors="coerce"
                    ).fillna(0).values
                    lap[ch_name] = vals[idx].tolist()
                except Exception:
                    pass

            laps.append(lap)

        if not laps:
            QMessageBox.warning(self, "データなし", "有効なLapデータが見つかりません。")
            return

        self._wave.set_csv_laps(laps)

        n_laps = len(laps)
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

---

## 変更4: `WaveformView.set_csv_laps()` — ドロップダウンラベルに `format_laptime` を使用

**場所**: `WaveformView.set_csv_laps()` メソッド末尾のラベル生成部分

**変更前:**
```python
        labels = [
            f"CSV Lap {r.get('lap_no', i + 1)}  ({r.get('lap_time_s', '?')}s)"
            for i, r in enumerate(laps)
        ]
```

**変更後:**
```python
        labels = []
        for i, r in enumerate(laps):
            lap_no = r.get("lap_no", i + 1)
            lt = r.get("lap_time_s")
            lt_str = format_laptime(float(lt)) if lt else "?:??,-"
            labels.append(f"CSV Lap {lap_no}  {lt_str}")
```

---

## 変更後の動作確認

`X_F1-#77-03_new.csv` をインポートして以下を確認すること:

1. **左パネル（Run一覧）が表示される** — `best_lap_s` エラーが消える
2. **Lap A/B ドロップダウンに2エントリが表示される**:
   - `CSV Lap 1  8:52,42`（約532秒）
   - `CSV Lap 2  9:54,44`（約594秒）
   ※ 実際のLapタイムはCSV内容による。上記は概算。
3. **ドロップダウンの秒部分が `,` 区切り**（`.` ではなく）
4. **Lap 1 を選択すると X軸が 0〜532秒**（ラップ内リセット済み）
5. **Lap 2 を選択すると X軸が 0〜594秒**（ラップ内リセット済み）

---

## 注意事項

- `format_laptime()` は **表示専用**。戻り値を数値比較や演算に使わないこと
- `t_raw[idx]` は numpy の fancy indexing を使っているため、`t_raw` は必ず `np.ndarray` であること（pandas Series ではなく `.values` を使うこと）
- `import numpy as np` は `_send()` 内ですでに実行されているが、`_send()` の最初（`if x_mode == "time"` より前）に移動しても問題なし

---

## Git コミットメッセージ

```
feat: laptime format + time-gap lap segmentation in CsvImportTab

- fix: best_lap_s → perf_best_lap (3 locations, restores left panel)
- add: format_laptime(sec) → "M:SS,cc" display utility
- feat: detect lap boundaries by time gap > 5s in _send()
- feat: reset lap-internal time to 0 per lap
- feat: update Lap A/B dropdowns with format_laptime() labels
```
