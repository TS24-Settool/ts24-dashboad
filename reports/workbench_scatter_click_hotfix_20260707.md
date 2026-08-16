# Workbench scatter click ValueError hotfix

- 日付: 2026-07-07 / 種別: hotfix（GO不要・DB無変更・`ts24_workbench.py` のみ）
- 症状: 散布図クリックで `_on_pt_click` L4589 `if not points:` が numpy.ndarray を真偽値判定し
  `ValueError: The truth value of an array with more than one element is ambiguous`。

## 修正（最小差分・`PostureAnalysisTab._on_pt_click` のみ）

```python
if points is None or len(points) == 0:
    return
try:
    d = points[0].data()
except Exception:
    return  # SpotItem 以外（配列要素等）はクリック詳細対象外
```

- `sigClicked.connect` 側（L4996/L5070 相当）は無変更（PyQtGraph 0.12/0.13 互換ラムダ維持）。
- ポップアップ仕様・DB・queue・provisional 全て無変更。

## 検証（全PASS）

1. py_compile PASS。
2. 再現テスト（offscreen・実タブインスタンス）: `[]` / `None` / `np.array([1,2,3])` / `np.array([])` /
   SpotItem 相当（`.data()` 有り）→ **ValueError ゼロ**・dict 以外は従来どおり return。
3. offscreen smoke: MainWindow **7タブ**・Suspension/Posture 到達・overlay **1281行**（prov 79）・**MISANO 12 prov runs** 表示。
   ※importlib ロード時の DB 相対パス化は既知の検証用人工物（CLAUDE.md §21b・実起動は正常）で、絶対パス指定で再検証済み。
4. 実機 GUI クリック確認は Tatsuki ローカル（散布図の点をクリック → Traceback が出ないこと）。

## rollback

該当 2 ブロックの revert のみ（DB 無関係）。
