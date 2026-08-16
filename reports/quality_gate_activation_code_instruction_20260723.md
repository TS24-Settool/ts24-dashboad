# Quality Gate Activation — Code実装指示

Date: 2026-07-23  
Priority: P0  
Objective: TS24のL0自動監査とL2 Reviewer諮問を、実ジョブでfail-closedに運用可能にする。

## Codexが完了した基盤

- `gate/run_gate.py`: 非破壊checkpoint、L0実行、JSON証跡、restore-plan。
- `gate/golden_cases.yaml`: baseline 3件とRound8実害由来Golden候補3件。
- `gate/reviewer_prompt.md`: Reviewerの固定出力契約。
- `gate/tests/test_run_gate.py`: 判定・安全実行・status parser等10件。
- `gate/check_syntax.py`: `__pycache__`を書かない構文検査。
- `.gate/`: `.gitignore`済み。監査証跡以外の場所へ自動書込しない。

基盤検証: gate runner 10/10 PASS、既存lap-analysis 41/41 PASS、critical module syntax PASS、PyYAML等の追加依存なし。

## Codeが実施する作業

### 1. checkpoint基準の厳密なjob差分

現状の `capture_job_diff()` はHEAD差分とcheckpoint dirty pathsを保存する基盤段階。L2へ渡す「今回のBuilder差分」にするため次を実装する。

1. checkpoint時点でdirtyだったpathは保存済snapshotをbaseにする。
2. cleanだったtracked pathはcheckpoint HEAD blobをbaseにする。
3. checkpoint後の新規untracked pathは不存在をbaseにする。
4. staged / unstaged / untracked / rename / delete / binaryを含むjob-scoped patchとchanged pathsを生成する。
5. checkpointより前の変更を混入させない。
6. baseを再構成できないpathがあれば `NOT_READY`。

fixture用一時git repoでpre-existing dirty変更とjob変更が分離されるテストを作る。production DBや実データで試験しない。

### 2. Golden Evalの実装と有効化

最低限 `GE-TS24-001` を実害fixtureで実装し `enabled: true` にする。

- diskに新規2D outingが存在
- registry/queueには存在しない
- candidate countは0
- 「成功/新規なし」に見せず、unregistered disk outingと復旧導線を明示

可能なら同一作業内で以下も実装・有効化する。

- `GE-TS24-002`: 時間差到着する同session outingでもrun identityが決定論的。同内容はno-op、異内容衝突はwrite前FAIL。
- `GE-TS24-003`: Donington全aliasがprovisional/final双方で`DONINGTON`になる。

単なる関数存在確認、常時PASS mock、期待値緩和は禁止。

### 3. L2 review packet

`JOB-xxxx`ごとに次の3点だけをReviewerへ渡すpacket builderを追加する。

1. immutable requirements snapshot（Objective / Scope / Do Not / Acceptance）
2. checkpoint基準job-scoped git diff
3. `.gate/JOB-xxxx.json`

Builderの説明、自己評価、完了報告は入れない。requirementsまたはdiff欠落時は `NOT_READY`。

### 4. fail-closed E2E

一時git repo / fixture / scratch DBだけで以下を自動検証する。

- baseline FAIL → `REJECTED`
- Golden FAIL → `BLOCKED`
- enabled Golden 0件 → `NOT_READY`
- requirements欠落 / diff再構成不能 → `NOT_READY`
- 全L0 PASS + packet完備 → `READY_FOR_L2`
- L2はL0 verdictを書き換えられない
- silent failureを正常終了扱いにしない
- runner前後でgit HEAD、index、refs、既存worktree内容が不変
- `git add/stash/tag/reset/checkout/clean`、DB overwrite、外部送信を実行しない

### 5. 運用資料

- Runbook（checkpoint → build → run → L2 → 人間判断）
- JOB requirements記入例
- `.gate/JOB-xxxx.json` schema
- 手動rollback手順（自動restoreは禁止）
- `reports/quality_gate_activation_apply_20260723.md`
- `CLAUDE.md`、Obsidian `log.md`、`CURRENT_STATE.md`、`AI_HANDOFF_LATEST.md`

## Acceptance

- 上記E2E全PASS。
- 少なくともGE-TS24-001が実事故fixtureで有効。
- L2 packetが指定3入力だけで再現可能。
- checkpoint前のdirty変更がjob diffへ混入しない。
- production DB / Original workbook / Workbench runtime dataはbefore==after。
- 曖昧な状態は必ず `NOT_READY`。

## Do Not

- L0結果のoverride。
- production DB、Original、Supabase、AWS、Workbenchデータへの書込。
- Goldenの仕様緩和、期待値書換え、skip化。
- Builder説明をReviewerへ渡すこと。
- 自動rollback、破壊的git操作、commit、push、external transmission。

## Result記入

変更ファイル、全テスト結果、Goldenの事故再現内容、before/after不変証跡、既知制限、rollback planを記録する。Acceptance未達を「完了」としない。
