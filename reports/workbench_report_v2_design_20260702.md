# Workbench Create Report v2 — 設計書（Phase A・read-only・GO不要）

- **日付:** 2026-07-02
- **担当:** Claude Code（Opus 4.8）
- **タスク:** `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-02）「Workbench Create Report v2」Phase A（設計のみ）。
- **入力要件:** Obsidian [[2026-07-02　Report Create System]]（Tatsuki のサンプル PPTX への改善指摘 6点）。
- **前タスク:** readiness `reports/workbench_suspension_report_readiness_20260702.md`（§45）/ DB full sync `reports/db_master_online_sync_apply_20260702.md`（§46e）。
- **結論:** 本 Phase A は **設計のみ**。`python-pptx` / `matplotlib` は依然未インストールのため実装は行わず、本設計書を作成して **Phase B（`Report v2 implementation GO`）で停止**。
  正本DB・コード・Excel は無変更（`build_excel_master.py` の未コミット変更＝§46e の LS_COLS 拡張は**一切触らない**）。

---

## 1. 現在地の確認（Phase A 手順1-2）

### 1a. git 作業ツリー（`phase2a-extraction-20260620` / HEAD `5651d97`）
- **未コミット変更（絶対に revert しない）:** `M build_excel_master.py`（§46e の LS_COLS 46→68 拡張）/ `M CLAUDE.md` / `M reports/round7_race_results_apply_dry_run_20260629.md`。
- 多数の untracked（instruction docs / TRN_*・reports・_backup_susp_speed_* 等）。**本タスクでは触らない。**
- Report v2 実装は新規 `suspension_report.py` + `ts24_workbench.py` への追加が中心で、上記未コミット変更とは独立。

### 1b. 依存（システム Python・venv 無し）
| 依存 | 状態 |
|---|---|
| `python-pptx` | ❌ 未インストール |
| `matplotlib` | ❌ 未インストール |
| `pandas` | ✅ 2.3.3 |
| `openpyxl` | ✅ 3.1.5 |

→ Phase A では install しない。実装は Phase C（GO後）。

## 2. サンプル v1 の構造分析（`sample_suspension_report_JEREZ_DA77_TEST1_DAY1_20260702.pptx` / inspect.ndjson より）

10スライド・**ネイティブ PPTX チャート**（python-pptx `add_chart`・bar/line 7枚）+ テーブル2枚。

| S | 内容 | 種別 |
|---|---|---|
| 1 | Title（Scope / Coverage カード） | text |
| 2 | Run overview（best/avg lap） | bar |
| 3 | Braking position 推移 | line |
| 4 | Braking speed | bar |
| 5 | Apex position 推移 | line |
| 6 | Exit position 推移 | line |
| 7 | (speed 推移) | line |
| 8 | (speed) | bar |
| 9 | Run Compare Table `Run｜Best｜Brk F pos｜Brk F dive｜Brk R reb｜Apex F pos｜Exit F reb｜Exit R abs` | 8×8 table |
| 10 | Data Quality `Metric group｜Null rate｜Meaning`（**「0%」問題のスライド**） | 7×3 table |

### 2a. Tatsuki 指摘（6点）と v1 の該当箇所
1. **グラフ内ラベルがグラフに被って読めない** → ネイティブ chart の data label / legend がプロット領域に重なっている。
2. **Lap time が `MM:SS,00` 形式でない** → `108.108` 等の生秒表示。
3. **表が分かりにくい**（特にヘッダ上部の数値説明不足・エリア色分け無し） → S9 の8×8表がヘッダ1行のみ・単位/意味なし・Braking/Apex/Exit の視覚区別なし。
4. **`0%` の意味が不明** → S10「Null rate 0%」が null率/coverage/missing のどれか不明。
5. **Run 総合比較に寄り、Run内 Lap by lap分析が不足** → S2-S8 は Run 集約中心。lap 単位の推移ページが薄い。
6. **全体的に視覚に訴えるグラフが不足** → 単純 bar/line 中心。

## 3. 設計判断（v2 の中核）

### 3a. ★チャートエンジン: matplotlib `Agg` 画像へ移行（ネイティブ chart から変更）
- **理由:** Tatsuki 指摘 #1（ラベル衝突）・#6（視覚強化）・#5（lap-by-lap small multiples）は、**ラベル/凡例の座標を精密制御**でき、
  **small multiples・注釈・エリア色帯・軸の `MM:SS,CC` フォーマッタ**を自在に置ける matplotlib の方が根本解決に向く。ネイティブ chart は PowerPoint 依存で
  data label 衝突の制御が弱い。タスク Phase C も matplotlib を明示。
- **方針:** matplotlib `Agg`（GUI 非依存）で PNG を生成 → python-pptx で貼付。**表はネイティブ table**（セル塗りで色分けできるため）。
- 例外: 単純な KPI カード（best/avg lap 等）はテキストボックスで可。

### 3b. Lap time フォーマッタ仕様（指摘 #2）
```python
def format_lap_time(sec: float | None) -> str:
    # 例: 103.739 -> "1:43,74" / 68.5 -> "1:08,50" / None,<=0 -> "n/a"
    if sec is None or sec != sec or sec <= 0:
        return "n/a"
    m = int(sec) // 60
    rem = sec - m * 60                    # 秒（小数含む）
    cs = round(rem * 100)                 # センチ秒へ丸め
    if cs == 6000:                        # 59.995 の繰り上げ対策
        m += 1; cs = 0
    return f"{m}:{cs//100:02d},{cs%100:02d}"   # M:SS,CC（欧州式カンマ小数）
```
- 形式 = **`M:SS,CC`**（分ゼロ埋めなし・秒2桁・カンマ小数・センチ秒）。タスク例 `103.739 → 1:43,74` と一致。
- 適用先: 全チャートの time 軸ティック・テーブルの Best/Lap time セル・データラベル。
- 必要時、生秒（`108.108s`）を小さく併記可（tooltip 的注記）。**既存 workbench `_fmt_lap`（`1'43.74`）とは別関数**として新設（用途が異なる・上書きしない）。

### 3c. ラベル衝突回避（指摘 #1）
- **data label はプロット内に置かない。** 値はテーブル/コールアウト（プロット外の余白）へ分離。
- 凡例は `bbox_to_anchor` でプロット外（右 or 下）へ。ラベルは短縮（例 `DA77 SP R1`）。
- `constrained_layout=True` or `tight_layout` + 明示 `subplots_adjust` で余白確保。棒グラフの値は棒の外側 or 隣接表。
- ライン系は run 数が多いと凡例肥大 → **最大 N=6 run/グラフ**、超過は「+K runs（表参照）」と注記（silent 切り捨て禁止・§20 運用）。

### 3d. テーブル改善（指摘 #3）
- **ヘッダを2行化:** 1行目=列グループ（`Lap time` / `Braking` / `Apex` / `Exit`）、2行目=指標名＋**単位**（`Best [M:SS,CC]` / `F pos [mm]` / `F dive [idx]`）。
- **エリア色分け（セル塗り）:** Braking 列群=薄赤 `#FBE9E7`（見出し `#C0392B`）、Apex 列群=薄青 `#E8F1FB`（`#0078D4`）、Exit 列群=薄緑 `#E9F6EE`（`#2E9E4F`）。
- 表上部に**凡例/説明行**（`idx = relative damping-speed index (mm/s, uncalibrated) — not vehicle speed`／`n/a = data not available`）。
- 数値は右寄せ・小数桁統一（pos=1桁 mm・speed=0-1桁 idx）。

### 3e. `0%` の意味を明確化（指摘 #4）— Data Quality スライド再設計
- 「Null rate」単独表記をやめ、指標ごとに **3つを分離明示**:
  - **Missing / Null rate**: 値が NULL のラップ割合。`Missing 0% (all N laps populated)` のように**説明文＋分母**を併記。
  - **Coverage**: 有効ラップ / 全ラップ（lap_time 60–300s 通過率）。
  - **Structural n/a**: 構造的に存在しない（例 Exit=CORNER_EXIT 希薄・§19/§43）→ `n/a (structural: sparse CORNER_EXIT)` と NULL と区別。
- サンプル不足（avg n<5 / peak n<10・§44）は `low-sample (n<5)` と注記。外れ値（p95 で抑制済み・§43）は該当時 warning。

### 3f. カラーシステム（指摘 #6・UIと一致）
- Braking=`#C0392B`（red）/ Apex=`#0078D4`（blue）/ Exit=`#2E9E4F`（green）。`PhaseRunCompareWidget._PHASE_COLORS` と一致。
- 全チャート・全テーブル・見出しで一貫使用（フェーズを色で即認知）。

## 4. Report v2 スライド構成（拡張・~15スライド）

| # | スライド | 目的 | 主データ | 改善点 |
|---|---|---|---|---|
| 1 | Title / Scope | Circuit/Rider/Session/選択Run/生成時刻 | filter | — |
| 2 | **Data Quality & Coverage** | Missing/Coverage/Structural を明示 | 集計 | #4 |
| 3 | Run Overview | best/avg lap（`M:SS,CC`・ラベル外側） | lap_suspension | #1#2 |
| 4 | Run Comparison Summary | Braking/Apex/Exit の F/R を color-coded 棒 | 集計 | #3#6 |
| 5 | Braking Phase Summary | Braking F/R position + speed（F dive / R reb） | brk_* | #6 |
| 6 | Apex Phase Summary | Apex F/R position + speed（dive/reb） | apex_* | #6 |
| 7 | Exit Phase Summary | Exit F/R position + speed（ce_f_reb / ce_r） | ce_* | #6 |
| 8 | **Lap-by-lap: Lap time progression** | X=lap_no・best lap 線・best 差 | per-lap | #5 |
| 9 | **Lap-by-lap: Phase position progression** | Braking/Apex/Exit F/R を lap 毎 | per-lap | #5 |
| 10 | **Lap-by-lap: Phase suspension speed progression** | 方向別 speed を lap 毎 | per-lap | #5 |
| 11-N | **Run detail pages**（選択Run毎 or best/reference run） | small multiples で1 run を精査 | per-lap | #5#6 |
| 末-1 | Run Compare Table | color-coded・単位/説明付き | 集計 | #3 |
| 末 | Data limits / missing coverage | 構造的欠損・注意事項 | — | #4 |

- **ページ増加可**（タスク許可）。Run detail は「選択 run が多い時は best/reference run に限定＋残りは注記」。

## 5. Lap by lap 分析 最小仕様（Phase A 手順5）

- **X 軸 = `lap_no`**（run 内）。
- **series:** lap time（`M:SS,CC`）/ best lap との差 [s]（Δ）/ Braking F・R pos [mm] / Apex F・R pos / Exit F・R pos /
  Braking F dive・R reb speed [idx] / Apex F/R dive・reb speed / Exit F reb・R speed。
- **best lap 定義:** run 内の valid lap（lap_time 60–300s）最小。**推奨強化:** `laps.is_outlap`（lap_suspension には無い・`laps` に有り→ `lap_id` JOIN）で out/in ラップ除外可。MVP は 60–300s フィルタ、is_outlap JOIN は任意強化。
- **表示形態:** run 毎の **small multiples**（1 run = 小パネル群）、または選択 run の詳細ページ。**138/158 run が3周以上**（最大35周）＝ lap-by-lap は十分成立。
- **欠損:** `n/a`（構造的 not available）と `NULL`（データ欠落）と `0`（実測ゼロ）を明確に区別。0 を欠損として描かない（§19/§44 の鉄則）。

## 6. Workbench 接続（Phase C・GO後）

- `PhaseRunCompareWidget`（🔧 3フェーズ Run比較・`ts24_workbench.py` L3059）フィルタバーに **`📄 Create Report v2`** ボタン追加（`fb.addStretch()` 前）。
- ハンドラ `_on_create_report_v2()`:
  1. `df = self._base_df()`（circuit/rider/session フィルタ+lap_time レンジ済）、`run_ids = self._checked_run_ids()`。
  2. run 未選択 → message box「Run を1つ以上選択」。
  3. 生成中は status text 表示 → `suspension_report.build_report_v2(df, run_ids, filters, out_dir)`。
  4. 成功=出力パスを message box/status。失敗=例外捕捉し message box（**アプリを落とさない**・既存タブ無回帰）。
- 既存 `_PHASE_POS`/`_PHASE_SPD`/`_PHASE_COLORS` を helper に渡し UI と定義一致。

## 7. モジュール設計（`suspension_report.py`・新規）

- **純関数（単体テスト可）:** `format_lap_time` / `load_lap_suspension(db_ro, filters, run_ids)` / `session_summary` /
  `phase_stats(df, phase)` / `lap_by_lap_series(df, run_id)` / `run_compare_rows` / `data_quality(df)`。
- **描画:** `chart_*(...) -> Path`（matplotlib Agg・PNG・§3c ラベル制御・§3f 色）。
- **組立:** `build_report_v2(df, run_ids, filters, out_dir) -> Path`（python-pptx・§4 スライド・§3d 色分けテーブル）。
- **import guard:** `python-pptx`/`matplotlib` 未導入時 `ReportUnavailableError` → Workbench で message box（アプリ継続）。
- **DB:** `file:...?mode=ro`（read-only）。主ソース= `lap_suspension`（自己内包で JOIN 不要）。`race_results`/`race_lap_detail` は必要時のみ read-only。**正本DB schema 変更・書込は禁止。**

## 8. 出力 / 命名

- ディレクトリ: `05_SCRIPTS/reports/pptx/`（既存）。
- ファイル名: `suspension_report_v2_<circuit>_<rider>_<session>_<YYYYMMDD_HHMMSS>.pptx`（timestamp・上書きなし）。
- v1 サンプルは残し、old/new 差分を apply report に記録（タスク Phase C 手順6）。

## 9. 検証計画（Phase C）

- `python3 -m py_compile ts24_workbench.py suspension_report.py`（`PYTHONPYCACHEPREFIX=/tmp/ts24_pycache`）。
- helper 直呼びでサンプル1本生成 → 存在・サイズ>0 → python-pptx で **slide 数（≥12）** 確認。
- 可能なら PPTX→PNG/PDF レンダで目視/自動: ①ラベル重なり大幅減 ②lap time が `M:SS,CC` ③Braking/Apex/Exit 色分け ④lap-by-lap ページ存在 ⑤`0%` の意味説明。
- offscreen smoke（`QT_QPA_PLATFORM=offscreen`）: Workbench 起動 → `PostureAnalysisTab` → `🔧 3フェーズ Run比較` → `Create Report v2` ボタン存在 → 既存グラフ無回帰。
- GUI 目視は Tatsuki ローカル。

## 10. rollback

| 対象 | rollback |
|---|---|
| `suspension_report.py` | 新規ファイル削除 |
| `ts24_workbench.py` | ボタン追加分を revert（col-guard 済で新列無くても起動可） |
| 依存 | `pip uninstall python-pptx matplotlib`（環境影響は事前に version 記録） |
| 生成 pptx | reports/pptx 配下・timestamp 付きで既存を上書きしない |
- 正本DB・Excel・Supabase は本タスクで無変更（rollback 対象外）。

## 11. 必要 dependency（Phase C・GO後 install）
```text
python-pptx>=0.6.23
matplotlib>=3.7.0
```
- `requirements_workbench.txt` 追記案（§45 と同）。ネットワーク install は承認境界。

## 12. Multi-agent operating check

| エージェント | Phase A 実施 |
|---|---|
| Report/PPT | v1 サンプル10スライド構造を inspect.ndjson から解析し v2 15スライド構成を設計 |
| Data | `lap_suspension` 自己内包・per-lap 分布（138/158 run≥3周）・is_outlap は laps JOIN を確認 |
| Dynamics | Braking/Apex/Exit 指標解釈・relative damping-speed index（車速 km/h 非混同）を注記方針に反映 |
| Workbench/UI | `_base_df`/`_checked_run_ids` 再利用・非クラッシュ方針を設計 |
| Visual QA | ラベル衝突回避（matplotlib 移行）・色分け・テーブル可読性の具体策を定義 |
| Quality Gate | py_compile/slide count/offscreen/rollback を §9-10 に定義。deps 欠落を検出 |
| Supervisor | install/コード編集を **Phase B `Report v2 implementation GO`** に保持。DB write/Supabase/DB Master/push/新2D を別承認に保持 |

## 13. Phase B ゲート（次アクション）

Phase A 設計完了 → Tatsuki へ確認:
```text
Report v2 の設計確認が完了しました。設計は reports/workbench_report_v2_design_20260702.md に記録済みです。
python-pptx / matplotlib の導入、Workbench Create Report 実装、Report v2 PPTX 生成まで進めてよいですか？
実行する場合は「Report v2 implementation GO」と明示してください。
```
- GO 受領時のみ Phase C（install → `suspension_report.py` → Workbench ボタン → サンプル生成 → 検証 → `reports/workbench_report_v2_apply_20260702.md`）。
- GO 無しなら本設計書まで停止。

## 14. スコープ外（禁止遵守）

- dependency install / Workbench 編集 / PPTX 正式生成（GO 前）/ 正本DB schema 変更・行更新 / Supabase sync・cleanup /
  DB Master 再生成 / origin push / 新2D取込 / remote_extra 24 cleanup / `build_excel_master.py` 未コミット変更への干渉。
- 新規: `reports/workbench_report_v2_design_20260702.md`（本ファイル）。
