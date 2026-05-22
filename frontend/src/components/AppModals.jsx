import HelpPanel from './Common/HelpPanel'
import AtakServerPanel from './Tools/AtakServerPanel'
import SdrPanel from './Tools/SdrPanel'
import ArchivePanel from './Tools/ArchivePanel'

/** The top-level modal dialogs: Help · ATAK / Server console · SDR console · Archive. */
export default function AppModals({
  helpOpen, onCloseHelp,
  atakPanelOpen, onCloseAtak, mapCenter,
  sdrPanelOpen, onCloseSdr, sdr, sdrHidden, onSdrPickLocation, sdrMapFeatures,
  archiveOpen, onCloseArchive, currentGeojson, currentParams, onArchiveLoad,
}) {
  return (
    <>
      {helpOpen && <HelpPanel onClose={onCloseHelp} />}

      {atakPanelOpen && (
        <AtakServerPanel onClose={onCloseAtak} mapCenter={mapCenter} />
      )}

      {sdrPanelOpen && (
        <SdrPanel
          onClose={onCloseSdr}
          mapCenter={mapCenter}
          sdr={sdr}
          hidden={sdrHidden}
          onPickLocation={onSdrPickLocation}
          mapFeatures={sdrMapFeatures}
        />
      )}

      {archiveOpen && (
        <ArchivePanel
          currentGeojson={currentGeojson}
          currentParams={currentParams}
          onLoad={onArchiveLoad}
          onClose={onCloseArchive}
        />
      )}
    </>
  )
}
