# Race Weekend Event Control Plane — Track B 実装 apply レポート（B-1/B-2/B-3）— 2026-07-13

- 指示書: `reports/round8_final_integration_code_instruction_20260713.md`（"Parallel Track B"）
- 設計正本: `reports/race_weekend_event_control_plane_readiness_20260711.md` /
  `reports/event_manifest_schema_proposal_20260711.json` / CLAUDE.md §75（§68/§73 併存）
- 実装者: Claude Code（Track B agent）。Track A（ROUND8 canonical apply）と並行・完全分離で実施。

## 0. 隔離ルール遵守宣言

- **正本DB `02_DATABASE/ts24_unified.db` への書込: ゼロ**。全DBテストは `/tmp` の scratch コピー
  （pre-Track-A スナップショット + post-Track-A コピー）に対して実施。
  - suite 実行前後の正本 sha256: `977baad8c4e9b02f7471977b307a135c60d221ba4ef0389b1b8fe1a1ed47088d`
    → **同一**（adversarial suite 全26テスト実行を通して byte 不変。suite 内 T00 で自動検証）。
  - 注: suite 完了**後**の 2026-07-13 07:56 に正本が並行 Track A/supervisor 作業で更新されている
    （現 sha256 `390372e3…`）。正本に `event_manifest`/`event_state_ledger` テーブルは存在せず、
    analysis_run_log にも Track B 由来の行は無いことを read-only で確認 = Track B の書込ゼロは不変。
- **`DATA 2D/` 無改変**（読取のみ。fixture は `/tmp/ts24_trackb_fixtures/` に複製して構築）。
- **`ts24_workbench.py` 無改変**（UI 配線は §7 の ready-to-apply 仕様書として納品）。
- `extraction_scan.py` / `session_extract_staging.py` の変更は**後方互換**（§5 回帰試験で証明）。
  編集前バックアップ: scratchpad `backup/extraction_scan.py.pre_trackb`（sha256 `34ac1ea5…`）/
  `backup/session_extract_staging.py.pre_trackb`（sha256 `608ed8a6…`）。
- Supabase / DB Master xlsx / git commit·push / 歴史的 queue cleanup / canonical 業務テーブル: 非接触。

## 1. 実装サマリ（フェーズ別）

### B-1 — Event Manifest + State Ledger（新規ファイルのみ・既存 ALTER なし）

| 成果物 | 内容 |
|---|---|
| `05_SCRIPTS/create_event_control_tables.py` | `event_manifest` + `event_state_ledger` を **追加のみ**で作成（create_quality_tables.py 方式・CREATE TABLE IF NOT EXISTS・冪等・WAL-safe backup）。status CHECK(draft/approved/active/locked/closed)。**active は同時1件のみ**を partial UNIQUE index `ux_event_manifest_single_active` で DB レベル強制。ledger は state CHECK（discovered/registered/candidate_ready/staged/verified/reportable/finalized/failed/warning_accepted/skipped/superseded/quarantined）+ **UPDATE/DELETE 拒否トリガ**（追記型を DB で強制）。 |
| `05_SCRIPTS/event_manifest.py` | manifest ライブラリ + CLI（validate/seal/register/activate/show-active）。canonical JSON → content_hash（sha256）計算・改竄検出（JSON・DBミラー行・**列レベル**の三層）。register は immutable version（同 version 異内容=拒否・書換えは新 version のみ）。`status='active'` の直接登録は不可（activate の明示操作のみ）。`get_active_manifest()` は 0件/複数件/改竄で ManifestError（fail-closed）。`ledger_append_durable()` = 短命コネクション即 commit の耐久 receipt。業務テーブル非接触。 |
| `02_DATABASE/event_manifests/20260710-ROUND8-JA52.json` | ROUND8 実 manifest（status=approved・sealed content_hash `ed3e3b1c…`）。expected_outings = 実在 8 outing stem。**本フェーズでは正本DBへ register/activate していない**（activation は scratch のみ）。 |
| `02_DATABASE/event_manifests/20260710-ROUND8-DA77.json` | 同上 DA77（sealed `387b57b7…`）。expected_outings は正規 10 stem のみ宣言 = 重複 `SP-77-03` と未知 `SX_*` は live scan で **gated**（Round8 で実際に起きた事故の再発防止をデータで宣言）。 |
| `02_DATABASE/event_manifests/TEMPLATE_ROUND9.json` | ROUND9 テンプレート（placeholder + status=draft + content_hash null → **そのままでは validation 不合格 = 誤 activate 不能**）。手順は `_howto` と round9_readiness_acceptance_20260713.md のチェックリスト。 |

補足（設計判断）: 2ライダー同時 weekend と「active は1件のみ」の関係は
**「rider event 単位の manifest を、取込対象を切り替えるときに activate し直す」運用**とした
（§8 open item 参照。schema v2 で weekend 単位 multi-root を検討可能）。

### B-2 — Event-scoped scan（`extraction_scan.py` — 後方互換変更）

- 新 CLI `--manifest <path>`（**無指定 = 従来の全域 scan = maintenance mode**。help/docstring に明記）。
- `--manifest` 指定時（live scan・validation 不合格は **exit 5・無書込**）:
  - scan_2d は manifest.event_key の 1 イベントのみ走査（event-external ソースは構造的に対象外）。
  - `allowed_sessions` 外 session / `expected_outings` 外 stem → **gated**（queue 非投入）。
    check 名: `detect_session_not_allowed` / `detect_outing_not_expected`（FAIL/critical）。
  - `fingerprint_policy='content'` → outing 全ファイル**全バイト** sha256（`manifest_hash(deep_all=True)`
    新規パス）。同名同サイズ差替（adversarial シナリオ1）を live event で完全検出。
  - reports/results は round 一致（reports は rider 一致も）だけ registry/queue 対象。
  - queue 投入は event 内のみ。upsert の全域 self-heal UPDATE は live モードでは skip
    （event 外 registry 行への副作用ゼロ）。
  - `event_state_ledger` が存在すれば受入 receipt を追記: event scope `registered`
    （identities = **(event_key, outing_stem, fingerprint)** の列挙）+ gated/incomplete は
    outing scope `quarantined`。テーブル無し = 従来動作（後方互換）。
  - analysis_run_log の run_scope = event_key / params に manifest path + content_hash。

### B-3 — Fail-closed import/apply（`session_extract_staging.py` — 後方互換変更）

1. **P0-1: active event + required round を apply の必須条件に**。
   - `resolve_manifest_context()`: 対象DBの active manifest を read-only 解決
     （テーブル無し/active 0件 → None = 従来動作）。
   - `enforce_apply_guard()` 拡張: --apply で --required-round 省略時は active manifest の round を
     自動採用。**どちらも無ければ exit 4（CLI 穴の閉鎖）**。active manifest があるときは
     `--event == manifest.event_key` 必須（event-external/historical apply 拒否）+
     `--session ∈ allowed_sessions`。active 複数/改竄 = ctx.error → 明示フラグがあっても exit 4。
   - manifest 未導入DB + 明示フラグ（従来運用）は不変。
2. **P0-2: 決定論 run identity**（active manifest 存在 or `--deterministic-runid` で有効。それ以外は
   従来のバッチ相対採番 = byte 同一）。
   - run_no = **outing stem 末尾連番**（`FP-JA52-02` → R2）。バッチ相対採番を廃止 → 時間差取込でも
     run_id 不変。連番なし stem / session 内連番衝突 = `stage_run_identity` FAIL（抽出前に隔離）。
   - 事前衝突検査: (a) canonical `runs` に PROV_ 除去 run_id が既存 → `stage_canonical_conflict`
     FAIL（finalized イベントへの再取込禁止）。(b) 既存 provisional と同 run_id →
     同 hash + 同 stem = **冪等 no-op**（disposition=noop・行を書かない）/ それ以外 =
     `stage_run_id_conflict` FAIL（**silent overwrite 禁止**・書込ゼロ）。
   - manifest あり時は `stage_session_allowed` も gate 検査。
3. **WAL-safe backup + 耐久 receipt**。
   - apply 前 backup が db + `-wal` + `-shm` sidecar を含むよう修正（readiness シナリオ7 残穴の閉鎖）。
   - `event_state_ledger` が存在すれば（無ければ従来動作）:
     backup 後・書込前に `candidate_ready/apply_started`（expected delta + 候補 identity + backup path、
     **別トランザクションで即 commit** = 中断時に残る）→ commit 後 `staged/apply_committed`
     （actual delta + invariant 結果）→ 失敗時 `failed`（rollback 後も残る耐久 receipt）。
     `apply_started` に対応する `apply_committed` が無い = 中断残骸として起動時検出可能。

## 2. ファイル別差分サマリ

| ファイル | 変更 | 後方互換性 |
|---|---|---|
| `create_event_control_tables.py` | **新規**（sha256 `112296bf…`） | 追加のみ・実行は明示 --db |
| `event_manifest.py` | **新規**（sha256 `5e92ee4c…`） | ライブラリ/CLI・既存コード非接触 |
| `02_DATABASE/event_manifests/*.json` | **新規 3 ファイル**（ROUND8×2 sealed + ROUND9 template） | データファイルのみ・未配線DB無し |
| `extraction_scan.py` | `--manifest` 追加 / `manifest_hash(deep_all)` / `scan_2d(manifest=)` gate / `upsert(self_heal=)` / ledger receipt / docstring・help（pre `34ac1ea5…` → post `e53800ca…`） | **無指定時 byte 同一**（§5-1） |
| `session_extract_staging.py` | `resolve_manifest_context` / `enforce_apply_guard(ctx)` / 決定論採番 + 衝突検査 / noop / WAL-safe backup / ledger receipt / `--deterministic-runid`（pre `608ed8a6…` → post `432030a5…`） | **manifest 無し dry-run は出力同一**（§5-2）。唯一の意図的挙動変更 = `--apply` で required round 解決不能なら exit 4（P0 穴の閉鎖・指示書どおり） |
| `ts24_workbench.py` | **無変更** | — |

py_compile: 4 ファイルすべて合格（各編集後に実施）。

## 3. Adversarial テスト結果（必須スイート・26/26 PASS）

- ハーネス: scratchpad `trackb_adversarial_suite.py` / 結果 JSON: `/tmp/ts24_trackb_work/results.json`
- fixture: `/tmp/ts24_trackb_fixtures/`（実 outing の複製を rename した合成 event 木 + sealed fixture
  manifest + 意図的改竄 manifest）。scratch DB: pre-Track-A スナップショット（live weekend 状態:
  provisional 15/137/137・canonical ROUND8=0）+ post-Track-A 現正本コピー（T26）。

| # | ケース（指示書の要求） | 期待 | 結果 |
|---|---|---|---|
| T18/T19 | zero / multiple active manifests | apply 拒否 exit 4（multiple は明示フラグでも拒否） | ✅ PASS |
| T03 | 2件目 activate（API + 直接 SQL） | ManifestError + partial unique index IntegrityError | ✅ PASS |
| T04/T05 | tampered manifest hash / 同 version 異内容 | load 拒否・scan exit 5 無書込 / register 拒否 | ✅ PASS |
| T20 | DB ミラー列改竄（round 書換） | apply exit 4（列 vs hashed raw_json 突合） | ✅ PASS |
| T17 | event-external + historical pending への apply | active manifest と不一致 → exit 4 | ✅ PASS |
| T16 | 直接 CLI apply（event 無し / round 解決不能） | exit 4 / exit 4。明示フラグの従来運用は通過 | ✅ PASS |
| T12 | 同一 outing の再取込 | 冪等 no-op（行数不変・exit 0） | ✅ PASS |
| T14 | 同名パス・内容変更 | scan が hash 変化検出（detect_updated）+ 再取込は `stage_run_id_conflict` FAIL・無書込・既存行不変 | ✅ PASS |
| T10/T11 | 従来なら同一 run ID になる2バッチ | stem 決定論採番で R1/R2 に分離・laps 孤児化なし。--required-round は manifest から解決 | ✅ PASS |
| T13 | 同 run_id・別ソース stem | 明示 conflict FAIL・無書込 | ✅ PASS |
| T07 | コピー途中/変化中フォルダ（+ .LAP 欠落） | incomplete 保留・queue 非投入 | ✅ PASS |
| T06/T08 | 未知 session（XX）/ expected_outings 外 | gated・queue 非投入・ledger quarantined | ✅ PASS |
| T15 | 有効ラップ 0 outing（GRID） | gate FAIL 隔離・queue failed・行ゼロ | ✅ PASS |
| T21 | backup 前クラッシュ（copy2 例外注入） | DB byte 不変・receipt ゼロ | ✅ PASS |
| T22 | トランザクション中クラッシュ（build_rows 例外注入） | rollback（行数不変）+ 耐久 failed receipt | ✅ PASS |
| T23 | commit 後 receipt 前クラッシュ（receipt 抑止注入） | データは commit 済・orphan `apply_started` が検出可能 | ✅ PASS |
| T24 | Result PDF あり・2D 無し（Race2 実ケース） | PDF は pdf_extract queue（公式経路）・telemetry 候補/行 = 0・捏造なし | ✅ PASS |
| T25 | live scan の副作用 | event 外 registry/queue 完全不変（self-heal skip 含む） | ✅ PASS |
| T26 | canonical/provisional 重複（**post-Track-A 正本コピー**・ROUND8 finalized 16 runs） | `stage_canonical_conflict` FAIL・無書込 | ✅ PASS |
| T01/T02 | 冪等 DDL / ledger 追記型強制 | 再実行無害 / UPDATE・DELETE 拒否 | ✅ PASS |
| T00 | **正本DB sha256 不変（suite 全体）** | `977baad8…` == `977baad8…` | ✅ PASS |

## 4. 受入条件（Track B acceptance）対照

- live モードで global scan 副作用なし → T25 ✅
- unscoped CLI apply 経路なし → T16/T17/T18 ✅（P0-1 閉鎖）
- silent overwrite / 曖昧 run identity なし → T10–T14, T26 ✅（P0-2 閉鎖）
- 全遷移が source hash + manifest + receipt に帰属 → ledger receipt（scan/apply/failed）✅
- 正本DBは suite で byte 不変 → T00 ✅
- 既存 Workbench/provisional/Report v2 の回帰 → §5（コード無変更 + CLI 回帰）✅

## 5. 後方互換 回帰試験

1. **argless `extraction_scan.py --dry-run --min-age 0`**: 変更前後の stdout **byte-identical**
   （diff 完全一致。実 DATA 2D 全域 read-only scan・DB 非接触）。
2. **`session_extract_staging.py` dry-run（現行運用形）**: `--event 20260710-ROUND8-JA52
   --include-awaiting` を pre-Track-A scratch コピーに対して変更前/変更後で実行。
   stdout 同一（report パス指定分のみ）・report .md は timestamp/analysis_run_id/db パス正規化後
   **完全一致**（run_no 採番・gate 判定・件数すべて不変）。
3. manifest 未導入 DB（= 現正本）ではコードパスが従来と同一分岐（`resolve_manifest_context` は
   read-only 1 query のみ追加・出力無し）。

## 6. ロールバック手順

Track B は正本DB無変更のため、ロールバック = コード/ファイルの復元のみ:

1. `cp <scratchpad>/backup/extraction_scan.py.pre_trackb 05_SCRIPTS/extraction_scan.py`
   （sha256 `34ac1ea502984ac7c31d2d55d8fd07ff515dca2ade61f2cd9ab8a334f50f8d4` 相当に復帰）
2. `cp <scratchpad>/backup/session_extract_staging.py.pre_trackb 05_SCRIPTS/session_extract_staging.py`
3. `rm 05_SCRIPTS/create_event_control_tables.py 05_SCRIPTS/event_manifest.py`
4. `rm -r 02_DATABASE/event_manifests/`
5. （将来 scratch 以外に tables を作成した場合のみ）`DROP TABLE event_manifest; DROP TABLE
   event_state_ledger;` + トリガ/インデックスは同時に消える。§68/§73 ガードは無改変なので安全。

scratchpad backup が消えている場合は git 履歴/Time Machine 相当から復元（本フェーズでは commit
していないため、正本コードのバックアップは scratchpad コピーが一次）。

## 7. Workbench UI 配線仕様（ready-to-apply・Track A 完了後に supervisor が適用）

対象: `05_SCRIPTS/ts24_workbench.py` の `ImportQualityTab`（:7108〜）。**全て追加/置換のみ・
§68/§73 ガードは残置（多層防御）**。

1. **REQUIRED_ROUND の manifest 化**（:7301 `REQUIRED_ROUND = "ROUND8"`）
   - 追加メソッド（class 内・:7302 直後）:
     ```python
     def _active_manifest(self):
         """対象DBの active event manifest（無ければ None・read-only）。"""
         try:
             import importlib.util, sqlite3
             spec = importlib.util.spec_from_file_location(
                 "event_manifest", SCRIPT_DIR / "event_manifest.py")
             evm = importlib.util.module_from_spec(spec); spec.loader.exec_module(evm)
             conn = sqlite3.connect(f"file:{self._db.path}?mode=ro", uri=True)
             try:
                 return evm.get_active_manifest_or_none(conn)
             finally:
                 conn.close()
         except Exception:
             return None   # fail-closed 側は required_round() の定数フォールバック

     def required_round(self) -> str:
         m = self._active_manifest()
         return m["round"] if m else self.REQUIRED_ROUND
     ```
   - 既存の全 `self.REQUIRED_ROUND` 参照（:7443, :7553, :7591, :7675, :7678, :7696, :7701, :7780 ほか
     grep で `REQUIRED_ROUND` 全件）を `self.required_round()` に置換。定数はフォールバックとして残置。
   - `_guess_event_key`（:7303）: active manifest があれば `m["event_key"]` を返す分岐を先頭に追加
     （フォールバック = 現行の DATA 2D 推測）。
2. **Live / Maintenance scan の分離**（:7208 `_run_scan`）
   - 既存ボタン `🔍 Session Scan`（:7124）のラベルを `🔍 Live Event Scan` に変更し、
     `_run_scan(live=True)` 化: active manifest があり `source_json_path` が存在すれば
     コマンドを `[sys.executable, str(script), "--manifest", m["source_json_path"]]` に変更
     （:7224-7228 の subprocess 引数）。manifest 不在時は明示ダイアログ
     「active manifest がありません — Historical Maintenance Scan を使うか manifest を activate」
     で**拒否**（fail-closed。従来の全域 scan に暗黙フォールバックしない）。
   - 新ボタン `🗄 Historical Maintenance Scan`（:7130 の import ボタンの後に追加）: 従来の引数なし
     実行（確認ダイアログ付き・「全域 scan・歴史 pending を再検出します」）。
3. **🏁 Race Weekend Status タブ拡張**（:7159-7178 / 再計算 :7674 `_refresh_status` 系）
   - 表示追加（read-only SELECT のみ）: active manifest の event_key / manifest_version /
     content_hash（先頭12桁）/ status / allowed_sessions、event_state_ledger の最新10行
     （state・reason・created_at）、直近の `apply_started`/`apply_committed` 突合
     （orphan apply_started があれば ⚠ 中断残骸表示）、queue counts の event scope 版
     （`file_path LIKE '%'||event_key||'%'`）。
   - Race2 らしく「2D 無し + Result PDF あり」の session は `telemetry pending` と表示
     （既存 Status 計算 `_build_status` :7586 に per-session 判定を追加）。
4. **Import dialog**（:7300 以降 `_run_import` 系）
   - 既存どおり `--event <key> --required-round <round>` を常時付与（値の出所だけ
     `self.required_round()` / `_guess_event_key()` = manifest 化）。
   - dry-run 確認ダイアログに candidates の (outing stem, fingerprint 先頭12, run_id,
     predicted laps) と stop reasons（`stage_run_identity` / `stage_run_id_conflict` /
     `stage_canonical_conflict` / `stage_session_allowed`）を staging report .md から表示。
     Apply は既存の明示確認・default Cancel を維持。
5. **Safety Audit**（:7859）: 検査に「active manifest 存在 + provisional rounds ⊆ active round +
   orphan apply_started = 0」を追加（SELECT のみ）。

前提: 本タブから使う DB パス属性（`self._db.path` 相当）は既存 WorkbenchDB の実装名に合わせること。
適用後の受入: Live ボタンが manifest 無しで拒否すること / Import が --required-round を
manifest から得ること / Status タブに manifest hash と ledger が出ること（オフスクリーン smoke +
Tatsuki GUI 確認）。

## 8. Open items（supervisor 向け）

1. **Workbench 配線**（§7）は未適用 — Track A 安定後に適用し、オフスクリーン smoke + GUI 確認。
2. **正本DBへの `create_event_control_tables.py` 実行 + ROUND8/ROUND9 manifest の register/activate は
   別 GO**（本フェーズでは scratch のみ。実行コマンドは §B-1 成果物と round9 レポート参照）。
3. 2ライダー weekend と exactly-one-active の運用（rider 切替 activate）は schema v2 検討事項。
4. `analysis_run_log.analysis_run_id` が秒解像度のため、同一秒内の scan 2回で PK 衝突する
   **既存**問題を確認（Track B 起因ではない）。低優先の別修正候補。
5. 決定論採番は stem 末尾連番規約（`*-NN`）に依存。連番なし stem は fail-closed（FAIL）になる仕様。
6. deliverable: `reports/round9_readiness_acceptance_20260713.md`（テンプレート + activation
   checklist + 受入判定）も併せて参照。

## 8. Production wiring 実施記録（Track B 最終接続・2026-07-13）

Track A（ROUND8 finalization §78）完了 + rollback point + 全 acceptance PASS（26/26 adversarial suite）を
確認済みの承認条件（00_INBOX/FOR_CLAUDE_CODE.md 2026-07-13 item 8）に基づき、**本番接続を実施**。

### 8.1 実施内容（時系列）

1. **恒久バックアップ**: `05_SCRIPTS/_backup_trackb_wiring_20260713_080110/`
   - `ts24_workbench.py.pre_wiring`（sha256 `82e62f82…4ef035`）
   - `extraction_scan.py.pre_trackb`（`34ac1ea5…`）/ `session_extract_staging.py.pre_trackb`（`608ed8a6…`）
     / `pre_hashes.txt`（scratchpad から恒久化）
2. **管理2テーブルを正本DBへ作成（B-1・管理テーブルのみ）**:
   WAL-safe backup `02_DATABASE/_backup_event_control_20260713_082939/`（db + -wal + -shm）→
   `python3 05_SCRIPTS/create_event_control_tables.py` exit 0。
   `event_manifest`（21列）+ `event_state_ledger`（13列）+ append-only トリガ2 +
   `ux_event_manifest_single_active` 作成を検証。**業務テーブル不変 assert 合格**
   （runs 302 / laps 1423 / lap_suspension 1423 / race_results 940 / pdf_lap_times 7613 /
   pdf_lap_times_v2_staging 8824）。
3. **ROUND8 manifest 2件を register → closed（TERMINAL）**:
   `20260710-ROUND8-JA52` v1（hash `ed3e3b1c…`）/ `20260710-ROUND8-DA77` v1（`387b57b7…`）を
   `register_manifest`（status=approved）→ `set_manifest_status('closed')`（forward-only 遷移）。
   ledger 4行（registered ×2 + closed 遷移 ×2・監査記録）。**activate は実施せず — active manifests = 0**
   （`get_active_manifest_or_none()` → None = 全 manifest-aware コードパスが後方互換フォールバック）。
   ROUND9 activation は `round9_readiness_acceptance_20260713.md` §2 checklist（別GO）。
4. **Workbench 配線（§7 仕様どおり・`ts24_workbench.py` のみ変更）**:
   - `ImportQualityTab._active_manifest()` / `required_round()` 新設（read-only URI 接続・例外=None=定数
     フォールバック）。`REQUIRED_ROUND = "ROUND8"` はフォールバック定数として残置。
     全 `self.REQUIRED_ROUND` 値参照（12箇所）を `self.required_round()` へ置換。
   - `_guess_event_key`: active manifest があれば `m["event_key"]` を返す分岐を先頭に追加。
   - **Live / Maintenance scan 分離**: `🔍 Session Scan` → `🔍 Live Event Scan`
     （`_run_scan(live=True)`・active manifest の `source_json_path` を `--manifest` で渡す。
     **manifest 不在は fail-closed 拒否ダイアログ・全域 scan へ暗黙フォールバックしない**）。
     新ボタン `🗄 Historical Maintenance Scan`（従来の引数なし全域 scan・確認ダイアログ既定 Cancel）。
   - **🏁 Status タブ拡張**: 先頭に Event Control Plane ブロック = active manifest
     （event_key / version / status / hash 先頭12 / allowed_sessions・不在時は明示の
     "no active manifest" 表示）+ registered_manifests + ledger 最新10行 + last_receipt +
     apply_started/apply_committed 突合（orphan → ⚠ 中断残骸）+ queue counts event scope 版。
     per-session `telemetry_pending` 判定（race_results に session あり・2D disk/provisional/canonical
     いずれにも無し → 表示。ROUND8 では RACE2 のみが正しく表示されることを確認）。
   - **Import dialog**: dry-run に `--report` を付与し staging report .md から
     candidates（outing stem / registry fingerprint 先頭12 / run_id / predicted laps）と
     stop reasons（`stage_run_identity`/`stage_run_id_conflict`/`stage_canonical_conflict`/
     `stage_session_allowed` 等の checks 列）を確認ダイアログに表示
     （`_parse_staging_report`/`_registry_fingerprint`/`_candidate_report_text` 新設）。
     既存の明示確認・既定 Cancel・複数 session 既定 No は不変。
   - **Safety Audit**: §4b「Event Control Plane」節 + summary 3行を追加 =
     active manifest 状態（不在時は INFO・fallback 明示）/ provisional rounds ⊆ active round /
     orphan apply_started = 0（すべて SELECT のみ）。
   - **§68/§73 ガード・§77 Run Filter は無改変**（値の出所が manifest 化されただけ。
     `--event`/`--required-round` の script 側二層ガードは多層防御として残置）。
   - post-wiring sha256: `ts24_workbench.py` = `edbd5c96…e09821`。

### 8.2 検証結果

- `py_compile`: ts24_workbench.py / extraction_scan.py / session_extract_staging.py / event_manifest.py 全PASS。
- **offscreen smoke（QT_QPA_PLATFORM=offscreen・28/28 PASS）**:
  7タブ構築 / ImportQualityTab inner 4タブ（先頭=🏁）/ Status タブに "no active manifest" +
  registered closed ×2 + ledger + orphan=0 + `telemetry_pending: RACE2` 表示 /
  Live Event Scan = manifest 不在で **subprocess 未起動のまま fail-closed 拒否** /
  Maintenance Scan = 確認ダイアログ既定 Cancel で未実行 /
  Suspension/Posture = DONINGTON final 16 runs・PROV 0・§77 Run Filter（リスト16件・既定全選択
  139行・空選択→0行）無回帰 / Race Analysis = `RACE_LAP_SRC=race_lap_detail`・ROUND8 v2 1114行 /
  `_parse_staging_report` が実 report .md をパース。実 scan/apply は本番に対して未実行。
- **scratch activation テスト（正本コピーのみ・PASS）**: scratchpad の scratch DB に合成
  `20260719-ROUND9-JA52`（MOST）manifest を register → activate →
  `required_round()`=ROUND9 / `_guess_event_key()`=event_key / Live Event Scan が
  `--manifest <json>` コマンドを構築 / Status タブに active manifest 表示。正本DBは 0 active のまま。
- **正本DB 不変 assert（backup vs 現DB・full-row sha256）**: 業務6 + provisional 3 + 管理7
  （registry/queue/quality/analysis_run_log/metric_version_log/problem_log/setup_decision_log）
  計16テーブル **全て byte 一致**。追加は `event_manifest`（2行）+ `event_state_ledger`（4行）のみ。
  active manifests = 0。

### 8.3 Rollback

1. Workbench: `cp 05_SCRIPTS/_backup_trackb_wiring_20260713_080110/ts24_workbench.py.pre_wiring
   05_SCRIPTS/ts24_workbench.py`（sha256 `82e62f82…` に復帰）。
2. 管理テーブル: `02_DATABASE/_backup_event_control_20260713_082939/` から DB 復元、または
   `DROP TABLE event_manifest; DROP TABLE event_state_ledger;`（トリガ/インデックス同時消滅・
   業務テーブル無影響。§68/§73 ガードは script 側に残るため安全）。
3. （必要なら）`extraction_scan.py`/`session_extract_staging.py` は同バックアップ dir の
   `.pre_trackb` で Track B 以前へ戻せる（§6 参照）。

### 8.4 残作業（human steps）

1. **Tatsuki GUI 目視**（ローカル `python3 ts24_workbench.py`）: 📥 Import/Quality →
   🏁 Status の "no active manifest" 表示 / 🔍 Live Event Scan が拒否ダイアログを出すこと /
   🗄 Historical Maintenance Scan の確認ダイアログ / 🦾 Suspension/Posture・Race Analysis の無回帰。
2. **Round9 activation（次戦・別GO）**: `round9_readiness_acceptance_20260713.md` §2 checklist
   （テンプレート記入 → seal → validate → register → activate → live scan dry-run 確認）。
   activation 後は `required_round()` が manifest から ROUND9 を返し、REQUIRED_ROUND 定数の
   手書換えは不要になる。
3. **既知の別修正候補（Track B 起因ではない・§8 open item 4 再掲）**:
   `analysis_run_log.analysis_run_id` が秒解像度のため同一秒内の scan 2回で PK 衝突する既存バグ
   （低優先・別タスク）。
4. **既知の cosmetic 事項**: 🏁 Status の `next_action` は §73 の live-intake 前提ロジックのため、
   ROUND8 finalized + fallback 定数 ROUND8 の現状では「⚠ canonical に ROUND8 行あり」と表示される
   （配線前からの既存挙動・regression ではない）。Round9 manifest activation で required_round() が
   ROUND9 になり自然解消する。
