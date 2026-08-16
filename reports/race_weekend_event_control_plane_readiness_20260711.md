# Race Weekend Event Control Plane readiness（P0・Phase A・read-only）— 2026-07-11

- 依頼元: `08_OBSIDIAN/TS24_Engineering_Knowledge/00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-11 P0）
- 設計正本: `08_OBSIDIAN/TS24_Engineering_Knowledge/04_SYSTEM_DESIGN/2026-07-11_Race_Weekend_Event_Control_Plane.md`
- モード: **Phase A read-only readiness**（ROUND8 live 運用中）
- 実装開始ゲート: `Event control plane implementation GO`

## 0. Forbidden 遵守宣言

本 readiness で行った書込は **本レポート（.md）/ 設計専用 JSON（`reports/event_manifest_schema_proposal_20260711.json`）/ Obsidian vault の .md 更新のみ**。

- `ts24_workbench.py` / `extraction_scan.py` / `session_extract_staging.py` の runtime 変更: **なし**
- canonical / provisional / registry / queue / data_quality_log への書込・削除・migration: **なし**（DB は本フェーズで一切開いていない。数値はすべて調査エージェント3件の結果を引用）
- DB Master refresh / Supabase 操作 / commit / push: **なし**
- Round8 finalization / provisional clear / Round8-only guard の弱体化: **なし**
- live intake 自動化 / folder watcher / auto-apply: **なし**

---

## 1. 調査結果サマリ（3エージェント）

### 1a. Workflow 棚卸し（extraction_scan / session_extract_staging / ts24_workbench）

- **`extraction_scan.py`**: scan root はモジュール定数（`DATA 2D` / `01_REPORTS` / `07_RESULTS` 全域）。**event/round filter は一切なし**（scan_2d:167-174 は discover_events 全件・reports/results は rglob 全域・CLI に `--event` なし）。`PDF_SESSION_RE`:63 は round をメタ記録するのみ。queue 投入:419-432 は discovered 全件 → **歴史的 pending の発生源**。ROUND8 リテラル 0 件。
- **`session_extract_staging.py`**: filesystem 直 scan せず queue 駆動。`--event` filter:110-119・`--required-round`:643-654（§68 Layer1 `enforce_apply_guard`:634-654 は run_pipeline 前 exit 4・Layer2 `do_apply` 冒頭:484-494）。**ただし `--required-round` は default None＝CLI 単体では guard 非有効**。run_id 生成:445-446 `PROV_{date}_{round}_{circuit}_{session}_{rider}_R{n}`。ROUND8 リテラルは docstring のみ。
- **`ts24_workbench.py` ImportQualityTab**: **ROUND8 実効ハードコードは :6935 `REQUIRED_ROUND = "ROUND8"` の1箇所のみ**（毎ラウンド手動更新・全消費側は `self.REQUIRED_ROUND` 経由）。`_guess_event_key`:6937。`_run_scan`:6857 は引数なし subprocess＝全域 scan（live/maintenance 未分離）。`_run_import` guard:7683-7706 が `--event`/`--required-round` を常時付与。laps に round 列なし → run_id LIKE 照合。
- **Manifest 導入の最小手術点は3つ**: (a) extraction_scan の scan_2d イベント dict filter + reports/results round filter + CLI `--manifest`（無指定=現行フル walk=maintenance として後方互換）(b) staging `main()` の manifest→args 充填（`--session` 単一値→allowed_sessions は1行変更・`enforce_apply_guard` 無改変流用）(c) Workbench REQUIRED_ROUND / `_guess_event_key` の manifest 化（フォールバック=現行定数）。**§68/§73 防御機構は入力値の出所が変わるだけで無改変**。
- 運用負債: ① :6935 の毎ラウンド書換（唯一の必須コード変更・忘れると全ガード誤動作）② CLI 手動実行時の `--required-round` 手入力 ③ 歴史的 pending 整理 ④ `build_master_db.py`:124 `EVENT_RE` の rider 列挙 `(DA77|JA52|JA25)` ハードコード ⑤ KNOWN_SESSIONS 固定集合。

### 1b. Data-integrity（スキーマ実態とギャップ）

- スキーマ実態: `source_file_registry` 14列（status: queued 422 / incomplete 8 / gated 1・event 専用列なし＝file_path 埋込のみ・sha256 は 2d=64hex manifest / report系=`stat:` 短縮の**二形式混在**）。`import_queue` 12列（status: pending 383 / awaiting_gate 18 / skipped 14 / failed 7・**'done' は設計上あるが 0 件＝awaiting_gate から先の遷移が未実装**）。provisional 3テーブルは共通6列（data_stage / intake_ts / source_manifest_hash / source_file_path / provisional_event_key / quality_status）で event を明示保持。`data_quality_log` は severity 表記揺れ（info/INFO/warn/WARNING 混在）→ 新テーブルは CHECK 制約推奨。
- `events` テーブルは report 取込後の事後生成（ROUND8 行なし）＝ **manifest には使えない**。
- **ギャップ確定**: event 一次表現・event 粒度 state・遷移履歴（actor/when）・raw_2d_root/allowed_sessions・schema_version・event 単位 fingerprint 集約は**すべて不足 → 新テーブル `event_manifest` + `event_state_ledger` が必要**（既存列流用不可）。`provisional_event_key` は rider 含む＝「event×rider」粒度なので weekend と rider フォルダの2階層を manifest で区別要。
- ROUND8 現況: registry JA52 7件（2d 6 + report 1・全 queued）+ DA77 11件 + incomplete 1 / queue JA52 2d 6=awaiting_gate・report 1=pending・DA77 10=pending / runs_provisional 6行（PASS 5 / WARNING 1=FP_R2）・source_manifest_hash は registry.sha256 と一致=トレーサビリティ成立 / stage_* 72行。
- **イベント外走査の副作用（定量）**: queue pending 383 のうち ROUND8 は 11 のみ・**historical 372（97%）**が 26 イベントに分散。detect_duplicate が log の 87%（2304行）＝全件再走査の副作用。

### 1c. Adversarial 7シナリオ

| # | シナリオ | 判定 | 要点 |
|---|---|---|---|
| 1 | 同名同サイズ差替 | UNPROTECTED（検出） | sha256=stat `name\|size`（mtime 意図的除外）→ 内容差替は永久に再検出されない。`--deep-hash` は opt-in |
| 2 | event 外 .MES 混入 | PARTIAL | copia/loose は HED ゲート2層で BLOCKED・**nested tier は HED ゲート免除で素通り**（folder 名メタを纏い全ガード PASS）。サブフォルダ混入のみ `_preapply_gate`#6 で偶発検出 |
| 3 | コピー途中/placeholder | PARTIAL | 名前系+mtime は有効。**dataless（st_blocks==0）と mtime 古い truncated は検出不能**（truncated は stage_lap_count で概ね事後隔離） |
| 4 | 同一 outing 再取込 | PARTIAL | **★最重要: run_no がバッチ相対採番**（既存 provisional 非考慮）→ 同一 session の outing が時間差で届く通常運用で run_id 衝突 → INSERT OR REPLACE 上書き + 旧 laps 孤児化。stage_prov_id_dup は batch 内のみ FAIL・既存衝突は PASS。Workbench 経由なら `_post_apply_check` の delta 不一致で事後検出・CLI は無検出 |
| 5 | historical pending | Workbench=BLOCKED / **CLI=PARTIAL** | `--required-round` default None → CLI で `--event <過去event> --apply` が素通り。Safety Audit も provisional rounds ⊆ active round 未検査 |
| 6 | canonical 混入 | BLOCKED-事前 | in-txn count assert（commit 前 rollback）+ 事後 `_post_apply_check`。残穴: assert は **COUNT のみ**（UPDATE/ALTER 検出不能）・**DDL ファイル無検証 executescript**（改竄で任意 SQL） |
| 7 | apply 途中中断 | BLOCKED | 単一トランザクションで不整合ウィンドウなし・冪等再実行可。残穴: **backup が WAL sidecar 非対応**（session_extract_staging:499-501 / extraction_scan:364-370。apply_round7_targeted_insert は §65 で対応済）・analysis_run_log 'running' 残骸 |

**fail-closed 追加要求（優先順）**:

- **P0-1**: active_event を DB 内 Ledger の単一正本にし、CLI もフラグ有無に関係なく強制（REQUIRED_ROUND 二重保守廃止）。
- **P0-2**: run_no を manifest 宣言 outing 集合からの決定論採番 + 既存 run_id 衝突×hash 不一致=FAIL + REPLACE 時旧 lap 全削除。
- P1-3: nested 含む全 tier の HED メタ照合（live intake は FAIL・歴史 rebuild と分離）+ 期待 outing 集合宣言。
- P1-4: apply 時 content sha256 を Ledger 記録・再取込不一致=FAIL。
- P1-5: DDL sha256 ピン留め + assert の content-digest 化。
- P2-6: dataless 検出（st_blocks）+ `--min-age 0` の apply 経路禁止。
- P2-7: 歴史 pending 一括 superseded + Safety Audit に provisional⊆active 検査。

**rollback 要求**: WAL-safe backup 統一・REPLACE pre-image 保存・apply 状態機械（started/committed）で中断残骸検出。

### 1d. Supervisor 矛盾検証

3報告は相互整合（CLI opt-in 穴を Workflow/Adversarial が独立同定・event×rider 粒度を Workflow/Data-integrity が一致確認）。補正1点: §62 の「historical 160 outing」は現在 372 件（pending 383 の 97%）に増加＝その後の全域 Scan の副作用で両数値とも各時点で正。run_no 衝突（シナリオ4）は**通常運用で発火し得る**ため設計 P0 とする。

---

## 2. Event Manifest 最小 schema（設計のみ・ファイル作成/配線はまだしない）

保存形態: 人（Tatsuki）が作成・承認する JSON（例 `02_DATABASE/event_manifests/<event_key>.json`）+ 強制用 DB ミラー `event_manifest` テーブル（Phase B で新設・**追加のみ**）。JSON Schema と ROUND8 実例は `reports/event_manifest_schema_proposal_20260711.json`（UNEXECUTED DESIGN PROPOSAL）。

### 必須フィールド

| フィールド | 型 | 内容 |
|---|---|---|
| `event_key` | string | `YYYYMMDD-ROUNDx-RIDER`（rider フォルダ粒度）。weekend 粒度は `weekend_key`=`YYYYMMDD-ROUNDx` を派生保持 |
| `date` | string (ISO) | イベント初日 |
| `round` | string | `ROUNDx` |
| `circuit` | string | canonical 名。**TRACK_M キーと一致必須** |
| `riders` | array | 例 `["JA52"]` |
| `raw_2d_root` | string | 相対パス（live scan の唯一の走査対象） |
| `allowed_sessions` | array | 例 `["FP","QP","WUP1","WUP2","RACE1","RACE2"]` |
| `status` | string | `draft → approved → active → locked → closed`（CHECK 制約・**active は同時に1件のみ**） |
| `schema_version` | integer | manifest schema の版 |

### 運用フィールド

| フィールド | 内容 |
|---|---|
| `manifest_version` | 内容変更で increment。書換え拒否ルール=「**locked 後は新 version のみ**」 |
| `content_hash` | canonical JSON の sha256。**初回 provisional apply の receipt に保存し、以後の書換えを検出**（改竄=FAIL） |
| `approved_by` / `approved_at` | operator 承認（Tatsuki） |
| `activated_at` | active 化時刻 |
| `fingerprint_policy` | `stat` \| `content`（シナリオ1対応の tier 明示。live intake は content 推奨） |
| `expected_outings` | 任意。宣言時は集合外を gated（シナリオ2 / P1-3 対応） |

### ROUND8 具体例

```json
{
  "schema_version": 1,
  "manifest_version": 1,
  "event_key": "20260710-ROUND8-JA52",
  "weekend_key": "20260710-ROUND8",
  "date": "2026-07-10",
  "round": "ROUND8",
  "circuit": "DONINGTON",
  "riders": ["JA52"],
  "raw_2d_root": "DATA 2D/20260710-ROUND8-JA52",
  "allowed_sessions": ["FP", "QP", "WUP1", "WUP2", "RACE1", "RACE2"],
  "status": "active",
  "fingerprint_policy": "content",
  "expected_outings": null,
  "content_hash": "<sha256 of canonical JSON (computed at approval)>",
  "approved_by": "tatsuki",
  "approved_at": "2026-07-11T00:00:00+01:00",
  "activated_at": "2026-07-11T00:00:00+01:00"
}
```

---

## 3. Event-scoped Scan 設計

- **live scan** = `--manifest <path>` 指定時: scan_2d は manifest.raw_2d_root（=当該 event dict）のみ・reports/results は round 一致のみ（または live では skip）。queue 投入も scope 内のみ → **歴史的 pending の発生源を遮断**（現状 pending 383 の 97% が historical という副作用の再発防止）。
- **maintenance scan** = 引数なし現行動作を明示的名称で分離。Workbench の live ボタンは `--manifest` 付与・maintenance は別導線/CLI のみ。
- **受入条件（一意一致）**: disk（raw_2d_root 直下 *.MES）/ registry / queue / dry-run 候補が **(event_key, outing_stem, fingerprint)** で 1:1 対応。不一致（missing / extra / hash 差）は fail-closed + 理由表示。
- **移行順（既存防御を弱めない）**: Phase B では manifest は**追加入力**であり §68 guard・§69/§72 zero-candidate 診断・§73 Safety Audit は**無改変で併存** → 複数セッション実証後（Phase C）に manifest を唯一の許可源へ切替。REQUIRED_ROUND 定数はフォールバックとして残置。

---

## 4. Event State Ledger 設計

- 新テーブル `event_state_ledger`（**追記型・UPDATE しない**）: `entry_id` PK / `event_key` / `scope`（event\|session\|outing）/ `scope_id` / `state` / `prev_state` / `reason` / `actor`（tatsuki\|claude_code\|codex\|script名）/ `analysis_run_id` / `receipt_json` / `created_at`。state は **CHECK 制約**（data_quality_log の severity 表記揺れの教訓）。
- **状態機械**: `discovered → registered → candidate_ready → staged → verified → reportable → finalized` + 分岐 `failed / warning_accepted / skipped / superseded / quarantined`（**理由必須**）。
- **Apply receipt**（receipt_json に保存）: manifest content_hash + version / expected delta / actual delta / post-apply invariants 結果 / operator 決定（Apply クリック・複数 session 確認）/ backup path / dry-run・apply ログ path。apply 状態機械（`apply_started → apply_committed`）で中断残骸を起動時検出（シナリオ7）。
- **境界**: `reportable` まで = provisional（race weekend 内）。`finalized` は**別 GO**（§65 型 targeted-insert）。DB Master / Supabase / origin push は**さらに独立 GO**（現行どおり）。

---

## 5. Phase B 最小実装計画（GO 後・小分割）

- **B-1（最初・最小）**: `create_quality_tables.py` 方式で `event_manifest` / `event_state_ledger` 2テーブル新設（追加のみ・冪等・CHECK 制約）+ ROUND8 manifest JSON 作成・承認 + Workbench 🏁 Status タブに manifest 内容の **read-only 表示**のみ。**scan/staging の挙動変更ゼロ**。
- **B-2**: extraction_scan `--manifest`（live scoped scan）+ maintenance 分離。フォールバック=現行。
- **B-3**: staging/Workbench が manifest を読む（REQUIRED_ROUND は残置・二重検証）+ **P0-2 run_no 決定論採番 + 既存 run_id 衝突 FAIL**（最優先 runtime 修正）+ CLI active-event 強制（P0-1）+ WAL-safe backup 統一。
- 各 B-x で明示するもの: 変更対象ファイル / DB migration（**2テーブル追加のみ・既存 ALTER なし**）/ 後方互換（manifest 不在=現行動作）/ テストケース（offscreen + CLI ガード行列 + DB 不変）/ GUI 確認項目（Tatsuki）/ 切戻し（テーブル DROP / manifest ファイル削除 / コード revert。**guard 無改変なので安全**）。
- **実装開始の明示 GO 文言**:

```text
Event control plane implementation GO
```

ROUND8 稼働中は Phase A のみ＝本 readiness で停止する。
