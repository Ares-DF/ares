# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""Mathematical verification of the propagation stack.

Closed-form checks against the published formulas (FSPL, Hata, knife-edge
Fresnel), cross-method agreement (the four diffraction constructions must
coincide for a single obstacle), and physical invariants (reciprocity,
monotonicity, asymptotic slopes) that hold regardless of implementation."""

import math

import numpy as np
import pytest

from app.core.propagation.models import (
    LinkBudget, PropagationModel, fspl_db, batch_fspl_db, hata_urban_db,
    cost231_hata_db, two_ray_db, egli_db, radar_two_way_db, select_model,
    oxygen_absorption_db_per_km, rain_attenuation_db_per_km,
)
from app.core.propagation.diffraction import (
    _knife_edge_loss_db, single_knife_edge_db, epstein_peterson_db,
    bullington_db, deygout_db, giovanelli_db,
)
from app.core.propagation.itm_its import compute_itm_path_loss
from app.core.propagation.antenna import AntennaConfig, AntennaType, get_antenna_gain_dbi
from app.core.propagation.atmosphere import AtmosphericConditions, compute_atmospheric_loss

C = 299_792_458.0


# ── free space ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("d_m,f_hz", [(1000.0, 1e9), (35_786_000.0, 12e9), (100.0, 433e6)])
def test_fspl_matches_definition(d_m, f_hz):
    expected = 20 * math.log10(4 * math.pi * d_m * f_hz / C)
    assert abs(fspl_db(d_m, f_hz) - expected) < 0.01


def test_fspl_known_value():
    # canonical: 1 km @ 2.4 GHz = 100.05 dB
    assert abs(fspl_db(1000.0, 2.4e9) - 100.05) < 0.1


def test_batch_fspl_agrees_with_scalar():
    d = np.array([100.0, 1000.0, 10_000.0])
    b = batch_fspl_db(d, 868e6)
    for i, dm in enumerate(d):
        assert abs(float(b[i]) - fspl_db(float(dm), 868e6)) < 1e-6


# ── empirical models vs published formulas ───────────────────────────────────

def test_hata_urban_published_value():
    """Hata (1980), medium city: f=900 MHz, hb=30 m, hm=1.5 m, d=1 km.
    L = 69.55 + 26.16·log f − 13.82·log hb − a(hm) + (44.9 − 6.55·log hb)·log d"""
    f, hb, hm = 900.0, 30.0, 1.5
    a_hm = (1.1 * math.log10(f) - 0.7) * hm - (1.56 * math.log10(f) - 0.8)
    expected = 69.55 + 26.16 * math.log10(f) - 13.82 * math.log10(hb) - a_hm
    got = hata_urban_db(1.0, f, tx_height_m=hb, rx_height_m=hm)
    assert abs(got - expected) < 0.5, f"{got} vs {expected}"


def test_cost231_published_value():
    """COST-231 Hata: f=1800 MHz, hb=30, hm=1.5, d=1 km, medium city (C=0)."""
    f, hb, hm = 1800.0, 30.0, 1.5
    a_hm = (1.1 * math.log10(f) - 0.7) * hm - (1.56 * math.log10(f) - 0.8)
    expected = 46.3 + 33.9 * math.log10(f) - 13.82 * math.log10(hb) - a_hm
    got = cost231_hata_db(1.0, f, tx_height_m=hb, rx_height_m=hm)
    assert abs(got - expected) < 3.5, f"{got} vs {expected} (city-size constant tolerance)"


def test_hata_distance_slope():
    """Hata slope is (44.9 − 6.55·log hb) dB/decade — verify numerically."""
    f, hb = 900.0, 30.0
    slope = (hata_urban_db(10.0, f, tx_height_m=hb, rx_height_m=1.5)
             - hata_urban_db(1.0, f, tx_height_m=hb, rx_height_m=1.5))
    assert abs(slope - (44.9 - 6.55 * math.log10(hb))) < 0.5


def test_two_ray_fourth_power_asymptote():
    """Far beyond the breakpoint, two-ray loss grows 40·log d → +12.04 dB per doubling."""
    f, ht, hr = 900e6, 30.0, 2.0
    d1 = 50_000.0
    delta = two_ray_db(2 * d1, f, ht, hr) - two_ray_db(d1, f, ht, hr)
    assert abs(delta - 12.04) < 0.5


def test_radar_two_way_slope():
    d1 = 10_000.0
    delta = radar_two_way_db(2 * d1, 3e9) - radar_two_way_db(d1, 3e9)
    assert abs(delta - 12.04) < 0.5  # 40·log d for the two-way path


def test_egli_matches_formula():
    """Egli: L = 117 + 40·log d_mi… — verify the 40 dB/decade distance behavior
    and TX-height gain of 20·log h."""
    f = 450.0
    slope = (egli_db(10.0, f, tx_height_m=10.0, rx_height_m=1.5)
             - egli_db(1.0, f, tx_height_m=10.0, rx_height_m=1.5))
    assert abs(slope - 40.0) < 0.5
    h_gain = (egli_db(5.0, f, tx_height_m=10.0, rx_height_m=1.5)
              - egli_db(5.0, f, tx_height_m=20.0, rx_height_m=1.5))
    assert abs(h_gain - 20.0 * math.log10(2.0)) < 0.5


def test_select_model_dispatch_every_model_finite():
    """Every enum member must dispatch to a real implementation and return a
    finite, positive loss at a representative geometry."""
    for model in PropagationModel:
        loss = select_model(model, 5_000.0, 900e6, 30.0, 1.5, context=2)
        assert math.isfinite(loss), f"{model.value} returned non-finite loss"
        assert 20.0 < loss < 400.0, f"{model.value} loss {loss:.1f} dB implausible"


def test_models_monotonic_with_distance():
    for model in (PropagationModel.FSPL, PropagationModel.HATA_URBAN,
                  PropagationModel.COST231_HATA, PropagationModel.EGLI):
        losses = [select_model(model, d, 900e6, 30.0, 1.5) for d in (1e3, 3e3, 10e3, 30e3)]
        assert all(b > a for a, b in zip(losses, losses[1:])), f"{model.value} not monotonic: {losses}"


# ── knife-edge diffraction vs the analytic Fresnel-integral approximation ────

@pytest.mark.parametrize("v,expected", [(-0.78, 0.0), (0.0, 6.02), (1.0, 13.93), (2.4, 20.55)])
def test_knife_edge_loss_reference_points(v, expected):
    """ITU-R P.526 J(ν) = 6.9 + 20·log10(√((ν−0.1)²+1)+ν−0.1) for ν>−0.78,
    else 0. Reference points evaluated from that closed form."""
    got = _knife_edge_loss_db(v)
    assert abs(got - expected) < 0.3, f"J({v}) = {got} vs {expected}"


def synth_profile(n=201, total_m=20_000.0, obstacle_idx=100, obstacle_h=120.0):
    elev = np.zeros(n)
    elev[obstacle_idx] = obstacle_h
    dist = np.linspace(0.0, total_m, n)
    return elev.tolist(), dist.tolist()


def test_single_knife_edge_matches_analytic_nu():
    """Build one triangular obstacle and compare against J(ν) computed from the
    geometry by hand."""
    elev, dist = synth_profile()
    freq = 900e6
    h_tx, h_rx = 10.0, 10.0
    d1, d2 = 10_000.0, 10_000.0
    h = 120.0 - 10.0  # obstacle height above the (level) TX–RX sightline
    lam = C / freq
    v = h * math.sqrt(2.0 / lam * (1.0 / d1 + 1.0 / d2))
    expected = 6.9 + 20 * math.log10(math.sqrt((v - 0.1) ** 2 + 1) + v - 0.1)
    got = single_knife_edge_db(elev, dist, h_tx, h_rx, freq)
    assert abs(got - expected) < 1.5, f"single knife edge {got} dB vs analytic {expected} dB"


def test_diffraction_methods_agree_for_single_obstacle():
    """With exactly one knife edge all four constructions reduce to the same
    single-edge loss."""
    elev, dist = synth_profile()
    freq = 900e6
    args = (elev, dist, 10.0, 10.0, freq)
    ref = single_knife_edge_db(*args)
    for fn in (epstein_peterson_db, bullington_db, deygout_db, giovanelli_db):
        got = fn(*args)
        assert abs(got - ref) < 1.5, f"{fn.__name__} {got} vs single-edge {ref}"


def test_diffraction_zero_when_path_clear():
    elev = [0.0] * 201
    dist = np.linspace(0, 20_000, 201).tolist()
    for fn in (single_knife_edge_db, epstein_peterson_db, bullington_db, deygout_db):
        loss = fn(elev, dist, 50.0, 50.0, 900e6)
        assert loss <= 1.0, f"{fn.__name__} reports {loss} dB on a clear path"


def test_diffraction_increases_with_obstacle_height():
    losses = []
    for h in (40.0, 80.0, 160.0):
        elev, dist = synth_profile(obstacle_h=h)
        losses.append(deygout_db(elev, dist, 10.0, 10.0, 900e6))
    assert losses[0] < losses[1] < losses[2]


# ── ITM (Longley-Rice) sanity ────────────────────────────────────────────────

def itm_loss(dist_m=10_000.0, freq_mhz=900.0, h1=30.0, h2=10.0, elev=None, n=101):
    if elev is None:
        elev = [0.0] * n
    r = compute_itm_path_loss(elevations=elev, distance_m=dist_m,
                              tx_height_m=h1, rx_height_m=h2, frequency_mhz=freq_mhz)
    return r.path_loss_db


def test_itm_smooth_earth_near_fspl_at_short_los():
    """Short line-of-sight over smooth earth: ITM must sit near FSPL — within
    the two-ray interference swing (−6 dB enhancement … +20 dB cancellation)."""
    pl = itm_loss(5_000.0, 900.0, 30.0, 10.0)
    fs = fspl_db(5_000.0, 900e6)
    assert fs - 6.0 <= pl <= fs + 20.0, f"ITM {pl:.1f} vs FSPL {fs:.1f}"


def test_itm_increases_with_distance_on_average():
    d = [2e3, 10e3, 40e3, 80e3]
    pls = [itm_loss(x, 900.0, 30.0, 10.0, n=201) for x in d]
    assert pls[-1] > pls[0] + 20.0, f"no distance trend: {pls}"


def test_itm_terrain_obstruction_adds_loss():
    n = 101
    flat = itm_loss(20_000.0, 900.0, 10.0, 10.0, [0.0] * n, n)
    hill = [0.0] * n
    hill[50] = 150.0
    blocked = itm_loss(20_000.0, 900.0, 10.0, 10.0, hill, n)
    assert blocked > flat + 5.0, f"obstruction added only {blocked - flat:.1f} dB"


def test_itm_reciprocity():
    """Swapping TX and RX heights over a symmetric profile must not change loss."""
    n = 101
    profile = (np.sin(np.linspace(0, math.pi, n)) * 20.0).tolist()  # symmetric bump
    a = itm_loss(15_000.0, 450.0, 25.0, 5.0, profile, n)
    b = itm_loss(15_000.0, 450.0, 5.0, 25.0, profile, n)
    assert abs(a - b) < 1.0, f"ITM not reciprocal: {a:.2f} vs {b:.2f}"


# ── atmosphere ───────────────────────────────────────────────────────────────

def test_oxygen_60ghz_peak():
    assert oxygen_absorption_db_per_km(60.0) > 10.0      # the O₂ resonance
    assert oxygen_absorption_db_per_km(10.0) < 0.1


def test_rain_attenuation_behavior():
    assert rain_attenuation_db_per_km(10.0, 0.0) == pytest.approx(0.0, abs=1e-9)
    a = rain_attenuation_db_per_km(10.0, 10.0)
    b = rain_attenuation_db_per_km(10.0, 50.0)
    c = rain_attenuation_db_per_km(30.0, 10.0)
    assert 0.0 < a < b      # more rain, more loss
    assert a < c            # higher frequency, more loss
    # ITU-R P.838 ballpark at 10 GHz / 10 mm/h ≈ 0.1–0.3 dB/km (vert pol)
    assert 0.03 < a < 1.0


def test_atmospheric_loss_scales_with_distance():
    atm = AtmosphericConditions()
    l1 = compute_atmospheric_loss(10e9, 10_000.0, atm, 0.0).total_db
    l2 = compute_atmospheric_loss(10e9, 20_000.0, atm, 0.0).total_db
    assert l2 > l1 > 0.0
    assert abs(l2 / l1 - 2.0) < 0.3   # ~linear in distance for gaseous absorption


# ── antennas ─────────────────────────────────────────────────────────────────

def test_isotropic_and_dipole_gains():
    iso = AntennaConfig(type=AntennaType.ISOTROPIC)
    assert get_antenna_gain_dbi(iso, 0.0, 0.0) == pytest.approx(0.0, abs=0.01)
    dip = AntennaConfig(type=AntennaType.DIPOLE_HALF_WAVE)
    assert get_antenna_gain_dbi(dip, 0.0, 0.0) == pytest.approx(2.15, abs=0.2)


def test_dish_gain_matches_aperture_formula():
    """G = 10·log10(η·(πD/λ)²) at boresight."""
    f = 10e9
    cfg = AntennaConfig(type=AntennaType.PARABOLIC_DISH, diameter_m=1.2,
                        efficiency=0.55, frequency_hz=f)
    lam = C / f
    expected = 10 * math.log10(0.55 * (math.pi * 1.2 / lam) ** 2)
    got = get_antenna_gain_dbi(cfg, 0.0, 0.0)
    assert abs(got - expected) < 1.0, f"dish {got:.1f} dBi vs formula {expected:.1f} dBi"


def test_directional_gain_decreases_off_boresight():
    f = 10e9
    cfg = AntennaConfig(type=AntennaType.PARABOLIC_DISH, diameter_m=1.2,
                        efficiency=0.55, frequency_hz=f)
    g0 = get_antenna_gain_dbi(cfg, 0.0, 0.0)
    g10 = get_antenna_gain_dbi(cfg, 0.0, 10.0)
    g40 = get_antenna_gain_dbi(cfg, 0.0, 40.0)
    assert g0 > g10 > g40


def test_yagi_gain_grows_with_elements():
    g3 = get_antenna_gain_dbi(AntennaConfig(type=AntennaType.YAGI_3EL), 0.0, 0.0)
    g15 = get_antenna_gain_dbi(AntennaConfig(type=AntennaType.YAGI_15EL), 0.0, 0.0)
    assert g15 > g3 + 3.0


# ── link budget arithmetic (incl. the de-stubbed feedline loss) ──────────────

def test_link_budget_arithmetic_exact():
    lb = LinkBudget(tx_power_dbm=30.0, tx_antenna_gain_dbi=6.0, tx_cable_loss_db=2.0,
                    rx_antenna_gain_dbi=3.0, rx_cable_loss_db=1.5,
                    path_loss_db=110.0, atmospheric_loss_db=0.7, rain_loss_db=0.3,
                    polarization_mismatch_db=0.5)
    assert lb.eirp_dbm == pytest.approx(34.0)
    assert lb.received_power_dbm == pytest.approx(30 + 6 - 2 + 3 - 1.5 - 110 - 0.7 - 0.3 - 0.5)
    assert lb.link_margin_db == pytest.approx(lb.received_power_dbm - lb.rx_sensitivity_dbm)
