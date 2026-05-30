"""
Event construction and time aggregation.

Turns per-chunk detections + segments into coherent, time-bounded SignalEvents.

Core concept:
    A SignalEvent exists when the same frequency segment persists across time.

Matching rule:
    Two segments belong to the same event if:
        |center_new - center_old| < MATCH_BW_FACTOR × bandwidth_old
"""

import uuid
import os
from typing import List, Dict, Any, Optional
from .event import SignalEvent
from .config import RFConfig
from .feature_extractor import FeatureExtractor


class EventBuilder:
    """
    Manages signal event lifecycle and matching.
    
    Sits between Segmenter and FeatureExtractor.
    
    Responsibilities:
    - Match new segments to existing events
    - Start new events for unmatched segments
    - Update events with new observations
    - Close events after max_misses or when detector says absent
    
    States:
    - ACTIVE: Event currently being tracked
    - CLOSED: Event finalized and ready for feature extraction
    """

    def __init__(self, config: RFConfig, event_publisher=None):
        """
        Initialize event builder.

        Args:
            config: RFConfig instance with matching parameters
            event_publisher: Optional EventPublisher instance
        """
        self.config = config
        self.active_events: List[SignalEvent] = []
        self.closed_events: List[SignalEvent] = []
        self._event_counter = 0
        self.event_publisher = event_publisher
        self.feature_extractor = FeatureExtractor()

    def process(
        self, timestamp: float, detected: bool, segments: List[Dict[str, Any]]
    ) -> Dict[str, List[SignalEvent]]:
        """
        Process one chunk's detection results.

        Args:
            timestamp: Current chunk timestamp (absolute time)
            detected: Boolean from detector (signal present/absent)
            segments: List of frequency segments from segmenter

        Returns:
            Dictionary with:
                'active': List of currently active events
                'closed': List of newly closed events (this iteration only)
        """

        if os.getenv("RFWATCH_DEBUG", "").lower() in {"1", "true", "yes", "on"}:
            print(
                f"[EVENT_BUILDER] detected={detected} "
                f"segments={len(segments)} "
                f"active_events={len(self.active_events)}"
            )

        matched_events = []
        newly_closed = []

        if detected and segments:
            # Match or create events for each segment
            for seg in segments:
                event = self._match_event(seg)
                if event:
                    # Only emit if hit_count increases (meaningful update)
                    prev_hit = event.hit_count
                    self._update_event(event, seg, timestamp)
                    if event not in matched_events:
                        matched_events.append(event)
                    if self.event_publisher and event.hit_count != prev_hit:
                        print(f"[EventBuilder] Event updated: {event.id} (hit_count={event.hit_count})")
                        self.event_publisher.event_updated.emit(event)
                else:
                    new_event = self._start_event(seg, timestamp)
                    matched_events.append(new_event)
                    if self.event_publisher:
                        print(f"[EventBuilder] New event: {new_event.id}")
                        self.event_publisher.event_updated.emit(new_event)

        # Handle misses: increment miss count for unmatched events
        for event in list(self.active_events):
            if event not in matched_events:
                event.miss_count += 1

                event.timestamp_history.append(timestamp)
                event.present_history.append(False)
                if event.miss_count >= self.config.max_misses:
                    closed = self._close_event(event, timestamp)
                    newly_closed.append(closed)
                    if self.event_publisher:
                        print(f"[EventBuilder] Event closed: {closed.id}")
                        self.event_publisher.event_closed.emit(closed)
            else:
                # Reset miss count on successful match
                event.miss_count = 0

        return {"active": self.active_events.copy(), "closed": newly_closed}

    def _match_event(self, segment: Dict[str, Any]) -> Optional[SignalEvent]:
        """
        Find existing active event that matches this segment.

        Matching rule:
            |center_new - center_old| < match_bw_factor * bandwidth_old

        Args:
            segment: Frequency segment dict with center_hz, bandwidth_hz

        Returns:
            Matching SignalEvent or None
        """
        seg_center = segment["center_hz"]

        for event in self.active_events:
            center_diff = abs(seg_center - event.last_center)
            threshold = self.config.match_bw_factor * event.last_bandwidth

            if center_diff < threshold:
                return event

        return None

    def _start_event(
        self, segment: Dict[str, Any], timestamp: float
    ) -> SignalEvent:
        """
        Create new SignalEvent from segment.

        Args:
            segment: Frequency segment dict
            timestamp: Event start time

        Returns:
            Newly created SignalEvent
        """
        self._event_counter += 1
        event_id = f"event_{self._event_counter:06d}"

        event = SignalEvent(
            id=event_id,
            start_time=timestamp,
            active=True,
            last_center=segment["center_hz"],
            last_bandwidth=segment["bandwidth_hz"],
            last_seen=timestamp,
            hit_count=1,
            miss_count=0,
        )

        # Initialize history
        event.center_freq_history.append(segment["center_hz"])
        event.bandwidth_history.append(segment["bandwidth_hz"])
        event.power_history.append(segment.get("peak_db", 0.0))

        event.timestamp_history.append(timestamp)
        event.present_history.append(True)

        self.active_events.append(event)

        return event

    def _update_event(
        self, event: SignalEvent, segment: Dict[str, Any], timestamp: float
    ) -> None:
        """
        Update existing event with new segment observation.

        Args:
            event: Event to update
            segment: New frequency segment
            timestamp: Current time
        """
        # Update tracking values
        event.last_center = segment["center_hz"]
        event.last_bandwidth = segment["bandwidth_hz"]
        event.last_seen = timestamp
        event.hit_count += 1

        # Append to history
        event.center_freq_history.append(segment["center_hz"])
        event.bandwidth_history.append(segment["bandwidth_hz"])
        event.power_history.append(segment.get("peak_db", 0.0))

        event.timestamp_history.append(timestamp)
        event.present_history.append(True)

    def _close_event(self, event: SignalEvent, timestamp: float) -> SignalEvent:
        """
        Close an active event and move to closed list.
        Automatically extracts features on close.

        Args:
            event: Event to close
            timestamp: End time

        Returns:
            The closed event
        """
        event.close(timestamp)
        self.active_events.remove(event)
        self.closed_events.append(event)
        
        # Extract features on close
        try:
            event.features = self.feature_extractor.extract(event)
        except Exception as e:
            print(f"[EventBuilder] Feature extraction failed for {event.id}: {e}")

        return event

    def get_active_events(self) -> List[SignalEvent]:
        """Get list of currently active events."""
        return self.active_events.copy()

    def get_closed_events(self) -> List[SignalEvent]:
        """Get list of all closed events."""
        return self.closed_events.copy()

    def reset(self) -> None:
        """Clear all events and reset state."""
        self.active_events.clear()
        self.closed_events.clear()
        self._event_counter = 0
