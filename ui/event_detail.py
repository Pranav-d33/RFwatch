# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""
Signal Detail View (Event Inspector) - Dock Panel

Responsibilities:
- Display detailed information about a selected signal event
- Show metrics with confidence bars
- Provide progressive disclosure via tabs
- Generate human-readable summaries
- No speculation, only facts and honesty
"""

import numpy as np
from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPalette, QFont
import pyqtgraph as pg


class ConfidenceBar(QWidget):
    """
    A thin horizontal confidence indicator bar.
    Green (high) → Amber (medium) → Gray (low)
    """
    def __init__(self, confidence: float, parent=None):
        super().__init__(parent)
        self.confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]
        self.setFixedHeight(8)
        self.setMinimumWidth(100)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QBrush
        painter = QPainter(self)

        # Determine color based on confidence
        if self.confidence >= 0.7:
            color = QColor("#2ea043")  # Green
        elif self.confidence >= 0.4:
            color = QColor("#d29922")  # Amber
        else:
            color = QColor("#6e7681")  # Gray

        # Draw background (light gray)
        painter.fillRect(self.rect(), QColor("#21262d"))

        # Draw confidence bar
        width = self.width() * self.confidence
        painter.fillRect(0, 0, width, self.height(), color)

        painter.end()

    def set_confidence(self, confidence: float):
        """Update confidence value and redraw."""
        self.confidence = max(0.0, min(1.0, confidence))
        self.update()


class MetricRow(QWidget):
    """
    A single metric row: label | value | confidence bar
    """
    def __init__(self, label: str, value: str, confidence: float = None, parent=None):
        super().__init__(parent)
        self.label_text = label
        self.value_text = value
        self.confidence = confidence

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        # Label
        label_widget = QLabel(label)
        label_font = QFont()
        label_font.setPointSize(9)
        label_widget.setFont(label_font)
        label_widget.setMinimumWidth(120)
        label_widget.setStyleSheet("color: #8b949e;")
        layout.addWidget(label_widget, 0)

        # Value
        value_widget = QLabel(value)
        value_font = QFont()
        value_font.setPointSize(10)
        value_font.setBold(True)
        value_widget.setFont(value_font)
        layout.addWidget(value_widget, 1)

        # Confidence bar (if provided)
        if confidence is not None:
            bar = ConfidenceBar(confidence)
            layout.addWidget(bar, 1)

        layout.addStretch()

    def set_tooltip_info(self, info: str):
        """Set hover tooltip with additional info."""
        self.setToolTip(info)


class SignalSummary(QFrame):
    """
    Top strip: human-readable summary of the signal.

    Example:
    "Wideband signal near 2.451 GHz
     Duration: 3.8 s • Mostly continuous"
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setStyleSheet("background-color: #161b22; border-bottom: 1px solid #30363d;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.title = QLabel()
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self.title.setFont(title_font)
        layout.addWidget(self.title)

        self.subtitle = QLabel()
        subtitle_font = QFont()
        subtitle_font.setPointSize(9)
        self.subtitle.setFont(subtitle_font)
        self.subtitle.setStyleSheet("color: #8b949e;")
        layout.addWidget(self.subtitle)

    def set_summary(self, event):
        """Generate and display friendly summary text."""
        # Determine signal type
        bw_hz = event.features.get("bandwidth", {}).get("mean_hz", 0)
        if bw_hz > 1e6:
            kind = "Wideband signal"
        else:
            kind = "Narrowband signal"

        # Format frequency
        center_hz = float(event.features.get("frequency", {}).get("center_hz", 0.0) or 0.0)
        freq_mhz = center_hz / 1e6

        # Determine continuity
        burst_type = event.features.get("time_structure", {}).get("burst_type", "unknown")
        if burst_type == "continuous":
            continuity = "Mostly continuous"
        else:
            duty_cycle = event.features.get("time_structure", {}).get("duty_cycle", 0)
            if duty_cycle > 0.8:
                continuity = "Mostly continuous"
            elif duty_cycle > 0.5:
                continuity = "Regular bursts"
            else:
                continuity = "Intermittent"

        # Set title (units must be trustworthy)
        self.title.setText(f"{kind} near {freq_mhz:.3f} MHz")

        # Set subtitle
        duration_s = event.features.get("meta", {}).get("duration_s", 0)
        self.subtitle.setText(f"Duration: {duration_s:.2f} s • {continuity}")


class OverviewTab(QWidget):
    """
    Overview Tab: The 80% view.

    Shows: Frequency, Bandwidth, Power, SNR, Duty Cycle, Duration
    Each with a confidence bar.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.metrics = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Scrollable area for metrics
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #0e1117; }")

        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setContentsMargins(8, 8, 8, 8)
        self.container_layout.setSpacing(1)

        scroll.setWidget(container)
        layout.addWidget(scroll)

    def display_event(self, event):
        """Populate overview with event features."""
        # Clear existing metrics
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        features = event.features

        # Extract values
        freq_hz = float(features.get("frequency", {}).get("center_hz", 0.0) or 0.0)
        peak_hz = float(features.get("frequency", {}).get("peak_hz", 0.0) or 0.0)
        freq_mhz = freq_hz / 1e6
        peak_mhz = peak_hz / 1e6
        freq_conf = features.get("confidence", {}).get("frequency", 0.5)

        bw_hz = float(features.get("bandwidth", {}).get("mean_hz", 0.0) or 0.0)
        bw_min_hz = float(features.get("bandwidth", {}).get("min_hz", 0.0) or 0.0)
        bw_max_hz = float(features.get("bandwidth", {}).get("max_hz", 0.0) or 0.0)
        bw_var_hz2 = float(features.get("bandwidth", {}).get("var_hz2", 0.0) or 0.0)
        if bw_hz >= 1e6:
            bw_display = f"{bw_hz / 1e6:.2f} MHz"
        else:
            bw_display = f"{bw_hz / 1e3:.1f} kHz"

        if bw_max_hz > 0:
            bw_range = f"{bw_min_hz/1e3:.1f}–{bw_max_hz/1e3:.1f} kHz" if bw_max_hz < 1e6 else f"{bw_min_hz/1e6:.2f}–{bw_max_hz/1e6:.2f} MHz"
        else:
            bw_range = "--"

        power_avg = float(features.get("power", {}).get("avg_power", 0.0) or 0.0)
        snr = float(features.get("noise", {}).get("snr", 0.0) or 0.0)
        duty_cycle = features.get("time_structure", {}).get("duty_cycle", 0)
        duration_s = features.get("meta", {}).get("duration_s", 0)

        avg_burst_s = float(features.get("time_structure", {}).get("avg_burst_s", 0.0) or 0.0)
        avg_gap_s = float(features.get("time_structure", {}).get("avg_gap_s", 0.0) or 0.0)
        stability_score = float(features.get("stability", {}).get("score", 0.0) or 0.0)
        power_var = float(features.get("signal_dynamics", {}).get("power_var", 0.0) or 0.0)

        # SNR confidence: use frequency confidence as proxy (all from same observation)
        snr_conf = freq_conf

        # Create metric rows
        metrics_list = [
            ("Avg Frequency", f"{freq_mhz:.3f} MHz", freq_conf),
            ("Peak Frequency", "--" if peak_hz <= 0 else f"{peak_mhz:.3f} MHz", max(0.2, freq_conf)),
            ("Bandwidth (avg)", bw_display, freq_conf),
            ("Bandwidth (min–max)", bw_range, max(0.2, freq_conf)),
            ("Bandwidth variance", "--" if bw_var_hz2 <= 0 else f"{bw_var_hz2:.0f} Hz²", max(0.2, freq_conf)),
            ("Avg Power", f"{power_avg:.1f} dB (relative)", freq_conf),
            ("Power variance", f"{power_var:.3f}", max(0.2, freq_conf)),
            ("SNR", f"{snr:.1f} dB", snr_conf),
            ("Duty Cycle", f"{duty_cycle * 100:.1f}%", freq_conf),
            ("Avg burst", "--" if avg_burst_s <= 0 else f"{avg_burst_s:.2f} s", max(0.2, min(1.0, duration_s / 1.0))),
            ("Avg gap", "--" if avg_gap_s <= 0 else f"{avg_gap_s:.2f} s", max(0.2, min(1.0, duration_s / 1.0))),
            ("Stability score", f"{stability_score * 100:.0f}%", max(0.2, freq_conf)),
            ("Duration", f"{duration_s:.2f} s", 1.0),  # Always 100% confident in duration
        ]

        for label, value, conf in metrics_list:
            row = MetricRow(label, value, conf)
            self.container_layout.addWidget(row)

        self.container_layout.addStretch()


class TimeBehaviorTab(QWidget):
    """
    Time Behavior Tab: Power vs time and Frequency drift vs time.

    Shows trends to answer: "Is it stable? Moving? Fading?"
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Power vs time plot
        self.power_plot = pg.PlotWidget()
        self.power_plot.setLabel('left', 'Power', units='dB')
        self.power_plot.setLabel('bottom', 'Time', units='s')
        self.power_plot.setTitle('Power vs Time')
        self.power_plot.setStyleSheet("background-color: #0e1117; color: #c9d1d9;")
        self.power_plot.getPlotItem().getViewBox().setBackgroundColor("#0e1117")
        self._style_plot(self.power_plot)

        layout.addWidget(self.power_plot)

        # Frequency drift vs time plot
        self.freq_plot = pg.PlotWidget()
        self.freq_plot.setLabel('left', 'Frequency', units='Hz')
        self.freq_plot.setLabel('bottom', 'Time', units='s')
        self.freq_plot.setTitle('Frequency Drift vs Time')
        self.freq_plot.setStyleSheet("background-color: #0e1117; color: #c9d1d9;")
        self.freq_plot.getPlotItem().getViewBox().setBackgroundColor("#0e1117")
        self._style_plot(self.freq_plot)

        layout.addWidget(self.freq_plot)

    def _style_plot(self, plot):
        """Apply consistent styling to plots."""
        plot.getPlotItem().hideAxis('right')
        plot.getPlotItem().hideAxis('top')
        plot.getPlotItem().showGrid(x=True, y=True, alpha=0.2)

    def display_event(self, event):
        """Plot power and frequency history."""
        self.power_plot.clear()
        self.freq_plot.clear()

        features = event.features
        meta = features.get("meta", {})
        duration_s = meta.get("duration_s", 1)

        # Power vs time
        power_history = event.power_history
        if power_history:
            times = np.linspace(0, duration_s, len(power_history))
            self.power_plot.plot(
                times, power_history,
                pen=pg.mkPen(color="#58a6ff", width=2),
                symbol='o', symbolSize=4
            )

        # Frequency vs time
        center_freq_history = event.center_freq_history
        if center_freq_history:
            times = np.linspace(0, duration_s, len(center_freq_history))
            freq_hz = np.array(center_freq_history)
            self.freq_plot.plot(
                times, freq_hz,
                pen=pg.mkPen(color="#d29922", width=2),
                symbol='o', symbolSize=4
            )


class AdvancedTab(QWidget):
    """
    Advanced Tab: Raw features and confidence schema.

    For analysts. Beginners never open this.
    Shows:
    - Tree view of feature schema
    - Per-field confidence
    - Warnings section
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Warnings section
        warnings_label = QLabel("⚠ Warnings & Notes")
        warnings_font = QFont()
        warnings_font.setBold(True)
        warnings_font.setPointSize(9)
        warnings_label.setFont(warnings_font)
        layout.addWidget(warnings_label)

        self.warnings_text = QLabel()
        self.warnings_text.setWordWrap(True)
        self.warnings_text.setStyleSheet("color: #d29922; padding: 8px; background-color: #161b22; border: 1px solid #30363d;")
        layout.addWidget(self.warnings_text)

        # Feature tree
        tree_label = QLabel("Raw Feature Schema")
        tree_font = QFont()
        tree_font.setBold(True)
        tree_font.setPointSize(9)
        tree_label.setFont(tree_font)
        layout.addWidget(tree_label)

        self.feature_tree = QTreeWidget()
        self.feature_tree.setColumnCount(2)
        self.feature_tree.setHeaderLabels(["Field", "Value"])
        self.feature_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: #0e1117;
                color: #c9d1d9;
                border: 1px solid #30363d;
            }}
            QTreeWidget::item:hover {{
                background-color: #161b22;
            }}
        """)
        layout.addWidget(self.feature_tree)

    def display_event(self, event):
        """Populate advanced view with raw features and warnings."""
        self.feature_tree.clear()

        # Generate warnings
        warnings = self._generate_warnings(event)
        if warnings:
            self.warnings_text.setText("\n".join(f"• {w}" for w in warnings))
        else:
            self.warnings_text.setText("No warnings. Data looks good.")

        # Build feature tree
        features = event.features
        for section_name, section_data in features.items():
            if section_name == "confidence":
                continue  # Handle separately if needed
            section_item = QTreeWidgetItem([section_name, ""])
            section_font = QFont()
            section_font.setBold(True)
            section_item.setFont(0, section_font)

            if isinstance(section_data, dict):
                for key, value in section_data.items():
                    if isinstance(value, float):
                        display_value = f"{value:.4f}"
                    else:
                        display_value = str(value)
                    QTreeWidgetItem(section_item, [key, display_value])

            self.feature_tree.addTopLevelItem(section_item)

        self.feature_tree.expandAll()
        self.feature_tree.resizeColumnToContents(0)

    def _generate_warnings(self, event):
        """Generate analyst-friendly warnings."""
        warnings = []
        features = event.features

        # Low SNR warning
        snr = features.get("noise", {}).get("snr", 0)
        if snr < 3:
            warnings.append("Low SNR: frequency estimates may be unreliable")

        # Unstable bandwidth
        bw_unstable = features.get("bandwidth", {}).get("unstable", False)
        if bw_unstable:
            warnings.append("Bandwidth unstable over time: possible signal drift or capture artifact")

        # Short observation window
        duration_s = features.get("meta", {}).get("duration_s", 0)
        if duration_s < 0.5:
            warnings.append("Short observation window: statistics less reliable")

        # High PAPR
        papr = features.get("power", {}).get("papr", 0)
        if papr > 10:
            warnings.append("High peak-to-average power ratio: signal may be pulsed or non-stationary")

        return warnings


class EventDetailView(QDockWidget):
    """
    Signal Detail View: Main dock widget container.

    Displays signal details in a side panel with tabs:
    - Summary (top)
    - Overview (default)
    - Time Behavior
    - Advanced (collapsed)
    """
    def __init__(self, event_store, theme, parent=None):
        super().__init__("Signal Details", parent)
        self.event_store = event_store
        self.theme = theme
        self.current_event = None

        # Configure dock widget
        self.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )

        # Main container
        container = QWidget()
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Signal summary (always visible)
        self.summary = SignalSummary()
        main_layout.addWidget(self.summary)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget {{
                background-color: #0e1117;
            }}
            QTabBar::tab {{
                background-color: #161b22;
                color: #c9d1d9;
                padding: 6px 12px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                border-bottom-color: #58a6ff;
            }}
            QTabBar::tab:hover {{
                background-color: #21262d;
            }}
        """)

        # Create tabs
        self.overview_tab = OverviewTab()
        self.time_behavior_tab = TimeBehaviorTab()
        self.advanced_tab = AdvancedTab()

        self.tabs.addTab(self.overview_tab, "Overview")
        self.tabs.addTab(self.time_behavior_tab, "Time Behavior")
        self.tabs.addTab(self.advanced_tab, "Advanced")

        main_layout.addWidget(self.tabs)

        self.setWidget(container)

        # Set initial visibility
        self.hide()

    def show_event(self, event_id: str):
        """
        Display details for a specific emitter (preferred) or event.

        Args:
            event_id: ID of the event to display
        """
        item = None
        try:
            # Prefer emitter store API if present.
            if hasattr(self.event_store, 'get_emitter'):
                item = self.event_store.get_emitter(event_id)
            elif hasattr(self.event_store, 'get_event'):
                item = self.event_store.get_event(event_id)
        except Exception:
            item = None

        if not item:
            self.hide()
            return

        self.current_event = item

        # Require extracted features, but allow active emitters.
        features = getattr(item, 'features', None) or {}
        if not features:
            self.hide()
            return

        # Update all tabs
        self.summary.set_summary(item)
        self.overview_tab.display_event(item)
        self.time_behavior_tab.display_event(item)
        self.advanced_tab.display_event(item)

        # Show the dock
        self.show()
        self.tabs.setCurrentIndex(0)  # Reset to Overview tab

    def hide_event(self):
        """Hide the detail view."""
        self.current_event = None
        self.hide()

    def clear_event(self):
        """Clear selection (used by Clear/Reset)."""
        self.hide_event()
