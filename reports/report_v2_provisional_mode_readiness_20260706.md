# Report v2 provisional モード readiness（Phase B-5 / Phase A・read-only・GO待ち）

- 日付: 2026-07-06 / 作成: Claude Code（readiness のみ・コード/DB 無変更）
- 対象: `05_SCRIPTS/suspension_report.py`（~1036行）/ `05_SCRIPTS/ts24_workbench.py`
- 前提: §53/§57 で provisional 12 runs / 79 laps（`PROV_20260612_ROUND7_MISANO_*`・quality PASS 8 / WARNING 4）、
  §55 で Workbench overlay + Report v2 暫定警告ガード稼働中。本タスクはその warning を本対応（provisional モード）へ置換する設計凍結。
- 本フェーズで PPTX/PDF は生成しない。書込は本レポートのみ。

---

## 1. `provisional` モードの配管（シグネチャ設計）

### 1.1 変更点（suspension_report.py）

| 箇所 | 現行（実測行） | 変更後 |
|---|---|---|
| `build_report_v2` | L781-782 `build_report_v2(df, run_ids=None, scope=None, out_dir=DEFAULT_OUT, timestamp=None)` | 末尾に `provisional=False` を追加（キーワード引数・既存呼出し無影響） |
| `build_report_pdf` | L961-962 同形シグネチャ | 同じく `provisional=False` を追加 |
| `chart_cover` | L700 `chart_cover(resolved, summ, generated_human, tmpdir)` | `provisional=False, mixed=False` を追加 |

### 1.2 自動検出（安全網）

両 build 関数の冒頭（run_ids フィルタ直後・L786-789 / L967-970 相当）に:

```python
prov_ids = {r for r in df["run_id"].astype(str) if r.startswith("PROV_")}
if prov_ids:
    provisional = True                      # 呼び出し側が False でも強制昇格
mixed = bool(prov_ids) and len(prov_ids) < df["run_id"].nunique()
```

### 1.3 推奨方式（凍結）

**明示フラグ（caller から `provisional=True`）+ 内部自動検出を安全網として併用。**
- 明示フラグ: Workbench の確認ダイアログ結果を意図として伝える正規経路。
- 自動検出: CLI（`main()` L1006-1032 は provisional を知らない）や将来の呼出し元が
  フラグを渡し忘れても、PROV_ run を含む限り必ず provisional 表記になる（表記漏れ=提出事故の恒久防止）。
- 逆方向（PROV_ 無しなのに provisional=True）は許容（明示指定を尊重）だが Workbench からは発生しない。

---

## 2. Cover への PROVISIONAL 表示（chart_cover 内・単一変更点）

### 2.1 構造の確認（実測）

`chart_cover()` L700-770 は 16:9 全面 matplotlib 画像（ax 座標 0-1）:
navy 縦帯+上部バー L716-717 → Title L718-719 → Subtitle L720-722 → 罫線 L723 →
KPI 4カード L725-739（yb=0.505, h=0.20）→ Scope カード L741-752（syb=0.085, sh=0.36, x=0.05-0.47）→
Phase colours カード L754-768（x=0.53-0.95）→ footer 注記 L769 → `_save(..., tight=False)` L770。

**単一変更点の検証: 成立。** 同一 cover 画像を PPTX は `build_report_v2` L809
（`_add_cover_slide(prs, Inches, chart_cover(...))`、`_add_cover_slide` は L773-778 で全面貼付）、
PDF は `build_report_pdf` L983（`pages.append(chart_cover(...))`）で使用。
**chart_cover 1関数の変更だけで PPTX/PDF 両方の cover に反映される。**

### 2.2 リボン（provisional=True 時のみ描画・英語のみ / CJK=0 遵守）

- 位置: Title 帯の右上（Subtitle L720-722 と重ならない空き領域 x≈0.60-0.95, y≈0.83-0.92）。
  L723 の罫線描画の直後に追加（既存要素の座標は一切動かさない）。
- 実装: `mpatches.FancyBboxPatch`（amber `#B7791F` 系 or 警告赤 `#B03A2E`・白文字・zorder=4）+
  `ax.text(... "PROVISIONAL - SESSION DATA", fontweight="bold")`。
- `mixed=True` の場合はリボン直下に小さく `Mixed final + provisional runs` を追記（§4）。

### 2.3 メタデータ注記ブロック（provisional=True 時のみ）

Scope カード内の Generated 行（L748-752 のループ・ry 減算 0.07 刻み）で余白が残るため、
Scope カード下端〜footer の間（y≈0.10-0.14 近傍）に小フォント（9-10pt・警告色）で 4行固定:

```
Not final DB integration
Original setup data not merged
Run numbers are provisional
For race-weekend engineering review only
```

（footer `SPEED_NOTE` L769 は不変。座標が窮屈な場合は Scope カード右横の空きに縦積みでも可 — 実装時に目視調整。）

---

## 3. ファイル名 `_PROVISIONAL_` トークン

- PPTX: L849-850 / PDF: L999-1000。両方とも同一パターン
  `suspension_report_v2_{circuit_tok}_{rider_tok}_{session_tok}_{ts}.pptx|pdf`。
- 変更: `prov_tok = "_PROVISIONAL" if provisional else ""` を導入し
  `f"...{rs['session_tok']}{prov_tok}_{ts}.pptx"` — **timestamp 直前に挿入**。
- サンプル: `suspension_report_v2_MISANO_JA52_FP_PROVISIONAL_<TS>.pptx` / 同 `.pdf`。
- トークンは固定 ASCII 定数のため `_ascii_token()`（L670-674）を通す必要なし。
- **final-only（provisional=False）は prov_tok="" で文字列生成が現行と byte 一致 → 既存パス無変更。**

---

## 4. final + provisional 混在選択

- §1.2 の `mixed` 判定（PROV_ が 1件以上かつ全 run 未満）で検出。
- 挙動: **provisional モードに倒す**（リボン+注記+ファイル名トークンすべて適用）+
  cover に `Mixed final + provisional runs` 注記を追加（§2.2）。
- 理由: 1件でも未確定 run を含む成果物は確定扱いにできない（安全側）。混在の明示で誤読を防ぐ。

---

## 5. Workbench `_on_create_report`（ts24_workbench.py L3446-3505）

- 現行: L3458-3470 の暫定警告（「Task 6 未実装・提出禁止」文面・Yes|Cancel・既定 Cancel）→ opt-in で
  **provisional 表記なしのまま**生成（§54/§55 の暫定ガード）。
- 変更（この警告ブロックを置換）:
  ```python
  prov = [r for r in run_ids if str(r).startswith("PROV_")]
  provisional = False
  if prov:
      ret = QMessageBox.question(
          self, "Provisional Report",
          f"選択 Run に provisional（速報・未確定）が {len(prov)} 件含まれます。\n"
          "provisional reportとして生成しますか？\n"
          "（cover に PROVISIONAL 表記・ファイル名に _PROVISIONAL_ が付きます）",
          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
          QMessageBox.StandardButton.Cancel)
      if ret != QMessageBox.StandardButton.Yes:
          return
      provisional = True
  ```
- 呼出し 2箇所に伝播: L3487 `build_report_v2(df, run_ids=run_ids, scope=scope, provisional=provisional)` /
  L3490 `build_report_pdf(..., provisional=provisional)`。
- **final-only はダイアログなし・provisional=False で現行と完全同一動作**（無回帰）。
  仮に伝播漏れがあっても §1.2 の自動検出が二重の安全網として機能。

---

## 6. サンプル生成計画（Phase C・GO 後）

1. 小サンプル: MISANO / JA52 / FP（provisional 3 runs / 15 laps・§53）で PPTX+PDF を
   `reports/pptx/` へ生成 → cover リボン/注記/ファイル名を目視+機械検証。
2. 合格後: MISANO / JA52 / 全 session（All-provisional 12 runs / 79 laps）の生成可否を判断・実施。
3. 対照: final-only（例 JEREZ / DA77 / TEST1_DAY1・§48 サンプルと同条件）を再生成し無回帰確認。

## 7. 検証計画（Phase C）

| # | 検証 | 合格条件 |
|---|---|---|
| 1 | `py_compile` suspension_report.py / ts24_workbench.py | PASS |
| 2 | サンプル PPTX+PDF 生成（§6-1） | 例外なし・両ファイル生成 |
| 3 | PPTX テキスト抽出（python-pptx で全 shape 走査 + cover は画像のため PNG 化して目視） | "PROVISIONAL" が cover に存在・注記 4行あり |
| 4 | ファイル名トークン | `_MISANO_JA52_FP_PROVISIONAL_<TS>` 一致 |
| 5 | final-only サンプル | ファイル名に `_PROVISIONAL_` 無し・生成パス/構成が現行と同一（同一 timestamp 指定で名前 byte 比較可） |
| 6 | CJK=0（§49 ルール） | 全スライド native text + cover 画像内とも CJK 0 |
| 7 | offscreen Workbench smoke | 7タブ・`_on_create_report` の final-only 無ダイアログ・PROV 選択で question 1回 |
| 8 | DB 不変 | 業務6（runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613/v2_staging7710）+ provisional 3（12/79/79）before==after |

## 8. Rollback

- **diff revert のみ（2ファイル: suspension_report.py / ts24_workbench.py）。DB 関与ゼロ**
  （本機能は read-only の出力整形。schema/行/queue 一切触らない）。
- 生成済みサンプル pptx/pdf は superseded として残置可（削除も任意）。

## 9. Multi-agent operating check / 未実施リスト

- 運用: 本 readiness はメイン+読取エージェントで実施（§46d の委任効率方針・過去調査 §54/§55 を再利用し再調査を省略）。
  Extraction/Quality Gate/DB Integration は本タスク非該当（出力層のみ）。Supervisor 観点 = 承認境界で停止済み（Phase C は GO 待ち）。
  Tatsuki = `Report v2 provisional mode GO` の判断のみ残。
- 未実施（各別承認・不変）:
  1. FAIL 7 outing 救済/再解析（§53/§57）
  2. Workbench Session Import ボタン（Task 4）
  3. Supabase（remote_extra 24 cleanup 含む）
  4. DB Master 再生成 / race_results 由来新シート
  5. origin push（§48 以降の未コミット群含む）
  6. final化・provisional クリア（Post-event full rebuild・§50 Task 8）

---

**次ゲート: `Report v2 provisional mode GO`** — 受領時のみ Phase C（実装 → §6 サンプル → §7 検証 → apply レポート）。
