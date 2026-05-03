"""
ts24_workbench.py — TS24 Engineer Workbench v0.1
=================================================
PyQt6製ローカルデスクトップアプリ。
ラップデータを見ながら Problem Log / Setup Decision を DB に記録する作業台。

読み取り: ts24_unified.db, lap_overlay_data.json, turn_templates.json
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
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem,
    QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QLineEdit, QFrame, QScrollArea,
)

# ── パス設定 ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DB_PATH      = SCRIPT_DIR.parent / "02_DATABASE" / "ts24_unified.db"
OVERLAY_JSON = SCRIPT_DIR / "lap_overlay_data.json"
TEMPLATES_JSON = SCRIPT_DIR / "turn_templates.json"

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
# DB アクセス層
# ════════════════════════════════════════════════════════════════════

class WorkbenchDB:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

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
                    """SELECT run_id, circuit, session_type, rider, run_no, best_lap_s
                       FROM runs WHERE circuit = ? ORDER BY session_type, rider, run_no""",
                    (circuit,),
                )
            else:
                cur = conn.execute(
                    """SELECT run_id, circuit, session_type, rider, run_no, best_lap_s
                       FROM runs ORDER BY circuit, session_type, rider, run_no"""
                )
            return [dict(r) for r in cur.fetchall()]

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
                """SELECT run_id, session_type, run_no FROM runs
                   WHERE circuit = ? AND rider = ? AND run_id != ?
                   ORDER BY session_type, run_no""",
                (row["circuit"], row["rider"], run_id),
            )
            return [dict(r) for r in cur2.fetchall()]

    def get_problem_logs(self, run_id: str) -> list[dict]:
        with self._conn() as conn:
            cur = conn.execute(
                """SELECT * FROM problem_log WHERE run_id = ?
                   ORDER BY created_at DESC""",
                (run_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def add_problem_log(self, data: dict) -> int:
        with self._conn() as conn:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                """INSERT INTO problem_log
                   (run_id, round, circuit, session, rider, run_no, lap_no,
                    corner, phase, problem_tag, description, severity, source,
                    export_status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("run_id"), data.get("round"), data.get("circuit"),
                    data.get("session"), data.get("rider"), data.get("run_no"),
                    data.get("lap_no"), data.get("corner"), data.get("phase"),
                    data.get("problem_tag"), data.get("description"),
                    data.get("severity", "MEDIUM"), data.get("source", "OBSERVATION"),
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


# ════════════════════════════════════════════════════════════════════
# 波形ビュー (Speed / Brake / Gas — Reference only)
# ════════════════════════════════════════════════════════════════════

class WaveformView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlay_data: list[dict] = []
        self._templates: dict = {}
        self._circuit: str = ""
        self._setup_ui()
        self._load_static_data()

    def _setup_ui(self):
        try:
            import pyqtgraph as pg
            self._pg = pg
            self._has_pg = True
        except ImportError:
            self._has_pg = False

        layout = QVBoxLayout(self)

        # Reference warning
        warn = QLabel("⚠️  Reference only — time-normalized data, not track-position aligned.")
        warn.setStyleSheet("color: #D83B01; font-style: italic; padding: 4px;")
        layout.addWidget(warn)

        # Lap selectors
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Lap A:"))
        self._combo_a = QComboBox()
        self._combo_a.setMinimumWidth(260)
        sel_row.addWidget(self._combo_a)
        sel_row.addSpacing(16)
        sel_row.addWidget(QLabel("Lap B:"))
        self._combo_b = QComboBox()
        self._combo_b.setMinimumWidth(260)
        sel_row.addWidget(self._combo_b)
        btn = QPushButton("表示更新")
        btn.clicked.connect(self._draw)
        sel_row.addWidget(btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        if self._has_pg:
            pg = self._pg
            pg.setConfigOption("background", "w")
            pg.setConfigOption("foreground", "k")
            self._plot_widget = pg.GraphicsLayoutWidget()
            self._p_speed = self._plot_widget.addPlot(row=0, col=0, title="Speed (km/h)")
            self._p_brake = self._plot_widget.addPlot(row=1, col=0, title="Brake (bar)")
            self._p_gas   = self._plot_widget.addPlot(row=2, col=0, title="Gas (%)")
            for p in (self._p_speed, self._p_brake, self._p_gas):
                p.setLabel("bottom", "Lap Progress")
                p.showGrid(x=True, y=True, alpha=0.3)
                p.setXRange(0, 1)
            # Link X axes
            self._p_brake.setXLink(self._p_speed)
            self._p_gas.setXLink(self._p_speed)
            layout.addWidget(self._plot_widget)
        else:
            layout.addWidget(QLabel(
                "pyqtgraph が見つかりません。\n"
                "pip install pyqtgraph でインストールしてください。"
            ))

    def _load_static_data(self):
        if OVERLAY_JSON.exists():
            try:
                self._overlay_data = json.loads(OVERLAY_JSON.read_text(encoding="utf-8"))
            except Exception:
                self._overlay_data = []
        if TEMPLATES_JSON.exists():
            try:
                self._templates = json.loads(TEMPLATES_JSON.read_text(encoding="utf-8"))
            except Exception:
                self._templates = {}

    def set_run(self, run_id: str, circuit: str):
        self._circuit = circuit
        self._combo_a.clear()
        self._combo_b.clear()
        if not self._overlay_data:
            return
        laps = [r for r in self._overlay_data if r.get("run_id") == run_id]
        labels = [
            f"Lap {r.get('lap_no','?')}  {r.get('lap_time_s','?')}s"
            for r in laps
        ]
        self._combo_a.addItems(labels)
        self._combo_b.addItems(labels)
        if len(labels) > 1:
            self._combo_b.setCurrentIndex(1)
        self._laps_cache = laps

    def set_csv_laps(self, csv_laps: list[dict]):
        """CSV インポートからのラップデータを波形に設定する（参考値）。"""
        self._laps_cache = csv_laps
        self._circuit = ""
        self._combo_a.clear()
        self._combo_b.clear()
        labels = [
            f"CSV Lap {r.get('lap_no', i + 1)}  ({r.get('lap_time_s', '?')}s)"
            for i, r in enumerate(csv_laps)
        ]
        self._combo_a.addItems(labels)
        self._combo_b.addItems(labels)
        if len(labels) > 1:
            self._combo_b.setCurrentIndex(1)

    def _draw(self):
        if not self._has_pg or not hasattr(self, "_laps_cache") or not self._laps_cache:
            return
        pg = self._pg
        import numpy as np

        ia = self._combo_a.currentIndex()
        ib = self._combo_b.currentIndex()
        if ia < 0 or ia >= len(self._laps_cache):
            return
        lap_a = self._laps_cache[ia]
        lap_b = self._laps_cache[ib] if (ib >= 0 and ib < len(self._laps_cache)) else None

        colors = {"a": pg.mkPen("#0078D4", width=2), "b": pg.mkPen("#E74C3C", width=1.5)}

        for p in (self._p_speed, self._p_brake, self._p_gas):
            p.clear()

        def _normalize_x(xs_raw):
            """ラン全体の連続progress → ラップ内 0.0–1.0 に正規化する。"""
            arr = np.array(xs_raw, dtype=float)
            x_min, x_max = arr.min(), arr.max()
            if x_max > x_min:
                return (arr - x_min) / (x_max - x_min)
            return np.zeros_like(arr)

        def _get_channel(lap, channel):
            """チャンネルデータを取得。channels dict 内とフラット両方に対応。"""
            ch = lap.get("channels") or {}
            data = ch.get(channel) or lap.get(channel)
            return data

        def _plot(lap, label, pen, channel, plot_obj):
            xs_raw = _get_channel(lap, "lap_progress")
            ys_raw = _get_channel(lap, channel)
            if not xs_raw or not ys_raw:
                return
            if len(xs_raw) != len(ys_raw):
                return
            xs = _normalize_x(xs_raw)
            ys = np.array(ys_raw, dtype=float)
            plot_obj.plot(x=xs, y=ys, pen=pen, name=label)

        for ch, p in [("speed", self._p_speed), ("brake", self._p_brake), ("gas", self._p_gas)]:
            _plot(lap_a, f"A Lap{lap_a.get('lap_no','')}", colors["a"], ch, p)
            if lap_b:
                _plot(lap_b, f"B Lap{lap_b.get('lap_no','')}", colors["b"], ch, p)

        # Y auto-range を有効化してから X を 0–1 に固定
        for p in (self._p_speed, self._p_brake, self._p_gas):
            p.enableAutoRange(axis="y")
            p.setXRange(0.0, 1.0, padding=0.02)

        # Turn markers — list 形式・dict 形式両対応
        tmpl_raw = self._templates.get(self._circuit)
        if tmpl_raw is None:
            # 大文字小文字を無視して検索
            for k, v in self._templates.items():
                if k.upper() == self._circuit.upper():
                    tmpl_raw = v
                    break
        if isinstance(tmpl_raw, dict):
            # {"T1": {"progress": 0.05, ...}, ...} 形式
            tmpl_turns = [{"name": k, **v} for k, v in tmpl_raw.items()
                          if isinstance(v, dict)]
        elif isinstance(tmpl_raw, list):
            tmpl_turns = tmpl_raw
        else:
            tmpl_turns = []

        for turn in tmpl_turns:
            prog = turn.get("progress")
            if prog is None:
                continue
            for p in (self._p_speed, self._p_brake, self._p_gas):
                line = pg.InfiniteLine(
                    pos=float(prog), angle=90,
                    pen=pg.mkPen("#107C10", width=1, style=Qt.PenStyle.DashLine),
                    label=str(turn.get("name", "")),
                    labelOpts={"color": "#107C10", "position": 0.9,
                               "rotateAxis": (1, 0)},
                )
                p.addItem(line)


# ════════════════════════════════════════════════════════════════════
# Problem Log タブ
# ════════════════════════════════════════════════════════════════════

class ProblemLogTab(QWidget):
    def __init__(self, db: WorkbenchDB, parent=None):
        super().__init__(parent)
        self._db = db
        self._run_id: str = ""
        self._run_meta: dict = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # ── 一覧テーブル ──────────────────────────────────
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["ID", "Corner", "Phase", "Tag", "Description", "Severity", "Lap"]
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 60)
        self._table.setColumnWidth(2, 60)
        self._table.setColumnWidth(3, 140)
        self._table.setColumnWidth(4, 280)
        self._table.setColumnWidth(5, 70)
        self._table.setColumnWidth(6, 50)
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

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run.setText(run_id or "（未選択）")
        self._refresh_table()

    def _refresh_table(self):
        rows = self._db.get_problem_logs(self._run_id) if self._run_id else []
        self._table.setRowCount(0)
        for r in rows:
            ri = self._table.rowCount()
            self._table.insertRow(ri)
            for ci, val in enumerate([
                r.get("problem_id", ""),
                r.get("corner", "—"),
                r.get("phase", "—"),
                r.get("problem_tag", ""),
                r.get("description", ""),
                r.get("severity", ""),
                r.get("lap_no", "—"),
            ]):
                self._table.setItem(ri, ci, QTableWidgetItem(str(val) if val is not None else "—"))

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
            "session":    self._run_meta.get("session_type"),
            "rider":      self._run_meta.get("rider"),
            "run_no":     self._run_meta.get("run_no"),
            "lap_no":     lap_val,
            "corner":     corner_val,
            "phase":      self._combo_phase.currentText(),
            "problem_tag": self._combo_tag.currentText(),
            "description": self._txt_desc.toPlainText().strip(),
            "severity":   self._combo_sev.currentText(),
            "source":     self._combo_src.currentText(),
        }
        self._db.add_problem_log(data)
        self._clear_form()
        self._refresh_table()

    def _clear_form(self):
        self._spin_lap.setValue(0)
        self._combo_corner.setCurrentIndex(0)
        self._combo_phase.setCurrentIndex(0)
        self._combo_tag.setCurrentIndex(0)
        self._txt_desc.clear()
        self._combo_sev.setCurrentText("MEDIUM")
        self._combo_src.setCurrentIndex(0)

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

    def set_run(self, run_id: str, meta: dict):
        self._run_id = run_id
        self._run_meta = meta
        self._lbl_run_from.setText(run_id or "（未選択）")
        self._combo_run_to.clear()
        self._combo_run_to.addItem("NEXT（未定）")
        next_runs = self._db.get_next_runs(run_id) if run_id else []
        for nr in next_runs:
            self._combo_run_to.addItem(
                f"{nr['run_id']}  ({nr['session_type']} R{nr['run_no']})",
                userData=nr["run_id"],
            )
        self._refresh_table()

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
            "session":        self._run_meta.get("session_type"),
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

    def _clear_form(self):
        self._combo_chg_type.setCurrentIndex(0)
        self._combo_comp.setCurrentIndex(0)
        self._edit_from.clear()
        self._edit_to.clear()
        self._txt_rationale.clear()
        self._txt_expected.clear()
        self._combo_result.setCurrentText("UNKNOWN")


# ════════════════════════════════════════════════════════════════════
# 2D CSV Import タブ
# ════════════════════════════════════════════════════════════════════

class CsvImportTab(QWidget):
    """2Dロガー CSVデータ インポートタブ。

    06_CSV/ フォルダからCSVを読み込み、チャンネルをマッピングして
    WaveformView に送る（§0 データソース原則: 参考値扱い、権威源ではない）。

    確定チャンネル (CLAUDE.md §5):
      BRAKE_FRONT (-0.6~0.3 Bar), GAS (0~6%), dTPS_A (-10~100),
      SUSP_FRONT (20~140mm), SUSP_REAR (5~50mm), Speed (km/h)
    """

    _AUTO_DETECT: list[tuple[list[str], str]] = [
        (["time", "timestamp", "elapsed", "t_lap", "sec"],       "time"),
        (["lap_no", "lap_num", "lap_marker", "lapno", "lap"],    "lap"),
        (["speed", "gps_speed", "velocity", "v_gps", "spd"],    "speed"),
        (["brake_front", "brakefront", "brake_f", "bf", "brake"], "brake"),
        (["gas", "throttle", "tps", "thr"],                      "gas"),
        (["dtps_a", "dtps"],                                      "dTPS_A"),
        (["susp_front", "suspf", "susp_f", "front_susp", "fork"], "susp_front"),
        (["susp_rear",  "suspr", "susp_r", "rear_susp",  "shock"], "susp_rear"),
    ]

    _CHANNEL_OPTIONS = [
        "(ignore)", "time", "lap", "speed", "brake", "gas",
        "dTPS_A", "susp_front", "susp_rear",
    ]

    def __init__(self, waveform_view: "WaveformView", parent=None):
        super().__init__(parent)
        self._waveform = waveform_view
        self._df: "pd.DataFrame | None" = None
        self._col_combos: dict[str, QComboBox] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # §0 reference warning
        warn = QLabel(
            "⚠️  Reference only（§0 データソース原則）"
            " — CSV データは参考値です。権威源（ts24 original database / Excel Report）ではありません。"
        )
        warn.setStyleSheet("color: #D83B01; font-style: italic; padding: 4px;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        # File select
        file_row = QHBoxLayout()
        btn_browse = QPushButton("📁  CSV を開く")
        btn_browse.clicked.connect(self._browse_csv)
        self._lbl_file = QLabel("ファイル未選択")
        self._lbl_file.setStyleSheet("color: #444;")
        file_row.addWidget(btn_browse)
        file_row.addWidget(self._lbl_file, stretch=1)
        layout.addLayout(file_row)

        self._lbl_info = QLabel("")
        self._lbl_info.setStyleSheet("color: #0078D4; font-size: 10px;")
        layout.addWidget(self._lbl_info)

        # Channel mapping (scrollable)
        map_label = QLabel("▼ チャンネルマッピング（自動検出・手動修正可）")
        map_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(map_label)

        self._map_inner = QWidget()
        self._map_layout = QFormLayout(self._map_inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._map_inner)
        scroll.setMaximumHeight(180)
        layout.addWidget(scroll)

        # Lap segmentation
        seg_row = QHBoxLayout()
        seg_row.addWidget(QLabel("ラップ分割:"))
        self._combo_seg = QComboBox()
        self._combo_seg.addItem("全体を1ラップとして扱う", userData=None)
        seg_row.addWidget(self._combo_seg, stretch=1)
        layout.addLayout(seg_row)

        # Preview
        prev_label = QLabel("▼ データプレビュー（先頭 100 行）")
        prev_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(prev_label)

        self._preview_table = QTableWidget(0, 0)
        self._preview_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._preview_table, stretch=1)

        # Send button
        btn_row = QHBoxLayout()
        self._btn_send = QPushButton("📊  波形に送る")
        self._btn_send.setEnabled(False)
        self._btn_send.clicked.connect(self._send_to_waveform)
        self._btn_send.setStyleSheet(
            "QPushButton { background: #0078D4; color: white; padding: 6px 16px;"
            " border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #106EBE; }"
            "QPushButton:disabled { background: #ccc; color: #888; }"
        )
        btn_row.addWidget(self._btn_send)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    # ── CSV 読み込み ─────────────────────────────────────────────────

    def _browse_csv(self):
        csv_dir = SCRIPT_DIR.parent / "06_CSV"
        if not csv_dir.exists():
            csv_dir = SCRIPT_DIR.parent
        path, _ = QFileDialog.getOpenFileName(
            self, "CSV ファイルを選択", str(csv_dir),
            "CSV Files (*.csv);;All Files (*.*)",
        )
        if not path:
            return
        self._lbl_file.setText(Path(path).name)
        self._load_csv(Path(path))

    def _load_csv(self, path: Path):
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(path, encoding="shift_jis")
            except Exception as e:
                QMessageBox.critical(self, "CSV 読み込みエラー", str(e))
                return
        except Exception as e:
            QMessageBox.critical(self, "CSV 読み込みエラー", str(e))
            return

        self._df = df
        n_rows, n_cols = df.shape
        self._lbl_info.setText(f"{n_rows} 行 × {n_cols} 列 を読み込みました。")

        # Rebuild channel mapping UI
        while self._map_layout.rowCount():
            self._map_layout.removeRow(0)
        self._col_combos.clear()

        for col in df.columns:
            combo = QComboBox()
            combo.addItems(self._CHANNEL_OPTIONS)
            auto = self._auto_detect(col)
            if auto in self._CHANNEL_OPTIONS:
                combo.setCurrentText(auto)
            self._col_combos[col] = combo
            self._map_layout.addRow(f"{col}:", combo)

        # Rebuild lap segmentation combo
        lap_cols = [c for c in df.columns if self._auto_detect(c) == "lap"]
        self._combo_seg.clear()
        for c in lap_cols:
            self._combo_seg.addItem(f"'{c}' カラムで分割", userData=c)
        self._combo_seg.addItem("全体を1ラップとして扱う", userData=None)

        # Preview
        preview = df.head(100)
        self._preview_table.setColumnCount(len(preview.columns))
        self._preview_table.setHorizontalHeaderLabels(list(preview.columns))
        self._preview_table.setRowCount(len(preview))
        for ri, row_data in enumerate(preview.itertuples(index=False)):
            for ci, val in enumerate(row_data):
                self._preview_table.setItem(ri, ci, QTableWidgetItem(str(val)))
        self._preview_table.resizeColumnsToContents()

        self._btn_send.setEnabled(True)

    def _auto_detect(self, col_name: str) -> str:
        lower = col_name.lower().replace(" ", "_")
        for keywords, target in self._AUTO_DETECT:
            for kw in keywords:
                if kw in lower:
                    return target
        return "(ignore)"

    # ── 波形に送る ────────────────────────────────────────────────────

    def _send_to_waveform(self):
        if self._df is None:
            return

        # Build channel → col mapping (last assignment wins if duplicate)
        channel_to_col: dict[str, str] = {}
        for col, combo in self._col_combos.items():
            ch = combo.currentText()
            if ch != "(ignore)":
                channel_to_col[ch] = col

        if "time" not in channel_to_col:
            QMessageBox.warning(
                self, "マッピング不足",
                "'time' チャンネルが割り当てられていません。\n"
                "X 軸に使う時間カラムを 'time' にマッピングしてください。",
            )
            return

        df = self._df.copy()

        # Lap segmentation
        seg_col = self._combo_seg.currentData()
        if seg_col and seg_col in df.columns:
            laps_df_list = [grp.reset_index(drop=True) for _, grp in df.groupby(df[seg_col])]
        else:
            laps_df_list = [df.reset_index(drop=True)]

        import numpy as np

        csv_laps: list[dict] = []
        for lap_no, lap_df in enumerate(laps_df_list, start=1):
            time_col = channel_to_col["time"]
            try:
                t_vals = lap_df[time_col].astype(float).values
            except Exception:
                continue
            t_min, t_max = float(t_vals.min()), float(t_vals.max())
            if t_max > t_min:
                progress = ((t_vals - t_min) / (t_max - t_min)).tolist()
            else:
                progress = [0.0] * len(t_vals)

            channels: dict[str, list] = {"lap_progress": progress}
            for ch_name, col_name in channel_to_col.items():
                if ch_name in ("time", "lap"):
                    continue
                if col_name not in lap_df.columns:
                    continue
                try:
                    channels[ch_name] = lap_df[col_name].astype(float).tolist()
                except Exception:
                    channels[ch_name] = [str(v) for v in lap_df[col_name]]

            csv_laps.append({
                "lap_no":     lap_no,
                "lap_time_s": round(t_max - t_min, 3),
                "channels":   channels,
            })

        if not csv_laps:
            QMessageBox.warning(self, "データなし", "ラップデータが生成できませんでした。")
            return

        self._waveform.set_csv_laps(csv_laps)
        QMessageBox.information(
            self, "送信完了",
            f"{len(csv_laps)} ラップを波形ビューに送りました。\n"
            "「📊 波形 (Reference)」タブに切り替えて確認してください。",
        )


# ════════════════════════════════════════════════════════════════════
# メインウィンドウ
# ════════════════════════════════════════════════════════════════════

class MainWindow(QMainWindow):
    def __init__(self, db: WorkbenchDB):
        super().__init__()
        self._db = db
        self._run_meta: dict = {}
        self.setWindowTitle("TS24 Engineer Workbench v0.1")
        self.resize(1400, 800)
        self._setup_ui()
        self._load_circuits()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ── 左パネル ─────────────────────────────────────
        left = QWidget()
        left.setFixedWidth(280)
        left_lay = QVBoxLayout(left)

        title = QLabel("TS24 Engineer Workbench")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        left_lay.addWidget(title)

        lbl_circ = QLabel("Circuit:")
        self._combo_circuit = QComboBox()
        self._combo_circuit.currentTextChanged.connect(self._on_circuit_changed)
        left_lay.addWidget(lbl_circ)
        left_lay.addWidget(self._combo_circuit)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabel("Session / Rider / Run")
        self._tree.itemClicked.connect(self._on_run_selected)
        left_lay.addWidget(self._tree, stretch=1)

        self._lbl_status = QLabel("")
        self._lbl_status.setWordWrap(True)
        self._lbl_status.setStyleSheet("color: #666; font-size: 10px;")
        left_lay.addWidget(self._lbl_status)

        # ── 右パネル (タブ) ───────────────────────────────
        self._tabs = QTabWidget()
        self._tab_wave    = WaveformView()
        self._tab_problem = ProblemLogTab(db=self._db)
        self._tab_setup   = SetupDecisionTab(db=self._db)
        self._tab_csv     = CsvImportTab(waveform_view=self._tab_wave)
        self._tabs.addTab(self._tab_wave,    "📊 波形 (Reference)")
        self._tabs.addTab(self._tab_problem, "⚠️  Problem Log")
        self._tabs.addTab(self._tab_setup,   "🔧 Setup Decision")
        self._tabs.addTab(self._tab_csv,     "📥 2D CSV Import")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        root.addWidget(splitter)

    def _load_circuits(self):
        try:
            circuits = self._db.get_circuits()
        except Exception as e:
            self._lbl_status.setText(f"DB error: {e}")
            circuits = []
        self._combo_circuit.blockSignals(True)
        self._combo_circuit.clear()
        self._combo_circuit.addItems(circuits)
        self._combo_circuit.blockSignals(False)
        if circuits:
            self._on_circuit_changed(circuits[0])

    def _on_circuit_changed(self, circuit: str):
        self._tree.clear()
        try:
            runs = self._db.get_runs(circuit=circuit)
        except Exception as e:
            self._lbl_status.setText(f"DB error: {e}")
            return

        # Group by session_type
        by_session: dict[str, list[dict]] = {}
        for r in runs:
            s = r.get("session_type") or "—"
            by_session.setdefault(s, []).append(r)

        for session, run_list in sorted(by_session.items()):
            sess_item = QTreeWidgetItem([session])
            sess_item.setFont(0, QFont("Arial", 10, QFont.Weight.Bold))
            for r in run_list:
                best = r.get("best_lap_s")
                best_str = f"{best:.3f}s" if best else "—"
                label = f"{r.get('rider','')}  R{r.get('run_no','')}  [{best_str}]"
                run_item = QTreeWidgetItem([label])
                run_item.setData(0, Qt.ItemDataRole.UserRole, r)
                sess_item.addChild(run_item)
            self._tree.addTopLevelItem(sess_item)
        self._tree.expandAll()

    def _on_run_selected(self, item: QTreeWidgetItem, _col: int):
        meta = item.data(0, Qt.ItemDataRole.UserRole)
        if not meta:
            return
        run_id = meta.get("run_id", "")
        self._run_meta = meta
        circuit = self._combo_circuit.currentText()
        self._lbl_status.setText(f"Selected: {run_id}")
        self._tab_wave.set_run(run_id, circuit)
        self._tab_problem.set_run(run_id, meta)
        self._tab_setup.set_run(run_id, meta)


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
