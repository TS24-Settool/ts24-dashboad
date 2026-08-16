# Round7 JA52 フル統合（最終化）Readiness — Phase A

- 日付: 2026-07-07
- 実施: Claude Code（委任エージェント・**read-only Phase A**）
- 対象: `20260612-ROUND7-JA52`（MISANO / JA52）を DB 全体へフル統合（provisional → final 昇格）
- 正本: `02_DATABASE/ts24_unified.db`（**mode=ro のみ・一切書込なし**）
- スクラッチ検証: `/tmp/ts24_round7_scratch.db`（`build_master_db.py --all --out` で新規生成・正本非変更）
- ゲート文言（最終化の唯一のトリガ）: **`Round7 final integration GO`**

> **結論（先出し）**: スクラッチ全ビルドは成功、受入ゲート合格、既存 1202 laps は完全不変（byte 一致）。
> ただし **final（13 runs / 77 laps）は provisional（12 runs / 79 laps）と一致しない**。差分は
> すべて build_master_db の Original 駆動マージ仕様に起因（他 Round と同一挙動）で、BLOCKER ではないが
> **Tatsuki の明示了承が必要な構造差**（WUP2 −2 laps・RACE ×2 Original-only run 追加・setup 行割当）。
> → 推奨は **条件付き GO**（下記 §9）。判定は最終化ゲートに委ねる。

---

## 1. 現状実測（mode=ro）

### 1.1 業務テーブル（ROUND7 反映状況）

| table | 全体 | ROUND7 | 備考 |
|---|--:|--:|---|
| runs | 275 | **0** | 2D は final 未反映（§37/§57） |
| laps | 1202 | **0** | 同上 |
| lap_suspension | 1202 | **0** | 同上 |
| race_results | 866 | **74** | §37d 適用済 |
| pdf_lap_times_v2_staging | — | **1094**(PASS) | §38e 適用済 |
| race_lap_detail (VIEW) | — | **1094** | staging をオーバレイ |

- race_results ROUND7 内訳（session_type）: FP 2 / QP 2 / WUP1 2 / WUP2 2 / RACE1 33 / RACE2 33 = **74** ✅
- pdf_lap_times_v2_staging ROUND7: RACE1 528 / RACE2 566（全 gate_status=PASS）= **1094** ✅

### 1.2 provisional 3 テーブル（実測）

- runs_provisional = **12** / laps_provisional = **79** / lap_suspension_provisional = **79**
- provisional_event_key = `20260612-ROUND7-JA52`（3 テーブル共通）
- session 内訳（run/lap）: FP 3(15) / QP 4(14) / WUP1 1(6) / WUP2 2(6) / RACE1 1(19) / RACE2 1(19)
- quality_status: PASS 8 / WARNING 4（WARNING は全て stage_phase22_fill）

### 1.3 source_file_registry / import_queue（ROUND7 JA52）

- source_file_registry: 34 件・status=`queued`（session=NULL）
- import_queue（`%20260612-ROUND7-JA52%`）:
  - 2d_extract: awaiting_gate **12** / failed **7** / skipped **14**（計 33）
  - report_import: pending **1**
- §2.3（前回レポート）と一致。

---

## 2. ソース完全性

| ソース | 実測 | 判定 |
|---|---|:--:|
| `DATA 2D/20260612-ROUND7-JA52` | 33 outing（D0/FP/QP/R1/R2/WUP1/WUP2 各 prefix + EVENT.INI/RING 等）| ✅ |
| Report `01_REPORTS/JA52/20260612-ROUND7-JA52.xlsx` | 存在（256 KB）| ✅ |
| Original `04_REFERENCE/Data_Base_TS24_ORIGINAL.xlsx` | ROUND7/MISANO/JA52 = **13 行**・setup 値あり | ✅ |
| Result PDF `07_RESULTS/ROUND7_MISANO_20260612/` | FP/QP/RACE1/RACE2/WUP1/WUP2 = **6 本** | ✅ |

**Original の setup は 12 run 分を充足** — DRY/温度/FKR・C104/C106・spring・comp/reb・ride_hgt・tyre 等フルに存在。
ただし Original の MISANO 行構成は **FP3 / QP4 / WUP1 1 / WUP2 1 / RACE1 ×2 / RACE2 ×2 = 13**。
provisional（2D 由来）の **WUP2 2 / RACE1 1 / RACE2 1** と **session 別本数が不一致**（→ §3/§5 の差分要因）。

---

## 3. スクラッチ全ビルド vs provisional（最重要）

- コマンド: `python3 build_master_db.py --all --out /tmp/ts24_round7_scratch.db` → **exit 0**
- スクラッチ全体: events=27・runs=**286**・laps=**1279**・lap_suspension=**1279**
- **受入ゲート `|2D(session最速) − PDF best| > 1.5s`: 0 件 ✅合格**（BLOCKER なし）
- 参考 WARN: `NA_BALATON_RACE2_JA52_R1 ×2`（ROUND7 と無関係の別イベント既知重複・本件対象外）

### 3.1 ROUND7 スクラッチ実測（= 最終化後の予定形）

| session | scratch run | scratch laps | provisional run | prov laps | 差分 |
|---|--:|--:|--:|--:|---|
| FP | 3 | 15 | 3 | 15 | 一致 |
| QP | 4 | 14 | 4 | 14 | 一致 |
| WUP1 | 1 | 6 | 1 | 6 | 一致 |
| WUP2 | **1** | **4** | 2 | 6 | **run −1 / lap −2** |
| RACE1 | **2** | 19 | 1 | 19 | **run +1**（R2=0lap）|
| RACE2 | **2** | 19 | 1 | 19 | **run +1**（R2=0lap）|
| **計** | **13** | **77** | **12** | **79** | **run +1 / lap −2** |

### 3.2 差分の内訳と原因（build_master_db 仕様）

1. **run_id 命名**: final = `20260612_ROUND7_MISANO_{session}_JA52_R{n}`（**PROV_ 前置なし**）。想定どおり ✅
2. **best_lap_s**: 一致 run は完全一致（FP 99.429/98.791/98.364・QP 97.953/98.25/97.636/101.714・WUP1 98.109・WUP2_R1 98.16・RACE1_R1 98.055・RACE2_R1 97.778）。RACE R2 は best=NULL。
3. **WUP2 −2 laps（要注意）**: Original WUP2 は 1 行（M=1）→ `per_event=round(M/E)=1`。build は lap 数最大の 1 outing のみ採用し、**WUP2-02（2 laps・prov では R2/PASS）を不採用**。→ **有効 2 laps が final で脱落**。
4. **RACE1/RACE2 +1 run**: Original の RACE1/RACE2 は各 **2 行**（全 circuit 共通の構造）→ `per_event=2`。2D outing は各 1 本のため R1=2D+Original1行目・**R2=Original2行目のみ（has_2d=0・source=ORIGINAL・0 lap・best NULL）**。
5. **setup 充填**: provisional は setup 全 NULL → final は Original から充填（全 run）。ただし RACE は **1行目（C104・温度なし）が 2D 付き R1**・**2行目（C106・track52/air29 の実レース温度）が 0lap の R2** に割当 → 実レース setup(C106) が 2D データと別 run になる **行割当リスク**。
6. **lap_suspension 列充填差**: provisional は 75 列・final は 69 列（§44）。共有 wheel-force 列 `wf_{f,r}_{apex,brk,ce}_n` は **provisional=NULL / final=値あり**。best/コア susp metrics は一致。→ final は provisional より**列が充実**（劣化なし）。

> §57(L2718) の記載「PROV_ run_id は Original 不在時の本番挙動（2D_ONLY・全 outing 採用）と整合」の通り、
> provisional は **Original を読まない純 2D ステージング**。MISANO は Original が存在するため final は
> Original 駆動パスに切替わり **run 構成が再編**される。→ **provisional と final の不一致は設計どおり・想定内**。

### 3.3 決定論ゲート（既存 1202 laps 保護）の実測

- スクラッチ非-ROUND7 laps = **1202**、正本 laps = 1202 → **差 0（byte 一致・欠落 0・追加 0）** ✅
- スクラッチ非-ROUND7 runs = 273 vs 正本 runs = 275 → 差 **2**。内訳:
  - 正本のみ: `NA_MISANO_RACE1_JA52_R1` / `NA_MISANO_RACE2_JA52_R1`（ORIGINAL_NO2D・0 lap の setup 専用行）
  - これらは 2D 不在時の placeholder。ROUND7 2D が入った今、**ROUND7 RACE R2 へ再割当**され消滅（0 lap のためデータ喪失なし）。
- ⇒ 最終化後の正本予定形: runs 275 − 2 + 13 = **286** / laps 1202 + 77 = **1279**（= scratch）。

---

## 4. reconcile（2D ↔ Original・ROUND7）

`reconcile_2d_vs_original.py` 実測より ROUND7/MISANO 該当:

- **Original 重複キー**: `JA52|MISANO|RACE1|R1 ×2`・`JA52|MISANO|RACE2|R1 ×2`（全 circuit 共通の構造的重複）。
- **2D vs Original 本数**: WUP2 は 2D=2 / Orig=1（不一致 → §3.2-3 の lap 脱落要因）。RACE1/RACE2 は 2D=1 / Orig=2（→ §3.2-4 の R2 追加要因）。
- **unmatched 2D / unmatched Original / session・rider・circuit mismatch**: ROUND7 固有の致命的不整合は無し（差は上記 2 点＝ build ロジックが決定論的に吸収）。

---

## 5. provisional → final マッピング

`round7_full_integration_mapping_20260707.csv` 参照（12 PROV + final-only 2 = 14 行）。要点:

- 10 run は **1:1 対応**（FP×3・QP×4・WUP1×1・WUP2_R1・RACE1_R1・RACE2_R1）・best 一致・setup は Original 充填。
- `PROV_...WUP2_JA52_R2`（98.045 / 2 laps）は **final に対応 run なし（DROPPED）**。
- `...RACE1_JA52_R2` / `...RACE2_JA52_R2` は **final 新規**（prov 由来なし・0 lap・Original 2 行目 setup）。

---

## 6. 最終化プラン（write・**未実行**）

`round7_full_integration_plan_20260707.sql`（provisional clear + 検証クエリ）参照。手順とゲート:

| # | 段 | 内容 | ゲート / 停止条件 |
|--:|---|---|---|
| 0 | backup | 正本を `_backup_*`（フルコピー）へ退避 | backup サイズ>0・SHA 記録 |
| 1 | scratch rebuild | `build_master_db.py --all --out /tmp/...` 再実行 | exit 0・受入ゲート 0 件 |
| 2 | **決定論ゲート** | scratch 非-ROUND7 laps == 正本 1202（byte 一致）**かつ** ROUND7 新規行 == scratch(13/77) | **1 lap でも差異 → 停止** |
| 3 | cutover | `cutover_db.py`（ts24_master→正本昇格・run_id 再マップ） | `NA_MISANO_RACE*` 2 件消滅・runs 286/laps 1279 |
| 4 | Workbench final 確認 | §7 の before/after | final 13 run 表示 |
| 5 | provisional clear | `DELETE ... WHERE provisional_event_key='20260612-ROUND7-JA52'`（susp→laps→runs 順）| クリア後 0/0/0・業務テーブル不変 |
| 6 | DB Master refresh | `refresh_db_master_safe.py`（Excel 再生成・DB は SELECT のみ・自動 backup） | Excel ロック無・件数一致 |
| 7 | Supabase v3 sync + audit | `sync_to_supabase.py`（v3 スキーマ）+ 監査 | 行数照合 OK |

> **run_id 再マップ risk（§20a / lap_id）**: cutover は旧→新 run_id を再マップし `lap_id={run_id}_L{n}` を再生成する。
> 既存 1202 laps は §3.3 で **byte 一致**を確認済のため、決定論ゲート(段2)が「既存不変」を機械保証する。
> 再マップの影響は `NA_MISANO_RACE1/2_JA52_R1`（0 lap）→ ROUND7 R2 への移行 2 件のみ。

### 6b. Rollback（各段）

| 段 | rollback |
|---|---|
| 0-2 | scratch は /tmp のみ・正本無変更 → 破棄で完了 |
| 3 cutover | 段0 backup から正本を丸ごと復元 |
| 5 provisional clear | 段0 backup または plan.sql §4（ATTACH backup → INSERT ... SELECT で event_key 限定復元） |
| 6-7 downstream | Excel は `backups/` から復元・Supabase は v3 upsert 冪等（再 sync で回復） |

最終手段は常に **段0 のフル backup から DB 丸ごと復元**。

---

## 7. Workbench 表示確認プラン

| フェーズ | 期待 | 判定基準 |
|---|---|---|
| before（現状=provisional overlay） | ROUND7 MISANO = **12 run・全て `(prov)` マーク** | 前回 §5 と同一 |
| after cutover（final・clear 前） | ROUND7 final = **13 run**（RACE1/RACE2 に 0lap R2 が増）+ provisional 12 が残存し **二重表示** | overlay と final 併存を確認 |
| after provisional clear | ROUND7 = **13 run のみ・`(prov)` 消滅・重複 0** | final のみ |

- final-only 無回帰: 既存 event（JEREZ/TEST1 等）の run/lap 数不変（§48 base_df）。
- Report v2 PROV guard（`ts24_workbench.py` L3459/L3568）は存置のまま（clear 後は PROV_ 検出 0）。
- GUI 最終目視は Tatsuki ローカル（`python3 ts24_workbench.py`）。

---

## 8. downstream 同期プラン（DB Master + Supabase v3 のみ）

- **DB Master**: `refresh_db_master_safe.py` — `TS24 DB Master.xlsx` を安全再生成（Excel ロック検出→中止・`backups/` 自動退避・DB は SELECT のみ・正本非書込）。派生成果物であり正本ではない（§23/§26）。
- **Supabase v3**: `sync_to_supabase.py`（v3 新スキーマ・upsert 冪等・batch）。sync 後に行数 audit。
- **除外**: **Supabase v2 は別 G1 ゲート**のため本フローに含めない（本件スコープ外）。

---

## 9. Multi-agent operating check / 禁止事項遵守

- 本 Phase A は **read-only**。正本 `ts24_unified.db` は全操作 `mode=ro`・**書込 0**（final/provisional/business 全て非変更・provisional clear 未実行・DB Master 再生成なし・Supabase なし・push なし）。
- 書込は許可された成果物 3 ファイル（reports/*.md, *.csv, *.sql）と /tmp スクラッチのみ。コード編集ゼロ・git commit なし。
- 承認境界は不変。最終化の実行は **Tatsuki の明示ゲート `Round7 final integration GO`** 受領後の別 Phase。
- Obsidian 運用層: CURRENT_STATE / AI_HANDOFF_LATEST の更新はメインセッションで実施のこと。

### GO / NO-GO 推奨 = **条件付き GO**

**GO 材料**: 正本無傷・スクラッチ exit0・受入ゲート 0 件・既存 1202 laps byte 一致・setup 充足・reconcile 致命傷なし・provisional_event_key 単一で clear 安全。

**要了承（NO-GO 化しうる構造差・Tatsuki 判断事項）**:
1. **final は 13 run / 77 lap**（provisional 12/79 と不一致）。Workbench の run 数・lap 数が変わる。
2. **WUP2-02 の 2 laps が final で脱落**（Original WUP2 1 行のため）。この 2 laps を残すなら Original 側に WUP2 2 行目追加が必要（＝仕様変更・別対応）。
3. **RACE1/RACE2 に 0lap の Original-only R2 が追加**、かつ **実レース setup(C106) が 2D 付き R1 でなく R2 に割当**（他 Round と同一挙動だが、レース解析時に setup 参照 run がずれる）。

→ 上記 1–3 を「他 Round と同じ既定挙動として受容」する場合は **そのまま GO**。
　WUP2 2 laps 保持や RACE setup 行割当の是正を求める場合は **NO-GO（Original 修正 or build 仕様調整を先行）**。

**最終化トリガ文言**: 上記了承のうえ **`Round7 final integration GO`** を発話 → 別 Phase で §6 手順を実行。

---

## 10. 成果物

- `05_SCRIPTS/reports/round7_full_integration_readiness_20260707.md`（本書）
- `05_SCRIPTS/reports/round7_full_integration_mapping_20260707.csv`（12 PROV + 2 final-only）
- `05_SCRIPTS/reports/round7_full_integration_plan_20260707.sql`（provisional clear + 検証・未実行）
- スクラッチ: `/tmp/ts24_round7_scratch.db`（検証用・破棄可）
