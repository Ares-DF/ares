/**
 * The "Space Wx" bottom-panel tab — NOAA SWPC space weather: geomagnetic (Kp, F10.7
 * solar flux, storm class), HF propagation (radio blackout + a plain-language summary),
 * and VHF Sporadic-E likelihood.
 */
export default function SpaceWxPanel({ spaceWeather }) {
  const sw = spaceWeather
  const kpColor = sw.kp_index >= 5 ? '#ef4444' : sw.kp_index >= 3 ? '#f59e0b' : '#06d6a0'
  const fetchedAt = sw.timestamp_utc
    ? new Date(sw.timestamp_utc).toLocaleString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit', timeZoneName: 'short',
      })
    : null
  return (
    <div style={{ padding: '18px 24px', display: 'flex', flexWrap: 'wrap', gap: 24, flex: 1, minHeight: 0, overflowY: 'auto', alignContent: 'flex-start' }}>
      {fetchedAt && (
        <div style={{ width: '100%', fontSize: 10, color: '#484f58', marginBottom: -12 }}>Current as of {fetchedAt} · Source: NOAA SWPC</div>
      )}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>Geomagnetic</div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: kpColor, flexShrink: 0 }} />
          <span style={{ fontSize: 13, color: '#e6edf3', fontWeight: 700 }}>Kp {sw.kp_index?.toFixed(1)}</span>
          {sw.storm_class !== 'None' && <span style={{ fontSize: 11, color: '#f59e0b', marginLeft: 6 }}>Storm {sw.storm_class}</span>}
        </div>
        <div style={{ fontSize: 11, color: '#8b949e' }}>F10.7 solar flux: <strong style={{ color: '#e6edf3' }}>{sw.solar_flux_f107?.toFixed(0)} sfu</strong></div>
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>HF Propagation</div>
        <div style={{ fontSize: 11, color: sw.radio_blackout !== 'None' ? '#ef4444' : '#8b949e', marginBottom: 4 }}>
          Radio blackout: <strong style={{ color: '#e6edf3' }}>{sw.radio_blackout}</strong>
        </div>
        <div style={{ fontSize: 11, color: '#8b949e', maxWidth: 320, lineHeight: 1.5 }}>{sw.hf_propagation}</div>
      </div>
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#8b949e', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.8 }}>VHF / Sporadic-E</div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: sw.vhf_sporadic_e_likely ? '#06d6a0' : '#30363d', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: sw.vhf_sporadic_e_likely ? '#06d6a0' : '#8b949e' }}>
            {sw.vhf_sporadic_e_likely ? 'Sporadic-E possible' : 'No Sporadic-E expected'}
          </span>
        </div>
      </div>
    </div>
  )
}
