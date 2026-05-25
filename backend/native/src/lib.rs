// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

//! ares_native — optional Rust acceleration (Track D, D4).
//!
//! The seam, not a rewrite. `app.core.native` imports this if the wheel is built
//! and the Python callers fall back to their pure-Python paths otherwise, so Ares
//! always runs. Ported here are the hot loops that are (a) pure scalar Python —
//! NOT numpy-backed — and (b) on a per-pixel / per-path critical path:
//!
//!   - terrain diffraction (diffraction.py): all five knife-edge models, called
//!     per-pixel from the coverage/raster path. Zero numpy in the original.
//!   - ITM horizon analysis (_hzns): the one sequential, non-vectorisable loop in
//!     the Longley-Rice profile path (_zlsq1/_dlthx are already numpy → left in
//!     Python).
//!
//! Numeric parity with the Python originals is asserted by test_native_parity.

use pyo3::prelude::*;

const C: f64 = 3e8;

// ── proof-of-wiring kernels (kept for the native shim / benchmarks) ──────────
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[pyfunction]
fn sum_squares(xs: Vec<f64>) -> f64 {
    xs.iter().map(|x| x * x).sum()
}

// ── diffraction helpers (mirror diffraction.py exactly) ──────────────────────
fn fresnel_v(h: f64, d1: f64, d2: f64, wl: f64) -> f64 {
    if d1 <= 0.0 || d2 <= 0.0 || wl <= 0.0 {
        return 0.0;
    }
    h * (2.0 * (d1 + d2) / (wl * d1 * d2)).sqrt()
}

fn knife_edge_loss_db(v: f64) -> f64 {
    if v < -0.7 {
        return 0.0;
    }
    let inner = ((v - 0.1).powi(2) + 1.0).sqrt() + v - 0.1;
    if inner <= 0.0 {
        return 0.0;
    }
    (6.9 + 20.0 * inner.log10()).max(0.0)
}

fn los_height_at(d: f64, d_total: f64, h_tx: f64, h_rx: f64) -> f64 {
    if d_total <= 0.0 {
        return h_tx;
    }
    h_tx + (h_rx - h_tx) * d / d_total
}

/// (clearance, distance-from-start) for each interior point.
fn clearances(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64) -> Vec<(f64, f64)> {
    let n = elev.len();
    if n < 3 {
        return Vec::new();
    }
    let h_tx = elev[0] + tx_h;
    let h_rx = elev[n - 1] + rx_h;
    let d_total = dist[n - 1] - dist[0];
    let mut out = Vec::with_capacity(n - 2);
    for i in 1..n - 1 {
        let d = dist[i] - dist[0];
        let los = los_height_at(d, d_total, h_tx, h_rx);
        out.push((elev[i] - los, dist[i] - dist[0]));
    }
    out
}

fn single_knife_edge(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64) -> f64 {
    let n = elev.len();
    if n < 3 || freq <= 0.0 {
        return 0.0;
    }
    let wl = C / freq;
    let d_total = dist[n - 1] - dist[0];
    let cl = clearances(elev, dist, tx_h, rx_h);
    if cl.is_empty() {
        return 0.0;
    }
    // worst (highest) obstacle — matches Python max(..., key=clearance)
    let mut best = cl[0];
    for &c in &cl[1..] {
        if c.0 > best.0 {
            best = c;
        }
    }
    if best.0 <= 0.0 {
        return 0.0;
    }
    let (d1, d2) = (best.1, d_total - best.1);
    if d1 <= 0.0 || d2 <= 0.0 {
        return 0.0;
    }
    knife_edge_loss_db(fresnel_v(best.0, d1, d2, wl)).max(0.0)
}

fn epstein_peterson(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64) -> f64 {
    let n = elev.len();
    if n < 3 || freq <= 0.0 {
        return 0.0;
    }
    let wl = C / freq;
    let d_total = dist[n - 1] - dist[0];
    let mut total = 0.0;
    for (h, d) in clearances(elev, dist, tx_h, rx_h) {
        if h <= 0.0 {
            continue;
        }
        let (d1, d2) = (d, d_total - d);
        if d1 <= 0.0 || d2 <= 0.0 {
            continue;
        }
        total += knife_edge_loss_db(fresnel_v(h, d1, d2, wl)).max(0.0);
    }
    total
}

fn bullington(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64) -> f64 {
    let n = elev.len();
    if n < 3 || freq <= 0.0 {
        return 0.0;
    }
    let wl = C / freq;
    let d_total = dist[n - 1] - dist[0];
    let h_tx = elev[0] + tx_h;
    let h_rx = elev[n - 1] + rx_h;

    let mut max_slope_tx = f64::NEG_INFINITY;
    for i in 1..n - 1 {
        let d = dist[i] - dist[0];
        if d <= 0.0 {
            continue;
        }
        let slope = (elev[i] - h_tx) / d;
        if slope > max_slope_tx {
            max_slope_tx = slope;
        }
    }
    let mut max_slope_rx = f64::NEG_INFINITY;
    for i in 1..n - 1 {
        let d = d_total - (dist[i] - dist[0]);
        if d <= 0.0 {
            continue;
        }
        let slope = (elev[i] - h_rx) / d;
        if slope > max_slope_rx {
            max_slope_rx = slope;
        }
    }

    let denom = max_slope_tx + max_slope_rx;
    let d_edge = if denom.abs() < 1e-9 {
        d_total / 2.0
    } else {
        let e = (h_rx - h_tx + max_slope_rx * d_total) / denom;
        e.max(1.0).min(d_total - 1.0)
    };
    let h_edge = h_tx + max_slope_tx * d_edge;
    let clearance = h_edge - los_height_at(d_edge, d_total, h_tx, h_rx);
    if clearance <= 0.0 {
        return 0.0;
    }
    let (d1, d2) = (d_edge, d_total - d_edge);
    if d1 <= 0.0 || d2 <= 0.0 {
        return 0.0;
    }
    knife_edge_loss_db(fresnel_v(clearance, d1, d2, wl)).max(0.0)
}

fn deygout_recurse(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64, depth: u32) -> f64 {
    let n = elev.len();
    if n < 3 || depth > 4 {
        return 0.0;
    }
    let wl = C / freq;
    let d_start = dist[0];
    let d_total = dist[n - 1] - d_start;
    let mut best_v = f64::NEG_INFINITY;
    let mut best_idx: isize = -1;
    for i in 1..n - 1 {
        let d = dist[i] - d_start;
        let h_clear = elev[i] - los_height_at(d, d_total, tx_h, rx_h);
        let (d1, d2) = (d, d_total - d);
        if d1 <= 0.0 || d2 <= 0.0 {
            continue;
        }
        let v = fresnel_v(h_clear, d1, d2, wl);
        if v > best_v {
            best_v = v;
            best_idx = i as isize;
        }
    }
    if best_idx < 0 || best_v <= 0.0 {
        return 0.0;
    }
    let bi = best_idx as usize;
    let mut loss = knife_edge_loss_db(best_v).max(0.0);
    loss += deygout_recurse(&elev[..=bi], &dist[..=bi], tx_h, elev[bi], freq, depth + 1);
    loss += deygout_recurse(&elev[bi..], &dist[bi..], elev[bi], rx_h, freq, depth + 1);
    loss
}

fn deygout(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64) -> f64 {
    let n = elev.len();
    if n < 3 || freq <= 0.0 {
        return 0.0;
    }
    let h_tx = elev[0] + tx_h;
    let h_rx = elev[n - 1] + rx_h;
    deygout_recurse(elev, dist, h_tx, h_rx, freq, 0)
}

fn giovanelli(elev: &[f64], dist: &[f64], tx_h: f64, rx_h: f64, freq: f64) -> f64 {
    let n = elev.len();
    if n < 3 || freq <= 0.0 {
        return 0.0;
    }
    let ep = epstein_peterson(elev, dist, tx_h, rx_h, freq);
    if ep <= 0.0 {
        return 0.0;
    }
    let bull = bullington(elev, dist, tx_h, rx_h, freq);
    let j = 0.2;
    let combined = bull + j * (ep - bull);
    bull.max(combined)
}

/// Dispatch by model name; unknown ⇒ deygout (matches diffraction.py default).
#[pyfunction]
fn diffraction_db(
    model: &str,
    elevations: Vec<f64>,
    distances: Vec<f64>,
    tx_height_m: f64,
    rx_height_m: f64,
    freq_hz: f64,
) -> f64 {
    let (e, d) = (&elevations[..], &distances[..]);
    match model {
        "single_knife_edge" => single_knife_edge(e, d, tx_height_m, rx_height_m, freq_hz),
        "epstein_peterson" => epstein_peterson(e, d, tx_height_m, rx_height_m, freq_hz),
        "bullington" => bullington(e, d, tx_height_m, rx_height_m, freq_hz),
        "giovanelli" => giovanelli(e, d, tx_height_m, rx_height_m, freq_hz),
        _ => deygout(e, d, tx_height_m, rx_height_m, freq_hz),
    }
}

// ── ITM horizon analysis (mirror itm_its._hzns exactly) ──────────────────────
/// Returns (the0, the1, dl0, dl1) — the two horizon elevation angles + distances.
#[pyfunction]
fn itm_hzns(pfl: Vec<f64>, hg0: f64, hg1: f64, gme: f64, dist: f64) -> (f64, f64, f64, f64) {
    let np_ = pfl[0] as usize;
    let xi = pfl[1];
    let za = pfl[2] + hg0;
    let zb = pfl[np_ + 2] + hg1;
    let qc = 0.5 * gme;
    let mut q = qc * dist;
    let mut the1 = (zb - za) / dist;
    let mut the0 = the1 - q;
    the1 = -the1 - q;
    let mut dl0 = dist;
    let mut dl1 = dist;
    if np_ >= 2 {
        let mut sa = 0.0;
        let mut sb = dist;
        let mut wq = true;
        for i in 1..np_ {
            sa += xi;
            sb -= xi;
            q = pfl[i + 2] - (qc * sa + the0) * sa - za;
            if q > 0.0 {
                the0 += q / sa;
                dl0 = sa;
                wq = false;
            }
            if !wq {
                q = pfl[i + 2] - (qc * sb + the1) * sb - zb;
                if q > 0.0 {
                    the1 += q / sb;
                    dl1 = sb;
                }
            }
        }
    }
    (the0, the1, dl0, dl1)
}

#[pymodule]
fn ares_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add_function(wrap_pyfunction!(sum_squares, m)?)?;
    m.add_function(wrap_pyfunction!(diffraction_db, m)?)?;
    m.add_function(wrap_pyfunction!(itm_hzns, m)?)?;
    Ok(())
}
