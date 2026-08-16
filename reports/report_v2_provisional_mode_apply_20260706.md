# Report v2 provisional モード apply（Phase B-5 / Phase C・GO受領・実装済）

- 日付: 2026-07-07 / 実施: Claude Code（**Tatsuki `Report v2 provisional mode GO` 受領済**）
- readiness: `reports/report_v2_provisional_mode_readiness_20260706.md`（§59・凍結設計に準拠）
- 変更 = **`suspension_report.py` / `ts24_workbench.py` の2ファイルのみ**。DB は read-only（業務6 + provisional 3 とも before==after 不変を機械検証）。commit なし。

---

## 1. Diff サマリ

### 1.1 `suspension_report.py`（5 seam・readiness §1-§3 どおり）

| 箇所 | 変更 |
|---|---|
| `chart_cover`（旧 L700） | シグネチャに `provisional=False, mixed=False` 追加。罫線描画（旧 L723）直後に provisional ブロック追加: ①**amber `#B7791F` リボン**（x0.60-0.95・y0.930-0.988・白 bold 14.5pt `PROVISIONAL - SESSION DATA`・zorder4/5）②mixed 時のみリボン直下 y0.912 右寄せ `Mixed final + provisional runs` ③**注記4行**（8.5pt bold amber・`Not final DB integration` / `Original setup data not merged` / `Run numbers are provisional` / `For race-weekend engineering review only`）。既存要素の座標は一切不変。 |
| リボン位置（目視調整・readiness §2.2 許容範囲内） | readiness 想定の y≈0.83-0.92 は Title 31pt テキスト（x≈0.05-0.71）と衝突するため、**タイトル帯最上段 y0.930-0.988 へ移動**（何とも重ならず、より prominent）。注記4行も Scope カード直下（0.085-0.045）は物理的に入らないため、**KPI カード下端(0.505)〜Scope カード上端(0.445) の空き帯 y0.4975-0.451** に配置（readiness「実装時に目視調整」条項）。レンダリング PNG で衝突なしを目視確認済み。 |
| `_detect_provisional(df, provisional)`（新規・`_add_cover_slide` 直前） | readiness §1.2 の自動検出安全網: `PROV_` run 検出で `provisional=True` へ強制昇格・`mixed = PROV あり and 全 run 未満`。CLI（`main` は provisional 非対応のまま）経路も自動保護。 |
| `build_report_v2`（旧 L781） | kwarg `provisional=False` 追加 → run_ids フィルタ直後に `_detect_provisional` → `chart_cover(..., provisional, mixed)` → ファイル名 `prov_tok = "PROVISIONAL_" if provisional else ""` を `{ts}` 直前に挿入（旧 L849-850）。 |
| `build_report_pdf`（旧 L961） | 同上（cover 旧 L983 / ファイル名 旧 L999-1000）。 |

- final-only（provisional=False）はファイル名文字列生成が現行と byte 一致・cover 描画も従来パスのみ → **無回帰**。

### 1.2 `ts24_workbench.py`（`_on_create_report`・旧 L3458-3470）

- §55 の暫定 warning（「Task 6 未実装・提出禁止」）を **`QMessageBox.question`** に置換:
  「選択 Run に provisional（速報・未確定）が N 件含まれます。provisional reportとして生成しますか？（cover に PROVISIONAL 表記・ファイル名に _PROVISIONAL_ が付きます）」
  Yes | Cancel・**既定 Cancel**。Yes → `provisional=True`。
- `build_report_v2(...)` / `build_report_pdf(...)` の呼出し2箇所へ `provisional=provisional` を伝播。
- final-only 選択はダイアログなし・`provisional=False` で現行と完全同一動作。

---

## 2. サンプル（`reports/pptx/`）

| ファイル | 内容 |
|---|---|
| `suspension_report_v2_MISANO_JA52_FP_PROVISIONAL_20260707_PROVSAMPLE.pptx` | provisional 3 runs / 15 laps・**14 スライド** |
| `suspension_report_v2_MISANO_JA52_FP_PROVISIONAL_20260707_PROVSAMPLE.pdf` | 同内容 単一 PDF |
| `suspension_report_v2_JEREZ_DA77_TEST1_DAY1_20260707_FINALREG.pptx` | final-only 回帰（7 runs / 66 laps・**18 スライド** = §48 と同構成） |
| `suspension_report_v2_JEREZ_DA77_TEST1_DAY1_20260707_FINALREG.pdf` | 同内容 単一 PDF |

- provisional サンプルは関数呼出しで生成（`lap_suspension_provisional` を mode=ro で読込 → `provisional=True`）。
  自動検出単体も確認: 明示フラグ無しで `_detect_provisional → (True, False)`（3 runs 全 PROV = mixed=False）。
- final-only サンプルは CLI（`--circuit JEREZ --rider DA77 --session TEST1_DAY1 --pdf`）で生成。

## 3. 検証結果（readiness §7 全8項目）

| # | 検証 | 結果 |
|---|---|---|
| 1 | `PYTHONPYCACHEPREFIX=/tmp/ts24_pycache python3 -m py_compile suspension_report.py ts24_workbench.py` | **PASS** |
| 2 | MISANO/JA52/FP サンプル PPTX+PDF 生成 | **PASS**（例外なし・両ファイル生成） |
| 3 | cover 画像レンダリング目視（PPTX スライド1画像を抽出して確認） | **PASS**（amber リボン `PROVISIONAL - SESSION DATA` + 注記4行が描画・既存要素と衝突なし・英語のみ） |
| 4 | ファイル名トークン | **PASS**（`..._MISANO_JA52_FP_PROVISIONAL_<TS>.pptx/.pdf`） |
| 5 | final-only 無回帰 | **PASS**（ファイル名に `_PROVISIONAL_` 無し・cover にリボン/注記なし（画像目視）・18 スライド構成不変・本文に "PROVISIONAL" 文字列 0） |
| 6 | CJK=0（§49） | **PASS**（provisional 14 スライド / final 18 スライド の全 shape+table テキスト走査で CJK 0。cover は画像＝目視で英語のみ確認） |
| 7 | offscreen Workbench smoke | **PASS**（7タブ・overlay df 1281行。PROV 3 run 選択 → `question` **1回**・既定 **Cancel**・Cancel で生成ゼロ。monkeypatch stub で Yes → `build_report_v2/pdf` 両方に `provisional=True` 伝播を確認。final-only 7 run → ダイアログ **0回**・`provisional=False` 伝播） |
| 8 | DB 不変 | **PASS**（before==after: 業務6 = runs275/laps1202/lap_suspension1202/race_results866/pdf_lap_times7613/v2_staging7710・provisional 3 = 12/79/79） |

- ※Yes 経路の実生成は UI からは行わず（readiness/タスク指定どおり）、関数直接呼出しサンプル（#2）で生成自体を担保。
- GUI 最終目視（実機で MISANO/JA52 選択 → Yes → PPTX 確認）は Tatsuki ローカル。

## 4. Rollback

- **2ファイルの diff revert のみ**（`suspension_report.py`: chart_cover 拡張 + `_detect_provisional` + 両 builder の kwarg/トークン / `ts24_workbench.py`: `_on_create_report` のダイアログブロック + 呼出し2箇所）。
- DB 関与ゼロ（read-only 出力整形。schema/行/queue 不変）。
- サンプル4ファイル（`reports/pptx/*_20260707_PROVSAMPLE.* / *_20260707_FINALREG.*`）は削除任意（superseded 残置可）。

## 5. Multi-agent operating check

- Report（実装）/ Workbench（UI seam）/ DB integrity（mode=ro・before==after 機械検証）/ Quality（CJK=0・cover 目視・回帰）/
  Operations（サンプル生成・ログ）を本セッションで遂行。Supervisor 観点 = 承認境界で停止済み:
  **FAIL 7 outing 救済 / Workbench Session Import ボタン（Task 4）/ Supabase（remote_extra 24 cleanup 含む）/
  DB Master 再生成・race_results 由来新シート / origin push（§48 以降の未コミット群含む）/ final化・provisional クリア（§50 Task 8）**
  は引き続き各別承認。
- 効率設計（§46d）: 過去調査（§54/§55/§59 readiness）を再利用し再調査なし・単一セッションで完結。

## 6. 未実施リスト（各別承認・不変）

1. FAIL 7 outing 救済/再解析（§53/§57）
2. Workbench Session Import ボタン（Task 4）
3. Supabase（remote_extra 24 cleanup 含む）
4. DB Master 再生成 / race_results 由来新シート
5. origin push（本2ファイル変更 + §48 以降の未コミット群）
6. final化・provisional クリア（Post-event full rebuild・§50 Task 8）
