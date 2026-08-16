# Race Weekend workflow Phase B-2: Session Extraction Staging 承認前 readiness

- 日付: 2026-07-06
- 種別: **Phase A read-only readiness**（正本DB `mode=ro` のみ・DDL 未実行・コード/Excel/DB 無変更）
- 設計元: `reports/race_weekend_live_workflow_design_20260706.md` §3 Stage 2 / §1a（設計 Task 3）
- 成果物: 本レポート + `reports/race_weekend_session_staging_ddl_20260706.sql`（レビュー用DDL・未実行）
- 前提: Phase B-1（Session Scan ボタン・§51）は apply 済み。import_queue に ROUND7 の 2d_extract pending あり。

---

## 1. 目的 / ゲート

Race Weekend 中にセッション直後の 2D outing だけを抽出し、正本DB内の **provisional 3テーブル**
（`runs_provisional` / `laps_provisional` / `lap_suspension_provisional`）へ staging する新スクリプト
**`session_extract_staging.py`**（未実装）の実装可否を確定する。

- 本レポートは read-only。**実装・DDL実行・provisional 行 INSERT は `Session staging implementation GO` 受領後のみ**。
- 業務6テーブル（runs / laps / lap_suspension / race_results / pdf_lap_times / pdf_lap_times_v2_staging）は
  Race Weekend 中一切触らない（§50 原則）。provisional テーブルは正本DB内に住むが業務テーブルではない
  （§34/§38 の `pdf_lap_times_v2_staging` と同じ位置付け）。

作業前 `git status --short`（05_SCRIPTS・HEAD `5651d97`・記録のみ・無変更）:
tracked M = CLAUDE.md / build_excel_master.py / reports/round7_race_results_apply_dry_run_20260629.md /
requirements_workbench.txt / ts24_workbench.py。untracked = 既知の作業メモ md 群・§45-51 の新スクリプト/レポート
（suspension_report.py・parse_race_pdf.py・reports/race_weekend_*_20260706.md 等）・`_backup_susp_speed_20260620-071355/`。
本タスクの追加はレポート2ファイルのみ。

## 2. 現行抽出ロジック確認（build_master_db.py・960行・read-only 精読）

**確定方針: 本番関数を import で再利用し、2D パーサを二重実装しない。**

### 2a. `extract_outing(mes_path, base=None)`（L207-361）

- 引数: `mes_path`=outing ディレクトリ（Path）、`base`=内部 .DDD/.LAP/.HED の stem。
  nested 以外（copia/loose）ではフォルダ名と base が一致しないため**呼び出し側が base を必ず明示**する
  （`gated_outings` が返す `(mes_path, base)` をそのまま渡せば良い）。
- 戻り値: `{"laps": [lap_dict, ...], "nlaps": int}` または `None`（SPEED_FRONT/SUSP_FRONT 欠落・
  サンプル<10・LAPマーカー無し・有効ラップ0 のとき）。EngineWarmup 系は通常ここで None になる。
- lap_dict のキー（1ラップ分）:
  - `lap_no` / `lap_time_s`（`_lap_timebase` の tb=400/1000 自動判定済・HED Fastest×0.97 stray フィルタ済・MIN_LAP_S=30s）
  - `susf_mean` / `susf_max` / `susr_mean`
  - `f_dive_spd` / `f_reb_spd` / `r_dive_spd` / `r_reb_spd` / `rear_light_brk`
  - `brk_f_dive_spd_avg` / `brk_f_dive_spd_peak` / `ce_r_spd_avg` / `ce_r_spd_peak` / `ph12_rear0_s`（§19 ゾーン5指標）
  - `phase_spd_matrix` = **22値タプル（`PHASE_SPD_NEW_COLS` 順・§44）**。n<5→avg NULL / n<10→peak(p95) NULL のガード込み
  - `metrics` = `{MID_CORNER|FULL_BRAKING|CORNER_EXIT: {n, susf, susr, speed, brake, thr}}`（3エリア・lap_metrics 相当）
- → **lap_suspension の 2D 由来列は全てこの戻り値だけで組み立て可能**（後述 §2c の WF 6列を除く）。

### 2b. `discover_outings` / `gated_outings` / `session_canon_2d` の入力

| 関数 | 入力 | 備考 |
|---|---|---|
| `discover_outings(event_dir)` L380 | イベントディレクトリ Path のみ | 3層 nested/copia/loose 横断・NOISE(`^D0-`等)除外・重複除外。→ `[(mes_path, base, tier)]` |
| `gated_outings(ev, ev_circ)` L418 | `ev` は **`ev["dir"]` キーだけ使用**の dict + イベント基準サーキット文字列 | copia/loose のみ HED サーキット矛盾ゲート。→ `[(mes_path, base)]` |
| `session_canon_2d(base, rnd)` L78 | base 文字列 + round 文字列（"ROUND7"等） | FP/QP/WUP1/WUP2/RACE1/RACE2/SP/TESTx_DAYy 正規化 |
| `circuit_from_2d(event_dir)` L157 | イベントディレクトリ | `*.line` の stem（"Ring"除外）→ `circuit_canon` |

→ staging は `ev = {"dir": event_dir}` の最小 dict で `gated_outings` を verbatim 再利用できる。
イベントメタ（date/round/rider）は既存 `EVENT_RE`（`^(\d{8})-(ROUND\d+|TEST\d+)-(DA77|JA52|JA25)$`）で
フォルダ名から取得（`discover_events()` と同一規約）。

### 2c. `_build_lap_suspension`（L640-697）の 69列射影と provisional で欠ける入力

正本 `lap_suspension`（PRAGMA 実測 69列）への射影元:

| 由来 | 列 |
|---|---|
| **runs（Original setup 由来）** | `f_spr_l`/`f_spr_r`/`r_spr` → **WF 6列**: `wf_f_apex_n` `wf_r_apex_n` `wf_f_brk_n` `wf_r_brk_n` `wf_f_ce_n` `wf_r_ce_n`（WF_F=susF×(F_SPR_L+F_SPR_R)/2, WF_R=susR×R_SPR×0.5） |
| runs（構造メタ） | `run_id` `round` `circuit` `session` `rider` `run_no` `date` |
| laps | `lap_id` `lap_no` `lap_time_s`(+`lap_time_fmt`) `lap_susF_mean`(=susf_mean) `lap_susF_max` `lap_susR_mean` `f_dive_spd` `f_reb_spd` `r_dive_spd` `r_reb_spd` `rear_light_brk` |
| lap_metrics（=extract_outing の metrics） | `apex_*`(MID_CORNER) `brk_*`/`fullbrk_*`(FULL_BRAKING) `ce_*`(CORNER_EXIT) の count/spd/susF/susR |
| extra_by_lapid | `brk_f_dive_spd_avg/peak` `ce_r_spd_avg/peak` `ph12_rear0_s` |
| matrix_by_lapid | §44 の 22列 |
| 常時 NULL（本番仕様） | `lap_susF_min` |

**→ provisional（Original 不在）で NULL のまま残る列 = 7列のみ**:

1-6. `wf_f_apex_n` / `wf_r_apex_n` / `wf_f_brk_n` / `wf_r_brk_n` / `wf_f_ce_n` / `wf_r_ce_n`
     （バネレートは Original 由来。SpecSheet なし段階では算出不能 → **NULL 必須・0 代用禁止**）
7. `lap_susF_min`（final でも常時 NULL の既知仕様・provisional でも同じ）

残り 62列は extract_outing 戻り値 + フォルダ名/推定メタ + 暫定 run_no だけで final と同一ロジックで埋まる。
`run_no` は値は入るが**暫定連番であり final と一致する保証がない**（§2d）ことを provenance で明示する。

（`runs_provisional` 側では setup 33列 `weather`〜`tyre_rear` が全 NULL、`comment`（Report DAY1/DAY2 r48 由来）も NULL。）

### 2d. Run/setup 割当ロジック（L780-806）と provisional run_no の確認

本番は `(rider,circuit,session)` ごとに **Original の run 数 M と 2D イベント数 E から per_event=round(M/E) を算出し、
ラップ数上位 per_event 本を採用 → 時系列（base 名）順に R1.. を振り、Original pool から setup を順に consume** する。
Original が無い session-first 段階では M=0 → per_event=0 → 本番でも「2D_ONLY: 全 outing keep・時系列順連番」に落ちる。

**→ staging 設計決定を確認・妥当**: provisional run_no = **(event, session) 内の outing 時系列順**
（= base 名 sort 順。本番の 2D_ONLY パスと同一挙動）。
`run_id = PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}`、`lap_id = {run_id}_L{lap_no}`。
`PROV_` プレフィクスで final run_id と構造衝突しない。ただし final 化時に Original 突合で
run 採用集合・番号が変わり得る（ラップ数上位 per_event 本のみ採用）ため、**provisional run_no ≠ final run_no は仕様**
としてWorkbench/Report の「⏳ prov」表示で明示する。

### 2e. `_recompute_is_outlap`（L705-746）の per-session 適用可否

**結論: per-session 適用可能（1点だけ縮退あり・許容）。** 4ステップの依存:

- ① 物理下限 stray 除去: `TRACK_M[circuit]`（**MISANO=4226 登録済み**）と lap_time のみ → per-run で完結。
- ② GRID/FORMATION 除去: `mes_file` 文字列のみ → per-run で完結。
- ③ 相対 run_min×1.15: run 内 laps のみ → per-run で完結。
- ④ 単一ラップ上限ガード: **サーキット基準 P10 を DB 全 laps から算出** → イベント文脈依存。
  正本 laps に MISANO は 0 行のため ref=None → ④は silent skip（本番コードも ref 無しなら skip する実装）。
  provisional 段階では ③までで十分（GRID01 は②で確実に落ちる）。final full rebuild で④込みの正式値に置換される。

実装方針: 本番関数は `conn` の `laps`/`runs` テーブル名を直書きしているため verbatim 適用は不可。
staging では **同一 4ステップのロジックを provisional テーブル名で適用する薄いラッパ**を書く
（判定式は本番と同値・quality gate で「①②③の適用済み」を記録。数式の二重実装はこの is_outlap ラッパのみで、
2D パース/指標計算の二重実装はゼロ）。

## 3. provisional 3テーブル DDL 案

全文 = **`reports/race_weekend_session_staging_ddl_20260706.sql`**（CREATE TABLE IF NOT EXISTS ×3 + index + rollback コメント・未実行）。

### 3a. 構成

- `runs_provisional`: 正本 runs **49列**ミラー + provenance 6列。UNIQUE INDEX on `run_id`。
- `laps_provisional`: 正本 laps **16列**ミラー + provenance 6列。UNIQUE INDEX on `lap_id`。
- `lap_suspension_provisional`: 正本 lap_suspension **69列**ミラー（PRAGMA 実測順・同名同型）+ provenance 6列。
  UNIQUE INDEX on `lap_id`。
- provenance 6列（3テーブル共通）:
  `data_stage TEXT NOT NULL DEFAULT 'provisional'` / `intake_ts TEXT NOT NULL` /
  `source_manifest_hash TEXT`（registry.sha256）/ `source_file_path TEXT` /
  `provisional_event_key TEXT`（イベントフォルダ名）/ `quality_status TEXT`（PASS/WARNING。FAIL は行を作らない）。

### 3b. provisional で NULL のまま残す列（正本と同名だが埋めない）

- `lap_suspension_provisional`: **WF 6列 + lap_susF_min**（§2c）。
- `runs_provisional`: **setup 33列（weather〜tyre_rear）** + `comment`（Report 由来）。`source='2D_PROVISIONAL'`。
- 0 での代用は全面禁止（0≠NULL 意味論・§19/§20 準拠）。

### 3c. 位置付け

正本DB内の**非業務テーブル**（§34/§38 の `pdf_lap_times_v2_staging` と同パターン）。
Workbench overlay（Task 5）・Report v2 provisional（Task 6）だけが参照し、final 化後は
`provisional_event_key` 単位で DELETE される消耗品。Supabase / DB Master の同期対象外。

### 3d. 衝突確認（実測）

`SELECT name FROM sqlite_master WHERE name LIKE '%provisional%'` → **0 件**。3テーブルとも名前衝突なし。

## 4. `session_extract_staging.py` 仕様（未実装・GO 後に実装）

- **dry-run 既定**（`--apply` 無しでは正本DBを `mode=ro` でしか開かない）。
- CLI: `--db`（既定=正本）`--event <folder名>` `--rider` `--session`（FP/QP/... 絞込）
  `--source-file`（単一 outing 指定）`--apply` `--limit N` `--report <path>`。
- 入力 = `import_queue` の `status='pending' AND target_kind='2d_extract'` を `--event/--rider/--session` でフィルタ
  （registry JOIN で file_path/sha256 を取得）。
- パイプライン:
  1. イベントメタ解決（フォルダ名 EVENT_RE）→ circuit 推定（`circuit_from_2d` の `.line` fallback。Report があれば
     `circuit_from_report` 優先＝本番 `event_circuit` と同順）。
  2. `gated_outings` → 対象 outing を queue と突合 → `extract_outing` で抽出（**本番 import・二重実装なし**）。
  3. per-lap 組み立て（§2c の射影・WF 6列 NULL）→ per-session is_outlap ラッパ（§2e）。
  4. Quality gate（§5）→ dry-run report（件数・NULL 率・gate 判定・INSERT 予定行数）。
  5. `--apply` 時のみ: **フルDBバックアップ `02_DATABASE/_backup_session_staging_<TS>/`** →
     1トランザクションで DDL（IF NOT EXISTS）+ 自然キー（run_id/lap_id）`INSERT OR REPLACE`（冪等・再実行安全）→
     **業務6テーブル before==after assert（runs/laps/lap_suspension/race_results/pdf_lap_times/pdf_lap_times_v2_staging・
     件数+必要に応じ sha256。違反→rollback・exit 3）** → commit。
  6. queue 状態遷移: `pending → processing →`（gate 判定後）`awaiting_gate`（done は final 化時のみ・§22 状態機械準拠）。
     FAIL outing は `failed` + error 記録。
- exit code（プロジェクト慣行）: **0**=成功（dry-run 完了 or apply 成功）/ **1**=事前チェック失敗 /
  **2**=quality gate FAIL あり（隔離・部分成功）/ **3**=apply 中 assert 違反→rollback。

## 5. Quality gate 案（apply 前・FAIL は隔離＝INSERT しない）

outing 単位で判定し、結果を `data_quality_log`（check_name=`stage_*` 系・PASS/WARNING/FAIL）へ記録:

| # | チェック | FAIL 条件 |
|---|---|---|
| 1 | lap count | `extract_outing` 有効ラップ 0（None 含む。EngineWarmup は「FAIL」でなく skip 記録） |
| 2 | rider / session / circuit 推定 | フォルダ名 rider 不一致・session_canon_2d 不明 prefix・circuit 推定空 |
| 3 | lap_time 分布 | 60–300s 外のラップ（is_outlap 除外後に best がレンジ外なら FAIL、個別ラップは WARNING） |
| 4 | braking/apex/exit 成立率 | fullbrk/apex/ce の n>0 ラップ比率が異常低（apex=0% 等）→ WARNING、全エリア 0 → FAIL |
| 5 | §44 22列 | 列が dict に存在すること（必須）。成立率（非NULL率）は WARNING 記録のみ（Exit 系 ~46% NULL は本質・§44b） |
| 6 | zero≠NULL | n<5/n<10 条件のセルに 0.0 が入っていない（ガード違反=FAIL） |
| 7 | PROV run_id 重複 | 生成 run_id/lap_id のバッチ内・既存 provisional との重複 0（INSERT OR REPLACE 前に検出し報告） |
| 8 | source hash 冪等 | 同一 `source_manifest_hash` が既に取込済みなら skip（再実行で行が増えない） |

FAIL outing は provisional 3テーブルへ**一切 INSERT せず**、`data_quality_log` + queue `failed` に隔離記録。

## 6. Round7 JA52 実テスト対象確認（read-only 実測）

- ディレクトリ `DATA 2D/20260612-ROUND7-JA52/`: **nested `.MES` レイアウトのみ**（copia/loose 無し）。
  セッション prefix = FP / QP / R1 / R2 / WUP1 / WUP2 + D0（EngineWarmup・NOISE 除外対象）。
- **`discover_outings` 実行結果 = 33 outing（全 nested）**・session 内訳 FP5 / QP7 / RACE1 8 / RACE2 4 / WUP1 4 / WUP2 5
  （EngineWarmup/GRID を含む数。有効ラップの出る walk はさらに少ない見込み）。`D0-...` は NOISE 正規表現で除外済み。
- registry/queue（正本DB `mode=ro`）: 当該イベント **registry 34 行（2d_outing 33 + report 1・全 status=queued・
  sha256 全行あり=manifest hash 完備）**、queue **pending 34（2d_extract 33 + report_import 1）**。
  → staging の入力条件（pending 2d_extract）を満たす。
- circuit 推定: **`Misano.line` と `EVENT.INI`（Name=Misano, World circuit）が存在** →
  `circuit_from_2d` 実測 = `Misano` → canon **`MISANO`**（`TRACK_M['MISANO']=4226` 登録済み・is_outlap ①有効）。
  ※Report `01_REPORTS/JA52/20260612-ROUND7-JA52.xlsx` は 2026-06-28 に保存済みで実在するが（§35）、
  **staging は Report 非依存で動くこと自体がテスト目的**のため `.line` fallback 経路を主検証とする。
- 正本DB: runs/lap_suspension とも ROUND7(2026)/MISANO は **0 行**（2D final 未取込）→ 汚染リスクなし・overlay 効果が明確。
- **実テスト計画**: 最初の dry-run は小さなサブセット（例 `--event 20260612-ROUND7-JA52 --session FP`、5 outing）。
  初回 apply も同サブセット限定（`--limit` 併用）。**33 outing 一括は最初からやらない**。
  検証後に残 session を段階投入。

## 7. rollback 案

- 全撤去: `DROP TABLE` ×3（+index）。イベント単位: `DELETE ... WHERE provisional_event_key=?` ×3。
  （DDL ファイル末尾にコメントで同梱。）
- 業務テーブルは**構造上到達しない**（別テーブル + apply 時 before==after assert の二重防御）。
- apply 前フルバックアップ `_backup_session_staging_<TS>/` から DB ごと差し戻しも可能。
- queue は `awaiting_gate/failed → pending` に戻せば再処理可能（scanner 冪等）。

## 8. Multi-agent operating check

- **2D extraction**: 本番 `discover_outings`/`gated_outings`/`extract_outing`/`session_canon_2d` を import 再利用・
  パーサ二重実装ゼロ（唯一の再実装は is_outlap の provisional テーブル向け薄ラッパ §2e）。
- **DB integrity**: provisional 3テーブル分離・自然キー UNIQUE・INSERT OR REPLACE 冪等・業務6テーブル before==after assert・
  フルバックアップ・rollback=DROP/DELETE。
- **Quality gate**: dry-run 既定・8チェック・FAIL 隔離（INSERT しない）・`data_quality_log` 記録・0≠NULL 厳守。
- **Operations**: Tatsuki 手順 = 保存 → 🔍 Session Scan（済 §51）→ （GO 後）Session Import staging（CLI or 将来ボタン）。
  初回は FP のみの限定 dry-run/apply。
- **Workbench**: 本タスクでは**触らない**（overlay `_load_data` 切替 = Task 5・別承認）。
- **Supervisor（別承認のまま維持）**: Workbench overlay / Report v2 provisional モード / Supabase sync/cleanup /
  DB Master 再生成 / origin push / final 化（full rebuild+cutover）/ folder watch — 全て本 GO に含まれない。

## 9. 未実施リスト（本レポート時点・inbox タスク準拠）

- `session_extract_staging.py` の実装・DDL 実行・provisional 行 INSERT（→ `Session staging implementation GO` 待ち）
- Workbench overlay（`_load_data` UNION・⏳ prov マーク）
- Report v2 provisional モード（cover リボン・filename トークン）
- folder watch（Option C・将来）
- Supabase sync / remote_extra 24 cleanup
- DB Master 再生成
- origin push（未コミット変更は §51 時点のまま）
- final 化（full rebuild + 決定論ゲート + cutover + provisional クリア）

**次ゲート文言 = `Session staging implementation GO`。**
