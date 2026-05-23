"""
dvb_s2_fec.py — DVB-S2 inner LDPC + outer BCH FEC (EN 302 307-1 §5.3).

The FEC that DVB-T's chain doesn't cover. DVB-S2 concatenates an outer t-error BCH
with an inner IRA-LDPC:

  * **BCH** — systematic binary BCH; g(x) = product of the first t short-frame
    polynomials (Table 6b). Encode = polynomial remainder; decode = GF(2^14)
    syndromes → Berlekamp-Massey → Chien (errors are binary, magnitude 1).
  * **LDPC** — irregular repeat-accumulate. Encode accumulates each info bit at the
    parity addresses from the Annex C table (offset by m·q per §5.3.2), then a
    dual-diagonal accumulate. Decode builds H = [A | B(dual-diagonal)] from the same
    table and runs a normalised min-sum belief-propagation decoder.

Tabulated here: the short FECFRAME (nldpc = 16200), rate 2/3 (Table C.6, q=15). The
engine is rate-agnostic — adding a rate is just pasting its Annex C table + q. The
self-test round-trips message → BCH → LDPC → BPSK/AWGN → min-sum LDPC → BCH → message.

Self-test: ``python -m app.core.sdr.dvb_s2_fec``.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

# ── short-frame rate 2/3 parameters (Table 5b / 7b / C.6) ────────────────────
NLDPC = 16200
KLDPC_2_3 = 10800
Q_2_3 = 15
KBCH_2_3 = 10632          # BCH uncoded; Nbch = kldpc = 10800; t = 12 → 168 parity (14·12)
BCH_T = 12

# Annex C.6: parity-bit accumulator addresses, one row per 360-bit info group (30 rows).
LDPC_SHORT_2_3 = [
    [2084, 1613, 1548, 1286, 1460, 3196, 4297, 2481, 3369, 3451, 4620, 2622],
    [122, 1516, 3448, 2880, 1407, 1847, 3799, 3529, 373, 971, 4358, 3108],
    [259, 3399, 929, 2650, 864, 3996, 3833, 107, 5287, 164, 3125, 2350],
    [342, 3529], [4198, 2147], [1880, 4836], [3864, 4910], [243, 1542],
    [3011, 1436], [2167, 2512], [4606, 1003], [2835, 705], [3426, 2365],
    [3848, 2474], [1360, 1743],
    [163, 2536], [2583, 1180], [1542, 509], [4418, 1005], [5212, 5117],
    [2155, 2922], [347, 2696], [226, 4296], [1560, 487], [3926, 1640],
    [149, 2928], [2364, 563], [635, 688], [231, 1684], [1129, 3894],
]

# Annex C.5 — short rate 3/5 (kldpc=9720, q=18, 27 rows).
LDPC_SHORT_3_5 = [
    [5713, 6426, 3596, 1374, 4811, 2182, 544, 3394, 2840, 4310, 771],
    [211, 2208, 723, 1246, 2928, 398, 5739, 265, 5601, 5993, 2615],
    [4730, 5777, 3096, 4282, 6238, 4939, 1119, 6463, 5298, 6320, 4016],
    [2063, 4757, 3157, 5664, 3956, 6045, 563, 4284, 2441, 3412, 6334],
    [2428, 4474, 59, 1721, 736, 2997, 428, 3807, 1513, 4732, 6195],
    [3081, 5139, 3736, 1999, 5889, 4362, 3806, 4534, 5409, 6384, 5809],
    [1622, 2906, 3285, 1257, 5797, 3816, 817, 875, 2311, 3543, 1205],
    [2184, 5415, 1705, 5642, 4886, 2333, 287, 1848, 1121, 3595, 6022],
    [2830, 4069, 5654, 1295, 2951, 3919, 1356, 884, 1786, 396, 4738],
    [2161, 2653], [1380, 1461], [2502, 3707], [3971, 1057], [5985, 6062],
    [1733, 6028], [3786, 1936], [4292, 956], [5692, 3417], [266, 4878],
    [4913, 3247], [4763, 3937], [3590, 2903], [2566, 4215], [5208, 4707],
    [3940, 3388], [5109, 4556], [4908, 4177],
]

# Annex C.7 — short rate 3/4 (kldpc=11880, q=12, 33 rows).
LDPC_SHORT_3_4 = [
    [3198, 478, 4207, 1481, 1009, 2616, 1924, 3437, 554, 683, 1801],
    [2681, 2135], [3107, 4027], [2637, 3373], [3830, 3449], [4129, 2060],
    [4184, 2742], [3946, 1070], [2239, 984], [1458, 3031], [3003, 1328],
    [1137, 1716], [132, 3725], [1817, 638], [1774, 3447], [3632, 1257],
    [542, 3694], [1015, 1945], [1948, 412], [995, 2238], [4141, 1907],
    [2480, 3079], [3021, 1088], [713, 1379], [997, 3903], [2323, 3361],
    [1110, 986], [2532, 142], [1690, 2405], [1298, 1881], [615, 174],
    [1648, 3112], [1415, 2808],
]

# ── short-frame BCH generator polynomials (Table 6b), as bit masks (LSB = x^0) ─
_BCH_SHORT_POLYS = [
    [0, 1, 3, 5, 14], [0, 6, 8, 11, 14], [0, 1, 2, 6, 9, 10, 14],
    [0, 4, 7, 8, 10, 12, 14], [0, 2, 4, 6, 8, 9, 11, 13, 14], [0, 3, 7, 8, 9, 13, 14],
    [0, 2, 5, 6, 7, 10, 11, 13, 14], [0, 5, 8, 9, 10, 11, 14], [0, 1, 2, 3, 9, 10, 14],
    [0, 3, 6, 9, 11, 12, 14], [0, 4, 11, 12, 14], [0, 1, 2, 3, 5, 6, 7, 8, 10, 13, 14],
]
_GF_M = 14
_GF_PRIM = (1 << 14) | (1 << 5) | (1 << 3) | (1 << 1) | 1   # x^14+x^5+x^3+x+1 (= g1 short)


# ── GF(2) polynomial helpers ─────────────────────────────────────────────────
def _poly_from_terms(terms) -> int:
    v = 0
    for t in terms:
        v ^= (1 << t)
    return v


def _gf2_polymul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
    return r


def _bch_generator(t: int) -> int:
    g = 1
    for i in range(t):
        g = _gf2_polymul(g, _poly_from_terms(_BCH_SHORT_POLYS[i]))
    return g                                  # degree 14·t


def _deg(p: int) -> int:
    return p.bit_length() - 1


# ── GF(2^14) tables for BCH decode ───────────────────────────────────────────
_EXP = [0] * (2 * ((1 << _GF_M) - 1))
_LOG = [0] * (1 << _GF_M)
_x = 1
for _i in range((1 << _GF_M) - 1):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & (1 << _GF_M):
        _x ^= _GF_PRIM
for _i in range((1 << _GF_M) - 1, len(_EXP)):
    _EXP[_i] = _EXP[_i - ((1 << _GF_M) - 1)]
_N2 = (1 << _GF_M) - 1


def _gmul(a, b):
    return 0 if (a == 0 or b == 0) else _EXP[_LOG[a] + _LOG[b]]


def _ginv(a):
    return _EXP[_N2 - _LOG[a]]


# ── BCH encode / decode ──────────────────────────────────────────────────────
def bch_encode(msg_bits: np.ndarray, kbch: int = KBCH_2_3, t: int = BCH_T) -> np.ndarray:
    """Systematic binary BCH: append the degree-14t remainder of x^(n-k)·m(x) / g(x)."""
    g = _bch_generator(t)
    nparity = _deg(g)
    # remainder of x^(n-k)·m(x) / g(x): feed the message MSB-first followed by
    # nparity zero bits (the x^(n-k) shift), long-dividing by g over GF(2).
    reg = 0
    msg = np.asarray(msg_bits, dtype=np.uint8)
    for bit in np.concatenate([msg, np.zeros(nparity, dtype=np.uint8)]):
        reg = (reg << 1) | int(bit)
        if reg >> nparity:
            reg ^= g
    parity = reg & ((1 << nparity) - 1)
    pbits = np.array([(parity >> (nparity - 1 - i)) & 1 for i in range(nparity)], dtype=np.uint8)
    return np.concatenate([msg, pbits])


def bch_decode(code_bits: np.ndarray, kbch: int = KBCH_2_3, t: int = BCH_T) -> tuple[np.ndarray, int]:
    """Correct up to t errors. Returns (message_bits, n_corrected | -1 if uncorrectable)."""
    n = len(code_bits)
    c = np.asarray(code_bits, dtype=np.uint8).copy()
    # codeword polynomial value at α^j: bit i is coefficient of x^(n-1-i)
    def at(alpha_pow):
        s = 0
        for i in range(n):
            if c[i]:
                s ^= _EXP[(alpha_pow * (n - 1 - i)) % _N2]
        return s
    synd = [at(j) for j in range(1, 2 * t + 1)]
    if not any(synd):
        return c[:kbch], 0
    # Berlekamp-Massey (binary BCH)
    L, m_ = 0, 1
    Lam = [1] + [0] * (2 * t)
    B = [1] + [0] * (2 * t)
    b = 1
    for r in range(2 * t):
        delta = synd[r]
        for i in range(1, L + 1):
            delta ^= _gmul(Lam[i], synd[r - i])
        if delta == 0:
            m_ += 1
        elif 2 * L <= r:
            T = Lam[:]
            coef = _gmul(delta, _ginv(b))
            for i in range(2 * t + 1 - m_):
                Lam[i + m_] ^= _gmul(coef, B[i])
            L = r + 1 - L; B = T; b = delta; m_ = 1
        else:
            coef = _gmul(delta, _ginv(b))
            for i in range(2 * t + 1 - m_):
                Lam[i + m_] ^= _gmul(coef, B[i])
            m_ += 1
    # Chien search over positions (robust for the shortened code): error at bit p has
    # locator X_p = α^(n-1-p); Λ(X_p^-1) = 0 at an error. Test each position directly.
    errs = []
    for p in range(n):
        e = (_N2 - ((n - 1 - p) % _N2)) % _N2          # exponent of α^-(n-1-p)
        val = 0
        for d in range(L + 1):
            if Lam[d]:
                val ^= _gmul(Lam[d], _EXP[(e * d) % _N2])
        if val == 0:
            errs.append(p)
    if len(errs) != L:
        return c[:kbch], -1
    for p in errs:
        c[p] ^= 1
    if any(at(j) for j in range(1, 2 * t + 1)):
        return c[:kbch], -1
    return c[:kbch], len(errs)


# ── LDPC: H construction, encode, min-sum decode ─────────────────────────────
# rate → (kldpc, q, table). BCH t=12 for all tabulated short rates (Nbch-Kbch=168).
_LDPC_SHORT = {
    "3/5": (9720, 18, LDPC_SHORT_3_5),
    "2/3": (KLDPC_2_3, Q_2_3, LDPC_SHORT_2_3),
    "3/4": (11880, 12, LDPC_SHORT_3_4),
}
_KBCH_SHORT = {"3/5": 9552, "2/3": KBCH_2_3, "3/4": 11712}   # Table 5b


def _ldpc_params(rate: str):
    if rate in _LDPC_SHORT:
        return _LDPC_SHORT[rate]
    raise ValueError(f"DVB-S2 short rate {rate} not tabulated here (have: {sorted(_LDPC_SHORT)})")


def ldpc_encode(info_bits: np.ndarray, rate: str = "2/3") -> np.ndarray:
    """IRA-LDPC systematic encode: accumulate, then dual-diagonal (§5.3.2)."""
    kldpc, q, table = _ldpc_params(rate)
    m = NLDPC - kldpc
    info = np.asarray(info_bits, dtype=np.uint8)
    p = np.zeros(m, dtype=np.uint8)
    for t in range(kldpc):
        L = t // 360
        off = t % 360
        if info[t]:
            for a in table[L]:
                p[(a + off * q) % m] ^= 1
    # dual-diagonal accumulate: p_i ^= p_{i-1}
    for i in range(1, m):
        p[i] ^= p[i - 1]
    return np.concatenate([info, p])


def _build_H(rate: str):
    """Variable/check adjacency of H = [A | B] for the IRA code (B = dual diagonal)."""
    kldpc, q, table = _ldpc_params(rate)
    m = NLDPC - kldpc
    chk_to_var = [[] for _ in range(m)]
    for t in range(kldpc):
        L = t // 360
        off = t % 360
        for a in table[L]:
            chk_to_var[(a + off * q) % m].append(t)
    for j in range(m):                          # dual-diagonal parity part
        chk_to_var[j].append(kldpc + j)
        if j >= 1:
            chk_to_var[j].append(kldpc + j - 1)
    return chk_to_var, kldpc, m


def ldpc_decode(llr: np.ndarray, rate: str = "2/3", max_iter: int = 50) -> np.ndarray:
    """Normalised min-sum BP decode. ``llr`` is the per-bit channel LLR (sign = bit,
    +ve ⇒ 0). Returns the hard-decided codeword bits."""
    chk_to_var, kldpc, m = _build_H(rate)
    llr = np.asarray(llr, dtype=np.float64)
    # edge lists
    edges_c, edges_v = [], []
    for j, vs in enumerate(chk_to_var):
        for v in vs:
            edges_c.append(j); edges_v.append(v)
    edges_c = np.asarray(edges_c); edges_v = np.asarray(edges_v)
    msg_vc = llr[edges_v].copy()                 # variable→check messages
    alpha = 0.75                                 # min-sum normalisation
    # group edges by check once (stable sort → contiguous per-check segments)
    order = np.argsort(edges_c, kind="stable")
    ec = edges_c[order]
    seg_start = [0] + list(np.nonzero(np.diff(ec))[0] + 1) + [len(ec)]
    segs = [(seg_start[i], seg_start[i + 1]) for i in range(len(seg_start) - 1)]
    msg_cv = np.zeros_like(msg_vc)
    for _ in range(max_iter):
        vals = msg_vc[order]
        gsign = np.where(vals >= 0, 1.0, -1.0)
        agv = np.abs(vals)
        cv_sorted = np.empty_like(vals)
        for a, b in segs:
            gs = gsign[a:b]; ga = agv[a:b]
            sgn_all = np.prod(gs)
            si = np.argsort(ga)
            min1 = ga[si[0]]
            min2 = ga[si[1]] if si.size > 1 else min1
            mag = np.where(np.arange(b - a) == si[0], min2, min1)
            cv_sorted[a:b] = alpha * (sgn_all * gs) * mag
        msg_cv[order] = cv_sorted
        # variable→check + total
        tot = llr.copy()
        np.add.at(tot, edges_v, msg_cv)
        msg_vc = tot[edges_v] - msg_cv
        hard = (tot < 0).astype(np.uint8)
        # syndrome check (vectorised per check via the segments)
        hc = hard[edges_v][order]
        synd_ok = True
        for a, b in segs:
            if int(hc[a:b].sum()) & 1:
                synd_ok = False; break
        if synd_ok:
            break
    return hard


def decode_fecframe(llr: np.ndarray, rate: str = "2/3") -> tuple[Optional[np.ndarray], dict]:
    """LDPC min-sum + BCH on a short FECFRAME's soft bits → BBFRAME bits (or None)."""
    kldpc, _, _ = _ldpc_params(rate)
    kbch = _KBCH_SHORT[rate]
    cw = ldpc_decode(llr, rate)
    info = cw[:kldpc]                            # = BCH codeword (Nbch bits)
    msg, nerr = bch_decode(info, kbch, BCH_T)
    if nerr < 0:
        return None, {"ldpc": "done", "bch": "uncorrectable"}
    return msg, {"bch_corrected": nerr, "rate": rate}


if __name__ == "__main__":
    import math
    rng = np.random.default_rng(0)
    fails = 0

    # 1) BCH round-trip: inject up to t errors, recover
    for nerr in (0, 6, 12, 13):
        msg = rng.integers(0, 2, KBCH_2_3).astype(np.uint8)
        cw = bch_encode(msg)
        bad = cw.copy()
        for pos in rng.choice(len(cw), nerr, replace=False):
            bad[pos] ^= 1
        dec, got = bch_decode(bad)
        ok = (np.array_equal(dec, msg) and nerr <= 12) or (got == -1 and nerr > 12)
        print(f"BCH t=12, {nerr} errors → corrected={got}: {'PASS' if ok else 'FAIL'}")
        fails += not ok

    # 2-4) per tabulated rate: valid codeword (H·c=0), LDPC AWGN correction, and the
    #      full FECFRAME round-trip (message → BCH → LDPC → AWGN → LDPC → BCH → message).
    #      Min-sum on the short frame sits ~1–2 dB off sum-product → test with margin.
    ebno_db = 5.0
    for rate in ("3/5", "2/3", "3/4"):
        kldpc, _, _ = _ldpc_params(rate)
        kbch = _KBCH_SHORT[rate]
        info = rng.integers(0, 2, kldpc).astype(np.uint8)
        cw = ldpc_encode(info, rate)
        chk_to_var, _, _ = _build_H(rate)
        valid = all(np.bitwise_xor.reduce(cw[vs]) == 0 for vs in chk_to_var)
        r_lin = eval(rate.replace("/", "/"))
        sigma = math.sqrt(1.0 / (2.0 * r_lin * 10 ** (ebno_db / 10)))
        msg = rng.integers(0, 2, kbch).astype(np.uint8)
        fec = ldpc_encode(bch_encode(msg, kbch), rate)
        rx = (1.0 - 2.0 * fec.astype(np.float64)) + sigma * rng.standard_normal(fec.size)
        out, dinfo = decode_fecframe(2.0 * rx / (sigma ** 2), rate)
        rt = out is not None and np.array_equal(out, msg)
        print(f"DVB-S2 short {rate}: valid-codeword={valid}, FECFRAME round-trip @ {ebno_db} dB="
              f"{'PASS' if rt else 'FAIL'} ({dinfo})")
        fails += (not valid) + (not rt)

    print(f"\n{'ALL PASS' if fails == 0 else str(fails)+' FAILED'}")
    raise SystemExit(0 if fails == 0 else 1)
