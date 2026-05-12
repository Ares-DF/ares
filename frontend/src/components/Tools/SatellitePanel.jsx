/**
 * Satellite Visibility Panel
 * Proxy CelesTrak API, compute LOS from satellite position to ground.
 */
import { useState, useCallback } from 'react'
import { Satellite, RefreshCw } from 'lucide-react'
import { simulateSatelliteVisibility } from '../../api/client'
import { toast } from 'react-toastify'

const CONSTELLATIONS = [
  { id: 'STARLINK',  label: 'Starlink (SpaceX)' },
  { id: 'ISS',       label: 'ISS' },
  { id: 'GPS-OPS',   label: 'GPS (US)' },
  { id: 'GALILEO',   label: 'Galileo (EU)' },
  { id: 'BEIDOU',    label: 'BeiDou (CN)' },
  { id: 'GLONASS',   label: 'GLONASS (RU)' },
  { id: 'IRIDIUM',   label: 'Iridium' },
  { id: 'INTELSAT',  label: 'Intelsat (GEO)' },
]

export default function SatellitePanel({ txLat, txLon, onResult }) {
  const [constellation, setConstellation] = useState('STARLINK')
  const [minElevation, setMinElevation] = useState(10)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleRun = useCallback(async () => {
    setLoading(true)
    try {
      const res = await simulateSatelliteVisibility({
        ground_lat: txLat,
        ground_lon: txLon,
        ground_height_m: 0,
        constellation,
        min_elevation_deg: minElevation,
      })
      setResult(res.metadata)
      onResult?.(res.geojson)
      toast.success(`${res.metadata?.visible_count} visible ${constellation} satellites`)
    } catch (err) {
      toast.error('Satellite visibility failed: ' + (err.response?.data?.detail || err.message))
    } finally {
      setLoading(false)
    }
  }, [txLat, txLon, constellation, minElevation, onResult])

  return (
    <div style={{ padding: '8px 12px', borderTop: '1px solid #21262d' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Satellite size={13} color="var(--accent-blue)" />
        <span style={{ fontSize: 11, fontWeight: 600, color: '#8b949e' }}>
          SATELLITE VISIBILITY
        </span>
      </div>

      <div style={{ marginBottom: 8 }}>
        <label style={{ fontSize: 11, color: '#8b949e', display: 'block', marginBottom: 4 }}>
          Constellation
        </label>
        <select
          value={constellation}
          onChange={e => setConstellation(e.target.value)}
          style={{
            width: '100%', padding: '4px 8px', fontSize: 12,
            background: '#0d1117', border: '1px solid #30363d',
            borderRadius: 4, color: '#e6edf3',
          }}
        >
          {CONSTELLATIONS.map(c => (
            <option key={c.id} value={c.id}>{c.label}</option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 10 }}>
        <label style={{ fontSize: 11, color: '#8b949e', display: 'block', marginBottom: 4 }}>
          Min Elevation Angle: {minElevation}°
        </label>
        <input
          type="range"
          min={0} max={45} step={1}
          value={minElevation}
          onChange={e => setMinElevation(Number(e.target.value))}
          style={{ width: '100%' }}
        />
      </div>

      <div style={{ fontSize: 11, color: '#444d56', marginBottom: 8 }}>
        Ground station: {txLat?.toFixed(4)}, {txLon?.toFixed(4)}
      </div>

      <button
        className="btn btn-primary"
        style={{ width: '100%', gap: 6, fontSize: 12 }}
        onClick={handleRun}
        disabled={loading}
      >
        {loading
          ? <><div className="spinner" style={{ width: 11, height: 11, borderWidth: 2 }} />Computing…</>
          : <><RefreshCw size={12} />Compute Visibility</>}
      </button>

      {result && (
        <div style={{ marginTop: 10, padding: 8, background: '#0d1117', borderRadius: 4, border: '1px solid #21262d' }}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#06d6a0' }}>
                {result.visible_count}
              </div>
              <div style={{ fontSize: 10, color: '#8b949e' }}>Visible sats</div>
            </div>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#8b949e' }}>
                {result.total_sats}
              </div>
              <div style={{ fontSize: 10, color: '#8b949e' }}>Total tracked</div>
            </div>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#00b4d8' }}>
                {minElevation}°
              </div>
              <div style={{ fontSize: 10, color: '#8b949e' }}>Min elevation</div>
            </div>
          </div>
          <div style={{ fontSize: 10, color: '#444d56', marginTop: 6 }}>
            {result.timestamp_utc?.slice(0, 19).replace('T', ' ')} UTC
          </div>
        </div>
      )}
    </div>
  )
}
