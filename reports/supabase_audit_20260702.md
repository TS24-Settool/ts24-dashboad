# Supabase Audit — 20260702

read-only 監査（local SELECT / remote GET のみ）。自動削除・自動 sync なし。

- local 正本: `02_DATABASE/ts24_unified.db`
- local 投影: `sync_to_supabase.py` と同一ロジック（生テーブル直比較ではない）
- 自然キー: CLAUDE.md §1c / NULLS NOT DISTINCT 正規化

## サマリ

| table | local | remote(uniq) | remote(total) | remote_extra | missing | remote/local |
|---|---:|---:|---:|---:|---:|---:|
| race_results | 866 | 866 | 866 | 0 | 0 | 1.00 |
| lap_times | 7613 | 7613 | 7613 | 0 | 0 | 1.00 |
| sessions_2d | 246 | 259 | 259 | 13 | 0 | 1.05 |
| lap_times_2d | 1202 | 1213 | 1213 | 11 | 0 | 1.01 |

## race_results

- 自然キー: `round_no, circuit, session_type, rider_no, position`
- local 投影行(raw): 866 / dedup 後キー: 866
- remote uniq キー: 866 / remote 総数(header): 866
- **remote_extra**（online のみ・cleanup 候補）: 0
- **missing**（local のみ・再 sync 候補／削除しない）: 0

## lap_times

- 自然キー: `round_id, circuit, session_type, rider_num, lap_no`
- local 投影行(raw): 7613 / dedup 後キー: 7613
- remote uniq キー: 7613 / remote 総数(header): 7613
- **remote_extra**（online のみ・cleanup 候補）: 0
- **missing**（local のみ・再 sync 候補／削除しない）: 0

## sessions_2d

- 自然キー: `round, circuit, session_type, rider, run_no, date`
- local 投影行(raw): 246 / dedup 後キー: 246
- remote uniq キー: 259 / remote 総数(header): 259
- **remote_extra**（online のみ・cleanup 候補）: 13
- **missing**（local のみ・再 sync 候補／削除しない）: 0

remote_extra サンプル（最大 20）:

```text
 | JEREZ | TEST1_DAY1 | DA77 | 1 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 2 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 3 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 4 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 5 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 6 | NULL
 | JEREZ | TEST1_DAY1 | DA77 | 7 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 1 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 2 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 3 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 4 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 5 | NULL
 | JEREZ | TEST1_DAY2 | DA77 | 6 | NULL
```

## lap_times_2d

- 自然キー: `round, circuit, session_type, rider, run_no, lap_no, date`
- local 投影行(raw): 1202 / dedup 後キー: 1202
- remote uniq キー: 1213 / remote 総数(header): 1213
- **remote_extra**（online のみ・cleanup 候補）: 11
- **missing**（local のみ・再 sync 候補／削除しない）: 0

remote_extra サンプル（最大 20）:

```text
ROUND1 | PHILLIPISLAND | RACE1 | DA77 | 1 | 1 | 20260220
ROUND1 | PHILLIPISLAND | RACE1 | JA52 | 1 | 1 | 20260220
ROUND1 | PHILLIPISLAND | RACE1 | JA52 | 2 | 1 | 20260220
ROUND1 | PHILLIPISLAND | RACE2 | DA77 | 1 | 1 | 20260220
ROUND1 | PHILLIPISLAND | RACE2 | JA52 | 1 | 1 | 20250221
ROUND1 | PHILLIPISLAND | RACE2 | JA52 | 1 | 1 | 20260220
ROUND3 | ASSEN | RACE1 | DA77 | 1 | 1 | 20260425
ROUND5 | MOST | RACE1 | DA77 | 1 | 1 | 20260515
ROUND5 | MOST | RACE1 | JA52 | 1 | 1 | 20260515
ROUND5 | MOST | RACE2 | DA77 | 1 | 1 | 20260515
ROUND5 | MOST | RACE2 | JA52 | 1 | 1 | 20260515
```

## 総評

- remote_extra 合計: 24（cleanup 提案 = `cleanup_proposal_20260702.sql`）
- missing 合計: 0（`sync_to_supabase.py` 再実行で解消。**削除ではない**）
- cleanup SQL は提案のみ。SELECT で確認してから Tatsuki が Supabase 上で手動実行する。
