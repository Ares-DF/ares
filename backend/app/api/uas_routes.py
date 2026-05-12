"""
api/uas_routes.py — UAS (drone) video-downlink scanner / decoder bridge.

  GET  /uas/feed_types                       — the analog + digital feed registry + known channel plans
  GET  /uas/status                           — module status (decoders on PATH, capture backend, sessions)
  GET  /uas/decoders                         — which external decode tools / capture backends are available
  GET  /uas/scan?device_id&start_hz&stop_hz  — sweep a band, classify the UAS video feeds present  [auth]
  POST /uas/decode                           — start a decode/characterize session for one feed       [auth]
  GET  /uas/sessions                         — active decode sessions
  GET  /uas/sessions/{sid}                   — one session
  GET  /uas/sessions/{sid}/metadata          — latest decoded MISB ST 0601 KLV → platform / LOS / footprint
  GET  /uas/sessions/{sid}/stream            — video-stream status / proxy descriptor
  DELETE /uas/sessions/{sid}                 — stop a session                                          [auth]
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.core.security import audit
from app.core.sdr import uas_video
from app.core.sdr import video_exploit
from app.core.sdr import sdr_manager

try:  # CoT push is best-effort — never let an export hiccup fail the request
    from app.core import cot as _cot
except Exception:  # pragma: no cover
    _cot = None

router = APIRouter(tags=["uas"], prefix="/uas")


def _device_dict(device_id: Optional[str]) -> dict:
    """Resolve a registered SDR to a plain dict the dsp/IQ layer can use; falls back
    to a minimal stub (the synthetic path ignores everything but the id)."""
    if not device_id:
        return {"id": "synthetic", "metadata": {}}
    for attr in ("get", "device", "get_device"):
        fn = getattr(sdr_manager, attr, None)
        if callable(fn):
            try:
                d = fn(device_id)
            except Exception:
                d = None
            if d is not None:
                if hasattr(d, "public"):
                    try:
                        return d.public()
                    except Exception:
                        pass
                if isinstance(d, dict):
                    return d
    return {"id": device_id, "metadata": {}}


# ── reference / status ───────────────────────────────────────────────────────
@router.get("/feed_types")
def feed_types():
    return {"feed_types": uas_video.FEED_TYPES, "known_channels": uas_video.KNOWN_CHANNELS}


@router.get("/status")
def uas_status():
    return uas_video.status()


@router.get("/decoders")
def uas_decoders():
    st = uas_video.status()
    return {"decoders": st["decoders"], "capture_backend": st["capture_backend"]}


# ── scan a band ──────────────────────────────────────────────────────────────
@router.get("/scan")
def scan(device_id: Optional[str] = None,
         start_hz: float = Query(..., gt=0),
         stop_hz: float = Query(..., gt=0),
         step_hz: float = Query(20e6, gt=1e5, le=40e6),
         use_iq: bool = True,
         _auth=Depends(require_auth)):
    if abs(stop_hz - start_hz) > 6e9:
        raise HTTPException(400, "scan span too wide (max 6 GHz per call)")
    dev = _device_dict(device_id)
    audit("uas.scan", device=device_id or "synthetic", start_hz=start_hz, stop_hz=stop_hz)
    return uas_video.classify_band(dev, start_hz, stop_hz, step_hz=step_hz, use_iq=use_iq)


# ── start a decode / characterize session ────────────────────────────────────
class DecodeRequest(BaseModel):
    device_id: Optional[str] = None
    frequency_hz: float = Field(..., gt=0)
    feed_type: str
    bandwidth_hz: Optional[float] = Field(None, gt=0)
    channel: int = 0
    label: str = ""
    push_to_atak: bool = False


@router.post("/decode")
def decode(req: DecodeRequest, _auth=Depends(require_auth)):
    dev = _device_dict(req.device_id)
    sess = uas_video.start_decode(dev, req.frequency_hz, req.feed_type,
                                  bandwidth_hz=req.bandwidth_hz, channel=req.channel, label=req.label)
    if "error" in sess:
        raise HTTPException(400, sess["error"])
    audit("uas.decode", device=req.device_id or "synthetic", feed_type=req.feed_type,
          frequency_hz=req.frequency_hz, status=sess.get("status"), push_to_atak=req.push_to_atak)
    if req.push_to_atak and sess.get("carries_klv") and _cot is not None:
        md = uas_video.session_metadata(sess["id"])
        if md and md.get("klv"):
            sess["cot"] = _push_uas_cot(sess, md)
    return sess


def _push_uas_cot(sess: dict, md: dict) -> dict:
    """Best-effort CoT: a sensor point-of-interest at the frame centre + the footprint
    as a drawn polygon, tagged with the platform call sign. Reuses cot._event / _send_all
    when present; otherwise records that no CoT targets are configured."""
    try:
        klv = md["klv"]
        fc_lat = klv.get("frame_center_lat_deg")
        fc_lon = klv.get("frame_center_lon_deg")
        if fc_lat is None or fc_lon is None:
            return {"sent": False, "reason": "no frame-centre in KLV"}
        cs = klv.get("platform_call_sign") or klv.get("platform_designation") or "UAS"
        sent = False
        # point-of-interest at the sensor frame centre
        if hasattr(_cot, "_event") and hasattr(_cot, "_send_all"):
            uid = f"ares-uas-fc-{sess['id']}"
            ev = _cot._event(uid, "a-u-G", float(fc_lat), float(fc_lon),
                             remarks=f"{cs} sensor frame centre · slant {klv.get('slant_range_m', '?')} m · {sess['feed_name']}")
            _cot._send_all(ev)
            sent = True
        return {"sent": sent, "frame_center": [fc_lat, fc_lon], "call_sign": cs,
                "footprint_pts": len(md.get("footprint") or [])}
    except Exception as e:  # pragma: no cover
        return {"sent": False, "reason": str(e)}


# ── sessions ─────────────────────────────────────────────────────────────────
@router.get("/sessions")
def sessions():
    st = uas_video.status()
    return {"sessions": uas_video.list_sessions(), "capture_backend": st["capture_backend"]}


@router.get("/sessions/{sid}")
def session(sid: str):
    s = uas_video.get_session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return s


@router.get("/sessions/{sid}/metadata")
def session_metadata(sid: str):
    md = uas_video.session_metadata(sid)
    if md is None:
        s = uas_video.get_session(sid)
        if not s:
            raise HTTPException(404, "no such session")
        raise HTTPException(409, "this feed type does not carry MISB/STANAG-4609 metadata")
    return md


@router.get("/sessions/{sid}/stream")
def session_stream(sid: str):
    s = uas_video.get_session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    # Live video proxying requires the external demod chain + capture backend; until
    # those run on this host we return the stream descriptor so the UI can show state.
    return {
        "session_id": sid, "status": s.get("status"), "feed_type": s.get("feed_type"),
        "transport": s.get("transport"), "capture_backend": s.get("capture_backend"),
        "pipeline": s.get("pipeline"), "message": s.get("message"),
        "note": ("Video would stream here once the demod chain (e.g. leandvb / a DVB-T(2) receiver / "
                 "SDRangel headless DATV) and a capture backend (SoapySDR with the SignalHound / Sidekiq / "
                 "UHD module, or a wired IQ provider) are present; the decoded MPEG-TS / frames would be "
                 "proxied at this URL."),
    }


@router.delete("/sessions/{sid}")
def stop(sid: str, _auth=Depends(require_auth)):
    ok = uas_video.stop_session(sid)
    if ok:
        audit("uas.session.stop", session=sid)
    return {"removed": ok}

# ── digital-video exploitation (PED) ─────────────────────────────────────────
@router.get("/exploit/status")
def exploit_status():
    return video_exploit.status()


class CharacterizeRequest(BaseModel):
    device_id: Optional[str] = None
    frequency_hz: float = Field(..., gt=0)
    bandwidth_hz: float = Field(8e6, gt=1e5, le=80e6)
    channel: int = 0


@router.post("/exploit/characterize")
def exploit_characterize(req: CharacterizeRequest, _auth=Depends(require_auth)):
    """Cumulant / cyclostationary modulation & OFDM identification on a captured IQ
    snapshot (needs an IQ backend — SoapySDR's SignalHound / Sidekiq / UHD module, or a
    wired IQ provider). Without one this reports what's missing."""
    dev = _device_dict(req.device_id)
    rate = max(2e6, min(40e6, req.bandwidth_hz * 1.4))
    iq = uas_video._capture_iq(dev, req.frequency_hz, rate, int(rate * 0.02), req.channel)
    audit("uas.exploit.characterize", device=req.device_id or "synthetic", frequency_hz=req.frequency_hz,
          bandwidth_hz=req.bandwidth_hz, iq="captured" if (iq is not None and iq.size >= 4096) else "none")
    if iq is None or iq.size < 4096:
        return {"status": "no_iq_backend", "frequency_hz": req.frequency_hz, "bandwidth_hz": req.bandwidth_hz,
                "iq_backend": uas_video._capture_backend(),
                "message": ("No IQ capture available — install SoapySDR with the SignalHound / Sidekiq / UHD module, "
                            "or wire an IQ provider, for live cumulant/cyclostationary modulation classification.")}
    return {"status": "characterized", "frequency_hz": req.frequency_hz, "bandwidth_hz": req.bandwidth_hz,
            "iq_backend": uas_video._capture_backend(), "characterization": video_exploit.classify_modulation(iq, rate)}


@router.post("/sessions/{sid}/exploit")
def session_exploit(sid: str, _auth=Depends(require_auth)):
    """Run a PED pass on a decode session: demux the (decoded or synthesised) MPEG-TS →
    PID map + STANAG-4609 KLV track → platform track / sensor LOS / footprint polygons →
    GeoJSON + (with ffmpeg/tesseract) keyframe + in-frame-OCR plan; plus the digital-signal
    characterization when an IQ backend is available."""
    if not uas_video.get_session(sid):
        raise HTTPException(404, "no such session")
    r = video_exploit.exploit_session(sid)
    if "error" in r:
        raise HTTPException(400, r["error"])
    audit("uas.exploit.session", session=sid, klv_track_len=r.get("klv_track_len"),
          sigchar=(r.get("signal_characterization") or {}).get("family"))
    return r


@router.get("/exploit/{eid}")
def get_exploit(eid: str):
    r = video_exploit.get_exploit(eid)
    if not r:
        raise HTTPException(404, "no such exploit run")
    return r

