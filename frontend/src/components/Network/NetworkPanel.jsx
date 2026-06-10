// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

import { useEffect, useMemo, useState } from 'react'
import {
  Network as NetworkIcon, RefreshCw, ChevronRight, ChevronDown, Radio, Search,
  Table2, GitFork, ListTree, Download, SlidersHorizontal,
} from 'lucide-react'
import { listTargets } from '../../api/client'
import ErrorBoundary from '../Common/ErrorBoundary'
import CellularPanel from '../Tools/CellularPanel'
import {
  DOMAINS, DOMAIN_ORDER, deriveNetworks, domainCounts,
  BASE_COLUMNS, discoverMetaColumns, toCSV, sheetRows, networkSummaryRows, anbSheets,
} from '../../utils/network'
import { makeXlsx, downloadBlob } from '../../utils/xlsx'
import NetworkTable from './NetworkTable'
import NetworkGroups from './NetworkGroups'
import NetworkNotebook from './NetworkNotebook'

const card = { background: '#0d1117', border: '1px solid #21262d', borderRadius: 8, padding: 10, marginBottom: 10 }
const inp = { background: '#0d1117', color: '#c9d1d9', border: '1px solid #21262d', borderRadius: 4, padding: '3px 6px', fontSize: 11 }

const LS = 'ares.network.prefs'
const loadPrefs = () => { try { return JSON.parse(localStorage.getItem(LS)) || {} } catch { return {} } }
const savePrefs = (p) => { try { localStorage.setItem(LS, JSON.stringify(p)) } catch { /* quota */ } }

const VIEWS = [
  { id: 'table',    label: 'Spreadsheet', icon: Table2 },
  { id: 'notebook', label: 'Notebook',    icon: GitFork },
  { id: 'groups',   label: 'Groups',      icon: ListTree },
]

const SIMPLE_COLS = BASE_COLUMNS.filter((c) => c.simple).map((c) => c.id)

/**
 * The Network tab. Hosts the passive monitors (cellular / Wi-Fi / BLE captures
 * that feed the tracker) and "Network Analysis" — three interchangeable views of
 * the networks (cellular, Wi-Fi, PTT, UAS, …) collected on their selectors
 * (IMSI, RID, talk-group, MAC, BSSID, …). Filters, density and table columns are
 * customizable and persisted, so the tab can be as simple or comprehensive as
 * the operator wants.
 */
export default function NetworkPanel({ onSendToMap }) {
  const prefs = useMemo(loadPrefs, [])
  const [targets, setTargets] = useState([])
  const [err, setErr] = useState('')
  const [monitorsOpen, setMonitorsOpen] = useState(prefs.monitorsOpen ?? false)
  const [view, setView] = useState(prefs.view || 'table')
  const [detailed, setDetailed] = useState(prefs.detailed ?? false)
  const [search, setSearch] = useState('')
  const [enabled, setEnabled] = useState(() => new Set(prefs.enabled || DOMAIN_ORDER))
  const [cols, setCols] = useState(() => new Set(prefs.cols || SIMPLE_COLS))
  const [colsOpen, setColsOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)

  // Persist on change
  useEffect(() => {
    savePrefs({ monitorsOpen, view, detailed, enabled: [...enabled], cols: [...cols] })
  }, [monitorsOpen, view, detailed, enabled, cols])

  const refresh = async () => {
    try { const d = await listTargets({ min_obs: 1 }); setTargets(d.targets || []); setErr('') }
    catch (e) { setErr(String(e?.response?.data?.detail || e?.message || e)) }
  }
  useEffect(() => {
    refresh()
    const h = setInterval(() => { if (!document.hidden) refresh() }, 4000)
    return () => clearInterval(h)
  }, [])

  const { nodes, networks, netLabelByKey } = useMemo(() => {
    const d = deriveNetworks(targets)
    const map = {}
    for (const net of d.networks) for (const n of net.all) map[n._key] = net.label
    return { ...d, netLabelByKey: map }
  }, [targets])

  const counts = useMemo(() => domainCounts(nodes), [nodes])

  const q = search.trim().toLowerCase()
  const matches = (n) => {
    if (!q) return true
    if (n.value?.toLowerCase().includes(q) || n.label?.toLowerCase().includes(q)) return true
    if ((netLabelByKey[n._key] || '').toLowerCase().includes(q)) return true
    return Object.values(n.metadata || {}).some((v) => String(v).toLowerCase().includes(q))
  }
  const filteredNodes = useMemo(() => nodes.filter((n) => enabled.has(n.domain) && matches(n)), [nodes, enabled, q, netLabelByKey])
  const filteredNets = useMemo(() => networks.filter((net) =>
    enabled.has(net.domain) && (!q || net.label.toLowerCase().includes(q) || net.all.some(matches))
  ), [networks, enabled, q, netLabelByKey])

  // Table columns: base + discovered metadata, filtered to the operator's selection.
  const metaCols = useMemo(() => discoverMetaColumns(filteredNodes), [filteredNodes])
  const allCols = useMemo(() => [...BASE_COLUMNS, ...metaCols], [metaCols])
  const visibleCols = useMemo(() => allCols.filter((c) => cols.has(c.id)), [allCols, cols])
  const ctx = useMemo(() => ({ netLabelByKey }), [netLabelByKey])

  const setPreset = (d) => { setDetailed(d); setCols(new Set(d ? allCols.map((c) => c.id) : SIMPLE_COLS)) }
  const toggleCol = (id) => setCols((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleDomain = (id) => setEnabled((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const ts = () => new Date().toISOString().slice(0, 19).replace(/[:T]/g, '')
  const exportCols = () => (visibleCols.length ? visibleCols : BASE_COLUMNS)

  const exportCSV = () => {
    const csv = toCSV(filteredNodes, exportCols(), ctx)
    downloadBlob(new Blob([csv], { type: 'text/csv' }), `ares-network-${ts()}.csv`)
  }
  // Excel: the spreadsheet view as sheet 1 + a per-network summary as sheet 2.
  const exportExcel = async () => {
    const blob = await makeXlsx([
      { name: 'Selectors', rows: sheetRows(filteredNodes, exportCols(), ctx) },
      { name: 'Networks', rows: networkSummaryRows(filteredNets) },
    ])
    downloadBlob(blob, `ares-network-${ts()}.xlsx`)
  }
  // i2 Analyst's Notebook: Entities + Links sheets, importable with a
  // spreadsheet Import Specification (entity rows keyed by Entity ID; the
  // Links sheet references the same IDs for the link chart).
  const exportANB = async () => {
    const { entities, links } = anbSheets(filteredNets)
    const blob = await makeXlsx([{ name: 'Entities', rows: entities }, { name: 'Links', rows: links }])
    downloadBlob(blob, `ares-network-anb-${ts()}.xlsx`)
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto', padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <NetworkIcon size={16} color="#22d3ee" />
        <b style={{ color: '#e6edf3' }}>Network — passive monitors + multi-view network analysis</b>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: '#6e7681' }}>{filteredNodes.length} selector(s) · {filteredNets.length} network(s)</span>
        <button className="btn btn-ghost" style={{ fontSize: 10, padding: '3px 8px' }} onClick={refresh}><RefreshCw size={11} /> Refresh</button>
      </div>

      {/* Passive monitors — the captures that FEED the tracker. */}
      <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
        <button onClick={() => setMonitorsOpen((o) => !o)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', background: 'transparent', border: 'none', cursor: 'pointer', color: '#e6edf3' }}>
          {monitorsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <Radio size={13} color="#22d3ee" />
          <b style={{ fontSize: 12 }}>Passive monitors</b>
          <span style={{ fontSize: 10, color: '#6e7681', fontWeight: 400 }}>cellular (2G/LTE/5G) · Wi-Fi · BLE — strictly passive; decoded identifiers feed the analysis below</span>
        </button>
        {monitorsOpen && (
          <div style={{ padding: '0 10px 10px', borderTop: '1px solid #161b22' }}>
            <ErrorBoundary label="Passive monitors"><CellularPanel /></ErrorBoundary>
          </div>
        )}
      </div>

      {/* Network Analysis */}
      <div style={{ ...card }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          <b style={{ fontSize: 12, color: '#e6edf3' }}>Network Analysis</b>
          <span style={{ flex: 1 }} />
          {/* View switch */}
          <div style={{ display: 'flex', border: '1px solid #21262d', borderRadius: 6, overflow: 'hidden' }}>
            {VIEWS.map((v) => {
              const Icon = v.icon
              return (
                <button key={v.id} onClick={() => setView(v.id)}
                        style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, padding: '4px 9px', border: 'none', cursor: 'pointer',
                                 background: view === v.id ? '#1f6feb' : 'transparent', color: view === v.id ? '#fff' : '#8b949e' }}>
                  <Icon size={11} /> {v.label}
                </button>
              )
            })}
          </div>
          {/* Density */}
          <div style={{ display: 'flex', border: '1px solid #21262d', borderRadius: 6, overflow: 'hidden' }}>
            <button onClick={() => setPreset(false)} style={{ fontSize: 10, padding: '4px 9px', border: 'none', cursor: 'pointer', background: !detailed ? '#30363d' : 'transparent', color: !detailed ? '#fff' : '#8b949e' }}>Simple</button>
            <button onClick={() => setPreset(true)} style={{ fontSize: 10, padding: '4px 9px', border: 'none', cursor: 'pointer', background: detailed ? '#30363d' : 'transparent', color: detailed ? '#fff' : '#8b949e' }}>Detailed</button>
          </div>
          {view === 'table' && (
            <div style={{ position: 'relative' }}>
              <button className="btn btn-ghost" style={{ fontSize: 10, padding: '4px 8px' }} onClick={() => setColsOpen((o) => !o)} title="Choose columns">
                <SlidersHorizontal size={11} /> Columns
              </button>
              {colsOpen && (
                <div style={{ position: 'absolute', top: '110%', right: 0, zIndex: 20, width: 200, maxHeight: 280, overflowY: 'auto', background: '#0d1117', border: '1px solid #30363d', borderRadius: 8, padding: 8 }}>
                  <div style={{ fontSize: 10, color: '#8b949e', marginBottom: 4 }}>Base fields</div>
                  {BASE_COLUMNS.map((c) => (
                    <label key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#c9d1d9', padding: '2px 0', cursor: 'pointer' }}>
                      <input type="checkbox" checked={cols.has(c.id)} onChange={() => toggleCol(c.id)} /> {c.label}
                    </label>
                  ))}
                  {metaCols.length > 0 && <div style={{ fontSize: 10, color: '#8b949e', margin: '6px 0 4px' }}>Metadata</div>}
                  {metaCols.map((c) => (
                    <label key={c.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#c9d1d9', padding: '2px 0', cursor: 'pointer' }}>
                      <input type="checkbox" checked={cols.has(c.id)} onChange={() => toggleCol(c.id)} /> <span style={{ fontFamily: 'ui-monospace, monospace' }}>{c.label}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          <div style={{ position: 'relative' }}>
            <button className="btn btn-ghost" style={{ fontSize: 10, padding: '4px 8px' }} onClick={() => setExportOpen((o) => !o)} title="Export the filtered networks">
              <Download size={11} /> Export
            </button>
            {exportOpen && (
              <div style={{ position: 'absolute', top: '110%', right: 0, zIndex: 20, width: 230, background: '#0d1117', border: '1px solid #30363d', borderRadius: 8, padding: 4 }}>
                {[
                  { label: 'CSV (.csv)', hint: 'visible columns', run: exportCSV },
                  { label: 'Excel (.xlsx)', hint: 'selectors + network summary', run: exportExcel },
                  { label: "Analyst's Notebook (.xlsx)", hint: 'Entities + Links sheets for i2 import', run: exportANB },
                ].map((it) => (
                  <button key={it.label} onClick={async () => { setExportOpen(false); await it.run() }}
                          style={{ display: 'block', width: '100%', textAlign: 'left', fontSize: 11, color: '#c9d1d9', background: 'transparent', border: 'none', borderRadius: 6, padding: '6px 8px', cursor: 'pointer' }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = '#161b22' }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}>
                    {it.label}
                    <div style={{ fontSize: 9, color: '#6e7681' }}>{it.hint}</div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Domain filter chips + search */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          {DOMAIN_ORDER.filter((id) => counts[id]).map((id) => {
            const d = DOMAINS[id], on = enabled.has(id)
            return (
              <button key={id} onClick={() => toggleDomain(id)}
                      title={d.blurb}
                      style={{ fontSize: 10, padding: '2px 9px', borderRadius: 12, cursor: 'pointer',
                               border: `1px solid ${on ? d.color : '#30363d'}`,
                               background: on ? `${d.color}22` : 'transparent',
                               color: on ? d.color : '#6e7681', fontWeight: 600 }}>
                {d.label} <span style={{ opacity: 0.8 }}>{counts[id]}</span>
              </button>
            )
          })}
          <span style={{ flex: 1 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, border: '1px solid #21262d', borderRadius: 6, padding: '0 6px' }}>
            <Search size={11} color="#6e7681" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="filter selectors / networks…"
                   style={{ ...inp, border: 'none', width: 180, padding: '4px 2px' }} />
          </div>
        </div>

        {err && <div style={{ fontSize: 10, color: '#f0883e', marginBottom: 6 }}>{err}</div>}

        {nodes.length === 0 ? (
          <div style={{ padding: 16, textAlign: 'center', color: '#6e7681', fontSize: 12 }}>
            No networks collected yet. Start a capture from <strong>Passive monitors</strong> above — decoded selectors (IMSI, MAC, BSSID, RID, UAS serial, …) stream in and are grouped into networks here.
          </div>
        ) : (
          <div style={{ minHeight: view === 'notebook' ? 420 : 0, height: view === 'notebook' ? 480 : 'auto' }}>
            {view === 'table' && <NetworkTable rows={filteredNodes} columns={visibleCols.length ? visibleCols : BASE_COLUMNS.filter((c) => c.simple)} ctx={ctx} onSendToMap={onSendToMap} />}
            {view === 'groups' && <NetworkGroups networks={filteredNets} detailed={detailed} onSendToMap={onSendToMap} />}
            {view === 'notebook' && <NetworkNotebook networks={filteredNets} onSendToMap={onSendToMap} />}
          </div>
        )}
      </div>
    </div>
  )
}
