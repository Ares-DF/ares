# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""Mathematical verification of the array-DoA estimator stack.

Every test builds synthetic plane-wave snapshots with a *known* arrival angle
(X = a(az)·s + n) and asserts the estimator recovers it within a tolerance
justified by the SNR/CRLB — no golden files, the physics is the oracle.
"""

import math

import numpy as np
import pytest

from app.core.df.arrays import ArrayGeometry, steering_vector, steering_matrix
from app.core.df.algorithms import (
    bartlett, capon, music, mem, root_music, esprit, peak_pick, covariance_from_iq,
)
from app.core.df.classic_df import watson_watt_aoa, correlative_aoa, pseudo_doppler_aoa
from app.core.df.interferometry import (
    ArrayGeometry as Geom3D,           # the 3-D (N,3) geometry classic_df/interferometry use
    steering_matrix as steering_matrix_3d,
    _crlb_phase,
)

C = 299_792_458.0
FREQ = 433e6
LAM = C / FREQ
RNG = np.random.default_rng(0xA53)


def synth_snapshots(geom, az_deg, snr_db=20.0, n_snap=2000, freq_hz=FREQ, rng=RNG):
    """X = Σ_k a(az_k)·s_k + n, unit-power sources, complex AWGN at snr_db."""
    az = np.atleast_1d(az_deg).astype(float)
    M = geom.n
    S = (rng.standard_normal((az.size, n_snap)) + 1j * rng.standard_normal((az.size, n_snap))) / math.sqrt(2)
    A = np.stack([steering_vector(geom, freq_hz, a) for a in az], axis=1)  # (M, K)
    X = A @ S
    sigma_n = 10 ** (-snr_db / 20.0)
    X += sigma_n * (rng.standard_normal((M, n_snap)) + 1j * rng.standard_normal((M, n_snap))) / math.sqrt(2)
    return X


def ang_err(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def grid_peak(spectrum, grid):
    return float(grid[int(np.argmax(spectrum))])


UCA5 = ArrayGeometry.uca(5, radius_m=0.45 * LAM / (2 * math.sin(math.pi / 5)))  # ~λ/2 inter-element
ULA8 = ArrayGeometry.ula(8, spacing_m=LAM / 2)
GRID = np.linspace(0.0, 360.0, 1441)[:-1]  # 0.25° grid


# ── steering vector geometry ─────────────────────────────────────────────────

def test_steering_vector_ula_matches_analytic():
    """For a ULA along east (axis 90°), the phase of element m is
    k·m·d·sin(az) — the textbook expression."""
    d = LAM / 2
    geom = ArrayGeometry.ula(4, spacing_m=d, axis_deg=90.0)
    k = 2 * math.pi / LAM
    for az in (0.0, 30.0, 77.0, 120.0):
        v = steering_vector(geom, FREQ, az)
        # element positions along east, centred — reconstruct expected phases
        x = geom.positions[:, 0]
        expected = np.exp(1j * k * x * math.sin(math.radians(az)))
        np.testing.assert_allclose(v, expected, atol=1e-12)


def test_steering_matrix_consistent_with_vector():
    azs = np.array([10.0, 95.0, 311.0])
    A = steering_matrix(UCA5, FREQ, azs)
    for i, a in enumerate(azs):
        np.testing.assert_allclose(A[:, i], steering_vector(UCA5, FREQ, a), atol=1e-12)


def test_covariance_from_iq_definition():
    X = (RNG.standard_normal((4, 256)) + 1j * RNG.standard_normal((4, 256)))
    R = covariance_from_iq(X, normalize=False)
    np.testing.assert_allclose(R, X @ X.conj().T / 256, rtol=1e-10)
    # Hermitian, PSD
    np.testing.assert_allclose(R, R.conj().T, atol=1e-12)
    assert np.all(np.linalg.eigvalsh((R + R.conj().T) / 2) > -1e-9)


# ── spectral estimators on a UCA, single source ──────────────────────────────

@pytest.mark.parametrize("az_true", [0.0, 33.3, 77.0, 145.5, 210.0, 289.9, 359.0])
@pytest.mark.parametrize("est,tol", [("music", 0.5), ("capon", 0.5), ("mem", 1.0), ("bartlett", 3.0)])
def test_single_source_uca(est, tol, az_true):
    X = synth_snapshots(UCA5, az_true, snr_db=20.0)
    R = covariance_from_iq(X)
    if est == "music":
        p = music(R, UCA5, FREQ, GRID, n_sources=1)
    elif est == "capon":
        p = capon(R, UCA5, FREQ, GRID)
    elif est == "mem":
        p = mem(R, UCA5, FREQ, GRID)
    else:
        p = bartlett(R, UCA5, FREQ, GRID)
    assert ang_err(grid_peak(p, GRID), az_true) <= tol, f"{est} @ {az_true}°"


def test_music_two_sources_resolved():
    az1, az2 = 60.0, 110.0
    X = synth_snapshots(UCA5, [az1, az2], snr_db=25.0, n_snap=4000)
    R = covariance_from_iq(X)
    p = music(R, UCA5, FREQ, GRID, n_sources=2)
    peaks = peak_pick(p, GRID, 2)
    got = sorted(pk["az_deg"] for pk in peaks)
    assert ang_err(got[0], az1) <= 2.0 and ang_err(got[1], az2) <= 2.0, got


def test_music_error_scales_with_snr():
    """Bullet-proof check: estimator error must not *grow* as SNR improves."""
    az = 123.4
    errs = []
    for snr in (0.0, 15.0, 30.0):
        rng = np.random.default_rng(7)
        X = synth_snapshots(UCA5, az, snr_db=snr, n_snap=1000, rng=rng)
        p = music(covariance_from_iq(X), UCA5, FREQ, GRID, n_sources=1)
        errs.append(ang_err(grid_peak(p, GRID), az))
    assert errs[2] <= errs[0] + 0.25
    assert errs[2] <= 0.5


# ── ULA root-MUSIC / ESPRIT (mirror ambiguity allowed) ───────────────────────

def ula_err(est_az, az_true, axis_deg=90.0):
    """A ULA cannot distinguish the mirror about its axis; accept either."""
    mirror = (2 * axis_deg - az_true) % 360.0  # reflection across the array axis
    return min(ang_err(est_az, az_true), ang_err(est_az, mirror))


@pytest.mark.parametrize("az_true", [20.0, 60.0, 150.0])
def test_root_music_ula(az_true):
    X = synth_snapshots(ULA8, az_true, snr_db=20.0)
    R = covariance_from_iq(X)
    roots = root_music(R, ULA8, FREQ, n_sources=1)
    assert min(ula_err(float(r), az_true) for r in np.atleast_1d(roots)) <= 1.0


@pytest.mark.parametrize("az_true", [20.0, 60.0, 150.0])
def test_esprit_ula(az_true):
    X = synth_snapshots(ULA8, az_true, snr_db=20.0)
    R = covariance_from_iq(X)
    azs = esprit(R, ULA8, FREQ, n_sources=1)
    assert min(ula_err(float(a), az_true) for a in np.atleast_1d(azs)) <= 1.0


# ── classic DF (Watson-Watt / correlative / pseudo-Doppler) ──────────────────
# These estimators take the 3-D ArrayGeometry from interferometry.py, so the
# synthetic snapshots are built with that module's own manifold.

def synth_snapshots_3d(geom, az_deg, snr_db=20.0, n_snap=2000, freq_hz=FREQ, rng=RNG):
    a = steering_matrix_3d(geom, freq_hz, np.array(az_deg), np.array(0.0))  # (N,)
    s = (rng.standard_normal(n_snap) + 1j * rng.standard_normal(n_snap)) / math.sqrt(2)
    X = np.outer(a, s)
    sigma_n = 10 ** (-snr_db / 20.0)
    X += sigma_n * (rng.standard_normal(X.shape) + 1j * rng.standard_normal(X.shape)) / math.sqrt(2)
    return X


UCA5_3D = Geom3D.uca(5, radius_m=0.45 * LAM / (2 * math.sin(math.pi / 5)))


@pytest.mark.parametrize("az_true", [10.0, 95.0, 200.0, 318.0])
def test_correlative_aoa(az_true):
    X = synth_snapshots_3d(UCA5_3D, az_true, snr_db=20.0)
    r = correlative_aoa(UCA5_3D, FREQ, X)
    assert ang_err(r.az_deg, az_true) <= 2.0
    assert 0.0 <= r.quality <= 1.0


@pytest.mark.parametrize("az_true", [10.0, 95.0, 200.0, 318.0])
def test_pseudo_doppler_aoa(az_true):
    X = synth_snapshots_3d(UCA5_3D, az_true, snr_db=25.0, n_snap=4000)
    r = pseudo_doppler_aoa(UCA5_3D, FREQ, X)
    assert ang_err(r.az_deg, az_true) <= 5.0


@pytest.mark.parametrize("az_true", [45.0, 170.0, 260.0])
def test_watson_watt_adcock(az_true):
    # 4-element N/E/S/W Adcock + centre sense element, electrically small (r ≪ λ)
    geom = Geom3D.adcock(4, radius_m=0.05 * LAM, sense=True)
    X = synth_snapshots_3d(geom, az_true, snr_db=30.0, n_snap=4000)
    r = watson_watt_aoa(geom, FREQ, X)
    err = ang_err(r.az_deg, az_true)
    # with a sense channel the 180° ambiguity must be resolved
    assert err <= 5.0, f"watson-watt {r.az_deg}° vs {az_true}° (err {err}°)"


# ── CRLB sanity ──────────────────────────────────────────────────────────────

def test_crlb_decreases_with_aperture_and_phase_noise():
    sigma = math.radians(8.0)
    small = Geom3D.uca(5, radius_m=0.1)
    large = Geom3D.uca(5, radius_m=0.4)
    s_small, _ = _crlb_phase(small, FREQ, 50.0, 0.0, sigma, 0, False)
    s_large, _ = _crlb_phase(large, FREQ, 50.0, 0.0, sigma, 0, False)
    assert s_large < s_small  # bigger aperture → tighter bound
    s_lo, _ = _crlb_phase(large, FREQ, 50.0, 0.0, sigma / 4, 0, False)
    assert abs(s_lo - (s_large / 4)) / (s_large / 4) < 1e-6  # bound linear in σ_φ


def test_music_meets_crlb_order_of_magnitude():
    """Monte-Carlo RMSE of MUSIC should sit near the CRLB (and never far below
    it — beating the bound means the bound or the noise model is wrong)."""
    az = 77.0
    snr_db, n_snap, trials = 15.0, 200, 24
    errs = []
    fine = np.linspace(az - 5, az + 5, 2001)
    for t in range(trials):
        rng = np.random.default_rng(100 + t)
        X = synth_snapshots(UCA5, az, snr_db=snr_db, n_snap=n_snap, rng=rng)
        p = music(covariance_from_iq(X), UCA5, FREQ, fine, n_sources=1)
        errs.append(grid_peak(p, fine) - az)
    rmse = float(np.sqrt(np.mean(np.square(errs))))
    # per-element phase σ ≈ 1/√(SNR·N) rad for coherent integration over N snaps
    sigma_phase = 1.0 / math.sqrt(10 ** (snr_db / 10) * n_snap)
    crlb, _ = _crlb_phase(UCA5_3D, FREQ, az, 0.0, sigma_phase, 0, False)
    assert crlb * 0.3 <= rmse <= crlb * 5.0, f"RMSE {rmse:.4f}° vs CRLB {crlb:.4f}°"
