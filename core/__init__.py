# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Pranav Dhiran

"""Core detection engine.

Public API:
- RFConfig: Configuration parameters
- Detector: Binary signal presence detection
- Segmenter: FFT-based frequency segmentation
- EventBuilder: Time aggregation of segments
- FeatureExtractor: Feature extraction on event close
- EmitterTracker: Emitter identity inference
- IQStream: Thread-safe IQ sample buffer
- EngineController: Mode lifecycle and state machine
- SignalEvent: Signal event dataclass
"""

