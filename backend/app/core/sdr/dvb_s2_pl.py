"""
dvb_s2_pl.py — DVB-S2 physical-layer framing primitives (EN 302 307-1 §5.5).

What a receiver needs to find DVB-S2 FECFRAMEs in a symbol stream and learn their
config, before the FEC (dvb_s2_fec):

  * **SOF** — the 26-symbol π/2-BPSK Start-Of-Frame (0x18D2E82); correlate to locate
    each PLFRAME.
  * **PLS** — the 64-symbol Physical-Layer Signalling code: MODCOD (5 b) + TYPE (frame
    size + pilots), bi-orthogonally (64,7)-coded and scrambled. Decoded by correlating
    against all candidate codewords → constellation + code rate + frame size + pilots.
  * **PL scrambler** — the complex Gold sequence (two degree-18 m-sequences) that
    randomises the XFECFRAME; descramble = multiply by exp(−j·Rn·π/2).

These are the framing primitives. Turning a live capture into FECFRAME soft bits
additionally needs APSK soft-demap + pilot-block removal + XFECFRAME assembly (the
remaining live layer); these primitives + dvb_s2_fec are the verified pieces.

Self-test: ``python -m app.core.sdr.dvb_s2_pl``.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

_SQRT1_2 = 1.0 / np.sqrt(2.0)
_SOF_HEX = 0x18D2E82                       # 26-bit SOF, MSB first
_PLS_SCRAMBLE = "0111000110011101100000111100100101010011010000100010110111111010"  # 64 bits

# (32,6) generator matrix G (Figure 13b), 6 rows × 32 bits.
_G32 = [
    "01010101010101010101010101010101",
    "00110011001100110011001100110011",
    "00001111000011110000111100001111",
    "00000000111111110000000011111111",
    "00000000000000001111111111111111",
    "11111111111111111111111111111111",
]

# MODCOD value → (modulation, code_rate) (Table 12). 0 = dummy PLFRAME.
MODCOD_TABLE = {
    1: ("qpsk", "1/4"), 2: ("qpsk", "1/3"), 3: ("qpsk", "2/5"), 4: ("qpsk", "1/2"),
    5: ("qpsk", "3/5"), 6: ("qpsk", "2/3"), 7: ("qpsk", "3/4"), 8: ("qpsk", "4/5"),
    9: ("qpsk", "5/6"), 10: ("qpsk", "8/9"), 11: ("qpsk", "9/10"),
    12: ("8psk", "3/5"), 13: ("8psk", "2/3"), 14: ("8psk", "3/4"), 15: ("8psk", "5/6"),
    16: ("8psk", "8/9"), 17: ("8psk", "9/10"),
    18: ("16apsk", "2/3"), 19: ("16apsk", "3/4"), 20: ("16apsk", "4/5"), 21: ("16apsk", "5/6"),
    22: ("16apsk", "8/9"), 23: ("16apsk", "9/10"),
    24: ("32apsk", "3/4"), 25: ("32apsk", "4/5"), 26: ("32apsk", "5/6"), 27: ("32apsk", "8/9"),
    28: ("32apsk", "9/10"),
}


def _pi2_bpsk(bits, start: int = 0) -> np.ndarray:
    """π/2-BPSK modulate a header bit sequence at absolute header position ``start``."""
    out = np.empty(len(bits), dtype=np.complex64)
    for m, b in enumerate(bits):
        s = (1.0 - 2.0 * b) * _SQRT1_2
        pos = start + m
        out[m] = (s + 1j * s) if (pos % 2 == 0) else (-s + 1j * s)
    return out


def sof_symbols() -> np.ndarray:
    bits = [(_SOF_HEX >> (25 - i)) & 1 for i in range(26)]
    return _pi2_bpsk(bits, 0)


def _pls_bits(modcod: int, short: bool, pilots: bool) -> list[int]:
    b = [(modcod >> (4 - i)) & 1 for i in range(5)] + [1 if short else 0]   # b1..b6
    y32 = [0] * 32
    for i in range(6):
        if b[i]:
            row = _G32[i]
            for j in range(32):
                y32[j] ^= int(row[j])
    b7 = 1 if pilots else 0
    y64 = []
    for j in range(32):
        y64.append(y32[j]); y64.append(y32[j] ^ b7)        # repeat, complemented if b7
    scr = [int(c) for c in _PLS_SCRAMBLE]
    return [y64[i] ^ scr[i] for i in range(64)]


def pls_symbols(modcod: int, short: bool, pilots: bool) -> np.ndarray:
    return _pi2_bpsk(_pls_bits(modcod, short, pilots), start=26)            # after the 26-symbol SOF


# ── SOF correlation + PLS decode ─────────────────────────────────────────────
def find_sof(symbols: np.ndarray, threshold: float = 0.6) -> Optional[int]:
    """Index of the best SOF correlation peak in ``symbols`` (normalised |corr| over
    the 26 SOF symbols), or None below threshold."""
    x = np.asarray(symbols, dtype=np.complex64)
    sof = sof_symbols()
    if x.size < sof.size:
        return None
    best_i, best_m = None, 0.0
    sof_n = np.linalg.norm(sof)
    for i in range(x.size - sof.size + 1):
        seg = x[i:i + sof.size]
        m = abs(np.vdot(sof, seg)) / (sof_n * (np.linalg.norm(seg) + 1e-12))
        if m > best_m:
            best_m, best_i = m, i
    return best_i if best_m >= threshold else None


def decode_pls(pls_rx: np.ndarray, phase: float = 0.0) -> Optional[dict]:
    """Decode the 64 PLS symbols (the slot after the SOF) → config. COHERENT
    correlation (real part): the frame-size bit negates the whole codeword, so
    |corr| can't distinguish it — the caller must phase-correct first (the SOF
    gives the reference); ``phase`` derotates the input if not already done."""
    x = np.asarray(pls_rx, dtype=np.complex64)[:64]
    if x.size < 64:
        return None
    if phase:
        x = x * np.exp(-1j * phase)
    best, best_m = None, -1e30
    for modcod in MODCOD_TABLE:
        for short in (False, True):
            for pilots in (False, True):
                ref = pls_symbols(modcod, short, pilots)
                m = np.vdot(ref, x).real            # coherent — preserves the sign
                if m > best_m:
                    best_m, best = m, (modcod, short, pilots)
    if best is None:
        return None
    modcod, short, pilots = best
    mod, rate = MODCOD_TABLE[modcod]
    return {"modcod": modcod, "modulation": mod, "code_rate": rate,
            "frame": "short" if short else "normal", "pilots": pilots,
            "corr": round(float(best_m), 2)}


# ── PL scrambler (complex Gold sequence, §5.5.4) ─────────────────────────────
def _rn_sequence(n: int, length: int) -> np.ndarray:
    """Rn(i) ∈ {0,1,2,3} for the chosen scrambling-code number n."""
    P = (1 << 18) - 1
    need = length + 131072 + n + 2
    x = np.zeros(need, dtype=np.uint8); x[0] = 1
    y = np.zeros(need, dtype=np.uint8); y[:18] = 1
    for i in range(need - 18):
        x[i + 18] = x[i + 7] ^ x[i]
        y[i + 18] = y[i + 10] ^ y[i + 7] ^ y[i + 5] ^ y[i]
    def zn(i):
        return x[(i + n) % P] ^ y[i % P]
    rn = np.empty(length, dtype=np.uint8)
    for i in range(length):
        rn[i] = (2 * zn((i + 131072) % P) + zn(i)) & 3
    return rn


def pl_descramble(symbols: np.ndarray, n: int = 0) -> np.ndarray:
    """Undo the PL scrambling: divide by exp(j·Rn·π/2) ⇒ multiply by exp(−j·Rn·π/2)."""
    x = np.asarray(symbols, dtype=np.complex64)
    rn = _rn_sequence(n, x.size)
    rot = np.exp(-1j * rn.astype(np.float64) * (np.pi / 2.0)).astype(np.complex64)
    return x * rot


def pl_scramble(symbols: np.ndarray, n: int = 0) -> np.ndarray:
    x = np.asarray(symbols, dtype=np.complex64)
    rn = _rn_sequence(n, x.size)
    rot = np.exp(1j * rn.astype(np.float64) * (np.pi / 2.0)).astype(np.complex64)
    return x * rot


_BITS_PER_SYM = {"qpsk": 2, "8psk": 3, "16apsk": 4, "32apsk": 5}


def _depilot(region: np.ndarray, n_data: int, pilots: bool) -> np.ndarray:
    """Strip the 36-symbol pilot block inserted after every 16 slots (1440 symbols)."""
    if not pilots:
        return region[:n_data]
    out = []
    src = 0
    while len(out) < n_data:
        take = min(16 * 90, n_data - len(out))
        out.extend(region[src:src + take]); src += take
        if len(out) < n_data:
            src += 36                                  # skip the pilot block
    return np.asarray(out[:n_data], dtype=np.complex64)


def decode_dvbs2_plframe(symbols: np.ndarray, n: int = 0):
    """Full DVB-S2 receive of one short-frame QPSK PLFRAME: SOF-sync → PLS decode →
    derotate + PL descramble → de-pilot → QPSK soft-demap → BCH+LDPC → BBFRAME bits.
    Returns (bbframe_bits | None, info). APSK/8PSK soft-demap is the remaining mod path."""
    from . import dvb_s2_fec
    x = np.asarray(symbols, dtype=np.complex64)
    off = find_sof(x)
    if off is None:
        return None, {"reason": "no SOF"}
    sof = sof_symbols()
    phase = float(np.angle(np.vdot(sof, x[off:off + 26])))
    cfg = decode_pls(x[off + 26:off + 90], phase=phase)
    if not cfg:
        return None, {"reason": "PLS decode failed"}
    if cfg["frame"] != "short" or cfg["modulation"] != "qpsk":
        return None, {"reason": f"only short-QPSK wired here; PLS={cfg}", **cfg}
    bps = _BITS_PER_SYM["qpsk"]
    n_bits = 16200
    n_data = n_bits // bps
    slots = n_data // 90
    n_blocks = (slots - 1) // 16 if cfg["pilots"] else 0
    total = n_data + n_blocks * 36
    region = x[off + 90:off + 90 + total]
    region = pl_descramble(region * np.exp(-1j * phase), n)     # derotate then descramble
    data = _depilot(region, n_data, cfg["pilots"])
    llr = np.empty(n_bits)
    llr[0::2] = data.real * 4.0                                 # QPSK Gray: I→even bit, Q→odd
    llr[1::2] = data.imag * 4.0
    out, info = dvb_s2_fec.decode_fecframe(llr, cfg["code_rate"])
    return out, {**cfg, **info}


def _qpsk_modulate(bits: np.ndarray) -> np.ndarray:
    b = np.asarray(bits, dtype=np.float64)
    return ((1.0 - 2.0 * b[0::2]) + 1j * (1.0 - 2.0 * b[1::2])).astype(np.complex64) * _SQRT1_2


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    fails = 0

    # 1) SOF correlation finds the frame start in a noisy stream
    sof = sof_symbols()
    pad_a = (rng.standard_normal(40) + 1j * rng.standard_normal(40)).astype(np.complex64) * 0.3
    pad_b = (rng.standard_normal(40) + 1j * rng.standard_normal(40)).astype(np.complex64) * 0.3
    stream = np.concatenate([pad_a, sof + 0.1 * (rng.standard_normal(26) + 1j * rng.standard_normal(26)), pad_b])
    idx = find_sof(stream)
    print(f"SOF correlation: found at {idx} (expect 40): {'PASS' if idx == 40 else 'FAIL'}")
    fails += idx != 40

    # 2) PLS decode recovers MODCOD + frame size + pilots
    for modcod, short, pilots in ((6, True, False), (19, False, True), (28, True, True)):
        rx = pls_symbols(modcod, short, pilots) + 0.05 * (rng.standard_normal(64) + 1j * rng.standard_normal(64))
        got = decode_pls(rx)
        ok = got and got["modcod"] == modcod and (got["frame"] == ("short" if short else "normal")) and got["pilots"] == pilots
        print(f"PLS decode modcod={modcod} short={short} pilots={pilots} → "
              f"{got and (got['modcod'], got['frame'], got['pilots'], got['modulation'], got['code_rate'])}: "
              f"{'PASS' if ok else 'FAIL'}")
        fails += not ok

    # 3) PL scrambler round-trip
    data = (rng.standard_normal(2000) + 1j * rng.standard_normal(2000)).astype(np.complex64)
    rt = pl_descramble(pl_scramble(data, 0), 0)
    ok = np.allclose(rt, data, atol=1e-4)
    print(f"PL scrambler (Gold) round-trip: {'PASS' if ok else 'FAIL'}")
    fails += not ok
    # Rn must be in {0,1,2,3}
    rn = _rn_sequence(0, 1000)
    fails += not set(np.unique(rn)).issubset({0, 1, 2, 3})

    # 4) FULL DVB-S2 PLFRAME end-to-end (short QPSK 2/3): BBFRAME → BCH → LDPC → QPSK
    #    map → PL scramble → prepend PLHEADER → AWGN → SOF-sync → PLS → descramble →
    #    de-pilot → demap → BCH+LDPC → BBFRAME. Tested with pilots off and on.
    import math
    from app.core.sdr import dvb_s2_fec as s2
    for pilots in (False, True):
        rate, modcod = "2/3", 6
        msg = rng.integers(0, 2, s2._KBCH_SHORT[rate]).astype(np.uint8)
        cw = s2.ldpc_encode(s2.bch_encode(msg, s2._KBCH_SHORT[rate]), rate)   # 16200 bits
        qpsk = _qpsk_modulate(cw)                                             # 8100 symbols
        # insert pilot blocks (unmodulated (1+j)/√2) after every 16 slots if signalled
        if pilots:
            out = []; src = 0; slots_done = 0
            while src < qpsk.size:
                out.extend(qpsk[src:src + 16 * 90]); src += 16 * 90
                if src < qpsk.size:
                    out.extend([(_SQRT1_2 + 1j * _SQRT1_2)] * 36)
            xfec = np.asarray(out, dtype=np.complex64)
        else:
            xfec = qpsk
        scrambled = pl_scramble(xfec, 0)
        plheader = np.concatenate([sof_symbols(), pls_symbols(modcod, True, pilots)])
        frame = np.concatenate([(rng.standard_normal(20) + 1j * rng.standard_normal(20)).astype(np.complex64) * 0.2,
                                plheader, scrambled])
        sigma = 0.18
        frame = frame + sigma * (rng.standard_normal(frame.size) + 1j * rng.standard_normal(frame.size)).astype(np.complex64)
        out, info = decode_dvbs2_plframe(frame, 0)
        ok = out is not None and np.array_equal(out, msg)
        print(f"full DVB-S2 PLFRAME (short QPSK 2/3, pilots={pilots}): {'PASS' if ok else 'FAIL'} ({info})")
        fails += not ok

    print(f"\n{'ALL PASS' if fails == 0 else str(fails)+' FAILED'}")
    raise SystemExit(0 if fails == 0 else 1)
