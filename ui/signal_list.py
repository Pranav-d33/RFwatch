from PySide6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem, QPushButton
from PySide6.QtCore import Signal

class SignalList(QTableWidget):
	# Signal emitted when a row is clicked: emitter_selected.emit(emitter_id)
	emitter_selected = Signal(str)
	# Signal emitted when TX button is clicked: tx_requested.emit(freq_hz)
	tx_requested = Signal(float)

	def __init__(self, theme):
		super().__init__(0, 5)
		self.theme = theme
		self.transmission_enabled = False
		self._is_transmitting = False

		self.setHorizontalHeaderLabels([
			"Frequency",
			"Bandwidth",
			"Power",
			"Duration",
			"Status"
		])

		self.verticalHeader().setVisible(False)
		self.horizontalHeader().setStretchLastSection(True)
		self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
		self.setAlternatingRowColors(True)
		self.setStyleSheet(f"""
			QTableWidget {{
				background-color: {theme.get("background")};
				color: {theme.get("text")};
				gridline-color: #30363d;
			}}
		""")

		self.emitter_rows = {}  # emitter_id -> row index
		self.row_emitter_ids = {}  # row index -> emitter_id
		self.emitters = {}  # emitter_id -> emitter object
		
		# Connect row click signal
		self.cellClicked.connect(self._on_cell_clicked)

	def set_transmission_enabled(self, enabled):
		"""Enable or disable transmission features."""
		if self.transmission_enabled == enabled:
			return
		self.transmission_enabled = enabled
		
		# Update column count and headers
		if enabled:
			self.setColumnCount(6)
			self.setHorizontalHeaderLabels([
				"Frequency",
				"Bandwidth", 
				"Power",
				"Duration",
				"Status",
				"TX"
			])
		else:
			self.setColumnCount(5)
			self.setHorizontalHeaderLabels([
				"Frequency",
				"Bandwidth",
				"Power", 
				"Duration",
				"Status"
			])
		
		# Refresh all existing rows
		for eid, row in self.emitter_rows.items():
			event = self.events.get(eid)
			if event:
				self._populate_row(row, event, event.active)

	def update_tx_buttons(self, is_transmitting):
		"""Update all TX button texts based on transmission state."""
		if not self.transmission_enabled:
			return
			
		self._is_transmitting = is_transmitting
		for eid, row in self.emitter_rows.items():
			self._update_tx_button_for_row(row, is_transmitting)

	def clear_all(self):
		"""Clear all rows and internal caches."""
		self.setRowCount(0)
		self.clearContents()
		self.emitter_rows.clear()
		self.row_emitter_ids.clear()
		self.emitters.clear()

	def update_emitter(self, emitter):
		eid = emitter.id
		if eid not in self.emitter_rows:
			row = self.rowCount()
			self.insertRow(row)
			self.emitter_rows[eid] = row
			self.row_emitter_ids[row] = eid
		else:
			row = self.emitter_rows[eid]
		self.emitters[eid] = emitter
		self._populate_row(row, emitter, active=True)

	def close_emitter(self, emitter):
		eid = emitter.id
		row = self.emitter_rows.get(eid)
		if row is None:
			return
		self.emitters[eid] = emitter
		self._populate_row(row, emitter, active=False)

	def _on_cell_clicked(self, row, col):
		"""Handle row click: emit emitter_selected signal."""
		if row in self.row_emitter_ids:
			emitter_id = self.row_emitter_ids[row]
			self.emitter_selected.emit(emitter_id)

	def _populate_row(self, row, emitter, active):
		from PySide6 import QtGui
		features = getattr(emitter, 'features', {}) or {}
		center_hz = float(features.get('frequency', {}).get('center_hz', 0.0) or 0.0)
		bw_hz = float(features.get('bandwidth', {}).get('mean_hz', 0.0) or 0.0)
		center_mhz = center_hz / 1e6
		bw_str = f"{bw_hz/1e6:.2f} MHz" if bw_hz >= 1e6 else f"{bw_hz/1e3:.1f} kHz"
		power_db = float(features.get('power', {}).get('avg_power', 0.0) or 0.0)
		self.setItem(row, 0, QTableWidgetItem(f"{center_mhz:.3f} MHz"))
		self.setItem(row, 1, QTableWidgetItem(bw_str))
		self.setItem(row, 2, QTableWidgetItem(f"{power_db:.1f} dB (rel)"))
		# Show emitter lifetime instead of event duration.
		lifetime_s = 0.0
		try:
			lifetime_s = float(getattr(emitter, 'last_update_ts', 0.0) or 0.0) - float(getattr(emitter, 'created_ts', 0.0) or 0.0)
			if lifetime_s < 0:
				lifetime_s = 0.0
		except Exception:
			lifetime_s = 0.0
		self.setItem(row, 3, QTableWidgetItem(f"{lifetime_s:.2f}s"))
		evt_count = int(features.get('emitter', {}).get('event_count', getattr(emitter, 'event_count', 0) or 0) or 0)
		activity = float(features.get('emitter', {}).get('activity_fraction', 0.0) or 0.0)
		status = "ACTIVE" if active else "ENDED"
		self.setItem(row, 4, QTableWidgetItem(f"{status} • {evt_count} events • {activity*100:.0f}%"))

		if self.transmission_enabled:
			tx_btn = QPushButton("Stop TX" if self._is_transmitting else "TX")
			tx_btn.clicked.connect(lambda _=False, f=center_hz: self.tx_requested.emit(f))
			if self._is_transmitting:
				tx_btn.setStyleSheet("background-color: red; color: white;")
			self.setCellWidget(row, 5, tx_btn)

		if not active:
			for col in range(self.columnCount()):
				item = self.item(row, col)
				if item:
					item.setForeground(QtGui.QColor("#8b949e"))

	def _update_tx_button_for_row(self, row, is_transmitting):
		"""Update the TX button for a specific row."""
		if self.transmission_enabled and self.columnCount() > 5:
			btn = self.cellWidget(row, 5)
			if btn and isinstance(btn, QPushButton):
				if is_transmitting:
					btn.setText("Stop TX")
					btn.setStyleSheet("background-color: red; color: white;")
				else:
					btn.setText("TX")
					btn.setStyleSheet("")
