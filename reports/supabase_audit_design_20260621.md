# Supabase Audit Script 設計書

**作成:** 2026-06-21 / Claude Code（Tatsuki指示・次作業候補の設計）
**ステータス:** 設計（DESIGN ONLY）。実装着手は Tatsuki 承認後。
**位置づけ:** local 正本 `ts24_unified.db` と Supabase（オンライン）の整合監査。Phase 2 の「自動で疑う」思想の延長。

---

## 0. 目的と鉄則

local `02_DATABASE/ts24_unified.db` と Supabase の **件数・自然キー差分を読み取り専用で比較**し、
- **remote extra**（Supabase にあって local に無い行）
- **missing**（local にあって Supabase に無い行）
を抽出、**cleanup SQL 案を生成**する。

**鉄則（厳守）:**
- **local は SELECT のみ・remote は GET のみ。** どちらにも書き込まない。
- **自動削除しない・自動 sync しない。** cleanup は SQL 案（`.sql`）として出力するだけ。実行は Tatsuki が Supabase 上で手動。
- 監査スクリプトが書き込んでよいのはローカルの **レポート(.md)と提案(.sql)** のみ（任意で local 管理テーブルへの監査ログ=将来）。
- **TS24 DB Master.xlsx は派生物**であり比較の正本ではない。比較の local 正本は常に `ts24_unified.db`。
- 差分は「提示」する。判断は Tatsuki（「疑う」役。AI は削除を決めない）。

---

## 1. 接続・認証（既存と同一）

- 認証元: `05_SCRIPTS/ts24_config.json` の `supabase_url` / `supabase_service_key`（`sync_to_supabase.py` と同一）。
- 方式: Supabase **PostgREST**（`{SUPABASE_URL}/rest/v1/{table}`）。ヘッダ `apikey` + `Authorization: Bearer <service_key>`。
- 監査は **GET のみ**使用（`sync_to_supabase.py` の POST/upsert は使わない）。
- `requests` 依存（既存と同様。無ければ pip 導入）。

---

## 2. 監査対象テーブルと自然キー（§1c 準拠）

| Supabase テーブル | local 源テーブル | 自然キー（= UNIQUE INDEX / 比較キー） |
|---|---|---|
| `race_results` | `race_results` | round_no, circuit, session_type, rider_no, position |
| `lap_times` | `pdf_lap_times` | round_id, circuit, session_type, rider_num, lap_no |
| `sessions_2d` | `runs` | round, circuit, session_type, rider, run_no, **date** |
| `lap_times_2d` | `laps` | round, circuit, session_type, rider, run_no, lap_no, **date** |

- Supabase 側 UNIQUE INDEX は `NULLS NOT DISTINCT`（§1c）。**キーに NULL を含む行**の同一判定は
  「NULL 同士を等しい」とみなす（PostgREST/SQL の既定 NULL 挙動と異なるため後述の差分・DELETE で明示対応）。

---

## 3. local 投影は sync と同一ロジックを使う（apples-to-apples）

**重要:** Supabase の各テーブルは local の**生テーブルそのものではなく**、`sync_to_supabase.py` の SELECT で
**変換投影**された行（例: `lap_times` ← `pdf_lap_times`、`sessions_2d` ← `runs`、`lap_times_2d` ← `laps`）。
監査で local 側のキー集合を作るときは、**`sync_to_supabase.py` と同じ投影 SELECT を再利用**して
「sync されるべき行集合」を再現する（生テーブルを直接数えると別物になり偽差分が出る）。

- 実装方針: `sync_to_supabase.py` の各テーブルの行ビルダ（121-134 race_results / 151-163 lap_times /
  175-197 sessions_2d / 218-233 lap_times_2d）を **import 再利用** するか、同等 SELECT を監査側に共通定数として持つ。
  前者を優先（二重管理を避ける）。sync 側を関数化（`build_<table>_rows(conn)`）してから両者で共有するのが理想。
- local キー集合 = 投影行から自然キー列だけを取り出した tuple の集合。重複は sync の conflict 解決と同じく
  「同一キーは1行」に正規化（NULLS NOT DISTINCT 同様の正規化）。

---

## 4. remote 読み取り（GET のみ・ページング）

- 各テーブルにつき自然キー列のみ取得: `GET /rest/v1/{table}?select=<key cols join ','>`。
- **総件数**: `Prefer: count=exact` ヘッダ → レスポンス `Content-Range: 0-N/total` の total を読む。
- **全キー取得**: PostgREST は既定 1000 行上限。`Range: 0-999`, `1000-1999`, … とページング（`Range-Unit: items`）。
  または `?limit=1000&offset=…`。レート/タイムアウトに配慮（batch 1000、retry/backoff）。
- 取得したキー列から remote キー tuple 集合を構築（NULL は専用センチネルへ正規化して NULLS NOT DISTINCT を再現）。

---

## 5. 差分アルゴリズム

各テーブルで:
1. `local_keys`（§3）と `remote_keys`（§4）の tuple 集合を構築。NULL は `("\x00NULL")` 等のセンチネルへ正規化。
2. `remote_extra = remote_keys − local_keys`（Supabase にあって local に無い → cleanup 候補）。
3. `missing = local_keys − remote_keys`（local にあって Supabase に無い → 再 sync 候補。**削除対象ではない**）。
4. `count_local / count_remote / |extra| / |missing|` を集計。**件数比**（remote/local）も出す（§1c の肥大検知）。
5. サンプル（各 top N）を提示。全件は付随 JSON/CSV に出力可。

---

## 6. 出力（書き込みはローカルファイルのみ）

`reports/supabase_audit_<YYYYMMDD-HHMMSS>/` 配下に:

1. **`audit_report.md`**: テーブル別の count_local / count_remote / extra / missing / 件数比、サンプル、総評。
2. **`cleanup_proposal.sql`**: **remote_extra のみ**の DELETE 案（手動実行用・コメントで件数と前提を明記）。
   - 形式（NULLS NOT DISTINCT 対応のため `IS NOT DISTINCT FROM` を使用）:
     ```sql
     -- TABLE race_results: remote_extra N 件（local 投影に存在しないオンライン行）
     -- 実行前に必ず SELECT で確認すること。自動実行禁止。
     DELETE FROM race_results
     WHERE round_no IS NOT DISTINCT FROM :v1 AND circuit IS NOT DISTINCT FROM :v2
       AND session_type IS NOT DISTINCT FROM :v3 AND rider_no IS NOT DISTINCT FROM :v4
       AND position IS NOT DISTINCT FROM :v5;   -- ×N（または VALUES IN バッチ）
     ```
   - 大量時は `... WHERE (k1,k2,..) IN (VALUES (...),(...))` のバッチ形式（NULL を含むキーは個別 DELETE に退避）。
   - 先頭に「SELECT で確認 → 手動実行」の手順コメント、件数サマリ、対応 audit 実行 ID を記載。
3. **`missing_resync.md`**（任意）: missing 件の一覧と「`sync_to_supabase.py` 再実行で解消」の案内（削除ではない）。

**任意（将来）**: 監査結果を local 管理テーブルへ記録（`analysis_run_log` に1 run、`data_quality_log` に
`audit_count_diff` / `audit_remote_extra` / `audit_missing` を `WARNING`）。これは管理テーブルのみで業務テーブル不変。

---

## 7. 安全性・誤検出対策（疑う）

- **読み取り専用の保証**: HTTP は GET のみ。local は SELECT のみ。コード上 POST/PUT/PATCH/DELETE を一切持たない。
- **偽差分の回避**:
  - local 投影は必ず sync と同一ロジック（§3）。生テーブル直比較は禁止。
  - NULLS NOT DISTINCT を両側で正規化（§5）。
  - `date` を含むキー（sessions_2d / lap_times_2d）は **シーズン跨ぎ衝突回避のため必須**（§1c）。フォーマット差（ISO/локаль）を正規化。
  - float/桁の表現差はキーに含めない（キーは識別列のみ）。値比較は本監査のスコープ外（件数・キーの存在差のみ）。
- **cleanup は提案のみ**: スクリプトは DELETE を実行しない。`.sql` は「SELECT 確認 → 手動」を強制するコメント付き。
- **冪等**: 監査は何度実行しても副作用なし（出力ディレクトリのみ増える）。

---

## 8. CLI（案）

```
python3 supabase_audit.py                 # 全4テーブル監査 → reports/supabase_audit_<ts>/
python3 supabase_audit.py --table race_results
python3 supabase_audit.py --emit-sql      # cleanup_proposal.sql も生成（既定: 生成）
python3 supabase_audit.py --no-sql        # レポートのみ
python3 supabase_audit.py --sample 20     # サンプル件数
```
- 終了コード: 差分ゼロ=0 / 差分あり=2（CI/定期監査で検知可能、ただし削除はしない）。

---

## 9. 未決事項 / Tatsuki 確認

1. local 投影は `sync_to_supabase.py` を関数化して共有してよいか（推奨。二重管理回避）。
2. cleanup SQL のバッチ形式（個別 DELETE / VALUES IN）の既定。
3. 監査結果の local 管理テーブル記録（`analysis_run_log`/`data_quality_log` audit_*）を採用するか。
4. missing（local にあって remote に無い）の扱い: 再 sync 案内のみで良いか（削除はしない前提）。
5. 値レベル監査（同一キーで値が違う行の検出）を将来スコープに含めるか（本設計は件数・キー存在差のみ）。

---

## 10. スコープ外（本書では扱わない）

- 実装コード（本書は設計のみ）。
- 自動削除・自動 sync・Supabase スキーマ変更。
- 値レベル（数値差）の照合。
- Phase 2B / Gate / 正本業務テーブル反映（別フェーズ・未開始）。
