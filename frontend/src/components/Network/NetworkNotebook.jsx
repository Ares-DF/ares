// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Send, X } from 'lucide-react'
import { DOMAINS } from '../../utils/network'

const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }

/**
 * Analyst-notebook-style link chart. Each network becomes a cluster: its hub at
 * the centre, member selectors on a ring around it, edges drawn member→hub.
 * Deterministic clustered layout (no physics) — readable and cheap. Click a node
 * to inspect it / send its fix to the map.
 */
export default function NetworkNotebook({ networks, onSendToMap }) {
  const wrapRef = useRef(null)
  const canvasRef = useRef(null)
  const [size, setSize] = useState({ w: 800, h: 480 })
  const [sel, setSel] = useState(null)        // selected node
  const [hover, setHover] = useState(null)
  const nodesRef = useRef([])

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  // ── Deterministic clustered layout ──────────────────────────────────────────
  const layout = useMemo(() => {
    const W = Math.max(360, size.w), H = Math.max(280, size.h)
    const nets = networks.filter((n) => n.all.length)
    if (!nets.length) return { nodes: [], edges: [] }
    const cols = Math.max(1, Math.round(Math.sqrt(nets.length * (W / Math.max(1, H)))))
    const rows = Math.ceil(nets.length / cols)
    const cellW = W / cols, cellH = H / rows
    const nodes = [], edges = []
    const byId = new Map()
    nets.forEach((net, i) => {
      const cx = (i % cols + 0.5) * cellW
      const cy = (Math.floor(i / cols) + 0.5) * cellH
      const d = DOMAINS[net.domain]
      const hubNode = { id: net.hub ? net.hub._key : net.key, x: cx, y: cy, r: 9, color: d.color, hub: true, label: net.label, target: net.hub, net }
      nodes.push(hubNode); byId.set(hubNode.id, hubNode)
      const ms = net.members
      const ring = Math.min(cellW, cellH) * 0.36 + Math.min(ms.length, 12) * 1.5
      ms.forEach((m, j) => {
        const a = (j / Math.max(1, ms.length)) * Math.PI * 2 - Math.PI / 2
        const node = { id: m._key, x: cx + Math.cos(a) * ring, y: cy + Math.sin(a) * ring, r: 5, color: d.color, hub: false, label: m.value, target: m, net }
        nodes.push(node); byId.set(node.id, node)
        edges.push({ x1: cx, y1: cy, x2: node.x, y2: node.y, color: d.color })
      })
    })
    return { nodes, edges, byId }
  }, [networks, size])

  // ── Draw ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const c = canvasRef.current; if (!c) return
    const dpr = window.devicePixelRatio || 1
    c.width = size.w * dpr; c.height = size.h * dpr
    const ctx = c.getContext('2d'); ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, size.w, size.h)
    ctx.fillStyle = '#0a0e13'; ctx.fillRect(0, 0, size.w, size.h)

    for (const e of layout.edges) {
      ctx.strokeStyle = `${e.color}44`; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(e.x1, e.y1); ctx.lineTo(e.x2, e.y2); ctx.stroke()
    }
    for (const n of layout.nodes) {
      const active = sel?.id === n.id || hover?.id === n.id
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r + (active ? 2 : 0), 0, Math.PI * 2)
      ctx.fillStyle = n.hub ? n.color : '#0a0e13'
      ctx.fill()
      ctx.lineWidth = active ? 2.5 : 1.5; ctx.strokeStyle = n.color; ctx.stroke()
      if (n.hub || active) {
        ctx.fillStyle = '#c9d1d9'; ctx.font = `${n.hub ? '11px' : '10px'} ui-monospace, monospace`
        ctx.textAlign = 'center'
        const txt = n.label.length > 24 ? n.label.slice(0, 23) + '…' : n.label
        ctx.fillText(txt, n.x, n.y - n.r - 4)
      }
    }
    nodesRef.current = layout.nodes
  }, [layout, size, sel, hover])

  const pick = (evt) => {
    const rect = canvasRef.current.getBoundingClientRect()
    const x = evt.clientX - rect.left, y = evt.clientY - rect.top
    let best = null, bestD = 14
    for (const n of nodesRef.current) {
      const d = Math.hypot(n.x - x, n.y - y)
      if (d < Math.max(bestD, n.r + 4)) { best = n; bestD = d }
    }
    return best
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative', width: '100%', height: '100%', minHeight: 300 }}>
      <canvas ref={canvasRef}
              style={{ width: '100%', height: '100%', display: 'block', cursor: hover ? 'pointer' : 'default', borderRadius: 6 }}
              onMouseMove={(e) => setHover(pick(e))}
              onMouseLeave={() => setHover(null)}
              onClick={(e) => setSel(pick(e))} />
      {!layout.nodes.length && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#6e7681', fontSize: 12 }}>
          No networks to graph with the current filters.
        </div>
      )}
      {sel && (
        <div style={{ position: 'absolute', top: 8, right: 8, width: 240, background: '#0d1117', border: '1px solid #30363d', borderRadius: 8, padding: 10, fontSize: 11 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 10, background: `${DOMAINS[sel.net.domain].color}22`, color: DOMAINS[sel.net.domain].color, fontWeight: 600 }}>{DOMAINS[sel.net.domain].short}</span>
            <b style={{ color: '#e6edf3' }}>{sel.target?.label || (sel.hub ? 'Hub' : 'Node')}</b>
            <span style={{ flex: 1 }} />
            <button className="btn btn-ghost" style={{ padding: 2 }} onClick={() => setSel(null)}><X size={12} /></button>
          </div>
          <code style={{ ...mono, color: '#c9d1d9', wordBreak: 'break-all' }}>{sel.target?.value || sel.label}</code>
          {sel.target && (
            <div style={{ marginTop: 6, color: '#8b949e', lineHeight: 1.7 }}>
              <div>Network: <span style={{ color: '#c9d1d9' }}>{sel.net.label}</span></div>
              {sel.target.peak_rssi_dbm != null && <div>Peak RSSI: <span style={{ color: '#f59e0b' }}>{sel.target.peak_rssi_dbm.toFixed(1)} dBm</span></div>}
              <div>Observations: <span style={{ color: '#c9d1d9' }}>{sel.target.n_obs}</span></div>
              {sel.target.position && <div>Fix: <span style={{ color: '#06d6a0' }}>{sel.target.position.lat.toFixed(4)}, {sel.target.position.lon.toFixed(4)}</span></div>}
              {sel.target.position && (
                <button className="btn btn-primary" style={{ fontSize: 10, padding: '3px 8px', marginTop: 6 }}
                        onClick={() => onSendToMap?.({ lat: sel.target.position.lat, lon: sel.target.position.lon, label: `${sel.target.label}: ${sel.target.value}`, method_id: sel.target.position.method, method_name: `target/${sel.target.kind}`, cep_m: sel.target.position.cep_m, raw: sel.target })}>
                  <Send size={11} /> Send to map
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
