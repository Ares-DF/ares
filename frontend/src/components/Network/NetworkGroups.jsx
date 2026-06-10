// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

import { useState } from 'react'
import { ChevronDown, ChevronRight, Send, Users } from 'lucide-react'
import { DOMAINS } from '../../utils/network'

const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }

function fmtMs(t) { return t ? new Date(t * 1000).toLocaleTimeString() : '—' }
function fmtRssi(d) { return d == null ? '' : `${d.toFixed(0)} dBm` }

/**
 * Grouped tree view — each network (cell / BSS / talk-group / operator) is a
 * collapsible card holding its hub and member selectors. The "comprehensive vs
 * simple" knob (detailed) decides whether per-member RSSI / obs / metadata show.
 */
export default function NetworkGroups({ networks, detailed, onSendToMap }) {
  const [open, setOpen] = useState(() => new Set())
  const toggle = (k) => setOpen((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n })

  if (!networks.length) {
    return <div style={{ padding: 16, textAlign: 'center', color: '#6e7681', fontSize: 12 }}>No networks match the current filters.</div>
  }

  const member = (m) => (
    <div key={m._key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 10px 3px 26px', borderTop: '1px solid #161b22', fontSize: 11 }}>
      <span style={{ color: '#8b949e', minWidth: 86 }}>{m.label}</span>
      <code style={{ ...mono, color: '#c9d1d9', flex: 1 }}>{m.value}</code>
      {detailed && <span style={{ color: '#f59e0b', minWidth: 60, textAlign: 'right' }}>{fmtRssi(m.peak_rssi_dbm)}</span>}
      {detailed && <span style={{ color: '#6e7681', minWidth: 46, textAlign: 'right' }}>{m.n_obs} obs</span>}
      <span style={{ color: '#6e7681', minWidth: 64, textAlign: 'right' }}>{fmtMs(m.last_seen_t)}</span>
      {m.position && (
        <button className="btn btn-ghost" style={{ fontSize: 9, padding: '1px 5px' }} title="Send to map"
                onClick={() => onSendToMap?.({ lat: m.position.lat, lon: m.position.lon, label: `${m.label}: ${m.value}`, method_id: m.position.method, method_name: `target/${m.kind}`, cep_m: m.position.cep_m, raw: m })}>
          <Send size={10} />
        </button>
      )}
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {networks.map((net) => {
        const d = DOMAINS[net.domain]
        const isOpen = open.has(net.key)
        const members = [...net.members].sort((a, b) => (b.peak_rssi_dbm ?? -1e9) - (a.peak_rssi_dbm ?? -1e9))
        return (
          <div key={net.key} style={{ border: `1px solid ${d.color}33`, borderRadius: 8, overflow: 'hidden', background: '#0d1117' }}>
            <button onClick={() => toggle(net.key)} style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', background: 'transparent', border: 'none', cursor: 'pointer', color: '#e6edf3', textAlign: 'left' }}>
              {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
              <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 10, background: `${d.color}22`, color: d.color, fontWeight: 600 }}>{d.short}</span>
              <b style={{ fontSize: 12 }}>{net.label}</b>
              {net.hub && <code style={{ ...mono, fontSize: 10, color: '#6e7681' }}>{net.hub.value}</code>}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 10, color: '#8b949e', display: 'flex', alignItems: 'center', gap: 3 }}><Users size={11} /> {net.members.length}</span>
              <span style={{ fontSize: 10, color: '#6e7681' }}>{fmtMs(net.lastSeen)}</span>
            </button>
            {isOpen && (
              <div>
                {net.hub && detailed && (
                  <div style={{ padding: '4px 10px', borderTop: '1px solid #161b22', fontSize: 10, color: '#6e7681' }}>
                    hub · {net.hub.label} {net.hub.position ? `· ${net.hub.position.lat.toFixed(4)}, ${net.hub.position.lon.toFixed(4)}` : ''}
                  </div>
                )}
                {members.length ? members.map(member)
                  : <div style={{ padding: '6px 10px 6px 26px', borderTop: '1px solid #161b22', fontSize: 10, color: '#6e7681' }}>no member selectors</div>}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
