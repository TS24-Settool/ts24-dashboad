# ROUND8 Live Intake P0 Operations Gate（read-only runbook）— 2026-07-11

- 依頼元: `08_OBSIDIAN/TS24_Engineering_Knowledge/00_INBOX/FOR_CLAUDE_CODE.md`（2026-07-11 P0・L86-135）
- 背景: `reports/race_weekend_event_control_plane_readiness_20260711.md`（§75・既知 P0 穴 ①-④）
- モード: **read-only / documentation-only**（DB は `mode=ro` SELECT のみ・書込は本 .md と Obsidian .md のみ）
- 実装ゲート: `Event control plane implementation GO`（B-1 のみ・受領まで runtime 変更なし）

## 0. Forbidden 遵守宣言

- runtime コード（`ts24_workbench.py` / `extraction_scan.py` / `session_extract_staging.py`）変更: **なし**
- DB / queue / provisional / registry への書込・更新・削除: **なし**（`mode=ro` URI 接続・SELECT のみ）
- テスト目的の Scan / Apply / queue 更新: **なし**
- DB Master / Supabase / commit / push / Round8 finalization / provisional clear: **なし**

---

## 1. 現状監査（2026-07-11・mode=ro 実測）

### 1a. provisional 3テーブル — 期待値と完全一致・整合性違反 0

| チェック | 実測 | 期待 | 判定 |
|---|---|---|---|
| runs_provisional | **6** | 6 | ✅ |
| laps_provisional | **46** | 46 | ✅ |
| lap_suspension_provisional | **46** | 46 | ✅ |
| session 内訳（runs/laps） | FP **2/21**・QP **3/18**・WUP1 **1/7** | 同左 | ✅ |
| run_id 重複 | **0** | 0 | ✅ |
| 親 run なし lap（laps.run_id ⊄ runs.run_id） | **0** | 0 | ✅ |
| laps ↔ lap_suspension の lap_id 差分（両方向） | **0 / 0** | 0 | ✅ |

### 1b. 各 provisional run の provenance（registry.sha256 と JOIN 照合）

全 6 run: `provisional_event_key='20260710-ROUND8-JA52'`・`circuit='DONINGTON'`・`rider='JA52'`・
`source_manifest_hash` が `source_file_registry.sha256` に **6/6 一致**（reg_match=1）。

| run_id | source_file_path（末尾） | quality_status |
|---|---|---|
| PROV_20260710_ROUND8_DONINGTON_FP_JA52_R1 | FP-JA52-01.MES | PASS |
| PROV_20260710_ROUND8_DONINGTON_FP_JA52_R2 | FP-JA52-02.MES | WARNING |
| PROV_20260710_ROUND8_DONINGTON_QP_JA52_R1 | QP-JA52-01.MES | PASS |
| PROV_20260710_ROUND8_DONINGTON_QP_JA52_R2 | QP-JA52-02.MES | PASS |
| PROV_20260710_ROUND8_DONINGTON_QP_JA52_R3 | QP-JA52-03.MES | PASS |
| PROV_20260710_ROUND8_DONINGTON_WUP1_JA52_R1 | WUP1-JA52-01.MES | PASS |

### 1c. canonical 不変（汚染 0）

| チェック | 実測 |
|---|---:|
| runs / lap_suspension `round='ROUND8'` | 0 / 0 |
| laps `run_id LIKE '%ROUND8%'` | 0 |
| race_results `round LIKE '%ROUND8%'` | 0 |
| canonical runs / laps `PROV_%` | 0 / 0 |
| runs / lap_suspension `circuit='DONINGTONPARK'` | 0 / 0 |
| canonical totals（runs/laps/ls/rr/plt/v2stg） | 286 / 1279 / 1279 / 866 / 7613 / 7710 |

### 1d. ★queue の分離明示 — 「今回の JA52 live intake 候補に混ぜてはいけない対象」

queue 全体 = **422 行**（pending 383 / awaiting_gate 18 / failed 7 / skipped 14）。ROUND8 関連 = **17 行**:

| 区分 | 件数 | status | 扱い |
|---|---:|---|---|
| **JA52 2d_extract**（FP2+QP3+WUP1・取込済） | **6** | awaiting_gate | 今回分は反映済み。**再候補化しない**（`--include-awaiting` 禁止） |
| **JA52 report_import**（`20260710-ROUND8-JA52.xlsx`） | **1** | pending | **2D 候補ではない = not a blocker**。混ぜない |
| **DA77 2d_extract**（F1×2/SP×3/SX×2/WU1×3） | **10** | pending | **JA52 live intake に混ぜない**（DA77 は別 event フォルダ。Apply 対象外） |
| **historical pending**（ROUND8 以外・26 イベント分散） | **372** | pending | **絶対に Apply しない**（§62 既知リスク・gate #3/#4 が検出） |

（awaiting_gate 18 の内訳 = ROUND8 JA52 6 + ROUND7 JA52 12〔final 反映済み §65〕。ROUND7 分も再候補化禁止。）

**監査結論: 現状は完全に健全。** provisional/canonical/provenance に違反ゼロ。危険は DB 状態でなく
「次の Apply 操作」にのみ存在する → 以下の Runbook で操作経路を固定する。

---

## 2. Runbook — ROUND8 現地操作手順（この経路のみ・一画面ずつ確認）

### 2.1 許可経路（これ以外は使わない）

```text
Workbench 📥 Import/Quality タブ
  → 🔍 Session Scan
  → ⬇ Session Import (staging)  … dry-run が自動実行される
  → 表示候補の確認（session / outing / laps / expected delta）
  → Apply 確認ダイアログ（既定 Cancel）
  → 🏁 Race Weekend Status / 🛡 Safety Audit
  → 🦾 Suspension/Posture で provisional overlay（⏳ prov）確認
```

### 2.2 禁止操作（live 中は絶対にしない）

- ❌ 直接 CLI `python3 session_extract_staging.py --apply ...`（**CLI 単体は `--required-round` 省略可 = P0穴①**）
- ❌ `--include-awaiting` の使用（取込済み outing の再候補化 → run_id 衝突 = P0穴②の直接トリガー）
- ❌ live 中の全体 maintenance scan の実行（Workbench ボタン以外での `extraction_scan.py` 手動実行）
- ❌ DB Browser 等での ts24_unified.db 直接更新
- ❌ 複数 session を曖昧にした一括 Apply（ダイアログが出たら原則 No）
- ❌ DA77 フォルダ / report 行 / historical pending を対象にした Apply

### 2.3 新 session 到着時の操作順（チェックリスト）

- [ ] **(1) iCloud 同期の目視**: Finder で `DATA 2D/20260710-ROUND8-JA52/` の新 outing フォルダ（例 `WUP2-JA52-01.MES`）が
      ダウンロード済み（雲アイコンなし）・ファイルサイズ > 0 であることを確認。
- [ ] **(2) 🏁 Status タブ**: raw_2d_on_disk / registered_2d / queue_2d / provisional by session / canonical_round8 を確認。
      **確認値**: canonical_round8 = 全 0・provisional が現在の既知値（今: FP 2/21・QP 3/18・WUP1 1/7）と一致・
      新 outing は disk にあるが registry/queue に未登録（= not_scanned が正常）。
- [ ] **(3) 🔍 Session Scan**: 実行。管理テーブルのみ更新（2D 抽出はまだ行われない）。
      **既知の副作用（気にしない・記録のみ）**: Scan は全域走査のため他イベントの registry/queue 行も増える。
      Apply 側は §68/§73 で防御済み。増分数値は Status タブ / Scan ログに残る。
- [ ] **(4) ⬇ Session Import**: event = `20260710-ROUND8-JA52`（自動 pre-fill）を確認して実行 → dry-run 結果を読む。
      **確認値**: 候補が**新 session のみ**（例 WUP2: 1 outing / N laps）・候補 run_id が
      `PROV_20260710_ROUND8_DONINGTON_<SESSION>_JA52_R{n}` 形式・
      **候補 run_id が Status タブの既存 provisional run_id と重複していない**（→ §3 ケース1）・
      expected provisional delta = +候補outing数 / +laps / +laps・pre-apply gate 全PASS。
- [ ] **(5) Apply 確認ダイアログ**: 内容が (4) と一致していれば Apply（既定は Cancel。迷ったら Cancel）。
      複数 session 確認ダイアログが出たら原則 **No**（→ §3 ケース2）。
- [ ] **(6) post-apply invariant**: 「全PASS」の information ダイアログを確認
      （canonical unchanged / provisional delta == expected / ROUND8 only / PROV 汚染 0 / DONINGTONPARK 0）。
- [ ] **(7) 🏁 Status 再確認 + 🛡 Safety Audit 実行**: provisional 件数が期待どおり増加・canonical_round8 = 全 0。
- [ ] **(8) 🦾 Suspension/Posture**: DONINGTON/JA52 で新 run が `⏳ ... (prov)` として表示されることを確認。

### 2.4 停止条件（1つでも該当したら Apply せず停止 → Tatsuki から Code へ連絡）

§3 の 5 ケース。共通ルール: **停止 = Cancel を押して何も書き込まない**。リカバリを自分で試みない。

### 2.5 復旧時に保存するもの（Code へ渡す）

- `reports/session_scan_<TS>.log` / `reports/session_import_dryrun_<TS>.log` / `reports/session_import_apply_<TS>.log`（該当分）
- 🛡 Safety Audit の出力 `reports/race_weekend_workbench_safety_audit_<TS>.md`
- 停止時のダイアログ / 🏁 Status タブのスクリーンショット
- （apply 後 FAIL の場合）critical ダイアログに表示された backup パス（`02_DATABASE/_backup_session_staging_<TS>/`）

### 2.6 実装ゲート再掲

- Event Control Plane **B-1 の実装開始 GO = `Event control plane implementation GO`**（それまで runtime 変更ゼロ）。
- finalization / DB Master refresh / Supabase / origin push は本 Runbook の**対象外・従来どおり個別 GO**。
- ROUND8 closure → ROUND9 readiness タスクは **`ROUND8 weekend closed`** 待ちのまま（触らない）。

---

## 3. Apply せず停止の 5 ケース（画面に何が出るか / なぜ危険か / 停止後の行動）

停止後の行動は全ケース共通: **Cancel（既定ボタン）→ ログ+スクリーンショット保存（§2.5）→ Code へ連絡。**

### ケース1: 同じ session の追加 outing が来た（例: FP-JA52-03 が後着）★最重要

- **画面**: dry-run 候補に既存 session（FP/QP/WUP1）の run_id が出る。**候補 run_id が既存 provisional run_id
  （例 `PROV_..._FP_JA52_R1`）と同名になり得る**（run_no はバッチ相対採番のため後着 outing が R1 から振り直される）。
- **なぜ危険（P0穴②）**: INSERT OR REPLACE により**既存 run が黙って上書きされ、旧 laps が孤児化**する。
- **⚠ 検出限界（隠さない）**: 現行 pre-apply gate は候補 run_id と既存 provisional run_id を**照合しない**。
  衝突時も expected delta は +1 で妥当に見えるため**事前検出は不完全**。事後に post-apply の
  「provisional delta」FAIL（actual +0 runs ≠ expected +1）で捕捉されるが、その時点で上書きは発生済み。
- **→ 運用で先回りする**: **同一 session の既存 run がある状態で同 session の新規候補が dry-run に現れたら、
  Apply 前に必ず停止。** 確認方法 = ①Status タブの provisional by session と dry-run 候補 session を突合
  ②候補 run_id 文字列が既存 run_id と重複していないか目視 ③expected delta が「新 session 分のみ」か確認。

### ケース2: Apply 候補が 1 session でない

- **画面**: 「複数 session の一括 Apply 確認」ダイアログ（例 `WUP2, RACE1`・既定 No）。
- **なぜ危険**: session 単位の検証・切り戻しができなくなる。想定外 session の混入（Scan 遅れ・後着）を見逃す。
- **行動**: 原則 **No**。意図した複数 session であることを確信できる場合のみ（それでも 1 session ずつが推奨）。

### ケース3: run_id 既存重複 または expected delta 不一致（post-apply invariant FAIL 含む）

- **画面**: dry-run 候補 run_id が既存と同名（ケース1 と同根）/ Apply 後に
  「⛔ Post-apply invariant FAIL — 作業停止」critical ダイアログ（変化テーブル・apply ログ・backup パス表示）。
- **なぜ危険**: 上書き・孤児 lap・canonical 汚染のいずれかが既に発生した可能性。
- **行動**: ダイアログの指示どおり **do not continue**。backup パスを控えて Code へ。以降の Scan/Import も停止。

### ケース4: event 外 / DA77 / report 行が候補に現れた

- **画面**: dry-run 候補に `PROV_` 以外・ROUND8 以外・DA77・report 系の行が見える
  （通常は pre-apply gate #2/#3 が critical「pre-apply gate FAIL」で列挙して Apply を中止する）。
- **なぜ危険（P0穴③含む）**: historical pending 372 件 / DA77 pending 10 件の誤取込 = final 済みデータの
  provisional 二重化。nested tier の event 外 .MES は HED ゲート免除で素通りし得るため、gate が PASS でも
  **見覚えのない outing 名が候補にあれば停止**。
- **行動**: Apply しない。候補一覧のスクリーンショットを保存して Code へ。

### ケース5: canonical 変化を示す表示

- **画面**: 🏁 Status タブの canonical_round8 が 0 でない / pre-apply gate #7 FAIL
  「canonical に ROUND8 行が存在します」/ post-apply「canonical unchanged」FAIL。
- **なぜ危険**: live intake 中に canonical へ ROUND8 が入るのは finalization 前の重大異常
  （guard バグ・手動書込・DDL 改変のいずれか）。
- **行動**: 即時全停止（Scan も Import もしない）。Safety Audit を 1 回だけ実行して .md を保存し Code へ。

---

## 付録A: 停止条件 ↔ 既存検出機構の対応表（コード読解・read-only 検証済み）

検証対象 = `ts24_workbench.py`（2026-07-11 時点・未コミット working tree）。

| ケース | 事前検出（Apply 前） | 事後検出（Apply 後） | 実効性判定 |
|---|---|---|---|
| **1. 同一 session 追加 outing（run_no 衝突）** | **なし（不完全）**: `_preapply_gate`:7322-7402 は候補 run_id vs 既存 provisional run_id の照合を持たず、expected delta（:7398-7401）も衝突時 +1 で「一致」してしまう。頼れるのは確認ダイアログ:7778-7800 の候補一覧 + 🏁 Status（`_race_weekend_status`:7219 / `_render_weekend_status`:7274）の**人間による突合のみ** | `_post_apply_check`:7405 の provisional delta 検査:7425-7435（REPLACE で actual runs +0 ≠ expected +1 → FAIL・critical:7483-7490 で backup パス提示） | **事前=運用先回り必須 / 事後=検出可**（ただし上書き発生後）。P0穴②は B-3（run_no 決定論採番+衝突 FAIL）まで解消しない |
| **2. 複数 session 一括 Apply** | 複数 session 確認ダイアログ:7811-7823（`gate_info["sessions"]` が 2 以上で発火・**既定 No**）+ 確認ダイアログの session 別一覧:7778-7789 | （session 単位 delta は集計値のみ） | **実効**（既定 No のため誤クリック耐性あり） |
| **3. expected delta 不一致 / invariant FAIL** | `_preapply_gate` #8:7398-7401 が expected delta を算出し確認ダイアログ:7782-7789 に表示（人間照合） | `_post_apply_check`:7405-7490 = canonical unchanged:7418-7423 / delta==expected かつ laps==lap_suspension:7425-7435 / ROUND8 only:7437-7446 / PROV 汚染:7447-7451 / DONINGTONPARK:7452-7458。FAIL 時 critical + 「do not continue」+ backup パス（stdout grep→glob fallback:7473-7482） | **実効**（read-only 検査・全 FAIL で停止指示を明示） |
| **4. event 外 / DA77 / report / historical 混入** | `_preapply_gate` #2:7339-7348（非 PROV_/非 ROUND8 run_id 列挙）・#3:7350-7373（run_id の date/round ≠ event → historical 検出）・#5:7375-7384（disk/registry/queue 突合・候補数>disk数）・report 行は候補 regex `_CAND_RE` の構造上候補になれない（#6:7386-7387・non_2d_pending として別掲）。FAIL 1件でも critical:7767-7777 で Apply 中止 | `_post_apply_check` の ROUND8 only:7437-7446 | **実効**（fail-closed・DB 無変更で中止）。残穴 = nested tier の event 内フォルダに紛れた event 外 .MES（P0穴③）は folder 名メタで PASS し得る → 「見覚えのない outing 名で停止」の運用を併用 |
| **5. canonical 変化** | `_preapply_gate` #7:7389-7396（`_canonical_round_counts`:7182 で runs/laps/lap_suspension の ROUND8 行 >0 → FAIL・停止指示文言入り）+ 🏁 Status の canonical_round8 表示 | `_post_apply_check` の canonical unchanged:7418-7423（`_all_counts`:7204 の before/after 比較）+ PROV/DONINGTONPARK 汚染検査 | **実効**（事前・事後の二重検査） |

**付録A 結論**: ケース 2-5 は既存 Workbench の fail-closed 機構（`_preapply_gate` / 確認ダイアログ /
`_post_apply_check` / 🏁 Status / 🛡 Safety Audit `_run_safety_audit`:7493）で誤検知でなく実際に P0 穴を防ぐ。
**ケース 1 のみ事前検出が構造的に不完全**（expected delta が衝突時も一致する）ため、
「同一 session の既存 run がある状態で同 session の新規候補が出たら Apply 前に必ず停止」を
**運用ルールとして先回り**する。恒久修正は B-3（P0-2: run_no 決定論採番 + 既存 run_id 衝突 = FAIL）。

## 付録B: 監査クエリの再現条件

- 接続: `sqlite3.connect("file:ts24_unified.db?mode=ro", uri=True)`・SELECT のみ。
- ROUND8/historical の分離は `import_queue JOIN source_file_registry ON file_id` の `file_path LIKE '%ROUND8%'`。
- provenance 照合は `runs_provisional.source_manifest_hash = source_file_registry.sha256` の EXISTS 件数。
