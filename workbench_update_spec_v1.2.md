# Workbench Update Spec v1.2
**作成者:** Cowork Claude  
**作成日:** 2026-05-12  
**対象ファイル:** `ts24_workbench.py`  
**実装担当:** Claude Code

---

## 概要

Tatsukiのフィードバック（スクリーンショット4枚）に基づく修正・機能強化。
優先度順に実装すること。

---

## Fix 1: 波形グラフ X軸同期（優先度: 高）

### 問題
`WaveformView` の5つのPlotWidget（Speed, Brake, Gas, SUSP_F, SUSP_R）が独立しており、
1つをズーム/パンしても他のグラフが追従しない。同一地点の比較ができない。

### 解決策

#### 1-A: X軸リンク
`_setup_ui()` でPlotWidgetを生成した後、全グラフのX軸を最初のグラフ（Speed）にリンクする：

```python
# _setup_ui() の最後に追加
# プロットリストを self._plot_widgets に保持しておく
for pw in self._plot_widgets[1:]:
    pw.setXLink(self._plot_widgets[0])
```

#### 1-B: クロスヘアカーソル（縦線）
全グラフに連動する黄色の縦線を追加し、マウスホバーで位置を表示：

```python
# _setup_ui() の最後に追加
self._vlines = []
for pw in self._plot_widgets:
    vl = pg.InfiniteLine(
        angle=90, movable=False,
        pen=pg.mkPen(color='y', width=1, style=Qt.PenStyle.DashLine)
    )
    pw.addItem(vl, ignoreBounds=True)
    self._vlines.append(vl)

# Speed PlotWidget のマウスムーブイベントに接続
self._plot_widgets[0].scene().sigMouseMoved.connect(self._on_mouse_moved)

def _on_mouse_moved(self, evt):
    pos = evt[0] if isinstance(evt, tuple) else evt
    if self._plot_widgets[0].sceneBoundingRect().contains(pos):
        mp = self._plot_widgets[0].plotItem.vb.mapSceneToView(pos)
        for vl in self._vlines:
            vl.setPos(mp.x())
```

#### 1-C: X軸表示をDistance (m)に統一
現在の実装を確認し、全グラフのX軸ラベルが `Distance (m)` で統一されているか確認。
Lap A / Lap B の距離スケールが異なる場合は、正規化（0-1 = lap progress）に切り替えも検討。

---

## Fix 2: Problem Log / Setup Decision のRun選択UI（優先度: 高）

### 問題
`ProblemLogTab` と `SetupDecisionTab` が Run=(未選択) の状態でテーブルが空になる。
これらのタブには独立したRun選択UIがなく、波形タブでCSVを開かないと使えない。

### 解決策

#### 2-A: ProblemLogTab にDBベースのRun選択を追加

`ProblemLogTab._setup_ui()` の先頭に以下を追加：

```python
# ── Run選択バー ──────────────────────────────────
run_bar = QHBoxLayout()

self._cmb_pl_circuit = QComboBox()
self._cmb_pl_circuit.addItem("全サーキット")
# DBから回路一覧を取得して追加
for c in self.db.get_circuits():
    self._cmb_pl_circuit.addItem(c)
self._cmb_pl_circuit.currentTextChanged.connect(self._pl_on_circuit_changed)
run_bar.addWidget(QLabel("Circuit:"))
run_bar.addWidget(self._cmb_pl_circuit)

self._cmb_pl_run = QComboBox()
self._cmb_pl_run.addItem("全Run")
self._cmb_pl_run.currentTextChanged.connect(self._pl_on_run_changed)
run_bar.addWidget(QLabel("Run:"))
run_bar.addWidget(self._cmb_pl_run)

run_bar.addStretch()
layout.addLayout(run_bar)  # テーブルの上に配置
```

`_pl_on_circuit_changed()` → Runコンボを当該サーキットのRunで更新  
`_pl_on_run_changed()` → `_refresh_table()` を呼ぶ（run_id フィルタ適用）

`_refresh_table()` を修正：run_id=None のとき全件表示。

#### 2-B: SetupDecisionTab も同様に修正

`SetupDecisionTab._setup_ui()` に同様のRun選択バーを追加。
`_refresh_table()` がrun_idフィルタを受け付けるよう修正。

---

## Enhancement 3: Suspension Analysis の F1スタイル強化（優先度: 中）

### 背景
現在の `🦾 Suspension` サブタブは「散布図 + 速度帯バーチャート + テーブル」。
より深い「バイクの姿勢分析」が必要。F1/MotoGPで使われる手法を応用する。

### 新しい考え方：Pitch & Heave

モータースポーツで標準的なバイク姿勢の定量化：

```
Pitch（ピッチ角）= ApexSusF - ApexSusR  [mm]
  → 正値: フロントが沈まずリアが沈む（ノーズUP = アンダーステア傾向）
  → 負値: フロントが沈みリアが浮く（ノーズDOWN = 良好なターンイン）

Heave（ヒーブ）= (ApexSusF + ApexSusR) / 2  [mm]
  → バイク全体の沈み込み量（スプリングレートの総合指標）
```

### 新サブタブ「🎯 姿勢分析」を TrendAnalysisTab に追加

既存サブタブ構成に `🎯 姿勢分析` を追加（Analysis の右隣）：

```
Lap Times | Performance | Setup History | Problems | Lap Log | 🦾 Suspension | 🔍 Analysis | 🎯 姿勢分析 | Perf Corr | Session Notes
```

#### パネル A: Pitch vs Lap Time 散布図

```python
# _build_posture_view(self, sus_data) に実装

# Pitch計算
for d in valid:
    d['_pitch'] = float(d['apex_sus_f'] or 0) - float(d['apex_sus_r'] or 0)
    d['_heave'] = (float(d['apex_sus_f'] or 0) + float(d['apex_sus_r'] or 0)) / 2

# 散布図: X=LapTime, Y=Pitch, 色=ライダー
# 目標ゾーン（Pitch: -5〜+5mm）をグレーの矩形で表示
# ライダー別平均Pitchを水平破線で表示
```

#### パネル B: Phase Space（フェーズ空間）プロット

```python
# X=BrkSusF, Y=BrkSusR → ブレーキング姿勢
# X=ApexSusF, Y=ApexSusR → Apex姿勢
# 各点をLapTime品質で色付け（速い=緑, 遅い=赤）
# ライダー別に「好みゾーン」クラスターが浮かび上がる
# Y=X の対角線（F=R の等荷重ライン）を表示

pw = self._pw_phase_space
pw.setLabel('bottom', 'BrkSusF / ApexSusF (mm)')
pw.setLabel('left', 'BrkSusR / ApexSusR (mm)')

# 等荷重ライン y=x
eq_line = pg.InfiniteLine(angle=45, pen=pg.mkPen('w', width=1, style=Qt.DashLine))
pw.addItem(eq_line)
```

#### パネル C: ライダー指紋レーダーチャート（QLabel画像で実装）

pyqtgraphはレーダーチャート非対応のため、matplotlibで生成してPixmapで表示：

```python
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PyQt6.QtGui import QPixmap
from io import BytesIO

def _draw_radar(self, stats_da77, stats_ja52):
    categories = ['ApexSusF', 'ApexSusR', 'BrkSusF', 'BrkSusR', 'Heave', 'Pitch(abs)']
    # 0-100%に正規化してspider chartを描画
    fig, ax = plt.subplots(subplot_kw=dict(polar=True), figsize=(4,4))
    fig.patch.set_facecolor('#1e1e1e')
    ax.set_facecolor('#1e1e1e')
    # ... (DA77=青, JA52=橙で描画)
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor='#1e1e1e')
    plt.close(fig)
    buf.seek(0)
    pix = QPixmap()
    pix.loadFromData(buf.read())
    self._lbl_radar.setPixmap(pix)
```

#### パネル D: ラップ進行でのPitch/Heave推移

```python
# X=LapNo, Y=Pitch または Heave
# セッション（FP/QP/R1/R2）でフィルタ
# タイヤ摩耗によるバイク姿勢変化の可視化
# 傾向線（線形回帰）を表示

from scipy import stats as sp_stats
slope, intercept, r, p, _ = sp_stats.linregress(lap_nos, pitches)
trend_y = [slope * x + intercept for x in lap_nos]
pw.plot(lap_nos, trend_y, pen=pg.mkPen('y', width=1, style=Qt.DashLine))
```

### UI レイアウト（🎯 姿勢分析タブ）

```
┌─────────────────────────────────────────────────────────┐
│ [Y軸選択: Pitch / Heave] [セッション: 全て/FP/QP/R]      │
├──────────────────┬──────────────────────────────────────│
│                  │                                       │
│   Pitch vs       │   Phase Space                        │
│   Lap Time       │   (BrkSus F vs R)                   │
│   scatter        │                                       │
│                  │                                       │
├──────────────────┴──────────────────────────────────────│
├──────────────────┬──────────────────────────────────────│
│                  │                                       │
│   レーダーチャート  │   Pitch/Heave ラップ推移             │
│   (DA77 vs JA52) │   (Lap No vs Pitch)                 │
│                  │                                       │
└──────────────────┴──────────────────────────────────────┘
```

---

## 実装の注意事項

1. **Fix 1を最初に実装すること** — X軸同期は他の機能より重要
2. **matplotlib の import** — `matplotlib.use('Agg')` を必ずバックエンド設定前に呼ぶ
3. **scipy は `requirements_workbench.txt` に追加** — `scipy>=1.10.0`
4. **`_build_posture_view()` は `_build_analysis_view()` と同パターンで実装**
5. **構文チェック必須**: `python3 -m py_compile ts24_workbench.py`

---

## 実装完了後の確認事項

- [ ] 波形グラフで片方をズームすると他の4つも追従するか
- [ ] クロスヘア縦線が全グラフで同時に動くか  
- [ ] Problem LogタブでCSV未ロード状態でもRun選択できるか
- [ ] `🎯 姿勢分析` タブにPitch散布図・Phase Space・レーダー・推移グラフが表示されるか
- [ ] Pitch = ApexSusF - ApexSusR の計算値が正しいか（lap_suspensionデータで手動確認）
- [ ] `python3 -m py_compile ts24_workbench.py` でエラーなし

---

*完了後、`race_memory.json` の `conversation_summaries` に実装内容を記録すること。*
