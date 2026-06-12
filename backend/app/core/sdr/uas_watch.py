# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
sdr/uas_watch.py — passive drone-detection watch mode (the "Vanilka / Tsukorok"
capability) for the Video tab.

A single antenna can't bear or fix a drone, but it CAN do what a passive
man-portable detector does: continuously sweep the FPV/UAS bands, flag when a
drone video/RF emitter is present, say what KIND of system it is (platform
family — DJI drone / analog FPV / digital FPV / ISR-COFDM downlink / military
CDL / Remote-ID beacon), and report signal strength as a proximity cue. Closer
emitter ⇒ stronger signal ⇒ smaller proximity ring.

This module is the server-side engine (a singleton loop, same shape as
``sdr/gps_source`` and ``df/sc_live``) so the detection log, RSSI-trend history,
and alert state survive the Video tab being opened/closed and so CoT can be
pushed without the UI being up. The heavy classifier
(:func:`uas_video.classify_band`) is **blocking**, so every sweep runs in a
thread executor — never on the event loop.

Honesty: a watch detection carries presence + a coarse Friis range only. It is
plotted at the OPERATOR position as a dashed proximity ring, never as a located
fix. Geolocating the drone needs a DF array or its Remote-ID beacon.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from typing import Optional

log = logging.getLogger(__name__)

_MAXHOLD_KEY = "uas_watch"
_CLEAR_AFTER_MISSES = 4          # drop a detection after this many consecutive sweeps unseen
_RSSI_HIST = 6                   # samples kept for the trend arrow
_FPV_P_TX_DBM = 30.0            # generic EIRP for the proximity range estimate
_FPV_PATHLOSS_N = 2.5          # LOS-ish exponent for FPV/UAS downlinks

_STATE: dict = {
    "running": False, "device_id": None,
    "start_hz": None, "stop_hz": None, "step_hz": None, "interval_s": None,
    "min_rssi_dbm": None, "min_confidence": None, "use_iq": False,
    "started_ts": None, "last_sweep_ts": None, "n_sweeps": 0,
    "paused_reason": None, "last_error": None, "source": None,
}
_DETECTIONS: dict[str, dict] = {}
_TASK: Optional[asyncio.Task] = None


# ─────────────────────────────────────────────────────────────────────────────
def _proximity_range_m(rssi_dbm: Optional[float]) -> Optional[float]:
    """Coarse Friis log-distance range from received power — the proximity cue.
    None when there's no RSSI (e.g. a max-hold-synthesised hit)."""
    if rssi_dbm is None:
        return None
    d = 10.0 ** ((_FPV_P_TX_DBM - float(rssi_dbm)) / (10.0 * _FPV_PATHLOSS_N))
    return float(max(50.0, min(d, 30_000.0)))


def _trend(hist: deque) -> str:
    vals = [v for v in hist if v is not None]
    if len(vals) < 3:
        return "unknown"
    recent = vals[-1]
    base = sum(vals[:-1]) / len(vals[:-1])
    if recent - base > 3.0:
        return "rising"        # signal growing → emitter approaching
    if recent - base < -3.0:
        return "falling"
    return "steady"


def _overlaps(a_center, a_bw, b_center, b_bw) -> bool:
    return abs(a_center - b_center) < 0.5 * (a_bw + b_bw) * 0.6


def _match(det: dict) -> Optional[dict]:
    c, bw = det["center_hz"], det.get("bandwidth_hz", 1e6)
    for rec in _DETECTIONS.values():
        if _overlaps(c, bw, rec["center_hz"], rec.get("bandwidth_hz", 1e6)):
            return rec
    return None


def _public(rec: dict) -> dict:
    """Serialise a detection record (drop the internal rssi ring buffer)."""
    return {k: v for k, v in rec.items() if k != "_rssi_hist"}


def _ingest(result: dict, min_rssi: Optional[float], min_conf: float) -> None:
    now = time.time()
    seen: set[str] = set()
    for d in result.get("detections", []):
        conf = float(d.get("confidence", 0.0) or 0.0)
        rssi = d.get("rssi_dbm")
        if conf < min_conf:
            continue
        # Null-RSSI-safe: only gate on strength when an RSSI is actually present.
        if rssi is not None and min_rssi is not None and float(rssi) < min_rssi:
            continue
        rec = _match(d)
        if rec is None:
            key = f"{round(d['center_hz'] / 250e3) * 250:.0f}k"
            while key in _DETECTIONS:
                key += "_"
            rec = {
                "key": key, "center_hz": d["center_hz"], "bandwidth_hz": d.get("bandwidth_hz", 1e6),
                "feed_type": d.get("feed_type"), "feed_name": d.get("feed_name"),
                "platform_family": d.get("platform_family", "Unknown"),
                "first_seen": now, "_rssi_hist": deque(maxlen=_RSSI_HIST),
            }
            _DETECTIONS[key] = rec
        # update
        rec["center_hz"] = d["center_hz"]
        rec["bandwidth_hz"] = d.get("bandwidth_hz", rec["bandwidth_hz"])
        rec["feed_type"] = d.get("feed_type", rec["feed_type"])
        rec["feed_name"] = d.get("feed_name", rec["feed_name"])
        rec["platform_family"] = d.get("platform_family", rec["platform_family"])
        rec["confidence"] = round(conf, 2)
        rec["rssi_dbm"] = (None if rssi is None else round(float(rssi), 1))
        rec["_rssi_hist"].append(None if rssi is None else float(rssi))
        rec["rssi_trend"] = _trend(rec["_rssi_hist"])
        rec["range_est_m"] = _proximity_range_m(rssi)
        rec["last_seen"] = now
        rec["n_hits"] = rec.get("n_hits", 0) + 1
        rec["missed"] = 0
        rec["from_max_hold"] = bool(d.get("from_max_hold"))
        seen.add(rec["key"])
    # age out detections no sweep saw this pass — but only after a few misses,
    # since hopping links routinely vanish for a sweep.
    for key, rec in list(_DETECTIONS.items()):
        if key in seen:
            continue
        rec["missed"] = rec.get("missed", 0) + 1
        if rec["missed"] > _CLEAR_AFTER_MISSES:
            del _DETECTIONS[key]


def _decode_active(device_id: Optional[str]) -> bool:
    """True when a decode/characterise session is using this real device — the
    watch loop pauses so two captures don't fight over a single-stream radio.
    The synthetic device has no such constraint."""
    if not device_id or device_id == "synthetic":
        return False
    try:
        from app.core.sdr import uas_video
        for s in uas_video.list_sessions():
            if s.get("device_id") == device_id and s.get("status") in ("started", "characterize_only"):
                return True
    except Exception:
        pass
    return False


# ─────────────────────────────────────────────────────────────────────────────
async def _run(device_id, dev, start_hz, stop_hz, step_hz, interval_s,
               min_rssi, min_conf, use_iq) -> None:
    from app.core.sdr import uas_video
    loop = asyncio.get_event_loop()
    while True:
        try:
            if _decode_active(device_id):
                _STATE["paused_reason"] = "paused — a decode session is using this device"
            else:
                _STATE["paused_reason"] = None
                # classify_band is blocking + CPU-heavy → ALWAYS run it in an executor.
                res = await loop.run_in_executor(
                    None, lambda: uas_video.classify_band(
                        dev, start_hz, stop_hz, step_hz=step_hz, use_iq=use_iq,
                        max_hold=False, maxhold_key=_MAXHOLD_KEY))
                _ingest(res, min_rssi, min_conf)
                _STATE["source"] = res.get("source")
                _STATE["n_sweeps"] += 1
                _STATE["last_sweep_ts"] = time.time()
                _STATE["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _STATE["last_error"] = f"sweep error: {e}"
            log.debug("uas_watch sweep failed", exc_info=True)
        await asyncio.sleep(interval_s)


# ─────────────────────────────────────────────────────────────────────────────
def status() -> dict:
    dets = sorted(_DETECTIONS.values(),
                  key=lambda r: (-(r.get("rssi_dbm") if r.get("rssi_dbm") is not None else -999),
                                 -r.get("last_seen", 0)))
    return {**_STATE, "n_detections": len(dets),
            "detections": [_public(r) for r in dets]}


def detections() -> list[dict]:
    return status()["detections"]


def get(key: str) -> Optional[dict]:
    rec = _DETECTIONS.get(key)
    return _public(rec) if rec else None


def start(device_id: Optional[str], start_hz: float, stop_hz: float, *,
          step_hz: float = 20e6, interval_s: float = 3.0,
          min_rssi_dbm: Optional[float] = None, min_confidence: float = 0.3,
          use_iq: bool = False) -> dict:
    """Start the passive watch loop over [start_hz, stop_hz]. Mirrors the one-shot
    /uas/scan call but runs continuously and maintains the detection registry."""
    from app.core.sdr import uas_video, sdr_manager
    if abs(stop_hz - start_hz) > 6e9:
        raise ValueError("watch span too wide (max 6 GHz)")
    # Resolve the device the same way the /uas routes do.
    dev = {"id": "synthetic", "metadata": {}}
    if device_id:
        d = None
        try:
            d = sdr_manager.get(device_id)
        except Exception:
            d = None
        if d is not None:
            dev = d.public() if hasattr(d, "public") else (d if isinstance(d, dict) else dev)
        else:
            dev = {"id": device_id, "metadata": {}}
    stop()
    _DETECTIONS.clear()
    uas_video.reset_max_hold(_MAXHOLD_KEY)
    _STATE.update(running=True, device_id=device_id or "synthetic",
                  start_hz=float(start_hz), stop_hz=float(stop_hz), step_hz=float(step_hz),
                  interval_s=float(interval_s), min_rssi_dbm=min_rssi_dbm,
                  min_confidence=float(min_confidence), use_iq=bool(use_iq),
                  started_ts=time.time(), last_sweep_ts=None, n_sweeps=0,
                  paused_reason=None, last_error=None, source=None)
    global _TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _STATE["running"] = False
        raise RuntimeError("watch loop must be started from within the running event loop")
    _TASK = loop.create_task(
        _run(device_id, dev, float(start_hz), float(stop_hz), float(step_hz),
             float(interval_s), min_rssi_dbm, float(min_confidence), bool(use_iq)))
    log.info("uas_watch started: device=%s band=%.0f–%.0f MHz",
             _STATE["device_id"], start_hz / 1e6, stop_hz / 1e6)
    return status()


def stop() -> dict:
    global _TASK
    if _TASK and not _TASK.done():
        _TASK.cancel()
    _TASK = None
    _STATE["running"] = False
    return status()


def clear() -> dict:
    _DETECTIONS.clear()
    return status()


def cot_payload(key: str) -> Optional[dict]:
    """Build the CoT placement for a detection: operator GPS position + the Friis
    range as the error radius (ce). Returns None when there's no detection or no
    operator GPS fix (a single antenna has nowhere else honest to place it)."""
    rec = _DETECTIONS.get(key)
    if rec is None:
        return None
    from app.core.sdr import sdr_manager
    fix = sdr_manager.gps_fix()
    if not fix or fix.get("lat") is None:
        return {"ok": False, "reason": "no operator GPS fix — can't place a bearing-less detection"}
    ce = rec.get("range_est_m") or 1500.0
    remarks = (f"{rec['platform_family']} · {rec.get('feed_name')} · "
               f"{rec['center_hz'] / 1e6:.3f} MHz · "
               f"{('RSSI ' + str(rec['rssi_dbm']) + ' dBm') if rec.get('rssi_dbm') is not None else 'RSSI n/a'} · "
               f"range≈{ce / 1000:.1f} km (no bearing)")
    return {"ok": True, "lat": float(fix["lat"]), "lon": float(fix["lon"]),
            "ce_m": float(ce), "remarks": remarks,
            "callsign": f"DRONE {rec['platform_family']}"}
