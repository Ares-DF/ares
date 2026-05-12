import ResultsPanel from '../Results/ResultsPanel'
import DfPanel from './DfPanel'
import ChatPanel from './ChatPanel'
import TerrainTab from './TerrainTab'
import LayerManagerPanel from '../Map/LayerManagerPanel'
import DecibelCalculator from '../Tools/DecibelCalculator'
import ThreeDView from '../Charts/ThreeDView'
import EmitterSummary from './EmitterSummary'
import SavedLocations from './SavedLocations'
import SpaceWxPanel from './SpaceWxPanel'

const COL = { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }
const HIDDEN = { flex: 1, minHeight: 0, overflow: 'hidden' }
const SCROLL = { flex: 1, minHeight: 0, overflowY: 'auto' }

/**
 * The bottom-panel content area — dispatches on the active tab and renders it
 * (most tabs are their own components; this is the dispatch + the wrapper divs).
 * `terrain` bundles the useStandaloneTerrainProfile outputs + the P2P-sim profile.
 */
export default function BottomPanelContent({
  active,
  metadata, p2pResult, warnings, activeTab,            // results / budget
  onChatLocate,                                        // chat
  terrain,                                             // terrain tab
  ul, openFileDialog,                                  // layers
  terrainGrid, terrainGridLoading, coverageGeoJSON, buildingGeoJSON,   // 3-D view
  txActive, txLabel, extraTxList, lobs, lobGroups, onRemoveLoB, onEditLoB,   // emitter summary
  savedLocations, onSavedFlyTo, onSavedRemove,         // saved locations
  tx, rx, propagation, spaceWeather,                   // shared
}) {
  return (
    <div style={{ flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {active === 'results' && <div style={SCROLL}><ResultsPanel metadata={metadata} p2pResult={p2pResult} warnings={warnings} spaceWeather={spaceWeather} activeTab={activeTab} /></div>}
      {active === 'budget' && <div style={SCROLL}><ResultsPanel metadata={metadata} p2pResult={p2pResult} warnings={warnings} spaceWeather={spaceWeather} activeTab={activeTab} showBudget /></div>}
      {active === 'df' && <div style={HIDDEN}><DfPanel /></div>}
      {active === 'chat' && <div style={HIDDEN}><ChatPanel onLocate={onChatLocate} /></div>}
      {active === 'terrain' && (
        <TerrainTab
          terrainLineMode={terrain.terrainLineMode}
          standaloneProfile={terrain.standaloneProfile}
          standaloneProfileLoading={terrain.standaloneProfileLoading}
          standaloneProfileError={terrain.standaloneProfileError}
          onToggleLineMode={terrain.onToggleLineMode}
          onClearStandalone={terrain.onClearStandalone}
          terrainProfile={terrain.terrainProfile}
          tx={tx}
          rx={rx}
          propagationModel={propagation.model}
          waveType={propagation.wave_type}
        />
      )}
      {active === 'layers' && <div style={COL}><LayerManagerPanel ul={ul} openFileDialog={openFileDialog} /></div>}
      {active === 'dbcalc' && <div style={{ ...HIDDEN, display: 'flex', flexDirection: 'column' }}><DecibelCalculator embedded /></div>}
      {active === '3d' && (
        <div style={COL}>
          <ThreeDView terrainGrid={terrainGrid} loading={terrainGridLoading} coverageGeoJSON={coverageGeoJSON} buildingGeoJSON={buildingGeoJSON} tx={tx} minSignalDbm={propagation.min_signal_dbm} />
        </div>
      )}
      {active === 'emitters' && (
        <EmitterSummary txActive={txActive} txLabel={txLabel} tx={tx} extraTxList={extraTxList} lobs={lobs} lobGroups={lobGroups} onRemoveLoB={onRemoveLoB} onEditLoB={onEditLoB} />
      )}
      {active === 'savedlocs' && <SavedLocations locations={savedLocations} onFlyTo={onSavedFlyTo} onRemove={onSavedRemove} />}
      {active === 'spacewx' && spaceWeather && <SpaceWxPanel spaceWeather={spaceWeather} />}
    </div>
  )
}
