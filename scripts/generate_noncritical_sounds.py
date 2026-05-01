"""
Non-critical notification sound generator for BlueBird Alerts.

IMPORTANT:
  - These are NON-CRITICAL sounds only. Do NOT use for emergency alerts.
  - Tuned for calm school environments: short, gentle, non-startling.
  - No siren, alarm, or urgent characteristics.
  - Emergency alert sound is managed separately (bluebird_alarm).

Usage:
    python3 generate_noncritical_sounds.py

Output files are placed in ../android/app/src/main/res/raw/ relative to this script.

Dependencies:
    pip install numpy scipy
"""
from __future__ import annotations

import os
import struct
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
OUT_DIR = Path(__file__).parent.parent / "android" / "app" / "src" / "main" / "res" / "raw"


def tone(frequency: float, duration_ms: float, volume: float = 0.3) -> np.ndarray:
    """Generate a single sine-wave tone with 10% fade-in/out envelope."""
    t = np.linspace(0, duration_ms / 1000, int(SAMPLE_RATE * duration_ms / 1000), endpoint=False)
    wave = np.sin(2 * np.pi * frequency * t)
    fade_len = max(1, int(len(wave) * 0.1))
    fade = np.linspace(0, 1, fade_len)
    wave[:fade_len] *= fade
    wave[-fade_len:] *= fade[::-1]
    return wave * volume


def silence(duration_ms: float) -> np.ndarray:
    return np.zeros(int(SAMPLE_RATE * duration_ms / 1000))


def save(name: str, data: np.ndarray) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    peak = np.max(np.abs(data))
    audio = np.int16(data / peak * 32767) if peak > 0 else np.int16(data)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    print(f"  ✓  {path.relative_to(OUT_DIR.parent.parent.parent.parent.parent.parent)}")


# ---------------------------------------------------------------------------
# Sound definitions — calm, short, school-safe
# ---------------------------------------------------------------------------

# Quiet request: two ascending gentle tones — "something needs attention"
quiet_request = np.concatenate([
    tone(850, 140),
    silence(80),
    tone(1050, 140),
])
save("quiet_request.wav", quiet_request)

# Quiet approved / denied confirmation: ascending two-tone resolution
quiet_approved = np.concatenate([
    tone(900, 120),
    silence(40),
    tone(1200, 160),
])
save("quiet_approved.wav", quiet_approved)

# Message received: single soft mid tone
message_received = tone(950, 100)
save("message_received.wav", message_received)

# Team assist: two tones with slight urgency but still non-alarming
team_assist = np.concatenate([
    tone(700, 140),
    silence(70),
    tone(900, 140),
])
save("team_assist.wav", team_assist)

# System notice: single neutral tone (lower than message for lower priority feel)
system_notice = tone(800, 180)
save("system_notice.wav", system_notice)

print("\n✅  All non-critical sound files generated successfully.")
print(f"    Output directory: {OUT_DIR}")
