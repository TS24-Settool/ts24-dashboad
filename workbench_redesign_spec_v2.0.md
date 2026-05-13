# Workbench Redesign Spec v2.0
**作成者:** Cowork Claude  
**作成日:** 2026-05-13  
**対象ファイル:** `ts24_workbench.py`, `ts24_unified.db`  
**実装担当:** Claude Code  
**優先度:** 最高 — 他の機能追加より先に実装すること

---

## 背景と目的

Workbench の本来の役割を再定義する。

```
❌ 旧理解: 2D Analyzerの代替グラフツール
✅ 正しい理解: Problem → Analysis → Decision → Result を閉じる記録・思考・検証ツール
```

現在 `problem_log` が 0 件なのは、記録のハードルが高すぎるから。
CSV を開かないと記録できない設計を根本から変える。

**設計原則:**
- Run を選ぶ → 問題を書く → 保存 を **30秒以内** で完結させる
- 波形・CSV は「後から紐付けるオプション」であり、記録の前提条件にしない
- DB に知見が蓄積されることが最優先

---

## DB 拡張（既存テーブルは変更禁止）

### 追加テーブル 1: `analysis_note`

```sql
CREATE TABLE IF NOT EXISTS analysis_note (
    note_id       TEXT PRIMARY KEY,          -- AN_{timestamp}
    problem_id    TEXT NOT NULL,             -- FK → problem_log.log_id
    run_id        TEXT,                      -- FK → runs.run_id（任意）
    rider         TEXT,
    circuit       TEXT,
    created_at    TEXT,
    updated_at    TEXT,
    -- 構造化フィールド
    hypothesis    TEXT,                      -- 仮説（何が原因か）
    evidence      TEXT,                      -- 根拠（データ・観察）
    evidence_laps TEXT,                      -- 紐付けラップID（JSON配列文字列）
    confidence    TEXT DEFAULT 'LOW',        -- HIGH / MED / LOW
    conclusion    TEXT,                      -- 結論・判断
    next_action   TEXT                       -- 次にすべきこと
);
```

### 追加テーブル 2: `result_validation`

```sql
CREATE TABLE IF NOT EXISTS result_validation (
    val_id              TEXT PRIMARY KEY,    -- RV_{timestamp}
    decision_id         TEXT NOT NULL,       -- FK → setup_decision_log.decision_id
    problem_id          TEXT,               -- FK → problem_log.log_id（任意）
    run_id_validated    TEXT,               -- 結果確認したラン
    rider               TEXT,
    circuit             TEXT,
    validated_at        TEXT,
    -- 評価
    performance_eval    TEXT,               -- IMPROVED / SAME / WORSE
    rider_eval          TEXT,               -- IMPROVED / SAME / WORSE
    final_eval          TEXT,               -- SUCCESS / PARTIAL / FAIL / UNKNOWN
    -- 数値
    lap_time_delta      REAL,               -- ラップタイム変化（秒）負=改善
    gap_to_teammate_delta REAL,             -- チームメイトとのギャップ変化
    -- テキスト
    reason_for_final    TEXT,               -- 最終評価の根拠
    notes               TEXT
);
```

### 追加テーブル 3: `knowledge_cases`

```sql
CREATE TABLE IF NOT EXISTS knowledge_cases (
    case_id         TEXT PRIMARY KEY,       -- KC_{timestamp}
    -- 問題定義
    circuit         TEXT,
    corner          TEXT,
    phase           TEXT,
    problem_tag     TEXT,
    symptom_desc    TEXT,                   -- 症状の詳細説明
    -- 条件（再現条件）
    condition_notes TEXT,                   -- どんな状況で発生するか
    sus_condition   TEXT,                   -- サスペンション状態のメモ（JSON）
    -- 解決策
    action_taken    TEXT,                   -- 実施したセットアップ変更
    result_summary  TEXT,                   -- 結果サマリー
    success_rate    REAL,                   -- 成功率（0.0〜1.0）
    -- 参照
    source_problem_ids TEXT,                -- 元の problem_log IDs（JSON配列）
    source_decision_ids TEXT,               -- 元の decision IDs（JSON配列）
    -- メタ
    rider           TEXT,                   -- NULL=両ライダーに適用
    created_at      TEXT,
    updated_at      TEXT,
    promoted_by     TEXT DEFAULT 'manual'   -- manual / auto
);
```

---

## UI 再設計

### タブ構成の変更

**現在:**
```
[波形] [Problem Log] [Setup Decision] [2D CSV] [Trend Analysis]
```

**新構成:**
```
[🏁 Run Browser] [⚡ Quick Log] [📋 Analysis] [🔧 Decision] [✅ Validation] [📚 Knowledge] [波形] [Trend]
```

---

## 実装詳細

### Tab 1: 🏁 Run Browser（全セッション一覧・Run選択ハブ）

**目的:** CSVを開かなくてもRunを選べるようにする。他タブの起点。

```
┌─ Run Browser ──────────────────────────────────────────────────────┐
│ フィルター: [Circuit▼] [Round▼] [Rider▼] [Session▼]  [🔍絞込]      │
├────────────────────────────────────────────────────────────────────┤
│ Round    Circuit    Date       Session   Rider  Run  Best Lap  Tier│
│ ROUND4   BALATON   2026-05-02  SP        DA77   R3   1:43.333  ● │
│ ROUND4   BALATON   2026-05-02  SP        DA77   R2   1:43.533  ● │
│ ...                                                                 │
├────────────────────────────────────────────────────────────────────┤
│ [選択したRunで問題記録 →]  [Analysis を見る →]  [Decision を見る →] │
└────────────────────────────────────────────────────────────────────┘
```

**実装ポイント:**
- `WorkbenchDB.get_runs()` で全 Run を取得して表示
- 行をダブルクリック or 選択してボタン押下 → 他タブへコンテキスト渡し
- 選択中 Run の情報を `self._selected_run_id` に保持（全タブ共通）
- Tier 列: FAST=緑、MED=黄、SLOW=赤のドット表示

---

### Tab 2: ⚡ Quick Log（最重要 — 30秒で記録完了）

**目的:** CSVも波形も不要で Problem Log を即時保存する。

```
┌─ Quick Problem Log ──────────────────────────────────────────────────┐
│  Run: [ROUND4_BALATON_SP_DA77_R3 ▼]  DA77 | BALATON | SP R3 | 1:43.333│
├──────────────────────────────────────────────────────────────────────┤
│  Problem Tag: [chattering_brake ▼]        Phase: [PH2 ▼]            │
│  Corner:      [T1 ▼]                      Severity: [HIGH ▼]        │
│  Lap No (任意): [____]                    Source: [OBSERVATION ▼]   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │ メモ（一言で、何が起きたか）                                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  [💾 保存 (Enter)]                        [クリア]                  │
├──────────────────────────────────────────────────────────────────────┤
│  このRunの記録済み問題:                                               │
│  #1  chattering_brake / T1 / PH2 / HIGH                             │
│  #2  understeer_exit / T3 / PH45 / MED                              │
│     [→ Analysis Note を書く]  [→ Setup Decision に繋げる]           │
└──────────────────────────────────────────────────────────────────────┘
```

**実装ポイント:**
- Run コンボは `get_runs()` でDB全件から選択（CSV不要）
- Problem Tag, Phase, Corner, Severity は固定リストのコンボ
- **Enter キーで保存** できること（マウス不要）
- 保存後、下部テーブルを即時更新
- 下部テーブルの各行に [→ Analysis] [→ Decision] ボタン

**Problem Tag リスト（固定）:**
```python
PROBLEM_TAGS = [
    "chattering_brake", "chattering_accel", "chattering_corner",
    "understeer_entry", "understeer_apex", "understeer_exit",
    "oversteer_entry", "oversteer_exit",
    "front_feeling_loss", "rear_feeling_loss",
    "rear_highside_risk", "front_tuck_risk",
    "bottoming_front", "bottoming_rear",
    "harsh_braking", "instability_braking",
    "tyre_overheating_front", "tyre_overheating_rear",
    "other"
]
```

---

### Tab 3: 📋 Analysis Note（仮説・根拠・結論の構造化記録）

**目的:** Quick Log で記録した問題に対して、エンジニアの思考を構造化して保存。

```
┌─ Analysis Note ──────────────────────────────────────────────────────┐
│  Problem: [chattering_brake - T1 - PH2 - ROUND4 SP R3 ▼]            │
├──────────────────────────────────────────────────────────────────────┤
│  仮説 (Hypothesis):                                                    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ ブレーキング時のフロント荷重過多？ BrkSusF > 90mm             │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  根拠 (Evidence):                                                      │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ SP R3: BrkSusF=83.75mm, SP R1: BrkSusF=94.2mm (チャタリング多)│    │
│  └──────────────────────────────────────────────────────────────┘    │
│  紐付けラップ: [SP R1 Lap3] [SP R1 Lap7]  [+ ラップ追加]             │
│  信頼度: ○ HIGH  ● MED  ○ LOW                                        │
│  結論 (Conclusion):                                                    │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ フロントコンプレッションを1クリック増し方向で試す              │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  次のアクション: [→ Setup Decision を作成]                           │
│  [💾 保存]                                                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

### Tab 4: 🔧 Setup Decision（変更内容・期待効果・リスク）

**既存の `SetupDecisionTab` を拡張する。**

追加フィールド:
- `problem_id`: Analysis Note の問題に紐付け（コンボ選択）
- `risk`: リスク評価テキスト
- `confidence`: 変更の確信度（HIGH/MED/LOW）

```
┌─ Setup Decision ─────────────────────────────────────────────────────┐
│  起因する問題: [chattering_brake - T1 ▼]  (Analysis Note より)       │
│  Run From: [ROUND4_BALATON_SP_DA77_R3 ▼]                             │
│  Run To: [NEXT（未定） ▼]                                             │
│  変更コンポーネント: [f_comp ▼]                                       │
│  From → To: [現在値____] → [変更後____]                              │
│  根拠 (Rationale): ________________                                   │
│  期待効果: ________________                                            │
│  リスク (Risk): ________________                                       │
│  確信度: ○ HIGH  ● MED  ○ LOW                                        │
│  [💾 保存]  [→ Result Validation を準備]                             │
└──────────────────────────────────────────────────────────────────────┘
```

---

### Tab 5: ✅ Result Validation（変更結果の評価・フィードバック）

**目的:** セットアップ変更の結果を定量・定性の両面で記録し、フィードバックループを閉じる。

```
┌─ Result Validation ──────────────────────────────────────────────────┐
│  Decision: [f_comp +1クリック (chattering_brake) ▼]                  │
│  確認ラン: [ROUND4_BALATON_QP_JA52_R1 ▼]                             │
├──────────────────────────────────────────────────────────────────────┤
│  パフォーマンス評価:  ● IMPROVED  ○ SAME  ○ WORSE                   │
│  ライダー評価:        ● IMPROVED  ○ SAME  ○ WORSE                   │
│  ラップタイム変化: [-0.___s]  チームメイトギャップ変化: [+/-0.___s] │
├──────────────────────────────────────────────────────────────────────┤
│  最終評価: ● SUCCESS  ○ PARTIAL  ○ FAIL  ○ UNKNOWN                  │
│  評価根拠:                                                             │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │ QP R1でチャタリングが軽減。ラップタイム -0.4s改善。           │    │
│  └──────────────────────────────────────────────────────────────┘    │
│  [💾 保存]  [🏆 Knowledge Case に昇格]                               │
└──────────────────────────────────────────────────────────────────────┘
```

**「Knowledge Case に昇格」ボタン:**
- `final_eval = SUCCESS` の場合のみ有効
- 昇格時に `knowledge_cases` テーブルに自動生成

---

### Tab 6: 📚 Knowledge Base（蓄積された知識の参照）

**目的:** 成功した Problem→Decision→Result のケースを検索・参照。

```
┌─ Knowledge Base ─────────────────────────────────────────────────────┐
│  フィルター: [Circuit▼] [Corner▼] [Problem Tag▼] [Rider▼]           │
├────────────────────────────────────────────────────────────────────  │
│  #  Tag               Circuit  Corner  Action           Success率    │
│  1  chattering_brake  BALATON  T1      f_comp +1click   85%          │
│  2  understeer_apex   ASSEN    T3      apex_preload -2  67%          │
├──────────────────────────────────────────────────────────────────────┤
│  [選択ケースの詳細を見る]                                              │
│                                                                       │
│  ── ケース詳細 ────────────────────────────────────────────────────  │
│  症状: ブレーキング後半のフロントチャタリング                          │
│  再現条件: BrkSusF > 88mm, 中速コーナー, ハードブレーキング時        │
│  解決策: フロントコンプ +1〜2クリック                                 │
│  結果: ラップタイム平均 -0.35s, ライダー評価 IMPROVED                │
└──────────────────────────────────────────────────────────────────────┘
```

---

## BI 集計ビュー（Trend Analysis タブ内に追加）

### 既存 Problems タブを拡張（データなし問題も解消）

現在 `problem_log = 0件` のため空。記録が増えれば自動的に機能する。
グラフはそのまま維持。

### 新規: 🔗 P→D→R チェーンビュー

Problem → Decision → Result の連鎖を一覧表示：

```
Problem Tag | Decision | Result | Lap Δ | Final Eval
chattering  | f_comp+1 | ✅ SUCCESS | -0.4s | IMPROVED
understeer  | preload-2| ⚠ PARTIAL | -0.1s | SAME
```

### 新規: 📊 Setup Effectiveness Matrix

```
          | chattering | understeer | oversteer | front_loss
f_comp    |    85%     |    —       |    —      |    60%
r_comp    |    —       |    70%     |    45%    |    —
preload   |    —       |    65%     |    —      |    —
```

---

## 実装手順（Claude Code への指示）

### Phase 1（必須・最優先）

1. **DBテーブル作成スクリプト**
   ```bash
   python create_workbench_tables.py  # analysis_note / result_validation / knowledge_cases を追加
   ```

2. **`WorkbenchDB` クラスへメソッド追加**
   ```python
   def get_all_runs(self, circuit=None, round_s=None, rider=None, session=None) -> list[dict]
   def save_analysis_note(self, data: dict) -> str
   def get_analysis_notes(self, problem_id: str) -> list[dict]
   def save_result_validation(self, data: dict) -> str
   def get_result_validations(self, decision_id: str) -> list[dict]
   def promote_to_knowledge(self, val_id: str) -> str
   def get_knowledge_cases(self, circuit=None, tag=None, rider=None) -> list[dict]
   ```

3. **`RunBrowserTab` クラスを新規作成**
   - `get_all_runs()` でDB全件表示
   - フィルター・選択・他タブへの誘導

4. **`QuickLogTab` クラスを新規作成**
   - Run コンボ（DB全件）
   - Problem Tag / Phase / Corner / Severity / Memo
   - Enter で保存
   - 保存後リスト即時更新

5. **タブ順序を変更**
   ```python
   tabs = [RunBrowserTab, QuickLogTab, AnalysisNoteTab, SetupDecisionTab, 
           ResultValidationTab, KnowledgeTab, WaveformView, TrendAnalysisTab]
   ```

### Phase 2（Phase 1完了後）

6. `AnalysisNoteTab` — 構造化仮説記録
7. `ResultValidationTab` — 変更結果評価
8. `KnowledgeTab` — 知識ベース閲覧
9. `SetupDecisionTab` に `problem_id` / `risk` / `confidence` フィールド追加

### Phase 3（将来）

10. P→D→R チェーンビュー
11. Setup Effectiveness Matrix
12. Wave形との紐付けオプション（現在のWaveformTabから）

---

## コーディング規則

- 既存テーブル（runs, laps, problem_log, setup_decision_log, lap_suspension）に ALTER は禁止
- 新テーブルは `create_workbench_tables.py` に追記する
- ID生成: `f"{prefix}_{int(time.time()*1000)}"` (例: `AN_1716000000000`)
- **Phase 1 完了後に必ず** `python3 -m py_compile ts24_workbench.py` で構文確認
- 完了後 `race_memory.json` に実装記録を追記

---

## 完了の定義（Phase 1）

- [ ] `analysis_note` / `result_validation` / `knowledge_cases` テーブルが DB に存在する
- [ ] Run Browser タブで全 Run が CSV なしで閲覧できる
- [ ] Quick Log タブで Run を選び → Tag → Memo → Enter で 30 秒以内に保存できる
- [ ] 保存したエントリが Problem Log タブにも反映される
- [ ] `python3 -m py_compile ts24_workbench.py` がエラーなし

---

*このスペックは `CLAUDE.md` セクション 15 にも要約を記載している。*
*Phase 1 完了後、`race_memory.json` に実装サマリーを追記すること。*
