# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
df/sc_live.py — live single-channel DF track recorder (GPS/INS-gated).

Every single-channel DF method (multi-pose RSS, Doppler-CPA, FDOA,
Doppler-consistency, synthetic aperture, …) locates an emitter from the
*receiver's own motion*: a measurement is only meaningful when paired with an
accurate receiver pose (position + velocity) at the measurement instant. That
makes a live GPS or INS feed a HARD dependency of single-channel DF:

  * ``start()`` refuses unless the operator pose comes from a live GPS/INS
    source (browser geolocation, gpsd, serial NMEA — INS units that speak
    NMEA/gpsd included — or an SDR's GPSDO) AND the latest fix is fresh.
    A manually-typed position is a fixed point, not a track — rejected.
  * While running, a pose older than ``POSE_MAX_AGE_S`` pauses collection
    (``paused_reason`` says why) — observations are never fabricated from a
    stale or manual position.
  * The spectrum must come from real hardware. A synthetic capture (no radio /
    driver fallback) never produces observations — the same rule that stops
    live-DF emitting LoBs from generated IQ.

Each tick pairs the current GPS/INS fix with the strongest peak near the
carrier in the device's live spectrum, recording::

    {t, lat, lon, frequency_offset_hz, rssi_dbm,
     heading_deg?, speed_mps? | vx_mps?, vy_mps?, pose_source}

Velocity comes from the fix's course/speed when the receiver reports it,
else it is derived from successive fixes. ``solve()`` then runs the standard
single-channel solvers (``doppler_geolocate`` / ``rss_path_loss_fix``) on the
recorded track. One session at a time (module-level singleton, like
``sdr/gps_source``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

log = logging.getLogger(__name__)

POSE_MAX_AGE_S = 10.0          # a fix older than this pauses collection
_MAX_OBS = 5000                # ring-buffer cap on the recorded track

_STATE: dict = {"running": False, "device_id": None, "carrier_hz": None,
                "span_hz": None, "interval_s": None, "started_ts": None,
                "paused_reason": None, "last_error": None,
                "n_collected": 0, "n_skipped_pose": 0, "n_skipped_spectrum": 0}
_OBS: list[dict] = []
_TASK: Optional[asyncio.Task] = None


# ─────────────────────────────────────────────────────────────────────────────
# The GPS/INS gate
# ─────────────────────────────────────────────────────────────────────────────
def pose_check() -> tuple[Optional[dict], Optional[str]]:
    """Return ``(fix, None)`` when a fresh GPS/INS pose is available, else
    ``(last_fix_or_None, reason)``. The fix's own ``source`` tag is the
    provenance: anything pushed by a live source (browser / gpsd / NMEA /
    SDR GPSDO) qualifies; a manually-typed position does not."""
    from app.core.sdr import sdr_manager
    fix = sdr_manager.gps_fix()
    if not fix:
        return None, ("no operator pose — start a GPS/INS source in the SDR console "
                      "(gpsd / serial NMEA / SDR GPSDO / browser geolocation)")
    if str(fix.get("source") or "").lower().startswith("manual"):
        return fix, ("operator pose is manually typed — single-channel DF needs a live "
                     "GPS/INS feed (a fixed point is not a track)")
    age = time.time() - float(fix.get("t") or 0.0)
    if age > POSE_MAX_AGE_S:
        return fix, f"GPS/INS fix is stale ({age:.0f} s > {POSE_MAX_AGE_S:.0f} s) — waiting for a fresh pose"
    return fix, None


def status() -> dict:
    fix, reason = pose_check()
    return {**_STATE,
            "n_observations": len(_OBS),
            "pose": {"ok": reason is None, "reason": reason, "fix": fix},
            "dependency": ("single-channel DF requires a live GPS or INS pose source — "
                           "the receiver track is what creates the virtual aperture")}


# ─────────────────────────────────────────────────────────────────────────────
# Observation assembly
# ─────────────────────────────────────────────────────────────────────────────
def _make_obs(fix: dict, frame: dict, carrier_hz: float, prev_fix: Optional[dict]) -> dict:
    ob = {"t": float(frame.get("t") or time.time()),
          "lat": float(fix["lat"]), "lon": float(fix["lon"]),
          "frequency_offset_hz": float(frame["peak_hz"]) - float(carrier_hz),
          "rssi_dbm": (None if frame.get("peak_dbm") is None else float(frame["peak_dbm"])),
          "pose_source": fix.get("source")}
    hdg, spd = fix.get("heading_deg"), fix.get("speed_mps")
    if hdg is not None and spd is not None:
        ob["heading_deg"] = float(hdg)
        ob["speed_mps"] = float(spd)
    elif prev_fix is not None:
        # derive ENU velocity from successive fixes (course/speed not reported)
        dt = float(fix.get("t") or 0.0) - float(prev_fix.get("t") or 0.0)
        if 0.0 < dt <= 3.0 * POSE_MAX_AGE_S:
            from app.core.df.single_channel import _enu_scale
            mlat, mlon = _enu_scale(float(fix["lat"]))
            ob["vx_mps"] = (float(fix["lon"]) - float(prev_fix["lon"])) * mlon / dt
            ob["vy_mps"] = (float(fix["lat"]) - float(prev_fix["lat"])) * mlat / dt
    return ob


async def _run(device_id: str, carrier_hz: float, span_hz: float, interval_s: float) -> None:
    from app.core.sdr import sdr_manager
    prev_fix: Optional[dict] = None
    last_frame_t: Optional[float] = None
    while True:
        try:
            fix, reason = pose_check()
            if reason is not None:
                _STATE["paused_reason"] = reason
                _STATE["n_skipped_pose"] += 1
            else:
                _STATE["paused_reason"] = None
                frame = sdr_manager.device_spectrum(device_id, carrier_hz, span_hz, 1024, 0)
                if frame is None:
                    frame = await asyncio.get_event_loop().run_in_executor(
                        None, sdr_manager.ondemand_spectrum, device_id, carrier_hz, span_hz, 1024, 0)
                if frame is None or frame.get("source") != "hardware":
                    _STATE["n_skipped_spectrum"] += 1
                    _STATE["last_error"] = ("no hardware spectrum from the device — synthetic/"
                                            "fallback IQ never produces single-channel observations")
                elif last_frame_t is not None and float(frame.get("t") or 0.0) <= last_frame_t:
                    # same capture as last tick (device idle / not re-capturing) — don't
                    # duplicate a measurement that carries no new information
                    _STATE["n_skipped_spectrum"] += 1
                    _STATE["paused_reason"] = "spectrum is not updating — device idle or capture stalled"
                else:
                    _OBS.append(_make_obs(fix, frame, carrier_hz, prev_fix))
                    del _OBS[:-_MAX_OBS]
                    _STATE["n_collected"] += 1
                    _STATE["last_error"] = None
                    last_frame_t = float(frame.get("t") or 0.0)
                    prev_fix = fix
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _STATE["last_error"] = f"collector error: {e}"
        await asyncio.sleep(interval_s)


# ─────────────────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────────────────
def start(device_id: str, carrier_hz: float, *, span_hz: float = 20_000.0,
          interval_s: float = 1.0) -> dict:
    """Start recording a single-channel DF track. Raises ``ValueError`` when the
    device is unknown or the GPS/INS dependency is not met *right now* (the gate
    re-checks every tick while running)."""
    from app.core.sdr import sdr_manager
    fix, reason = pose_check()
    if reason is not None:
        raise ValueError(f"cannot start single-channel DF: {reason}")
    if sdr_manager.get(device_id) is None:
        raise ValueError(f"no such device {device_id!r}")
    stop()
    _OBS.clear()
    _STATE.update(running=True, device_id=device_id, carrier_hz=float(carrier_hz),
                  span_hz=float(span_hz), interval_s=float(interval_s),
                  started_ts=time.time(), paused_reason=None, last_error=None,
                  n_collected=0, n_skipped_pose=0, n_skipped_spectrum=0)
    global _TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _STATE["running"] = False
        raise RuntimeError("single-channel collector must be started from within the running event loop")
    _TASK = loop.create_task(
        _run(device_id, float(carrier_hz), float(span_hz), float(interval_s)))
    log.info("single-channel DF collector started: device=%s carrier=%.0f Hz (pose: %s)",
             device_id, carrier_hz, fix.get("source"))
    return status()


def stop() -> dict:
    """Stop collecting. The recorded track is kept so it can still be solved/exported."""
    global _TASK
    if _TASK and not _TASK.done():
        _TASK.cancel()
    _TASK = None
    _STATE["running"] = False
    return status()


def clear() -> dict:
    _OBS.clear()
    _STATE.update(n_collected=0, n_skipped_pose=0, n_skipped_spectrum=0)
    return status()


def observations() -> list[dict]:
    return list(_OBS)


def solve(method: Optional[str] = None, **kwargs) -> dict:
    """Run a single-channel solver over the recorded track. ``method`` is
    ``doppler_geolocate`` / ``rss_path_loss`` or None to auto-pick (Doppler when
    ≥4 poses carry velocity, else multi-pose RSS when ≥3 carry RSSI)."""
    from app.core.df import single_channel as sc
    obs = list(_OBS)
    carrier = _STATE.get("carrier_hz")
    n_vel = sum(1 for o in obs if "vx_mps" in o or ("heading_deg" in o and "speed_mps" in o))
    n_rss = sum(1 for o in obs if o.get("rssi_dbm") is not None)
    if method is None:
        method = ("doppler_geolocate" if n_vel >= 4
                  else "rss_path_loss" if n_rss >= 3 else None)
    if method is None:
        return {"ok": False, "error": (f"track too sparse to solve — {len(obs)} observations, "
                                       f"{n_vel} with velocity, {n_rss} with RSSI "
                                       "(need ≥4 with velocity for Doppler or ≥3 with RSSI for RSS)")}
    if method == "doppler_geolocate":
        if not carrier:
            return {"ok": False, "error": "no carrier frequency recorded for this track"}
        r = sc.doppler_geolocate(obs, carrier_hz=float(carrier), **kwargs)
    elif method == "rss_path_loss":
        r = sc.rss_path_loss_fix(obs, **kwargs)
    else:
        return {"ok": False, "error": f"unknown solve method {method!r}"}
    r["track"] = {"n_observations": len(obs), "device_id": _STATE.get("device_id"),
                  "pose_sources": sorted({str(o.get("pose_source")) for o in obs})}
    return r
