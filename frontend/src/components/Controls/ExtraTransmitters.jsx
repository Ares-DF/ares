import { X, Plus } from 'lucide-react'
import EditableLabel from '../Common/EditableLabel'
import TransmitterPanel from './TransmitterPanel'
import PropagationPanel from './PropagationPanel'
import AntennaPanel from './AntennaPanel'
import AtmospherePanel from './AtmospherePanel'

/**
 * The additional transmitters in the sidebar — each a coloured, renamable, removable
 * block of TX / propagation / antenna / atmosphere panels (falling back to the primary
 * TX's propagation & atmosphere when the extra one hasn't overridden them) — plus the
 * "Add Transmitter" button. `resolveModelFast` resolves the "model = auto" choice per TX.
 */
export default function ExtraTransmitters({
  extraTxList, coordSystem, distUnit, rx, setRx, defaultPropagation, defaultAtmosphere, resolveModelFast,
  onRename, onRemove, onUpdateTx, onUpdatePropagation, onUpdateAtmosphere, onAdd,
  // {id, ts} signal from the Emitter Summary's Edit button — drives the
  // matching entry's TransmitterPanel to expand + scroll into view.
  expandSignalForId = null,
}) {
  return (
    <>
      {extraTxList.map((entry) => (
        <div key={entry.id} style={{ borderTop: '1px solid #21262d', marginTop: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', padding: '6px 12px 0', gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: entry.color, flexShrink: 0 }} />
            <EditableLabel value={entry.label} onChange={label => onRename(entry.id, label)} />
            <button className="btn btn-ghost" style={{ padding: '2px 6px', color: '#ef4444' }} onClick={() => onRemove(entry.id)}>
              <X size={12} />
            </button>
          </div>
          <TransmitterPanel
            tx={entry.tx}
            setTx={(newTx) => onUpdateTx(entry.id, newTx)}
            coordSystem={coordSystem}
            distUnit={distUnit}
            expandSignal={expandSignalForId?.id === entry.id ? expandSignalForId.ts : 0}
          />
          <PropagationPanel
            propagation={entry.propagation ?? defaultPropagation}
            setPropagation={(upd) => onUpdatePropagation(entry.id, upd)}
            resolvedModel={resolveModelFast(entry.tx, entry.propagation ?? defaultPropagation)}
            distUnit={distUnit}
          />
          <AntennaPanel
            tx={entry.tx}
            setTx={(newTx) => onUpdateTx(entry.id, newTx)}
            rx={rx}
            setRx={setRx}
            txFrequencyHz={entry.tx.frequency_hz}
          />
          <AtmospherePanel
            atmosphere={entry.atmosphere ?? defaultAtmosphere}
            setAtmosphere={(upd) => onUpdateAtmosphere(entry.id, upd)}
            txLat={entry.tx.lat}
            txLon={entry.tx.lon}
          />
        </div>
      ))}

      <div style={{ padding: '4px 12px' }}>
        <button className="btn btn-secondary" style={{ width: '100%', gap: 6, fontSize: 12 }} onClick={onAdd}>
          <Plus size={13} /> Add Transmitter
        </button>
      </div>
    </>
  )
}
