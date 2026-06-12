# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
Validation harness for the passive drone-detection watch mode (uas_watch).

Run from `backend/`:   python -m tests.test_uas_watch

Tests:
  1. Every FEED_TYPES entry declares a non-empty platform family, and
     PLATFORM_FAMILY is the derived map (drift guard).
  2. classify_band detections carry platform_family.
  3. _ingest registry: threshold gating (confidence + RSSI, null-RSSI-safe),
     overlap merge, RSSI trend, missed-sweep clearing, proximity range.
  4. Async loop over the synthetic device populates detections (executor path).
  5. cot_payload: needs an operator GPS fix; places at the operator with the
     Friis range as ce.
  6. TestClient round-trip of /uas/watch/{start,stop,clear,status} + the CoT route.
"""
from __future__ import annotations

import asyncio
import sys
import time
from collections import deque

sys.path.insert(0, ".")

from app.core.sdr import uas_video
from app.core.sdr import uas_watch

PASS = FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  {'✓' if ok else '✗ FAIL'} {name}" + (f" — {detail}" if detail else ""))
    PASS += ok
    FAIL += not ok


def _det(center_hz, bw, rssi, conf, feed="hdzero", fam="Digital FPV"):
    return {"center_hz": center_hz, "bandwidth_hz": bw, "rssi_dbm": rssi, "confidence": conf,
            "feed_type": feed, "feed_name": feed, "platform_family": fam}


def test_family_coverage():
    print("1) platform-family coverage on FEED_TYPES")
    missing = [f["id"] for f in uas_video.FEED_TYPES if not f.get("family")]
    check("every feed type has a non-empty family", not missing, str(missing))
    derived = {f["id"]: f["family"] for f in uas_video.FEED_TYPES}
    check("PLATFORM_FAMILY is the derived map", uas_video.PLATFORM_FAMILY == derived)
    check("families are a small named set", "DJI drone" in set(derived.values())
          and "Analog FPV/video" in set(derived.values()))


def test_classify_carries_family():
    print("2) classify_band detections carry platform_family")
    res = uas_video.classify_band({"id": "synthetic", "metadata": {}}, 5645e6, 5945e6,
                                  step_hz=20e6, use_iq=False)
    dets = res.get("detections", [])
    check("synthetic scan produced detections", len(dets) > 0, f"{len(dets)} dets")
    if dets:
        check("each detection has platform_family", all("platform_family" in d for d in dets))


def test_registry():
    print("3) detection registry: gating, merge, trend, clearing")
    uas_watch.clear()
    D = uas_watch._DETECTIONS

    # confidence gate
    uas_watch._ingest({"detections": [_det(5.8e9, 27e6, -50, 0.1)]}, None, 0.3)
    check("low-confidence detection gated out", len(D) == 0)

    # null-RSSI must NOT be gated out by a min-RSSI threshold
    uas_watch._ingest({"detections": [_det(5.8e9, 27e6, None, 0.6)]}, -60.0, 0.3)
    check("null-RSSI detection kept despite min-RSSI", len(D) == 1)
    uas_watch.clear(); D = uas_watch._DETECTIONS

    # weak RSSI gated out when a threshold is set
    uas_watch._ingest({"detections": [_det(5.8e9, 27e6, -90, 0.6)]}, -60.0, 0.3)
    check("weak RSSI gated out by min-RSSI", len(D) == 0)

    # ingest a rising-strength emitter over several sweeps → one merged record, trend rising
    for r in (-70, -64, -58, -50):
        uas_watch._ingest({"detections": [_det(5.80e9 + 1e6, 27e6, r, 0.7)]}, None, 0.3)
    check("overlapping hits merge to one record", len(D) == 1, f"{len(D)} records")
    rec = next(iter(D.values()))
    check("RSSI trend = rising", rec["rssi_trend"] == "rising", rec["rssi_trend"])
    check("proximity range computed", rec["range_est_m"] and rec["range_est_m"] > 0)
    check("platform family carried", rec["platform_family"] == "Digital FPV")

    # missed-sweep clearing: empty sweeps don't drop it immediately, but do after the threshold
    for _ in range(uas_watch._CLEAR_AFTER_MISSES):
        uas_watch._ingest({"detections": []}, None, 0.3)
    check("survives a few missed sweeps (hopping)", len(D) == 1)
    uas_watch._ingest({"detections": []}, None, 0.3)
    check("cleared after > N misses", len(D) == 0)


def test_async_loop():
    print("4) async watch loop over the synthetic device")
    async def run():
        uas_watch.start(None, 5645e6, 5945e6, step_hz=20e6, interval_s=0.05, use_iq=False)
        await asyncio.sleep(0.35)
        st = uas_watch.status()
        uas_watch.stop()
        return st
    st = asyncio.run(run())
    check("loop ran sweeps", st["n_sweeps"] >= 1, f"{st['n_sweeps']} sweeps")
    check("detections populated", st["n_detections"] >= 1, f"{st['n_detections']} dets")
    check("status() hides the internal rssi ring", all("_rssi_hist" not in d for d in st["detections"]))


def test_cot_payload():
    print("5) cot_payload placement at operator GPS")
    from app.core.sdr import sdr_manager
    uas_watch.clear()
    uas_watch._ingest({"detections": [_det(5.8e9, 27e6, -55, 0.7)]}, None, 0.3)
    key = next(iter(uas_watch._DETECTIONS))
    sdr_manager._gps = None
    p = uas_watch.cot_payload(key)
    check("no GPS → not placeable", p and p.get("ok") is False)
    sdr_manager.set_gps_fix(50.45, 30.52, source="browser")
    p = uas_watch.cot_payload(key)
    check("with GPS → placed at operator", p and p.get("ok") and abs(p["lat"] - 50.45) < 1e-6)
    check("ce = Friis range", p["ce_m"] > 0)
    check("unknown key → None", uas_watch.cot_payload("nope") is None)
    sdr_manager._gps = None


def test_routes():
    print("6) TestClient round-trip of /uas/watch/*")
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.auth import require_auth
    app.dependency_overrides[require_auth] = lambda: {"sub": "test"}
    c = TestClient(app)
    uas_watch.stop(); uas_watch.clear()
    r = c.get("/api/v1/uas/watch")
    check("GET /uas/watch ok", r.status_code == 200 and r.json()["running"] is False)
    r = c.post("/api/v1/uas/watch/start", json={"start_hz": 5645e6, "stop_hz": 5945e6,
                                                "step_hz": 20e6, "interval_s": 0.5, "use_iq": False})
    check("start ok", r.status_code == 200 and r.json()["running"] is True, r.text[:120])
    time.sleep(0.7)
    st = c.get("/api/v1/uas/watch").json()
    check("detections via route", st["n_detections"] >= 0)
    key = st["detections"][0]["key"] if st["detections"] else None
    if key:
        rc = c.post(f"/api/v1/uas/watch/{key}/cot")
        check("CoT route returns without raising", rc.status_code == 200, rc.text[:120])
        check("CoT honest about no targets / no gps",
              rc.json().get("sent") is False)
    r = c.post("/api/v1/uas/watch/stop")
    check("stop ok", r.status_code == 200 and r.json()["running"] is False)
    r = c.post("/api/v1/uas/watch/clear")
    check("clear ok", r.status_code == 200 and r.json()["n_detections"] == 0)
    app.dependency_overrides.pop(require_auth, None)


if __name__ == "__main__":
    print("── uas_watch (passive drone-detection watch mode) ──")
    test_family_coverage()
    test_classify_carries_family()
    test_registry()
    test_async_loop()
    test_cot_payload()
    test_routes()
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)
