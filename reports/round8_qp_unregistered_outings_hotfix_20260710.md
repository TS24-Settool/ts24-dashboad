# Round8 QP Unregistered Outings Hotfix — 実装報告（P0・outing単位診断）

- **Date**: 2026-07-10
- **Priority**: P0 field recovery during Round8 QP
- **指示書**: `05_SCRIPTS/reports/round8_qp_unregistered_outings_hotfix_code_instruction_20260710.md` / Obsidian `00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-10 19:09 P0）
- **変更ファイル**: `ts24_workbench.py` のみ（`ImportQualityTab`・追加のみ）。`extraction_scan.py` / `session_extract_staging.py` は無変更。
- **DB**: read-only 実装（canonical / provisional / 管理テーブルすべて before==after 完全一致・§6 参照）。commit / push なし。

---

## 1. Root cause

**telemetry parse failure でも Round8 guard failure でもない。「event に既存行があるまま新規 outing だけ未登録」の検出漏れ。**

- `DATA 2D/20260710-ROUND8-JA52` にはディスク上 **5 outing** が実在:
  `FP-JA52-01.MES` / `FP-JA52-02.MES` / `QP-JA52-01.MES` / `QP-JA52-02.MES` / `QP-JA52-03.MES`
- しかし正本DBの管理テーブルには **FP 2D 2行 + report 1行のみ**:
  - `import_queue`: FP-JA52-01/02 = `awaiting_gate 2d_extract`、`20260710-ROUND8-JA52.xlsx` = `pending report_import`
  - `source_file_registry`: 同3行（`2d_outing` ×2 + `report` ×1）
  - **QP-JA52-01/02/03 は registry / queue のどちらにも未登録**
- `session_extract_staging.py`（Session Import 実体）は filesystem 直読でなく **`import_queue` の pending `2d_extract` を読む** → QP 未登録のままでは候補0（exit 1）が必然。
  dry-run log `reports/session_import_dryrun_20260710_190918.log`: `[STAGE] 候補 0 件（pending 2d_extract がフィルタに一致しない）`
- §69 hotfix の `_diagnose_zero_candidates` は **event 単位 count 診断**（registry/queue の行数のみ）だったため、
  `registry=3 / queue=3(pending=1)` と見えて `not_scanned`（行0）にも `no_pending` にも該当せず **unknown に落ちていた**。
  → 診断を event 単位から **outing 単位の突合（reconciliation）** に強化する必要があった（本 hotfix の実装内容）。

### QP missing の実測 proof（実装後の `_reconcile_event_outings` 出力）

```text
event = 20260710-ROUND8-JA52
disk_2d               = 5  (FP-JA52-01, FP-JA52-02, QP-JA52-01, QP-JA52-02, QP-JA52-03)
registry_2d           = 2  (FP-JA52-01, FP-JA52-02)
queue_2d              = 2  (FP-JA52-01, FP-JA52-02)
pending_2d            = 0
awaiting_gate_2d      = 2
missing_from_registry = QP-JA52-01, QP-JA52-02, QP-JA52-03
missing_from_queue    = QP-JA52-01, QP-JA52-02, QP-JA52-03
non_2d_pending        = 1  (report_import 行。2D 抽出候補ではない)
```

指示書の要求（`missing_from_registry = missing_from_queue = QP-JA52-01/02/03` の明示）と完全一致。

---

## 2. Race weekend 必須要件の確認 — raw 2D first（Report / canonical 非依存）

指示書「Race weekend workflow requirement」への適合を実装・表示の両面で確認済み:

- **provisional 2D 抽出は Report 完了・canonical 紐付けを前提にしない**。診断メッセージと検出チェック行に
  「report 行 pending N 件は 2D 抽出候補ではありません。Report 紐付けは provisional 2D 抽出の前提条件ではありません」を明示
  （report pending 行が候補に見えて混乱する事象を UI で遮断）。
- 復旧経路は **`DATA 2D` の raw フォルダ突合 → Session Scan（管理テーブルのみ）→ Session Import（dry-run → 人手 Apply）** で完結し、
  DB Master / Supabase / canonical finalization / online サービスを一切要求しない。
- queue / registry は管理・監査層として維持しつつ、**stale 時は disk との outing 突合で検出・復旧を案内**
  （queue/registry を新規 session 検出の唯一経路にしない）。
- canonical への昇格（final 化）は従来どおり **race 終了後の別 GO**（§65 型 targeted-insert・本 hotfix は無関係に据え置き）。

---

## 3. Code changes（`ts24_workbench.py`・`ImportQualityTab`・追加のみ）

### 3.1 新規 `_reconcile_event_outings(ev)` — read-only outing 突合

- **disk**: `DATA 2D/<event>` 直下の `*.MES` フォルダを列挙。**name + stat のみ**（内容非読取・iCloud DL 非誘発・§24a と同方針）。
- **registry**: `file_type='2d_outing' AND file_path LIKE '%<ev>%'` の `.MES` stem 集合。
- **queue**: `target_kind='2d_extract'` の stem 集合 + `pending` / `awaiting_gate` 計数。report 等の非2D行は `non_2d_pending` に分離。
- 戻り値: `disk` / `registry` / `queued` / `pending_2d` / `awaiting_gate_2d` / `missing_from_registry` / `missing_from_queue` / `non_2d_pending`。

### 3.2 `_diagnose_zero_candidates` に case `missing_outings` を追加

- 判定順は **`no_pending` / `unknown` より前**（既存 case `folder_missing` / `not_scanned` / `unstable` は §69 のまま無回帰）。
- メッセージ内容: missing outing 名の明示（QP-JA52-01/02/03）+ outing 突合数値 +
  「report 行 pending N 件は 2D 抽出候補ではありません。Report 紐付けは provisional 2D 抽出の前提条件ではありません」+
  `_looks_unstable` の未安定サイン併記。
- `offer_scan=True` → 既存 §69 の **「Session Scan を実行」ボタン**（`_run_scan()`）→ Scan 完了後「再度 Session Import」案内へ接続。
  **auto-apply なし**（provisional 書込は従来どおり dry-run 確認 + 人手 Apply + §68 event guard 経由のみ）。

### 3.3 `🔎 検出チェック` タブに合成行 `detect_outing_reconcile_2d` を挿入（`_load()`）

- read-only 表示のみ（`data_quality_log` へは書かない）。表示例:

```text
detect_outing_reconcile_2d
disk_2d=5 registry_2d=2 queue_2d=2 pending_2d=0 awaiting_gate_2d=2
missing=QP-JA52-01, QP-JA52-02, QP-JA52-03
next_action=Session Scan（report pending 1 件は 2D 候補外）
```

- missing あり = **FAIL 赤表示**（report pending 行が存在しても 2D 候補と区別して可視化＝指示書 §3 要件）。

---

## 4. Validation（全 PASS）

### 4.1 実行コマンド

```bash
# 構文チェック（3ファイル）
python3 -m py_compile ts24_workbench.py extraction_scan.py session_extract_staging.py

# offscreen スモークテスト（GUI 非表示・実DB read-only）
QT_QPA_PLATFORM=offscreen python3 <offscreen test driver>
```

### 4.2 offscreen 検証結果

| 項目 | 結果 |
|---|---|
| MainWindow 7タブ | 無回帰 PASS |
| `_reconcile_event_outings('20260710-ROUND8-JA52')` | missing=QP-JA52-01/02/03・awaiting_gate_2d=2・non_2d_pending=1 を正確検出 |
| `_diagnose_zero_candidates` | case=`missing_outings`・offer_scan=True・msg に QP 3本 + Session Scan 導線 + report 非前提を明示 |
| 既存 case `folder_missing` | 無回帰 PASS |
| 検出チェック タブ行0 | `detect_outing_reconcile_2d` FAIL（赤）表示 |

### 4.3 DB before==after 完全一致（無書込証明）

| テーブル | 件数（before == after） |
|---|---:|
| runs | 286 |
| laps | 1279 |
| lap_suspension | 1279 |
| race_results | 866 |
| pdf_lap_times | 7613 |
| provisional（runs/laps/lap_suspension） | 2 / 21 / 21 |
| source_file_registry | 408 |
| import_queue | 400 |

### 4.4 Round8 guard・既存配線の無回帰

- **§68 guard 無変更**: `session_extract_staging.py` の `--required-round` / `enforce_apply_guard` は存置（本 hotfix で同ファイル無変更）。
  `extraction_scan.py` も無変更。
- **§69 の exit==1 配線 無回帰**（診断は case 追加のみ）。
- 変更ファイルは `ts24_workbench.py` のみ。working tree の他の未コミット差分は §46e / §65 / §71 の既記録作業であり本件と無関係。

---

## 5. 安全宣言（Round8 guard / canonical・Forbidden 遵守）

- **Round8 guard（§68）は一切弱体化していない**: `--event` / `--required-round ROUND8` の 2層 fail-closed は無変更で維持。
- **canonical business tables への書込ゼロ**（§4.3 の before==after で機械証明）。provisional への auto-apply もなし。
- unfiltered import なし / Round8 final 化なし / Report 完了を provisional import の前提にしない（raw 2D first を明記）/
  DB Master refresh なし / Supabase sync なし / historical queue cleanup なし / commit・push なし / folder watcher auto-apply なし。

---

## 6. 現地復旧手順（Tatsuki 用）

1. Workbench `📥 Import / Quality` → `⬇ Session Import (staging)` → event `20260710-ROUND8-JA52`（自動 pre-fill）。
2. 候補0 popup が **QP-JA52-01/02/03 の missing を明示** →「Session Scan を実行」ボタンを押す（管理テーブルのみ更新・抽出なし）。
3. Scan 完了後、もう一度 `⬇ Session Import` → dry-run 結果を確認（**Round8 QP のみ**であること）。
4. Apply（既定 Cancel・別確認ダイアログ）→ provisional 反映 → ⏳prov 表示 / Report v2 provisional。

※ 実 Scan / Import は iCloud 同期の Finder 目視運用のため **Tatsuki ローカルで実行**（本セッションでは未実行）。

---

## 7. Rollback

```bash
git checkout -- ts24_workbench.py
```

DB は無変更のためロールバック不要。
