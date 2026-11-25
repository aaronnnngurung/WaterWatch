"""Rainfall-triggered contamination event model."""

import math
import time


class ContaminationEvent:
    """
    Models a contamination event with:
    - A rapid rise
    - A peak
    - An exponential washout

    Intensity ranges from 0.0 (no event) to 1.0 (peak).
    """

    def __init__(
        self,
        rise_seconds=120,
        washout_seconds=1800,
        start_time=None
    ):
        self.rise_seconds = rise_seconds
        self.washout_seconds = washout_seconds
        self.start_time = start_time
        self.active = False

    def start(self, start_time=None):
        """Start the event."""
        self.start_time = start_time or time.time()
        self.active = True

    def stop(self):
        """Stop the event."""
        self.active = False
        self.start_time = None

    def get_intensity(self, current_time=None):
        """Return the current event intensity from 0.0 to 1.0."""
        if not self.active or self.start_time is None:
            return 0.0

        now = current_time or time.time()
        elapsed = max(0.0, now - self.start_time)

        if elapsed <= self.rise_seconds:
            # Fast initial rise towards the peak.
            intensity = 1.0 - math.exp(
                -5.0 * elapsed / self.rise_seconds
            )
        else:
            # Slow exponential washout after the rise.
            washout_elapsed = elapsed - self.rise_seconds
            peak_intensity = 1.0 - math.exp(-5.0)
            intensity = peak_intensity * math.exp(
                -washout_elapsed / self.washout_seconds
            )

        return max(0.0, min(1.0, intensity))
