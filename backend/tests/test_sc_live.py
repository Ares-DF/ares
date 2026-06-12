# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
Validation harness for the GPS/INS-gated live single-channel DF collector.

Run from `backend/`:   python -m tests.test_sc_live

Tests:
  1. Gate: start() refuses with no pose, a manually-typed pose, and a stale
     pose — single-channel DF must have a live GPS/INS feed.
  2. Collection: with a fresh GPS pose and hardware spectrum frames, the
     collector records observations carrying pose provenance and a velocity
     (from the fix's course/speed, or derived from successive fixes).
  3. Synthetic spectrum never produces observations (same rule as live-DF
     LoB suppression); a pose going stale mid-run pauses collection.
  4. solve(): a Doppler-consistent recorded track auto-picks
     doppler_geolocate and recovers the emitter.
"""
from __future__ import annotations

import asyncio
import math
import sys
import time

# Allow running as `python -m tests.test_sc_live` from backend/
sys.path.insert(0, ".")

from app.core.df import sc_live
from app.core.df.single_channel import _enu_scale
from app.core.sdr import sdr_manager

PASS = FAIL = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    print(f"  {'✓' if ok else '✗ FAIL'} {name}" + (f" — {detail}" if detail else ""))
    PASS += ok
    FAIL += not ok


class _FakeDev:
    id = "sc-test"


def _hw_frame(peak_hz: float, t: float, peak_dbm: float = -47.0, source: str = "hardware") -> dict:
    return {"source": source, "peak_hz": peak_hz, "peak_dbm": peak_dbm, "t": t}


def _reset():
    sc_live.stop()
    sc_live.clear()
    sdr_manager._gps = None


# ─────────────────────────────────────────────────────────────────────────────
def test_gate():
    print("1) GPS/INS gate on start()")
    _reset()
    sdr_manager.get = lambda did: _FakeDev() if did == "sc-test" else None

    def expect_refusal(name):
        try:
            sc_live.start("sc-test", 433.0e6)
            check(name, False, "start() did not refuse")
        except ValueError as e:
            check(name, True, str(e)[:80])

    expect_refusal("no pose → refused")

    sdr_manager.set_gps_fix(37.77, -122.42, source="manual")
    expect_refusal("manual pose → refused")
    fix, reason = sc_live.pose_check()
    check("pose_check names the manual pose", reason is not None and "manual" in reason)

    sdr_manager.set_gps_fix(37.77, -122.42, source="gpsd (3D)")
    sdr_manager._gps["t"] = time.time() - 60.0
    expect_refusal("stale pose → refused")

    st = sc_live.status()
    check("status() carries the dependency + pose gate",
          st["pose"]["ok"] is False and "GPS or INS" in st["dependency"])

    try:
        sdr_manager._gps["t"] = time.time()
        sc_live.start("nope", 433.0e6)
        check("unknown device → refused", False)
    except ValueError:
        check("unknown device → refused", True)


def test_collection():
    print("2) collection with a live GPS pose")
    _reset()
    sdr_manager.get = lambda did: _FakeDev()
    frames = {"t0": time.time(), "n": 0, "source": "hardware"}

    def fake_spectrum(device_id, c, span, n_bins, ch):
        frames["n"] += 1
        return _hw_frame(433.0e6 + 120.0, frames["t0"] + frames["n"], source=frames["source"])

    sdr_manager.device_spectrum = fake_spectrum

    async def run():
        # fresh fix with course/speed (the GPS reports velocity)
        sdr_manager.set_gps_fix(37.7700, -122.4200, heading_deg=90.0, speed_mps=12.0, source="gpsd (3D)")
        sc_live.start("sc-test", 433.0e6, interval_s=0.02)
        await asyncio.sleep(0.1)
        obs1 = sc_live.observations()

        # fix without course/speed → velocity derived from successive fixes
        mlat, mlon = _enu_scale(37.77)
        sdr_manager.set_gps_fix(37.7700, -122.4200, source="USB GPS (NMEA)")
        await asyncio.sleep(0.05)
        sdr_manager.set_gps_fix(37.7700, -122.4200 + 30.0 / mlon, source="USB GPS (NMEA)")  # ~30 m east
        await asyncio.sleep(0.05)
        obs2 = sc_live.observations()

        # synthetic spectrum → nothing recorded
        before = len(sc_live.observations())
        frames["source"] = "synthetic"
        await asyncio.sleep(0.1)
        skipped_synth = sc_live.status()["n_skipped_spectrum"]
        after_synth = len(sc_live.observations())
        frames["source"] = "hardware"

        # pose goes stale mid-run → paused, nothing recorded
        sdr_manager._gps["t"] = time.time() - 60.0
        await asyncio.sleep(0.1)
        st_stale = sc_live.status()
        after_stale = len(sc_live.observations())
        sc_live.stop()
        return obs1, obs2, before, skipped_synth, after_synth, st_stale, after_stale

    obs1, obs2, before, skipped_synth, after_synth, st_stale, after_stale = asyncio.run(run())

    check("observations recorded", len(obs1) >= 2, f"{len(obs1)} in 0.1 s")
    o = obs1[-1]
    check("offset = peak − carrier", abs(o["frequency_offset_hz"] - 120.0) < 1e-6)
    check("pose provenance recorded", o["pose_source"] == "gpsd (3D)")
    check("GPS course/speed carried", o.get("heading_deg") == 90.0 and o.get("speed_mps") == 12.0)
    derived = [o for o in obs2 if "vx_mps" in o]
    check("velocity derived from successive fixes", any(abs(o["vx_mps"]) > 1.0 for o in derived),
          f"{len(derived)} derived-velocity obs")
    check("synthetic spectrum recorded nothing", after_synth == before and skipped_synth > 0,
          f"skipped {skipped_synth}")
    check("stale pose pauses collection",
          after_stale == after_synth and st_stale["paused_reason"] is not None
          and st_stale["n_skipped_pose"] > 0, str(st_stale["paused_reason"])[:60])


def test_solve():
    print("3) solve() on a recorded Doppler track")
    _reset()
    f0, c = 433.0e6, 299_792_458.0
    em_lat, em_lon = 37.77, -122.42
    mlat, mlon = _enu_scale(em_lat)
    sc_live._STATE["carrier_hz"] = f0
    # L-shaped track with a constant unknown LO offset baked in
    poses = [(-1500 + i * 200, 900, 30.0, 0.0) for i in range(10)] + \
            [(300, 900 + i * 200, 0.0, 30.0) for i in range(10)]
    for east, north, vx, vy in poses:
        d = math.hypot(east, north)                       # D = observer − emitter
        dop = -(f0 / c) * (vx * east + vy * north) / d + 180.0
        sc_live._OBS.append({"lat": em_lat + north / mlat, "lon": em_lon + east / mlon,
                             "vx_mps": vx, "vy_mps": vy, "frequency_offset_hz": dop,
                             "rssi_dbm": -50.0, "pose_source": "gpsd (3D)"})
    r = sc_live.solve()
    check("auto-picked doppler_geolocate", r.get("method") == "doppler_geolocate")
    if r.get("ok"):
        err_m = math.hypot((r["estimate"]["lat"] - em_lat) * mlat,
                           (r["estimate"]["lon"] - em_lon) * mlon)
        check("emitter recovered (<200 m)", err_m < 200.0, f"err {err_m:.0f} m")
        check("track provenance in result", r["track"]["pose_sources"] == ["gpsd (3D)"])
    else:
        check("solve ok", False, r.get("error", ""))

    sc_live.clear()
    r2 = sc_live.solve()
    check("empty track refuses to solve", r2.get("ok") is False)


if __name__ == "__main__":
    print("── sc_live (GPS/INS-gated single-channel DF) ──")
    test_gate()
    test_collection()
    test_solve()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
