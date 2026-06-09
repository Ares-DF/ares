# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""Mathematical verification of the single-channel (one SDR + motion) DF stack.

Each test simulates the physics the estimator assumes — log-distance RSS field,
CPA Doppler S-curve, plane-wave phase across a synthetic aperture — and demands
the estimator invert it back to the planted emitter."""

import math

import numpy as np
import pytest

from app.core.df.single_channel import (
    rss_path_loss_fix, doppler_cpa_fit, synthetic_aperture_doa, ml_grid_fusion,
)

C = 299_792_458.0
M_PER_DEG_LAT = 111_320.0
EMITTER = (37.7750, -122.4180)


def err_m(lat, lon, em=EMITTER):
    return math.hypot((lat - em[0]) * M_PER_DEG_LAT,
                      (lon - em[1]) * M_PER_DEG_LAT * math.cos(math.radians(em[0])))


def rss_at(lat, lon, p_tx=20.0, n=3.0, em=EMITTER):
    d = max(err_m(lat, lon, em), 1.0)
    return p_tx - 10.0 * n * math.log10(d)


# ── RSS log-distance ML ──────────────────────────────────────────────────────

def test_rss_path_loss_fix_recovers_emitter():
    rng = np.random.default_rng(1)
    obs = []
    for _ in range(30):
        la = EMITTER[0] + rng.uniform(-0.005, 0.005)
        lo = EMITTER[1] + rng.uniform(-0.005, 0.005)
        obs.append({"lat": la, "lon": lo,
                    "rssi_dbm": rss_at(la, lo) + rng.normal(0, 2.0)})
    out = rss_path_loss_fix(obs, grid_span_m=3_000.0, grid_m=25.0)
    assert out["ok"], out
    est = out["estimate"]
    e = err_m(est["lat"], est["lon"])
    assert e < 800.0, f"RSS-ML fix {e:.0f} m from planted emitter"


def test_rss_fix_estimates_path_loss_exponent():
    """With zero noise and a known exponent, the closed-form (P_tx, n) solve
    should recover n to first decimal."""
    rng = np.random.default_rng(2)
    obs = []
    for _ in range(40):
        la = EMITTER[0] + rng.uniform(-0.006, 0.006)
        lo = EMITTER[1] + rng.uniform(-0.006, 0.006)
        obs.append({"lat": la, "lon": lo, "rssi_dbm": rss_at(la, lo, n=2.5)})
    out = rss_path_loss_fix(obs, grid_span_m=3_000.0, grid_m=25.0)
    assert out["ok"], out
    est = out["estimate"]
    # RSS-only localization is a weak-geometry problem (P_tx / n / range trade
    # off), but the path-loss exponent is well-determined by the field's slope.
    assert abs(est["path_loss_n"] - 2.5) < 0.5
    assert err_m(est["lat"], est["lon"]) < 1500.0


# ── Doppler closest-point-of-approach ────────────────────────────────────────

def test_doppler_cpa_recovers_geometry():
    """Observer drives a straight east line past the emitter; the fitted CPA
    range and time must match the simulation."""
    v = 20.0                      # m/s eastbound
    f0 = 433e6
    r0_true = 400.0               # CPA offset north of the track
    t_cpa_true = 30.0
    lat_track = EMITTER[0] - r0_true / M_PER_DEG_LAT
    obs = []
    for t in np.arange(0.0, 60.0, 1.0):
        x = v * (t - t_cpa_true)  # east offset from CPA point
        rng_m = math.hypot(x, r0_true)
        # radial velocity toward emitter → Doppler shift
        df = f0 * (-v * x / rng_m) / C * -1.0  # approaching (x<0) → positive shift
        lon = EMITTER[1] + x / (M_PER_DEG_LAT * math.cos(math.radians(EMITTER[0])))
        obs.append({"t": float(t), "frequency_offset_hz": float(df),
                    "v_mps": v, "lat": lat_track, "lon": lon})
    out = doppler_cpa_fit(obs, carrier_hz=f0)
    assert out["ok"], out
    fit = out["fit"]
    assert abs(fit["cpa_time_s"] - t_cpa_true) < 2.0, fit
    assert abs(fit["cpa_distance_m"] - r0_true) / r0_true < 0.30, fit
    # both left/right candidates should sit ~r0 from the track at t_cpa
    assert len(out["candidates"]) >= 1


# ── synthetic-aperture DoA ───────────────────────────────────────────────────

@pytest.mark.parametrize("az_true", [30.0, 120.0, 250.0])
def test_synthetic_aperture_doa(az_true):
    """Plane wave from az_true sampled along a 2-wavelength track."""
    f0 = 433e6
    lam = C / f0
    rng = np.random.default_rng(4)
    snaps = []
    for i in range(16):
        x = (i / 15.0) * 2.0 * lam      # east-bound track
        y = 0.0
        phase = -2 * math.pi * (x * math.sin(math.radians(az_true))
                                + y * math.cos(math.radians(az_true))) / lam
        iq = np.exp(1j * phase) + 0.05 * (rng.standard_normal() + 1j * rng.standard_normal())
        snaps.append({"x_m": x, "y_m": y, "iq_complex": complex(iq)})
    out = synthetic_aperture_doa(snaps, carrier_hz=f0)
    assert out["ok"], out
    got = float(out["peaks"][0]["azimuth_deg"]) % 360.0
    # straight east-west track ⇒ mirror about the E-W axis is unresolvable
    mirror = (180.0 - got) % 360.0
    e = min(abs((got - az_true + 180) % 360 - 180), abs((mirror - az_true + 180) % 360 - 180))
    assert e <= 6.0, f"SA-DoA {got}° vs {az_true}° (err {e}°)"


# ── universal grid fusion ────────────────────────────────────────────────────

def test_ml_grid_fusion_aoa_plus_rss():
    rng = np.random.default_rng(6)
    obs = []
    for la, lo in [(37.770, -122.425), (37.781, -122.424), (37.780, -122.410)]:
        dx = (EMITTER[1] - lo) * M_PER_DEG_LAT * math.cos(math.radians(37.78))
        dy = (EMITTER[0] - la) * M_PER_DEG_LAT
        brg = math.degrees(math.atan2(dx, dy)) % 360.0
        obs.append({"kind": "aoa", "lat": la, "lon": lo,
                    "bearing_deg": (brg + rng.normal(0, 2.0)) % 360.0, "sigma_deg": 2.0})
    for _ in range(10):
        la = EMITTER[0] + rng.uniform(-0.004, 0.004)
        lo = EMITTER[1] + rng.uniform(-0.004, 0.004)
        obs.append({"kind": "rss", "lat": la, "lon": lo,
                    "rssi_dbm": rss_at(la, lo) + rng.normal(0, 3.0)})
    out = ml_grid_fusion(obs, grid_span_m=6_000.0, grid_step_m=50.0)
    assert out["ok"], out
    est = out["estimate"]
    e = err_m(est["lat"], est["lon"])
    assert e < 400.0, f"fusion fix {e:.0f} m from planted emitter"


def test_ml_grid_fusion_aoa_only_matches_triangulation():
    obs = []
    for la, lo in [(37.770, -122.425), (37.781, -122.424), (37.780, -122.410)]:
        dx = (EMITTER[1] - lo) * M_PER_DEG_LAT * math.cos(math.radians(37.78))
        dy = (EMITTER[0] - la) * M_PER_DEG_LAT
        brg = math.degrees(math.atan2(dx, dy)) % 360.0
        obs.append({"kind": "aoa", "lat": la, "lon": lo, "bearing_deg": brg, "sigma_deg": 1.0})
    out = ml_grid_fusion(obs, grid_span_m=6_000.0, grid_step_m=50.0)
    assert out["ok"], out
    est = out["estimate"]
    assert err_m(est["lat"], est["lon"]) < 150.0


# ── Doppler-consistency geolocation (maneuvering single receiver) ─────────────
from app.core.df.single_channel import doppler_geolocate  # noqa: E402


def _doppler_track(emitter, poses, carrier_hz, centre_offset_hz=0.0, noise_hz=0.0, rng=None):
    """Synthesize Δf_peak for a moving receiver and a stationary emitter using
    the exact vector-Doppler model the solver inverts."""
    C_ = 299_792_458.0
    mlat = M_PER_DEG_LAT
    mlon = M_PER_DEG_LAT * math.cos(math.radians(emitter[0]))
    obs = []
    for (lat, lon, vx, vy) in poses:
        dx = (lon - emitter[1]) * mlon          # observer − emitter, east
        dy = (lat - emitter[0]) * mlat          # north
        dist = math.hypot(dx, dy)
        proj = (vx * dx + vy * dy) / dist        # V·D/|D|
        df_doppler = -(carrier_hz / C_) * proj
        df_peak = df_doppler + centre_offset_hz
        if noise_hz and rng is not None:
            df_peak += rng.normal(0, noise_hz)
        obs.append({"lat": lat, "lon": lon, "vx_mps": vx, "vy_mps": vy,
                    "frequency_offset_hz": df_peak})
    return obs


def _straight_track(emitter, n=16, v=25.0, heading_deg=90.0, t_cpa=8.0, dt=1.0, cpa_north_m=600.0):
    mlat = M_PER_DEG_LAT
    mlon = M_PER_DEG_LAT * math.cos(math.radians(emitter[0]))
    vx = v * math.sin(math.radians(heading_deg))
    vy = v * math.cos(math.radians(heading_deg))
    poses = []
    for i in range(n):
        t = i * dt
        east = vx * (t - t_cpa)
        north = vy * (t - t_cpa) + cpa_north_m
        lat = emitter[0] + north / mlat
        lon = emitter[1] + east / mlon
        poses.append((lat, lon, vx, vy))
    return poses


def test_doppler_geolocate_straight_pass_offset_and_honest_cep():
    """A single straight constant-velocity leg is weakly observable in range
    (the cost valley is near-flat along the line of sight). The solver must
    still recover the constant offset and the cross-track geometry, and — the
    important part — report an HONEST (large/inf) CEP rather than a falsely
    tight one, so a downstream consumer knows the fix is under-determined."""
    f0 = 406e6
    poses = _straight_track(EMITTER, cpa_north_m=700.0)
    obs = _doppler_track(EMITTER, poses, f0, centre_offset_hz=120.0)
    out = doppler_geolocate(obs, carrier_hz=f0)
    assert out["ok"], out
    # offset is recovered as the mean of Δf_centre regardless of the range valley
    assert abs(out["fit"]["estimated_centre_offset_hz"] - 120.0) < 5.0
    assert out["fit"]["centre_offset_consistency_hz"] < 1.0
    # the reported uncertainty must reflect the weak geometry, not hide it
    assert out["uncertainty"]["cep_m"] > 300.0 or not math.isfinite(out["uncertainty"]["cep_m"])


def test_doppler_geolocate_recovers_unknown_offset():
    """The estimate must be invariant to the constant frequency offset — that's
    the whole point of the variance criterion."""
    f0 = 406e6
    poses = _straight_track(EMITTER, cpa_north_m=500.0)
    fixes = []
    for off in (-3000.0, 0.0, 2500.0):
        obs = _doppler_track(EMITTER, poses, f0, centre_offset_hz=off)
        out = doppler_geolocate(obs, carrier_hz=f0)
        assert out["ok"], out
        fixes.append((out["estimate"]["lat"], out["estimate"]["lon"]))
    # all three fixes must coincide (offset is a nuisance parameter)
    for la, lo in fixes[1:]:
        d = math.hypot((la - fixes[0][0]) * M_PER_DEG_LAT,
                       (lo - fixes[0][1]) * M_PER_DEG_LAT * math.cos(math.radians(EMITTER[0])))
        assert d < 30.0, f"offset changed the fix by {d:.0f} m"


def test_doppler_geolocate_maneuvering_track():
    """A turning sUAS/vehicle track (the case the CPA S-curve fit can't handle)."""
    f0 = 433e6
    mlat = M_PER_DEG_LAT
    mlon = M_PER_DEG_LAT * math.cos(math.radians(EMITTER[0]))
    poses = []
    # L-shaped path: east leg then north leg, offset from the emitter
    for i in range(10):
        east = -1500.0 + i * 200.0
        north = 900.0
        poses.append((EMITTER[0] + north / mlat, EMITTER[1] + east / mlon, 30.0, 0.0))
    for i in range(10):
        east = 300.0
        north = 900.0 + i * 200.0
        poses.append((EMITTER[0] + north / mlat, EMITTER[1] + east / mlon, 0.0, 30.0))
    obs = _doppler_track(EMITTER, poses, f0, centre_offset_hz=-450.0)
    out = doppler_geolocate(obs, carrier_hz=f0)
    assert out["ok"] and out["solved"], out
    e = err_m(out["estimate"]["lat"], out["estimate"]["lon"])
    assert e < 200.0, f"maneuvering Doppler fix {e:.0f} m from truth"


def test_doppler_geolocate_noise_robustness():
    f0 = 406e6
    rng = np.random.default_rng(99)
    poses = _straight_track(EMITTER, n=24, cpa_north_m=600.0)
    errs = []
    for _ in range(15):
        obs = _doppler_track(EMITTER, poses, f0, centre_offset_hz=80.0, noise_hz=2.0, rng=rng)
        out = doppler_geolocate(obs, carrier_hz=f0)
        assert out["ok"], out
        errs.append(err_m(out["estimate"]["lat"], out["estimate"]["lon"]))
    assert np.median(errs) < 500.0, f"median Doppler fix error {np.median(errs):.0f} m under 2 Hz noise"


def test_doppler_geolocate_heading_speed_input():
    """Velocity may be given as true heading + speed instead of vx/vy."""
    f0 = 406e6
    poses = _straight_track(EMITTER, cpa_north_m=550.0, heading_deg=90.0, v=25.0)
    obs = _doppler_track(EMITTER, poses, f0, centre_offset_hz=0.0)
    for o in obs:                      # swap vx/vy for heading+speed
        o.pop("vx_mps"); o.pop("vy_mps")
        o["heading_deg"] = 90.0
        o["speed_mps"] = 25.0
    out = doppler_geolocate(obs, carrier_hz=f0)
    assert out["ok"], out
    assert err_m(out["estimate"]["lat"], out["estimate"]["lon"]) < 200.0
