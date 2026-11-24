# -*- coding: utf-8 -*-
"""Movement settings model: defaults, limits, validation and pure math.

Nothing in this module touches Windows or Qt, so it can be unit tested anywhere.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULTS = {
    "x": 0,
    "y": 20,
    "duration": 300,
    "smoothness": 80,
    "speed": 1.0,
    "easing": "linear",
}
LIMITS = {
    "x": (-2000, 2000),
    "y": (-2000, 2000),
    "duration": (10, 5000),
    "smoothness": (1, 100),
    "speed": (0.1, 5.0),
}
EASINGS = ["linear", "ease_in", "ease_out", "ease_in_out"]
EASING_LABELS = {
    "linear": "Linear (constant)",
    "ease_in": "Ease In (slow start)",
    "ease_out": "Ease Out (fast start)",
    "ease_in_out": "Ease In-Out (smooth start)",
}

PRESET_COUNT = 4
PRESET_NAME_MAX = 24


def sanitize(raw) -> dict:
    """Return a fully valid settings dict (clamped, correct types).

    Unknown keys (for example the V1 "repeat" flag) are ignored.
    """
    out = dict(DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in ("x", "y", "duration", "smoothness"):
        try:
            v = float(raw.get(key, out[key]))
            if math.isnan(v) or math.isinf(v):
                raise ValueError
            v = int(round(v))
        except (TypeError, ValueError, OverflowError):
            v = out[key]
        lo, hi = LIMITS[key]
        out[key] = max(lo, min(hi, v))
    try:
        sp = round(float(raw.get("speed", out["speed"])), 1)
        if math.isnan(sp) or math.isinf(sp):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        sp = out["speed"]
    out["speed"] = max(LIMITS["speed"][0], min(LIMITS["speed"][1], sp))
    easing = raw.get("easing", out["easing"])
    out["easing"] = easing if easing in EASINGS else out["easing"]
    return out


def ease(u: float, mode: str) -> float:
    """Map linear progress u in [0, 1] to eased progress in [0, 1]."""
    u = 0.0 if u < 0.0 else 1.0 if u > 1.0 else u
    if mode == "ease_in":
        return u * u
    if mode == "ease_out":
        return 1.0 - (1.0 - u) * (1.0 - u)
    if mode == "ease_in_out":
        return u * u * (3.0 - 2.0 * u)
    return u


def tick_interval_s(smoothness: int) -> float:
    """Smoothness 1..100 -> update interval 8 ms .. 1 ms (125 Hz .. 1000 Hz)."""
    smoothness = max(1, min(100, int(smoothness)))
    return (8.0 - 7.0 * (smoothness - 1) / 99.0) / 1000.0


def effective_duration_ms(duration: int, speed: float) -> float:
    """Reference time (ms) for one X/Y travel at the given speed multiplier."""
    return max(5.0, duration / max(0.1, speed))


@dataclass(frozen=True)
class MovementParams:
    """Precomputed, immutable values used by the engine every tick.

    vx / vy   : steady rate in mouse units per second.
                X and Y are the distance covered per reference Duration, so
                rate = distance / (Duration / Speed).
    ramp_s    : length of the start-up ramp (the easing curve is applied to
                this ramp only, never repeated).
    interval  : target time between two updates (from Smoothness).
    """

    vx: float
    vy: float
    ramp_s: float
    easing: str
    interval: float

    @classmethod
    def from_settings(cls, settings: dict) -> "MovementParams":
        s = sanitize(settings)
        eff_s = effective_duration_ms(s["duration"], s["speed"]) / 1000.0
        return cls(
            vx=s["x"] / eff_s,
            vy=s["y"] / eff_s,
            ramp_s=eff_s,
            easing=s["easing"],
            interval=tick_interval_s(s["smoothness"]),
        )

    def envelope(self, held_s: float) -> float:
        """Rate multiplier 0..1 after the buttons have been held for held_s."""
        if self.easing == "linear" or self.ramp_s <= 0.0:
            return 1.0
        return ease(held_s / self.ramp_s, self.easing)
