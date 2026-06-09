// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2026 Ares

import { AlertTriangle, X } from 'lucide-react'
import ErrorBoundary from './Common/ErrorBoundary'
import HelpPanel from './Common/HelpPanel'
import AtakServerPanel from './Tools/AtakServerPanel'
import SdrPanel from './Tools/SdrPanel'

/**
 * A dismissible modal-shaped fallback for a crashed panel. Without this a render
 * error in any modal escapes to the app root (the modals live outside the main
 * ErrorBoundary) and whites-out the entire app. Now a panel crash shows the
 * error and a working Close button instead.
 */
function modalErrorFallback(onClose, title) {
  return (err, reset) => (
    <div onClick={() => { reset(); onClose?.() }}
         style={{ position: 'fixed', inset: 0, background: 'rgba(1,4,9,0.6)', zIndex: 2000,
                  display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 'min(520px, 92vw)',
        background: '#0d1117', border: '1px solid #f85149', borderRadius: 8,
        boxShadow: '0 10px 40px rgba(0,0,0,0.5)', padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <AlertTriangle size={16} color="#f0883e" />
          <div style={{ fontSize: 14, fontWeight: 700, color: '#e6edf3', flex: 1 }}>{title} hit an error</div>
          <button className="btn btn-ghost" style={{ padding: '4px 8px' }}
                  onClick={() => { reset(); onClose?.() }}><X size={14} /></button>
        </div>
        <div style={{ fontSize: 12, color: '#8b949e', wordBreak: 'break-word', marginBottom: 12 }}>
          {String(err?.message || err)}
        </div>
        <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 12px' }}
                onClick={() => { reset(); onClose?.() }}>Close</button>
      </div>
    </div>
  )
}

/** The top-level modal dialogs: Help · ATAK / Server console · SDR console. */
export default function AppModals({
  helpOpen, onCloseHelp,
  atakPanelOpen, onCloseAtak, mapCenter,
  sdrPanelOpen, onCloseSdr, sdr, sdrHidden, onSdrPickLocation, sdrMapFeatures,
}) {
  return (
    <>
      {helpOpen && (
        <ErrorBoundary label="Help" fallback={modalErrorFallback(onCloseHelp, 'Help')}>
          <HelpPanel onClose={onCloseHelp} />
        </ErrorBoundary>
      )}

      {atakPanelOpen && (
        <ErrorBoundary label="ATAK / Server" fallback={modalErrorFallback(onCloseAtak, 'ATAK / Server')}>
          <AtakServerPanel onClose={onCloseAtak} mapCenter={mapCenter} />
        </ErrorBoundary>
      )}

      {sdrPanelOpen && (
        <ErrorBoundary label="SDR console" fallback={modalErrorFallback(onCloseSdr, 'SDR console')}>
          <SdrPanel
            onClose={onCloseSdr}
            mapCenter={mapCenter}
            sdr={sdr}
            hidden={sdrHidden}
            onPickLocation={onSdrPickLocation}
            mapFeatures={sdrMapFeatures}
          />
        </ErrorBoundary>
      )}
    </>
  )
}
