# CLAUDE.md — TS24 Project Team Shared Context
**Project:** TS24 SET-UP TOOL / Puccetti Racing WorldSSP Suspension Management System
**Last Updated:** 2026-04-29
**Read this file at the start of every session — Claude Code and Cowork Claude both.**

---

## 1. チームとその役割

このプロジェクトは3者チームで運営される。

| メンバー | 役割 | 主な責任 |
|---------|------|---------|
| **Tatsuki Suzuki（鈴木達樹）** | チームマネージャー / データ収集 | MESデータ収集・現場フィードバック・最終意思決定 |
| **Claude (Cowork)** | データ分析 / ソリューション提示 | ダッシュボード上でのリアルタイム分析・セットアップ提案・知見の蓄積 |
| **Claude Code** | システム管理 / ダッシュボード維持 | dashboard.py更新・データ処理・Git管理・スクリプト実行 |

**重要:** CoworkとClaude Codeは直接通信できない。このファイル（CLAUDE.md）と `race_memory.json` が共有の文脈として機能する。作業前に必ずこのファイルを読むこと。

---

## 2. プロジェクト概要

- **チーム:** Puccetti Racing（プチェッティ・レーシング）
- **バイク:** Kawasaki ZX-636（WorldSSP）
- **ライダー:** DA77（ダ77）・JA52（ジャ52）
- **シーズン:** TS24（2025-10 ～ 2026 継続中）
- **ダッシュボード:** https://ts24-dashboad-3gf7gbyieajua9ygq9f8rr.streamlit.app
- **GitHubリポジトリ:** https://github.com/TS24-Settool/ts24-dashboad

---

## 3. フォルダ構造

```
~/Desktop/Data TS24 Claude/          ← iCloud同期済み
├── 01_REPORTS/
│   ├── DA77/                        ← DA77イベントレポート (.xlsx)
│   └── JA52/                        ← JA52イベントレポート (.xlsx)
├── 02_DATABASE/
│   ├── TS24 DB Master.xlsx          ← メインDB（Excel）
│   ├── ts24_setup.db                ← SQLite（sessions / tags / race_results）
│   └── all_sessions.json            ← セッションJSONキャッシュ
├── 03_TEMPLATES/                    ← イベントレポートテンプレート
├── 04_REFERENCE/
│   ├── TS24_Knowledge_Base.md       ← サスペンション理論・ZX-636知識（必読）
│   └── TS24_System_Architecture.md ← システム設計書
├── 05_SCRIPTS/                      ← Claude Codeが主管するディレクトリ
│   ├── CLAUDE.md                    ← このファイル（必読）
│   ├── dashboard.py                 ← Streamlitダッシュボード（本体）
│   ├── parse_2d_channels.py         ← MESデータ解析（APEX検出アルゴリズム）
│   ├── lap_suspension_stats.py      ← ラップサスペンション統計生成
│   ├── lap_suspension_data.json     ← 615行・34列（Streamlit Cloud用）
│   ├── dynamics_data.json           ← DYNAMICS_ANALYSIS（Streamlit Cloud用）
│   ├── lap_times_data.json          ← ラップタイムデータ
│   ├── race_memory.json             ← 【重要】AI分析知見の蓄積ファイル
│   ├── git_push_fix.command         ← GitHubプッシュスクリプト（手動実行）
│   └── run_full_analysis.command    ← 全データ再処理スクリプト
└── 04_MES/                          ← MES生データ（2Dロガー出力）
    └── [RIDER]/[DATE]/              ← ライダー別・日付別
```

---

## 4. 技術アーキテクチャ

### 4.1 データフロー

```
MES生データ（.MES）
    ↓ parse_2d_channels.py
    ↓ lap_suspension_stats.py
lap_suspension_data.json  →  dashboard.py（Streamlit Cloud）
dynamics_data.json        →
lap_times_data.json       →
    ↑
ts24_setup.db（SQLite）   →  sessions / tags / race_results テーブル
```

### 4.2 主要JSONファイル（Streamlit Cloud用）

| ファイル | レコード数 | 主要列 | 更新タイミング |
|---------|-----------|--------|---------------|
| `lap_suspension_data.json` | 615行・34列 | THRON_SUSF_AVG, BRK_SUSF_AVG, APEX_SPD_AVG | MES再処理時 |
| `dynamics_data.json` | ラップ単位 | ACC_Y_PEAK, BOFF_SUSF, THRON_SUSF | MES再処理時 |
| `lap_times_data.json` | セッション単位 | best_lap, rider, circuit, date, run_no | セッション登録時 |

### 4.3 データベース（SQLite）

```sql
-- 主要テーブル
sessions      -- セッション基本情報
tags          -- 問題タグ（chattering_brake等）
race_results  -- 公式レース結果
```

### 4.4 Streamlit Cloud設定

- **デプロイ:** GitHub mainブランチへのpushで自動デプロイ（約1〜2分）
- **Secrets:** Anthropic APIキー・Supabase URLはst.secretsで管理
- **データ読込:** JSONファイルをキャッシュ（`@st.cache_data(ttl=120)`）

---

## 5. APEX定義システム（最重要）

**現在の方針 (2026-04-30 チーム確定):**
APEX Area = BRAKE_FRONT -0.6~0.3Bar ∩ GAS 0~6% ∩ dTPS_A 5~50 ∩ SUSP_F 20~140mm ∩ SUSP_R 5~50mm
5条件が同時成立する区間の平均をAPEX値とする。旧ACC_Y/BRAKE_OFF/THR_ON定義は廃止。

| チャンネル | 条件 | サンプルレート比 |
|-----------|------|----------------|
| BRAKE_FRONT | -0.6 〜 0.3 Bar | 1x（基準） |
| GAS | 0.0 〜 6.0 % | 2x |
| dTPS_A | 5.0 〜 50.0 | 2x |
| SUSP_FRONT | 20.0 〜 140.0 mm | 4x |
| SUSP_REAR | 5.0 〜 50.0 mm | 4x |

**フォールバック:** dTPS_Aチャンネルが存在しない古いMESファイルは旧THR_ON定義で検出。

### APEX検出アルゴリズム（parse_2d_channels.py）

```python
# detect_apex_area(): 5条件マスクを生成 → 連続区間を抽出 → マージ → 代表値計算
# ラップ区間をbrake_fレートでスライス → GAS/dTPS_Aは2x → SUSP_F/Rは4xにマップ
# dTPS_A未搭載ファイル: has_dtps=False → 旧THR_ON方式にフォールバック
```

### 出力列（後方互換）
- `APEX_SUSF_AVG` / `THRON_SUSF_AVG` → 新APEX定義の値（同値）
- `BOFF_SUSF_AVG` → None（廃止、列のみ保持）

---

## 6. ダッシュボード（dashboard.py）構成

### ページ一覧と役割

| ページ | 役割 | 主なデータソース |
|-------|------|----------------|
| Problem Analysis | 問題タグ頻度・位相分布 | SQLite tags |
| Heatmap | サーキット×フェーズのヒートマップ | SQLite tags |
| Season Trend | シーズン推移 | SQLite sessions |
| Race Results | 公式結果 | SQLite race_results |
| Race Pace | ペース分析 | SQLite |
| Lap Analysis | ラップタイム分析 | SQLite |
| 2D Lap Data | MESラップデータ可視化 | lap_suspension_data.json |
| Suspension Dynamics | APEX/Braking/PitLimiter可視化 | dynamics_data.json |
| Lap Sus Stats | ラップ統計・APEX比較 | lap_suspension_data.json |
| **Setup Target** | FAST/SLOW比較・Δ分析 | lap_suspension_data.json + lap_times_data.json |
| Session Detail | セッション詳細 | SQLite |
| Trend Analysis | シーズントレンド | SQLite |
| Problem→Solution | 問題→解決策DB | SQLite |
| Performance | パフォーマンス分析 | SQLite |
| AI Advice | Claude AIセットアップ提案 | Claude API |
| Setup Chat | 通常チャット | Claude API |

### 重要な実装詳細

```python
# レイアウト: st.sidebar非使用、st.columns([1,5])でナビ+コンテンツ
_nav_col, _content_col = st.columns([1, 5], gap="small")

# フローティングチャット: st.components.v1.html(height=0)で親DOMに注入
# → URLもページ状態も変更しない、Streamlit rerun不要

# サーキット名正規化
_dyn_norm_circuit()  # WORKSHOP/AUSTRALIA → PHILLIP ISLAND など

# pandas 2.2+ 対策: groupby.apply非推奨 → 手動ループで代替
```

### UIスタイル（Power BIスタイル）

```python
# 背景色: #FFFFFF (白), グリッド: #E5E7EB
# アクセント: #0078D4 (Microsoft Blue)
# フォント: Arial, sans-serif
# ゼロライン: line_dash="dot", line_width=1.8
```

---

## 7. race_memory.json — 知見蓄積ファイル

**このファイルはCoworkとClaude Codeの共有記憶。**

```json
{
  "version": 2,
  "circuit_insights": {
    "PORTIMAO": {
      "DA77": ["[2026-04-29] THR_ON SusF consistently 3-5mm higher when fast"],
      "JA52": []
    }
  },
  "global_insights": [],
  "setup_learnings": [],
  "conversation_summaries": []
}
```

**Claude Code への指示:** 新しいMESデータを処理したとき、以下を `race_memory.json` に追記すること。

```json
// setup_learningsに追記するフォーマット
{
  "date": "YYYY-MM-DD",
  "circuit": "PORTIMAO",
  "rider": "DA77",
  "run_no": 3,
  "insight": "New MES data processed: 12 laps, THR_ON avg 42.3mm",
  "source": "auto_processing"
}
```

---

## 8. 重要な命名・コーディング規則

### データ列名

```
THRON_SUSF_AVG   ← THR_ON定義でのフロントサスペンション平均（mm）
THRON_SUSR_AVG   ← THR_ON定義でのリアサスペンション平均（mm）
BRK_SUSF_AVG     ← Braking Entry時のフロントサス（mm）
BRK_SUSR_AVG     ← Braking Entry時のリアサス（mm）
APEX_SPD_AVG     ← APEX通過速度（km/h）
THRON_CNT        ← THR_ON検出カウント（0の場合はデータなし）
```

### サーキット名正規化ルール

```python
"WORKSHOP"   → "PHILLIP ISLAND"
"AUSTRALIA"  → "PHILLIP ISLAND"
"ASSEN"      → "ASSEN"
"CREMONA"    → "CREMONA"
"JEREZ"      → "JEREZ"
"PORTIMAO"   → "PORTIMAO"
```

### ファイル命名規則（レポート）

```
20260417-ROUND3-DA77.xlsx   ← YYYYMMDD-EVENTTYPE-RIDER
```

---

## 9. ワークフロー（新レース/テスト後）

### Step 1: データ収集（Tatsuki）
1. MESファイルを `04_MES/[RIDER]/[DATE]/` に置く
2. レポートExcelを `01_REPORTS/[RIDER]/` に置く

### Step 2: データ処理（Claude Code）
```bash
# MES再処理
python lap_suspension_stats.py

# JSONエクスポート（Streamlit Cloud用）
# → lap_suspension_data.json を更新

# Git push
./git_push_fix.command
```

### Step 3: 分析（Cowork Claude + Tatsuki）
- ダッシュボードを開いてフローティングチャット（🤖）で対話
- Setup Target ページでFAST/SLOW差分を確認
- race_memory.json に知見が自動蓄積される

### Step 4: ソリューション実施（Tatsuki）
- 提案されたセットアップ変更を次のセッションで試す
- 結果をレポートに記録

---

## 10. 現在の技術的課題と優先事項

### 解決済み ✅
- pandas 2.2+ `groupby.apply` 非推奨 → 手動ループで対応
- Setup Target: データソースをdynamics → LAP_SUSPENSION (THR_ON) に変更
- フローティングチャット: URL変更によるページリセット問題 → DOM直接注入で解決
- APEXチャート: Power BIスタイルの散布図実装
- Δチャート: 折れ線+マーカー、サーキット間トレンド可視化

### 進行中 🔄
- フローティングチャットのFABボタン動作確認（DOM注入方式）
- race_memory.json の知見蓄積テスト

### 今後の優先課題 📋
1. **相関分析ページ:** サスペンション指標とラップタイムの相関係数可視化
2. **セットアップ変更効果検証:** 同一条件での前後比較の自動化
3. **race_memory.json活用:** Claude Codeが処理完了時に自動でinsightを追記
4. **Supabase同期の安定化:** 新レポートの自動クラウド同期

---

## 11. Claude Code への具体的な作業指示

**このプロジェクトをClaudeCodeで開くときは必ずこのファイルを最初に読め。**

### 作業前チェックリスト
- [ ] CLAUDE.md を読んだ
- [ ] `race_memory.json` に前回の知見があれば把握した
- [ ] `git status` で現在の差分を確認した

### dashboard.py を変更するとき
1. 変更前に `python -m py_compile dashboard.py` で構文チェック
2. 変更内容を `race_memory.json` の `setup_learnings` に記録
3. `git_push_fix.command` でpush（または `git add . && git commit -m "..." && git push`）

### 新しいMESデータを処理するとき
```bash
cd ~/Desktop/"Data TS24 Claude"/05_SCRIPTS
python lap_suspension_stats.py
# 完了後、race_memory.jsonに処理記録を追記
```

### Cowork Claude への引き継ぎが必要なとき
`race_memory.json` の `conversation_summaries` に以下を追記：
```json
{
  "date": "YYYY-MM-DD",
  "page": "system",
  "rider": "ALL",
  "circuit": "ALL",
  "summary": "Claude Code作業内容: [具体的な内容]"
}
```

---

## 12. Cowork Claude への作業方針

**ダッシュボードでTatsukiと分析をするときの優先順位:**

1. **現在のページのデータを見る** → フローティングチャットのコンテキストに現在ページ・サーキット・ライダーが注入される
2. **race_memory.jsonの過去知見を確認** → 同じサーキットの過去の発見を踏まえて回答
3. **具体的な数値で提案する** → 「フロントを硬くする」ではなく「THR_ON SusF の目標値を38→42mmに調整」
4. **Claude Codeへの作業依頼はTatsukiを通じて伝える** → 「次にClaude Codeを使うとき、dashboard.pyの〇〇を更新してもらってください」

---

*このファイルはプロジェクトの進化とともに更新する。*
*重要な決定・変更・発見は必ずここに反映すること。*
