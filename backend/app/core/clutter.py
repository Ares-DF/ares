"""
clutter.py — land-cover (clutter) integration for the propagation engine (Workstream A).

Reads the ESA WorldCover 10 m GeoTIFF tiles from an installed ``clutter`` data pack
(see :mod:`app.core.pack_builder.build_clutter_pack`) and turns each land-cover
class into a *clutter canopy height* (m, added to the terrain profile so ridgelines
of vegetation/buildings obstruct the path) and an *excess loss* (dB, applied when a
ray enters/leaves a clutter cell — ITU-R P.833-style). This replaces the engine's
single scalar ``clutter_height_m`` with a per-pixel raster — the way ATDI/Atoll/EDX
do it — when a clutter pack is present.

GeoTIFF decoding needs an optional dependency:
  * ``rasterio`` (preferred — windowed reads, no full-tile load)  →  ``pip install rasterio``
  * ``tifffile``  (memmap fallback)                                →  ``pip install tifffile``
If neither is installed, :func:`clutter_profile` returns ``None`` and the engine
falls back to the scalar ``clutter_height_m`` exactly as before — fully optional.
"""
from __future__ import annotations

import logging
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from app.config import PACKS_DIR
from app.core import packs as packs_mod

log = logging.getLogger(__name__)

# ESA WorldCover v200 class → (canopy height m, one-way excess loss dB through the clutter edge)
WORLDCOVER_CLUTTER = {
    10:  (15.0, 12.0),   # tree cover         — forest canopy
    20:  (3.0,  4.0),    # shrubland
    30:  (0.3,  0.0),    # grassland
    40:  (1.5,  1.0),    # cropland
    50:  (12.0, 18.0),   # built-up           — urban canopy
    60:  (0.0,  0.0),    # bare / sparse
    70:  (0.0,  0.0),    # snow & ice
    80:  (0.0,  0.0),    # permanent water
    90:  (0.5,  1.0),    # herbaceous wetland
    95:  (8.0,  10.0),   # mangroves
    100: (0.1,  0.0),    # moss & lichen
    0:   (0.0,  0.0),    # no-data
}

try:
    import rasterio                              # type: ignore
    _BACKEND = "rasterio"
except Exception:
    rasterio = None
    try:
        import tifffile                          # type: ignore
        _BACKEND = "tifffile"
    except Exception:
        tifffile = None
        _BACKEND = None


def backend() -> Optional[str]:
    return _BACKEND


def _clutter_pack_dir() -> Optional[Path]:
    lp = packs_mod.latest_pack("clutter")
    if lp is None:
        return None
    d = Path(lp["path"])
    return d if d.is_dir() else None


def _wc_tile_name(lat: float, lon: float) -> str:
    la3 = int(math.floor(lat / 3.0) * 3)
    lo3 = int(math.floor(lon / 3.0) * 3)
    return f"{'N' if la3 >= 0 else 'S'}{abs(la3):02d}{'E' if lo3 >= 0 else 'W'}{abs(lo3):03d}"


@lru_cache(maxsize=8)
def _open_tile(path_str: str):
    if _BACKEND == "rasterio":
        try:
            return ("rasterio", rasterio.open(path_str))
        except Exception:
            return None
    if _BACKEND == "tifffile":
        try:
            arr = tifffile.memmap(path_str)
            return ("tifffile", arr)
        except Exception:
            return None
    return None


def _sample_class(lat: float, lon: float, pack_dir: Path) -> Optional[int]:
    """Land-cover class code at (lat, lon) from the covering WorldCover tile, or None."""
    name = _wc_tile_name(lat, lon)
    path = pack_dir / f"{name}.tif"
    if not path.is_file():
        return None
    h = _open_tile(str(path))
    if h is None:
        return None
    backend, obj = h
    try:
        if backend == "rasterio":
            for v in obj.sample([(lon, lat)]):
                return int(v[0])
        else:  # tifffile memmap — assume the WorldCover convention: 36000×36000, SW corner at (3°-grid)
            la3 = math.floor(lat / 3.0) * 3
            lo3 = math.floor(lon / 3.0) * 3
            n = obj.shape[0]
            col = int((lon - lo3) / 3.0 * n)
            row = int((la3 + 3.0 - lat) / 3.0 * n)        # row 0 = north edge
            col = min(max(0, col), n - 1)
            row = min(max(0, row), obj.shape[0] - 1)
            return int(obj[row, col])
    except Exception:
        return None
    return None


def clutter_profile(lat1: float, lon1: float, lat2: float, lon2: float, n: int) -> Optional[np.ndarray]:
    """Per-sample clutter canopy heights (m) along the great-circle path, length ``n``.
    Returns ``None`` if there's no clutter pack installed *or* no GeoTIFF backend —
    the caller then keeps using the scalar ``clutter_height_m``."""
    if _BACKEND is None:
        return None
    pack_dir = _clutter_pack_dir()
    if pack_dir is None:
        return None
    heights = np.zeros(n, dtype=float)
    any_hit = False
    for i in range(n):
        f = i / (n - 1) if n > 1 else 0.0
        lat = lat1 + (lat2 - lat1) * f          # adequate for the few-km radials we sample
        lon = lon1 + (lon2 - lon1) * f
        c = _sample_class(lat, lon, pack_dir)
        if c is None:
            continue
        any_hit = True
        heights[i] = WORLDCOVER_CLUTTER.get(c, (0.0, 0.0))[0]
    return heights if any_hit else None


def clutter_at(lat: float, lon: float) -> Optional[tuple[int, float, float]]:
    """``(class_code, canopy_height_m, excess_loss_db)`` at a point, or None."""
    if _BACKEND is None:
        return None
    pack_dir = _clutter_pack_dir()
    if pack_dir is None:
        return None
    c = _sample_class(lat, lon, pack_dir)
    if c is None:
        return None
    h, l = WORLDCOVER_CLUTTER.get(c, (0.0, 0.0))
    return c, h, l


def status() -> dict:
    pd = _clutter_pack_dir()
    return {"backend": _BACKEND, "pack_installed": pd is not None,
            "pack": str(pd) if pd else None,
            "hint": None if _BACKEND else "install `rasterio` (or `tifffile`) to enable per-pixel clutter from WorldCover packs"}
