# Race weekend Workbench data ops hardening — 実装・検証レポート

- Date: 2026-07-10
- Priority: P0（次の Round8 session 前）
- 指示書: `reports/race_weekend_workbench_data_ops_hardening_code_instruction_20260710.md`
- 変更ファイル: **`ts24_workbench.py` のみ**（`ImportQualityTab`・約610行追加）
- `extraction_scan.py` / `session_extract_staging.py` は**無変更** = §68 Round8-only guard 完全保持
- DB への書込: なし（status/gate/audit は SELECT のみ。Safety Audit の書込は `.md` 1ファイルのみ）
- commit / push: なし

---

## 1. ★Workbench が「不可能 / ブロック」にしたもの（コードで遮断）

以下は operator の注意力に依存せず、**Workbench 自身が構造的に不可能またはブロック**にした項目。

| # | 事象 | 遮断メカニズム |
|---|------|----------------|
| 1 | 非 ROUND8 event での Apply | event 入力必須 + `REQUIRED_ROUND` 照合（§68 既存）+ `_preapply_gate` チェック1 で再確認（多層防御）。subprocess には常に `--event <ev> --required-round ROUND8` が付く（§68 Layer1/2 = exit 4 fail-closed） |
| 2 | 非 ROUND8 / 非 `PROV_` 候補が混ざったままの Apply | `_preapply_gate` チェック2: dry-run stdout から候補 run_id を regex 抽出し、`ROUND8` を含まない・`PROV_` で始まらない run_id が 1 件でもあれば **FAIL → Apply 中止**（critical ダイアログで全列挙・DB 無変更） |
| 3 | historical pending queue 行（過去イベント）の混入 Apply | `_preapply_gate` チェック3: 各候補 run_id の date+round を event key（`YYYYMMDD-ROUNDx-RIDER`）と突合。不一致 = FAIL。加えてチェック5 で候補数 > disk outing 数も FAIL |
| 4 | 未 Scan（disk にあるが registry/queue 未登録）のままの Apply | `_preapply_gate` チェック5: disk / registry / queue 突合で missing があれば **FAIL「先に Session Scan」**（§72 の outing 単位突合 `_reconcile_event_outings` を再利用） |
| 5 | report pending 行を 2D 候補として数える | 候補抽出 regex は `gate <outing>: PASS|WARNING (run_id=PROV_..., laps=N)` 形式の 2D 行のみ一致 = **構造的に不可能**。report pending は別カウント（not a blocker）表示のみ |
| 6 | FAIL 隔離された outing の取込 | 候補 regex は PASS/WARNING のみ一致。FAIL 隔離分は `session_extract_staging.py` 側でも insert 対象外（既存挙動）+ gate の expected delta にも入らない |
| 7 | canonical に ROUND8 行がある状態での live intake 続行 | `_preapply_gate` チェック7: canonical runs/laps/lap_suspension の ROUND8 行 > 0 なら **FAIL・作業停止指示**（finalization 開始は別 GO） |
| 8 | Apply 後の canonical 汚染の見逃し | `_post_apply_check`: apply 直後に canonical 6 テーブル before==after / provisional delta==expected（laps==lap_suspension）/ ROUND8 only / canonical `PROV_%`=0 / canonical DONINGTONPARK=0 を即時判定。FAIL 時は **critical ダイアログ（apply ログ・backup パス・変化テーブル明示・「これ以上操作せず Code に連絡 / do not continue」）** + 常設ラベルに ⛔ 表示 |
| 9 | dry-run stdout が空 / 形式変化した場合の見切り Apply | `_preapply_gate` チェック2: 候補 0 抽出 = **FAIL（fail-closed）**。「候補が読めない」は「安全」ではなく「中止」と解釈する |
| 10 | Report 完了を provisional 2D 抽出の前提にする退行 | status / gate / audit のすべてで report pending を「not a blocker」と明示。gate は report 行を候補に数えない（#5）。オフライン raw-2D-first 経路は不変 |

いずれの FAIL でも **Apply subprocess は起動されず DB は無変更**（gate は `--apply` 実行前に評価される）。

## 2. 人間確認ステップとして残るもの（意図的に自動化しない）

| # | ステップ | 残す理由 |
|---|---------|----------|
| 1 | raw 2D フォルダの保存と iCloud 同期完了の目視 | iCloud dataless/半端コピーは Finder 目視が最終判断（`_looks_unstable` は補助検出のみ・内容非読取） |
| 2 | 🔍 Session Scan ボタンを押す | folder watcher auto-scan は Forbidden（指示書）。status タブ / gate が「押すべきタイミング」を明示する |
| 3 | ⬇ Session Import の dry-run 結果確認 → **Apply の最終クリック** | 確認ダイアログは候補 session 別一覧（例 QP: 3 outing / 18 laps）+ expected provisional delta + gate 全 PASS を明示・**既定 Cancel**。auto-apply は Forbidden |
| 4 | 複数 session が同時 pending の場合の追加確認 | 複数 session 混在 Apply は誤解しやすいため、追加の明示確認ダイアログ（**既定 No**）を挟む。1 session のみなら通常確認のみ |
| 5 | post-apply invariant FAIL 時の対応（作業停止・Code へ連絡） | 自動 rollback はしない（誤爆リスク）。backup パスと変化テーブルを提示し人間判断に委ねる |
| 6 | Report v2 provisional 生成の確認（既定 Cancel・§60） | 提出物の最終判断は Tatsuki |
| 7 | Safety Audit の実行と読解（session 前 / 現地離脱前） | 🛡 ボタン 1 クリックで生成されるが、PASS/FAIL summary の確認は人間 |
| 8 | Round8 finalization（canonical 反映） | 完全にスコープ外・別 GO（§65 型 targeted-insert・weekend 後のみ） |

## 3. 実装内容（`ts24_workbench.py` / `ImportQualityTab`）

- **§1 🏁 Race Weekend Status サブタブ**（inner QTabWidget 先頭・等幅テキスト）: `_race_weekend_status()` / `_render_weekend_status()` / `_refresh_weekend_status()`（`_load` から refresh）。表示 = event / raw_2d_on_disk / registered_2d / queue_2d(pending/awaiting_gate/failed/skipped) / provisional by session / canonical_round8 / report_pending(not a blocker) / next_action。**local disk + SQLite のみ**（ネットワーク・Supabase・DB Master 非参照）。+ 🛡 Safety Audit ボタン。
- **§2 `_preapply_gate(ev, dry_stdout)`**（L7322）: fail-closed 8 チェック（上表 #1-#9）。FAIL 1 件でも critical ダイアログで全列挙し Apply 中止。
- **§4 PASS 時の確認ダイアログ**: 候補 session 別一覧 + expected provisional delta + gate 全 PASS + report pending not-a-blocker を明記（既定 Cancel）。複数 session 混在時は追加確認（既定 No）。
- **§3 `_post_apply_check(ev, pre, info, ...)`**（L7405）: apply 直前 `_all_counts()`（canonical 6 + provisional 3）→ apply 後に 6 invariant 判定。全 PASS=information / FAIL=critical（ログ・backup パス〔stdout grep → `02_DATABASE` glob fallback〕・do not continue）。
- **§5 `_reconcile_event_outings` 拡張**: disk/registry/queue/missing_by_session + failed_2d/skipped_2d を追加（既存キー不変 = §72 無回帰）。`_session_of_stem()` 新設。
- **§6 `_run_safety_audit()` / `_write_safety_audit()`**: `reports/race_weekend_workbench_safety_audit_<TS>.md` を生成（7 セクション: raw disk / registry・queue / provisional / canonical invariants / 最新ログ / next action / PASS-FAIL summary）。DB は SELECT のみ。生成済みサンプル = `reports/race_weekend_workbench_safety_audit_20260710_213504.md`（全項目 PASS）。

## 4. 検証結果

### 4a. 実装エージェント セルフチェック（全 PASS）
py_compile 3 ファイル / offscreen 7 タブ + inner 4 タブ / status 実測 / gate 模擬 4 ケース / audit .md 生成 / DB counts before==after 完全一致。監督（Claude Code 本体）が `_preapply_gate` / `_post_apply_check` / `_run_import` 配線をコードレビュー済み（fail-closed 順序・既定 Cancel/No・例外時 DB 無変更・exit 2 時の expected delta 整合）。

### 4b. ★独立検証（別エージェント・read-only・2026-07-10）

| 項目 | 実測 | 判定 |
|---|---|---|
| MainWindow タブ | **7**（… 📥 Import / Quality） | ✅ |
| ImportQualityTab inner タブ | **4**・先頭 = **🏁 Race Weekend Status**（他: 📋 未処理キュー / ⚠ 要確認 / 🔎 検出チェック） | ✅ |
| `_race_weekend_status('20260710-ROUND8-JA52')` | disk_total=**5**（FP=2 QP=3）/ registered_2d=5 / queue pending=0 awaiting_gate=**5** failed=0 skipped=0 | ✅ |
| 同 provisional | **5 runs / 39 laps**（FP=2/21・QP=3/18） | ✅ |
| 同 canonical_round8 | runs=0 laps=0 lap_suspension=0 race_results=0 | ✅ |
| 同 report_pending | **1**（not a blocker 表示） | ✅ |
| 同 next_action | `safe / waiting for new raw 2D` | ✅ |
| `_preapply_gate` 正常系（模擬 stdout: `PROV_20260710_ROUND8_DONINGTON_QP_JA52_R1..R3`・laps 6/6/6） | **ok=True**・failures=0・sessions=`{QP: 3 outings / 18 laps}`・expected_delta=**(3, 18, 18)** | ✅ |
| `_preapply_gate` 混入系（+`PROV_20260612_ROUND7_MISANO_FP_JA52_R1`） | **ok=False**・FAIL 2 件（ROUND8 以外/非PROV 混入 + event と date/round 不一致 = historical 疑い）で当該 run_id を明示列挙 | ✅ |
| `_preapply_gate` 空 stdout | **ok=False**（候補抽出不能 = fail-closed） | ✅ |
| DB counts before==after（11 テーブル） | runs **286** / laps **1279** / lap_suspension **1279** / race_results **866** / pdf_lap_times **7613** / pdf_lap_times_v2_staging **7710** / provisional **5/39/39** / registry **411** / queue **403** — **完全一致** | ✅ |
| §68 guard 保持 | `extraction_scan.py` = git clean（無変更）/ `session_extract_staging.py` に `enforce_apply_guard` / `--required-round` 存置 | ✅ |

## 5. 現地操作手順（session 後）

1. raw 2D フォルダを `DATA 2D/20260710-ROUND8-JA52/` に保存（iCloud 同期完了を Finder で目視）。
2. Workbench `📥 Import / Quality` → **🏁 Race Weekend Status** で `raw_2d_on_disk` に新 outing が出るか確認。`next_action` の指示に従う。
3. missing 表示があれば **🔍 Session Scan**（管理テーブルのみ・2D 抽出なし）。
4. **⬇ Session Import (staging)** → event `20260710-ROUND8-JA52`（自動 pre-fill）→ dry-run 自動実行。
5. **pre-apply gate が自動評価**: FAIL があれば全列挙ダイアログで中止（DB 無変更）。PASS なら候補 session 別一覧 + expected delta の確認ダイアログ（既定 Cancel）→ Apply。
6. Apply 直後に **post-apply invariant check が自動実行**: 全 PASS = information。FAIL = 作業停止・Code へ連絡（do not continue）。
7. Status タブで provisional 反映・`next_action: safe` を確認 → 🦾 Suspension/Posture ⏳prov 確認 → Report v2 provisional 生成（確認ダイアログ・既定 Cancel）。
8. session 前 / 現地離脱前に **🛡 Safety Audit** で read-only レポートを生成し PASS/FAIL summary を確認。

## 6. rollback

```bash
git checkout -- ts24_workbench.py
```

**⚠ 注意（重要）**: 現在 `ts24_workbench.py` の HEAD（`5651d97`）は §44 時点のため、上記コマンドは本タスク（§73）だけでなく **未コミットの §48〜§72 の Workbench 機能（Report v2 ボタン / Session Scan / Session Import / §68 guard UI / §69・§72 hotfix / provisional overlay）もまとめて巻き戻す**。本タスクのみを外したい場合は、`ImportQualityTab` に追加された §73 ブロック（`_race_weekend_status` 系 / `_preapply_gate` / `_post_apply_check` / `_run_safety_audit` 系 / status サブタブ構築部 / `_run_import` 内の gate・post-check 呼出）を除去する targeted revert が安全。DB は無変更のため DB 側の rollback は不要。

## 7. Forbidden 遵守表（指示書）

| Forbidden | 遵守 |
|---|---|
| canonical business tables 書込 | ✅ なし（SELECT のみ・独立検証で before==after 実証） |
| Round8 final 化 | ✅ なし（gate はむしろ canonical ROUND8>0 を FAIL 扱い） |
| provisional クリア | ✅ なし（5/39/39 不変） |
| DB Master refresh | ✅ なし（status/audit は Excel 非参照） |
| Supabase sync | ✅ なし（local disk + SQLite のみ） |
| commit / push | ✅ なし（working tree のみ） |
| folder watcher auto-apply | ✅ なし（全操作ボタン式・既定 Cancel/No） |
| `--event` / `--required-round ROUND8` guard 弱体化 | ✅ なし（`extraction_scan.py`/`session_extract_staging.py` 無変更・gate は追加の多層防御） |
| Report 完了を provisional 2D の前提化 | ✅ なし（report pending = not a blocker を status/gate/audit 全所で明示） |
