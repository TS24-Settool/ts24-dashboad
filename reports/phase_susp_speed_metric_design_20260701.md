# 3フェーズ×F/R Suspension Speed 指標設計 + scratch feasibility — 2026-07-01 Claude Code

Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-01）の指示に基づく **設計 + scratch/read-only feasibility**。
**正本DB schema変更・本番 `build_master_db.py` ロジック変更・2D再処理・正本DB書込は一切なし**。
成果物はこの設計 report のみ。本番反映は Tatsuki の明示GO後の別タスク。

多エージェント設計レビュー（物理 / データ / 品質ゲート / UI の4レンズ）＋ 6主張の敵対的検証で、
本レポートの推奨は **ENDORSE WITH CHANGES**（実装可・下記6補正込み）に収束した。

---

## 1. 現状の不足（why）

Workbench `🔧 3フェーズ Run比較`（§42）の Speed グラフは、実在する **Braking F=`brk_f_dive_spd_*` / Exit R=`ce_r_spd_*`** の
2系統のみ表示し、残り **Braking R / Apex F / Apex R / Exit F** は `not available yet` になっている。
Tatsuki 要望は Braking / Apex / Exit の各フェーズで **F/R Suspension Speed (mm/s)** を Run単位で見ることなので、
3フェーズ×F/R×（圧縮/伸び）のサス速度指標を DB に用意する必要がある。

既存のサス速度列（`lap_suspension`, CLAUDE.md §18/§19）:

| 列 | 定義 | reducer |
|---|---|---|
| `f_dive_spd`/`f_reb_spd`/`r_dive_spd`/`r_reb_spd`（`laps`） | ラップ**全体**の F/R 圧縮/伸びピーク | max |
| `brk_f_dive_spd_avg`/`_peak` | **FULL_BRAKING** ゾーン × Front × 圧縮(v>0) | avg=mean / peak=max |
| `ce_r_spd_avg`/`_peak` | **CORNER_EXIT** ゾーン × Rear × **絶対値\|v\|** | avg=mean / peak=max |
| `ph12_rear0_s` | PH1-2 代理で SUSP_REAR≤0mm 累積秒 | — |

→ ゾーン限定は Braking-F（圧縮）と Exit-R（絶対値）の2セルしか無い。**3フェーズ×F/R×方向のマトリクスが未整備**。

---

## 2. 既存算出ロジック（read-only 確認・`build_master_db.py`）

`extract_outing()`（L187-319）が per-lap で全チャンネルを共通グリッド長 M に resample し（`R`）、
`dtg = lap_t / M`（グリッド1点あたり秒）を作る。

```python
# L273-296 抜粋（本番・不変）
def _vel(arr):                       # 位置[mm] → 速度[mm/s]（グリッドM上の微分）
    return np.gradient(arr) / dtg
def _zone_mask(area):                # AREAS[area] の全チャンネル条件 AND
    m = np.ones(M, bool)
    for ch,(lo,hi) in AREAS[area].items():
        if R.get(ch) is None: return None
        m &= (R[ch]>=lo)&(R[ch]<=hi)
    return m
# 既存 brk_f_dive: FULL_BRAKING × Front × 圧縮(v>0)、n>=5 二段ガード、avg=mean/peak=max
# 既存 ce_r     : CORNER_EXIT × Rear × abs(|v|)、n>=5、avg=mean/peak=max
```

- **フェーズ = 既存 AREAS マスク**（`build_master_db.py` L41-47）:
  Braking=`FULL_BRAKING`（BRAKE 9-20bar, SUSP_F 90-130mm, SUSP_R -0.5-2.0mm）/
  Apex=`MID_CORNER`（トレイルブレーキ〜中立）/ Exit=`CORNER_EXIT`（THROTTLE 50-100%, SUSP_F 0-70mm）。
- 速度は **相対ダンピング速度指数**（グリッドM上の `np.gradient/dtg`・**校正済み絶対 mm/s ではない**・
  モーションレシオ補正なし）。データセット内比較は正当、絶対速度・車速 km/h と混同禁止。
- null条件は **n>=5 の二段ガード**（ゾーンマスク n>=5 **かつ** 方向サブセット n>=5、未満は NULL・0は厳禁）。

---

## 3. scratch feasibility 結果（read-only・正本DB無変更）

**手順**: 本番 `build_master_db.py` を **import のみ**（ロジック不変）。低レベル parse 関数・`AREAS`・`_vel`/`_zone_mask` と
**同一コードパス**で、代表サンプル outing について「3フェーズ×F/R×{dive,reb,abs}×{avg,peak}」を再計算。
既存4列（`brk_f_dive_spd_avg/peak`, `ce_r_spd_avg/peak`）を同一パスで再計算し `bm.extract_outing()` と突合＝決定論ゲート。
scratch script = セッション scratchpad `scratch_phase_susp_speed_feasibility.py`（**正本DBは `mode=ro`・書込なし**）。

**サンプル**: ARAGON / ASSEN / JEREZ × DA77 / JA52 = **70 outing / 475 lap**。

### 3a. 決定論（複製の忠実性）
- 既存4列 × 475 lap = **1900 ペア突合 → 不一致 0（PASS ✅）**。
  → 私の再計算は本番 `extract_outing` と**ビット一致**。よってマトリクス18新セルも**同一 grid/velocity/mask 基盤**で算出される（構成上）。
- 正本DB `lap_suspension` 照合（`mode=ro`・sample circuit）: scratch distinct 値の正本カバー率 **98.9%**（`brk_f_dive_spd_avg`）/ **98.6%**（`ce_r_spd_avg`）。
  残 ~1% は本番ビルドが session 毎に一部 outing のみ採用（per_event 選抜）するのに対し scratch は全 outing を処理するため（欠陥ではない）。
- **検証スコープの正直な限界**（敵対的検証の caveat）: 1900/0 は既存4アンカーセルの直接証明。他18セルは**構成による**担保（共有 `_vel`/`_zone_mask`/同一グリッド）で直接測定ではない（本番に参照値が無いため）。本番反映時は **拡張後の full rebuild に対し決定論ゲートを再実行**すること。

### 3b. ゾーン成立率（n>=5・sample）
| フェーズ | zone | laps | n>=5 成立 |
|---|---|--:|--:|
| Braking | FULL_BRAKING | 475 | 450（95%） |
| Apex | MID_CORNER | 475 | 472（99%） |
| Exit | CORNER_EXIT | 475 | 304（**64%**） |

Exit の低成立は **CORNER_EXIT ゾーンの本質的な希薄性**（既存 `ce_r_spd` の非NULL率と整合。full DB では ~45% NULL, §21c）で、計算欠陥ではない。

### 3c. 候補マトリクス（sample 475 lap・avg=mean, peak=max）
| セル | 非NULL | null% | avg mean | peak max/p95 | 物理解釈 |
|---|--:|--:|--:|--:|---|
| brk_f_dive | 449 | 5.5 | 55.5 | **1.61** | 制動フォーク圧縮（既存・良性） |
| brk_f_reb | 449 | 5.5 | 47.5 | 1.55 | 制動フォーク伸び |
| brk_r_dive | 448 | 5.7 | 40.5 | 1.88 | ⚠低解釈: 制動中リアは伸び切り(SUSP_R -0.5-2.0)＝圧縮余地少 |
| brk_r_reb | 449 | 5.5 | 40.1 | 1.72 | 制動リア伸び（**Braking-R の本命**） |
| apex_f_dive | 472 | 0.6 | 108.1 | **6.85** | 中コーナー・**peak外れ値大** |
| apex_f_reb | 472 | 0.6 | 105.6 | 4.57 | 中コーナー |
| apex_r_dive | 472 | 0.6 | 51.7 | **7.24** | 中コーナー・**peak外れ値大** |
| apex_r_reb | 472 | 0.6 | 51.4 | 4.17 | 中コーナー（dive≈reb＝ほぼ対称） |
| ce_f_dive | 297 | 37.5 | 98.7 | 4.40 | ⚠低解釈: 立上りで前は伸び側（SUSP_F 0-70軽）＝圧縮は希薄 |
| ce_f_reb | 299 | 37.1 | 95.4 | 1.80 | 立上りフォーク伸び（**Exit-F の本命**） |
| ce_r_dive | 297 | 37.5 | 62.4 | 2.28 | 立上りリア スクワット圧縮 |
| ce_r_reb | 300 | 36.8 | 63.2 | 3.72 | 立上りリア伸び |
| ce_r_abs | 304 | 36.0 | 51.7 | 3.63 | 既存(絶対値)。**dive/reb 両平均より小**＝別統計 |

**重要所見**:
1. **Apex/Exit の peak(max) は外れ値支配**（max/p95 が最大 7.24×。`apex_f_dive_spd_peak` max=**7011 mm/s** はフォークが 7m/s で動く非物理値＝グリッド微分スパイク／マスク境界アーティファクト）。Braking-F peak は 1.6× で良性。
2. **方向非対称は物理的に妥当**: 制動は `brk_f_dive 55.5 > brk_f_reb 47.5`（前を速く圧縮）。中コーナーは `apex_r_dive 51.7 ≈ apex_r_reb 51.4`（準平衡でほぼ対称）。
3. **abs は dive/reb の冗長ブレンドではない**: `ce_r_abs 51.7` は `ce_r_dive 62.4` / `ce_r_reb 63.2` の**両方より下**（広いマスクで小|v|を残すため）。独立した統計＝将来の「活動量/チャター」指標候補。

---

## 4. 推奨指標定義（設計・6補正込み）

### 4a. 列（family = 26列: 22新規 + 2凍結 + 2 abs別名）
- **方向 dive/reb を主指標**（圧縮=コンプ側クリッカー / 伸び=リバウンド側クリッカーに対応、front/rear別）。ただし**相対指数**であり「校正済み物理速度」ではない（Claim 3補正）。
- **22 新規列**（各セル avg+peak）:
  `brk_f_reb`, `brk_r_dive`, `brk_r_reb`,
  `apex_f_dive`, `apex_f_reb`, `apex_r_dive`, `apex_r_reb`,
  `ce_f_dive`, `ce_f_reb`, `ce_r_dive`, `ce_r_reb`
  （各 `<cell>_spd_avg` / `<cell>_spd_peak`）。
- **2 凍結列（不変・byte一致・peak=max）**: `brk_f_dive_spd_avg` / `brk_f_dive_spd_peak`（＝マトリクスの brk/f/dive セル。back-compat）。
- **2 既存 abs 別名（保持・peak=max・`superseded_by` 記録）**: `ce_r_spd_avg` / `ce_r_spd_peak`（CORNER_EXIT rear |v|）。directional `ce_r_dive`/`ce_r_reb` を後継とする。
- **v1 では他5セル（brk_f, brk_r, apex_f, apex_r, ce_f）に abs を追加しない**（directional のみ）。abs は distinct 統計として **v2 の Apex「活動量」指標**に earmark（Claim 3補正）。

### 4b. 算出式（本番拡張時・per-lap）
```
v_side = np.gradient(R[SUSP_side]) / dtg          # 相対 mm/s（既存 _vel と同一）
zone   = _zone_mask(phase)                         # FULL_BRAKING / MID_CORNER / CORNER_EXIT
vz     = v_side[zone]; vz = vz[np.isfinite(vz)]    # isfinite 前フィルタ（防御的・既存値に無影響）
dive   = vz[vz > 0]                                # 圧縮
reb    = -vz[vz < 0]                               # 伸び（大きさ）
avg = round(mean(subset),1)   # n>=5
peak(new) = round(p95(subset),1)   # n>=10（新列のみ）／ 既存2 peak は max のまま
```

### 4c. null 条件（Draft の flat n>=5 を分割＝補正2）
- **二段ガード**: `zone.sum()>=5` **かつ** 方向サブセット `subset.size>=閾値`、未満は **NULL**。0 は「速度ゼロ」を意味しない（NEW列に literal 0.0 は欠陥）。
- **avg = n>=5**（feasibility でavgは全フェーズ安定）。
- **peak/p95 = n>=10**（n=5では p95 が max へ退化し、外れ値抑制の意味を失う＝Apex/Exit で最悪）。
  ※ p95 は小n で max 近傍に寄る性質があるため、閾値は Tatsuki 承認事項（下記 open question）。
- DB は zone count（`fullbrk_count`/`apex_count`(MID_CORNER)/`ce_count`）のみ保持し**方向サブセット count は持たない**。よって方向側 n ゲートは**抽出/scratch 層でのみ厳密適用**、DB側は `NOT NULL while zone_count<5` を弱バックストップとする。

### 4d. avg / peak / p95 判断（補正1）
- **avg（mean）= 主 UI 指標**（安定・現場解釈しやすい）。
- **peak = 新22列は p95**（Apex/Exit max はスパイク）。**既存2 peak（brk_f_dive）と abs別名 peak（ce_r）は max のまま**（FULL_BRAKING は良性・back-compat）。
- **reducer は列ごとに `metric_version_log` と UI 凡例へ必ず記録**（`brk_f_dive_peak`(max) と `brk_r_dive_peak`(p95) を同一統計として誤比較させない）。

### 4e. 低解釈セルの明示（補正4）
- `ce_f_dive`（立上りで前は伸び側＝圧縮は希薄）と `brk_r_dive`（制動でリアは伸び切り＝圧縮余地少）は**計算するが UI 凡例で低解釈と明示**し、本命 `ce_f_reb` / `brk_r_reb` へ誘導。

---

## 5. Quality Gate 案（`create_quality_tables.py` の `data_quality_log`/`metric_version_log` に整合）

| check_name | 種別 | 判定 |
|---|---|---|
| `gate_det_phase_spd_existing_unchanged` | critical/BLOCKING | 既存46列を full rebuild 後 lap_id JOIN で突合、`abs(diff)<1e-6` かつ lap_id 集合一致＝PASS、差分1件でも `sys.exit(1)`・正本無書込。`backfill_susp_zone_speed.py` の `NEW_COLS` を5→22へ拡張し再実行 |
| `gate_det_phase_spd_backcompat_frozen` | critical/BLOCKING | `brk_f_dive_spd_avg/peak` scratch==canonical 完全一致 |
| `gate_null_semantics_zero_leak` | critical | NEW列で `NOT NULL AND value==0.0` の行数 = 0 |
| `gate_zone_sample_guard` | critical（抽出層） | `NOT NULL AND (zone_count<5 OR 方向subset<閾値)` = 0。peak は n>=10。DB側は `zone_count<5` 弱バックストップ |
| `gate_null_rate_band` | warn/critical | **full-DB基準**: brk PASS≤15%/WARN≤40%/FAIL>40%・apex PASS≤10%/WARN≤30%/FAIL>30%・**ce PASS≤55%/WARN≤70%/FAIL>85%**（sample 37.5% ではなく full ~45% で設定＝補正5） |
| `gate_physical_range_avg` | 12 avg列 | PASS max≤250 / WARN 250-500 / FAIL>500 mm/s |
| `gate_physical_range_peak_new` | 10 新p95 peak | PASS max≤2500 / WARN≤4000 / FAIL>4000（p95 が 7000-9500 の生maxへ達したら reducer/n>=10 バイパス疑い） |
| `gate_physical_range_peak_frozen` | 既存 max系 peak | PASS max/p95≤5× / WARN≤8× / FAIL>8× or 値>10000。**reducer別に別ルール**（一律禁止） |
| `gate_unit_semantics_registered` | critical | family 26列全てに `metric_version_log` 行。units に `relative`＋`mm/s` を含み `km/h` を含まない・reducer(max/p95)記録・車速列(`brk_spd_avg`等)と別名/JOIN禁止 |
| `detect_susp_speed_outlier` | Phase2A/WARNING | 生 peak が非現実値（例 apex 7011）なら `data_quality_log` に WARNING 監査行（p95でクリップしても痕跡を残す） |
| `gate_directional_asymmetry_sane` | WARNING-only | `0.3≤dive_avg/reb_avg≤3.0`（非対称は物理・FAILにしない） |
| `gate_canonical_coverage` | 補強のみ | scratch distinct が canonical distinct の≥95%（feasibility 98.9/98.6%）。per-lap 決定論ゲートが主証明、これは補助 |

**`metric_version_log` シード**: 22新列を `(metric_name, "lap_suspension", "v1", 定義, "mm/s(相対)", guard_rule, "build_master_db.py", "YYYY-MM-DD", notes)` で追加。
guard_rule に「n>=5(avg)/n>=10(peak)→NULL」「peak=p95（新）／legacy=max」「相対指数・一人歩き禁止・車速と混同禁止」を明記。`ce_r_spd_*` は `superseded_by=ce_r_dive/ce_r_reb`。

---

## 6. UI 反映方針（`ts24_workbench.py` `PhaseRunCompareWidget`・dive-only MVP）

`_PHASE_SPD`（現 L3086-3090）を dive 主で埋め、3消費者（`_draw_speed` L3699 / `_phase_speed_vals` L3729 / `_update_note` L3560）と
`None`＝`not available yet` 契約・単一トリプル形状を保つ:

| フェーズ×側 | (avg列, peak列, タグ) | 備考 |
|---|---|---|
| Braking F | `(brk_f_dive_spd_avg, brk_f_dive_spd_peak, 'F-Dive')` | 既存不変・peak=max |
| Braking R | `(brk_r_dive_spd_avg, brk_r_dive_spd_peak, 'R-Dive')` | 新・p95・**低解釈フラグ→brk_r_reb 誘導** |
| Apex F | `(apex_f_dive_spd_avg, apex_f_dive_spd_peak, 'F-Dive')` | 新・p95 |
| Apex R | `(apex_r_dive_spd_avg, apex_r_dive_spd_peak, 'R-Dive')` | 新・p95 |
| Exit F | `(ce_f_dive_spd_avg, ce_f_dive_spd_peak, 'F-Dive')` | 新・p95・**低解釈フラグ→ce_f_reb 誘導** |
| Exit R | `(ce_r_spd_avg, ce_r_spd_peak, 'R\|v\|')` | **当面 abs 維持**・directional は検証後に第2系列で追加 |

- `_draw_speed` に **`col in rs.columns` ガード**を追加 → DB未追加列は `None`＝`not available yet` へ degrade（UI編集を**DB反映前**に安全にマージ可能）。
- Y軸/タイトルは `relative damping-speed index (mm/s, uncalibrated grid-M gradient)`。**km/h 車速トレースと同一軸/凡例に載せない**（`brk_spd_avg` 等は km/h）。dashed 系列は新=`p95`・既存=`peak/max` と別ラベル。
- **構造的 NULL（Exit ~45%）を `not available yet` プレースホルダと区別**して描画（希薄を「機能欠如」「速度ゼロ」と誤読させない）。trend は present 点 >=3 で描く。
- 凡例過多対策: Speed パネルは Run を ~4 に上限、色=Run / 線種=方向、`peak` 系列名は `None` で重複抑制（Phase=All を ~96→<=12 行へ）。
- テーブルは MVP で side あたり dive avg の1値のみ（14列維持）。Reb は将来 tooltip/任意列（トリプル→リストへ形状変更が必要）。

---

## 7. 本番実装時の変更対象（GO後・別タスク）／ rollback

**変更対象**:
1. `build_master_db.py` `extract_outing()` per-lap ブロックに 22新列の算出（dive/reb×3フェーズ×F/R、avg=n>=5、peak=p95 n>=10）を追加＝**本番ロジック変更**。`SCHEMA`（L557/576）と `_build_lap_suspension`（L639-648・INSERT列とVALUES）に22列追加。`extra_by_lapid` タプルを5→拡張。
2. `backfill_susp_zone_speed.py` `NEW_COLS` を5→22へ拡張し、**full rebuild に対する決定論ゲート再実行**（既存46列不変を証明）→ 合格時のみ ALTER ADD + lap_id UPDATE。
3. `create_quality_tables.py` に22列の `metric_version_log` シード追加。§5 のゲート実装。
4. `ts24_workbench.py` `_PHASE_SPD` を §6 表で更新＋`col in rs.columns` ガード＋ラベル。
5. `build_excel_master.py` DAMPING グループ拡張（任意・DB Master 反映が要る場合）。

**rollback**: 新列は追加のみ。`ALTER TABLE lap_suspension DROP COLUMN`（SQLite 3.35+）または backup 差し戻し。Workbench は `_PHASE_SPD` を現状へ戻す。既存46列は決定論ゲートで不変保証のため業務影響なし。

---

## 8. 敵対的検証の結果（6主張）

| # | 主張 | 判定 | 補正 |
|--:|---|---|---|
| 1 | 複製は本番 extract_outing と一致→マトリクスも同一基盤 | **CONFIRMED** | scope: 直接は4アンカー、他18は構成担保。full rebuild で再ゲート |
| 2 | Apex/Exit peak(max) は外れ値→新列は p95 | **CONFIRMED** | avg も完全にクリーンではない（微分ノイズ）＝相対指数と明記 |
| 3 | directional 主・abs は back-compat のみ | **UNCERTAIN→補正** | ①相対指数（非校正）②「主」はフェーズ依存（Apex はほぼ対称）③abs は distinct 統計・v2 活動量へ |
| 4 | 既存 brk_f_dive 不変・ce_r は abs 別名 | **CONFIRMED** | — |
| 5 | n>=5 妥当・Exit ~37% は本質的希薄 | （検証エージェント失敗）→ synth で補正 | avg=n>=5/peak=n>=10 に分割・CE band は full-DB ~45% 基準 |
| 6 | 書込/ロジック変更/2D再処理なし・rollout は backfill 流用 | **CONFIRMED** | 新列populate は extract_outing 拡張＝本番コード変更→full rebuild ゲート必須 |

---

## 9. Multi-agent operating check

- **Suspension/Physics**: dive/reb は圧縮/伸びクリッカーに対応し現場解釈可。非対称（brk_f_dive>reb）・対称（apex_r）は物理的に妥当。低解釈セル（ce_f_dive/brk_r_dive）を特定し本命へ誘導。相対指数の但し書きを要求。
- **Data/Extraction**: 決定論 1900/0・98.6-98.9% カバーで再現性確認。np.gradient 端点/マスク境界スパイク→p95。n>=5/10・isfinite 前フィルタ。Exit 64% は本質的希薄。
- **Quality Gate**: 既存46列不変（BLOCKING）・0≠NULL・range/unit/zone-sample・reducer別 peak ルール・CE band は full-DB 基準。
- **Workbench/UI**: `not available yet` の埋め方（dive-only MVP・`col in df.columns` ガード・km/h と firewall・構造NULL 区別）。
- **Documentation/Handoff**: 本 report / `CLAUDE.md` §43 / Obsidian log・handoff・current_state・INBOX Result 更新。
- **Supervisor**: 指標定義変更・schema変更・正本DB書込・2D再処理・Supabase・push を**別承認に保持**（本タスクでは未実施）。
- **Tatsuki=決める**: 下記 open questions と rollout GO の承認者。

---

## 10. Tatsuki への確認事項（open questions・GO前）

1. **peak 閾値**: 新 p95 peak を **n>=10**（avg は n>=5）にするか、一律 n>=5（低n で p95≈max を許容）か。
2. **abs 範囲(v1)**: 未整備5セルに abs を追加しない（推奨・既存 ce_r 別名のみ）か、全フェーズ×側へ abs を追加（22→最大34列）か。
3. **Exit-R 初日**: 当面 `ce_r_spd_*`(abs) を表示し、directional 検証後に切替（推奨）か、即 directional か。
4. **UI の Reb**: dive-only MVP（低リスク・形状不変）で出すか、`brk_r_reb`/`ce_f_reb`（本命弱セル）を即見せるため形状変更（トリプル→リスト）に投資するか。
5. **位置チャンネル前処理**: `np.gradient` 前に SUSP 位置を平滑化（CAL `F(#SUSP,F(10))`・§6c）するか。**する場合 既存 brk_f_dive/ce_r 値が変わり byte-compat/決定論が壊れる → 非平滑化を推奨**（相対指数として一貫ロガー設定内で有効と文書化）。
6. **rollout GO**: 本設計で `lap_suspension` 派生列追加（extract_outing 拡張 + full rebuild + 拡張決定論ゲート + ALTER/UPDATE）へ進むか。full DB 対象（3サーキットsample ではなく）。

### 次の実行ゲート文言案
```text
3フェーズ×F/R Suspension Speed 指標設計と scratch feasibility は完了済みです。
提案した列定義（22新規・dive/reb・peak=p95）で lap_suspension 派生列を追加し、
scratch→正本DBへ反映する実行準備（build_master_db 拡張 + 拡張決定論ゲート）に進んでよいですか？
実行する場合は「Phase suspension speed design GO」と明示してください。
```

---

## 11. まだ実施しないこと（禁止遵守・本タスクで未実施）

正本DB schema変更 / `lap_suspension` 新列追加 / 本番 `build_master_db.py` 算出ロジック変更 / 2D raw再処理 /
Workbench Speed グラフ本格拡張 / DB Master 再生成 / Supabase cleanup・sync / origin push。
本タスクは **設計 + scratch/read-only feasibility のみ**（正本DBは `mode=ro`・scratch は session scratchpad）。

## 12. 成果物
- 本 report `reports/phase_susp_speed_metric_design_20260701.md`（コミット対象）。
- scratch script `scratch_phase_susp_speed_feasibility.py`（session scratchpad・read-only・非コミット）。
- 設計レビュー/検証: 多エージェント（物理/データ/品質/UI ＋ 6主張敵対的検証 ＋ synthesis）。
