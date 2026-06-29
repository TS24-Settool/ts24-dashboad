# ROUND7 race_results 反映 dry-run — 2026-06-29 14:15

**dry-run（正本DB `mode=ro`・無変更）**。`apply_round7_race_results.py`（`--apply` 無し）。
非RACE 候補ポリシー: TS24 チーム(#77/#52)のみ（既存慣行）。
自然キー（ローカル UPSERT）= (round, session_type, rider_num)（`apply_pdf_positions_v2.py` と同一）。

## 1. 投入候補サマリ

- 候補総数: **74 行**

| session | 候補rider数 |
|---|---:|
| FP | 2 |
| QP | 2 |
| RACE1 | 33 |
| RACE2 | 33 |
| WUP1 | 2 |
| WUP2 | 2 |

## 2. session×rider 候補（抜粋: TS24 #77/#52）

| session | rider | pos | laps | best_lap_s | date |
|---|---:|---:|---:|---:|---|
| FP | #77 | 17 | 17 | 98.044 | 2026-06-12 |
| FP | #52 | 19 | 16 | 98.37 | 2026-06-12 |
| QP | #77 | 18 | 18 | 97.433 | 2026-06-12 |
| QP | #52 | 19 | 16 | 97.648 | 2026-06-12 |
| RACE1 | #77 | 13 | 18 | 97.988 | 2026-06-12 |
| RACE1 | #52 | 14 | 18 | 98.061 | 2026-06-12 |
| RACE2 | #52 | 5 | 18 | 97.793 | 2026-06-12 |
| RACE2 | #77 | 13 | 18 | 97.942 | 2026-06-12 |
| WUP1 | #52 | 20 | 5 | 98.107 | 2026-06-12 |
| WUP1 | #77 | 23 | 5 | 98.303 | 2026-06-12 |
| WUP2 | #77 | 15 | 6 | 97.928 | 2026-06-12 |
| WUP2 | #52 | 16 | 6 | 98.034 | 2026-06-12 |

## 3. Quality Gate（投入前検査）

| 検査 | 結果 | 判定 |
|---|---:|:--:|
| 自然キー重複（候補内）| 0 | ✅ |
| 既存 race_results 衝突（ROUND7）| 0 | ✅ |
| 必須キー NULL（round/circuit/session/rider）| 0 | ✅ |
| date NULL | 0 | ✅ |
| best_lap_s NULL | 0 | ✅ |
| best_lap_s 物理レンジ外([80.0,130.0]) | 0 | ✅ |
| 型不正（rider_num/best_lap_s）| 0 | ✅ |
| RACE: race_results best ≠ lap明細 best | 0 | ✅ |

## 4. 既存 race_results との差分

- ROUND7 既存行（非COMPANY）= 0（0 なら全候補が新規 INSERT）。
- 反映は自然キー UPSERT（COALESCE）。既存があれば position/best/laps/name 等を None で潰さず更新。

## 5. apply 時 SQL / UPSERT 方針

```sql
-- 既存あり: UPDATE ... COALESCE(new, existing) WHERE round=? AND session_type=? AND rider_num=?
-- 既存なし: INSERT INTO race_results(round,circuit,session_type,date,position,rider_num,
--           rider_name,laps,best_lap,best_lap_s,source_file,data_scope='TS24_PRIVATE')
```
- 自然キー = (round, session_type, rider_num)。COMPANY(BSB) とは衝突しない（ROUND7=MISANO のみ）。

## 6. rollback 方針

- 事前に正本DB をフルコピー（`02_DATABASE/_backup_round7_rr_<TS>/`）。
- apply は単一トランザクション。**runs/laps/lap_suspension/pdf_lap_times が before==after でなければ rollback**。
- 失敗時は backup から差し戻し。INSERT のみ（COALESCE UPDATE）で既存良データを破壊しない。

## 7. 正本DB業務テーブル（dry-run: 無変更を確認）

| table | before | after | 不変 |
|---|---:|---:|:--:|
| runs | 275 | 275 | ✅ |
| laps | 1202 | 1202 | ✅ |
| lap_suspension | 1202 | 1202 | ✅ |
| race_results | 792 | 792 | ✅ |
| pdf_lap_times | 7613 | 7613 | ✅ |

## Multi-agent operating check（CLAUDE.md §1/§20・PROJECT_RULES・decision records 照合）

§20 の 6 エージェント（Extraction=測る / Quality Gate=疑う / DB Integration=保存 / Case Search=探す / Hypothesis=考える / Supervisor=止める）＋ Tatsuki=決める、§1 の役割境界に照らした自己点検。

| 役割 | 本タスクでの担当・成果物 | 状態 |
|---|---|---|
| Codex / Handoff | Obsidian 最新状態確認・方針整理・Code 指示・承認境界明示（INBOX/handoff/log） | ✅ 別エージェント(Codex)が実施 |
| Claude Code / Implementation | dry-run helper `apply_round7_race_results.py`・既存資産再利用・git 差分管理・ローカルコミット | ✅ 本タスク |
| Extraction agent（測る） | ROUND7 6 PDF → race_results 候補抽出（`extract_pdf`・MISANO 対応） | ✅ 本レポート §1-2 |
| Quality Gate agent（疑う） | 自然キー重複・既存衝突・NULL/型/物理レンジ・RACE best/laps 整合・既存無回帰 | ✅ 本レポート §3 |
| DB Integration agent（保存） | UPSERT(自然キー+COALESCE)・rollback・before/after・write 境界設計（apply は未実行） | ✅ 設計のみ（apply 要承認） |
| Documentation / Handoff agent | `reports/`・`CLAUDE.md`・Obsidian log/handoff/current_state 更新 | ✅ 本タスク |
| Case Search / Hypothesis（探す/考える） | 本タスク範囲外（反映後の分析フェーズ） | – 未実施（スコープ外） |
| Supervisor（止める） | write apply を承認境界で停止・2D 不在値の作成禁止を明示 | ✅ 本タスクは dry-run で停止 |
| Tatsuki / 決める | race_results write apply の承認 | ⏳ 承認待ち |

**所見**: 抽出・品質ゲート・統合設計・文書化・停止（承認境界）は成果物上で満たされている。Case Search/Hypothesis は反映後フェーズのため未実施（正常）。実 write は Tatsuki 承認後。

## 8. race_results 反映後に再実行する手順

1. `python3 pdf_v2_scratch_gate.py --all` を再実行 → ROUND7 RACE が真値を得て PASS/WARNING/FAIL 判定可能に。
2. `python3 apply_pdf_v2_staging.py`（dry-run）で ROUND7 RACE PASS 行が staging 候補に入るか確認。
3. 問題なければ（別承認）staging / VIEW / Workbench 切替へ。

## 9. Tatsuki 承認後に実行するコマンド（案）

```bash
python3 apply_round7_race_results.py --apply     # ROUND7 race_results 反映（非対象業務テーブル不変 assert）
python3 pdf_v2_scratch_gate.py --all             # race_results 反映後に Gate 再実行
```

> `--apply` は **race_results（業務テーブル）への書込**＝要 Tatsuki 承認。runs/laps/lap_suspension/pdf_lap_times は不変。2D 取込・staging apply・VIEW・Workbench・Supabase・push は別タスク。