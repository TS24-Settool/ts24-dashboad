# Round9 Readiness Acceptance — Event Control Plane 前提の次戦準備 — 2026-07-13

- 出典: Track B 実装（`reports/race_weekend_event_control_plane_apply_20260713.md`）
- 目的: ROUND8 でのハードコード運用（`REQUIRED_ROUND` 手書換・全域 scan・CLI ガード穴）を廃し、
  ROUND9 以降は **validated manifest だけ**から active round/event を導出する。

## 1. Round9 manifest テンプレート

- ファイル: `02_DATABASE/event_manifests/TEMPLATE_ROUND9.json`
- 仕様: schema v1（`reports/event_manifest_schema_proposal_20260711.json` 準拠・
  `event_manifest.py` が enforcement）。placeholder + `status: draft` + `content_hash: null` のため
  **そのままでは validate 不合格 = 誤って activate できない**（fail-closed をテンプレート自体に内蔵）。
- ハードコード除去の状態:
  - `extraction_scan.py --manifest` / `session_extract_staging.py`（active manifest 解決）は
    round/event/session/root を **manifest からのみ**取得 — ROUND8 リテラル依存なし。
  - 残るラウンド定数は `ts24_workbench.py :7301 REQUIRED_ROUND`（Track B では無改変対象）。
    配線仕様（apply レポート §7）適用後は **manifest 優先 + 定数フォールバック**となり、
    毎ラウンドの必須書換えが消える。

## 2. Pre-event activation checklist（ROUND9 開幕前・順番厳守）

すべて正本DBに対する操作は **operator（Tatsuki）GO の下で** 実施。()) 内は検証コマンド。

1. ☐ event フォルダ命名確定: `DATA 2D/<YYYYMMDD>-ROUND9-<RIDER>`（EVENT_RE 準拠・rider ごとに1つ）。
2. ☐ テンプレートを複製し全 placeholder を記入
   （circuit は **canonical TRACK_M キー**。例: DONINGTON であって DONINGTONPARK ではない）。
   riders / raw_2d_root / allowed_sessions（当該イベントに実在する session のみ）/
   fingerprint_policy=content / expected_outings=null（weekend 中に宣言を絞るのは任意）。
3. ☐ status を `approved` にし approved_by / approved_at を記入。
4. ☐ seal: `python3 05_SCRIPTS/event_manifest.py seal 02_DATABASE/event_manifests/<key>.json`
5. ☐ validate: `python3 05_SCRIPTS/event_manifest.py validate <同ファイル>`（[OK] を確認）。
6. ☐ （初回のみ）正本DBに管理2テーブル作成 **[別GO]**:
   `python3 05_SCRIPTS/create_event_control_tables.py`（WAL-safe backup 自動・追加のみ・冪等）。
7. ☐ register **[別GO]**: `python3 05_SCRIPTS/event_manifest.py register <json> --db 02_DATABASE/ts24_unified.db`
8. ☐ 前イベントの active manifest を閉鎖:（ROUND8 が active の場合）
   `set_manifest_status(... 'locked'/'closed')` — active は同時1件のみ（DB index が強制）。
9. ☐ activate **[別GO]**: `python3 05_SCRIPTS/event_manifest.py activate <event_key> --db ... --actor tatsuki`
   （show-active で確認）。
10. ☐ live scan 動作確認（dry-run から）:
    `python3 05_SCRIPTS/extraction_scan.py --manifest 02_DATABASE/event_manifests/<key>.json --dry-run`
    → scope 内 outing のみ検出・unknown session/undeclared stem が gated になること。
11. ☐ staging ガード確認（書込なし）:
    `python3 05_SCRIPTS/session_extract_staging.py --event <event_key>`（dry-run）→
    ログに `active event manifest: <key> … round=ROUND9` と
    `run_no 採番 = deterministic` が出ること。
12. ☐ 2人目の rider が走る場合: rider2 の manifest も 2〜7 を実施（activate は取込対象の
    rider event に切替えて行う — exactly-one-active 運用）。
13. ☐ Workbench 配線適用済みなら: Status タブに manifest hash/version が表示され、
    Live Event Scan が manifest 経由になっていること（apply レポート §7 の受入項目）。

## 3. 受入条件ステータス（Round9 readiness acceptance criteria）

| 基準（指示書 §Round9 readiness） | 状態 | 根拠 |
|---|---|---|
| ハードコード Round8 挙動の除去（CLI 層） | ✅ 完了 | scan/staging は manifest から round/event を導出（adversarial T10/T16/T17）。 |
| active round/event は validated manifest のみから導出 | ✅ 完了（CLI）/ ⏳ Workbench は配線待ち | `get_active_manifest()` 三層改竄検出 + exactly-one-active（T03/T18/T19/T20）。 |
| Round9 manifest テンプレート提供 | ✅ 完了 | `TEMPLATE_ROUND9.json`（validate 不合格 by design）。 |
| Pre-event activation checklist 提供 | ✅ 完了 | 本書 §2。 |
| 実 Round9 イベントを activate していない | ✅ 遵守 | 正本DBに event control テーブル自体を未作成（activation は scratch のみ）。 |
| 既存 final/provisional データ・レポートへの読取互換 | ✅ 完了 | 後方互換回帰（apply レポート §5）: 変更前後で argless scan / staging dry-run 出力一致・既存テーブル無 ALTER。 |
| ROUND8 実 manifest（両 rider）が実ファイルとして存在 | ✅ 完了 | `20260710-ROUND8-JA52.json` / `20260710-ROUND8-DA77.json`（sealed）。 |

## 4. ROUND8 manifest の位置づけ（記録）

- ROUND8 は Track A により canonical finalized 済（runs 302 / laps 1423 現況）。ROUND8 manifest は
  (a) 監査記録、(b) 万一の再取込を `stage_canonical_conflict` で拒否する検証データ（adversarial T26 で
  実証済）、(c) DA77 の `SP-77-03` 重複・`SX_*` 未知フォルダを gated と宣言する事故記録として保存。
- ROUND8 manifest を activate する運用上の必要は基本的に無い（activate するとしても再取込は
  canonical 衝突で fail-closed になることを T26 で確認済）。

## 5. Round9 週末の標準運用（配線後の想定フロー）

1. session 終了 → 2D フォルダコピー完了を待つ（コピー中は scan が `incomplete` で保留 = T07）。
2. Workbench `Live Event Scan`（= `--manifest`）→ scope 内のみ queue。
3. `Session Import` dry-run → candidates + 予測 delta + stop reasons 確認 → Apply（明示確認）。
   run_id は stem 決定論・再実行は no-op・矛盾は conflict FAIL。
4. Status タブ / Safety Audit で ledger receipt（apply_started/apply_committed 突合）と
   provisional ⊆ active round を確認。
5. weekend 終了 → finalization は従来どおり **別 GO**（§65 型 targeted insert）→ manifest を
   locked/closed に遷移。
