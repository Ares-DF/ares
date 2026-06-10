// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

/**
 * Network-analysis derivation for the Network tab.
 *
 * The targets tracker stores every decoded identifier (IMSI, MAC, BSSID,
 * DMR RID, UAS serial, …) keyed by (kind, value). This module turns that flat
 * list into *networks*: it groups selectors into the radio network they belong
 * to (a cell, a Wi-Fi BSS, a PTT talk-group, a UAS operator …) and derives the
 * member→hub edges an analyst-notebook graph needs. Pure functions, no I/O —
 * the panel feeds it the array from listTargets().
 */

// ── Network domains ──────────────────────────────────────────────────────────
// Each domain bundles one or more tracker "families". `selectorKinds` are the
// per-device identifiers; `hubKinds` are identifiers that are themselves a
// network hub (a cell, an access point); `hubKeys` are the metadata fields on a
// member that name its hub, in priority order.
export const DOMAINS = {
  cellular: {
    label: 'Cellular', short: 'Cell', color: '#22d3ee',
    families: ['cellular', 'cellular_infra'],
    hubKinds: ['gsm_cell', 'lte_cell', 'nr_cell', 'umts_cell'],
    hubKeys: ['cell_id', 'ci'],
    // Members carry mcc/mnc/(tac|lac)/(cell_id|ci); rebuild the same composite the
    // cell hub is keyed by ("mcc-mnc-area-ci") so they attach to the right cell.
    hubValueOf: (m) => {
      if (m?.mcc != null && m?.mnc != null) {
        const area = m.tac ?? m.lac ?? '?'
        const ci = m.cell_id ?? m.ci ?? '?'
        return `${m.mcc}-${m.mnc}-${area}-${ci}`
      }
      return m?.cell_id ?? m?.ci ?? null
    },
    hubName: (m) => cellName(m),
    blurb: 'Subscribers (IMSI/TMSI/IMEI/RNTI/GUTI) grouped under the cell (PLMN · LAC/TAC · CI) they were seen on.',
  },
  wifi: {
    label: 'Wi-Fi', short: 'Wi-Fi', color: '#a78bfa',
    families: ['wifi'],
    hubKinds: ['bssid', 'ssid'],
    hubKeys: ['bssid'],
    hubValueOf: (m) => m?.bssid || null,
    hubName: (m) => m.ssid || m.bssid || null,
    blurb: 'Stations (client MACs) grouped under the BSSID / SSID they probed or associated with.',
  },
  ble: {
    label: 'Bluetooth LE', short: 'BLE', color: '#60a5fa',
    families: ['ble'],
    hubKinds: [],
    hubKeys: ['name', 'company'],
    hubName: (m) => m.name || m.company || null,
    blurb: 'BLE advertisers grouped by device name / company identifier when present.',
  },
  ptt: {
    label: 'PTT / LMR', short: 'PTT', color: '#f59e0b',
    families: ['ptt'],
    hubKinds: [],
    hubKeys: ['talkgroup', 'tg', 'tgid'],
    hubName: (m) => (m.talkgroup ?? m.tg ?? m.tgid) != null ? `TG ${m.talkgroup ?? m.tg ?? m.tgid}` : null,
    blurb: 'Radio IDs (DMR/P25/NXDN/TETRA) grouped by the talk-group they keyed up on.',
  },
  uas: {
    label: 'UAS / Drone', short: 'UAS', color: '#34d399',
    families: ['uas'],
    hubKinds: ['uas_op'],
    hubKeys: ['uas_op', 'operator_id', 'op_id'],
    hubName: (m) => m.uas_op || m.operator_id || m.op_id || null,
    blurb: 'Drone serials (Remote ID) grouped under their operator ID.',
  },
  aviation: {
    label: 'Aviation (ADS-B)', short: 'Air', color: '#f472b6',
    families: ['aviation'],
    hubKinds: [], hubKeys: ['squawk', 'flight'],
    hubName: (m) => m.flight || (m.squawk != null ? `Squawk ${m.squawk}` : null),
    blurb: 'ICAO addresses / callsigns from ADS-B.',
  },
  maritime: {
    label: 'Maritime (AIS)', short: 'Sea', color: '#2dd4bf',
    families: ['maritime'],
    hubKinds: [], hubKeys: ['ship_name'],
    hubName: (m) => m.ship_name || null,
    blurb: 'AIS MMSIs.',
  },
  other: {
    label: 'Other', short: 'Other', color: '#8b949e',
    families: ['other'],
    hubKinds: [], hubKeys: [],
    hubName: () => null,
    blurb: 'Identifiers without a known network family.',
  },
}

export const DOMAIN_ORDER = ['cellular', 'wifi', 'ble', 'ptt', 'uas', 'aviation', 'maritime', 'other']

const FAMILY_TO_DOMAIN = (() => {
  const m = {}
  for (const id of DOMAIN_ORDER) for (const f of DOMAINS[id].families) m[f] = id
  return m
})()

export function domainOf(target) {
  return FAMILY_TO_DOMAIN[target.family] || 'other'
}

function cellName(m) {
  if (!m) return null
  const plmn = (m.mcc != null && m.mnc != null) ? `${m.mcc}-${m.mnc}` : null
  const area = m.tac != null ? `TAC ${m.tac}` : (m.lac != null ? `LAC ${m.lac}` : null)
  const ci = m.cell_id ?? m.ci
  const tail = ci != null ? `CI ${ci}` : null
  const parts = [plmn, area, tail].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

const firstKey = (meta, keys) => {
  for (const k of keys) {
    const v = meta?.[k]
    if (v != null && v !== '') return String(v)
  }
  return null
}

/** The value of the hub a member belongs to — composite cell id, BSSID, etc. */
const hubValueOf = (cfg, meta) =>
  (cfg.hubValueOf ? cfg.hubValueOf(meta) : null) ?? firstKey(meta, cfg.hubKeys || [])

/**
 * Group a flat target list into networks.
 *
 * Returns:
 *   nodes   — every target, annotated with { domain, isHub, networkKey }
 *   networks — [{ key, domain, label, hubValue, hub, members[], all[], lastSeen, count }]
 *   edges   — [{ from: memberKey, to: hubKey, domain }] for the notebook graph
 *
 * `keyOf` produces a stable id used by both the table and the graph.
 */
export const keyOf = (t) => `${t.kind}/${t.value}`

export function deriveNetworks(targets) {
  const nodes = targets.map((t) => {
    const domain = domainOf(t)
    const cfg = DOMAINS[domain]
    const isHub = cfg.hubKinds.includes(t.kind)
    return { ...t, domain, isHub, _key: keyOf(t) }
  })

  // Index hubs by domain+value so members can attach to the real hub target.
  const hubIndex = new Map()  // `${domain}:${value}` -> node
  for (const n of nodes) if (n.isHub) hubIndex.set(`${n.domain}:${n.value}`, n)

  const networks = new Map()
  const ensure = (domain, hubValue, hubLabel) => {
    const key = `${domain}:${hubValue ?? '∅'}`
    if (!networks.has(key)) {
      networks.set(key, {
        key, domain, hubValue,
        label: hubLabel || (hubValue ? hubValue : `Unaffiliated ${DOMAINS[domain].short}`),
        hub: hubIndex.get(`${domain}:${hubValue}`) || null,
        members: [], all: [], lastSeen: 0,
      })
    }
    return networks.get(key)
  }

  const edges = []
  for (const n of nodes) {
    const cfg = DOMAINS[n.domain]
    if (n.isHub) {
      const net = ensure(n.domain, n.value, cfg.hubName(n.metadata) || n.value)
      net.hub = n
      net.all.push(n)
    } else {
      const hubValue = hubValueOf(cfg, n.metadata)
      const hubLabel = cfg.hubName(n.metadata)
      const net = ensure(n.domain, hubValue, hubLabel)
      net.members.push(n)
      net.all.push(n)
      if (hubValue) edges.push({ from: n._key, to: `${n.domain}:${hubValue}`, domain: n.domain })
    }
    const nk = `${n.domain}:${n.isHub ? n.value : (hubValueOf(cfg, n.metadata) ?? '∅')}`
    const net = networks.get(nk)
    if (net) net.lastSeen = Math.max(net.lastSeen, n.last_seen_t || 0)
  }

  const list = [...networks.values()].map((net) => ({ ...net, count: net.all.length }))
  list.sort((a, b) => (b.lastSeen || 0) - (a.lastSeen || 0))
  return { nodes, networks: list, edges, hubIndex }
}

/** Domain → count summary for the filter chips. */
export function domainCounts(nodes) {
  const c = {}
  for (const n of nodes) c[n.domain] = (c[n.domain] || 0) + 1
  return c
}

// ── Table columns ─────────────────────────────────────────────────────────────
// Base columns are always available; metadata columns are discovered from the
// data so the table is as comprehensive as the capture allows.
export const BASE_COLUMNS = [
  { id: 'domain',   label: 'Network',    simple: true,  get: (t) => DOMAINS[t.domain].label },
  { id: 'label',    label: 'Selector',   simple: true,  get: (t) => t.label },
  { id: 'value',    label: 'Identifier', simple: true,  mono: true, get: (t) => t.value },
  { id: 'network',  label: 'Member of',  simple: true,  get: (t, ctx) => ctx?.netLabelByKey?.[t._key] || '—' },
  { id: 'peak',     label: 'Peak RSSI',  simple: true,  get: (t) => t.peak_rssi_dbm != null ? `${t.peak_rssi_dbm.toFixed(1)} dBm` : '—' },
  { id: 'nobs',     label: 'N obs',      simple: true,  get: (t) => t.n_obs },
  { id: 'last',     label: 'Last seen',  simple: true,  get: (t) => t.last_seen_t ? new Date(t.last_seen_t * 1000).toLocaleTimeString() : '—' },
  { id: 'first',    label: 'First seen', simple: false, get: (t) => t.first_seen_t ? new Date(t.first_seen_t * 1000).toLocaleString() : '—' },
  { id: 'range',    label: 'Range',      simple: false, get: (t) => t.range_m_estimate != null ? (t.range_m_estimate < 1000 ? `${t.range_m_estimate.toFixed(0)} m` : `${(t.range_m_estimate / 1000).toFixed(2)} km`) : '—' },
  { id: 'position', label: 'Position',   simple: false, get: (t) => t.position ? `${t.position.lat.toFixed(4)}, ${t.position.lon.toFixed(4)}` : '—' },
]

const HIDDEN_META = new Set(['source_line', 'event_kind', 'raw', 'argv'])

/** Discover metadata keys present across the (filtered) targets, sorted. */
export function discoverMetaColumns(targets) {
  const keys = new Set()
  for (const t of targets) for (const k of Object.keys(t.metadata || {})) {
    if (!HIDDEN_META.has(k)) keys.add(k)
  }
  return [...keys].sort().map((k) => ({
    id: `meta:${k}`, label: k, meta: true, simple: false,
    get: (t) => { const v = t.metadata?.[k]; return v == null ? '—' : String(v) },
  }))
}

/** CSV serialiser for the current rows + visible columns. */
export function toCSV(rows, columns, ctx) {
  const esc = (s) => {
    const v = s == null ? '' : String(s)
    return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v
  }
  const header = columns.map((c) => esc(c.label)).join(',')
  const body = rows.map((r) => columns.map((c) => esc(c.get(r, ctx))).join(',')).join('\n')
  return `${header}\n${body}`
}
