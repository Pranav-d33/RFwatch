from __future__ import annotations

import datetime
from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QPushButton
from PySide6.QtCore import Signal


class ScanResultsTable(QTableWidget):
	# Signal emitted when TX button is clicked: tx_requested.emit(freq_hz)
	tx_requested = Signal(float)

	"""Simple scan-step results table.

	Shows per-step counts and high-level summary only (no cross-step merging).
	"""

	def __init__(self, theme):
		super().__init__(0, 5)
		self.theme = theme
		self.transmission_enabled = False
		self._is_transmitting = False
		self._results = []
		self._render_headers()
		self.verticalHeader().setVisible(False)
		self.horizontalHeader().setStretchLastSection(True)
		self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		self.setAlternatingRowColors(True)
		self.setStyleSheet(f"""
			QTableWidget {{
				background-color: {theme.get('background')};
				color: {theme.get('text')};
				gridline-color: #30363d;
			}}
		""")

	def _render_headers(self):
		if self.transmission_enabled:
			self.setColumnCount(6)
			self.setHorizontalHeaderLabels([
				"Center",
				"Dwell",
				"Emitters",
				"Strongest",
				"When",
				"TX",
			])
		else:
			self.setColumnCount(5)
			self.setHorizontalHeaderLabels([
				"Center",
				"Dwell",
				"Emitters",
				"Strongest",
				"When",
			])

	def set_transmission_enabled(self, enabled: bool):
		if self.transmission_enabled == enabled:
			return
		self.transmission_enabled = enabled
		self._render_headers()
		self._rerender()

	def update_tx_buttons(self, is_transmitting: bool):
		self._is_transmitting = bool(is_transmitting)
		if not self.transmission_enabled:
			return
		for row in range(self.rowCount()):
			btn = self.cellWidget(row, 5)
			if isinstance(btn, QPushButton):
				btn.setText("Stop TX" if self._is_transmitting else "TX")
				btn.setStyleSheet("background-color: red; color: white;" if self._is_transmitting else "")

	def clear_all(self) -> None:
		self.setRowCount(0)
		self.clearContents()
		self._results.clear()

	def _rerender(self) -> None:
		# Rebuild from stored results so toggling TX updates the table.
		self.setRowCount(0)
		self.clearContents()
		for r in self._results:
			self._append_row(r)

	def add_result(self, scan_result) -> None:
		"""Append a ScanResult row."""
		self._results.append(scan_result)
		self._append_row(scan_result)

	def _append_row(self, scan_result) -> None:
		row = self.rowCount()
		self.insertRow(row)

		center_hz = float(getattr(scan_result, 'center_freq', 0.0) or 0.0)
		center_mhz = center_hz / 1e6
		dwell_s = float(getattr(scan_result, 'dwell_time', 0.0) or 0.0)
		closed_events = getattr(scan_result, 'closed_events', []) or []
		updated_emitters = getattr(scan_result, 'updated_emitters', []) or []
		emitter_count = len(updated_emitters)

		strongest_db = None
		for ev in closed_events:
			try:
				if getattr(ev, 'power_history', None):
					p = max(ev.power_history)
					strongest_db = p if strongest_db is None else max(strongest_db, p)
			except Exception:
				pass

		when_ts = float(getattr(scan_result, 'timestamp', 0.0) or 0.0)
		when_str = "--"
		if when_ts > 0:
			when_str = datetime.datetime.fromtimestamp(when_ts).strftime('%H:%M:%S')

		self.setItem(row, 0, QTableWidgetItem(f"{center_mhz:.3f} MHz"))
		self.setItem(row, 1, QTableWidgetItem(f"{dwell_s:.2f} s"))
		self.setItem(row, 2, QTableWidgetItem(f"{emitter_count:d}"))
		self.setItem(row, 3, QTableWidgetItem("--" if strongest_db is None else f"{strongest_db:.1f} dB (rel)"))
		self.setItem(row, 4, QTableWidgetItem(when_str))

		if self.transmission_enabled:
			btn = QPushButton("Stop TX" if self._is_transmitting else "TX")
			btn.clicked.connect(lambda _=False, f=center_hz: self.tx_requested.emit(f))
			if self._is_transmitting:
				btn.setStyleSheet("background-color: red; color: white;")
			self.setCellWidget(row, 5, btn)
