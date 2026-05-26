# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
ATAK feature-stream toggles — which classes of events Ares publishes to TAK
when the master ATAK switch (settings.atak_enabled) is on.

  lobs            publish_lob          — DF bearings from the SDR stream
  emitter_fixes   publish_fix          — geolocated emitters (≥2 LoBs)
  chat            publish_chat         — MANET GeoChat ↔ ATAK chat
  tracks          track_cot_bridge     — Kalman / GM-PHD track heartbeats

Default ON. Operator toggles them from the ATAK / Server panel. Choice is
persisted to data/.atak_streams.json so it survives a backend restart.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Mapping

from app.core.security import DATA_DIR

log = logging.getLogger(__name__)

_FILE = DATA_DIR / ".atak_streams.json"

DEFAULTS: dict[str, bool] = {
    "lobs":          True,
    "emitter_fixes": True,
    "chat":          True,
    "tracks":        True,
}

_lock = threading.Lock()
_state: dict[str, bool] | None = None


def _load() -> dict[str, bool]:
    try:
        if _FILE.exists():
            d = json.loads(_FILE.read_text())
            return {k: bool(d.get(k, v)) for k, v in DEFAULTS.items()}
    except (OSError, ValueError) as e:
        log.debug("atak_streams load failed: %s", e)
    return dict(DEFAULTS)


def get() -> dict[str, bool]:
    """Current stream-toggle state (lazily loaded from disk)."""
    global _state
    with _lock:
        if _state is None:
            _state = _load()
        return dict(_state)


def set_streams(updates: Mapping[str, bool]) -> dict[str, bool]:
    """Merge ``updates`` into the stream state, persist, return the new state."""
    global _state
    with _lock:
        if _state is None:
            _state = _load()
        for k, v in updates.items():
            if k in DEFAULTS:
                _state[k] = bool(v)
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            _FILE.write_text(json.dumps(_state))
        except OSError as e:
            log.warning("atak_streams persist failed: %s", e)
        return dict(_state)


def is_enabled(key: str) -> bool:
    return get().get(key, False)
