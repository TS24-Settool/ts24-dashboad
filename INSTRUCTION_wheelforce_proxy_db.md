# INSTRUCTION: WheelForce_Proxy 列を DB に追加

**作成:** Cowork Claude 2026-05-05  
**対象:** Claude Code  
**優先度:** 中（新機能追加）

---

## 背景・目的

現在の `lap_suspension_data` テーブル（JSON / SQLite）は、サスペンション変位を **mm 単位** で保存している。

今回、ZX-636R のリンク比（LR = 2.0 → MR = 0.5）と RUN_LOG のバネレートを使い、  
**サスペンション力の代用値（WheelForce_Proxy）を N 単位** で計算して追加カラムとして格納する。

この値は「真のタイヤ接地荷重」ではなく、**バネ成分のみのプロキシ**である（Level 1 実装）。

---

## 計算式（確定）

```python
# フロント（テレスコピックフォーク: MR=1.0）
WF_F_N = SUSP_mm × (F_SPR_L + F_SPR_R) / 2      # [N]
# 例: 70mm × (9.0 + 9.5)/2 = 70 × 9.25 = 647.5 N

# リア（リンク式: LR=2.0, MR=0.5）
WF_R_N = SUSP_mm × R_SPR × 0.5                    # [N]
# 例: 16mm × 84 × 0.5 = 672 N
```

**ゼロ点:** センサーゼロ = 完全伸び切り状態。オフセット補正不要。  
**バネレート単位:** N/mm（RUN_LOG の F_SPR_L / F_SPR_R / R_SPR 列から取得）

---

## 追加する列

| 列名 | 型 | 説明 |
|------|----|------|
| `WF_F_APEX_N` | REAL | APEX 区間のフロント WheelForce_Proxy 平均 [N] |
| `WF_R_APEX_N` | REAL | APEX 区間のリア WheelForce_Proxy 平均 [N] |
| `WF_F_BRK_N`  | REAL | ブレーキング区間のフロント WheelForce_Proxy 平均 [N] |
| `WF_R_BRK_N`  | REAL | ブレーキング区間のリア WheelForce_Proxy 平均 [N] |

NULL = 対応する SUSP_AVG が NULL（有効データなし）または RUN_LOG にバネレートなし。

---

## バネレート取得方法

RUN_LOG (`02_DATABASE/TS24 DB Master.xlsx`, シート `RUN_LOG`) から RUN_ID をキーに JOIN する。

```python
# openpyxl で読み込む場合（headers は row 3、data は row 4 以降）
# 列名: 'F_SPR\nL', 'F_SPR\nR', 'R_SPR'

def get_spring_rates(run_log_dict, run_id):
    """Returns (f_eff, r_spr) or (None, None) if not found."""
    rec = run_log_dict.get(run_id)
    if rec is None:
        return None, None
    fl = rec.get('F_SPR\nL')
    fr = rec.get('F_SPR\nR')
    r_spr = rec.get('R_SPR')
    if fl and fr and r_spr:
        return (fl + fr) / 2.0, r_spr
    return None, None
```

RUN_LOG に存在しない RUN_ID は NULL（計算スキップ）。無理なフォールバックは行わない。

---

## 実装対象ファイル

### 1. `lap_suspension_stats.py`

- `process_run()` または集計後の lap レコード構築時に WF 計算を追加する
- RUN_LOG を起動時に一度読み込んでキャッシュする
- 既存のフロー（APEX_SUSF_AVG / APEX_SUSR_AVG / BRK_SUSF_AVG / BRK_SUSR_AVG）が確定した後に計算

```python
# 追加するイメージ
f_eff, r_spr = get_spring_rates(run_log_cache, run_id)

wf_f_apex = (f_eff * apex_susf_avg) if (f_eff and apex_susf_avg is not None) else None
wf_r_apex = (r_spr * apex_susr_avg * 0.5) if (r_spr and apex_susr_avg is not None) else None
wf_f_brk  = (f_eff * brk_susf_avg)  if (f_eff and brk_susf_avg is not None) else None
wf_r_brk  = (r_spr * brk_susr_avg * 0.5) if (r_spr and brk_susr_avg is not None) else None
```

### 2. SQLite スキーマ（`TS24_data.db`）

`lap_suspension_data` テーブルに列を追加する。  
既存テーブルが存在する場合は `ALTER TABLE` で追加（再作成不要）。

```sql
ALTER TABLE lap_suspension_data ADD COLUMN WF_F_APEX_N REAL;
ALTER TABLE lap_suspension_data ADD COLUMN WF_R_APEX_N REAL;
ALTER TABLE lap_suspension_data ADD COLUMN WF_F_BRK_N  REAL;
ALTER TABLE lap_suspension_data ADD COLUMN WF_R_BRK_N  REAL;
```

スキーマ定義にも追加しておくこと（`CREATE TABLE IF NOT EXISTS` 内）。

### 3. `lap_suspension_data.json`

JSON 出力時に 4 列を含めること。NULL は Python の `None`（JSON では `null`）。

---

## 実行・確認手順

1. `lap_suspension_stats.py` を修正（RUN_LOG 読み込み + WF 計算追加 + schema 更新）
2. 全 MES を再処理：`python lap_suspension_stats.py --all`（または既存の全処理コマンド）
3. 結果確認：
   ```python
   # ROUND3_ASSEN_FP_DA77_R1 のラップを確認
   # 期待値: WF_F_APEX_N ≈ 647N, WF_R_APEX_N ≈ 682N
   ```
4. JSON を再生成して `05_SCRIPTS/lap_suspension_data.json` を更新
5. GitHub push（既存フロー通り）

---

## 期待値（ASSEN 主要ランの検証用）

| RUN_ID | F_eff | R_SPR | SUSF_mm | SUSR_mm | WF_F_N | WF_R_N | F/R |
|--------|-------|-------|---------|---------|--------|--------|-----|
| ROUND3_ASSEN_FP_DA77_R1 | 9.0 | 84 | 71.8 | 16.2 | 647 | 682 | 0.948 |
| ROUND3_ASSEN_FP_JA52_R1 | 9.25 | 84 | 69.9 | 19.5 | 647 | 818 | 0.791 |
| ROUND3_ASSEN_RACE1_DA77_R1 | 9.25 | 84 | 66.8 | 18.5 | 618 | 775 | 0.797 |

DA77 は F/R ≈ 0.94（フロント重め）、JA52 は F/R ≈ 0.79（リア重め）が特徴的。

---

## 注意事項

- WheelForce_Proxy は **Level 1（バネ成分のみ）** である
- ダンパー力・慣性力・空力は含まれない
- 列名に `_Proxy` は付けず `WF_F/R_APEX/BRK_N` とする（Dashboard 表示での簡潔さを優先）
- MR = 0.5（= 1/LR = 1/2.0）は ZX-636R 実測値。他車種使用時は要確認

---

*このファイルは Cowork Claude が解析を終えた後、Claude Code への作業指示として作成した。*  
*解析元データ: `05_SCRIPTS/lap_suspension_data.json` + `02_DATABASE/TS24 DB Master.xlsx`（RUN_LOG）*
