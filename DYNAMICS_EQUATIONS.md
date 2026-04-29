# TS24 Puccetti — Dynamics Analysis 使用方程式集
`parse_2d_channels.py` が各指標を算出する際に使用している数式・アルゴリズムの一覧です。

---

## 1. チャンネルデータ物理値変換

2D Analyser のバイナリファイル (.A0D 等) を物理値に変換する基本式。

```
physical_value = (raw_int16 − offset) × scale × multiplier
```

| パラメータ | 取得元 | 備考 |
|---|---|---|
| `raw_int16` | チャンネルバイナリファイル (signed/unsigned int16) | 2 bytes per sample |
| `offset` | .DDD ファイル Line 3, フィールド 1 | 整数 |
| `scale` | .DDD ファイル Line 3, フィールド 4 | IEEE 754 float32 hex |
| `multiplier` | .DDD ファイル Line 3, フィールド 7 | IEEE 754 float32 hex |

---

## 2. サンプルレート推定

LAP ファイルの最終ラップ終了時刻から Speed チャンネルのサンプルレートを算出。

```
SR [Hz] = N_speed_samples / (last_lap_end_ms / 1000)
```

- `N_speed_samples` : SPEED_FRONT チャンネルの総サンプル数
- `last_lap_end_ms` : LAP ファイルに記録された最終ラップ終了時刻 (ms)
- クランプ範囲: 10 ≦ SR ≦ 500 Hz

---

## 3. SUSP / SPEED チャンネルの時刻同期

SUSP チャンネルは SPEED チャンネルの **約 4 倍** のサンプルレートで記録される。

```
i_susp = i_speed × ratio

ratio = round( N_susp_samples / N_speed_samples )  ≈ 4
```

SPEED の index `i` における SUSP 値 → `SUSP[ i × ratio ]`

---

## 4. APEX 検出アルゴリズム（全コーナー局所極小方式）

コース上の**全コーナー**のAPEXを個別に検出する。旧方式（ランレングス符号化）は連続コーナー区間を1点に折りたたんでしまうため、局所極小点（Local Minima）方式に変更。

**Step 1 — スムージング**
```
speed_smooth = moving_average(Speed_F, window = 0.3 s)
```
0.3 秒移動平均でノイズを除去（サンプルレートに依存しない秒単位で指定）。

**Step 2 — 速度閾値設定**
```
threshold = max(speed_smooth_in_lap) × 0.92
```
ラップ最高速の 92% 以下の局所極小のみAPEX候補とする（高速コーナーも捕捉）。

**Step 3 — 局所極小点の検出**
```
gradient = d(speed_smooth) / dt

local_minimum at index i:
  gradient[i-1] < 0  AND  gradient[i] >= 0
  AND  speed_smooth[i] < threshold
```
勾配の符号が (負 → 正) に変化する点 = 速度の局所極小 = コーナーAPEX候補。

**Step 4 — プロミネンスフィルタ（直線上ノイズ除去）**
```
depth = max(speed_smooth[ i−4s : i+4s ]) − speed_smooth[i]

有効条件: depth ≥ 15 km/h
```
APEX前後 ±4 秒の最高速との落差が 15 km/h 未満の点は直線上の微細な変動として除外。

**Step 5 — 最小間隔フィルタ**
```
隣接APEX間隔 ≥ 0.25 秒 (シケイン対応)
```

**Step 6 — 短ラップ除外**
```
ラップ時間 ≥ 60 秒のラップのみ処理
```
アウトラップ・フォーメーションラップ・ピット出入りを除外。

**検出精度（実測）**

| サーキット | 公式コーナー数 | 検出 APEX/lap |
|---|---|---|
| Assen | 18 | 17.7〜21.7 |
| Phillip Island | 13 | 18.4〜23.5 |
| Portimao | 15 | 18.6〜22.2 |
| Jerez | 13 | 19.1〜26.2 |

※ 公式コーナー数より多い場合はシケイン・エスセクション等の複数アペックスを個別検出しているため。

---

## 5. APEX 時の加速度 (中央差分)

APEX index `i` における前後方向加速度を Speed F の微分で算出。

```
ax [m/s²] = ( V[i+1] − V[i−1] ) / ( 2 × dt )
```

- `V[i]` = Speed F at index i [m/s]  (km/h → m/s: ÷ 3.6)
- `dt` = 1 / SR [s]

コーナーAPEXでは速度がほぼ一定のため ax ≈ 0 に近い値が得られる。
(np.gradient による全配列一括計算でも同一の中央差分式を使用)

---

## 6. ホイール荷重計算 (動的荷重移動)

Knowledge Base 11.8 の車体動力学方程式に基づく。

### 6-1. 静的荷重 (スタティック)

```
Nf₀ = m × g × fw_ratio
Nr₀ = m × g × (1 − fw_ratio)
```

| 記号 | 説明 | 単位 |
|---|---|---|
| `m` | 総質量 (バイク + ライダー) | kg |
| `g` | 重力加速度 = 9.81 | m/s² |
| `fw_ratio` | フロント荷重比率 (静的) | — |

### 6-2. 動的荷重移動

```
ΔN = m × (−ax) × h / L
```

| 記号 | 説明 | 単位 |
|---|---|---|
| `ax` | 前後方向加速度 (正=加速, 負=制動) | m/s² |
| `h` | 重心高さ (CG height) | m |
| `L` | ホイールベース | m |

制動時 (ax < 0) は −ax > 0 となりフロント荷重が増加。

### 6-3. 動的ホイール荷重

```
Nf = Nf₀ + ΔN
Nr = Nr₀ − ΔN
```

### TS24 バイク パラメータ

| パラメータ | JA52 | DA77 |
|---|---|---|
| ホイールベース L | 1.399 m | 1.4115 m |
| 重心高 h | 0.6449 m | 0.6511 m |
| フロント荷重比率 fw | 48.92% | 48.71% |
| Fサス レート | 30.1 N/mm | 26.1 N/mm |
| Rサス レート | 58.4 N/mm | 57.8 N/mm |

---

## 7. ブレーキング直前検出アルゴリズム

### Step 1 — 加速度算出

```
ax[i] = gradient( smooth(V_ms, window=7) ) / dt
```

スムージング後の Speed [m/s] を np.gradient で微分。

### Step 2 — ブレーキ候補マスク

```
mask[i] = 1  if ax[i] < −8 m/s²  AND  Speed[i] >= 80 km/h
        = 0  otherwise
```

| 定数 | 値 | 意味 |
|---|---|---|
| BRAKE_DECEL_THRESHOLD | −8 m/s² | 強い制動と見なす減速度 |
| BRAKE_MIN_SPEED | 80 km/h | 高速コーナー進入のみ対象 |

### Step 3 — 連続確認 & 間隔フィルタ

```
連続 ≥ 15 samples かつ 前回ブレーキから ≥ 80 samples 離れていること
```

(@ 100 Hz: 15 samples ≒ 0.15 s,  80 samples ≒ 0.8 s)

### Step 4 — ブレーキ直前サンプル

```
brake_sample = brake_start_index − 8 samples
```

ブレーキ開始の約 0.08 秒前の SUSP 値を「直前」の値として記録。

---

## 8. ピットレーンリミッター区間検出

電子制御による 60 km/h リミッター発動区間を速度帯域で検出。

### 検出条件

```
Speed F ∈ [56, 64] km/h  が連続 ≥ 3 秒
```

| 定数 | 値 |
|---|---|
| リミッター速度 | 60 km/h |
| 検出帯域 (±) | ±4 km/h |
| 最小持続時間 | 3 秒 |

ローリング平均ではなく **瞬時速度** に 0.2 秒スムージングのみ適用。
(リミッターは電子的速度クランプのため速度が帯域内で安定する)

区間内の SUSP_FRONT / SUSP_REAR の **平均値** を出力する。

---

## 9. 出力値の集計

各ラップで検出された全 APEX / ブレーキ / ピットリミッター区間の値を
**セッション全体の算術平均** として記録する。

```
avg_value = sum(values) / count
```

---

*方程式の参照元: TS24 Knowledge Base Section 11.8 — Motorcycle Dynamics*
