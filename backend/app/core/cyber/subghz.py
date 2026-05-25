# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2026 Ares

"""
Sub-GHz (≈300–928 MHz ISM) capability, backed by the real SDR stack — no separate
radio app, no synthetic data. Scan/capture are passive (RX); replay/transmit are
active (TX) and are gated by the caller (``cyber`` package) behind
``ARES_AUTHORIZED_ACTIVE``.

Radios come from two places the rest of Ares already drives:
  * **configured devices** in :mod:`app.core.sdr.manager` (e.g. a Pluto over pyadi);
  * **SoapySDR** devices (HackRF / RTL / etc.) via :mod:`app.core.sdr.iq_capture`.

Everything here raises on "no radio" / "radio busy" rather than fabricating a trace.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

_CAP_DIR = Path(__file__).resolve().parents[3] / "data" / "cyber_captures"
_SUBGHZ_LO, _SUBGHZ_HI = 280e6, 960e6     # the band this capability advertises


class RadioBusy(RuntimeError):
    """The only suitable radio is currently owned by a running adapter (e.g. DF)."""


class NoRadio(RuntimeError):
    """No sub-GHz-capable SDR is available."""


# ── discovery ──────────────────────────────────────────────────────────────────
def _subghz_driver_ids() -> set[str]:
    from app.core.sdr import drivers
    ids = set()
    for d in drivers.list_drivers():
        lo, hi = (d.get("tunable_range_hz") or (0, 0))[:2] if d.get("tunable_range_hz") else (0, 0)
        if d.get("id") == "synthetic":
            continue
        if hi >= _SUBGHZ_LO and lo <= _SUBGHZ_HI:
            ids.add(d["id"])
    return ids


def radios() -> list[dict]:
    """All sub-GHz-capable radios available right now (configured + Soapy)."""
    from app.core.sdr import sdr_manager, drivers
    out: list[dict] = []
    tx_ids = {d["id"] for d in drivers.list_drivers() if d.get("tx_capable")}
    sub_ids = _subghz_driver_ids()
    for dev in sdr_manager.list():
        drv = (dev.get("metadata") or {}).get("driver_id")
        if drv and drv in sub_ids:
            out.append({"id": dev["id"], "label": dev.get("name") or drv, "source": "configured",
                        "driver": drv, "tx": drv in tx_ids, "busy": dev.get("status") == "streaming"})
    try:
        from app.core.sdr import iq_capture
        if iq_capture.available():
            for d in iq_capture.enumerate_devices():
                drv = d.get("driver", "soapy")
                out.append({"id": f"soapy:{drv}", "label": d.get("label") or drv, "source": "soapy",
                            "driver": drv, "tx": drv in ("hackrf", "pluto", "plutosdr", "uhd", "lime", "bladerf"),
                            "busy": False})
    except Exception as e:
        log.debug("soapy enumerate failed: %s", e)
    return out


def _pick(device_id: Optional[str]) -> dict:
    rs = radios()
    if not rs:
        raise NoRadio("no sub-GHz-capable SDR connected")
    if device_id:
        for r in rs:
            if r["id"] == device_id:
                return r
        raise NoRadio(f"radio {device_id!r} not found")
    return rs[0]


# ── passive: scan ───────────────────────────────────────────────────────────────
def scan(center_hz: float, span_hz: float = 2.0e6, n_bins: int = 1024,
         device_id: Optional[str] = None) -> dict:
    """Real PSD at ``center_hz``. Reuses the SDR manager for configured devices
    (so it cooperates with a running DF adapter) and SoapySDR otherwise."""
    if not (_SUBGHZ_LO <= center_hz <= _SUBGHZ_HI):
        raise ValueError(f"{center_hz/1e6:.3f} MHz outside the sub-GHz band "
                         f"({_SUBGHZ_LO/1e6:.0f}–{_SUBGHZ_HI/1e6:.0f} MHz)")
    r = _pick(device_id)
    if r["source"] == "configured":
        from app.core.sdr import sdr_manager
        fr = sdr_manager.device_spectrum(r["id"], center_hz, span_hz, n_bins, 0)
        if fr is None:
            fr = sdr_manager.ondemand_spectrum(r["id"], center_hz, span_hz, n_bins, 0)
        if fr is None:
            raise RadioBusy("radio is owned by a running adapter (stop DF to scan), "
                            "or produced no samples")
        fr["radio"] = r["label"]
        return fr
    # SoapySDR path — capture a block and Welch-average it.
    from app.core.sdr import iq_capture
    rate = max(span_hz, 2.0e6)
    dev = {"metadata": {"soapy": f"driver={r['driver']}"}}
    x = iq_capture.capture(dev, center_hz, rate, max(n_bins * 8, 8192), channels=(0,), gain_db=None)
    if x is None:
        raise NoRadio("SoapySDR returned no samples")
    X = np.asarray(x[0] if isinstance(x, list) else x)
    psd = _welch(X, n_bins)
    f0 = center_hz - rate / 2.0
    peak = int(np.argmax(psd))
    return {"source": "hardware", "radio": r["label"], "driver": r["driver"],
            "center_hz": center_hz, "span_hz": rate, "n_bins": n_bins,
            "power_dbm": [round(float(v), 2) for v in psd],
            "noise_floor_dbm": round(float(np.percentile(psd, 20)), 2),
            "peak_hz": round(f0 + peak / max(1, n_bins - 1) * rate, 1),
            "peak_dbm": round(float(psd[peak]), 2), "t": time.time()}


def _welch(x: np.ndarray, n_bins: int) -> np.ndarray:
    win = np.hanning(n_bins); wp = float(np.sum(win ** 2))
    nseg = max(1, len(x) // n_bins); acc = np.zeros(n_bins); cnt = 0
    for i in range(nseg):
        seg = x[i * n_bins:(i + 1) * n_bins]
        if len(seg) < n_bins:
            break
        acc += np.abs(np.fft.fftshift(np.fft.fft(seg * win))) ** 2; cnt += 1
    return 10.0 * np.log10(np.maximum(acc / (max(1, cnt) * wp), 1e-20)) - 30.0


# ── passive: capture ────────────────────────────────────────────────────────────
def capture(center_hz: float, rate_hz: float = 2.0e6, seconds: float = 1.0,
            device_id: Optional[str] = None) -> dict:
    """Record a short complex64 IQ burst to data/cyber_captures/ for later replay."""
    r = _pick(device_id)
    n = int(max(4096, min(rate_hz * seconds, 32e6)))    # cap at ~32 Msamp
    if r["source"] == "configured":
        from app.core.sdr import drivers, sdr_manager
        if r.get("busy"):
            # a running adapter owns the radio — borrow its DDC'd capture if it offers one
            x = sdr_manager.capture_iq(r["id"], center_hz, rate_hz, n)
            if x is None:
                raise RadioBusy("radio is in use by a running adapter (stop it to capture)")
        else:
            # idle device → open its built-in driver directly (free any warm spectrum handle first)
            rel = getattr(sdr_manager, "_release_spectrum_driver", None)
            if rel:
                try:
                    rel(r["id"])
                except Exception:
                    pass
            dev = sdr_manager.get(r["id"])
            drv = drivers.create((getattr(dev, "metadata", {}) or {}).get("driver_id"), channels=1)
            drv.open()
            try:
                drv.set_frequency(center_hz); drv.set_sample_rate(rate_hz)
                x = drv.read_iq(n).samples
            finally:
                try:
                    drv.close()
                except Exception:
                    pass
    else:
        from app.core.sdr import iq_capture
        dev = {"metadata": {"soapy": f"driver={r['driver']}"}}
        x = iq_capture.capture(dev, center_hz, rate_hz, n, channels=(0,), gain_db=None)
    if x is None:
        raise NoRadio("capture returned no samples")
    X = np.ascontiguousarray(np.asarray(x[0] if isinstance(x, list) else x, dtype=np.complex64))
    _CAP_DIR.mkdir(parents=True, exist_ok=True)
    cid = f"sg_{int(time.time())}_{int(center_hz/1e3)}k"
    path = _CAP_DIR / f"{cid}.npy"
    np.save(path, X)
    return {"id": cid, "center_hz": center_hz, "rate_hz": rate_hz,
            "samples": int(X.size), "seconds": round(X.size / rate_hz, 4),
            "path": str(path), "t": time.time()}


def list_captures() -> list[dict]:
    if not _CAP_DIR.exists():
        return []
    out = []
    for p in sorted(_CAP_DIR.glob("sg_*.npy")):
        try:
            out.append({"id": p.stem, "bytes": p.stat().st_size, "t": p.stat().st_mtime})
        except OSError:
            pass
    return out


# ── ACTIVE: replay / transmit (gated by caller) ─────────────────────────────────
def transmit(center_hz: float, rate_hz: float, *, capture_id: Optional[str] = None,
             device_id: Optional[str] = None) -> dict:
    """Re-radiate a previously captured burst. ACTIVE — caller must enforce the
    authorization gate + audit before calling this."""
    if capture_id is None:
        raise ValueError("transmit needs a capture_id (capture a burst first)")
    path = _CAP_DIR / f"{capture_id}.npy"
    if not path.exists():
        raise FileNotFoundError(f"no such capture {capture_id!r}")
    samples = np.load(path).astype(np.complex64)
    r = _pick(device_id)
    if not r.get("tx"):
        raise NoRadio(f"radio {r['label']!r} cannot transmit")
    if r.get("busy"):
        raise RadioBusy("radio is in use by a running adapter")
    if r["source"] == "configured":
        from app.core.sdr import drivers, sdr_manager
        rel = getattr(sdr_manager, "_release_spectrum_driver", None)
        if rel:
            try:
                rel(r["id"])
            except Exception:
                pass
        dev = sdr_manager.get(r["id"])
        drv_id = (getattr(dev, "metadata", {}) or {}).get("driver_id")
        drv = drivers.create(drv_id, channels=1)
        drv.open()
        try:
            drv.set_frequency(center_hz); drv.set_sample_rate(rate_hz); drv.transmit(samples)
        finally:
            try:
                drv.close()
            except Exception:
                pass
    else:
        from app.core.sdr import iq_capture
        dev = {"metadata": {"soapy": f"driver={r['driver']}"}}
        ok = iq_capture.transmit(dev, center_hz, rate_hz, samples, channel=0, gain_db=None)
        if not ok:
            raise RuntimeError("SoapySDR transmit failed")
    return {"transmitted": int(samples.size), "center_hz": center_hz, "rate_hz": rate_hz,
            "radio": r["label"], "capture_id": capture_id, "t": time.time()}
