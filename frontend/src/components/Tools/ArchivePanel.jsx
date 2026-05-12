/**
 * Archive Panel
 * localStorage-based: save calculations with name/network,
 * load back, export as GeoJSON. Key: 'ares-archive' (legacy 'rf-sim-archive' migrated on read)
 */
import { useState, useEffect, useCallback } from 'react'
import { Save, FolderOpen, Trash2, Download, ChevronDown, ChevronRight, Archive } from 'lucide-react'

const ARCHIVE_KEY = 'ares-archive'
const LEGACY_ARCHIVE_KEY = 'rf-sim-archive'

function loadArchive() {
  try {
    let raw = localStorage.getItem(ARCHIVE_KEY)
    if (!raw) {
      const legacy = localStorage.getItem(LEGACY_ARCHIVE_KEY)
      if (legacy) {
        localStorage.setItem(ARCHIVE_KEY, legacy)
        localStorage.removeItem(LEGACY_ARCHIVE_KEY)
        raw = legacy
      }
    }
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveArchive(entries) {
  try {
    localStorage.setItem(ARCHIVE_KEY, JSON.stringify(entries))
  } catch {
    console.error('Archive save failed — localStorage may be full')
  }
}

export default function ArchivePanel({ currentGeojson, currentParams, onLoad, onClose }) {
  const [entries, setEntries] = useState([])
  const [saveName, setSaveName] = useState('')
  const [saveNetwork, setSaveNetwork] = useState('')
  const [expandedId, setExpandedId] = useState(null)

  useEffect(() => {
    setEntries(loadArchive())
  }, [])

  const handleSave = useCallback(() => {
    if (!saveName.trim()) return
    const newEntry = {
      id:        Date.now().toString(),
      name:      saveName.trim(),
      network:   saveNetwork.trim() || 'Default',
      type:      currentParams?.type || 'coverage',
      timestamp: new Date().toISOString(),
      params:    currentParams || {},
      geojson:   currentGeojson || null,
      metadata:  {
        point_count: currentGeojson?.features?.length || 0,
      },
    }
    const updated = [...entries, newEntry]
    setEntries(updated)
    saveArchive(updated)
    setSaveName('')
  }, [saveName, saveNetwork, currentGeojson, currentParams, entries])

  const handleDelete = useCallback((id) => {
    const updated = entries.filter(e => e.id !== id)
    setEntries(updated)
    saveArchive(updated)
  }, [entries])

  const handleExport = useCallback((entry) => {
    if (!entry.geojson) return
    const blob = new Blob([JSON.stringify(entry.geojson, null, 2)], { type: 'application/geo+json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${entry.name.replace(/\s+/g, '_')}_${entry.id}.geojson`
    a.click()
    URL.revokeObjectURL(url)
  }, [])

  const handleLoad = useCallback((entry) => {
    onLoad?.(entry)
  }, [onLoad])

  const handleExportAll = useCallback(() => {
    const all = {
      type: 'FeatureCollection',
      features: entries.flatMap(e => e.geojson?.features || []),
    }
    const blob = new Blob([JSON.stringify(all, null, 2)], { type: 'application/geo+json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ares-archive-${Date.now()}.geojson`
    a.click()
    URL.revokeObjectURL(url)
  }, [entries])

  // Group entries by network
  const groups = {}
  for (const e of entries) {
    const net = e.network || 'Default'
    if (!groups[net]) groups[net] = []
    groups[net].push(e)
  }

  const typeColor = (type) => {
    if (type === 'p2p')        return '#a855f7'
    if (type === 'best_site')  return '#f59e0b'
    if (type === 'manet')      return '#06d6a0'
    if (type === 'route')      return '#00b4d8'
    if (type === 'ray_trace')  return '#ef4444'
    return '#8b949e'
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9998,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#161b22', border: '1px solid #30363d', borderRadius: 10,
          padding: 0, width: 500, maxWidth: '95vw',
          maxHeight: '85vh', display: 'flex', flexDirection: 'column',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 18px', borderBottom: '1px solid #21262d',
        }}>
          <Archive size={16} color="var(--accent-blue)" />
          <span style={{ fontWeight: 700, fontSize: 15, color: '#e6edf3', flex: 1 }}>
            Calculation Archive
          </span>
          <button
            className="btn btn-ghost"
            style={{ padding: '2px 6px', fontSize: 11 }}
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        {/* Save form */}
        <div style={{ padding: '12px 18px', borderBottom: '1px solid #21262d' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: '#8b949e', marginBottom: 8 }}>
            SAVE CURRENT RESULT
          </div>
          {!currentGeojson && (
            <div style={{ fontSize: 11, color: '#444d56', marginBottom: 6 }}>
              Run a simulation first to save its result.
            </div>
          )}
          <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
            <input
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
              placeholder="Name (required)"
              style={{
                flex: 2, padding: '4px 8px', fontSize: 12,
                background: '#0d1117', border: '1px solid #30363d',
                borderRadius: 4, color: '#e6edf3', outline: 'none',
              }}
            />
            <input
              value={saveNetwork}
              onChange={e => setSaveNetwork(e.target.value)}
              placeholder="Network / Project"
              style={{
                flex: 1, padding: '4px 8px', fontSize: 12,
                background: '#0d1117', border: '1px solid #30363d',
                borderRadius: 4, color: '#e6edf3', outline: 'none',
              }}
            />
            <button
              className="btn btn-primary"
              style={{ padding: '4px 12px', fontSize: 12, gap: 4 }}
              disabled={!saveName.trim() || !currentGeojson}
              onClick={handleSave}
            >
              <Save size={12} /> Save
            </button>
          </div>
        </div>

        {/* Entry list */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 18px' }}>
          {entries.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '32px 0', color: '#444d56', fontSize: 13 }}>
              No saved calculations yet
            </div>
          ) : (
            Object.entries(groups).map(([net, netEntries]) => (
              <div key={net} style={{ marginBottom: 12 }}>
                <div style={{
                  fontSize: 10, fontWeight: 700, color: '#8b949e',
                  textTransform: 'uppercase', letterSpacing: 1,
                  marginBottom: 4, padding: '2px 0',
                  borderBottom: '1px solid #21262d',
                }}>
                  {net}
                </div>
                {netEntries.map(entry => (
                  <div key={entry.id} style={{
                    background: '#0d1117', border: '1px solid #21262d',
                    borderRadius: 6, marginBottom: 4, overflow: 'hidden',
                  }}>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 8,
                      padding: '6px 10px', cursor: 'pointer',
                    }}
                      onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                    >
                      {expandedId === entry.id
                        ? <ChevronDown size={12} color="#8b949e" />
                        : <ChevronRight size={12} color="#8b949e" />}
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%', flexShrink: 0,
                        background: typeColor(entry.type),
                      }} />
                      <span style={{ fontSize: 12, color: '#e6edf3', flex: 1 }}>{entry.name}</span>
                      <span style={{ fontSize: 10, color: '#444d56' }}>
                        {new Date(entry.timestamp).toLocaleDateString()}
                      </span>
                      <span style={{
                        fontSize: 10, color: typeColor(entry.type),
                        background: typeColor(entry.type) + '22',
                        padding: '1px 5px', borderRadius: 3,
                      }}>{entry.type}</span>
                    </div>

                    {expandedId === entry.id && (
                      <div style={{ padding: '6px 10px 10px 28px', borderTop: '1px solid #21262d' }}>
                        <div style={{ fontSize: 11, color: '#8b949e', marginBottom: 6 }}>
                          {entry.metadata?.point_count || 0} features ·{' '}
                          {new Date(entry.timestamp).toLocaleString()}
                        </div>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button
                            className="btn btn-secondary"
                            style={{ fontSize: 11, gap: 4, padding: '3px 8px' }}
                            onClick={() => handleLoad(entry)}
                          >
                            <FolderOpen size={11} /> Load to Map
                          </button>
                          <button
                            className="btn btn-ghost"
                            style={{ fontSize: 11, gap: 4, padding: '3px 8px' }}
                            disabled={!entry.geojson}
                            onClick={() => handleExport(entry)}
                          >
                            <Download size={11} /> GeoJSON
                          </button>
                          <button
                            className="btn btn-ghost"
                            style={{ fontSize: 11, gap: 4, padding: '3px 8px', color: '#ef4444' }}
                            onClick={() => handleDelete(entry.id)}
                          >
                            <Trash2 size={11} /> Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        {entries.length > 0 && (
          <div style={{
            padding: '10px 18px', borderTop: '1px solid #21262d',
            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          }}>
            <span style={{ fontSize: 11, color: '#444d56' }}>
              {entries.length} saved calculation{entries.length !== 1 ? 's' : ''}
            </span>
            <button
              className="btn btn-ghost"
              style={{ fontSize: 11, gap: 4 }}
              onClick={handleExportAll}
            >
              <Download size={11} /> Export All GeoJSON
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
