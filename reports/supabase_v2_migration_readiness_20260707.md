# Supabase v2 Migration Readiness（Phase A・read-only 監査）

- **日付:** 2026-07-07
- **担当:** Claude Code（read-only readiness エージェント）
- **入力:** `reports/supabase_v2_architecture_design_20260707.md`（Codex設計）/
  `04_REFERENCE/SQL_SCHEMAS/supabase_v2_core_schema_20260707.sql`（提案DDL）/
  `sync_to_supabase.py` v3 / `supabase_audit.py` / `reports/db_master_online_sync_apply_20260702.md` /
  正本DB `02_DATABASE/ts24_unified.db`（`mode=ro` PRAGMA のみ）
- **書込:** 本レポート1ファイルのみ。正本DB・Supabase・既存コードは一切無変更。

---

## 1. 目的とゲート

Supabase を現行の public 4テーブル mirror（race_results / lap_times / sessions_2d / lap_times_2d）から、
正規化コア + metric-long + 互換ビューの **`ts24_v2` schema** へ移行するための readiness 監査。

**本タスク = Phase A（read-only）。以下は全て別GO（実行禁止）:**

| 行為 | ゲート |
|---|---|
| `supabase_v2_core_schema_20260707.sql` の本番実行 | `Supabase v2 schema GO` |
| v2 への初回 sync / backfill | `Supabase v2 backfill GO` |
| remote_extra 24行 cleanup（`cleanup_proposal_20260702.sql`） | 別GO（§46e以降 保留中） |
| 旧 public 4テーブルの変更・削除 | 別GO（dashboard 依存のため最後） |

正本は引き続き local `ts24_unified.db`。Supabase は mirror / query layer（正本ではない）。

---

## 2. v2 schema レビュー（13テーブル案 vs local 正本）

### 2.1 総合判定: **概ね整合・ただし要修正 7点**（実行前に DDL 改訂を推奨）

方向性（正規化コア + `lap_phase_metrics` metric-long + compatibility view + `data_stage` +
provenance 3テーブル）は local の §18-§20/§50-§57 の実態（provisional 3テーブル・quality 5テーブル・
metric_version_log 32行）と噛み合っており、採用可。以下は実行前に直すべき点。

### 2.2 自然キー整合（§1c との照合）

| v2 テーブル | v2 UNIQUE | §1c 現行キー | 判定 |
|---|---|---|---|
| sessions | (event_id, rider_id, session_type, session_date, data_stage) | sessions_2d: (round,circuit,session_type,rider,run_no,**date**) | ✅ 整合。event_id が season を内包するため **round 番号のシーズン跨ぎ再利用問題**（2025/2026 ROUND1 PHILLIP ISLAND）は event_id 側で解決され、さらに session_date も保持＝二重に安全 |
| runs | (session_id, run_no, data_stage) | 同上 | ✅ session_id 経由で date/round を内包 |
| laps | (run_id, lap_no, data_stage) | lap_times_2d: (+lap_no,+date) | ✅ run_id=local 規則 `{YYYYMMDD}_...` で date 内包 |
| race_results | (event_id, session_type, rider_no, position) | (round_no,circuit,session_type,rider_no,position) | ✅ 同型でより強い（season 付き）。**留意:** position をキーに含む現行慣行を踏襲＝順位訂正時に旧行が残留し得る（現行と同じ既知特性。v2 では quality_events で検出可能にする） |
| result_laps | (event_id, session_type, rider_no, lap_no) | lap_times: (round_id,circuit,session_type,rider_num,lap_no) | ⚠️ ほぼ整合だが **legacy(pdf_lap_times) と v2 staging が同一キーで衝突する**（意図的 overlay に使えるが、投入順の規約が必須。§3.5 参照） |
| lap_phase_metrics | (lap_id,phase,subsystem,channel,side,direction,statistic,data_stage,metric_version) | 新規 | ✅ metric_version 込みで良設計 |

`NULLS NOT DISTINCT` は PostgreSQL 15+ 構文。Supabase は対応済み（既存
`supabase_dedup_and_constraints_*.sql` でも使用実績あり）。

### 2.3 要修正点（実行前に DDL 改訂）

1. **【BLOCKING】`v_sync_runs` の `rs.*` で `run_id` 列が重複** — `r.run_id` と `run_setup.run_id`
   の両方が select され、Postgres は `CREATE VIEW` 時点で
   `column "run_id" specified more than once` でエラー → **COMMIT 内の全DDLが失敗する**。
   `rs.*` をやめ run_setup の30列を明示列挙（run_id 除外）すること。
2. **【設計】track_temp / air_temp / weather の置き場所が local と不一致** — local では
   `runs` の **per-run 列**（run 毎に温度が違うのが実データ）。v2 は sessions に置いており、
   同一 session 内の複数 run の温度差が表現できない。→ **runs（または run_setup）へ移す**か両持ちにする。
   sessions 側は代表値（任意）とする。
3. **【設計】`lap_phase_metrics.statistic` の 'peak' は曖昧** — local の peak は
   **新22列 = p95 / 凍結2列(brk_f_dive_spd_peak)・abs別名(ce_r_spd_peak) = max**（§43/§44）。
   statistic を `avg / p95 / max / count / duration / min / mean` とし、**'peak' という語を使わない**
   （もしくは reducer 列を追加）。metric_version_log の guard_rule と一致させる。
4. **【設計】phase CHECK に PH1-2 が無い** — `ph12_rear0_s`（PH1-2 リア0mm累積秒）は
   ('braking','apex','exit','full_lap','full_brake') のどれとも定義が違う（BRAKE≥0.3bar 進入相の代理マスク）。
   CHECK に **'ph12'** を追加（推奨）、statistic='duration', unit='s'。
5. **【設計】`source_files.sha256` の意味が local と違う** — local `source_file_registry.sha256` は
   §24a の **stat ベース manifest（name|size）**であり真の sha256 ではない。v2 で `sha256` 列に
   そのまま流すと嘘になる。→ `manifest_hash` 列を別に設ける（or 列名変更）。真 sha256 は
   `--deep-hash` 実行時のみ充填。UNIQUE partial index は manifest_hash 側にも必要。
6. **【小】`runs.source` 列（2D/REPORT等の出所）が v2 runs に無い** — source_file_id で代替可能だが、
   backfill 初期は registry との突合が完全でないため `source TEXT` を保持推奨。
7. **【小】status 系の enum 不一致** — local registry.status は
   discovered/queued/incomplete/gated/unknown（§22 rev.2/§24）だが v2 source_files.status は
   default 'discovered' のみで CHECK なし。local の実値集合を CHECK に明記するか、あえて自由TEXTと
   ドキュメント化する（値の揺れは quality_events で検出）。

### 2.4 data_stage / PROV_ run の格納方針（確定案）

- v2 の `data_stage IN ('staging','provisional','final')` は local の
  `runs_provisional` 等の provenance 列（data_stage/intake_ts/source_manifest_hash/
  source_file_path/provisional_event_key/quality_status）と対応可能。
- **格納規則:** local `runs/laps/lap_suspension`（業務）→ `data_stage='final'`。
  local `*_provisional`（PROV_ 12 runs / 79 laps）→ `data_stage='provisional'`・
  **run_id/lap_id は `PROV_` prefix のまま**（PK 衝突なし: final化時は別 run_id が採番されるため）。
  quality_status（PASS/WARNING）をそのまま v2 runs.quality_status へ。
- **既定は final-only:** dashboard/compatibility view は `WHERE data_stage='final'` を既定とし、
  provisional は明示 opt-in の view（`v_..._with_provisional`）だけに出す（§54-§55 の Workbench
  overlay と同じ思想）。final化・provisional クリア時は v2 側の provisional 行も削除する運用を
  final化手順（Task 7-8）に組み込む。

### 2.5 lap_phase_metrics の metric_name / version 対応（metric_version_log 32行）

local `metric_version_log` は 32行・全 v1。分解規則（wide列名 → long キー）:

`{phase}_{side}_{direction}_spd_{stat}` → phase / subsystem='suspension' / channel='sus_speed' /
side / direction / statistic / metric_version='v1'。

| local 列群 | phase | side/direction | statistic | 備考 |
|---|---|---|---|---|
| brk_f_dive_spd_avg/peak（凍結） | full_brake※ | front/dive | avg / **max** | ※§19 の zone は FULL_BRAKING。§44 新22列の brk_* も fb_mask（FULL_BRAKING）由来 → **braking と full_brake のどちらへ載せるか要決定**。推奨: 位置系 brk_susF/R（BRAKING ENTRY）= 'braking'、速度系 brk_*_spd（FULL_BRAKING mask）= 'full_brake' と分離し、guard_rule に明記 |
| §44 の brk/apex/ce ×f/r×dive/reb×avg/peak（22列） | full_brake / apex / exit | 各 | avg / **p95** | peak_nmin=10・avg n≥5。n<5(10) は**行を作らない**（＝NULL） |
| ce_r_spd_avg/peak（abs 別名） | exit | rear/none(abs) | avg / max | direction='none'＋channel='sus_speed_abs' で dive/reb と区別。superseded_by=directional を notes に |
| ph12_rear0_s | ph12（CHECK追加後） | rear/none | duration | unit='s'・0秒は実測値 |
| f/r_dive/reb_spd（lap全体・laps由来） | full_lap | 各 | max | 旧v1指標（§18） |
| rear_light_brk | full_brake | rear/none | avg（%） | channel='rear_light_ratio', unit='%' |

**NULL/0 の扱い（厳守）:** metric-long では「行が無い＝NULL（n<5/n<10 ガード）」
「value_num=0＝実測ゼロ」。0埋め・NULL行の挿入は禁止（§19a の 0≠NULL 原則をそのまま持ち込む）。
unit は `'mm/s (relative damping-speed index)'` とし、車速 km/h 系
（apex_spd_avg/brk_spd_avg/ce_spd_avg）は channel='speed_kmh', subsystem='speed' で完全分離する。

---

## 3. Mapping 表（local → ts24_v2）

### 3.1 runs（49列）→ sessions / runs / run_setup

| local runs 列 | v2 先 | 備考 |
|---|---|---|
| run_id | runs.run_id (PK) | そのまま（PROV_ 含む） |
| rider | runs.rider_id / sessions.rider_id | riders dim（JA52/DA77 をシード） |
| circuit | sessions.circuit_id → circuits | 正規化 slug（§8 正規化表 + circuits.aliases） |
| round | events.round_no | event_id = `{season}_{round}_{circuit}`（season は date から導出） |
| session | sessions.session_type | 列名注意（local は `session`） |
| run_no | runs.run_no | |
| date | sessions.session_date | ISO 形式へ正規化（local は `YYYYMMDD` 文字列。audit と同じ 8桁⇄ISO 変換） |
| event_id | events.event_id | local event_id があれば照合、無ければ導出 |
| source | **runs.source（列追加・修正提案6）** | |
| has_2d / n_laps / best_lap_s | runs.has_2d / n_laps / best_lap_s | |
| perf_best_lap | runs.perf_best_lap_s | 改名のみ |
| comment | runs.comment | |
| weather / track_temp / air_temp | **runs 側へ（修正提案2）** | v2 案では sessions（不一致） |
| fork_type〜tyre_rear（30列: fork_type,f_set_c,f_set_r,f_tos_spring,f_tos_length,f_spr_l,f_spr_r,f_preload,f_oil_level,f_comp,f_reb,f_offset,f_offset2,f_hgt_top,f_hgt_bot,shock_type,r_set_c,r_set_r,r_spr,r_preload,r_comp,r_reb,r_tos_spring,r_tos_length,shock_len,link,ride_hgt,swing_arm,tyre_front,tyre_rear） | run_setup（同名30列） | ✅ v2 DDL は30列**完全一致**（欠落なし）。TEXT のまま=粒度差情報（`SC1 NEW` 等・§1b）を劣化させない |
| created_at / updated_at | v2 側 now() | local 値を保持したい場合は source 側 timestamp 列の追加検討（任意） |

49列 = 上記で全て割当先あり（漏れなし）。session_id は
`{date}_{ROUND}_{CIRCUIT}_{SESSION}_{RIDER}` を推奨（run_id から run_no を落とした形＝規則と自明整合）。

### 3.2 laps（16列）→ laps + lap_phase_metrics

- laps.lap_id/run_id/lap_no/lap_time_s/is_outlap → v2 laps（lap_time_fmt は lap_suspension から）。
- is_pit/is_cancelled は 2D 系 local に無い → false 既定（result_laps 側でのみ意味を持つ）。
- susf_mean/susf_max/susr_mean、f/r_dive/reb_spd、rear_light_brk → **lap_phase_metrics
  phase='full_lap'/'full_brake'**（§2.5）。mes_file → source_file_id 突合（不可なら value_text 退避 or 保留）。

### 3.3 lap_suspension（69列）→ lap_phase_metrics（wide→long）

- キー/重複列（lap_id,run_id,round,circuit,session,rider,run_no,lap_no,date,lap_time_s,lap_time_fmt,updated_at
  の12列）は正規化コアに吸収（変換対象外）。
- 位置・カウント系: apex/brk/fullbrk/ce の count/spd_avg/susF/susR/wf_*（21列）→
  phase={apex,braking,full_brake,exit} × channel={count, speed_kmh, sus_pos_front, sus_pos_rear,
  wheel_force_front, wheel_force_rear} × statistic={count,avg}。wf_* は subsystem='wheel_force'
  （unit='N'・Level1 バネ成分のみと notes 明記）。
- lap 統計4列（lap_susF_mean/min/max, lap_susR_mean）→ phase='full_lap',
  statistic={mean,min,max}。lap_susF_min は全NULL（本番でも NULL）→ 行を作らない。
- 速度・phase系 27列（§2.5 の表）→ 同表どおり。**22 directional 列は statistic='p95'（peak）で登録。**
- 見込み行数: 69−12=57 値列 × 1202 lap − NULL ≈ **5〜6万行**（Exit系 ~46%・brk系 ~11% が NULL で
  行なし）。Supabase 規模として問題なし。lap_phase_metrics_natkey が再sync 冪等性を保証。

### 3.4 race_results → ts24_v2.race_results

| local | v2 | 備考 |
|---|---|---|
| round+circuit+date | event_id（season 導出） | **date NULL 行に注意**（旧 remote_extra の教訓）。local 側 date は 866行で充填済み想定だが backfill 時に NULL チェックを Gate 化 |
| session_type/position/rider_num→rider_no/rider_name/nationality/team/bike/laps/race_time/gap/best_lap/best_lap_s | 同名/改名 | |
| sector1-3 | **v2 に無い** → race_results へ3列追加 or result_laps 側 seg と混同しない別扱い（追加推奨・小） |
| source_file / imported_at / data_scope | source_file_id（突合）+ 原文パスは notes / imported_at / data_scope | **data_scope='COMPANY'（BSB）混在に注意**: §32b のとおり同一 round ラベルで BSB/WorldSSP が混在。v2 でも data_scope を必ず運搬し、view の既定を要検討 |
| rider_id | team rider（77/52）のみ riders FK、他は NULL | |

### 3.5 race_lap_detail / pdf_lap_times_v2_staging → result_laps

- **供給元は VIEW `race_lap_detail`（12763行）を推奨**（v2 PASS overlay + legacy fallback が既に
  解決済みのため）。列は result_laps とほぼ1:1（seg1-4/lap_time_s/speed/local_time/is_outlap/is_pit/
  is_cancelled/extractor_version/gate_status/source_file）。
- **困難点1:** view の legacy 行（5053）は extractor_version/gate_status が NULL（出所不明の旧抽出）。
  → gate_status='LEGACY'（または NULL のまま）+ **非キー列 `source_table`（'v2_staging'/'legacy'）を
  result_laps に追加**して来歴を明示することを推奨。
- **困難点2（投入順規約）:** result_laps natkey に stage 識別が無いため、legacy と v2 が同キーで
  upsert し合う。view を源にすれば view 側で優先解決済みなので衝突しない（**生2テーブルを別々に
  sync してはいけない** — これを sync_to_supabase_v2.py の規約として固定）。
- position 列は race_results から JOIN 充填（staging に有るが legacy に無い場合は NULL 許容）。

### 3.6 registry / queue / quality / analysis log → source_files / import_batches / quality_events

| local | v2 | 備考 |
|---|---|---|
| source_file_registry（405行: file_id/file_path/file_name/file_type/file_size/file_mtime/sha256(=manifest)/rider/circuit/round/session/status/notes） | source_files | **sha256→manifest_hash に改名対応（修正提案5）**。rider/circuit/round/session → rider_id/event_id/session_type へ dim 突合（未解決は notes 退避） |
| import_queue（397行: queue_id/file_id/target_kind/priority/status/enqueued/started/finished/analysis_run_id/error/notes） | import_batches | queue_id→import_batch_id、target_kind→importer_name 相当。**data_stage/quality_status が local queue に無い** → analysis_run_log/staging 結果から補完、不明は 'staging'/'SKIPPED' 既定を定義 |
| analysis_run_log | import_batches（同上に統合）or notes | importer_name/importer_version/row_count/error が対応 |
| data_quality_log（detect_*/gate_*/stage_*） | quality_events | check_name をそのまま運搬（prefix 規約 §22 を継承）。scope/scope_id→entity_type/entity_id、result→status |
| metric_version_log（32行） | v2 に対応テーブル**無し** → **`ts24_v2.metric_versions` の追加を推奨**（lap_phase_metrics.metric_version の参照先。guard_rule/definition を online でも参照可能に） |

---

## 4. 並行運用計画（旧4テーブルと v2 の共存）

1. **現行 public 4テーブルは当面そのまま**: `sync_to_supabase.py` v3 による upsert 運用を継続
   （Streamlit dashboard が st.secrets 経由で参照中のため停止不可）。remote_extra 24行 cleanup も
   従来どおり別GO のまま。
2. **v2 は別 schema `ts24_v2` に追加構築**（public 4本に触れない — DDL の設計どおり）。
3. **sync は新規 `sync_to_supabase_v2.py` を新設**し、既存 `sync_to_supabase.py` は**一切編集しない**
   （supabase_audit.py が AUDIT_SPECS で v3 の投影を複製している依存もあるため、v3 を触ると監査も
   壊れる）。v2 側にも対になる `supabase_v2_audit.py`（read-only）を後続で用意。
   実装前に Phase B（`supabase_v2_projection.py`・JSON/CSV サンプル出力・POST なし）を挟む。
4. **切替は compatibility views で**: v2 データが audit で local と一致した後、
   `v_sync_runs` 等で旧4テーブルの列形（sessions_2d の fork/fork_comp/shock_spec 等の**合成列**:
   `f_offset||'/'||f_offset2`, `r_set_c||'/'||r_set_r` を view 内で再現）を提供 →
   dashboard の参照先を view へ変える（別GO）→ 安定後に旧4テーブル整理（別GO）。
   ※現行 `v_sync_runs` 案は raw 列出しで sessions_2d の形と一致していない。切替用には
   **`v_compat_sessions_2d` / `v_compat_lap_times_2d` / `v_compat_race_results` / `v_compat_lap_times`**
   を旧列名・合成規則込みで別途定義する必要がある（rs.* 問題の修正と併せて）。

---

## 5. Migration risk と対策

| リスク | 対策 |
|---|---|
| **provisional 混入**（PROV_ run が final として dashboard に出る） | ①sessions/runs/laps/metrics 全てに data_stage NOT NULL（DDL 済）②compatibility/dashboard view は `data_stage='final'` を**既定でハードコード** ③PROV_ prefix と data_stage の整合を quality_events でチェック（`run_id LIKE 'PROV_%' AND data_stage<>'provisional'` を FAIL）④final化時に v2 provisional 行の削除を手順化 |
| **RLS / TS24_PRIVATE** | DDL は data_scope 列のみで RLS 未設定（意図的・末尾コメントどおり）。**v2 backfill GO の前に RLS 有効化 + service key 専用ポリシーを最低限設定**（anon 読み取りは dashboard 切替設計時に view 単位で許可）。COMPANY(BSB) データの data_scope 保持を sync で必須化 |
| **backup DB / DB Master の位置づけ** | どちらも**派生物・正本ではない**（§27b/§41/§46）。v2 の源は常に `ts24_unified.db` のみ。DB Master.xlsx や backup からの backfill は禁止と sync スクリプトに明記 |
| **冪等 upsert** | 全テーブル自然キー UNIQUE + `on_conflict`（v3 と同方式）。autoincrement id を conflict キーに使わない（§1c の事故の再発防止）。lap_phase_metrics は BIGSERIAL PK だが natkey UNIQUE があるので upsert は natkey 指定 |
| **失敗時 rollback** | v2 は独立 schema のため **`DROP SCHEMA ts24_v2 CASCADE` 一発で正本・旧4テーブル・dashboard に無影響**。local 側は読み取りのみで rollback 不要。部分失敗時も旧 sync 系は独立して動き続ける |
| **date/round 正規化の偽差分** | audit 実績（§28b）のとおり `YYYYMMDD`⇄`YYYY-MM-DD` 変換を projection 層で一元化。event_id 導出（season）を sync と audit で同一関数に |
| **DDL 自体の失敗** | §2.3-1 の rs.* バグで**現状の SQL は COMMIT ごと失敗する**見込み → 実行 GO の前に改訂必須。改訂後は staging プロジェクト（または一時 schema 名）でのドライ実行を推奨 |

---

## 6. Phase B 以降のゲート分割案

| Gate | 内容 | 事前条件 |
|---|---|---|
| **G1: `Supabase v2 schema GO`（DDL 実行）** | 改訂版 DDL（§2.3 の7点反映）を ts24_v2 に実行。テーブル/インデックス/ビュー存在確認のみ・データ投入なし | §2.3 修正の反映・Phase B projection サンプル（POST なし）で列マッピング確定 |
| **G2: `Supabase v2 backfill GO`（初回 v2 sync）** | `sync_to_supabase_v2.py` で final のみ upsert → `supabase_v2_audit.py` で local と件数/自然キー一致確認 | G1 完了・RLS 最低限設定・provisional 除外の既定確認 |
| **G3: `Compatibility view 切替 GO`** | `v_compat_*` 4本が旧4テーブルと**行レベル一致**することを audit で証明 → dashboard 参照切替 | G2 完了・v2/旧4 の並行 sync 期間で差分ゼロ実績 |
| **G4: 旧テーブル整理 GO** | 旧 public 4テーブルの sync 停止 → remote_extra 24 cleanup 判断と統合 → 旧テーブル凍結/削除 | G3 後の安定運用期間・Tatsuki 最終判断 |

各 Gate 間で provisional 対応（v2 への provisional sync 可否）は独立の小 GO として分離可能。

---

## 7. Multi-agent operating check + 禁止事項遵守宣言

| エージェント役割 | 本タスクでの実施 |
|---|---|
| Architecture | v2 DDL 13テーブルを local 正本（runs49列/lap_suspension69列/staging25列/registry14列 実測 PRAGMA）と突合、BLOCKING 1件（rs.*）+ 設計6件を検出 |
| DB Integrity | 正本DB は `file:...?mode=ro` の PRAGMA/SELECT のみで参照。書込ゼロ |
| Supabase | remote アクセスなし（GET すら不実行）。sync/audit はコード読解のみ |
| Documentation | 本 readiness report 1点を新規作成 |
| Supervisor | DDL 実行・sync・cleanup・既存ファイル編集・commit を全て停止（別GO 保持） |
| Tatsuki | G1〜G4 の GO 判断待ち |

**遵守宣言:** Supabase への SQL 実行なし / `sync_to_supabase.py` 実行なし / POST・PATCH・DELETE なし /
local DB 書込なし（sqlite は read-only URI のみ）/ 既存ファイル編集なし / commit なし。
書込は本レポート `reports/supabase_v2_migration_readiness_20260707.md` の新規作成のみ。
