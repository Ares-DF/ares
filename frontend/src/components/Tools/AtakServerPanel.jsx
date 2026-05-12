/**
 * AtakServerPanel — the "ATAK / Server" console (Workstream A/C).
 *
 * A modal opened from the header (the server/antenna button next to Run). Shows:
 *   - server identity / GPU / online-offline / disk  (GET /api/v1/server/info)
 *   - offline data packs: terrain / osm / buildings / clutter / imagery, with a
 *     "download region pack" form (POST /api/v1/packs/download) and a job poller
 *   - radio templates available to the ATAK plugin (GET /api/v1/atak/templates)
 *   - a note on connecting an ATAK device to this server.
 *
 * This is the web/desktop counterpart of the ATAK plugin's Settings tab — the
 * offline-ops console. (When the frontend is served by the same Ares process,
 * "server" = this backend; a remote-server picker can be added later.)
 */
import { useEffect, useState, useCallback } from 'react'
import { X, RefreshCw, Download, Trash2, HardDrive, Wifi, WifiOff, Cpu, Radio, Square, ShieldCheck } from 'lucide-react'
import {
  getServerInfo, getNetStatus, listDataPacks, downloadDataPack, listPackJobs,
  deleteDataPack, verifyDataPack, listAtakTemplates, setAtakEnabled, getCotTargets, setCotTargets,
} from '../../api/client'

const PACK_LAYERS = ['terrain', 'osm', 'buildings', 'clutter', 'imagery']

function fmtBytes(n) {
  if (!n && n !== 0) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0; let v = n
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`
}

function Section({ title, right, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#8b949e', textTransform: 'uppercase', letterSpacing: 0.8, flex: 1 }}>{title}</div>
        {right}
      </div>
      {children}
    </div>
  )
}

const inputStyle = { background: '#0d1117', border: '1px solid #30363d', borderRadius: 4, color: '#e6edf3', fontSize: 12, padding: '5px 7px' }
const btn = { display: 'inline-flex', alignItems: 'center', gap: 5, background: '#161b22', color: '#e6edf3', border: '1px solid #30363d', borderRadius: 5, fontSize: 12, padding: '5px 9px', cursor: 'pointer' }

export default function AtakServerPanel({ onClose, mapCenter, incomingBbox, onRequestDrawBbox }) {
  const [info, setInfo] = useState(null)
  const [net, setNet] = useState(null)
  const [packs, setPacks] = useState([])
  const [jobs, setJobs] = useState([])
  const [templates, setTemplates] = useState([])
  const [busy, setBusy] = useState(false)
  const [errText, setErrText] = useState(null)
  // download form
  const [dlLayer, setDlLayer] = useState('terrain')
  const [bbox, setBbox] = useState({ w: '', s: '', e: '', n: '' })
  const [maxZoom, setMaxZoom] = useState(12)
  const [fullPlanet, setFullPlanet] = useState(false)
  // CoT push targets (the ATAK / TAK-server option set lives here)
  const [cotTargets, setCotTargetsState] = useState([])
  const [cotInput, setCotInput] = useState('')
  useEffect(() => { getCotTargets().then(r => setCotTargetsState(r.targets || [])).catch(() => {}) }, [])
  const toggleAtak = async () => {
    try { const r = await setAtakEnabled(!(info?.atak_enabled)); setInfo(prev => prev ? { ...prev, atak_enabled: r.atak_enabled } : prev) }
    catch (e) { setErrText(String(e?.response?.data?.detail || e?.message || e)) }
  }
  const applyCot = async () => {
    setErrText(null)
    const targets = cotInput.split(/[\n,]+/).map(s => s.trim()).filter(Boolean)
    try { const r = await setCotTargets(targets); setCotTargetsState(r.targets || []); setCotInput(''); setErrText(`✓ CoT targets: ${(r.targets || []).join(', ') || '(none)'}`) }
    catch (e) { setErrText(String(e?.response?.data?.detail || e?.message || e)) }
  }

  const refresh = useCallback(async () => {
    setBusy(true); setErrText(null)
    try {
      const [i, n, p, j, t] = await Promise.allSettled([
        getServerInfo(), getNetStatus(), listDataPacks(), listPackJobs(), listAtakTemplates(),
      ])
      if (i.status === 'fulfilled') setInfo(i.value)
      if (n.status === 'fulfilled') setNet(n.value)
      if (p.status === 'fulfilled') setPacks(p.value.packs || [])
      if (j.status === 'fulfilled') setJobs(j.value.jobs || [])
      if (t.status === 'fulfilled') setTemplates(t.value.templates || [])
      if (i.status === 'rejected') setErrText(String(i.reason?.message || i.reason))
    } finally { setBusy(false) }
  }, [])

  useEffect(() => { refresh() }, [refresh])
  // a bbox drawn on the map (via "Draw on map") arrives here → pre-fill the form
  useEffect(() => {
    if (incomingBbox && incomingBbox.length === 4) {
      const [w, s, e, n] = incomingBbox
      setBbox({ w: w.toFixed(4), s: s.toFixed(4), e: e.toFixed(4), n: n.toFixed(4) })
      setFullPlanet(false)
    }
  }, [incomingBbox])
  // poll jobs while any is running
  useEffect(() => {
    if (!jobs.some(j => j.status === 'queued' || j.status === 'running')) return
    const t = setInterval(async () => {
      try { setJobs((await listPackJobs()).jobs || []) } catch { /* ignore */ }
    }, 3000)
    return () => clearInterval(t)
  }, [jobs])

  const useMapBbox = () => {
    if (!mapCenter) return
    // a ~1°×1° box around the current map center
    const { lat, lon } = mapCenter
    setBbox({ w: (lon - 0.5).toFixed(3), s: (lat - 0.5).toFixed(3), e: (lon + 0.5).toFixed(3), n: (lat + 0.5).toFixed(3) })
  }

  const submitDownload = async () => {
    setErrText(null)
    let bb = null
    if (!fullPlanet) {
      const w = parseFloat(bbox.w), s = parseFloat(bbox.s), e = parseFloat(bbox.e), n = parseFloat(bbox.n)
      if ([w, s, e, n].some(isNaN)) { setErrText('Enter a bounding box (or tick "whole planet").'); return }
      bb = [w, s, e, n]
    }
    try {
      await downloadDataPack({ layers: [dlLayer], bbox: bb, ...((dlLayer === 'osm' || dlLayer === 'imagery') ? { max_zoom: Number(maxZoom) } : {}) })
      setJobs((await listPackJobs()).jobs || [])
    } catch (err) { setErrText(String(err?.response?.data?.detail || err?.message || err)) }
  }

  const removePack = async (id) => {
    try { await deleteDataPack(id); setPacks(p => p.filter(x => x.id !== id)) } catch (err) { setErrText(String(err?.message || err)) }
  }

  const checkPack = async (id) => {
    setErrText(null)
    try {
      const r = await verifyDataPack(id, false)
      setErrText(r.ok ? `✓ ${id}: ok — ${r.file_count} files, ${fmtBytes(r.size_bytes_on_disk)}, v${r.pack_version}`
                       : `⚠ ${id}: ${r.issues.join('; ')}`)
    } catch (err) { setErrText(String(err?.response?.data?.detail || err?.message || err)) }
  }

  const online = info?.online
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(1,4,9,0.6)', zIndex: 2000,
                                    display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 'min(720px, 92vw)', maxHeight: '88vh', overflowY: 'auto',
        background: '#0d1117', border: '1px solid #30363d', borderRadius: 8, boxShadow: '0 10px 40px rgba(0,0,0,0.5)', padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16 }}>
          <Radio size={16} color="#58a6ff" />
          <div style={{ fontSize: 15, fontWeight: 700, color: '#e6edf3', marginLeft: 8, flex: 1 }}>ATAK / Server</div>
          <button style={{ ...btn, marginRight: 8 }} onClick={refresh} disabled={busy}><RefreshCw size={13} />{busy ? 'Refreshing…' : 'Refresh'}</button>
          <button style={btn} onClick={onClose}><X size={14} /></button>
        </div>

        {errText && <div style={{ background: '#3d1418', border: '1px solid #f85149', color: '#ff7b72', fontSize: 12, padding: '6px 10px', borderRadius: 5, marginBottom: 14 }}>{errText}</div>}

        {/* Server */}
        <Section title="Server" right={info && (
          <button style={{ ...btn, padding: '3px 9px', background: info.atak_enabled ? '#0f3d2e' : '#3d1414', borderColor: info.atak_enabled ? '#2ea043' : '#f85149' }} onClick={toggleAtak}>
            ATAK integration: {info.atak_enabled ? 'ON' : 'OFF'}
          </button>
        )}>
          {info && info.atak_enabled === false && (
            <div style={{ fontSize: 11, color: '#d29922', marginBottom: 6 }}>ATAK integration is OFF — data packs, radio templates, KMZ export and CoT push are disabled. Turn it on above.</div>
          )}
          {info ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, fontSize: 12, color: '#c9d1d9' }}>
              <span><b>{info.name}</b> v{info.version}</span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                {online ? <Wifi size={13} color="#3fb950" /> : <WifiOff size={13} color="#d29922" />}
                {online ? 'online' : online === false ? 'offline' : 'unknown'} ({info.network_policy})
              </span>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Cpu size={13} color={info.gpu?.available ? '#3fb950' : '#6e7681'} /> GPU: {info.gpu?.available ? (info.gpu.names?.join(', ') || `${info.gpu.devices}×`) : 'none'}
              </span>
              <span>auth: {info.auth_enabled ? 'on' : 'off'}</span>
              {info.disk && <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}><HardDrive size={13} /> {fmtBytes(info.disk.free_bytes)} free</span>}
            </div>
          ) : <div style={{ fontSize: 12, color: '#8b949e' }}>connecting…</div>}
          {net && (net.last_known || net.overrides) && (
            <div style={{ fontSize: 11, color: '#6e7681', marginTop: 6 }}>
              {Object.keys(net.last_known || {}).length > 0 && <>cached cloud data: {Object.entries(net.last_known).map(([k, v]) => `${k} (${v.as_of})`).join(', ')}</>}
            </div>
          )}
        </Section>

        {/* CoT push targets — the cursor-on-target / TAK-server option set */}
        <Section title="Cursor-on-Target push (→ ATAK / WinTAK / TAK Server)">
          <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 4 }}>
            LoBs and emitter fixes from the SDR console are pushed as CoT to every target below. One per line / comma-separated.<br/>
            <code>udp://239.2.3.1:6969</code> (ATAK multicast), <code>tcp://taksrv.lan:8087</code>, <code>tls://taksrv.lan:8089</code> (mutual-TLS — set <code>ARES_COT_TLS_CA/CERT/KEY</code>).
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
            <textarea rows={2} style={{ ...inputStyle, flex: 1, fontFamily: 'monospace' }}
                      value={cotInput} onChange={e => setCotInput(e.target.value)}
                      placeholder={cotTargets.join('\n') || 'udp://239.2.3.1:6969'} />
            <button style={btn} onClick={applyCot}><RefreshCw size={12} /> Apply</button>
          </div>
          {cotTargets.length > 0 && <div style={{ fontSize: 11, color: '#6e7681', marginTop: 4 }}>active: {cotTargets.join(', ')}</div>}
        </Section>

        {/* Data packs */}
        <Section title="Offline data packs">
          {packs.length === 0 ? <div style={{ fontSize: 12, color: '#8b949e', marginBottom: 8 }}>No packs installed yet.</div> : (
            <div style={{ marginBottom: 10 }}>
              {packs.map(p => (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#c9d1d9', padding: '4px 0', borderBottom: '1px solid #21262d' }}>
                  <span style={{ background: '#1f2937', color: '#9ca3af', borderRadius: 3, padding: '1px 5px', fontSize: 10, textTransform: 'uppercase' }}>{p.layer}</span>
                  <span style={{ flex: 1 }}>{p.name}</span>
                  <span style={{ color: '#6e7681' }}>{fmtBytes(p.size_bytes_on_disk ?? p.size_bytes)}</span>
                  <button style={{ ...btn, padding: '2px 6px' }} title="Verify pack integrity / version" onClick={() => checkPack(p.id)}><ShieldCheck size={12} color="#3fb950" /></button>
                  <button style={{ ...btn, padding: '2px 6px' }} title="Delete pack" onClick={() => removePack(p.id)}><Trash2 size={12} color="#f85149" /></button>
                </div>
              ))}
            </div>
          )}
          {/* download form */}
          <div style={{ background: '#0b0f14', border: '1px solid #21262d', borderRadius: 6, padding: 10, fontSize: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ color: '#8b949e' }}>Download:</span>
              <select value={dlLayer} onChange={e => setDlLayer(e.target.value)} style={inputStyle}>
                {PACK_LAYERS.map(l => <option key={l} value={l}>{l}</option>)}
              </select>
              {(dlLayer === 'osm' || dlLayer === 'imagery') && <label style={{ color: '#8b949e' }}>max zoom <input type="number" min={0} max={19} value={maxZoom} onChange={e => setMaxZoom(e.target.value)} style={{ ...inputStyle, width: 52 }} /></label>}
              <label style={{ color: '#8b949e', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <input type="checkbox" checked={fullPlanet} onChange={e => setFullPlanet(e.target.checked)} /> whole planet
              </label>
            </div>
            {!fullPlanet && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                <span style={{ color: '#8b949e' }}>bbox:</span>
                {['w', 's', 'e', 'n'].map(k => (
                  <input key={k} placeholder={k} value={bbox[k]} onChange={e => setBbox(b => ({ ...b, [k]: e.target.value }))} style={{ ...inputStyle, width: 78 }} />
                ))}
                {onRequestDrawBbox && (
                  <button style={{ ...btn, padding: '3px 7px' }} onClick={onRequestDrawBbox} title="Close this dialog and draw a rectangle on the map">
                    <Square size={12} /> Draw on map
                  </button>
                )}
                <button style={{ ...btn, padding: '3px 7px' }} onClick={useMapBbox} disabled={!mapCenter}>≈1° around map center</button>
              </div>
            )}
            <button style={{ ...btn, background: '#1f6feb', borderColor: '#1f6feb' }} onClick={submitDownload}><Download size={13} /> Download pack</button>
            <div style={{ color: '#6e7681', fontSize: 10, marginTop: 6 }}>
              terrain = SRTM30 .hgt (≈26 MB / 1° tile) · osm = raster base-map tiles · imagery = satellite/aerial tiles (ESRI World Imagery) — both rate-limited & capped, use your own tile server for large jobs · buildings = OSM footprints (extruded on the 3D globe) · clutter = ESA WorldCover 10 m land cover (≈130 MB / 3° tile). “whole planet” for terrain is clipped to SRTM land coverage. ⛉ verifies a pack's integrity & version.
            </div>
          </div>
          {/* jobs */}
          {jobs.length > 0 && (
            <div style={{ marginTop: 10 }}>
              {jobs.slice(-4).map(j => (
                <div key={j.job_id} style={{ fontSize: 11, color: j.status === 'error' ? '#ff7b72' : j.status === 'done' ? '#3fb950' : '#d29922', padding: '2px 0' }}>
                  {j.job_id} · {j.layers?.join('+')} · {j.status}{typeof j.progress === 'number' && j.status === 'running' ? ` ${Math.round(j.progress * 100)}%` : ''} — {j.detail}
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* Radio templates */}
        <Section title={`Radio templates (${templates.length})`}>
          {templates.length === 0 ? <div style={{ fontSize: 12, color: '#8b949e' }}>None.</div> : (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {templates.map(t => {
                const f = t.transmitter?.frequency_hz, p = t.transmitter?.power_dbm
                return (
                  <div key={t.id} style={{ background: '#0b0f14', border: '1px solid #21262d', borderRadius: 6, padding: '6px 10px', fontSize: 12, color: '#c9d1d9' }}>
                    <div style={{ fontWeight: 600 }}>{t.name}</div>
                    <div style={{ color: '#6e7681', fontSize: 10 }}>{t.id}{f ? ` · ${(f / 1e6).toFixed(1)} MHz` : ''}{p != null ? ` · ${p} dBm` : ''}{t.antenna?.type ? ` · ${t.antenna.type}` : ''}</div>
                  </div>
                )
              })}
            </div>
          )}
          <div style={{ color: '#6e7681', fontSize: 10, marginTop: 8 }}>
            These templates are what the ARES-ATAK plugin loads. Point an ATAK device at this server: <b>{typeof window !== 'undefined' ? `${window.location.protocol}//${window.location.hostname}:8000` : 'http://&lt;this-host&gt;:8000'}</b> (Settings tab in the plugin). The plugin module lives in <code>atak-plugin/</code>.
          </div>
        </Section>
      </div>
    </div>
  )
}
