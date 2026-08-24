# Workbench 拡張 — Setup Diff / Damping 分布 / コメント↔セット結合 — APPLY 記録

- 日付: 2026-08-24
- 対象: `05_SCRIPTS/ts24_workbench.py` のみ（+626 / −16 行・9486 行）
- 種別: **read-only UI 追加**。DB 書込ゼロ・スキーマ変更なし・SQL 追加は `mode=ro` の参照のみ
- 契機: T08 Front setups 意見書 rev.4 の作成過程で判明した「Workbench が答えられなかったこと」

## 背景

T08 の解析（NERO 30/+0.5 vs ROSSO 26/−0.5、OPZIONE A/B）で必要になった作業のうち、
Workbench で実行できたものは無く、すべて手作業の SQL と手計算だった。

| 必要だった作業 | 従来の Workbench |
|---|---|
| 2 assetto の trail 比較 | rake/trail/wheelbase が DB にも UI にも無い |
| offset 変更に何が同伴したかの特定 | run 間の設定差分機能が無い |
| 同一症状のときのフォーク構成の比較 | 全文検索はあるがセット状態と結合されない |
| TOS 188x8 が固定だった確認 | `r_tos_*` が UI に 1 箇所も存在しない |
| HP Insert（`f_offset2`）の確認 | 設定パネルに表示されていない |

## 変更内容

### 1. `SetupDiffWidget`（新規クラス）— 🦾 Suspension/Posture ▸ 「🆚 Setup Diff」

2 run の設定差分を全 27 項目 + 導出ジオメトリで比較し、**交絡バナー**で単一変数比較か否かを判定する。

- 群: FRONT / REAR / TYRE / COND。交絡判定は FRONT・REAR のみを数える
- バナー: 記録上の FRONT/REAR 差分**件数のみ**を述べる。**効果の帰属は主張しない**
  （2026-08-24 修正・Codex 監査 §3。未統制の TYRE/COND 差分も併記する）
- 成績デルタ: best lap・n laps・`brk_f_dive_spd_avg/peak`・`ph12_rear0_s` の run 平均
- 別イベント間の比較時は `ph12_rear0_s` の較正依存を警告表示
- 共通 Run Filter の影響を受けない独立コントロール（`_rf_on_tab_changed` を更新）

**検証例**（ROUND5 MOST・QP R3 → RACE1 R1）:

```text
⚠ 18 変数を同時変更 — 帰属不能
  F Spring 9/9 → 8/9 ・ F Preload 10 → 16 ・ F Comp 20 → 16 ・ F Reb 21 → 12
  Fork Offset 26 → 30 ・ HP Insert −0.5 → 0 ・ R Spring 88 → 80 ・ R TOS 150x8 → 120x12
  Link 6 → 5 ・ Swing arm 562 → 556 …
  GEO Rake 23.60° → 23.95°（+0.35） Trail 103.5 → 101.3（−2.25）
```

意見書 §6-4「A/B 比較の間はリア車高とフォーク内部を固定する」は、これで運用ルールではなく
ツールが走行前に提示する事実になる。

### 2. 導出ジオメトリ（`SetupDiffWidget.geometry_of`）

`f_offset` と `f_offset2` から rake / ground trail / normal trail をモデル計算する。

```text
rake  = 23.95 + 0.70 * insert
trail = (R*sin(rake) − offset) / cos(rake) ,  R = 301.75 mm
```

- 較正点: T08 実測 2 点 `(30, +0.5) → 24.3° / 103.4` と `(26, −0.5) → 23.6° / 103.3`
- **ASSUMPTION**（2 点較正）。±0.2mm は独立検証精度ではなく**較正点への再現誤差**。
  出典間の再現性（T08 と Cremona Test #07 で 0.1° / 0.2mm 差）と同オーダーのため、
  **0.3mm 未満の差は解釈しない**旨を UI に明記
- `f_offset2` は insert の**角度のみ**を保持し、OPZIONE A/B の「+2」に相当する線形成分を表現
  できない。線形成分を伴う構成では約 0.5mm 過大評価する（コメントに明記）
- 較正範囲（insert ±0.5）外は `extrapolated` を立て、UI に「⚠外挿」を表示（DA77 の −2 系が該当）
- **モデル値であり実測ではない**。実測値がある場合はそちらを優先すること

### 3. `DampingDistWidget`（新規クラス）— 「📉 Damping 分布」

既存 Damping/Phase は avg と peak の 2 点を推移表示するのみで、使用速度域の分布が失われている。
本タブは 12 チャンネル（3 フェーズ × F/R × dive/reb）のラップ単位分布を出す。

- 統計: avg / peak / avg+peak、bins 5–60、Rider 分割
- **peak の定義はチャンネル依存**: `brk_f_dive_spd_peak` のみ **MAX**（凍結列）、
  他 11 チャンネルは **p95(n≥10)**。UI が選択チャンネルごとにラベルを切替え、
  MAX 選択時は「定義をまたいだ分布比較は不可」を明示（2026-08-24 修正・Codex 監査 §2）
- 表示: median・p10・p90・max・n
- 共通 Run Filter に従う（`_update_all` から `set_dataframe` を呼ぶ）
- **注記**: DB は lap ごとの avg/peak しか持たないため、これは**ラップ単位の分布**であって
  サンプル単位のヒストグラムではない。速度は相対ダンピング速度指数で絶対 mm/s ではない

**減衰カーブスロット**（当初実装・後に撤回）:

> **⚠ 訂正 + 撤回（2026-08-24・Codex 監査）**
>
> 1. 「同 PDF は力-速度カーブを含まない」は **誤り**。PDF 2 ページ目に Compression /
>    Rebound の Force–Velocity グラフがある（テキスト層のみ抽出して見落とした）。
> 2. **overlay 機能そのものを撤回・無効化した**（`CURVE_OVERLAY_ENABLED = False`）。
>    本タブの X 軸は未校正の相対指数、dyno は校正済み shaft velocity であり、
>    同一軸に載せることは物理的に不正。既存監査
>    `report_v2_feedback_audit_20260708.md` の結論とも一致する。
> 3. 代替として、**セット側の力換算**（`FKRDamperLibrary`）を実装した。詳細は
>    `fkr_damping_curve_prep_20260824.md` §6 および
>    `workbench_dynamics_audit_fixes_20260824.md`。
※ Cremona Test #07 の "Diving is under control with **C106**" は、この valve code を指す。

### 4. 💬 Comment Analysis — セット状態の併記

コメント詳細表に `🔧 セット状態を併記` チェックボックス（既定 ON）を追加。ON で 6 列を挿入:

`F spr/pre/cmp/reb` / `Geo off/ins` / `Trail(model)` / `R spr/pre/cmp/reb` / `R TOS` / `Ride h`

OFF で従来の列構成に戻る。詳細クエリを `SELECT r.date,...` から `SELECT r.*` へ拡張。

**検証例**（意見書 §5.2 の論証がそのまま再現される）:

```text
"back quit fast"          → 20260710 DONINGTON FP JA52  9/11/20/21   30/0.5   trail 103.3  150x8
"comming back so fast"    → 20260313 CREMONA TEST5_DAY1 8.5/12/18/20 28/-0.5  trail 101.3  0x0
```

同一症状に対しフォーク構成とジオメトリが並ぶため、「幾何由来かダンピング由来か」の切り分けが
1 操作でできる。`Diagnosis_Principles` の固定マッピング禁止には抵触しない（共通項を並べるだけで
解を出さないため）。

### 5. ラップ詳細ダイアログ 🔧 セットアップパネル

従来非表示だった項目を追加:

- `Fork Offset / Insert`（`f_offset2` を初めて表示）
- `Geometry (model)` — rake / trail のモデル値
- `Shock Preload` / `Shock TOS len x spr` / `Link / Swing arm`

## 検証

| 項目 | 結果 |
|---|---|
| `py_compile` | PASS |
| offscreen 全タブ巡回（main 7 + posture 5） | PASS |
| ラップ詳細ダイアログ構築 | PASS（`Fork Offset / Insert = 30.0 mm / 0.5`、`rake 24.30° / trail 103.3mm`） |
| ジオメトリモデル vs 実測 | `30/+0.5` 誤差 −0.07mm、`26/−0.5` 誤差 +0.16mm |
| Comment 検索の結合表示 | PASS（上記 2 例） |
| Comment チェック OFF での旧列復帰 | PASS |
| Run Filter 表示制御 | tab 0/1/3 = 表示、2/4 = 非表示 |
| **後続監査** | Codex による Motorcycle Dynamics 監査で 5 件の修正 → `workbench_dynamics_audit_fixes_20260824.md` |
| **DB SHA-256** | **変更なし** |
| **業務 8 テーブル件数** | **変更なし**（runs 302 / laps 1423 / lap_suspension 1423 / race_results 940 / problem_log 4 / setup_decision_log 7 / import_queue 430 / source_file_registry 439） |

バックアップ: `ts24_workbench.py.bak_20260824_161541`（session scratchpad）

## 未実施（別途 GO が必要）

- **sag フィールドの追加**（`f_sag_static` / `f_sag_rider` / `r_sag_static` / `r_sag_rider`）。
  意見書 §5.2 の結論は「プリロード値ではなく sag 実測値が正しい比較対象」であり、これが最重要の
  欠損データ。ただし**正本 DB のスキーマ変更**にあたるため本作業では実施していない
- 指標の比較スコープ・メタデータ化（`ph12_rear0_s` の `SUSP_REAR` ゼロ点依存）。
  現状は Setup Diff の別イベント比較時の警告文のみ。**ゼロ点が伸び切りか静止姿勢かの確認が前提**
- 外部イベント登録（Test #06 / #07）。既存 `event_manifest` への `external` 種別追加を想定
- `setup_decision_log` の予測→検証ループ（`expected_metric` 等の列追加）
- 最小検出可能差の表示

## GUI 最終目視

`python3 ts24_workbench.py` を Tatsuki ローカルで実行し、以下を確認:

1. 🦾 Suspension/Posture に「📉 Damping 分布」「🆚 Setup Diff」の 2 タブが増えている
2. 🆚 Setup Diff で MOST の QP R3 → RACE1 R1 を選ぶと「⚠ 18 変数を同時変更」が出る
3. 💬 Comment Analysis でキーワード検索するとセット状態 6 列が併記される
4. 散布図のラップ点クリック → セットアップに Insert / TOS / Link / Geometry が出る
