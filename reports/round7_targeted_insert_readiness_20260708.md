# Round7 targeted insert readiness — 2026-07-08 (Phase A, read-only)

**Task:** `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-08 最優先）+ 指示書 `reports/round7_targeted_insert_code_instruction_20260708.md`。
Round7 JA52 を provisional から final(canonical `runs`/`laps`/`lap_suspension`)へ **Option A = ROUND7-only targeted insert** で移行する準備。
**本フェーズは書込ゼロ**（canonical は `mode=ro`・scratch は /tmp のみ）。実書込は `Round7 targeted insert GO` 受領後の Phase B。

## 0. 結論（読む人向け要約）

- **設計・現状検証・移行アリスメティックは全て read-only で確定** → targeted insert の設計は完成し、`apply_round7_targeted_insert.py`（dry-run 既定・ゲート内蔵・未実行）として具体化済み。
- **⛔ ただし必須の「fresh full rebuild → 決定論ゲート」が現時点で実行不能（iCloud offloading・下記 §3）** → **Phase B（書込）へは進めない**。
  Round7 の *正確な final 行の値*（Original setup マージ + wheel-force 列）は fresh rebuild でしか生成できないため、materialize 完了までブロック。
- **推奨 = NO-GO（今は書けない）**。先に `DATA 2D` イベント26フォルダを materialize（0 dataless 確認）→ `build_master_db.py --all` → `r7_gate.py` ALL PASS → その後に限り Phase B の apply。ゲートが通らない限り書込禁止（Supervisor stop）。

## 1. 現在の canonical 件数（実測・mode=ro）

| テーブル | 件数 | 期待 |
|---|---:|---|
| runs | 275 | (Round7=0) ✓ |
| laps | 1202 | ✓ |
| lap_suspension | 1202 | ✓ |
| race_results | 866 | (Round7=74) ✓ |
| runs_provisional | 12 | ✓ |
| laps_provisional | 79 | ✓ |
| lap_suspension_provisional | 79 | ✓ |
| pdf_lap_times_v2_staging | 7710 | (Round7 PASS=1094) ✓ |
| race_lap_detail (VIEW) | 12763 | 存在 ✓ |
| source_file_registry | 405 | ✓ |
| import_queue | 397 | ✓ |
| data_quality_log | 1340 | 保全対象 |
| analysis_run_log | 11 | 保全対象 |
| metric_version_log | 32 | 保全対象 |

canonical DB mtime = 2026-07-06 17:02（§46e 以降 read-only 作業で不変）。

## 2. Round7 現状（apply 前の必須確認・全て充足）

- final `runs`/`laps`/`lap_suspension` の **Round7 = 0 / 0 / 0**（apply 前提どおり）。
- provisional = **12 / 79 / 79**（event_key `20260612-ROUND7-JA52` 100%）。
- `race_results` Round7 = **74**。`pdf_lap_times_v2_staging` Round7 PASS = **1094**。
- 0-lap placeholder 2件が canonical `runs` に実在: `NA_MISANO_RACE1_JA52_R1` / `NA_MISANO_RACE2_JA52_R1`（round=''・laps=0・lap_suspension=0）。

### provisional 分布（実測）= §64 mapping と完全一致
| session | prov run | laps | best |
|---|---|---:|---|
| FP | R1/R2/R3 | 4/7/4 | 99.429/98.791/98.364 |
| QP | R1/R2/R3/R4 | 4/3/5/2 | 97.953/98.250/97.636/101.714 |
| WUP1 | R1 | 6 | 98.109 |
| WUP2 | R1/**R2** | 4/**2** | 98.160/**98.045** |
| RACE1 | R1 | 19 | 98.055 |
| RACE2 | R1 | 19 | 97.778 |
計 12 runs / 79 laps。

## 3. ⛔ Fresh scratch rebuild = 現時点で実行不能（iCloud offloading）

指示 §Phase A(3) は「/tmp へ rebuild → final Round7 = 13/77/77 確認 → 非Round7 1202 laps byte一致確認」を要求。
**本セッションで2回試行（前景10分・背景）とも失敗:**

```
TimeoutError: [Errno 60] Operation timed out
  parse_2d_channels.py read_channel -> path.read_bytes()
```

- 原因 = **`DATA 2D` の 2D ファイルが iCloud にオフロード済**（CLAUDE.md §24a の既知リスクが顕在化）。
  build_master_db はファイル中身を読むため、dataless ファイルで DL 待ち → timeout/空読み。
- 実測: `build_master_db` が処理するイベント26フォルダ（`EVENT_RE=^\d{8}-(ROUND\d+|TEST\d+)-(DA77|JA52|JA25)$`）内に
  **dataless 17,785 files / 3.59 GB**。ROUND7-JA52 自身も 1,626 files offloaded。
  （非対象の `DATA WSSP KAWASAKI` 2.24 GB は EVENT_RE 非該当で build が読まないため除外可）。
- materialize 試行（`brctl download` + 並列 force-read）→ **~10–20 files/min の超スロットリング**（ディスク 91% 使用 = macOS "Optimize Storage" が DL を抑制）。
  1ファイル read テスト = 23秒後に **0 bytes 返却**（materialize 不成立）。→ この環境では full rebuild を成立させられない。

### 代替の read-only 根拠（rebuild なしで確認できた事実）
- **移行アリスメティックを現 provisional 実データで検証**: 12/79 →（WUP2 R2 の −2 laps drop）→ 11/77 →（RACE1 R2 + RACE2 R2 = 0-lap Original-only を +2 runs）→ **13 / 77**。**final 13 runs / 77 laps と一致**（read-only 実データで確認）。
- **§64（2026-07-07・~18h 前）は同一・無変更の source から fresh full rebuild に成功**し、
  final=13/77/77・非Round7 laps=1202 byte一致・受入ゲート PASS・BLOCKER 無しを確認済（`round7_full_integration_readiness_20260707.md` / mapping.csv）。
  source は不変（Round7 2D=2026-06-12 保存・canonical mtime 2026-07-06）。→ 値は §64 時点と同一になる見込みだが、**Phase B では必ず再取得+再ゲートする**。

## 4. Targeted insert 設計（Option A・追加のみ・cutover 不使用）

### 4a. 書き込むテーブル = `runs` / `laps` / `lap_suspension` のみ
- **DELETE**（placeholder 2件・子行も防御的に）:
  `NA_MISANO_RACE1_JA52_R1`, `NA_MISANO_RACE2_JA52_R1`（現状 laps=0/susp=0 なので子行なし）。
- **INSERT**（scratch の Round7 行 = 13 runs / 77 laps / 77 lap_suspension）。final run_id は PROV_ 接頭辞を外した §20a 規則:

| # | final run_id | session | laps | best | 由来 |
|---|---|---|---:|---|---|
| 1 | `20260612_ROUND7_MISANO_FP_JA52_R1` | FP | 4 | 99.429 | ORIGINAL+2D |
| 2 | `20260612_ROUND7_MISANO_FP_JA52_R2` | FP | 7 | 98.791 | ORIGINAL+2D |
| 3 | `20260612_ROUND7_MISANO_FP_JA52_R3` | FP | 4 | 98.364 | ORIGINAL+2D |
| 4 | `20260612_ROUND7_MISANO_QP_JA52_R1` | QP | 4 | 97.953 | ORIGINAL+2D |
| 5 | `20260612_ROUND7_MISANO_QP_JA52_R2` | QP | 3 | 98.250 | ORIGINAL+2D |
| 6 | `20260612_ROUND7_MISANO_QP_JA52_R3` | QP | 5 | 97.636 | ORIGINAL+2D |
| 7 | `20260612_ROUND7_MISANO_QP_JA52_R4` | QP | 2 | 101.714 | ORIGINAL+2D (prov WARNING) |
| 8 | `20260612_ROUND7_MISANO_WUP1_JA52_R1` | WUP1 | 6 | 98.109 | ORIGINAL+2D (prov WARNING) |
| 9 | `20260612_ROUND7_MISANO_WUP2_JA52_R1` | WUP2 | 4 | 98.160 | ORIGINAL+2D (WUP2-01) |
| 10 | `20260612_ROUND7_MISANO_RACE1_JA52_R1` | RACE1 | 19 | 98.055 | ORIGINAL+2D |
| 11 | `20260612_ROUND7_MISANO_RACE1_JA52_R2` | RACE1 | 0 | (NULL) | **NEW Original-only**（placeholder NA_RACE1 を置換）|
| 12 | `20260612_ROUND7_MISANO_RACE2_JA52_R1` | RACE2 | 19 | 97.778 | ORIGINAL+2D |
| 13 | `20260612_ROUND7_MISANO_RACE2_JA52_R2` | RACE2 | 0 | (NULL) | **NEW Original-only**（placeholder NA_RACE2 を置換）|

- **DROP される provisional 行**: `PROV_...WUP2_JA52_R2`（2 laps・98.045）。build_master_db の Original マージ仕様（WUP2 M=1 → per_event=1 で **top-lap（＝最多ラップ）outing のみ採用**）による。全ラウンド共通挙動。
- **⚠️ Tatsuki 要確認（adversarial review 指摘・§64c の開示を補強）**: WUP2 で採用される R1 は **4 laps・best 98.160**、drop される R2 は **2 laps・best 98.045**。
  "top-lap"＝最多ラップ選択のため、**WUP2 セッションの最速ラップ(98.045)が final DB から落ちる**（WUP2 session-best が 98.045→98.160 に後退）。§64c の「−2 laps」だけでは伝わらない結果なので明示。これは build_master_db の標準挙動（全ラウンド共通）だが、承認前に知っておくべき影響。
- **正確な final 行の値は fresh rebuild からのみ取得**（Original setup 33列 + wheel-force `wf_*_n` は provisional では NULL・rebuild で充填）。→ §3 のブロックが解けるまで INSERT 対象行を確定できない。
- **placeholder 置換は ID 継承ではない**（adversarial review 指摘）: 削除する `NA_..._RACE1/2_JA52_R1` と新規 `..._RACE1/2_JA52_R2` は **run_id 名が異なる**。「対応」は意味的（両者とも 0-lap Original-only RACE 行）であり、件数（DELETE 2 / INSERT 13 のうち 2）で整合するだけ。run_id 連続性を仮定しないこと。

### 4b. 保全（書き込まない）を証明
- canonical schema 実測: `run_id`/`lap_id` は **PRIMARY KEY**、laps/lap_suspension に **FK なし・trigger なし**。Round7 run_id は現在0件 → **衝突なし**。placeholder は別 run_id → DELETE と INSERT は独立。
- `apply_round7_targeted_insert.py` は **`runs`/`laps`/`lap_suspension` 以外に一切 SQL を発行しない**。以下は before==after を1トランザクション内で assert（違反で全 ROLLBACK）:
  `pdf_lap_times_v2_staging`(7710) / `race_lap_detail`(VIEW) / `source_file_registry`(405) / `import_queue`(397) /
  `data_quality_log`(1340) / `analysis_run_log`(11) / `metric_version_log`(32) / `race_results`(866) / `pdf_lap_times`(7613) /
  provisional 3テーブル(12/79/79)。
- **cutover_db.py 不使用**・DB 丸ごと swap なし・DDL(CREATE/ALTER/DROP) なし。→ §64d の data-loss 欠陥を回避。

### 4c. スクリプト = `apply_round7_targeted_insert.py`（新規・dry-run 既定・py_compile PASS）
- 入力 = `--scratch <fresh full rebuild>.db`。`--apply` 無しは canonical `mode=ro`・書込ゼロ。
- **2段ゲート内蔵**（両方 PASS でないと apply 拒否）:
  1. **決定論ゲート**（`r7_gate.py` と同ロジック）: schema一致 / 非Round7 byte一致 / Round7 13/77/77。
  2. **content ゲート**（adversarial review 指摘で追加）: 「移行の目的そのもの」を検証 —
     ①13 Round7 runs すべて `f_spr_l` NOT NULL（Original setup マージ済＝provisional の NULL 状態でない）
     ②Round7 lap_suspension に `wf_f_apex_n` 充填行 ≥1（wheel-force 算出済）
     ③data-bearing 11 runs の `best_lap_s` が §64 mapping と一致（±0.001）
     ④0-lap Original-only R2 2件が round='ROUND7'・laps=0 で存在。
     → **NULL-setup の scratch 行が誤って canonical に入るのを防ぐ**（従来の shape/preservation ゲートだけでは素通りしていた穴を塞ぐ）。
- `--apply`: フルバックアップ `02_DATABASE/_backup_round7_targeted_<TS>/` → BEGIN → placeholder DELETE → Round7 INSERT(明示列リスト) → 保全 assert → 最終件数 assert(286/1279/1279・Round7 13/77/77) → **content ゲート再検証（canonical 反映後）** → COMMIT / 違反時 ROLLBACK。

## 5. Rollback 計画
- 主: apply 直前フルバックアップ `02_DATABASE/_backup_round7_targeted_<TS>/ts24_unified.db` から丸ごと復元。
- 副（targeted）: `DELETE FROM lap_suspension/laps/runs WHERE round='ROUND7'`（Round7 のみ除去）+ placeholder 2行を backup から `INSERT ... SELECT` で復元。
- トランザクション内 assert 違反時は自動 ROLLBACK（canonical 無変更）。

## 6. 検証計画（Phase B・apply 後）
- runs=286 / laps=1279 / lap_suspension=1279。Round7=13/77/77。非Round7 1202 laps 不変（backup 比較 byte 一致）。
- placeholder NA_MISANO_RACE1/2_JA52_R1 消滅・`..._RACE1/2_JA52_R2` 出現。
- `pdf_lap_times_v2_staging`=7710・`race_lap_detail` VIEW が Round7 PASS 行を返す・quality/queue/registry 件数不変。
- provisional 12/79/79 **不変**（本 GO では clear しない）。
- Workbench: Round7 が **final** として表示（overlay の ⏳prov ではなく通常 run）+ MISANO/JA52 の重複なし（offscreen smoke）。GUI 最終目視 = Tatsuki ローカル。

## 7. Provisional clear = 別 GO
- 指示どおり本 targeted insert では provisional 3テーブルを **clear しない**。
- 推奨順: ① targeted insert → ② Workbench で final 表示確認 → ③ 別 `Round7 provisional clear GO`（`round7_full_integration_plan_20260707.sql` の [1] DELETE 段を再利用）。

## 8. スコープ外（禁止遵守・本フェーズ未実施）
cutover_db.py / 全DB rebuild-swap / v2_staging drop / race_lap_detail 破壊 / registry・queue・quality 更新 /
`refresh_db_master_safe.py` / `sync_to_supabase.py` / origin push / provisional clear。

## 9. 次アクション（Tatsuki 判断）
1. **materialize の解消**（推奨）: `DATA 2D` の26イベントフォルダを Finder「今すぐダウンロード」or ディスク空き確保で dataless=0 にする。
   その後 Claude Code が `build_master_db.py --all` → `r7_gate.py` ALL PASS を確認 → **その時点で改めて GO 判断**。
2. ゲート ALL PASS 後に限り `Round7 targeted insert GO` → `apply_round7_targeted_insert.py --apply`。
3. ゲートが通らない場合は **書込しない**（NO-GO 維持）。

## 10. Adversarial review（3 lens 並列 + synthesis・2026-07-08）

canonical 書込をゲートする設計のため、apply スクリプト + 計画を3独立レビュー（safety / constraint / numeric-logic）で敵対的検証。
- **safety**: apply は runs/laps/lap_suspension のみ書込・禁止テーブルに COUNT 不変 assert・rollback あり・単一 BEGIN/COMMIT・subprocess/network/git なし → **ゲートを skip する/PK 衝突/部分 commit/不正 committed state の経路なし**。低リスク hardening 3点を指摘 → **全て対応済**:
  ①backup が `-wal`/`-shm` 未取得 → **`PRAGMA wal_checkpoint(TRUNCATE)` 後にバックアップ + sidecar もコピー**。
  ②`busy_timeout` 未設定/TOCTOU → **`PRAGMA busy_timeout=30000` + apply 前に他 writer(Workbench/Streamlit)を閉じる注意を明示**。
  ③dry-run print が laps 数ハードコード → **scratch から動的算出**。
- **constraint**: §64d 禁止リスト（cutover / v2_staging / race_lap_detail / quality・queue・registry / DB Master / Supabase / push / provisional clear）に**違反なし**。
- **numeric-logic**: 12/79→13/77 変換・286/1279/1279 総計・placeholder 整合は**算術的に厳密**・矛盾なし。
- **検出された material finding（対応済/反映済）**:
  - [medium] shape/preservation ゲートが Round7 行の **setup/WF 充填を未検証** → **content ゲートを追加**（§4c・script 反映・py_compile PASS）。
  - [medium] **WUP2 最速ラップ(98.045)が final から落ちる** → §4a に Tatsuki 要確認として明示。
  - [low] placeholder は ID 継承でなく件数整合 → §4a に注記。
  - [low] full rebuild は「値生成」でなく「preservation ゲート」のために必須 → 設計裏付け。
- **総合**: **fresh-rebuild 決定論ゲート + content ゲートが PASS すれば canonical 書込は安全**にゲートできる、が review 結論。ゲート未達なら書かない。

---
成果物: `apply_round7_targeted_insert.py`（新規・未実行・2段ゲート内蔵・py_compile PASS）/ 本 readiness / `r7_gate.py`（scratchpad・検証用）。
canonical DB・業務テーブル・Supabase・DB Master 全て無変更。**⛔ Phase B（書込）は iCloud materialize → fresh rebuild → 両ゲート ALL PASS の後・かつ `Round7 targeted insert GO` 明示後のみ**。
