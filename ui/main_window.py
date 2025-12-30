
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QLineEdit, QMessageBox, QProgressBar,
    QDialog, QCheckBox, QFileDialog, QSlider, QStackedWidget, QApplication,
    QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from .spectrum_view import SpectrumView
from .signal_list import SignalList
from .event_detail import EventDetailView
from .scan_results import ScanResultsTable
from .settings_store import load_settings, save_settings
from core.engine_controller import (
    ControllerState, InspectorConfig, ScannerConfig
)
from core.tx_thread import TxThread
import json
import time


class MainWindow(QMainWindow):
    def __init__(self, event_store, emitter_store, theme, engine_controller):
        super().__init__()
        self.setWindowTitle("RF Inspector (v1)")
        # Compact design for laptops (fits 1080p with room to spare)
        self._design_width = 1100
        self._design_height = 650
        self._design_aspect = self._design_width / self._design_height
        self.event_store = event_store
        self.emitter_store = emitter_store
        self.controller = engine_controller
        self.transmission_enabled = False
        self.tx_thread = None
        self.is_transmitting = False
        self.current_tx_freq_hz = None
        self.hold_display = False
        self._last_detected_ts = 0.0
        self._last_psd_ts = 0.0
        self._last_status_mode = None

        self._settings = load_settings()

        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(4, 4, 4, 4)

        # ====================================================================
        # ROW 1: Mode + Action Buttons (always visible, compact)
        # ====================================================================
        row1 = QHBoxLayout()
        row1.setSpacing(8)

        # Mode selector
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Inspector", "Scanner"])
        self.mode_combo.setFixedWidth(90)
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        row1.addWidget(QLabel("Mode:"))
        row1.addWidget(self.mode_combo)

        row1.addSpacing(10)

        # Start/Stop buttons
        self.start_btn = QPushButton("Start")
        self.start_btn.setFixedWidth(60)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(60)
        self.stop_btn.clicked.connect(self._on_stop)
        self.stop_btn.setEnabled(False)
        row1.addWidget(self.start_btn)
        row1.addWidget(self.stop_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setFixedWidth(50)
        self.clear_btn.clicked.connect(self._on_clear_reset)
        row1.addWidget(self.clear_btn)

        self.hold_btn = QPushButton("Hold")
        self.hold_btn.setFixedWidth(50)
        self.hold_btn.setCheckable(True)
        self.hold_btn.toggled.connect(self._on_hold_toggled)
        row1.addWidget(self.hold_btn)

        row1.addSpacing(10)

        # Sensitivity
        row1.addWidget(QLabel("Sens:"))
        self.sensitivity_slider = QSlider(Qt.Horizontal)
        self.sensitivity_slider.setMinimum(0)
        self.sensitivity_slider.setMaximum(100)
        self.sensitivity_slider.setValue(50)
        self.sensitivity_slider.setFixedWidth(80)
        self.sensitivity_slider.valueChanged.connect(self._on_sensitivity_changed)
        row1.addWidget(self.sensitivity_slider)
        self.sensitivity_label = QLabel("50%")
        self.sensitivity_label.setFixedWidth(30)
        row1.addWidget(self.sensitivity_label)

        row1.addStretch()

        # Export + Settings
        self.export_btn = QPushButton("Export")
        self.export_btn.setFixedWidth(55)
        self.export_btn.clicked.connect(self._on_export_json)
        row1.addWidget(self.export_btn)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.clicked.connect(self._open_settings)
        row1.addWidget(self.settings_btn)

        # Status label
        self.status_label = QLabel("Idle")
        self.status_label.setMinimumWidth(150)
        self.status_label.setStyleSheet("color: #8b949e;")
        row1.addWidget(self.status_label)

        main_layout.addLayout(row1)

        # ====================================================================
        # ROW 2: Mode-Specific Controls (Inspector or Scanner)
        # ====================================================================
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        # Inspector controls
        self.inspector_group = QWidget()
        inspector_layout = QHBoxLayout(self.inspector_group)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(6)
        
        self.inspector_freq = QDoubleSpinBox()
        self.inspector_freq.setMinimum(1)
        self.inspector_freq.setMaximum(6000)
        self.inspector_freq.setValue(1000)
        self.inspector_freq.setSuffix(" MHz")
        self.inspector_freq.setFixedWidth(100)
        inspector_layout.addWidget(QLabel("Freq:"))
        inspector_layout.addWidget(self.inspector_freq)

        self.inspector_bw = QDoubleSpinBox()
        self.inspector_bw.setMinimum(0.1)
        self.inspector_bw.setMaximum(20)
        self.inspector_bw.setValue(20)
        self.inspector_bw.setSuffix(" MHz")
        self.inspector_bw.setFixedWidth(80)
        inspector_layout.addWidget(QLabel("BW:"))
        inspector_layout.addWidget(self.inspector_bw)

        self.inspector_gain = QDoubleSpinBox()
        self.inspector_gain.setMinimum(0)
        self.inspector_gain.setMaximum(80)
        self.inspector_gain.setValue(40.0)
        self.inspector_gain.setSuffix(" dB")
        self.inspector_gain.setFixedWidth(70)
        self.inspector_gain.valueChanged.connect(self._on_gain_changed)
        inspector_layout.addWidget(QLabel("Gain:"))
        inspector_layout.addWidget(self.inspector_gain)

        inspector_layout.addSpacing(10)

        # Waterfall controls
        self.waterfall_check = QCheckBox("Waterfall")
        self.waterfall_check.toggled.connect(self._on_waterfall_toggled)
        inspector_layout.addWidget(self.waterfall_check)

        self.waterfall_palette = QComboBox()
        self.waterfall_palette.addItems(["Viridis", "Grayscale", "Inferno", "Plasma", "Turbo"])
        self.waterfall_palette.setFixedWidth(80)
        self.waterfall_palette.currentTextChanged.connect(self._on_waterfall_palette_changed)
        inspector_layout.addWidget(self.waterfall_palette)

        self.waterfall_range_slider = QSlider(Qt.Horizontal)
        self.waterfall_range_slider.setMinimum(10)
        self.waterfall_range_slider.setMaximum(120)
        self.waterfall_range_slider.setValue(60)
        self.waterfall_range_slider.setFixedWidth(80)
        self.waterfall_range_slider.valueChanged.connect(self._on_waterfall_range_changed)
        inspector_layout.addWidget(QLabel("dB:"))
        inspector_layout.addWidget(self.waterfall_range_slider)

        inspector_layout.addSpacing(15)

        # TX Controls for Inspector (Grouped)
        self.inspector_tx_group = QWidget()
        inspector_tx_layout = QHBoxLayout(self.inspector_tx_group)
        inspector_tx_layout.setContentsMargins(0, 0, 0, 0)
        inspector_tx_layout.setSpacing(6)

        self.inspector_tx_freq = QDoubleSpinBox()
        self.inspector_tx_freq.setMinimum(1)
        self.inspector_tx_freq.setMaximum(6000)
        self.inspector_tx_freq.setValue(1000)
        self.inspector_tx_freq.setSuffix(" MHz")
        self.inspector_tx_freq.setFixedWidth(100)
        inspector_tx_layout.addWidget(QLabel("TX:"))
        inspector_tx_layout.addWidget(self.inspector_tx_freq)
        
        self.inspector_tx_btn = QPushButton("Transmit")
        self.inspector_tx_btn.setFixedWidth(70)
        self.inspector_tx_btn.clicked.connect(self._on_inspector_tx_clicked)
        inspector_tx_layout.addWidget(self.inspector_tx_btn)
        
        inspector_layout.addWidget(self.inspector_tx_group)
        self.inspector_tx_group.hide() # Hidden by default

        self.inspector_freq.valueChanged.connect(self._on_inspector_freq_changed)

        row2.addWidget(self.inspector_group)

        # Scanner controls
        self.scanner_group = QWidget()
        scanner_layout = QHBoxLayout(self.scanner_group)
        scanner_layout.setContentsMargins(0, 0, 0, 0)
        scanner_layout.setSpacing(6)
        
        self.scanner_start = QDoubleSpinBox()
        self.scanner_start.setMinimum(1)
        self.scanner_start.setMaximum(6000)
        self.scanner_start.setValue(900)
        self.scanner_start.setSuffix(" MHz")
        self.scanner_start.setFixedWidth(100)
        scanner_layout.addWidget(QLabel("Start:"))
        scanner_layout.addWidget(self.scanner_start)

        self.scanner_stop = QDoubleSpinBox()
        self.scanner_stop.setMinimum(1)
        self.scanner_stop.setMaximum(6000)
        self.scanner_stop.setValue(1100)
        self.scanner_stop.setSuffix(" MHz")
        self.scanner_stop.setFixedWidth(100)
        scanner_layout.addWidget(QLabel("Stop:"))
        scanner_layout.addWidget(self.scanner_stop)

        self.scanner_step = QDoubleSpinBox()
        self.scanner_step.setMinimum(0.1)
        self.scanner_step.setMaximum(20)
        self.scanner_step.setValue(20)
        self.scanner_step.setSuffix(" MHz")
        self.scanner_step.setFixedWidth(80)
        scanner_layout.addWidget(QLabel("Step:"))
        scanner_layout.addWidget(self.scanner_step)

        self.scanner_dwell = QDoubleSpinBox()
        self.scanner_dwell.setMinimum(0.1)
        self.scanner_dwell.setMaximum(60)
        self.scanner_dwell.setValue(1.0)
        self.scanner_dwell.setSuffix(" s")
        self.scanner_dwell.setFixedWidth(60)
        scanner_layout.addWidget(QLabel("Dwell:"))
        scanner_layout.addWidget(self.scanner_dwell)

        self.scanner_bw = QDoubleSpinBox()
        self.scanner_bw.setMinimum(0.1)
        self.scanner_bw.setMaximum(20)
        self.scanner_bw.setValue(20)
        self.scanner_bw.setSuffix(" MHz")
        self.scanner_bw.setFixedWidth(80)
        scanner_layout.addWidget(QLabel("BW:"))
        scanner_layout.addWidget(self.scanner_bw)

        self.scanner_gain = QDoubleSpinBox()
        self.scanner_gain.setMinimum(0)
        self.scanner_gain.setMaximum(80)
        self.scanner_gain.setValue(40.0)
        self.scanner_gain.setSuffix(" dB")
        self.scanner_gain.setFixedWidth(70)
        self.scanner_gain.valueChanged.connect(self._on_gain_changed)
        scanner_layout.addWidget(QLabel("Gain:"))
        scanner_layout.addWidget(self.scanner_gain)

        scanner_layout.addSpacing(15)

        # TX Controls for Scanner (Grouped)
        self.scanner_tx_group = QWidget()
        scanner_tx_layout = QHBoxLayout(self.scanner_tx_group)
        scanner_tx_layout.setContentsMargins(0, 0, 0, 0)
        scanner_tx_layout.setSpacing(6)

        self.scanner_tx_freq = QDoubleSpinBox()
        self.scanner_tx_freq.setMinimum(1)
        self.scanner_tx_freq.setMaximum(6000)
        self.scanner_tx_freq.setValue(1000)
        self.scanner_tx_freq.setSuffix(" MHz")
        self.scanner_tx_freq.setFixedWidth(100)
        scanner_tx_layout.addWidget(QLabel("TX:"))
        scanner_tx_layout.addWidget(self.scanner_tx_freq)
        
        self.scanner_tx_btn = QPushButton("Transmit")
        self.scanner_tx_btn.setFixedWidth(70)
        self.scanner_tx_btn.clicked.connect(self._on_scanner_tx_clicked)
        scanner_tx_layout.addWidget(self.scanner_tx_btn)
        
        scanner_layout.addWidget(self.scanner_tx_group)
        self.scanner_tx_group.hide() # Hidden by default

        self.scanner_group.hide()
        row2.addWidget(self.scanner_group)
        row2.addStretch()

        main_layout.addLayout(row2)

        # ====================================================================
        # SCAN PROGRESS BAR (Scanner mode only)
        # ====================================================================
        self.scan_progress_layout = QHBoxLayout()
        self.scan_progress_layout.setSpacing(4)
        self.scan_progress_label = QLabel("Scanning:")
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setMinimum(0)
        self.scan_progress_bar.setMaximum(100)
        self.scan_progress_bar.setFixedHeight(16)
        self.scan_freq_label = QLabel("-- MHz")
        
        self.scan_progress_layout.addWidget(self.scan_progress_label)
        self.scan_progress_layout.addWidget(self.scan_progress_bar, 1)
        self.scan_progress_layout.addWidget(self.scan_freq_label)
        
        self.scan_progress_label.hide()
        self.scan_progress_bar.hide()
        self.scan_freq_label.hide()
        
        main_layout.addLayout(self.scan_progress_layout)

        # ====================================================================
        # MAIN CONTENT: Spectrum (left) + Signal List/Scan Results (right)
        # ====================================================================
        content = QHBoxLayout()
        content.setSpacing(4)
        self.spectrum = SpectrumView(theme)
        self.signal_list = SignalList(theme)
        self.scan_results = ScanResultsTable(theme)
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.signal_list)
        self.right_stack.addWidget(self.scan_results)
        self.right_stack.setMinimumWidth(350)
        self.right_stack.setMaximumWidth(450)

        content.addWidget(self.spectrum, 2)
        content.addWidget(self.right_stack, 1)

        main_layout.addLayout(content, 1)

        # Hidden Manual TX controls
        self.manual_tx_group = QWidget()
        self.manual_tx_group.hide()
        manual_tx_layout = QHBoxLayout(self.manual_tx_group)
        manual_tx_layout.setContentsMargins(0, 0, 0, 0)
        self.manual_tx_freq = QDoubleSpinBox()
        self.manual_tx_freq.setMinimum(1)
        self.manual_tx_freq.setMaximum(6000)
        self.manual_tx_freq.setValue(1000)
        self.manual_tx_freq.setSuffix(" MHz")
        manual_tx_layout.addWidget(QLabel("TX Freq:"))
        manual_tx_layout.addWidget(self.manual_tx_freq)
        self.manual_tx_btn = QPushButton("TX")
        self.manual_tx_btn.clicked.connect(self._on_manual_tx)
        manual_tx_layout.addWidget(self.manual_tx_btn)

        # Create event detail view as dock widget (hidden by default to save space)
        self.detail_view = EventDetailView(emitter_store, theme, self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.detail_view)
        self.detail_view.hide()  # Users can show via menu or clicking a signal
        
        # Wire signal list clicks to detail view
        self.signal_list.emitter_selected.connect(self.detail_view.show_event)

        # Wire controller updates (must be queued; controller emits from a worker thread)
        self.controller.state_changed.connect(
            self._on_controller_state_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.controller.scan_progress.connect(
            self._on_scan_progress,
            Qt.ConnectionType.QueuedConnection,
        )

        # Status refresh timer (for "no signals detected" messaging)
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_line)
        self._status_timer.start(250)  # Reduced from 500ms to 250ms for better responsiveness

        # Fit window to screen once the widget is realized.
        QTimer.singleShot(0, self._fit_to_screen)

        # Start with a compact size
        try:
            self.resize(1050, 620)
        except Exception:
            pass

        # Apply persisted appearance + waterfall defaults.
        self._apply_settings_to_ui()

    def _fit_to_screen(self) -> None:
        """Resize & position the window to fit the current screen.

        Keeps the original UI aspect ratio so the layout proportions stay the same,
        while ensuring the app never exceeds the available screen area.
        """
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return

        avail = screen.availableGeometry()
        if avail.width() <= 0 or avail.height() <= 0:
            return

        # Leave a tiny margin so window managers don't clip edges.
        margin_factor = 0.98
        max_w = int(avail.width() * margin_factor)
        max_h = int(avail.height() * margin_factor)

        # Compute the largest size that fits while preserving the aspect ratio.
        target_w = max_w
        target_h = int(target_w / self._design_aspect)
        if target_h > max_h:
            target_h = max_h
            target_w = int(target_h * self._design_aspect)

        # Do NOT clamp against minimumSizeHint(): on smaller laptops, some dock/widget
        # size hints can exceed the available geometry and force the window off-screen.
        target_w = min(target_w, max_w)
        target_h = min(target_h, max_h)

        x = avail.x() + max(0, (avail.width() - target_w) // 2)
        y = avail.y() + max(0, (avail.height() - target_h) // 2)
        # Resize/move is more reliable than setGeometry with some window managers.
        try:
            self.resize(target_w, target_h)
            self.move(x, y)
        except Exception:
            self.setGeometry(x, y, target_w, target_h)

    def _on_mode_changed(self, mode: str):
        """Switch between Inspector and Scanner modes."""
        if mode == "Inspector":
            self.inspector_group.show()
            self.scanner_group.hide()
        else:
            self.inspector_group.hide()
            self.scanner_group.show()

        # Waterfall is Inspector-only.
        self.spectrum.set_inspector_mode(mode == "Inspector")
        self.spectrum.reset_waterfall()
        if mode == "Inspector":
            self.spectrum.set_waterfall_enabled(bool(self.waterfall_check.isChecked()))

    def _on_start(self):
        """Start button clicked."""
        mode = self.mode_combo.currentText()

        # Start/Stop presses must reset waterfall.
        self.spectrum.reset_waterfall()

        try:
            if mode == "Inspector":
                config = InspectorConfig(
                    center_freq=self.inspector_freq.value() * 1e6,
                    sample_rate=self.inspector_bw.value() * 1e6,
                    gain=float(self.inspector_gain.value())
                )
                self.controller.start_inspector(config)
            else:
                config = ScannerConfig(
                    start_freq=self.scanner_start.value() * 1e6,
                    stop_freq=self.scanner_stop.value() * 1e6,
                    step=self.scanner_step.value() * 1e6,
                    dwell_time=self.scanner_dwell.value(),
                    sample_rate=self.scanner_bw.value() * 1e6,
                    gain=float(self.scanner_gain.value())
                )
                self.controller.start_scanner(config)
        except RuntimeError as e:
            # HackRF-specific errors
            error_msg = str(e)
            if "HackRF" in error_msg:
                QMessageBox.critical(
                    self, 
                    "HackRF Not Found", 
                    f"❌ HackRF device not detected!\n\n"
                    f"Please ensure:\n"
                    f"• HackRF is physically connected to USB\n"
                    f"• USB drivers are installed\n"
                    f"• HackRF firmware is updated\n\n"
                    f"Run 'lsusb' in terminal to verify HackRF is detected (ID: 1d50:6089)"
                )
            else:
                QMessageBox.critical(self, "Startup Error", f"Failed to start: {error_msg}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start: {str(e)}")

    def _on_stop(self):
        """Stop button clicked."""
        # Start/Stop presses must reset waterfall.
        self.spectrum.reset_waterfall()
        self.controller.stop()

    def _on_scan_progress(self, current_step: int, total_steps: int, current_freq_hz: float):
        """Scan progress update from controller."""
        if total_steps > 0:
            percentage = int((current_step / total_steps) * 100)
            self.scan_progress_bar.setValue(percentage)
            self.scan_freq_label.setText(f"{current_freq_hz/1e6:.1f} MHz")
            self.status_label.setText(f"Status: Scanning {current_step}/{total_steps} ({current_freq_hz/1e6:.1f} MHz)")

    def _on_controller_state_changed(self, state: ControllerState):
        """Controller state changed - update UI."""
        state_names = {
            ControllerState.IDLE: "Idle",
            ControllerState.RUNNING_INSPECTOR: "Running (Inspector)",
            ControllerState.RUNNING_SCANNER: "Running (Scanner)",
            ControllerState.STOPPING: "Stopping...",
        }

        self._last_status_mode = state
        self.status_label.setText(f"Status: {state_names.get(state, 'Unknown')}")

        # Show/hide scan progress bar
        is_scanner = state == ControllerState.RUNNING_SCANNER
        self.scan_progress_label.setVisible(is_scanner)
        self.scan_progress_bar.setVisible(is_scanner)
        self.scan_freq_label.setVisible(is_scanner)

        # Enable/disable controls
        is_running = state in (ControllerState.RUNNING_INSPECTOR, ControllerState.RUNNING_SCANNER)
        
        self.mode_combo.setEnabled(not is_running)
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.inspector_freq.setEnabled(not is_running)
        self.inspector_bw.setEnabled(not is_running)
        self.inspector_gain.setEnabled(True)
        self.scanner_start.setEnabled(not is_running)
        self.scanner_stop.setEnabled(not is_running)
        self.scanner_step.setEnabled(not is_running)
        self.scanner_dwell.setEnabled(not is_running)
        self.scanner_bw.setEnabled(not is_running)
        self.scanner_gain.setEnabled(True)
        self.sensitivity_slider.setEnabled(True)

        # Switch right-side table based on mode
        if state == ControllerState.RUNNING_SCANNER:
            self.right_stack.setCurrentWidget(self.scan_results)
        else:
            self.right_stack.setCurrentWidget(self.signal_list)

        # Enforce Inspector-only waterfall behavior based on actual run state.
        if state == ControllerState.RUNNING_SCANNER:
            self.spectrum.set_inspector_mode(False)
        elif state == ControllerState.RUNNING_INSPECTOR:
            self.spectrum.set_inspector_mode(True)
        else:
            # Idle/stopping: reflect current mode selector.
            self.spectrum.set_inspector_mode(self.mode_combo.currentText() == "Inspector")
            if self.mode_combo.currentText() == "Inspector":
                self.spectrum.set_waterfall_enabled(bool(self.waterfall_check.isChecked()))

        # Reset detected timer at start
        if state in (ControllerState.RUNNING_INSPECTOR, ControllerState.RUNNING_SCANNER):
            self._last_detected_ts = 0.0
            self._refresh_status_line()

    def _on_gain_changed(self, _value):
        # Apply live gain while running.
        state = self.controller.get_state()
        if state in (ControllerState.RUNNING_INSPECTOR, ControllerState.RUNNING_SCANNER):
            gain = float(self.inspector_gain.value() if self.mode_combo.currentText() == "Inspector" else self.scanner_gain.value())
            self.controller.set_gain(gain)
            self._refresh_status_line()

    def _on_sensitivity_changed(self, value: int):
        s = max(0.0, min(1.0, float(value) / 100.0))
        self.sensitivity_label.setText(f"{int(value)}%")
        self.controller.set_detection_sensitivity(s)

    def _on_hold_toggled(self, checked: bool):
        self.hold_display = bool(checked)
        self.hold_btn.setText("Hold" if not self.hold_display else "Held")
        # When un-holding, refresh tables from store to catch up.
        if not self.hold_display:
            self._refresh_emitter_views_from_store()

    def _on_clear_reset(self):
        # Reset analysis state without stopping RX.
        try:
            self.controller.reset_analysis_state()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Reset failed: {str(e)}")
            return

        # Clear UI + store.
        self.event_store.clear_all()
        try:
            self.emitter_store.clear_all()
        except Exception:
            pass
        self.signal_list.clear_all()
        self.scan_results.clear_all()
        self.detail_view.clear_event()
        self._last_detected_ts = 0.0
        self._refresh_status_line()

    def _on_export_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Events", "rf_events.json", "JSON Files (*.json)")
        if not path:
            return
        scan_results = []
        try:
            for r in (self.controller.get_scan_results() or []):
                scan_results.append({
                    "center_freq_hz": float(getattr(r, "center_freq", 0.0) or 0.0),
                    "dwell_time_s": float(getattr(r, "dwell_time", 0.0) or 0.0),
                    "timestamp": float(getattr(r, "timestamp", 0.0) or 0.0),
                    "events": [e.to_dict() for e in (getattr(r, "closed_events", []) or [])],
                })
        except Exception:
            pass
        payload = {
            "exported_at": time.time(),
            "controller_state": getattr(self.controller.get_state(), "value", str(self.controller.get_state())),
            "config": self.controller.config.to_dict() if hasattr(self.controller, "config") else {},
            "emitters": self.emitter_store.export_dict() if hasattr(self, 'emitter_store') else {},
            "events": self.event_store.export_dict(),
            "scan_results": scan_results,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export failed: {str(e)}")

    def on_scan_result_ready(self, scan_result):
        if self.hold_display:
            return
        self.scan_results.add_result(scan_result)

    def on_analysis_reset(self):
        # Controller reset happened; clear analysis views unless held.
        if self.hold_display:
            return
        try:
            self.event_store.clear_all()
        except Exception:
            pass
        try:
            self.emitter_store.clear_all()
        except Exception:
            pass
        self.signal_list.clear_all()
        self.scan_results.clear_all()
        self.detail_view.clear_event()

    def _refresh_emitter_views_from_store(self):
        # Rebuild list from EmitterStore (active + recent history).
        self.signal_list.clear_all()
        try:
            for em in self.emitter_store.get_active():
                self.signal_list.update_emitter(em)
            for em in self.emitter_store.get_history(limit=200):
                self.signal_list.close_emitter(em)
        except Exception:
            pass

    def _refresh_status_line(self):
        state = self.controller.get_state()
        if state == ControllerState.RUNNING_INSPECTOR:
            # If PSD snapshots aren't arriving, the IQ source/flowgraph is likely stalled.
            if self._last_psd_ts and (time.time() - self._last_psd_ts) > 1.5:
                cf_mhz = float(self.controller.config.center_freq) / 1e6
                bw_mhz = float(self.controller.config.sample_rate) / 1e6
                self.status_label.setText(
                    f"Status: RX stalled — no IQ/PSD data (@ {cf_mhz:.3f} MHz, BW {bw_mhz:.2f} MHz)"
                )
                return
            cf_mhz = float(self.controller.config.center_freq) / 1e6
            bw_mhz = float(self.controller.config.sample_rate) / 1e6
            gain_db = float(self.controller.config.gain)
            if self._last_detected_ts and (time.time() - self._last_detected_ts) < 1.5:
                self.status_label.setText(f"Status: RX running @ {cf_mhz:.3f} MHz, BW {bw_mhz:.2f} MHz, Gain {gain_db:.0f} dB")
            else:
                self.status_label.setText(f"Status: RX active — no signals detected (@ {cf_mhz:.3f} MHz, BW {bw_mhz:.2f} MHz)")
        elif state == ControllerState.RUNNING_SCANNER:
            cur, total = self.controller.get_current_scan_progress()
            self.status_label.setText(f"Status: Scanning: step {cur} / {total}")
        elif state == ControllerState.STOPPING:
            self.status_label.setText("Status: Stopping…")
        else:
            self.status_label.setText("Status: Idle")

    def _open_settings(self):
        """Open settings dialog."""
        dialog = SettingsDialog(self, settings=self._settings)
        if dialog.exec() == QDialog.Accepted:
            old_enabled = self.transmission_enabled
            self.transmission_enabled = dialog.tx_toggle.isChecked()
            if old_enabled != self.transmission_enabled:
                self._update_transmission_ui()

            # Apply spectrum appearance from dialog and persist.
            rgba = dialog.get_spectrum_rgba()
            line_width = dialog.get_spectrum_line_width()
            fill_enabled = dialog.get_spectrum_fill_enabled()
            fill_alpha = dialog.get_spectrum_fill_alpha()

            self._settings["spectrum"] = {
                "rgba": list(rgba),
                "line_width": float(line_width),
                "fill_enabled": bool(fill_enabled),
                "fill_alpha": int(fill_alpha),
            }
            save_settings(self._settings)
            self.spectrum.set_spectrum_style(
                rgba=rgba,
                line_width=line_width,
                fill_enabled=fill_enabled,
                fill_alpha=fill_alpha,
            )

    def _update_transmission_ui(self):
        """Update UI elements based on transmission enabled state."""
        self.signal_list.set_transmission_enabled(self.transmission_enabled)
        self.scan_results.set_transmission_enabled(self.transmission_enabled)
        self.manual_tx_group.setVisible(self.transmission_enabled)
        
        # Update visibility of mode-specific TX controls
        if hasattr(self, 'inspector_tx_group'):
            self.inspector_tx_group.setVisible(self.transmission_enabled)
        if hasattr(self, 'scanner_tx_group'):
            self.scanner_tx_group.setVisible(self.transmission_enabled)

    def _update_inspector_only_controls(self) -> None:
        # Waterfall controls are part of inspector_group which auto-hides in Scanner mode.
        # Just ensure waterfall is off if not in inspector mode.
        if self.mode_combo.currentText() != "Inspector":
            self.spectrum.set_waterfall_enabled(False)

    def _apply_settings_to_ui(self) -> None:
        # Spectrum appearance
        spec = self._settings.get("spectrum") if isinstance(self._settings, dict) else None
        if isinstance(spec, dict):
            rgba = spec.get("rgba")
            if isinstance(rgba, (list, tuple)) and len(rgba) == 4:
                try:
                    rgba_t = (int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3]))
                except Exception:
                    rgba_t = None
            else:
                rgba_t = None
            try:
                lw = float(spec.get("line_width", 1.5))
            except Exception:
                lw = 1.5
            fill_enabled = bool(spec.get("fill_enabled", False))
            try:
                fill_alpha = int(spec.get("fill_alpha", 60))
            except Exception:
                fill_alpha = 60
            self.spectrum.set_spectrum_style(
                rgba=rgba_t,
                line_width=lw,
                fill_enabled=fill_enabled,
                fill_alpha=fill_alpha,
            )

        # Waterfall settings
        wf = self._settings.get("waterfall") if isinstance(self._settings, dict) else None
        if not isinstance(wf, dict):
            wf = {}

        enabled = bool(wf.get("enabled", False))
        palette = str(wf.get("palette", "viridis"))
        try:
            range_db = float(wf.get("range_db", 60.0))
        except Exception:
            range_db = 60.0

        self.waterfall_check.setChecked(enabled)
        # Map stored palette to UI text
        palette_map = {
            "viridis": "Viridis",
            "grayscale": "Grayscale",
            "inferno": "Inferno",
            "plasma": "Plasma",
            "turbo": "Turbo",
        }
        self.waterfall_palette.setCurrentText(palette_map.get(palette.lower(), "Viridis"))
        self.waterfall_range_slider.setValue(int(max(10, min(120, range_db))))

        self.spectrum.set_waterfall_palette(palette)
        self.spectrum.set_waterfall_range_db(range_db)
        self.spectrum.set_waterfall_enabled(enabled and (self.mode_combo.currentText() == "Inspector"))
        self.spectrum.set_inspector_mode(self.mode_combo.currentText() == "Inspector")
        self._update_inspector_only_controls()

    def _persist_waterfall_settings(self) -> None:
        self._settings["waterfall"] = {
            "enabled": bool(self.waterfall_check.isChecked()),
            "palette": str(self._current_waterfall_palette_key()),
            "range_db": float(self.waterfall_range_slider.value()),
        }
        save_settings(self._settings)

    def _current_waterfall_palette_key(self) -> str:
        t = (self.waterfall_palette.currentText() or "Viridis").strip().lower()
        if t.startswith("gray"):
            return "grayscale"
        if t.startswith("inferno"):
            return "inferno"
        if t.startswith("plasma"):
            return "plasma"
        if t.startswith("turbo"):
            return "turbo"
        return "viridis"

    def _on_waterfall_toggled(self, checked: bool) -> None:
        self.spectrum.reset_waterfall()
        self.spectrum.set_waterfall_enabled(bool(checked) and (self.mode_combo.currentText() == "Inspector"))
        self._persist_waterfall_settings()

    def _on_waterfall_palette_changed(self, _text: str) -> None:
        palette = self._current_waterfall_palette_key()
        self.spectrum.reset_waterfall()
        self.spectrum.set_waterfall_palette(palette)
        self._persist_waterfall_settings()

    def _on_waterfall_range_changed(self, value: int) -> None:
        self.spectrum.set_waterfall_range_db(float(value))
        self._persist_waterfall_settings()

    def _on_inspector_freq_changed(self, _mhz: float) -> None:
        # Center frequency change resets waterfall, per requirements.
        self.spectrum.reset_waterfall()

    def connect_engine(self, psd_publisher):
        psd_publisher.snapshot_ready.connect(
            self._on_psd_snapshot,
            Qt.ConnectionType.QueuedConnection,
        )

    def _on_psd_snapshot(self, snapshot):
        if self.hold_display:
            return
        self._last_psd_ts = time.time()
        if snapshot.get("detected"):
            self._last_detected_ts = time.time()
        self.spectrum.update_snapshot(snapshot)

    def connect_emitters(self, emitter_publisher):
        emitter_publisher.emitter_updated.connect(
            self._on_emitter_updated,
            Qt.ConnectionType.QueuedConnection,
        )
        emitter_publisher.emitter_closed.connect(
            self._on_emitter_closed,
            Qt.ConnectionType.QueuedConnection,
        )
        self.signal_list.tx_requested.connect(self._on_tx_requested)
        self.scan_results.tx_requested.connect(self._on_tx_requested)

    def _on_emitter_updated(self, emitter):
        if self.hold_display:
            return
        self.signal_list.update_emitter(emitter)

    def _on_emitter_closed(self, emitter):
        if self.hold_display:
            return
        self.signal_list.close_emitter(emitter)

    def _on_tx_requested(self, freq_hz):
        """Handle TX request for a specific frequency."""
        if self.transmission_enabled:
            freq_hz = float(freq_hz)
            if self.is_transmitting:
                # If user clicked a different row, retune TX to that frequency.
                if self.current_tx_freq_hz is None or abs(self.current_tx_freq_hz - freq_hz) > 1.0:
                    self._stop_transmission()
                    self._start_transmission(freq_hz)
                else:
                    self._stop_transmission()
            else:
                self._start_transmission(freq_hz)

    def _on_manual_tx(self):
        """Handle manual TX button click."""
        if self.transmission_enabled:
            if self.is_transmitting:
                self._stop_transmission()
            else:
                freq_hz = self.manual_tx_freq.value() * 1e6
                self._start_transmission(freq_hz)

    def _on_inspector_tx_clicked(self):
        """Handle Inspector mode TX button click."""
        if not self.transmission_enabled:
            return
        if self.is_transmitting:
            self._stop_transmission()
        else:
            freq_hz = self.inspector_tx_freq.value() * 1e6
            self._start_transmission(freq_hz)

    def _on_scanner_tx_clicked(self):
        """Handle Scanner mode TX button click."""
        if not self.transmission_enabled:
            return
        if self.is_transmitting:
            self._stop_transmission()
        else:
            freq_hz = self.scanner_tx_freq.value() * 1e6
            self._start_transmission(freq_hz)

    def _start_transmission(self, freq_hz):
        """Start transmission at the given frequency."""
        if self.is_transmitting:
            self._stop_transmission()
            return
        
        # Pause RX engine to release HackRF
        self.controller.pause_engine()
        
        self.tx_thread = TxThread(freq_hz, noise_amp=0.1)
        self.tx_thread.start()
        self.is_transmitting = True
        self.current_tx_freq_hz = float(freq_hz)
        
        # Update status
        self.status_label.setText(f"Status: TX @ {freq_hz/1e6:.3f} MHz")
        self.status_label.setStyleSheet("color: red;")
        
        # Update button texts
        self._update_tx_button_texts()

    def _stop_transmission(self):
        """Stop the current transmission."""
        if self.tx_thread and self.is_transmitting:
            self.tx_thread.stop_transmission()
            # Wait for thread to fully finish (with timeout)
            self.tx_thread.wait(timeout=2000)  # 2 second timeout
            self.tx_thread = None
        
        self.is_transmitting = False
        self.current_tx_freq_hz = None
        
        # Resume RX engine
        self.controller.resume_engine()
        
        self.status_label.setText("Status: Idle")
        self.status_label.setStyleSheet("")
        
        # Update button texts
        self._update_tx_button_texts()

    def _update_tx_button_texts(self):
        """Update all TX button texts based on transmission state."""
        if not self.transmission_enabled:
            return
            
        # Update manual TX button
        if self.is_transmitting:
            self.manual_tx_btn.setText("Stop TX")
            self.manual_tx_btn.setStyleSheet("background-color: red; color: white;")
            
            self.inspector_tx_btn.setText("Stop TX")
            self.inspector_tx_btn.setStyleSheet("background-color: red; color: white;")
            
            self.scanner_tx_btn.setText("Stop TX")
            self.scanner_tx_btn.setStyleSheet("background-color: red; color: white;")
        else:
            self.manual_tx_btn.setText("TX")
            self.manual_tx_btn.setStyleSheet("")
            
            self.inspector_tx_btn.setText("Transmit")
            self.inspector_tx_btn.setStyleSheet("")
            
            self.scanner_tx_btn.setText("Transmit")
            self.scanner_tx_btn.setStyleSheet("")
        
        # Update signal list TX buttons
        self.signal_list.update_tx_buttons(self.is_transmitting)
        self.scan_results.update_tx_buttons(self.is_transmitting)

    def closeEvent(self, event):
        """Handle window close event."""
        self._stop_transmission()
        event.accept()


class SettingsDialog(QDialog):
    def __init__(self, parent=None, *, settings: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        layout = QVBoxLayout(self)

        self._settings = settings or {}
        
        self.tx_toggle = QCheckBox("Enable Transmission")
        self.tx_toggle.setChecked(parent.transmission_enabled)
        layout.addWidget(self.tx_toggle)

        # Appearance (collapsible)
        self.appearance_group = QGroupBox("Appearance")
        self.appearance_group.setCheckable(True)
        self.appearance_group.setChecked(True)
        appearance_layout = QFormLayout(self.appearance_group)

        # Spectrum RGB picker (live spectrum only)
        self.spectrum_color_btn = QPushButton("Choose…")
        self.spectrum_color_btn.clicked.connect(self._pick_spectrum_color)
        appearance_layout.addRow("Spectrum color", self.spectrum_color_btn)

        self.spectrum_opacity = QSlider(Qt.Horizontal)
        self.spectrum_opacity.setMinimum(40)
        self.spectrum_opacity.setMaximum(255)
        self.spectrum_opacity.setValue(255)
        appearance_layout.addRow("Spectrum opacity", self.spectrum_opacity)

        self.spectrum_opacity.valueChanged.connect(self._apply_preview)

        self.spectrum_width = QDoubleSpinBox()
        self.spectrum_width.setMinimum(0.5)
        self.spectrum_width.setMaximum(6.0)
        self.spectrum_width.setSingleStep(0.5)
        self.spectrum_width.setValue(1.5)
        appearance_layout.addRow("Line width", self.spectrum_width)

        self.spectrum_width.valueChanged.connect(self._apply_preview)

        self.spectrum_fill = QCheckBox("Fill under spectrum")
        self.spectrum_fill.setChecked(False)
        appearance_layout.addRow(self.spectrum_fill)

        self.spectrum_fill.toggled.connect(self._apply_preview)

        self.spectrum_fill_alpha = QSlider(Qt.Horizontal)
        self.spectrum_fill_alpha.setMinimum(10)
        self.spectrum_fill_alpha.setMaximum(200)
        self.spectrum_fill_alpha.setValue(60)
        appearance_layout.addRow("Fill opacity", self.spectrum_fill_alpha)

        self.spectrum_fill_alpha.valueChanged.connect(self._apply_preview)

        layout.addWidget(self.appearance_group)

        self._load_from_settings()

        # Apply once on open so the preview matches persisted values.
        self._apply_preview()
        
        buttons = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

    def _load_from_settings(self) -> None:
        spec = self._settings.get("spectrum") if isinstance(self._settings, dict) else None
        if not isinstance(spec, dict):
            return

        rgba = spec.get("rgba")
        if isinstance(rgba, (list, tuple)) and len(rgba) == 4:
            try:
                self._spectrum_rgba = (int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3]))
                self.spectrum_opacity.setValue(int(self._spectrum_rgba[3]))
            except Exception:
                self._spectrum_rgba = (88, 166, 255, 255)
        else:
            self._spectrum_rgba = (88, 166, 255, 255)

        try:
            self.spectrum_width.setValue(float(spec.get("line_width", 1.5)))
        except Exception:
            pass
        self.spectrum_fill.setChecked(bool(spec.get("fill_enabled", False)))
        try:
            self.spectrum_fill_alpha.setValue(int(spec.get("fill_alpha", 60)))
        except Exception:
            pass

        self._sync_color_button()

    def _sync_color_button(self) -> None:
        r, g, b, a = getattr(self, "_spectrum_rgba", (88, 166, 255, 255))
        self.spectrum_color_btn.setText(f"RGB({r},{g},{b})")
        # Use alpha in the preview to reflect opacity.
        self.spectrum_color_btn.setStyleSheet(
            f"background-color: rgba({r},{g},{b},{a}); color: white;"
        )

    def _pick_spectrum_color(self) -> None:
        r, g, b, a = getattr(self, "_spectrum_rgba", (88, 166, 255, 255))
        initial = QColor(r, g, b, a)
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(initial, self, "Spectrum Color")
        if not color.isValid():
            return
        # Preserve current opacity slider as the authoritative alpha.
        alpha = int(self.spectrum_opacity.value())
        self._spectrum_rgba = (int(color.red()), int(color.green()), int(color.blue()), alpha)
        self._sync_color_button()
        self._apply_preview()

    def _apply_preview(self) -> None:
        # Keep the button preview alpha in sync with the slider.
        r, g, b, _a = getattr(self, "_spectrum_rgba", (88, 166, 255, 255))
        self._spectrum_rgba = (int(r), int(g), int(b), int(self.spectrum_opacity.value()))
        self._sync_color_button()

        parent = self.parent()
        try:
            # Immediate effect on live spectrum only.
            parent.spectrum.set_spectrum_style(
                rgba=self.get_spectrum_rgba(),
                line_width=self.get_spectrum_line_width(),
                fill_enabled=self.get_spectrum_fill_enabled(),
                fill_alpha=self.get_spectrum_fill_alpha(),
            )
        except Exception:
            pass

    def get_spectrum_rgba(self) -> tuple[int, int, int, int]:
        r, g, b, _a = getattr(self, "_spectrum_rgba", (88, 166, 255, 255))
        a = int(self.spectrum_opacity.value())
        return (int(r), int(g), int(b), int(a))

    def get_spectrum_line_width(self) -> float:
        try:
            return float(self.spectrum_width.value())
        except Exception:
            return 1.5

    def get_spectrum_fill_enabled(self) -> bool:
        return bool(self.spectrum_fill.isChecked())

    def get_spectrum_fill_alpha(self) -> int:
        try:
            return int(self.spectrum_fill_alpha.value())
        except Exception:
            return 60
