# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""Mathematical verification of triangulation, multilateration, and tracking.

Geometry is the oracle: place an emitter, generate exact (or noise-perturbed)
observations from it, and require the solvers to find it — including statistical
consistency of the reported covariances (the error ellipse must actually contain
the truth at its stated confidence)."""

import math
import time

import numpy as np
import pytest

from app.core.geolocation import (
    LoB, ml_fix, solve_fix, destination_point, initial_bearing, intersect_bearings,
    error_ellipse_from_cov, cep_from_cov,
)
from app.core.multilaterate import tdoa_fdoa_fix
from app.core.df.tracker import EmitterTracker
from app.core.df.gmphd import GmPhdTracker

C = 299_792_458.0
M_PER_DEG_LAT = 111_320.0


def bearing_to(lat1, lon1, lat2, lon2):
    b = initial_bearing(lat1, lon1, lat2, lon2)
    assert b is not None
    return b


# ── geodesy primitives ───────────────────────────────────────────────────────

@pytest.mark.parametrize("brg,dist", [(0.0, 5000.0), (45.0, 12000.0), (137.0, 800.0), (271.5, 30000.0)])
def test_destination_bearing_roundtrip(brg, dist):
    lat0, lon0 = 47.6, -122.3
    lat1, lon1 = destination_point(lat0, lon0, brg, dist)
    b = bearing_to(lat0, lon0, lat1, lon1)
    assert abs((b - brg + 180) % 360 - 180) < 0.2
    # haversine distance check
    dlat = math.radians(lat1 - lat0); dlon = math.radians(lon1 - lon0)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat0)) * math.cos(math.radians(lat1)) * math.sin(dlon / 2) ** 2
    d = 2 * 6_371_000 * math.asin(math.sqrt(a))
    assert abs(d - dist) / dist < 0.01


def test_intersect_bearings_exact():
    emitter = (40.01, -105.02)
    o1, o2 = (40.0, -105.1), (40.05, -105.0)
    az1 = bearing_to(*o1, *emitter)
    az2 = bearing_to(*o2, *emitter)
    pt = intersect_bearings(o1[0], o1[1], az1, o2[0], o2[1], az2)
    assert pt is not None
    err_m = math.hypot((pt[0] - emitter[0]) * M_PER_DEG_LAT,
                       (pt[1] - emitter[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 50.0


# ── ML triangulation ─────────────────────────────────────────────────────────

def make_lobs(emitter, observers, az_noise_deg=0.0, rng=None, conf=90.0):
    lobs = []
    for i, (la, lo) in enumerate(observers):
        az = bearing_to(la, lo, *emitter)
        if az_noise_deg and rng is not None:
            az = (az + rng.normal(0.0, az_noise_deg)) % 360.0
        lobs.append(LoB(lat=la, lon=lo, azimuth_deg=az, frequency_hz=433e6,
                        rssi_dbm=-70.0, confidence_pct=conf, id=f"l{i}"))
    return lobs


EMITTER = (40.02, -105.05)
OBSERVERS = [(40.00, -105.10), (40.06, -105.10), (40.06, -105.00), (39.98, -105.01)]


def test_ml_fix_exact_bearings():
    fix = ml_fix(make_lobs(EMITTER, OBSERVERS))
    assert fix is not None
    err_m = math.hypot((fix["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                       (fix["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 30.0, f"ML fix off by {err_m:.1f} m with exact bearings"
    assert fix["residual_rms_deg"] < 0.1


def test_ml_fix_unbiased_under_noise():
    rng = np.random.default_rng(42)
    errs = []
    for _ in range(60):
        fix = ml_fix(make_lobs(EMITTER, OBSERVERS, az_noise_deg=2.0, rng=rng))
        assert fix is not None
        errs.append(((fix["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                     (fix["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0))))
    errs = np.array(errs)
    bias = np.linalg.norm(errs.mean(axis=0))
    rmse = float(np.sqrt((errs ** 2).sum(axis=1).mean()))
    # ~4-6 km baselines and 2° noise → couple hundred m RMSE; bias ≪ RMSE
    assert rmse < 1000.0
    assert bias < rmse * 0.5, f"bias {bias:.0f} m vs RMSE {rmse:.0f} m"


def test_ml_fix_covariance_consistency():
    """The reported covariance must describe the actual error distribution:
    NEES = e^T P^-1 e over Monte-Carlo runs should average ≈ 2 (the state dim),
    and the 95 % ellipse should contain the truth ≈ 95 % of the time."""
    rng = np.random.default_rng(7)
    nees, contained = [], 0
    trials = 120
    chi2_95_2dof = 5.991
    for _ in range(trials):
        # sigma fed via rx_hpbw so lob_sigma_deg matches the injected noise
        lobs = make_lobs(EMITTER, OBSERVERS, az_noise_deg=2.0, rng=rng)
        fix = ml_fix(lobs, rx_hpbw_deg=2.0)
        assert fix is not None
        P = np.array(fix["covariance_enu"], dtype=float).reshape(2, 2)
        e = np.array([(fix["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)),
                      (fix["lat"] - EMITTER[0]) * M_PER_DEG_LAT])
        nees.append(float(e @ np.linalg.solve(P, e)))
        if nees[-1] <= chi2_95_2dof:
            contained += 1
    mean_nees = float(np.mean(nees))
    coverage = contained / trials
    assert 1.0 < mean_nees < 4.0, f"mean NEES {mean_nees:.2f} (should be ≈2)"
    assert 0.85 <= coverage <= 1.0, f"95% ellipse contained truth only {coverage:.0%}"


def test_lob_sigma_scales_uncertainty():
    """Same geometry, mushier DoA peaks (lower confidence) → larger reported σ."""
    sharp = ml_fix(make_lobs(EMITTER, OBSERVERS, conf=95.0))
    mushy = ml_fix(make_lobs(EMITTER, OBSERVERS, conf=20.0))
    assert mushy["position_sigma_m"] > sharp["position_sigma_m"] * 2


def test_solve_fix_end_to_end():
    obs = [l.__dict__ | {} for l in make_lobs(EMITTER, OBSERVERS)]
    out = solve_fix(obs)
    assert out["groups"], "solve_fix returned no groups"
    g = out["groups"][0]
    assert g["kind"] == "fix"
    err_m = math.hypot((g["centroid"]["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                       (g["centroid"]["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 50.0
    # GeoJSON sanity
    types = {f["properties"].get("type") for f in out["geojson"]["features"]}
    assert "lob" in types


def test_error_ellipse_and_cep_formulas():
    # isotropic 100 m σ — CEP ≈ 1.1774·σ, 95 % ellipse semi-axes = √5.991·σ
    P = np.diag([100.0 ** 2, 100.0 ** 2])
    a, b, _ = error_ellipse_from_cov(P, conf=0.95)
    assert abs(a - math.sqrt(5.991) * 100) < 1.0 and abs(b - math.sqrt(5.991) * 100) < 1.0
    assert abs(cep_from_cov(P) - 117.74) < 2.0
    # anisotropic: major axis along the large-σ eigenvector
    P2 = np.diag([300.0 ** 2, 50.0 ** 2])
    a2, b2, rot = error_ellipse_from_cov(P2, conf=0.95)
    assert a2 > b2 and abs(a2 / b2 - 6.0) < 0.2


# ── TDOA / FDOA multilateration ──────────────────────────────────────────────

RXS = [
    {"lat": 40.00, "lon": -105.10},
    {"lat": 40.08, "lon": -105.08},
    {"lat": 40.07, "lon": -105.00},
    {"lat": 39.99, "lon": -105.00},
]


def true_tdoas(emitter, rxs, ref=0):
    lat0 = sum(r["lat"] for r in rxs) / len(rxs)
    mpd_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    def rng_m(r):
        return math.hypot((emitter[0] - r["lat"]) * M_PER_DEG_LAT,
                          (emitter[1] - r["lon"]) * mpd_lon)
    R = [rng_m(r) for r in rxs]
    return [(Ri - R[ref]) / C for Ri in R]


def test_tdoa_exact():
    td = true_tdoas(EMITTER, RXS)
    out = tdoa_fdoa_fix(RXS, td)
    err_m = math.hypot((out["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                       (out["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 60.0, f"TDOA fix off by {err_m:.1f} m with exact TDOAs"


def test_tdoa_noise_consistency():
    rng = np.random.default_rng(3)
    sigma_t = 50e-9
    nees, trials = [], 80
    for _ in range(trials):
        td = [t + rng.normal(0, sigma_t) for t in true_tdoas(EMITTER, RXS)]
        out = tdoa_fdoa_fix(RXS, td, tdoa_sigma_s=[sigma_t] * len(RXS))
        P = np.array(out["covariance_enu"], dtype=float).reshape(2, 2)
        e = np.array([(out["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)),
                      (out["lat"] - EMITTER[0]) * M_PER_DEG_LAT])
        nees.append(float(e @ np.linalg.solve(P, e)))
    mean_nees = float(np.mean(nees))
    assert 0.8 < mean_nees < 4.0, f"TDOA mean NEES {mean_nees:.2f} (≈2 expected)"


def test_tdoa_fdoa_tightens_fix():
    """Adding exact FDOA from moving receivers must not worsen the solution."""
    rxs = [dict(r, vx=30.0 * math.cos(i), vy=30.0 * math.sin(i)) for i, r in enumerate(RXS)]
    td = true_tdoas(EMITTER, rxs)
    base = tdoa_fdoa_fix(rxs, td)
    # exact FDOAs from the model used by the solver itself (stationary emitter)
    lat0 = sum(r["lat"] for r in rxs) / len(rxs)
    mpd_lon = M_PER_DEG_LAT * math.cos(math.radians(lat0))
    lam = C / 1e9
    fds = []
    for r in rxs:
        dx = (EMITTER[1] - r["lon"]) * mpd_lon
        dy = (EMITTER[0] - r["lat"]) * M_PER_DEG_LAT
        rng_ = math.hypot(dx, dy)
        fds.append(-(r["vx"] * dx / rng_ + r["vy"] * dy / rng_) / lam)
    fds = [f - fds[0] for f in fds]
    both = tdoa_fdoa_fix(rxs, td, fdoa_hz=fds, freq_hz=1e9)
    assert both["position_sigma_m"] <= base["position_sigma_m"] * 1.05
    err_m = math.hypot((both["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                       (both["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 80.0


# ── EKF bearings-only tracker ────────────────────────────────────────────────

def test_ekf_tracker_converges_to_stationary_emitter():
    trk = EmitterTracker(dt=1.0)
    rng = np.random.default_rng(11)
    t0 = time.time()
    snaps = []
    for step in range(25):
        obs = []
        for la, lo in OBSERVERS[:3]:
            az = (bearing_to(la, lo, *EMITTER) + rng.normal(0, 2.0)) % 360.0
            obs.append({"lat": la, "lon": lo, "azimuth_deg": az,
                        "frequency_hz": 433e6, "t": t0 + step, "sigma_az_deg": 2.0})
        snaps = trk.step(obs)
    assert snaps, "EKF tracker produced no tracks"
    best = min(snaps, key=lambda s: math.hypot(
        (s["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
        (s["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0))))
    err_m = math.hypot((best["lat"] - EMITTER[0]) * M_PER_DEG_LAT,
                       (best["lon"] - EMITTER[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
    assert err_m < 1500.0, f"EKF track {err_m:.0f} m from truth after 25 steps"


# ── GM-PHD multi-emitter ─────────────────────────────────────────────────────

def test_gmphd_finds_two_separated_emitters():
    em1, em2 = (40.02, -105.06), (40.06, -105.02)
    trk = GmPhdTracker()
    rng = np.random.default_rng(5)
    out = []
    for step in range(30):
        obs = []
        for la, lo in OBSERVERS[:3]:
            for em in (em1, em2):
                az = (bearing_to(la, lo, *em) + rng.normal(0, 1.5)) % 360.0
                obs.append({"lat": la, "lon": lo, "azimuth_deg": az, "sigma_az_deg": 1.5})
        out = trk.step(obs)
    assert out, "GM-PHD produced no components"
    def err_to(em):
        return min(math.hypot((c["lat"] - em[0]) * M_PER_DEG_LAT,
                              (c["lon"] - em[1]) * M_PER_DEG_LAT * math.cos(math.radians(40.0)))
                   for c in out)
    assert err_to(em1) < 2000.0, f"GM-PHD missed emitter 1 by {err_to(em1):.0f} m"
    assert err_to(em2) < 2000.0, f"GM-PHD missed emitter 2 by {err_to(em2):.0f} m"
