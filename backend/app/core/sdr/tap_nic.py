"""
tap_nic.py — turn any SDR into a network interface card (NIC) over a TAP/TUN.

The OS sees a normal kernel network interface (``ares-nic0`` …); under it, Ares
bridges that interface's frames to RF with the in-process software modem
(:mod:`app.core.sdr.packet_modem`) driving any registry SDR driver
(:mod:`app.core.sdr.drivers`). No GNU Radio ``gr-tunnel`` flowgraph, no kernel
module beyond the stock ``tun`` driver — same "everything bundled" rule the DF
pipeline follows.

  * **TAP** (layer 2) presents an Ethernet NIC: it carries whole Ethernet
    frames, can be bridged, and ARP/DHCP just work.
  * **TUN** (layer 3) presents a point-to-point IP link: lighter, no Ethernet
    header, good for a raw IP tunnel between two radios.

Data path::

      kernel ──▶ /dev/net/tun ──▶ TX thread ──▶ modem.modulate ──▶ sdr.transmit
      kernel ◀── /dev/net/tun ◀── RX thread ◀── modem.demodulate ◀── sdr.read_iq

A driver that can transmit (``capabilities.tx_capable``) gives a full-duplex
NIC; a receive-only SDR still gives a *monitor* NIC that injects demodulated
frames into the interface (sniff a link, feed a tap to tcpdump/wireshark).

Bringing the interface up and assigning an address needs ``CAP_NET_ADMIN``
(run the backend with the capability, or as root). Everything degrades with a
clear error otherwise — opening ``/dev/net/tun`` and the modem itself need no
privilege beyond access to that device node.

Linux-only (it speaks the Linux ``TUNSETIFF`` ioctl). On other platforms NIC
creation raises a clear, caught error and the rest of Ares is unaffected.
"""
from __future__ import annotations

import fcntl
import logging
import os
import struct
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .packet_modem import PacketModem, ModemConfig

log = logging.getLogger(__name__)

# Linux <linux/if_tun.h> / <linux/if.h> constants
_TUNSETIFF = 0x400454CA
_IFF_TUN = 0x0001
_IFF_TAP = 0x0002
_IFF_NO_PI = 0x1000          # no 4-byte packet-info prefix on each frame
_TUN_CLONE = "/dev/net/tun"
_DEFAULT_MTU = 1400          # leave headroom under the modem's 2048-byte max frame


def tap_supported() -> tuple[bool, str]:
    """Whether this host can actually create a TAP/TUN interface — probed, not
    guessed: open /dev/net/tun and try a transient TUNSETIFF, then close. R/W
    on the device node isn't enough; the ioctl itself needs CAP_NET_ADMIN."""
    if os.name != "posix" or not os.path.exists(_TUN_CLONE):
        return False, f"{_TUN_CLONE} not present (TAP/TUN is Linux-only)"
    if not os.access(_TUN_CLONE, os.R_OK | os.W_OK):
        return False, f"no read/write access to {_TUN_CLONE} (need CAP_NET_ADMIN or root)"
    try:
        fd = os.open(_TUN_CLONE, os.O_RDWR)
    except OSError as e:
        return False, f"cannot open {_TUN_CLONE}: {e}"
    try:
        ifr = struct.pack("16sH", b"ares-probe%d", _IFF_TAP | _IFF_NO_PI)
        fcntl.ioctl(fd, _TUNSETIFF, ifr)
        return True, "ok"
    except OSError as e:
        return False, f"TUNSETIFF not permitted ({e}); run the backend with CAP_NET_ADMIN or as root"
    finally:
        os.close(fd)


class TapDevice:
    """A Linux TAP (layer-2) or TUN (layer-3) virtual interface."""

    def __init__(self, name: str = "ares-nic%d", mode: str = "tap",
                 mtu: int = _DEFAULT_MTU):
        ok, why = tap_supported()
        if not ok:
            raise RuntimeError(why)
        self.mode = "tun" if mode.lower() == "tun" else "tap"
        flags = (_IFF_TUN if self.mode == "tun" else _IFF_TAP) | _IFF_NO_PI
        self._fd = os.open(_TUN_CLONE, os.O_RDWR)
        try:
            ifr = struct.pack("16sH", name.encode()[:15], flags)
            res = fcntl.ioctl(self._fd, _TUNSETIFF, ifr)
        except OSError as e:
            os.close(self._fd)
            raise RuntimeError(f"TUNSETIFF failed ({e}); need CAP_NET_ADMIN/root") from e
        self.ifname = res[:16].rstrip(b"\x00").decode(errors="replace")
        self.mtu = int(mtu)
        self._closed = False
        try:
            self._ip("link", "set", "dev", self.ifname, "mtu", str(self.mtu))
        except Exception:
            pass

    # ── frame I/O ─────────────────────────────────────────────────────────────
    def read(self, n: int = 4096) -> bytes:
        """Read one frame the kernel handed us (blocking)."""
        return os.read(self._fd, n)

    def write(self, frame: bytes) -> int:
        return os.write(self._fd, frame)

    def fileno(self) -> int:
        return self._fd

    # ── interface config (best-effort; needs CAP_NET_ADMIN) ──────────────────
    def _ip(self, *args: str) -> None:
        subprocess.run(["ip", *args], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def configure(self, ip_cidr: Optional[str] = None, up: bool = True) -> Optional[str]:
        """Assign an address and/or bring the link up. Returns an error string
        on failure (caller surfaces it) or None on success."""
        try:
            if ip_cidr:
                self._ip("addr", "add", ip_cidr, "dev", self.ifname)
            if up:
                self._ip("link", "set", "dev", self.ifname, "up")
            return None
        except subprocess.CalledProcessError as e:
            return (e.stderr or b"").decode(errors="replace").strip() or "ip command failed"
        except Exception as e:
            return str(e)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                os.close(self._fd)
            except Exception:
                pass


@dataclass
class NicStats:
    tx_frames: int = 0
    tx_bytes: int = 0
    tx_errors: int = 0
    rx_frames: int = 0
    rx_bytes: int = 0
    rx_crc_drops: int = 0          # candidates that failed CRC (rough; modem drops silently)
    last_tx_t: float = 0.0
    last_rx_t: float = 0.0
    started_t: float = field(default_factory=time.time)


class SdrNic:
    """Bridge one SDR driver ⇄ one TAP/TUN interface via the packet modem."""

    def __init__(self, *, nic_id: str, name: str, driver_id: str,
                 driver_args: dict, mode: str = "tap",
                 ifname: str = "ares-nic%d", ip_cidr: Optional[str] = None,
                 frequency_hz: float = 433.92e6, sample_rate_hz: float = 2.4e6,
                 gain_db: Optional[float] = 40.0, sps: int = 8,
                 read_samples: int = 1 << 16, mtu: int = _DEFAULT_MTU):
        self.id = nic_id
        self.name = name
        self.driver_id = driver_id
        self.driver_args = dict(driver_args or {})
        self.mode = "tun" if mode.lower() == "tun" else "tap"
        self.requested_ifname = ifname
        self.ip_cidr = ip_cidr
        self.frequency_hz = float(frequency_hz)
        self.sample_rate_hz = float(sample_rate_hz)
        self.gain_db = gain_db
        self.sps = int(sps)
        self.read_samples = int(read_samples)
        self.mtu = int(mtu)

        self._driver = None
        self._tap: Optional[TapDevice] = None
        self._tx_modem = PacketModem(ModemConfig(sps=self.sps))
        self._rx_modem = PacketModem(ModemConfig(sps=self.sps))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.stats = NicStats()
        self.status = "stopped"          # stopped | starting | up | error
        self.last_error = ""
        self.ifname = ""
        self.tx_capable = False
        self.config_warning = ""

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.status = "starting"
        from app.core.sdr import drivers
        # 1) open the radio
        kwargs = dict(self.driver_args)
        drv = drivers.create(self.driver_id, **kwargs)
        drv.open()
        drv.set_sample_rate(self.sample_rate_hz)
        drv.set_frequency(self.frequency_hz)
        if self.gain_db is not None:
            try:
                drv.set_gain(float(self.gain_db))
            except Exception:
                pass
        self._driver = drv
        self.tx_capable = bool(getattr(drv.capabilities, "tx_capable", False))
        # 2) create the kernel interface
        self._tap = TapDevice(self.requested_ifname, self.mode, self.mtu)
        self.ifname = self._tap.ifname
        warn = self._tap.configure(self.ip_cidr, up=True)
        if warn:
            self.config_warning = warn
            log.warning("nic %s: interface config: %s", self.ifname, warn)
        # 3) spin RX (always) + TX (if the radio can transmit) threads
        self._stop.clear()
        self._threads = [threading.Thread(target=self._rx_loop, name=f"nic-rx:{self.id}", daemon=True)]
        if self.tx_capable:
            self._threads.append(threading.Thread(target=self._tx_loop, name=f"nic-tx:{self.id}", daemon=True))
        for t in self._threads:
            t.start()
        self.status = "up"
        log.info("nic %s up: if=%s mode=%s driver=%s %.4f MHz @ %.2f Msps tx=%s",
                 self.id, self.ifname, self.mode, self.driver_id,
                 self.frequency_hz / 1e6, self.sample_rate_hz / 1e6, self.tx_capable)

    def stop(self) -> None:
        self._stop.set()
        if self._tap is not None:
            self._tap.close()            # unblocks the RX/TX os.read on the fd
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:
                pass
        self._driver = None
        self._tap = None
        self.status = "stopped"
        log.info("nic %s stopped", self.id)

    # ── TX: kernel frame → modem → radio ─────────────────────────────────────
    def _tx_loop(self) -> None:
        assert self._tap and self._driver
        while not self._stop.is_set():
            try:
                frame = self._tap.read(self.mtu + 64)
            except OSError:
                break                    # fd closed on stop()
            if not frame:
                continue
            try:
                wave = self._tx_modem.modulate(frame)
                self._driver.transmit(wave)
                self.stats.tx_frames += 1
                self.stats.tx_bytes += len(frame)
                self.stats.last_tx_t = time.time()
            except Exception as e:
                self.stats.tx_errors += 1
                self.last_error = f"tx: {type(e).__name__}: {e}"
                log.debug("nic %s tx error: %s", self.id, e, exc_info=True)

    # ── RX: radio → modem → kernel frame ─────────────────────────────────────
    def _rx_loop(self) -> None:
        assert self._tap and self._driver
        while not self._stop.is_set():
            try:
                iqf = self._driver.read_iq(self.read_samples)
                frames = self._rx_modem.demodulate(np.asarray(iqf.samples))
            except Exception as e:
                self.last_error = f"rx: {type(e).__name__}: {e}"
                log.debug("nic %s rx error: %s", self.id, e, exc_info=True)
                time.sleep(0.2)
                continue
            for fr in frames:
                try:
                    self._tap.write(fr)
                    self.stats.rx_frames += 1
                    self.stats.rx_bytes += len(fr)
                    self.stats.last_rx_t = time.time()
                except OSError:
                    break

    # ── reporting ─────────────────────────────────────────────────────────────
    def public(self) -> dict:
        s = self.stats
        return {
            "id": self.id, "name": self.name, "status": self.status,
            "ifname": self.ifname, "mode": self.mode,
            "driver_id": self.driver_id, "tx_capable": self.tx_capable,
            "frequency_hz": self.frequency_hz, "sample_rate_hz": self.sample_rate_hz,
            "gain_db": self.gain_db, "sps": self.sps, "mtu": self.mtu,
            "ip_cidr": self.ip_cidr,
            "bitrate_bps": round(self._tx_modem.bits_per_second(self.sample_rate_hz)),
            "last_error": self.last_error, "config_warning": self.config_warning,
            "stats": {
                "tx_frames": s.tx_frames, "tx_bytes": s.tx_bytes, "tx_errors": s.tx_errors,
                "rx_frames": s.rx_frames, "rx_bytes": s.rx_bytes,
                "last_tx_t": s.last_tx_t, "last_rx_t": s.last_rx_t,
                "uptime_s": round(time.time() - s.started_t, 1),
            },
        }


class NicManager:
    """Process-wide registry of live SDR NICs (runtime only — not persisted)."""

    def __init__(self) -> None:
        self._nics: dict[str, SdrNic] = {}
        self._lock = threading.Lock()

    def supported(self) -> dict:
        ok, why = tap_supported()
        return {"supported": ok, "reason": why}

    def list(self) -> list[dict]:
        with self._lock:
            return [n.public() for n in self._nics.values()]

    def get(self, nic_id: str) -> Optional[SdrNic]:
        return self._nics.get(nic_id)

    def create(self, payload: dict) -> dict:
        ok, why = tap_supported()
        if not ok:
            raise RuntimeError(why)
        nic_id = payload.get("id") or uuid.uuid4().hex[:10]
        if nic_id in self._nics:
            raise ValueError(f"nic id {nic_id!r} already exists")
        nic = SdrNic(
            nic_id=nic_id,
            name=payload.get("name") or f"sdr-nic-{nic_id}",
            driver_id=payload.get("driver_id") or "synthetic",
            driver_args=payload.get("driver_args") or {},
            mode=payload.get("mode") or "tap",
            ifname=payload.get("ifname") or "ares-nic%d",
            ip_cidr=payload.get("ip_cidr"),
            frequency_hz=float(payload.get("frequency_hz") or 433.92e6),
            sample_rate_hz=float(payload.get("sample_rate_hz") or 2.4e6),
            gain_db=(None if payload.get("gain_db") in (None, "") else float(payload["gain_db"])),
            sps=int(payload.get("sps") or 8),
            read_samples=int(payload.get("read_samples") or (1 << 16)),
            mtu=int(payload.get("mtu") or _DEFAULT_MTU),
        )
        try:
            nic.start()
        except Exception as e:
            nic.status = "error"
            nic.last_error = f"{type(e).__name__}: {e}"
            try:
                nic.stop()
            except Exception:
                pass
            raise
        with self._lock:
            self._nics[nic_id] = nic
        return nic.public()

    def remove(self, nic_id: str) -> bool:
        with self._lock:
            nic = self._nics.pop(nic_id, None)
        if nic is None:
            return False
        try:
            nic.stop()
        except Exception:
            log.debug("nic %s stop error", nic_id, exc_info=True)
        return True

    def stop_all(self) -> None:
        for nid in list(self._nics.keys()):
            self.remove(nid)


nic_manager = NicManager()
