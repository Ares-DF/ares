// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Send } from 'lucide-react'
import { DOMAINS } from '../../utils/network'

const th = { textAlign: 'left', fontSize: 10, color: '#8b949e', fontWeight: 600, padding: '5px 8px', whiteSpace: 'nowrap', position: 'sticky', top: 0, background: '#0d1117', cursor: 'pointer', userSelect: 'none' }
const td = { fontSize: 11, color: '#c9d1d9', padding: '4px 8px', borderTop: '1px solid #161b22', whiteSpace: 'nowrap' }
const mono = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }

/**
 * Excel-sheet-style view: a sortable, dense grid of selectors with whatever
 * columns the operator has turned on (base fields + discovered metadata).
 * Click a row to send its fix to the map.
 */
export default function NetworkTable({ rows, columns, ctx, onSendToMap }) {
  const [sort, setSort] = useState({ id: 'last', dir: -1 })

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.id === sort.id) || columns[0]
    if (!col) return rows
    const arr = [...rows]
    arr.sort((a, b) => {
      const va = col.get(a, ctx), vb = col.get(b, ctx)
      const na = Number(String(va).replace(/[^0-9.\-]/g, '')), nb = Number(String(vb).replace(/[^0-9.\-]/g, ''))
      const bothNum = !Number.isNaN(na) && !Number.isNaN(nb) && va !== '—' && vb !== '—'
      const cmp = bothNum ? na - nb : String(va).localeCompare(String(vb))
      return cmp * sort.dir
    })
    return arr
  }, [rows, columns, ctx, sort])

  const clickHead = (id) => setSort((s) => s.id === id ? { id, dir: -s.dir } : { id, dir: 1 })

  if (!rows.length) {
    return <div style={{ padding: 16, textAlign: 'center', color: '#6e7681', fontSize: 12 }}>No selectors match the current filters.</div>
  }
  return (
    <div style={{ overflow: 'auto', maxHeight: '100%', border: '1px solid #21262d', borderRadius: 6 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.id} style={th} onClick={() => clickHead(c.id)}>
                {c.label}{sort.id === c.id && (sort.dir > 0 ? <ArrowUp size={9} style={{ marginLeft: 3 }} /> : <ArrowDown size={9} style={{ marginLeft: 3 }} />)}
              </th>
            ))}
            <th style={{ ...th, cursor: 'default' }}></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((t) => (
            <tr key={t._key} style={{ background: 'transparent' }}>
              {columns.map((c) => {
                const v = c.get(t, ctx)
                const style = { ...td, ...(c.mono ? mono : {}) }
                if (c.id === 'domain') return <td key={c.id} style={{ ...style, color: DOMAINS[t.domain].color }}>{v}</td>
                if (c.id === 'peak') return <td key={c.id} style={{ ...style, color: '#f59e0b' }}>{v}</td>
                return <td key={c.id} style={style}>{v}</td>
              })}
              <td style={td}>
                {t.position && (
                  <button className="btn btn-ghost" style={{ fontSize: 9, padding: '2px 6px' }}
                          title="Send fix to map"
                          onClick={() => onSendToMap?.({
                            lat: t.position.lat, lon: t.position.lon,
                            label: `${t.label}: ${t.value}`,
                            method_id: t.position.method, method_name: `target/${t.kind}`,
                            cep_m: t.position.cep_m, raw: t,
                          })}>
                    <Send size={10} />
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
