# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

from __future__ import annotations

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QRectF
import pyqtgraph as pg
import numpy as np


def _clamp_int(v: int, lo: int, hi: int) -> int:
	return int(max(lo, min(hi, int(v))))


def _parse_palette(name: str) -> str:
	n = (name or "").strip().lower()
	if n in {"gray", "grey", "grayscale", "greyscale"}:
		return "grayscale"
	if n in {"viridis", "inferno", "plasma", "turbo"}:
		return n
	return "viridis"


def _build_lut(palette: str, n: int = 256) -> np.ndarray:
	palette = _parse_palette(palette)
	try:
		import matplotlib.cm as cm
		cmap = cm.get_cmap("gray" if palette == "grayscale" else palette)
		lut = (cmap(np.linspace(0.0, 1.0, n)) * 255).astype(np.ubyte)
		return lut
	except Exception:
		pass
	try:
		name = "gray" if palette == "grayscale" else palette
		cmap = pg.colormap.get(name)
		lut = cmap.getLookupTable(0.0, 1.0, n, alpha=True)
		return lut.astype(np.ubyte)
	except Exception:
		g = np.linspace(0, 255, n, dtype=np.ubyte)
		return np.stack([g, g, g, np.full_like(g, 255)], axis=1)


class SpectrumView(QWidget):

	def update_snapshot(self, snapshot):
		freqs = snapshot["freqs"]
		psd = snapshot["psd"]
		self.curve.setData(freqs / 1e6, psd)
		self.set_detected(snapshot["detected"])
		self.update_segments(snapshot["segments"])

		# Waterfall is Inspector-only and purely visual.
		if self._is_inspector_mode and self._waterfall_enabled:
			self._maybe_reset_on_freq_change(freqs)
			self._append_waterfall_row(psd, freqs)

	def update_segments(self, segments):
		# Reuse pre-created region items to avoid heavy Qt object churn.
		max_regions = len(self.band_regions)
		for i in range(max_regions):
			if i < len(segments):
				seg = segments[i]
				low = seg["low_hz"] / 1e6
				high = seg["high_hz"] / 1e6
				self.band_regions[i].setRegion((low, high))
				self.band_regions[i].show()
			else:
				self.band_regions[i].hide()

	def set_detected(self, detected: bool):
		if detected == self.detected:
			return
		self.detected = detected
		if detected:
			self.plot.setBackground("#0f1a12")  # subtle greenish
		else:
			self.plot.setBackground(self.theme.get("background"))

	def set_inspector_mode(self, is_inspector: bool) -> None:
		self._is_inspector_mode = bool(is_inspector)
		# Scanner mode never shows waterfall.
		self._apply_waterfall_visibility()

	def set_waterfall_enabled(self, enabled: bool) -> None:
		self._waterfall_enabled = bool(enabled)
		self._apply_waterfall_visibility()
		if not self._waterfall_enabled:
			self.reset_waterfall()

	def set_waterfall_palette(self, palette: str) -> None:
		self._waterfall_palette = _parse_palette(palette)
		self._waterfall_lut = _build_lut(self._waterfall_palette)
		# Force refresh
		if self._waterfall_img is not None:
			self._waterfall_item.setImage(
				self._waterfall_img,
				autoLevels=False,
				levels=(self._waterfall_min_db, self._waterfall_max_db),
				lut=self._waterfall_lut,
			)

	def set_waterfall_range_db(self, range_db: float) -> None:
		# We model as (min,max) with fixed max and slider controlling range.
		try:
			r = float(range_db)
		except Exception:
			r = 60.0
		r = max(10.0, min(120.0, r))
		self._waterfall_range_db = r
		self._waterfall_min_db = float(self._waterfall_max_db - self._waterfall_range_db)
		if self._waterfall_img is not None:
			self._waterfall_item.setLevels((self._waterfall_min_db, self._waterfall_max_db))

	def reset_waterfall(self) -> None:
		self._waterfall_img = None
		self._last_freqs_hint = None
		try:
			self._waterfall_item.clear()
		except Exception:
			pass

	def set_spectrum_style(
		self,
		*,
		rgba: tuple[int, int, int, int] | None = None,
		line_width: float | None = None,
		fill_enabled: bool | None = None,
		fill_alpha: int | None = None,
	) -> None:
		if rgba is not None:
			r, g, b, a = rgba
			self._spectrum_rgba = (
				_clamp_int(r, 0, 255),
				_clamp_int(g, 0, 255),
				_clamp_int(b, 0, 255),
				_clamp_int(a, 40, 255),  # clamp alpha to prevent invisibility
			)
		if line_width is not None:
			try:
				self._spectrum_line_width = float(line_width)
			except Exception:
				pass
			self._spectrum_line_width = max(0.5, min(6.0, self._spectrum_line_width))
		if fill_enabled is not None:
			self._spectrum_fill_enabled = bool(fill_enabled)
		if fill_alpha is not None:
			self._spectrum_fill_alpha = _clamp_int(int(fill_alpha), 10, 200)
		self._apply_spectrum_style()

	def __init__(self, theme):
		super().__init__()
		self.theme = theme

		layout = QVBoxLayout(self)
		layout.setContentsMargins(0, 0, 0, 0)
		layout.setSpacing(2)

		# Spectrum plot (always visible)
		self.plot = pg.PlotWidget()
		self.plot.setBackground(self.theme.get("background"))
		self.plot.showGrid(x=True, y=True, alpha=0.2)
		self.plot.setLabel('left', 'Power', units='dB')
		self.plot.setLabel('bottom', 'Frequency', units='MHz')
		self.plot.setTitle('Power Spectral Density')
		self.plot.setMinimumHeight(100)
		layout.addWidget(self.plot, stretch=3)

		# Waterfall plot (Inspector-only, hidden by default)
		self._waterfall_plot = pg.PlotWidget()
		self._waterfall_plot.setBackground(self.theme.get("background"))
		self._waterfall_plot.showGrid(x=True, y=False, alpha=0.2)
		self._waterfall_plot.setLabel('bottom', 'Frequency', units='MHz')
		self._waterfall_plot.setLabel('left', 'Time')
		self._waterfall_plot.getAxis('left').setStyle(showValues=False)
		self._waterfall_plot.getAxis('left').setTicks([])
		self._waterfall_plot.setMouseEnabled(x=True, y=False)
		self._waterfall_plot.setMinimumHeight(100)
		self._waterfall_plot.setXLink(self.plot)
		layout.addWidget(self._waterfall_plot, stretch=2)

		# Spectrum style (user-customizable)
		self._spectrum_rgba = (88, 166, 255, 255)
		self._spectrum_line_width = 1.5
		self._spectrum_fill_enabled = False
		self._spectrum_fill_alpha = 60
		self.curve = self.plot.plot()
		self._apply_spectrum_style()

		# Detection overlay
		self.band_regions = []
		self.detected = False

		# Waterfall state (Inspector-only)
		self._is_inspector_mode = True
		self._waterfall_enabled = False
		self._waterfall_history = 200
		self._waterfall_img: np.ndarray | None = None
		self._waterfall_palette = "viridis"
		self._waterfall_lut = _build_lut(self._waterfall_palette)
		self._waterfall_max_db = -20.0
		self._waterfall_range_db = 60.0
		self._waterfall_min_db = float(self._waterfall_max_db - self._waterfall_range_db)
		self._last_freqs_hint: tuple[float, float] | None = None
		self._last_freq_bounds_mhz: tuple[float, float] | None = None

		self._waterfall_item = pg.ImageItem()
		self._waterfall_item.setAutoDownsample(True)
		self._waterfall_item.setZValue(-20)
		self._waterfall_plot.addItem(self._waterfall_item)
		self._waterfall_plot.setYRange(0, self._waterfall_history, padding=0)

		self._apply_waterfall_visibility()

		# Pre-create a small pool of region overlays.
		# Most frames have 0-2 segments; keeping this bounded avoids UI lag.
		for _ in range(8):
			region = pg.LinearRegionItem(
				values=(0.0, 0.0),
				brush=pg.mkBrush(self.theme.get("detection_fill") + "80"),
			)
			region.setZValue(-10)
			region.hide()
			self.plot.addItem(region)
			self.band_regions.append(region)

		# Dummy data for now
		x = np.linspace(-1, 1, 1024)
		y = -80 + 10 * np.random.randn(1024)
		self.curve.setData(x, y)

	def update_psd(self, freqs, psd):
		self.curve.setData(freqs / 1e6, psd)

	def _apply_spectrum_style(self) -> None:
		r, g, b, a = self._spectrum_rgba
		pen = pg.mkPen((r, g, b, a), width=float(self._spectrum_line_width))
		brush = None
		if self._spectrum_fill_enabled:
			brush = pg.mkBrush((r, g, b, _clamp_int(int(self._spectrum_fill_alpha), 10, 200)))
		self.curve.setPen(pen)
		if brush is not None:
			self.curve.setBrush(brush)
			self.curve.setFillLevel(self._waterfall_min_db)
		else:
			self.curve.setBrush(None)
			self.curve.setFillLevel(None)

	def _apply_waterfall_visibility(self) -> None:
		show = bool(self._is_inspector_mode and self._waterfall_enabled)
		self._waterfall_plot.setVisible(show)
		# Hide spectrum bottom axis when waterfall is shown (waterfall has it)
		try:
			self.plot.getAxis('bottom').setStyle(showValues=not show)
		except Exception:
			pass

	def _maybe_reset_on_freq_change(self, freqs_hz: np.ndarray) -> None:
		# Reset if the x-axis meaning changed (retune or different FFT bins).
		try:
			f0 = float(freqs_hz[0])
			f1 = float(freqs_hz[-1])
		except Exception:
			return
		cur = (f0, f1)
		if self._last_freqs_hint is None:
			self._last_freqs_hint = cur
			self._update_waterfall_rect_from_freqs(freqs_hz)
			return
		prev0, prev1 = self._last_freqs_hint
		# Any meaningful change triggers a reset.
		if abs(prev0 - f0) > 1.0 or abs(prev1 - f1) > 1.0:
			self.reset_waterfall()
			self._last_freqs_hint = cur
			self._update_waterfall_rect_from_freqs(freqs_hz)

	def _update_waterfall_rect_from_freqs(self, freqs_hz: np.ndarray) -> None:
		"""Map the image pixels to the spectrum x-axis (MHz).

		Without this, ImageItem defaults to x=0..N bins, which is off-screen
		when the plot x-axis is in MHz.
		"""
		try:
			x0 = float(freqs_hz[0]) / 1e6
			x1 = float(freqs_hz[-1]) / 1e6
		except Exception:
			return
		x_min = min(x0, x1)
		x_max = max(x0, x1)
		if not np.isfinite(x_min) or not np.isfinite(x_max) or (x_max - x_min) <= 0:
			return
		self._last_freq_bounds_mhz = (x_min, x_max)
		try:
			self._waterfall_item.setRect(QRectF(x_min, 0.0, (x_max - x_min), float(self._waterfall_history)))
		except Exception:
			pass

	def _append_waterfall_row(self, psd_db: np.ndarray, freqs_hz: np.ndarray | None = None) -> None:
		try:
			row = np.asarray(psd_db, dtype=np.float32)
		except Exception:
			return

		if freqs_hz is not None:
			self._update_waterfall_rect_from_freqs(freqs_hz)

		bins = int(row.shape[0])
		if bins <= 0:
			return
		if self._waterfall_img is None or self._waterfall_img.shape[1] != bins:
			self._waterfall_img = np.full((self._waterfall_history, bins), np.nan, dtype=np.float32)

		# Shift up and insert new row at bottom.
		self._waterfall_img[:-1, :] = self._waterfall_img[1:, :]
		self._waterfall_img[-1, :] = row

		# Display with LUT + fixed dB levels.
		self._waterfall_item.setImage(
			self._waterfall_img,
			autoLevels=False,
			levels=(self._waterfall_min_db, self._waterfall_max_db),
			lut=self._waterfall_lut,
		)
