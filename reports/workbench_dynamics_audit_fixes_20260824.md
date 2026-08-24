# Workbench Motorcycle Dynamics 監査 — 指摘5件の修正 + FKR 力換算実装

- 日付: 2026-08-24
- 契機: **Codex による Motorcycle Dynamics KB ベースの監査**（`workbench_setup_diff_damping_dist_apply_20260824.md` 対象）
- 対象: `05_SCRIPTS/ts24_workbench.py` のみ + `04_REFERENCE/fkr_damping_library.json`（新規）
- 種別: read-only UI 修正。**DB 書込ゼロ・スキーマ変更なし**

## 0. 結論

**Codex の指摘は 5 件すべて妥当。全件修正した。** うち 1 件（減衰カーブ overlay）は機能そのものを撤回・無効化した。
あわせて、私が実装報告に書いた **「FKR PDF にカーブは含まれない」は誤りであり訂正した**。

---

## 1. 減衰カーブ overlay を無効化（監査 §1）— 機能撤回

**指摘**: Workbench の X 軸は未校正の「相対ダンピング速度指数」、dyno カーブは校正済み shaft velocity。
実装（`ts24_workbench.py`）は両者を同一 X 軸へリンクしていた。既存監査
`report_v2_feedback_audit_20260708.md` も「TS24 値を Öhlins の速度軸へ載せられない」と結論済み。

**判定: 妥当。** これは私の設計ミスである。しかも自分で書いた
`fkr_damping_curve_prep_20260824.md` §4 で「そのまま重ねてはならない」と述べながら、
Workbench 側の overlay を有効なまま残していた（自己矛盾）。

**修正**:

```python
CURVE_OVERLAY_ENABLED = False   # 恒久無効
```

- `_load_curves()` は常に `None` を返す（右軸描画コードへ到達しない）
- UI に REFERENCE_REQUIRED を明示表示:

```text
REFERENCE_REQUIRED
topic: calibrated damper shaft velocity
required_information: front/rear sensor calibration, linkage conversion,
                      sampling-time calibration
reason: relative index cannot share an axis with dyno velocity
```

**再有効化の条件**: ①フロント/リアのセンサー校正 ②リンク比換算 ③サンプリング時間校正。
③の構造的バイアスは `fkr_damping_curve_prep_20260824.md` §4.1 に記載（距離グリッド上の平均 dt 仮定）。
唯一の不足入力は**コース長**（§4.2）。

### 1b. ⚠ 私の誤りの訂正 — FKR PDF にカーブは存在する

実装報告に「同 PDF は C101–C106 のシムスタック部品表であり力-速度カーブを含まない」と書いたが、
**これは誤り**。PDF の **2 ページ目に Compression / Rebound の Force–Velocity グラフ**がある
（C101–C106 / R101–R106 @ click 14・0–1.0 m/s・0–2000 N）。初回抽出でテキスト層のみを読み、
ベクター図を見落とした。`fkr_damping_curve_prep_20260824.md` と
`workbench_setup_diff_damping_dist_apply_20260824.md` の該当箇所を訂正済み。

---

## 2. peak 定義の誤表示（監査 §2）

**指摘**: UI が全チャンネルを「peak（ラップ p95）」と表示していたが、
`brk_f_dive_spd_peak` は **MAX**（凍結列・[build_master_db.py:309](../build_master_db.py:309)）、
新 22 列の `*_peak` は **p95**（同 :333）。MAX と p95 を同じ分布として比較できない。

**判定: 妥当。** コードを確認し裏付けた。12 チャンネル中 1 本のみが MAX である。

**修正**: `_CHANNELS` に 4 番目の要素として peak の定義（`"MAX"` / `"p95"`）を持たせ、
`_sync_peak_label()` でチャンネル選択のたびにラベルと注記を更新する。

| 選択チャンネル | コンボ表示 | 注記 |
|---|---|---|
| Braking F dive | `peak（ラップ MAX）` | ⚠ 本列のみ MAX（凍結列）であり、他チャンネルの p95 とは定義が異なる。**定義をまたいだ分布比較は不可** |
| 他 11 チャンネル | `peak（ラップ p95）` | p95 は方向サンプル n≥10 のラップのみ。n 不足は DB で NULL |

凡例も `peak(MAX)` / `peak(p95)` と定義付きで表示する。

---

## 3. 「単一変数＝帰属可能」は強すぎる（監査 §3）

**指摘**: Setup Diff は TYRE と COND を交絡数から除外しているため、タイヤや路面温度が変わっていても
FRONT/REAR 変更が 1 項目なら「この差は帰属可能」と表示していた。

**判定: 妥当。** バナーが**記述**（差分の数）を超えて**因果の主張**をしていた。

**修正**: バナーは**記録上の差分件数のみ**を述べ、帰属を主張しない。加えて未統制項目を列挙する。

| 差分数 | 修正前 | 修正後 |
|---|---|---|
| 0 | セット項目の差分なし | 記録上の FRONT/REAR 変更は **0 項目**（走行条件のみ、または同一設定）+ 未統制の差分列挙 |
| 1 | ✅ 単一変数比較 — **帰属可能です** | 記録上の FRONT/REAR 変更は **1 項目**。ただしタイヤ・コンディション・ライダー・走行フェーズ等を統制していないため、**効果の帰属は未確定**。+ 未統制の差分列挙 |
| 2+ | ⚠ N 変数を同時変更 — 帰属不能 | ⚠ 記録上の FRONT/REAR 変更は **N 項目**（同時変更）。…さらにタイヤ・コンディション等も統制されていません。+ 未統制の差分列挙 |

タブ上部の説明文も「バナーは**記録上の設定差分の数**のみを述べ、**効果の帰属は主張しない**」に変更。

---

## 4. `ph12_rear0_s` を「リア荷重ゼロ」と扱わない（監査 §4）

**指摘**: 実体は `SUSP_REAR <= 0 mm` の時間であり、後輪法線荷重 Nr=0 を計算した値ではない。

**判定: 妥当。** 実装（[build_master_db.py:318](../build_master_db.py:318)）は
`BRAKE_FRONT >= 0.3 bar かつ SUSP_REAR <= 0.0 mm` の累積秒であり、荷重は計算していない。

**修正（Workbench UI）**:

- パネル名: 「PH1-2 Rear@0mm 累積秒」→ **「PH1-2 リアサス位置≤0mm 滞在時間」**
- ヘルプから「リアが浮く＝荷重が乗っていない時間」を削除し、以下に置換:

```text
⚠ これは **サス位置が閾値以下だった時間** であり、
   後輪法線荷重 Nr=0 を計算した値ではない。
   リア接地喪失の代理として断定しないこと。
   Nr=0 の判定には wheel-load モデル（重心高・前後位置）が要る。
   0mm のゼロ点がイベント間で同一かも未確認。
```

- Setup Diff の指標ラベル: `PH1-2 rear0 [s]` → `PH1-2 R位置≤0mm [s]`
- 別イベント比較の警告に「本指標はサス位置の滞在時間であり、リア接地喪失（Nr=0）そのものではありません」を追加

**未対応（別作業）**: Obsidian `12_TACIT_KNOWLEDGE/Diagnosis_Principles.md` および
`Suspension_Position_And_Speed_Indicators.md` の「リア荷重ゼロ時間」「リア接地不足の支持」という記述。
Vault は Codex の運用領域のため、本作業では Workbench UI のみ修正した。**Vault 側の改称を推奨する。**

---

## 5. Pitch / Heave は車体 pitch/heave ではない（監査 §6）

**指摘**: `pitch = SUSP_FRONT − SUSP_REAR` / `heave = (SUSP_FRONT + SUSP_REAR)/2` は前後で異なるセンサー座標を
そのまま引き算・平均しており、物理的な pitch/heave ではない。さらに UI が「均等荷重」「高荷重」
「タイヤ摩耗で荷重増加」まで断定していた。

**判定: 妥当。** フォーク変位とショック変位はストローク・方向・リンク比が異なる。

**修正（Rider Fingerprint のヘルプ）**: 冒頭に警告を追加し、荷重解釈を削除:

```text
⚠ Pitch / Heave は車体の pitch / heave ではない。
   フォーク変位とショック変位はストローク・方向・リンク比が
   異なるため、これは **位置差 / 位置平均の proxy** である。
   荷重の大小として解釈しないこと（リンク比・rake・
   wheelbase を用いた座標変換が未実装）。

・Pitch proxy (SusF−SusR)   外側 = 前後の沈み込み差が小さい
・Heave proxy = (SusF+SusR)/2   外側 = 位置平均が小さい
```

**未対応（別作業・DB 再計算を伴う）**: 監査 §5 の Front WheelForce Proxy
（`(F_SPR_L + F_SPR_R)/2` は並列バネの合計 `k_L + k_R` の半分）と、`SUSP_REAR` のセンサー座標
（ショック変位なら LR=2、車輪変位なら比率の二乗）。Codex の指摘どおり**式とセンサー座標を確定した上で
別作業**とする。本作業では計算式に触れていない。

---

## 6. ジオメトリモデルの位置づけ（監査 補足）

**指摘**: 2 点較正の `ASSUMPTION`。「±0.2 mm」は独立検証精度ではなく較正点への再現誤差。

**判定: 妥当。** UI 表記を修正:

> GEO 行は実測値ではなく**モデル導出値（ASSUMPTION）**。±0.2mm は独立検証精度ではなく
> **較正点への再現誤差**（2 点較正）であり、**0.3mm 未満の差は解釈しないこと**。

---

## 7. FKR ダンパーライブラリを「セット側の力換算」として実装

overlay は不可だが、**ライブラリ自体は別用途で完全に有効**である。用途を 2 つに分離した。

| 用途 | 判定 | 状態 |
|---|---|---|
| 速度軸への overlay | **不可** — 未校正指数と校正済み shaft velocity は同一軸に載らない | 恒久無効化 |
| **セット側の力換算** — (valve code, click) → 指定 shaft velocity での力 | **可** — 2D テレメトリに一切触れない | **実装** |

後者は 2D の速度指数を使わない。「この設定は 0.3 m/s の shaft 速度で何 N 出るか」という
**セット固有の性質**であり、校正問題と無関係である。

### 実装

- `04_REFERENCE/fkr_damping_library.json`（228 本 = C101–C106 / R101–R106 × click 6–24）。
  出典 = interactive xlsm の `InData`。**ファイル名は overlay スロットの `damping_curves.json` と意図的に分離**
- `FKRDamperLibrary` クラス（read-only・線形補間・参照速度 0.1 / 0.3 m/s）
- 配線 3 箇所:
  - **Setup Diff** に `DAMP` 群（F 圧側/伸側 @0.1・0.3 m/s + バルブコード）
  - **ラップ詳細のセットアップパネル**に `F 減衰力 (FKR dyno)` 行
  - **Comment Analysis** に `F reb@0.3 [N]` 列
- **フロントのみ**。リアショックは別体系（C4x/R4x）で本ライブラリに収載なし → `—` 表示

### 実測例（Donington vs 好走決勝）

| Run | comp / reb key | F 圧@0.1 | F 伸@0.1 | **F 伸@0.3** |
|---|---|---:|---:|---:|
| R8 Donington RACE1 | C106_20 / R104_21 | 100 N | 76 N | **298 N** |
| R4 Balaton RACE1（P4 / 0.028） | C104_20 / R104_18 | 99 N | 85 N | 332 N（+11%） |
| R7 Misano RACE2（P5 / 0.275） | C104_16 / R104_12 | 119 N | 126 N | 442 N（+48%） |

「reb 21 vs 12」という比較不能な clicker が、実測ニュートンになった。
なお Donington の 298 N は **JA52 の 2026 シーズン全体で最小**（範囲 298–486 N）。
ただし Donington は**季最良の結果**でもあるため、これは「弱い伸側は遅い」を意味しない
（詳細と留意 = `fkr_damping_curve_prep_20260824.md` §3）。

---

## 8. 検証

| 項目 | 結果 |
|---|---|
| `py_compile` | PASS |
| offscreen 全タブ巡回（main 7 + posture 5） | PASS |
| 減衰カーブ | `CURVE_OVERLAY_ENABLED=False` / `_load_curves()` → `None` / REFERENCE_REQUIRED 表示 |
| peak ラベル | ch0 = `peak（ラップ MAX）`+ 定義差警告 / ch1 = `peak（ラップ p95）` |
| 交絡バナー | 「記録上の FRONT/REAR 変更は N 項目」＋未統制列挙・帰属主張なし |
| FKR 力換算 | 228 本読込 / R104_21=298.5 N / R104_18=331.5 N / R104_12=441.5 N / C45(別体系)=None |
| Comment Analysis | `F reb@0.3 [N]` 列に 298 表示 |
| **DB SHA-256** | **不変** |
| **業務テーブル件数** | **不変**（302 / 1423 / 1423 / 940） |

バックアップ: `ts24_workbench.py.bak2_*`（session scratchpad）

---

## 9. 未対応（別作業として残す）

Codex の優先順位「overlay 停止 → peak 表示 → 因果帰属 → `ph12_rear0_s` → WheelForce/Pitch/Heave 再定義」のうち、
**前 4 件は完了**。最後の 1 件は分割した。

| 項目 | 本作業 | 残 |
|---|---|---|
| Pitch / Heave | UI の断定表現を弱化（完了） | リンク比・rake・wheelbase を用いた座標変換（未実装） |
| Front WheelForce Proxy | **触れていない** | `(k_L+k_R)/2` → `k_L+k_R` の是正。**DB 再計算を伴うため式確定後の別作業** |
| Rear WheelForce ×0.5 | **触れていない** | `SUSP_REAR` のセンサー座標（ショック変位 or 車輪変位）確定が前提 = `REFERENCE_REQUIRED` |
| Obsidian の `ph12_rear0_s` 記述 | Workbench UI のみ修正 | Vault 側の改称（Codex 領域） |
| 速度軸の校正 | — | コース長入手 → 補正係数 → overlay 再検討 |
| Motorcycle Dynamics unit test | — | Setup Diff / Damping 分布に専用テストが無い（Quality Gate も未検出） |

---

## 10. 所見

Codex の監査は正確で、**5 件すべてが実際の欠陥**だった。とくに §1 は、
私が同じ日に自分で書いた prep レポート §4 で「重ねてはならない」と述べながら Workbench 側で重ねていた
自己矛盾であり、指摘されなければ工学判断に使われていた。

Quality Gate がこの種の**物理的誤用**を検出できていない点も Codex の指摘どおりである。
Setup Diff / Damping 分布に対する Motorcycle Dynamics 専用テストは存在せず、
今回の検出は人手（Codex）の監査に依存した。
