/**
 * The sidebar control for the Best-Server tab: the query point (which the tool
 * tests against your TX sites — the extra-TX list, plus any sites added below) and,
 * once Best-Server has run, the ranked list of servers. App owns the query point + result.
 */
export default function BestServerSidebar({ query, result, onClearQuery }) {
  return (
    <div style={{ borderTop: '1px solid #21262d', padding: '8px 12px' }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', marginBottom: 6 }}>BEST SERVER TOOL</div>
      <div style={{ fontSize: 11, color: '#444d56', marginBottom: 8 }}>
        Click a query point — the tool finds which of your TX sites serves it best.
        Uses the extra TX list as candidate sites, or add specific sites below.
      </div>
      {query ? (
        <div style={{ fontSize: 11, color: '#06d6a0', marginBottom: 8 }}>
          Query: {query.lat.toFixed(4)}, {query.lon.toFixed(4)}
          <button className="btn btn-ghost" style={{ marginLeft: 8, fontSize: 10, padding: '1px 4px', color: '#ef4444' }} onClick={onClearQuery}>×</button>
        </div>
      ) : (
        <div style={{ fontSize: 11, color: '#444d56', marginBottom: 8 }}>Click the map to set the query point.</div>
      )}
      {result && (
        <div style={{ padding: 8, background: '#0d1117', borderRadius: 4, border: '1px solid #21262d', marginTop: 4 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', marginBottom: 4 }}>RANKED SERVERS</div>
          {result.sites?.map((s, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between',
              fontSize: 11, padding: '2px 0', borderBottom: '1px solid #21262d',
            }}>
              <span style={{ color: i === 0 ? '#06d6a0' : '#c9d1d9' }}>{i === 0 ? '★ ' : ''}{s.label || `Site ${i + 1}`}</span>
              <span style={{ color: '#8b949e' }}>{s.signal_dbm} dBm · {(s.distance_m / 1000).toFixed(1)} km</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
