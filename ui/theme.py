# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

import json
from pathlib import Path

DEFAULT_THEME = {
	"background": "#0e1117",
	"spectrum_line": "#58a6ff",
	"detection_fill": "#2ea043",
	"noise_floor": "#8b949e",
	"highlight": "#d29922",
	"text": "#c9d1d9"
}

class Theme:
	def __init__(self, theme_path=None):
		self.colors = DEFAULT_THEME.copy()

		if theme_path:
			self.load(theme_path)

	def load(self, path):
		path = Path(path)
		if path.exists():
			with open(path, "r") as f:
				self.colors.update(json.load(f))

	def get(self, key):
		return self.colors.get(key)
