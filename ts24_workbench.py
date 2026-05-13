"""
ts24_workbench.py — TS24 Engineer Workbench v2.0
=================================================
PyQt6製ローカルデスクトップアプリ。
Run Browser / Quick Log / Problem Log / Setup Decision / Trend Analysis の5タブ構成。
CSV不要。DBから直接Runを選択してProblemを記録できる。

読み取り: ts24_unified.db, lap_suspension_data.json
書き込み: ts24_unified.db (problem_log / setup_decision_log のみ)

起動: python ts24_workbench.py
      または TS24_Workbench.command をダブルクリック
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt, QFileSystemWatcher
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QLineEdit, QFrame, QScrollArea,
)

# ── パス設定 ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"

# ── 定数 ─────────────────────────────────────────────────────────────
PROBLEM_TAGS = [
    "chattering_brake", "front_dive", "line_loss_exit",
    "nervousness", "no_turn_in", "push_rear_exit",
    "understeer_apex", "other",
]

COMPONENTS = [
    "f_preload", "f_comp", "f_reb", "f_spr_l", "f_spr_r",
    "r_preload", "r_comp", "r_reb", "r_spr",
    "ride_hgt", "swing_arm", "f_offset",
    "tyre_front", "tyre_rear", "other",
]

PHASES       = ["PH1", "PH2", "PH3", "PH4", "PH5", "GENERAL"]
SEVERITIES   = ["HIGH", "MEDIUM", "LOW"]
SOURCES      = ["OBSERVATION", "DATA", "RIDER_REPORT"]
CHANGE_TYPES = ["FORK", "SHOCK", "GEOMETRY", "TYRE", "ENGINE", "OTHER"]
RESULT_EVALS = ["POSITIVE", "NEGATIVE", "NEUTRAL", "UNKNOWN"]


# ════════════════════════════════════════════════════════════════════
# ユーティリティ
# ════════════════════════════════════════════════════════════════════

def format_laptime(sec: float) -> str:
    """秒数を 分:秒,00 形式に変換する（表示専用）。

    例: 97.45  → "1:37,45"
        300.63 → "5:00,63"
        65.0   → "1:05,00"
    """
    m = int(sec // 60)
    s = sec % 60
    return f"{m}:{s:05.2f}".replace(".", ",")


# ════════════════════════════════════════════════════════════════════
# DB アクセス層
# ════════════════════════════════════════════════════════════════════

class WorkbenchDB:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)
        try:
            with self._conn() as conn:
                self._migrate_problem_log(conn)
        except Exception:
            pass

    def _migrate_problem_log(self, conn: sqlite3.Connection):
        """problem_log テーブルに Phase 2 拡張列を追加（既存DBへの後方互換対応）。"""
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "problem_log" not in tables:
            return
        existing = {row[1] for row in conn.execute("PRAGMA table_info(problem_log)")}
        new_columns = [
            ("distance_start_m", "REAL"),
            ("distance_end_m",   "REAL"),
            ("time_start_s",     "REAL"),
            ("time_end_s",       "REAL"),
            ("data_source_file", "TEXT"),
            ("analysis_note",    "TEXT"),
        ]
        for col_name, col_type in new_columns:
            if col_name not in existing:
                conn.execute(
                    f"ALTER TABLE problem_log ADD COLUMN {col_name} {col_type}"
                )
        conn.commit()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_circuits(self) -> list[str]:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT DISTINCT circuit FROM runs WHERE circuit IS NOT NULL ORDER BY circuit"
            )
            return [r[0] for r in cur.fetchall()]

    def get_runs(self, circuit: str | None = None) -> list[dict]:
        with self._conn() as conn:
            if circuit:
                cur = conn.execute(
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs WHERE circuit = ? ORDER BY session, rider, run_no""",
                    (circuit,),
                )
            else:
                cur = conn.execute(
                    """SELECT run_id, circuit, session, rider, run_no, perf_best_lap
                       FROM runs ORDER BY circuit, session, rider, run_no"""
                )
            return [dict(r) for r in cur.fetchall()]

    def get_run(self, run_id: str) -> dict:
        """単一 run の全フィールドを返す。"""
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return dict(row) if row else {}

    def get_next_runs(self, run_id: str) -> list[dict]:
        """同一 circuit・rider の次の run 候補を返す。"""
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT circuit, rider FROM runs WHERE run_id = ?", (run_id,)
            )
            row = cur.fetchone()
            if not row:
                return []
            cur2 = conn.execute(
                """SELECT run_id, session, run_no FROM runs
                   WHERE circuit = ? AND rider = ? AND run_id != ?
                   ORDER BY session, run_no""",
                (row["circuit"], row["rider"], run_id),
            )
            return [dict(r) for r in cur2.fetchall()]

    def get_problem_logs(self, run_id: str) -> list[dict]:
        """problem_log を取得。スキーマ拡張後も安全に動作するよう SELECT * を使用。"""
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    "SELECT * FROM problem_log WHERE run_id = ? ORDER BY created_at DESC",
                    (run_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]
        except Exception as e:
            print("[WorkbenchDB] get_problem_logs error:", e)
            return []

    def add_problem_log(self, data: dict) -> int:
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO problem_log
                   (run_id, round, circuit, session, rider, run_no, lap_no,
                    corner, phase, problem_tag, description, severity, source,
                    distance_start_m, distance_end_m, time_start_s, time_end_s,
                    data_source_file, analysis_note,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"), data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"), data.get("run_no"),
                    data.get("lap_no"), data.get("corner"), data.get("phase"),
                    data.get("problem_tag"), data.get("description"),
                    data.get("severity", "MEDIUM"), data.get("source", "OBSERVATION"),
                    data.get("distance_start_m"), data.get("distance_end_m"),
                    data.get("time_start_s"), data.get("time_end_s"),
                    data.get("data_source_file", ""), data.get("analysis_note", ""),
                    "PENDING", now, now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_problem_log(self, problem_id: int):
        with self._conn() as conn:
            conn.execute("DELETE FROM problem_log WHERE problem_id = ?", (problem_id,))
            conn.commit()

    def get_setup_decisions(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM setup_decision_log WHERE run_id_from = ?
                   ORDER BY created_at DESC""",
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def add_setup_decision(self, data: dict) -> int:
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO setup_decision_log
                   (run_id_from, run_id_to, round, circuit, session, rider,
                    change_type, component, from_value, to_value,
                    rationale, expected_effect, actual_effect, result_eval,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id_from"), data.get("run_id_to"),
                    data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"),
                    data.get("change_type"), data.get("component"),
                    data.get("from_value"), data.get("to_value"),
                    data.get("rationale"), data.get("expected_effect"),
                    data.get("actual_effect"), data.get("result_eval", "UNKNOWN"),
                    "PENDING", now, now,
                ),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_setup_decision(self, decision_id: int, actual_effect: str, result_eval: str):
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """UPDATE setup_decision_log
                   SET actual_effect = ?, result_eval = ?, updated_at = ?
                   WHERE decision_id = ?""",
                (actual_effect, result_eval, now, decision_id),
            )
            conn.commit()

    def get_laps(self, run_id: str) -> list[dict]:
        """laps テーブルから指定 run_id の全ラップを返す。"""
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT lap_no, lap_time_s, is_outlap
                       FROM laps WHERE run_id = ? ORDER BY lap_no""",
                    (run_id,),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []

# ════════════════════════════════════════════════════════════════════
# Problem Log タブ
# ════════════════════════════════════════════════════════════════════


def _fmt_range(r: dict) -> str:
    """problem_log 行の距離/時間範囲を表示文字列に変換する。"""
    ds = r.get("distance_start_m")
    de = r.get("distance_end_m")
    if ds is not None and de is not None:
        return f"{ds:.0f}→{de:.0f}m"
    ts = r.get("time_start_s")
    te = r.get("time_end_s")
    if ts is not None and te is not None:
        return f"{ts:.1f}→{te:.1f}s"
    return "—"

class _RunSelectorWidget(QWidget):
    """Circuit → Run 選択 UI。CSV ロード不要で DB から直接 Run を選べる。"""

    def __init__(self, db: WorkbenchDB, on_run_selected, parent=None):
        super().__init__(parent)
        self._db = db
        self._cb = on_run_selected
        self._setup_ui()

    def _setup_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lbl_c = QLabel("🗂 Circuit:")
        lbl_c.setStyleSheet("font-size: 10px; font-weight: bold;")
        lay.addWidget(lbl_c)
        self._combo_circ = QComboBox()
        self._combo_circ.setMinimumWidth(120)
        lay.addWidget(self._combo_circ)
        lbl_r = QLabel("Run:")
        lbl_r.setStyleSheet("font-size: 10px; font-weight: bold;")
        lay.addWidget(lbl_r)
        self._combo_run = QComboBox()
        self._combo_run.setMinimumWidth(250)
        lay.addWidget(self._combo_run)
        lay.addStretch()
        self._combo_circ.currentTextChanged.connect(self._on_circ)
        self._combo_run.currentIndexChanged.connect(self._on_run)
        self.setStyleSheet(
            "background: #F0F4F8; border: 1px solid #C8D3DC;"
            " border-radius: 4px; padding: 2px;"
        )
        self._load_circuits()

    def _load_circuits(self):
        try:
            circs = self._db.get_circuits()
        except Exception:
            circs = []
        self._combo_circ.blockSignals(True)
        self._combo_circ.clear()
        self._combo_circ.addItem("— 全て —")
        self._combo_circ.addItems(circs)
        self._combo_circ.blockSignals(False)
        if circs:
            self._combo_circ.setCurrentIndex(1)
        else:
            self._on_circ("— 全て —")

    def _on_circ(self, circuit: str):
        circ = circuit if circuit != "— 全て —" else None
        try:
            runs = self._db.get_runs(circ)
        except Exception:
            runs = []
        self._combo_run.blockSignals(True)
        self._combo_run.clear()
        for r in runs:
            label = f"{r['rider']}  {r['session']} R{r['run_no']}  ({r['run_id']})"
            self._combo_run.addItem(label, userData=r["run_id"])
        self._combo_run.blockSignals(False)
        if self._combo_run.count():
            self._combo_run.setCurrentIndex(0)
            self._emit()

    def _on_run(self, _idx: int):
        self._emit()

    def _emit(self):
        run_id = self._combo_run.currentData()
        if run_id:
            self._cb(run_id)

    def select_run_id(self, run_id: str):
        """外部から特定 run_id を選択状態にする（波形ロード連携）。"""
        for i in range(self._combo_run.count()):
            if self._combo_run.itemData(i) == run_id:
                self._combo_run.setCurrentIndex(i)
                return


class ProblemLogTab(QWidget):
    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._run_id: str = ""
        self._run_meta: dict = {}
        self._wave_prefill: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── DB ベース Run セレクタ ────────────────────────────────────
        self._run_sel = _RunSelectorWidget(self._db, self._on_db_run_selected)
        layout.addWidget(self._run_sel)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Corner", "Phase", "Tag", "Description", "Severity", "Lap", "Range", "Source"]
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 60)
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 220)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 40)
        self._table.setColumnWidth(7, 160)
        self._table.setColumnWidth(8, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, stretch=2)

        # 削除ボタン
        del_btn = QPushButton("選択行を削除")
        del_btn.clicked.connect(self._delete_selected)
        layout.addWidget(del_btn)

        # ── 区切り ────────────────────────────────────────
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # ── 新規追加フォーム ──────────────────────────────
        form_label = QLabel("▼ 新規問題を追加")
        form_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(form_label)

        # ── 波形連携: 自動入力エリア ─────────────────────────────────
        self._wave_info_box = QWidget()
        self._wave_info_box.setStyleSheet(
            "background: #EFF6FF; border: 1px solid #0078D4;"
            " border-radius: 4px; padding: 4px;"
        )
        wave_info_lay = QVBoxLayout(self._wave_info_box)
        wave_info_lay.setContentsMargins(8, 4, 8, 4)
        wave_info_lay.setSpacing(2)

        wave_header = QLabel("📊 波形から自動入力（読み取り専用）")
        wave_header.setStyleSheet("color: #0078D4; font-weight: bold; font-size: 10px;")
        wave_info_lay.addWidget(wave_header)

        self._lbl_auto_run   = QLabel("Run: —")
        self._lbl_auto_lap   = QLabel("Lap: —")
        self._lbl_auto_range = QLabel("Range: —")
        for lbl in (self._lbl_auto_run, self._lbl_auto_lap, self._lbl_auto_range):
            lbl.setStyleSheet("color: #004578; font-size: 10px;")
            wave_info_lay.addWidget(lbl)

        btn_clear_wave = QPushButton("✕ 自動入力をクリア")
        btn_clear_wave.setFixedHeight(20)
        btn_clear_wave.setStyleSheet("font-size: 10px; color: #666;")
        btn_clear_wave.clicked.connect(self._clear_wave_prefill)
        wave_info_lay.addWidget(btn_clear_wave)

        self._wave_info_box.setVisible(False)
        layout.addWidget(self._wave_info_box)

        form = QFormLayout()

        self._lbl_run = QLabel("（未選択）")
        form.addRow("Run:", self._lbl_run)

        self._spin_lap = QSpinBox()
        self._spin_lap.setRange(0, 999)
        self._spin_lap.setSpecialValueText("—")
        form.addRow("Lap No (optional):", self._spin_lap)

        self._combo_corner = QComboBox()
        self._combo_corner.addItem("NONE")
        for i in range(1, 18):
            self._combo_corner.addItem(f"T{i}")
        form.addRow("Corner:", self._combo_corner)

        self._combo_phase = QComboBox()
        self._combo_phase.addItems(PHASES)
        form.addRow("Phase:", self._combo_phase)

        self._combo_tag = QComboBox()
        self._combo_tag.addItems(PROBLEM_TAGS)
        form.addRow("Problem Tag:", self._combo_tag)

        self._txt_desc = QTextEdit()
        self._txt_desc.setFixedHeight(60)
        self._txt_desc.setPlaceholderText("詳細説明（任意）")
        form.addRow("Description:", self._txt_desc)

        self._combo_sev = QComboBox()
        self._combo_sev.addItems(SEVERITIES)
        self._combo_sev.setCurrentText("MEDIUM")
        form.addRow("Severity:", self._combo_sev)

        self._combo_src = QComboBox()
        self._combo_src.addItems(SOURCES)
        form.addRow("Source:", self._combo_src)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_add   = QPushButton("追加")
        btn_clear = QPushButton("クリア")
        btn_add.clicked.connect(self._add_entry)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_db_run_selected(self, run_id: str):
        """Run セレクタから呼ばれる。DB からメタを取得して set_run() へ渡す。"""
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()
        if hasattr(self, "_run_sel"):
            self._run_sel.select_run_id(run_id)

    def prefill_from_waveform(self, data: dict) -> None:
        """WaveformView から呼ばれ、座標情報を自動入力する。"""
        self._wave_prefill = data

        run_id = data.get("run_id", "")
        if run_id and self._run_id and run_id != self._run_id:
            QMessageBox.warning(
                self,
                "Run 不一致",
                f"波形のRun ({run_id}) と\n"
                f"Problem Log のRun ({self._run_id}) が一致しません。\n"
                "左パネルで同じ Run を選択してください。",
            )
            self._wave_prefill = {}
            return

        self._lbl_auto_run.setText(f"Run: {run_id or '—'}")
        lap_no = data.get("lap_no")
        self._lbl_auto_lap.setText(f"Lap: {lap_no if lap_no is not None else '—'}")

        x_mode = data.get("x_mode", "")
        if x_mode == "distance":
            ds = data.get("distance_start_m")
            de = data.get("distance_end_m")
            range_str = (f"{ds:.1f}m → {de:.1f}m  ({de - ds:.1f}m)"
                         if ds is not None and de is not None else "—")
        elif x_mode == "time":
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = (f"{ts:.3f}s → {te:.3f}s  ({te - ts:.3f}s)"
                         if ts is not None and te is not None else "—")
        else:
            ts = data.get("time_start_s")
            te = data.get("time_end_s")
            range_str = f"progress {ts:.4f} → {te:.4f}" if ts is not None else "—"

        self._lbl_auto_range.setText(f"Range: {range_str}")
        self._wave_info_box.setVisible(True)

        if lap_no is not None:
            self._spin_lap.setValue(int(lap_no))

        src_items = [self._combo_src.itemText(i) for i in range(self._combo_src.count())]
        if "DATA" in src_items:
            self._combo_src.setCurrentText("DATA")

    def _clear_wave_prefill(self) -> None:
        """波形からの自動入力をリセットする。"""
        self._wave_prefill = {}
        self._lbl_auto_run.setText("Run: —")
        self._lbl_auto_lap.setText("Lap: —")
        self._lbl_auto_range.setText("Range: —")
        self._wave_info_box.setVisible(False)

    def _refresh_table(self):
        try:
            print("[ProblemLog] run_id:", self._run_id)
            rows = self._db.get_problem_logs(self._run_id) if self._run_id else []
            print("[ProblemLog] rows:", len(rows))
            if rows:
                print("[ProblemLog] keys:", list(rows[0].keys()))
        except Exception as e:
            print("[ProblemLog] refresh error:", e)
            import traceback; traceback.print_exc()
            rows = []
        self._table.setRowCount(0)
        for ri, r in enumerate(rows):
            try:
                self._table.insertRow(ri)
                vals = [
                    str(r.get("problem_id", "")),
                    str(r.get("corner", "") or ""),
                    str(r.get("phase", "") or ""),
                    str(r.get("problem_tag", "") or ""),
                    str(r.get("description", "") or ""),
                    str(r.get("severity", "") or ""),
                    str(r.get("lap_no", "") if r.get("lap_no") is not None else "—"),
                    _fmt_range(r),
                    str(r.get("source", "") or ""),
                ]
                for ci, val in enumerate(vals):
                    self._table.setItem(ri, ci, QTableWidgetItem(val))
            except Exception as e:
                print(f"[ProblemLog] row {ri} render error:", e)

    def _add_entry(self):
        if not self._run_id:
            QMessageBox.warning(self, "未選択", "左パネルでRunを選択してください。")
            return
        corner_val = self._combo_corner.currentText()
        if corner_val == "NONE":
            corner_val = None
        lap_val = self._spin_lap.value()
        if lap_val == 0:
            lap_val = None
        data = {
            "run_id":     self._run_id,
            "round":      self._run_meta.get("round"),
            "circuit":    self._run_meta.get("circuit"),
            "session":    self._run_meta.get("session"),
            "rider":      self._run_meta.get("rider"),
            "run_no":     self._run_meta.get("run_no"),
            "lap_no":     lap_val,
            "corner":     corner_val,
            "phase":      self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":   self._combo_sev.currentText(),
            "source":     self._combo_src.currentText(),
            "distance_start_m": self._wave_prefill.get("distance_start_m"),
            "distance_end_m":   self._wave_prefill.get("distance_end_m"),
            "time_start_s":     self._wave_prefill.get("time_start_s"),
            "time_end_s":       self._wave_prefill.get("time_end_s"),
            "data_source_file": self._wave_prefill.get("data_source_file", ""),
            "analysis_note":    "",
        }
        self._db.add_problem_log(data)
        self._clear_form()
        self._clear_wave_prefill()
        self._refresh_table()

    def _clear_form(self):
        self._spin_lap.setValue(0)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()
        self._combo_sev.setCurrentText("MEDIUM")
        self._combo_src.setCurrentIndex(0)

    def refresh(self):
        """DB変更時に外部から呼び出される。テーブルを再読み込みする。"""
        self._refresh_table()

    def _delete_selected(self):
        rows = self._table.selectedItems()
        if not rows:
            return
        row = self._table.currentRow()
        pid_item = self._table.item(row, 0)
        if not pid_item:
            return
        try:
            pid = int(pid_item.text())
        except ValueError:
            return
        reply = QMessageBox.question(
            self, "削除確認", f"problem_id={pid} を削除しますか？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._db.delete_problem_log(pid)
            self._refresh_table()


# ════════════════════════════════════════════════════════════════════
# Setup Decision Log タブ
# ════════════════════════════════════════════════════════════════════

class SetupDecisionTab(QWidget):
    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._run_id: str = ""
        self._run_meta: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── DB ベース Run セレクタ ────────────────────────────────────
        self._run_sel = _RunSelectorWidget(self._db, self._on_db_run_selected)
        layout.addWidget(self._run_sel)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Component", "From", "To", "Rationale", "Result"]
        )
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 280)
        self._table.setColumnWidth(5, 80)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table, stretch=2)

        # 区切り
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        form_label = QLabel("▼ セットアップ変更を記録")
        form_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        layout.addWidget(form_label)

        form = QFormLayout()

        self._lbl_run_from = QLabel("（未選択）")
        form.addRow("Run From:", self._lbl_run_from)

        self._combo_run_to = QComboBox()
        self._combo_run_to.addItem("NEXT（未定）")
        form.addRow("Run To:", self._combo_run_to)

        self._combo_chg_type = QComboBox()
        self._combo_chg_type.addItems(CHANGE_TYPES)
        form.addRow("Change Type:", self._combo_chg_type)

        self._combo_comp = QComboBox()
        self._combo_comp.addItems(COMPONENTS)
        form.addRow("Component:", self._combo_comp)

        row_fv = QHBoxLayout()
        self._edit_from = QLineEdit()
        self._edit_from.setPlaceholderText("例: 18")
        self._edit_to = QLineEdit()
        self._edit_to.setPlaceholderText("例: 16")
        row_fv.addWidget(self._edit_from)
        row_fv.addWidget(QLabel("→"))
        row_fv.addWidget(self._edit_to)
        form.addRow("From → To:", row_fv)

        self._txt_rationale = QTextEdit()
        self._txt_rationale.setFixedHeight(55)
        self._txt_rationale.setPlaceholderText("変更の根拠（データ/ライダー報告）")
        form.addRow("Rationale:", self._txt_rationale)

        self._txt_expected = QTextEdit()
        self._txt_expected.setFixedHeight(55)
        self._txt_expected.setPlaceholderText("期待する効果")
        form.addRow("Expected Effect:", self._txt_expected)

        self._combo_result = QComboBox()
        self._combo_result.addItems(RESULT_EVALS)
        self._combo_result.setCurrentText("UNKNOWN")
        form.addRow("Result Eval:", self._combo_result)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_add   = QPushButton("追加")
        btn_clear = QPushButton("クリア")
        btn_add.clicked.connect(self._add_entry)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _on_db_run_selected(self, run_id: str):
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self.set_run(run_id, meta)

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run_from.setText(run_id or "（未選択）")
        self._combo_run_to.clear()
        self._combo_run_to.addItem("NEXT（未定）")
        next_runs = self._db.get_next_runs(run_id) if run_id else []
        for nr in next_runs:
            self._combo_run_to.addItem(
                f"{nr['run_id']}  ({nr['session']} R{nr['run_no']})",
                userData=nr["run_id"],
            )
        self._refresh_table()
        if hasattr(self, "_run_sel"):
            self._run_sel.select_run_id(run_id)

    def _refresh_table(self):
        rows = self._db.get_setup_decisions(self._run_id) if self._run_id else []
        self._table.setRowCount(0)
        for r in rows:
            ri = self._table.rowCount()
            self._table.insertRow(ri)
            for ci, val in enumerate([
                r.get("decision_id", ""),
                r.get("component", ""),
                r.get("from_value", ""),
                r.get("to_value", ""),
                r.get("rationale", ""),
                r.get("result_eval", ""),
            ]):
                self._table.setItem(ri, ci, QTableWidgetItem(str(val) if val is not None else "—"))

    def _add_entry(self):
        if not self._run_id:
            QMessageBox.warning(self, "未選択", "左パネルでRunを選択してください。")
            return
        run_to_idx = self._combo_run_to.currentIndex()
        run_to_data = self._combo_run_to.itemData(run_to_idx)
        run_to_val = run_to_data if run_to_data else None

        data = {
            "run_id_from":    self._run_id,
            "run_id_to":      run_to_val,
            "round":          self._run_meta.get("round"),
            "circuit":        self._run_meta.get("circuit"),
            "session":        self._run_meta.get("session"),
            "rider":          self._run_meta.get("rider"),
            "change_type":    self._combo_chg_type.currentText(),
            "component":      self._combo_comp.currentText(),
            "from_value":     self._edit_from.text().strip(),
            "to_value":       self._edit_to.text().strip(),
            "rationale":      self._txt_rationale.toPlainText().strip(),
            "expected_effect": self._txt_expected.toPlainText().strip(),
            "actual_effect":  None,
            "result_eval":    self._combo_result.currentText(),
        }
        self._db.add_setup_decision(data)
        self._clear_form()
        self._refresh_table()

    def refresh(self):
        """DB変更時に外部から呼び出される。テーブルを再読み込みする。"""
        self._refresh_table()

    def _clear_form(self):
        self._combo_chg_type.setCurrentIndex(0)
        self._combo_comp.setCurrentIndex(0)
        self._edit_from.clear()
        self._edit_to.clear()
        self._txt_rationale.clear()
        self._txt_expected.clear()
        self._combo_result.setCurrentText("UNKNOWN")



# ════════════════════════════════════════════════════════════════════
# Run Browser タブ
# ════════════════════════════════════════════════════════════════════

class RunBrowserTab(QWidget):
    """🗺️ Run Browser — DB全Run一覧。Circuit / Rider / Session フィルタ + 行クリックで選択。"""

    run_selected = None  # will be set to a callable

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._on_run_selected = None  # callback(run_id, meta)
        self._setup_ui()
        self._refresh()

    def set_on_run_selected(self, cb):
        self._on_run_selected = cb

    def refresh(self):
        """DB変更時に外部から呼び出される。Run一覧を再読み込みする。"""
        self._refresh()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        # ── フィルタ行 ────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Circuit:"))
        self._combo_circ = QComboBox()
        self._combo_circ.setFixedWidth(130)
        self._combo_circ.addItem("ALL")
        self._combo_circ.currentTextChanged.connect(self._on_filter)
        filter_row.addWidget(self._combo_circ)

        filter_row.addWidget(QLabel("Rider:"))
        self._combo_rider = QComboBox()
        self._combo_rider.setFixedWidth(100)
        self._combo_rider.addItems(["ALL", "DA77", "JA52"])
        self._combo_rider.currentTextChanged.connect(self._on_filter)
        filter_row.addWidget(self._combo_rider)

        filter_row.addWidget(QLabel("Session:"))
        self._combo_session = QComboBox()
        self._combo_session.setFixedWidth(120)
        self._combo_session.addItem("ALL")
        self._combo_session.currentTextChanged.connect(self._on_filter)
        filter_row.addWidget(self._combo_session)

        btn_refresh = QPushButton("🔄 更新")
        btn_refresh.setFixedWidth(70)
        btn_refresh.clicked.connect(self._refresh)
        filter_row.addWidget(btn_refresh)
        filter_row.addStretch()

        self._lbl_count = QLabel("")
        self._lbl_count.setStyleSheet("color: #888; font-size: 10px;")
        filter_row.addWidget(self._lbl_count)
        lay.addLayout(filter_row)

        # ── テーブル ──────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Run ID", "Circuit", "Session", "Rider", "Run No", "Best Lap"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.cellClicked.connect(self._on_row_clicked)
        lay.addWidget(self._table)

    def _refresh(self):
        try:
            circuits = self._db.get_circuits()
        except Exception:
            circuits = []
        self._combo_circ.blockSignals(True)
        saved_circ = self._combo_circ.currentText()
        self._combo_circ.clear()
        self._combo_circ.addItem("ALL")
        self._combo_circ.addItems(circuits)
        idx = self._combo_circ.findText(saved_circ)
        if idx >= 0:
            self._combo_circ.setCurrentIndex(idx)
        self._combo_circ.blockSignals(False)

        try:
            all_runs = self._db.get_runs()
        except Exception:
            all_runs = []

        sessions = sorted({r.get("session", "") or "" for r in all_runs if r.get("session")})
        self._combo_session.blockSignals(True)
        saved_sess = self._combo_session.currentText()
        self._combo_session.clear()
        self._combo_session.addItem("ALL")
        self._combo_session.addItems(sessions)
        idx = self._combo_session.findText(saved_sess)
        if idx >= 0:
            self._combo_session.setCurrentIndex(idx)
        self._combo_session.blockSignals(False)

        self._populate_table(all_runs)

    def _on_filter(self):
        circ = self._combo_circ.currentText()
        try:
            runs = self._db.get_runs(circuit=circ if circ != "ALL" else None)
        except Exception:
            runs = []
        self._populate_table(runs)

    def _populate_table(self, runs: list[dict]):
        rider_f   = self._combo_rider.currentText()
        session_f = self._combo_session.currentText()

        filtered = [
            r for r in runs
            if (rider_f   == "ALL" or r.get("rider")   == rider_f)
            and (session_f == "ALL" or r.get("session") == session_f)
        ]

        self._table.setRowCount(len(filtered))
        for row, r in enumerate(filtered):
            best = r.get("perf_best_lap")
            best_str = format_laptime(float(best)) if best else "—"
            vals = [
                r.get("run_id", ""),
                r.get("circuit", ""),
                r.get("session", ""),
                r.get("rider", ""),
                str(r.get("run_no", "")),
                best_str,
            ]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole, r.get("run_id", ""))
                self._table.setItem(row, col, item)

        self._table.resizeColumnsToContents()
        self._lbl_count.setText(f"{len(filtered)} runs")

    def _on_row_clicked(self, row: int, col: int):
        item = self._table.item(row, 0)
        if not item:
            return
        run_id = item.data(Qt.ItemDataRole.UserRole)
        if not run_id:
            return
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {"run_id": run_id}
        if self._on_run_selected:
            self._on_run_selected(run_id, meta)


# ════════════════════════════════════════════════════════════════════
# Quick Log タブ
# ════════════════════════════════════════════════════════════════════

class QuickLogTab(QWidget):
    """⚡ Quick Log — CSV不要、30秒でProblemを記録する最小UIタブ。"""

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._setup_ui()

    def set_run(self, run_id: str, meta: dict) -> None:
        """RunBrowserからの選択を反映する。"""
        self._run_selector.select_run_id(run_id)

    def refresh(self):
        """DB変更時に外部から呼び出される。Run選択コンボを再読み込みする。"""
        if hasattr(self, "_run_selector"):
            self._run_selector._load_circuits()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(8)

        title = QLabel("⚡ Quick Problem Log")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #0078D4;")
        lay.addWidget(title)

        # ── Run セレクタ ────────────────────────────────────────────────────────────
        self._run_selector = _RunSelectorWidget(
            db=self._db,
            on_run_selected=self._on_run_selected,
        )
        lay.addWidget(self._run_selector)

        self._lbl_run_info = QLabel("Run未選択")
        self._lbl_run_info.setStyleSheet("color: #888; font-size: 10px;")
        lay.addWidget(self._lbl_run_info)

        # ── フォーム ────────────────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(6)

        self._spin_lap = QSpinBox()
        self._spin_lap.setRange(0, 99)
        self._spin_lap.setSpecialValueText("—")
        form.addRow("Lap No:", self._spin_lap)

        self._combo_corner = QComboBox()
        self._combo_corner.addItem("NONE")
        for i in range(1, 20):
            self._combo_corner.addItem(f"T{i}")
        form.addRow("Corner:", self._combo_corner)

        self._combo_phase = QComboBox()
        self._combo_phase.addItems(PHASES)
        form.addRow("Phase:", self._combo_phase)

        self._combo_tag = QComboBox()
        self._combo_tag.addItems(PROBLEM_TAGS)
        form.addRow("Problem Tag:", self._combo_tag)

        self._txt_desc = QTextEdit()
        self._txt_desc.setFixedHeight(72)
        self._txt_desc.setPlaceholderText("詳細説明（任意）")
        form.addRow("Description:", self._txt_desc)

        self._combo_sev = QComboBox()
        self._combo_sev.addItems(SEVERITIES)
        form.addRow("Severity:", self._combo_sev)

        lay.addLayout(form)

        # ── ボタン行 ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Save Problem")
        btn_save.setFixedHeight(36)
        btn_save.setStyleSheet(
            "QPushButton { background: #107C10; color: white; border-radius: 6px;"
            " font-size: 13px; font-weight: bold; padding: 0 20px; }"
            "QPushButton:hover { background: #0E6B0E; }"
        )
        btn_save.clicked.connect(self._save)
        btn_clear = QPushButton("クリア")
        btn_clear.setFixedHeight(36)
        btn_clear.clicked.connect(self._clear_form)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._lbl_result = QLabel("")
        self._lbl_result.setStyleSheet("color: #107C10; font-size: 10px;")
        lay.addWidget(self._lbl_result)

        lay.addStretch()

        self._current_run_id: str = ""
        self._current_meta: dict = {}

    def _on_run_selected(self, run_id: str) -> None:
        self._current_run_id = run_id
        try:
            meta = self._db.get_run(run_id)
        except Exception:
            meta = {}
        self._current_meta = meta
        circuit  = meta.get("circuit", "")
        rider    = meta.get("rider", "")
        run_no   = meta.get("run_no", "")
        session  = meta.get("session", "")
        self._lbl_run_info.setText(
            f"✅ {circuit}  |  {rider}  |  {session}  Run #{run_no}"
        )
        self._lbl_result.setText("")

    def _save(self) -> None:
        if not self._current_run_id:
            QMessageBox.warning(self, "警告", "Runを先に選択してください。")
            return
        corner_val = self._combo_corner.currentText()
        if corner_val == "NONE":
            corner_val = None
        data = {
            "run_id":      self._current_run_id,
            "round":       self._current_meta.get("round"),
            "circuit":     self._current_meta.get("circuit"),
            "session":     self._current_meta.get("session"),
            "rider":       self._current_meta.get("rider"),
            "run_no":      self._current_meta.get("run_no"),
            "lap_no":      self._spin_lap.value() or None,
            "corner":      corner_val,
            "phase":       self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":    self._combo_sev.currentText(),
            "source":      "OBSERVATION",
        }
        try:
            self._db.add_problem_log(data)
        except Exception as e:
            QMessageBox.critical(self, "DB Error", str(e))
            return
        tag = data["problem_tag"]
        self._lbl_result.setText(f"✅ 保存完了: {tag}")
        self._clear_form()

    def _clear_form(self) -> None:
        self._spin_lap.setValue(0)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()
        self._combo_sev.setCurrentIndex(0)


# ════════════════════════════════════════════════════════════════════
# メインウィンドウ
# ════════════════════════════════════════════════════════════════════

class PostureAnalysisTab(QWidget):
    """🎯 姿勢分析タブ
    Pitch = ApexSusF - ApexSusR  (負値=ノーズDOWN=良好なターンイン)
    Heave = (ApexSusF + ApexSusR) / 2  (全体沈み込み量)
    データソース: lap_suspension_data.json (参考値 §0)
    """

    _LAP_SUS = SCRIPT_DIR / "lap_suspension_data.json"
    _COLORS   = {"DA77": "#0078D4", "JA52": "#FF8C00"}

    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db  = db
        self._df  = None        # pandas DataFrame
        self._circuit_filter = ""
        self._setup_ui()
        self._load_data()

    # ── データ読み込み ──────────────────────────────────────────────

    def refresh(self):
        """DB/JSON変更時に外部から呼び出される。データを再読み込みする。"""
        self._load_data()

    def _load_data(self):
        if not self._LAP_SUS.exists():
            if hasattr(self, "_lbl_status"):
                self._lbl_status.setText(
                    "⚠️  lap_suspension_data.json が見つかりません。"
                    " python lap_suspension_stats.py を実行してください。"
                )
            return
        try:
            raw = json.loads(self._LAP_SUS.read_text(encoding="utf-8"))
            self._df = pd.DataFrame(raw)
            self._df.columns = [c.lower() for c in self._df.columns]
            sf = "apex_susf_avg"
            sr = "apex_susr_avg"
            if sf in self._df.columns and sr in self._df.columns:
                self._df["pitch"] = self._df[sf] - self._df[sr]
                self._df["heave"] = (self._df[sf] + self._df[sr]) / 2.0
            if hasattr(self, "_lbl_status"):
                n = len(self._df)
                riders = self._df["rider"].unique().tolist() if "rider" in self._df.columns else []
                self._lbl_status.setText(
                    f"✅  {n} ラップ読み込み済 | riders: {', '.join(riders)}"
                )
            # サーキット選択コンボ更新
            if "circuit" in self._df.columns:
                circs = sorted(self._df["circuit"].dropna().unique().tolist())
                self._combo_circ.blockSignals(True)
                self._combo_circ.clear()
                self._combo_circ.addItem("全サーキット")
                self._combo_circ.addItems(circs)
                self._combo_circ.blockSignals(False)
            self._update_all()
        except Exception as e:
            if hasattr(self, "_lbl_status"):
                self._lbl_status.setText(f"❌ 読み込みエラー: {e}")

    def _filtered_df(self):
        if self._df is None:
            return None
        df = self._df
        circ = self._combo_circ.currentText()
        if circ and circ != "全サーキット" and "circuit" in df.columns:
            df = df[df["circuit"] == circ]
        return df

    # ── UI 構築 ────────────────────────────────────────────────────

    def _setup_ui(self):
        try:
            import pyqtgraph as pg
            self._pg   = pg
            self._haspg = True
        except ImportError:
            self._haspg = False

        root = QVBoxLayout(self)
        root.setSpacing(4)

        # §0 原則注記
        warn = QLabel("⚠️  §0 参考値 — lap_suspension_data.json (推定値)")
        warn.setStyleSheet("color: #D83B01; font-style: italic; font-size: 10px; padding: 2px;")
        root.addWidget(warn)

        # ツールバー行
        tb = QHBoxLayout()
        self._lbl_status = QLabel("データ読込中…")
        self._lbl_status.setStyleSheet("font-size: 10px; color: #666;")
        tb.addWidget(self._lbl_status, stretch=1)
        tb.addWidget(QLabel("Circuit:"))
        self._combo_circ = QComboBox()
        self._combo_circ.setMinimumWidth(130)
        self._combo_circ.currentTextChanged.connect(self._update_all)
        tb.addWidget(self._combo_circ)
        btn_reload = QPushButton("↺ 再読込")
        btn_reload.setFixedHeight(24)
        btn_reload.clicked.connect(self._load_data)
        tb.addWidget(btn_reload)
        root.addLayout(tb)

        if not self._haspg:
            root.addWidget(QLabel("pyqtgraph が必要です: pip install pyqtgraph"))
            return

        pg = self._pg
        pg.setConfigOption("background", "w")
        pg.setConfigOption("foreground", "k")

        # 2×2 グリッド: QSplitter 縦 × (横スプリッタ 上/下)
        vsplit = QSplitter(Qt.Orientation.Vertical)

        # 上段スプリッタ
        top = QSplitter(Qt.Orientation.Horizontal)
        self._pw_scatter = pg.PlotWidget(title="Pitch vs Lap Time")
        self._pw_phase   = pg.PlotWidget(title="Phase Space (SusF vs SusR)")
        top.addWidget(self._pw_scatter)
        top.addWidget(self._pw_phase)
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)

        # 下段スプリッタ
        bot = QSplitter(Qt.Orientation.Horizontal)
        self._pw_radar = pg.PlotWidget(title="Rider Fingerprint")
        self._pw_trend = pg.PlotWidget(title="Pitch / Heave Lap推移")
        bot.addWidget(self._pw_radar)
        bot.addWidget(self._pw_trend)
        bot.setStretchFactor(0, 1)
        bot.setStretchFactor(1, 1)

        vsplit.addWidget(top)
        vsplit.addWidget(bot)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 1)
        root.addWidget(vsplit, stretch=1)

        for _pw in (self._pw_scatter, self._pw_phase, self._pw_radar, self._pw_trend):
            _pw.showGrid(x=True, y=True, alpha=0.3)
            _pw.addLegend()

        # Radar は極座標描画のため軸を非表示・正方形
        self._pw_radar.setAspectLocked(True)
        self._pw_radar.hideAxis("bottom")
        self._pw_radar.hideAxis("left")

    # ── 描画 ───────────────────────────────────────────────────────

    def _update_all(self):
        if not self._haspg or self._df is None:
            return
        df = self._filtered_df()
        if df is None or df.empty:
            return
        self._draw_pitch_scatter(df)
        self._draw_phase_space(df)
        self._draw_radar(df)
        self._draw_trend(df)

    def _draw_pitch_scatter(self, df):
        """Panel 1: Pitch vs Lap Time散布図。"""
        pg  = self._pg
        pw  = self._pw_scatter
        pw.clear()
        pw.setLabel("left", "Pitch (mm) = SusF - SusR")
        pw.setLabel("bottom", "Lap Time (s)")
        if "pitch" not in df.columns or "lap_time_s" not in df.columns:
            return
        pw.addLegend()
        for rider, col in self._COLORS.items():
            sub = df[df.get("rider", pd.Series(dtype=str)) == rider] if "rider" in df.columns else df
            if rider not in df.get("rider", pd.Series(dtype=str)).values:
                continue
            sub = df[df["rider"] == rider].dropna(subset=["pitch", "lap_time_s"])
            if sub.empty:
                continue
            pw.plot(
                x=sub["lap_time_s"].values.tolist(),
                y=sub["pitch"].values.tolist(),
                pen=None,
                symbol="o", symbolSize=6,
                symbolBrush=pg.mkBrush(col),
                symbolPen=pg.mkPen(col, width=0.5),
                name=rider,
            )
        # ゼロライン
        pw.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#888", width=1,
                                   style=Qt.PenStyle.DotLine)))

    def _draw_phase_space(self, df):
        """Panel 2: SusF vs SusR Phase Space。速いラップ=青、遅い=赤。"""
        pg = self._pg
        pw = self._pw_phase
        pw.clear()
        pw.setLabel("left",   "Apex SusR (mm)")
        pw.setLabel("bottom", "Apex SusF (mm)")
        sf_col = "apex_susf_avg"
        sr_col = "apex_susr_avg"
        lt_col = "lap_time_s"
        if sf_col not in df.columns or sr_col not in df.columns:
            return
        sub = df.dropna(subset=[sf_col, sr_col])
        if sub.empty:
            return
        pw.addLegend()
        for rider, col in self._COLORS.items():
            if "rider" not in df.columns:
                break
            rs = sub[sub["rider"] == rider]
            if rs.empty:
                continue
            symbol = "o" if rider == "DA77" else "t"
            pw.plot(
                x=rs[sf_col].values.tolist(),
                y=rs[sr_col].values.tolist(),
                pen=None,
                symbol=symbol, symbolSize=7,
                symbolBrush=pg.mkBrush(col + "A0"),
                symbolPen=pg.mkPen(col, width=0.5),
                name=rider,
            )
        # 対角線（SusF=SusR）
        lim = max(sub[sf_col].max(), sub[sr_col].max()) * 1.05
        pw.plot([0, lim], [0, lim], pen=pg.mkPen("#CCC", width=1,
                style=Qt.PenStyle.DotLine))

    def _draw_radar(self, df):
        """Panel 3: ライダー指紋レーダーチャート（5軸）。"""
        import math
        pg = self._pg
        pw = self._pw_radar
        pw.clear()
        pw.addLegend()

        METRICS = [
            ("pitch",          "Pitch\n(SusF-SusR)",  True),   # (列名, ラベル, 小さい=良い)
            ("heave",          "Heave\n(avg sink)",    True),
            ("brk_susf_avg",   "BRK\nSusF",           True),
            ("apex_spd_avg",   "Apex\nSpeed",          False),  # 大きい=良い
            ("lap_time_s",     "Lap\nTime",            True),
        ]
        n = len(METRICS)
        angles = [2 * math.pi * i / n - math.pi / 2 for i in range(n)]

        # 各指標の全ライダー平均
        rider_vals: dict[str, list[float]] = {}
        raw_stats: dict[str, dict] = {}
        for rider in self._COLORS:
            if "rider" not in df.columns:
                break
            rs = df[df["rider"] == rider]
            vals = []
            stats = {}
            for col, _lbl, lower_better in METRICS:
                if col in rs.columns:
                    v = rs[col].dropna().mean()
                    stats[col] = float(v) if not pd.isna(v) else 0.0
                else:
                    stats[col] = 0.0
                vals.append(stats[col])
            rider_vals[rider] = vals
            raw_stats[rider] = stats

        if not rider_vals:
            return

        # 各軸を 0-1 正規化（全ライダー横断）
        norm_vals: dict[str, list[float]] = {r: [] for r in rider_vals}
        for i, (col, _lbl, lower_better) in enumerate(METRICS):
            all_v = [rider_vals[r][i] for r in rider_vals if rider_vals[r]]
            mn, mx = min(all_v), max(all_v)
            span = mx - mn if mx != mn else 1.0
            for rider in rider_vals:
                raw = rider_vals[rider][i]
                norm = (raw - mn) / span  # 0=低, 1=高
                # 「小さい=良い」指標は反転して 1=良い になるよう
                if lower_better:
                    norm = 1.0 - norm
                norm_vals[rider].append(norm)

        # グリッド円
        for r in [0.25, 0.5, 0.75, 1.0]:
            xs = [math.cos(a) * r for a in angles] + [math.cos(angles[0]) * r]
            ys = [math.sin(a) * r for a in angles] + [math.sin(angles[0]) * r]
            pw.plot(xs, ys, pen=pg.mkPen("#DDD", width=0.7))

        # 軸線 + ラベル
        for a, (_, lbl, _b) in zip(angles, METRICS):
            pw.plot([0, math.cos(a)], [0, math.sin(a)],
                    pen=pg.mkPen("#AAA", width=0.7))
            ti = pg.TextItem(lbl, anchor=(0.5, 0.5), color="#555")
            ti.setPos(math.cos(a) * 1.22, math.sin(a) * 1.22)
            pw.addItem(ti)

        # ライダーポリゴン
        for rider, col in self._COLORS.items():
            if rider not in norm_vals:
                continue
            nv = norm_vals[rider]
            xs = [math.cos(angles[i]) * nv[i] for i in range(n)] + \
                 [math.cos(angles[0]) * nv[0]]
            ys = [math.sin(angles[i]) * nv[i] for i in range(n)] + \
                 [math.sin(angles[0]) * nv[0]]
            pw.plot(xs, ys, pen=pg.mkPen(col, width=2.5), name=rider,
                    fillLevel=0, brush=pg.mkBrush(col + "28"))

        pw.setXRange(-1.4, 1.4, padding=0)
        pw.setYRange(-1.4, 1.4, padding=0)

    def _draw_trend(self, df):
        """Panel 4: Lap 推移 (Pitch / Heave)。最新ランを自動選択。"""
        pg = self._pg
        pw = self._pw_trend
        pw.clear()
        pw.setLabel("left",   "mm")
        pw.setLabel("bottom", "Lap No")
        pw.addLegend()
        if "pitch" not in df.columns or "lap_no" not in df.columns:
            return
        for rider, col in self._COLORS.items():
            if "rider" not in df.columns:
                break
            rs = df[df["rider"] == rider].sort_values("lap_no")
            if rs.empty:
                continue
            rs = rs.dropna(subset=["lap_no", "pitch", "heave"])
            if rs.empty:
                continue
            laps = rs["lap_no"].values.tolist()
            pw.plot(laps, rs["pitch"].values.tolist(),
                    pen=pg.mkPen(col, width=2),
                    symbol="o", symbolSize=5, symbolBrush=pg.mkBrush(col),
                    name=f"{rider} Pitch")
            pw.plot(laps, rs["heave"].values.tolist(),
                    pen=pg.mkPen(col, width=1.5, style=Qt.PenStyle.DashLine),
                    symbol="t", symbolSize=5, symbolBrush=pg.mkBrush(col + "80"),
                    name=f"{rider} Heave")
        # Pitch=0 ライン
        pw.addItem(pg.InfiniteLine(pos=0, angle=0,
                   pen=pg.mkPen("#888", width=1, style=Qt.PenStyle.DotLine)))


class MainWindow(QMainWindow):
    def __init__(self, db: WorkbenchDB):
        super().__init__()
        self._db = db
        self.setWindowTitle("TS24 Engineer Workbench v2.0")
        self.resize(1400, 800)
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 上部ツールバー ────────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(40)
        toolbar.setStyleSheet("background: #1E1E1E; border-bottom: 1px solid #333;")
        tb_lay = QHBoxLayout(toolbar)
        tb_lay.setContentsMargins(8, 4, 8, 4)

        lbl_title = QLabel("TS24 Engineer Workbench v2.0")
        lbl_title.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color: #FFFFFF;")
        tb_lay.addWidget(lbl_title)
        tb_lay.addStretch()

        self._lbl_status = QLabel("")
        self._lbl_status.setStyleSheet("color: #888; font-size: 10px;")
        tb_lay.addWidget(self._lbl_status)

        root.addWidget(toolbar)

        # ── タブエリア ────────────────────────────────────────────────────────────
        self._tabs = QTabWidget()

        self._tab_browser = RunBrowserTab(db=self._db)
        self._tab_quick   = QuickLogTab(db=self._db)
        self._tab_problem = ProblemLogTab(db=self._db)
        self._tab_setup   = SetupDecisionTab(db=self._db)
        self._tab_posture = PostureAnalysisTab(db=self._db)

        # Run Browser → Quick Log / Problem Log / Setup Decision に連携
        self._tab_browser.set_on_run_selected(self._on_run_selected)

        self._tabs.addTab(self._tab_browser, "🗺️ Run Browser")
        self._tabs.addTab(self._tab_quick,   "⚡ Quick Log")
        self._tabs.addTab(self._tab_problem, "📋 Problem Log")
        self._tabs.addTab(self._tab_setup,   "🔧 Setup Decision")
        self._tabs.addTab(self._tab_posture, "📈 Trend Analysis")

        root.addWidget(self._tabs)

        # ── DB ファイル監視 ──────────────────────────────────────────────────────
        self._fs_watcher = QFileSystemWatcher([str(DB_PATH)])
        self._fs_watcher.fileChanged.connect(self._on_db_changed)

    def _on_db_changed(self, _path: str) -> None:
        """DB ファイルが更新されたとき全タブを自動リフレッシュする。"""
        self._lbl_status.setText("🔄 DB更新検出 — リフレッシュ中…")
        for tab in (self._tab_browser, self._tab_quick,
                    self._tab_problem, self._tab_setup, self._tab_posture):
            try:
                tab.refresh()
            except Exception:
                pass
        # watchdog が rename-replace でファイルを再作成する場合、パスが消える
        if str(DB_PATH) not in self._fs_watcher.files():
            self._fs_watcher.addPath(str(DB_PATH))
        self._lbl_status.setText("✅ リフレッシュ完了")

    def _on_run_selected(self, run_id: str, meta: dict) -> None:
        """RunBrowserでRunが選択されたとき全タブに伝播する。"""
        self._tab_quick.set_run(run_id, meta)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)
        self._lbl_status.setText(
            f"Run: {run_id}  |  {meta.get('circuit','')}  {meta.get('rider','')}  "
            f"Run#{meta.get('run_no','')}"
        )
        self._tabs.setCurrentWidget(self._tab_problem)




# ════════════════════════════════════════════════════════════════════
# エントリーポイント
# ════════════════════════════════════════════════════════════════════

def main():
    if not DB_PATH.exists():
        app = QApplication(sys.argv)
        QMessageBox.critical(
            None, "DB not found",
            f"ts24_unified.db が見つかりません:\n{DB_PATH}\n\n"
            "02_DATABASE フォルダを確認してください。",
        )
        sys.exit(1)

    db = WorkbenchDB(DB_PATH)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Arial", 10))

    window = MainWindow(db)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
