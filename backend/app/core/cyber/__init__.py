# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
Cyber capabilities (roadmap item 11 / Track-C "C6").

Exposes pentest-class capabilities by what they *do* — sub-GHz, low-frequency
RFID (125 kHz), and high-frequency NFC (13.56 MHz) — without naming any specific
device. Sub-GHz runs on the real SDR stack; the contactless capabilities run over
a connected USB field tool's serial CLI (see :mod:`.tools`). Nothing is faked:
with no suitable hardware, detection is empty and actions raise.

**Authorization gate.** Passive actions (scan / read / sniff / receive) need only the
hardware. Active actions (transmit / replay / emulate / clone / write / inject) are
refused unless the authorized-active gate is on, and every attempt is audit-logged.
The gate defaults OFF (``ARES_AUTHORIZED_ACTIVE``) and can be toggled at runtime.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from app.config import settings
from app.core.security import DATA_DIR, audit
from . import subghz, tools
from .tools import ToolUnavailable

log = logging.getLogger(__name__)

_GATE_FILE = DATA_DIR / ".authorized_active"


class NotAuthorized(PermissionError):
    """Active capability invoked while the authorized-active gate is off."""


# ── capability catalog (static metadata describing the feature surface) ─────────
# kind: "passive" (hardware only) | "active" (gated + audited).
CATALOG: list[dict] = [
    {"id": "subghz", "label": "Sub-GHz", "band": "≈300–928 MHz ISM", "transport": "sdr",
     "desc": "Scan, record, and replay sub-GHz ISM bursts (remotes, sensors, fobs) over an SDR.",
     "actions": [
         {"id": "scan", "label": "Scan band", "kind": "passive"},
         {"id": "capture", "label": "Capture burst", "kind": "passive"},
         {"id": "replay", "label": "Replay burst", "kind": "active"},
     ]},
    {"id": "rfid_lf", "label": "RFID (low-frequency)", "band": "125 kHz", "transport": "tool",
     "desc": "Read, clone, and emulate 125 kHz proximity credentials.",
     "actions": [
         {"id": "read", "label": "Read tag", "kind": "passive"},
         {"id": "sniff", "label": "Sniff reader", "kind": "passive"},
         {"id": "clone", "label": "Clone to writable tag", "kind": "active"},
         {"id": "emulate", "label": "Emulate tag", "kind": "active"},
     ]},
    {"id": "nfc_hf", "label": "NFC / RFID (high-frequency)", "band": "13.56 MHz", "transport": "tool",
     "desc": "Read, emulate, and sniff 13.56 MHz NFC / contactless cards.",
     "actions": [
         {"id": "read", "label": "Read card", "kind": "passive"},
         {"id": "sniff", "label": "Sniff field", "kind": "passive"},
         {"id": "emulate", "label": "Emulate card", "kind": "active"},
         {"id": "write", "label": "Write card", "kind": "active"},
     ]},
]

_CATALOG_BY_ID = {c["id"]: c for c in CATALOG}


def _action_kind(category: str, action: str) -> Optional[str]:
    cat = _CATALOG_BY_ID.get(category)
    if not cat:
        return None
    for a in cat["actions"]:
        if a["id"] == action:
            return a["kind"]
    return None


# ── authorization gate ──────────────────────────────────────────────────────────
def _read_gate() -> bool:
    try:
        if _GATE_FILE.exists():
            return _GATE_FILE.read_text().strip() in ("1", "true", "yes", "on")
    except OSError:
        pass
    return bool(settings.authorized_active)


_gate_state: Optional[bool] = None


def authorized_active() -> bool:
    global _gate_state
    if _gate_state is None:
        _gate_state = _read_gate()
    return _gate_state


def set_authorized_active(on: bool, by: str = "") -> bool:
    global _gate_state
    _gate_state = bool(on)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        _GATE_FILE.write_text("1" if on else "0")
    except OSError as e:
        log.warning("could not persist authorized-active gate: %s", e)
    audit("cyber.authorized_active", enabled=bool(on), by=by)
    return _gate_state


# ── detection ───────────────────────────────────────────────────────────────────
# Enumerating serial ports + SoapySDR devices costs ~0.5 s, so cache it: hardware
# doesn't change between UI polls, and re-running it every few seconds blocks the
# event loop and janks the rest of the app. The gate state is always read fresh
# (it's cheap and can toggle at runtime). Call detect(force=True) to bypass.
_DETECT_TTL_S = 10.0
_detect_lock = threading.Lock()
_detect_cache: dict = {"t": 0.0, "data": None}


def _detect_uncached() -> dict:
    serial_tools = [t.public() for t in tools.detect_serial_tools()]
    try:
        sg = subghz.radios()
    except Exception as e:
        log.debug("subghz radios() failed: %s", e)
        sg = []
    available: set[str] = set()
    if sg:
        available.add("subghz")
    for t in serial_tools:
        available.update(t.get("capabilities", []))
    return {"tools": serial_tools, "subghz_radios": sg,
            "available_capabilities": sorted(available)}


def detect(force: bool = False) -> dict:
    """What's connected right now, mapped to capabilities (no device brand names).
    Cached for `_DETECT_TTL_S`; BLOCKING on a cache miss — call from an executor."""
    now = time.time()
    with _detect_lock:
        cached = _detect_cache["data"]
        if not force and cached is not None and now - _detect_cache["t"] < _DETECT_TTL_S:
            return {**cached, "authorized_active": authorized_active()}
    data = _detect_uncached()
    with _detect_lock:
        _detect_cache["t"] = time.time()
        _detect_cache["data"] = data
    return {**data, "authorized_active": authorized_active()}


# ── action dispatch ─────────────────────────────────────────────────────────────
# Generic serial-CLI command templates for the contactless capabilities.
# `{p}` interpolates params; whatever the connected tool replies is returned verbatim.
_CLI: dict[tuple[str, str], str] = {
    ("rfid_lf", "read"): "rfid read",
    ("rfid_lf", "sniff"): "rfid sniff",
    ("rfid_lf", "clone"): "rfid clone",
    ("rfid_lf", "emulate"): "rfid emulate {uid}",
    ("nfc_hf", "read"): "nfc read",
    ("nfc_hf", "sniff"): "nfc sniff",
    ("nfc_hf", "emulate"): "nfc emulate",
    ("nfc_hf", "write"): "nfc write {data}",
}


def run(category: str, action: str, params: Optional[dict] = None, *, by: str = "") -> dict:
    """Execute a capability action. Raises ValueError (bad request), NotAuthorized
    (active while gate off), ToolUnavailable / subghz.NoRadio / RadioBusy (no/busy
    hardware) — all surfaced honestly by the route layer."""
    params = params or {}
    kind = _action_kind(category, action)
    if kind is None:
        raise ValueError(f"unknown capability action {category}/{action}")

    active = kind == "active"
    if active and not authorized_active():
        audit("cyber.refused", category=category, action=action, reason="gate_off", by=by)
        raise NotAuthorized("active capability is disabled — enable Authorized Active "
                            "(ARES_AUTHORIZED_ACTIVE) within an authorized scope")
    if active:
        audit("cyber.active", category=category, action=action, params=params, by=by)

    # Sub-GHz → real SDR stack.
    if category == "subghz":
        if action == "scan":
            return subghz.scan(float(params.get("center_hz", 433.92e6)),
                               float(params.get("span_hz", 2.0e6)),
                               int(params.get("n_bins", 1024)), params.get("device_id"))
        if action == "capture":
            return subghz.capture(float(params.get("center_hz", 433.92e6)),
                                  float(params.get("rate_hz", 2.0e6)),
                                  float(params.get("seconds", 1.0)), params.get("device_id"))
        if action == "replay":
            return subghz.transmit(float(params.get("center_hz", 433.92e6)),
                                   float(params.get("rate_hz", 2.0e6)),
                                   capture_id=params.get("capture_id"),
                                   device_id=params.get("device_id"))

    # Contactless RFID / NFC → connected field tool's serial CLI.
    tmpl = _CLI.get((category, action))
    if tmpl is None:
        raise ValueError(f"action {category}/{action} has no handler")
    tool = tools.find_tool(category)
    try:
        cmd = tmpl.format(**{k: params.get(k, "") for k in _PARAM_KEYS})
    except Exception:
        cmd = tmpl
    reply = tools.cli(tool.port, tool.baud, cmd)
    return {"category": category, "action": action, "kind": kind, "tool": tool.public(),
            "command": cmd, "response": reply}


_PARAM_KEYS = ("uid", "data")


def raw_cli(tool_id: str, command: str, *, by: str = "") -> dict:
    """Send a raw command line to a connected field tool and return its reply verbatim.

    ACTIVE — a raw passthrough can drive transmit / emulate / write, so it requires
    the authorized-active gate and is audit-logged. This makes the contactless / IR /
    HID capabilities fully usable regardless of the tool's exact CLI grammar."""
    command = (command or "").strip()
    if not command:
        raise ValueError("empty command")
    if not authorized_active():
        audit("cyber.refused", category="raw_cli", action="send", reason="gate_off", by=by)
        raise NotAuthorized("the raw tool console is an active capability — enable "
                            "Authorized Active within an authorized scope")
    tool = tools.find_tool_by_id(tool_id)
    audit("cyber.active", category="raw_cli", action="send", tool=tool.kind, command=command, by=by)
    reply = tools.cli(tool.port, tool.baud, command)
    return {"tool": tool.public(), "command": command, "response": reply}
