# Workbench 3フェーズ Suspension Run Compare UI 追加 — 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01）/ ノート `2026-07-01 What still missing on Workbench` の要望に基づき、
`ts24_workbench.py` の `PostureAnalysisTab`（🦾 Suspension/Posture）に **3フェーズ Suspension Run Compare UI の MVP** を追加した。

**スコープ厳守**: 既存 DB 列のみ使用。DB schema 変更・正本DB 書込・派生データ再計算・2D 再処理・Supabase・origin push は**なし**。

---

## 1. 背景（Tatsuki 要望）

- 現 UI は Apex 中心の姿勢しか見えず、各フェーズごとの Position / サス速度変化が見えない。
- 見たいフェーズ = **Braking Area / Apex Area / Exit Area**。
- 各フェーズで **F/R Sus Position (mm)** と **F/R Sus Speed (mm/s)** を、**Lap by lap だけでなく Run単位・複数Run比較**で確認したい。
- 目的: セットアップ変更に伴うバイク姿勢変化の把握、ライダーコメント PH1-5 区分の活用。
- グラフ内で lap point（実測）と Run trend を同時に見たい。Position Graph と Speed Graph は分離してよい。

---

## 2. 実装前の read-only 確認

- HEAD `6861222`（branch `phase2a-extraction-20260620`・未push）。`git status` = `ts24_workbench.py` 未変更（作業前）。
- `python3 -m py_compile ts24_workbench.py` PASS。
- 正本DB `lap_suspension` の列と non-null 件数（`mode=ro`・total **1202**）:

| 用途 | 列（DB / DataFrameは小文字化） | non-null |
|---|---|---:|
| Braking F/R Position | `brk_susF_avg` / `brk_susR_avg` | 1082 / 1082 |
| Apex F/R Position | `apex_susF_avg` / `apex_susR_avg` | 1198 / 1198 |
| Exit F/R Position | `ce_susF_avg` / `ce_susR_avg` | 678 / 678 |
| Braking F サス速度（利用可） | `brk_f_dive_spd_avg` / `_peak` | 1072 / 1072 |
| Exit R サス速度（利用可） | `ce_r_spd_avg` / `ce_r_spd_peak` | 661 / 661 |
| 信頼度サンプル | `fullbrk_count` / `ce_count` | 1202 / 1202 |

- **run_id は run の一意キー**（`(circuit,rider,session,run_no)` と 1:1・全 158 runs）。
- 既存 `PostureAnalysisTab` 内部サブタブ = `📊 APEX分析（基本）` / `⚙️ Damping / Phase` の2枚。DataFrame は `lap_suspension` 全件を `_load_data` で読み、列名を全小文字化して保持。

### ★データ制約（重要）

- **3フェーズ×F/R のサス速度は DB 未整備**。実在するサス速度は **Braking F（`brk_f_dive_spd_*`）と Exit R（`ce_r_spd_*`）のみ**。
- `brk_spd_avg` / `apex_spd_avg` / `ce_spd_avg` は **車速（km/h）** であり、サス速度 (mm/s) ではない。
- → 本実装では **存在しないサス速度を車速で代用しない**。未整備側は `not available yet` / `n/a` と明示。

---

## 3. 実装内容

### 3a. 新ヘルパークラス `PhaseRunCompareWidget`（`ts24_workbench.py`）

`PostureAnalysisTab` を肥大化させないため独立クラス化。`PostureAnalysisTab` が読み込んだ DataFrame を
`set_dataframe()` で共有する（DB 二重読込なし）。pyqtgraph 無し環境ではプレースホルダ表示で安全に劣化。

**フィルタ（独自・上部バー）**: Circuit / Rider / Session / Phase(`All`/Braking/Apex/Exit) / Metric。
左ペインに **Run 複数選択リスト**（チェックボックス・`全選択`/`全解除`）。Circuit→Rider→Session の順に選択肢を連動再構築（選択は可能な限り保持）。既定はサーキット先頭 + 先頭最大4 Run を自動選択。

**Metric**: `F & R Position` / `F Position` / `R Position` / `Pitch = F−R` / `Heave = (F+R)/2`。

**グラフ（2×2）**:

1. **Position 推移（Lap by Lap + Run Trend）** — X=lap_no, Y=mm。選択フェーズの F/R（または Pitch/Heave）を、
   点＝各ラップ実測、線＝Run の trend（線形近似）で表示。色=Run で複数Run比較。
   `F & R` は F(実線●)/R(破線▲)を同時表示。`Phase=All` のときは Apex を表示（3フェーズ比較は下記2）。
2. **Phase Summary（Run単位 平均 F/R）** — X=各 Run, Y=平均 mm。Braking(赤)/Apex(青)/Exit(緑) を色分け、
   F(実線●)/R(破線▲)。`All` で3フェーズ同時、単一選択でそのフェーズのみ。Run 間の姿勢変化を俯瞰。
3. **Suspension Speed（利用可能な指標のみ）** — X=lap_no, Y=mm/s（相対指数）。**Braking F（F-Dive）と Exit R（R|v|）のみ**を
   avg(実線●)/peak(破線×)で表示。未整備フェーズ×側は描画せず、注記＋タイトルで `not available yet` を明示。
4. **数値テーブル** — Run ID / Rider / Circuit / Session / Run No / Lap / Lap Time / Phase / F pos / R pos /
   Pitch / Heave / F spd(idx) / R spd(idx)。`All` は 1 lap あたり 3 行（フェーズ別）。速度は `n/a`(未整備) / `—`(NULL) を区別。先頭 2000 行に制限。

**データ定義（要望どおり）**:
`Braking: brk_susF/R_avg`・`Apex: apex_susF/R_avg`・`Exit: ce_susF/R_avg`。
`Pitch = F − R`・`Heave = (F + R) / 2`。物理限界（F 130mm / R 70mm）超と lap_time 60–300s 外は除外。

### 3b. `PostureAnalysisTab` への配線

- `_setup_ui`: 内部サブタブに **`🔧 3フェーズ Run比較`** を追加（既存 `📊 APEX分析（基本）` / `⚙️ Damping / Phase` は不変）。
- `_load_data` 成功時: `self._phase_cmp.set_dataframe(self._df)` を呼び、サブタブへ同一 DataFrame を渡す（try/except で保護）。
- 外側 Circuit コンボ変更（`_update_all`）はサブタブに影響しない（サブタブは独自 Circuit フィルタ）。

### 変更ファイル
- `ts24_workbench.py`: import に `QListWidget, QListWidgetItem` 追加 / `PhaseRunCompareWidget` 新規 / `PostureAnalysisTab` に2箇所配線。
- 新規: 本レポート `reports/workbench_phase_run_compare_ui_20260701.md`。

---

## 4. 検証

- `python3 -m py_compile ts24_workbench.py` **PASS**。
- **offscreen スモークテスト**（`QT_QPA_PLATFORM=offscreen`）**全項目 PASS**:
  - 内部サブタブ = `['📊 APEX分析（基本）', '⚙️ Damping / Phase', '🔧 3フェーズ Run比較']`。
  - Circuit コンボ 8件（全/ARAGON/ASSEN/BALATON/JEREZ/MOST/PHILLIPISLAND/PORTIMAO・既定 ARAGON）、Rider(DA77/JA52)、Session(FP/QP/RACE1/RACE2/SP/WUP1/WUP2)。
  - ARAGON = 20 Run・既定4 Run 選択。テーブル 14列・既定 Apex で 42 行。
  - Phase×Metric 全組合せ（4×5）で例外なし。Apex 42行 → All 126行（=3フェーズ×）。
  - 全選択=20 Run/519 行、全解除=0 行。Circuit 切替（ASSEN=17 Run、全=157 Run）、`全` 経路 OK。
  - Exit フェーズ注記 = `利用可 = Braking F, Exit R ／ 未整備(not available yet) = Braking R, Apex F, Apex R, Exit F`。
  - **既存無回帰**: `tab.refresh()` OK・Damping/Phase テーブル 1081 行（従来どおり）。`MainWindow` 7タブ構築 OK。
- **GUI 目視（最終）は Tatsuki ローカル**（`python3 ts24_workbench.py` → 🦾 Suspension/Posture → 🔧 3フェーズ Run比較）:
  ①Circuit/Rider/Session/Run 選択で3グラフ+表が更新される ②複数Run が色分けで重なる ③Phase Summary で Braking/Apex/Exit の F/R が比較できる ④Speed グラフが Braking F と Exit R のみ表示し他は `not available yet` ⑤既存2サブタブが壊れていない、を確認。

---

## 5. Multi-agent operating check

- **Product/Suspension agent**: Braking/Apex/Exit の3フェーズ×F/R Position を Run単位・複数Run比較・lap point+trend で提示 → 要望充足。
- **DB/Data agent**: 既存列のみ使用。サス速度は実在する Braking F / Exit R のみ表示し、車速をサス速度と誤表示しない。未整備列は `not available yet`/`n/a` 明示。
- **Workbench/UI agent**: フィルタ（Circuit/Rider/Session/Run複数/Phase/Metric）・3グラフ+表・既存タブ無回帰。密度重視のオペレーショナルUI、既存色/構成に整合。
- **Quality Gate agent**: py_compile PASS・offscreen smoke 全項目 PASS・non-null件数整合（1202 / Braking1082 / Apex1198 / Exit678）・既存タブ無回帰。
- **Documentation/Handoff agent**: 本レポート / `CLAUDE.md` §42 / Obsidian log・handoff・current_state・inbox Result 更新。
- **Supervisor**: DB schema変更・正本DB書込・2D再処理・Supabase・origin push を別承認に保持（本タスクでは未実施）。

---

## 6. スコープ外（未実施・禁止遵守）

- 正本DB schema 変更 / `lap_suspension` への新列追加 / 3フェーズ×F/R サス速度の推測補完。
- 2D raw data の再処理 / DB Master 再生成 / Supabase cleanup・sync / origin push。

## 7. 次の別タスク候補

- **3フェーズ×F/R suspension speed 派生列の設計・dry-run**（要 Tatsuki 承認）。
  2D raw channel から phase 別 dive/rebound speed の定義を先に確定してから `build_master_db.py` の抽出に追加する。
  完成後、本 UI の Speed グラフを全フェーズ×F/R へ拡張できる（現状の `not available yet` 部分が埋まる）。
